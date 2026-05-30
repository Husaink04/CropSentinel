#!/usr/bin/env bash
set -euo pipefail

APP_DIR="/opt/CropSentinel"
BRANCH="${1:-main}"
LOG_FILE="/var/log/cropsentinel-update.log"

mkdir -p "$(dirname "$LOG_FILE")"
touch "$LOG_FILE"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

if [ ! -d "$APP_DIR/.git" ]; then
  log "App folder not found at $APP_DIR"
  exit 1
fi

cd "$APP_DIR"

log "Checking for updates on branch $BRANCH"

git fetch origin "$BRANCH" >> "$LOG_FILE" 2>&1

LOCAL_COMMIT="$(git rev-parse HEAD)"
REMOTE_COMMIT="$(git rev-parse "origin/$BRANCH")"

if [ "$LOCAL_COMMIT" = "$REMOTE_COMMIT" ]; then
  log "No update found"
  exit 0
fi

log "New version found. Pulling latest code"
git pull --ff-only origin "$BRANCH" >> "$LOG_FILE" 2>&1

log "Rebuilding and restarting containers"
docker compose up --build -d >> "$LOG_FILE" 2>&1

log "Cleaning old images"
docker image prune -f >> "$LOG_FILE" 2>&1

log "Update complete"
