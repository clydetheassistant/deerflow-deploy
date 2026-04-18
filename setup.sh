#!/bin/bash
# DeerFlow setup script for mac-server.local
# Run this on the mac-server as root/sudo
# MAN-152

set -e

DEER_FLOW_REPO_ROOT=/opt/deerflow/app
DEER_FLOW_CONFIG_DIR=/opt/deerflow/config
DEER_FLOW_HOME=/opt/deerflow/data

echo "=== DeerFlow Setup ==="

# 1. Create directories
mkdir -p "$DEER_FLOW_REPO_ROOT" "$DEER_FLOW_CONFIG_DIR" "$DEER_FLOW_HOME"

# 2. Clone DeerFlow
if [ ! -d "$DEER_FLOW_REPO_ROOT/.git" ]; then
  git clone https://github.com/bytedance/deer-flow.git "$DEER_FLOW_REPO_ROOT"
else
  cd "$DEER_FLOW_REPO_ROOT" && git pull
fi

# 3. Copy config files (run from this deploy repo)
cp config.yaml "$DEER_FLOW_CONFIG_DIR/config.yaml"
cp extensions_config.json "$DEER_FLOW_CONFIG_DIR/extensions_config.json"

echo ""
echo "=== Next steps ==="
echo "1. Go to Dokploy → Projects → agentopia → Add Compose service"
echo "2. Name: deerflow"
echo "3. Compose file: use this repo (clydetheassistant/deerflow-deploy) or paste docker-compose.yml"
echo "4. Set env vars in Dokploy (see .env.example)"
echo "5. Add Caddy vhost for deerflow.mac-server.local → deer-flow-nginx:2026"
echo ""
echo "Done!"
