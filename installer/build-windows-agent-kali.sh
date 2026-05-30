#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
PORTAL_INSTALLERS_DIR="${REPO_ROOT}/backend/dist/installers"
ASSETS_DIR="${SCRIPT_DIR}/assets"
APP_ICON="${ASSETS_DIR}/app.ico"
PAYLOAD_MANIFEST_NAME="payload-manifest.json"

PYTHON_VERSION="${PYTHON_VERSION:-3.11.9}"
PYTHON_INSTALLER="python-${PYTHON_VERSION}-amd64.exe"
PYTHON_URL="${PYTHON_URL:-https://www.python.org/ftp/python/${PYTHON_VERSION}/${PYTHON_INSTALLER}}"

WINEPREFIX="${WINEPREFIX:-$HOME/.wine-cropsentinel}"
WINEARCH="${WINEARCH:-win64}"
RUNTIME_DIR="${RUNTIME_DIR:-/tmp/cropsentinel-runtime}"
PYTHON_EXE='C:\Program Files\Python311\python.exe'
WINDOWS_REPO_ROOT=""
WINDOWS_INSTALLER_DIR=""
WINDOWS_ASSETS_DIR=""
WINDOWS_PORTAL_INSTALLERS_DIR=""

VERSION="$(
  python3 - <<'PY' "${SCRIPT_DIR}/build.ps1"
from pathlib import Path
import re
import sys

text = Path(sys.argv[1]).read_text(encoding="utf-8")
match = re.search(r"\$Version\s*=\s*'([^']+)'", text)
if not match:
    raise SystemExit("Could not parse version from build.ps1")
print(match.group(1))
PY
)"
INSTALLER_BASENAME="cropsentinel-agent-${VERSION}-setup"
INSTALLER_NAME="${INSTALLER_BASENAME}.exe"
BUNDLE_NAME="cropsentinel-agent-${VERSION}-windows.zip"

log() {
  printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing command: $1" >&2
    exit 1
  fi
}

wine_run() {
  mkdir -p "${RUNTIME_DIR}"
  chmod 700 "${RUNTIME_DIR}"
  XDG_RUNTIME_DIR="${RUNTIME_DIR}" xvfb-run -a "$@"
}

wine_path() {
  local input="$1"
  if command -v winepath >/dev/null 2>&1; then
    winepath -w "${input}"
  else
    wine_run wine winepath -w "${input}"
  fi
}

ensure_linux_deps() {
  log "Checking Linux prerequisites"
  local missing=()
  for cmd in sudo curl wine xvfb-run python3; do
    if ! command -v "${cmd}" >/dev/null 2>&1; then
      missing+=("${cmd}")
    fi
  done
  if (( ${#missing[@]} > 0 )); then
    echo "Missing commands: ${missing[*]}" >&2
    echo "Install them first, for example:" >&2
    echo "  sudo dpkg --add-architecture i386 && sudo apt update && sudo apt install -y wine64 wine32 winbind cabextract unzip curl xvfb python3" >&2
    exit 1
  fi
}

bootstrap_wine() {
  log "Bootstrapping Wine prefix at ${WINEPREFIX}"
  export WINEPREFIX WINEARCH
  wine_run wineboot -u
}

resolve_windows_paths() {
  log "Resolving Windows-style paths for Wine"
  WINDOWS_REPO_ROOT="$(wine_path "${REPO_ROOT}")"
  WINDOWS_INSTALLER_DIR="$(wine_path "${SCRIPT_DIR}")"
  WINDOWS_ASSETS_DIR="$(wine_path "${ASSETS_DIR}")"
  WINDOWS_PORTAL_INSTALLERS_DIR="$(wine_path "${PORTAL_INSTALLERS_DIR}")"
}

install_windows_python() {
  local tmp_installer="/tmp/${PYTHON_INSTALLER}"

  if wine "${PYTHON_EXE}" --version >/dev/null 2>&1; then
    log "Windows Python already installed"
    return
  fi

  log "Downloading Windows Python ${PYTHON_VERSION}"
  curl -L "${PYTHON_URL}" -o "${tmp_installer}"

  log "Installing Windows Python under Wine"
  wine_run wine "${tmp_installer}" /quiet InstallAllUsers=1 PrependPath=1 Include_test=0
}

install_python_deps() {
  local requirements_win="${WINDOWS_REPO_ROOT}\\agent\\requirements.txt"

  log "Upgrading pip"
  wine_run wine "${PYTHON_EXE}" -m pip install --upgrade pip

  log "Installing Windows packaging dependencies"
  wine_run wine "${PYTHON_EXE}" -m pip install pyinstaller

  log "Installing agent dependencies"
  wine_run wine "${PYTHON_EXE}" -m pip install -r "${requirements_win}"
}

clean_previous_artifacts() {
  log "Cleaning old build artifacts"
  rm -rf "${SCRIPT_DIR}/build" "${SCRIPT_DIR}/dist"
  rm -f "${SCRIPT_DIR}"/cropsentinel-agent-*.exe "${SCRIPT_DIR}"/cropsentinel-agent-*.zip
  mkdir -p "${PORTAL_INSTALLERS_DIR}"
  rm -f "${PORTAL_INSTALLERS_DIR}"/cropsentinel-agent-*.exe "${PORTAL_INSTALLERS_DIR}"/cropsentinel-agent-*.zip
}

build_agent_bundle() {
  log "Building agent and watchdog executables"
  (
    cd "${SCRIPT_DIR}"
    wine_run wine "${PYTHON_EXE}" -m PyInstaller --noconfirm agent.spec
  )
}

generate_payload_manifest() {
  log "Generating payload integrity manifest"
  python3 - <<'PY' "${SCRIPT_DIR}/dist/cropsentinel-agent" "${SCRIPT_DIR}/dist/cropsentinel-agent/${PAYLOAD_MANIFEST_NAME}" "${VERSION}" "${PAYLOAD_MANIFEST_NAME}"
from pathlib import Path
import hashlib
import json
import sys
from datetime import datetime, timezone

payload_root = Path(sys.argv[1])
manifest_path = Path(sys.argv[2])
version = sys.argv[3]
manifest_name = sys.argv[4]

files = []
for file_path in sorted(path for path in payload_root.rglob("*") if path.is_file() and path.name != manifest_name):
    digest = hashlib.sha256()
    with file_path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    files.append(
        {
            "path": file_path.relative_to(payload_root).as_posix(),
            "sha256": digest.hexdigest(),
            "size": file_path.stat().st_size,
        }
    )

manifest = {
    "version": version,
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "files": files,
}
manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
PY
}

build_bootstrapper() {
  log "Building setup executable"
  local dist_dir="${WINDOWS_INSTALLER_DIR}\\dist\\cropsentinel-agent"
  local config_env="${WINDOWS_INSTALLER_DIR}\\config.env.example"
  local bootstrapper="${WINDOWS_INSTALLER_DIR}\\bootstrapper.py"
  local out_dir="${WINDOWS_INSTALLER_DIR}\\dist\\setup"
  local work_dir="${WINDOWS_INSTALLER_DIR}\\build\\installer"
  local icon_path="${WINDOWS_ASSETS_DIR}\\app.ico"

  (
    cd "${SCRIPT_DIR}"
    wine_run wine "${PYTHON_EXE}" -m PyInstaller \
      --noconfirm \
      --onefile \
      --windowed \
      --uac-admin \
      --clean \
      --noupx \
      --name "${INSTALLER_BASENAME}" \
      --distpath "${out_dir}" \
      --workpath "${work_dir}" \
      --specpath "${WINDOWS_INSTALLER_DIR}" \
      --icon "${icon_path}" \
      --add-data "${dist_dir};cropsentinel-agent" \
      --add-data "${config_env};." \
      --add-data "${icon_path};." \
      "${bootstrapper}"
  )
}

package_portal_bundle() {
  log "Packaging platform bundle and updating backend/dist/installers"
  python3 - <<'PY' "${SCRIPT_DIR}" "${PORTAL_INSTALLERS_DIR}" "${INSTALLER_NAME}" "${BUNDLE_NAME}"
from pathlib import Path
import shutil
import sys
import zipfile

script_dir = Path(sys.argv[1])
portal_dir = Path(sys.argv[2])
installer_name = sys.argv[3]
bundle_name = sys.argv[4]

setup_exe = script_dir / "dist" / "setup" / installer_name
config_example = script_dir / "config.env.example"

if not setup_exe.exists():
    raise SystemExit(f"Missing setup executable: {setup_exe}")

portal_dir.mkdir(parents=True, exist_ok=True)
bundle_path = portal_dir / bundle_name
portal_exe = portal_dir / installer_name

if bundle_path.exists():
    bundle_path.unlink()
if portal_exe.exists():
    portal_exe.unlink()

shutil.copy2(setup_exe, portal_exe)

readme = f"""CropSentinel Agent installation bundle

Files in this folder:
  - {installer_name}
  - config.env.example

How to use:
  1. For portal downloads, use the tenant-specific config.env that is already included.
  2. For manual testing, copy config.env.example to config.env and edit the values.
  3. Double-click the EXE and follow the consent/install wizard.
  4. The installer will copy the agent binaries, write config.env, and create the
     machine-level scheduled tasks automatically.

This bundle is generic. The portal download endpoint will generate a tenant-
specific config.env for the selected tenant.
"""

with zipfile.ZipFile(bundle_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    archive.write(setup_exe, installer_name)
    archive.write(config_example, "config.env.example")
    archive.writestr("README.txt", readme)
PY
}

show_outputs() {
  log "Build finished"
  echo "Installer EXE : ${SCRIPT_DIR}/dist/setup/${INSTALLER_NAME}"
  echo "Portal EXE    : ${PORTAL_INSTALLERS_DIR}/${INSTALLER_NAME}"
  echo "Portal ZIP    : ${PORTAL_INSTALLERS_DIR}/${BUNDLE_NAME}"
}

main() {
  ensure_linux_deps
  if [[ ! -f "${APP_ICON}" ]]; then
    echo "Missing app icon: ${APP_ICON}" >&2
    exit 1
  fi

  bootstrap_wine
  resolve_windows_paths
  install_windows_python
  install_python_deps
  clean_previous_artifacts
  build_agent_bundle
  generate_payload_manifest
  build_bootstrapper
  package_portal_bundle
  show_outputs
}

main "$@"
