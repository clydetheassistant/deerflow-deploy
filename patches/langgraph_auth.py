"""LangGraph compatibility auth handler.

Local patch (deerflow-deploy) on top of the upstream file at
backend/app/gateway/langgraph_auth.py in v2.1.0-rc0: ADDITIONALLY accept the
gateway's internal auth header (X-DeerFlow-Internal-Token +
X-DeerFlow-Owner-User-Id) so trusted internal callers inside the compose
network (the channel manager calling langgraph directly from the gateway
container) authenticate as the real chat owner instead of 401ing because they
have no JWT session cookie. Upstream v2.1.0-rc0 only recognises cookie JWTs
here; the channel manager still sends cookie-less SDK calls, which breaks
every IM-driven thread (Telegram was returning "An internal error occurred").
"""

import os
import secrets

from langgraph_sdk import Auth

from app.gateway.auth.errors import TokenError
from app.gateway.auth.jwt import decode_token
from app.gateway.auth_disabled import AUTH_DISABLED_USER_ID, is_auth_disabled
from app.gateway.deps import get_local_provider
from app.gateway.internal_auth import (
    INTERNAL_AUTH_HEADER_NAME,
    INTERNAL_OWNER_USER_ID_HEADER_NAME,
    is_valid_internal_auth_token,
)
from deerflow.config.paths import make_safe_user_id

auth = Auth()

_STUDIO_USER_TYPE = getattr(Auth.types, "StudioUser", None)
_CSRF_METHODS = frozenset({"POST", "PUT", "DELETE", "PATCH"})


def _check_csrf(request) -> None:
    method = getattr(request, "method", "") or ""
    if method.upper() not in _CSRF_METHODS:
        return

    if is_auth_disabled():
        return

    # Trusted internal callers already prove their identity via the shared
    # DEER_FLOW_INTERNAL_AUTH_TOKEN header; skipping the browser CSRF double-
    # submit for them matches how the Gateway's own CSRFMiddleware treats
    # internal callers.
    internal_token = request.headers.get(INTERNAL_AUTH_HEADER_NAME)
    if internal_token and is_valid_internal_auth_token(internal_token):
        return

    cookie_token = request.cookies.get("csrf_token")
    header_token = request.headers.get("x-csrf-token")

    if not cookie_token or not header_token:
        raise Auth.exceptions.HTTPException(
            status_code=403,
            detail="CSRF token missing. Include X-CSRF-Token header.",
        )

    if not secrets.compare_digest(cookie_token, header_token):
        raise Auth.exceptions.HTTPException(
            status_code=403,
            detail="CSRF token mismatch.",
        )


@auth.authenticate
async def authenticate(request):
    _check_csrf(request)

    # Trusted internal caller path. The gateway's channel manager calls
    # langgraph with the shared internal token and (optionally) the real
    # owner user id. Return a dict identity that carries the owner id *and*
    # an "internal" permission marker so @auth.on can recognise us and skip
    # the user_id filter — important for pre-v2.1.0-rc0 threads that have
    # no user_id in their stored metadata (filter would 404 them otherwise)
    # and for any cross-user channel ops the trusted caller performs.
    internal_token = request.headers.get(INTERNAL_AUTH_HEADER_NAME)
    if internal_token and is_valid_internal_auth_token(internal_token):
        owner_user_id = request.headers.get(INTERNAL_OWNER_USER_ID_HEADER_NAME)
        if owner_user_id:
            owner_user_id = owner_user_id.strip()
        identity = make_safe_user_id(owner_user_id) if owner_user_id else AUTH_DISABLED_USER_ID
        return {
            "identity": identity,
            "is_authenticated": True,
            "permissions": ["internal"],
        }

    if is_auth_disabled():
        return AUTH_DISABLED_USER_ID

    token = request.cookies.get("access_token")
    if not token:
        raise Auth.exceptions.HTTPException(
            status_code=401,
            detail="Not authenticated",
        )

    payload = decode_token(token)
    if isinstance(payload, TokenError):
        raise Auth.exceptions.HTTPException(
            status_code=401,
            detail="Invalid token",
        )

    user = await get_local_provider().get_user(payload.sub)
    if user is None:
        raise Auth.exceptions.HTTPException(
            status_code=401,
            detail="User not found",
        )
    if user.token_version != payload.ver:
        raise Auth.exceptions.HTTPException(
            status_code=401,
            detail="Token revoked (password changed)",
        )

    return payload.sub


@auth.on
async def add_owner_filter(ctx: Auth.types.AuthContext, value: dict):
    # Trusted internal callers (gateway channel manager) have already proved
    # identity via DEER_FLOW_INTERNAL_AUTH_TOKEN. Skip the user_id filter so
    # they can access threads created in older DeerFlow versions that have no
    # user_id in metadata, and so cross-user channel ops remain possible.
    # Still stamp metadata.user_id on writes so new rows get the owner.
    if "internal" in (getattr(ctx.user, "permissions", None) or []):
        metadata = value.setdefault("metadata", {})
        metadata["user_id"] = ctx.user.identity
        if ctx.resource == "assistants" and ctx.action in {"create", "update"}:
            metadata["created_by"] = "user"
        return None

    if _STUDIO_USER_TYPE is not None and isinstance(ctx.user, _STUDIO_USER_TYPE) and ctx.resource == "assistants" and ctx.action in {"read", "search"}:
        return {
            "$or": [
                {"created_by": "system"},
                {"user_id": ctx.user.identity},
            ]
        }

    metadata = value.setdefault("metadata", {})
    metadata["user_id"] = ctx.user.identity
    if ctx.resource == "assistants" and ctx.action in {"create", "update"}:
        metadata["created_by"] = "user"

    return {"user_id": ctx.user.identity}
