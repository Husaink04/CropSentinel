#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/CropSentinel"
BRANCH="${1:-main}"
SCRIPT_PATH="$APP_DIR/tools/server-deploy/update.sh"
CRON_LINE="* * * * * $SCRIPT_PATH $BRANCH >/dev/null 2>&1"

if [ ! -f "$SCRIPT_PATH" ]; then
  echo "Update script not found at $SCRIPT_PATH"
  echo "Make sure the project exists at /opt/CropSentinel"
  exit 1
fi

CURRENT_CRON="$(crontab -l 2>/dev/null || true)"

if echo "$CURRENT_CRON" | grep -F "$SCRIPT_PATH" >/dev/null 2>&1; then
  echo "Auto-update cron job already exists"
  exit 0
fi

{
  echo "$CURRENT_CRON"
  echo "$CRON_LINE"
} | crontab -

echo "Auto-update cron job installed"
echo "The server will check GitHub every minute"
echo "Update log: /var/log/cropsentinel-update.log"
