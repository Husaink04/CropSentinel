#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
VERSION="1.3.0"
DIST_DIR="$SCRIPT_DIR/dist/linux"
PORTAL_INSTALLERS_DIR="$REPO_ROOT/backend/dist/installers"
WORK_DIR="$(mktemp -d)"
PAYLOAD_NAME="cropsentinel-agent-$VERSION-linux-payload.tar.gz"
BUNDLE_NAME="cropsentinel-agent-$VERSION-linux.tar.gz"
BUNDLE_ALIAS_NAME="cropsentinel-agent-linux-$VERSION.tar.gz"
PAYLOAD_PATH="$DIST_DIR/$PAYLOAD_NAME"
BUNDLE_PATH="$DIST_DIR/$BUNDLE_NAME"
BUNDLE_ALIAS_PATH="$DIST_DIR/$BUNDLE_ALIAS_NAME"

cleanup() {
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

log() {
  printf '[linux-build] %s\n' "$1"
}

mkdir -p "$DIST_DIR" "$PORTAL_INSTALLERS_DIR"
rm -f "$DIST_DIR"/cropsentinel-agent-*-linux*.tar.gz
rm -f "$DIST_DIR"/cropsentinel-agent-linux-*.tar.gz
rm -f "$PORTAL_INSTALLERS_DIR"/cropsentinel-agent-*-linux*.tar.gz
rm -f "$PORTAL_INSTALLERS_DIR"/cropsentinel-agent-linux-*.tar.gz

log "Packaging Linux agent payload"
tar \
  --exclude='__pycache__' \
  --exclude='*.pyc' \
  --exclude='.pytest_cache' \
  -czf "$PAYLOAD_PATH" \
  -C "$REPO_ROOT" \
  agent

log "Assembling Linux installer bundle"
cp "$SCRIPT_DIR/linux/install-linux-agent.sh" "$WORK_DIR/"
cp "$SCRIPT_DIR/linux/cropsentinel-agent.service" "$WORK_DIR/"
cp "$SCRIPT_DIR/linux/cropsentinel-watchdog.service" "$WORK_DIR/"
cp "$SCRIPT_DIR/config.env.example" "$WORK_DIR/"
cp "$PAYLOAD_PATH" "$WORK_DIR/"

cat > "$WORK_DIR/README.txt" <<EOF
CropSentinel Linux Agent bundle

Files:
  - install-linux-agent.sh
  - $PAYLOAD_NAME
  - config.env.example
  - cropsentinel-agent.service
  - cropsentinel-watchdog.service

How to install:
  1. Copy config.env.example to config.env and fill in the tenant values, unless the portal already added config.env for you.
  2. Run: sudo bash ./install-linux-agent.sh
  3. The installer copies the agent to /opt/cropsentinel-agent, writes /etc/cropsentinel/config.env, creates systemd services, and starts them.
EOF

chmod 755 "$WORK_DIR/install-linux-agent.sh"
tar -czf "$BUNDLE_PATH" -C "$WORK_DIR" .
cp "$BUNDLE_PATH" "$BUNDLE_ALIAS_PATH"
cp "$BUNDLE_PATH" "$PORTAL_INSTALLERS_DIR/"
cp "$BUNDLE_ALIAS_PATH" "$PORTAL_INSTALLERS_DIR/"

log "Build complete"
printf 'Bundle : %s\n' "$BUNDLE_PATH"
printf 'Alias  : %s\n' "$BUNDLE_ALIAS_PATH"
printf 'Portal : %s\n' "$PORTAL_INSTALLERS_DIR/$BUNDLE_NAME"
