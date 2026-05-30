#!/usr/bin/env bash
set -euo pipefail

APP_NAME="CropSentinel Linux Agent Installer"
INSTALL_ROOT="/opt/cropsentinel-agent"
APP_DIR="$INSTALL_ROOT/app"
VENV_DIR="$INSTALL_ROOT/.venv"
CONFIG_DIR="/etc/cropsentinel"
CONFIG_FILE="$CONFIG_DIR/config.env"
SYSTEMD_DIR="/etc/systemd/system"
AGENT_SERVICE_NAME="cropsentinel-agent.service"
WATCHDOG_SERVICE_NAME="cropsentinel-watchdog.service"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PAYLOAD_ARCHIVE="$(find "$SCRIPT_DIR" -maxdepth 1 -type f -name 'cropsentinel-agent-*-linux-payload.tar.gz' | head -n 1)"
CONFIG_SOURCE="$SCRIPT_DIR/config.env"
CONFIG_EXAMPLE="$SCRIPT_DIR/config.env.example"

log() {
  printf '[%s] %s\n' "$APP_NAME" "$1"
}

fail() {
  printf '[%s] ERROR: %s\n' "$APP_NAME" "$1" >&2
  exit 1
}

require_root() {
  if [[ "${EUID:-$(id -u)}" -ne 0 ]]; then
    fail "Run this installer with sudo or as root."
  fi
}

require_linux() {
  if [[ "$(uname -s)" != "Linux" ]]; then
    fail "This installer only runs on Linux."
  fi
}

require_commands() {
  local missing=()
  for cmd in python3 systemctl tar; do
    command -v "$cmd" >/dev/null 2>&1 || missing+=("$cmd")
  done
  if [[ ${#missing[@]} -gt 0 ]]; then
    fail "Missing required commands: ${missing[*]}"
  fi
}

require_payload() {
  [[ -n "$PAYLOAD_ARCHIVE" && -f "$PAYLOAD_ARCHIVE" ]] || fail "Linux payload archive not found next to install-linux-agent.sh"
}

prepare_config() {
  mkdir -p "$CONFIG_DIR"
  if [[ -f "$CONFIG_SOURCE" ]]; then
    install -m 600 "$CONFIG_SOURCE" "$CONFIG_FILE"
    log "Installed tenant config to $CONFIG_FILE"
  elif [[ -f "$CONFIG_FILE" ]]; then
    log "Keeping existing config at $CONFIG_FILE"
  elif [[ -f "$CONFIG_EXAMPLE" ]]; then
    install -m 600 "$CONFIG_EXAMPLE" "$CONFIG_FILE"
    log "Installed example config to $CONFIG_FILE - update it before production use"
  else
    fail "No config.env or config.env.example was found next to the installer."
  fi
}

install_payload() {
  mkdir -p "$INSTALL_ROOT"
  rm -rf "$APP_DIR"
  mkdir -p "$APP_DIR"
  tar -xzf "$PAYLOAD_ARCHIVE" -C "$APP_DIR" --strip-components=1
}

install_python_deps() {
  python3 -m venv "$VENV_DIR"
  "$VENV_DIR/bin/pip" install --upgrade pip wheel setuptools
  "$VENV_DIR/bin/pip" install -r "$APP_DIR/requirements.txt"
}

render_unit() {
  local template="$1"
  local target="$2"
  sed \
    -e "s|__INSTALL_DIR__|$INSTALL_ROOT|g" \
    -e "s|__CONFIG_FILE__|$CONFIG_FILE|g" \
    "$template" > "$target"
}

install_services() {
  render_unit "$SCRIPT_DIR/cropsentinel-agent.service" "$SYSTEMD_DIR/$AGENT_SERVICE_NAME"
  render_unit "$SCRIPT_DIR/cropsentinel-watchdog.service" "$SYSTEMD_DIR/$WATCHDOG_SERVICE_NAME"
  chmod 644 "$SYSTEMD_DIR/$AGENT_SERVICE_NAME" "$SYSTEMD_DIR/$WATCHDOG_SERVICE_NAME"

  systemctl daemon-reload
  systemctl enable --now "$AGENT_SERVICE_NAME"
  systemctl enable --now "$WATCHDOG_SERVICE_NAME"
}

main() {
  require_linux
  require_root
  require_commands
  require_payload

  log "Installing agent files"
  install_payload

  log "Preparing config"
  prepare_config

  log "Installing Python environment"
  install_python_deps

  log "Registering systemd services"
  install_services

  log "Installation complete"
  systemctl --no-pager --full status "$AGENT_SERVICE_NAME" || true
  systemctl --no-pager --full status "$WATCHDOG_SERVICE_NAME" || true
}

main "$@"
