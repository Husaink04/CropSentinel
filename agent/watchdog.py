"""
CropSentinel Agent Watchdog

Cross-platform tamper-detection daemon:
  Windows : runs as a Windows service under LocalSystem. Verifies the agent
            service exists, is running, and that the protected payload still
            matches the cached manifest. Restarts or restores as needed.
  macOS   : checks launchd agent; re-loads if stopped.
  Linux   : checks the systemd service; re-starts if inactive.
"""

from __future__ import annotations

import json
import hashlib
import logging
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

OS = platform.system()
CHECK_INTERVAL = 5
INTEGRITY_CHECK_EVERY = 12
AGENT_SERVICE_NAME = "CropSentinelAgent"
WATCHDOG_SERVICE_NAME = "CropSentinelWatchdog"
AGENT_SERVICE = "cropsentinel-agent"
AGENT_SERVICE_EXE_NAME = "cropsentinel-agent-service.exe"
WATCHDOG_SERVICE_EXE_NAME = "cropsentinel-watchdog-service.exe"
PAYLOAD_MANIFEST = "payload-manifest.json"

if OS == "Windows":
    INSTALL_DIR = Path(r"C:\Program Files\CropSentinel Agent")
    PROGRAM_DATA_DIR = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "CropSentinel"
    CONFIG_PATH = PROGRAM_DATA_DIR / "config.env"
    CACHE_DIR = PROGRAM_DATA_DIR / "payload-cache"
    MANIFEST_PATH = PROGRAM_DATA_DIR / PAYLOAD_MANIFEST
    AGENT_SERVICE_EXE = INSTALL_DIR / AGENT_SERVICE_EXE_NAME
    WATCHDOG_SERVICE_EXE = CACHE_DIR / WATCHDOG_SERVICE_EXE_NAME
elif OS == "Linux":
    INSTALL_DIR = Path("/opt/cropsentinel-agent")
    PROGRAM_DATA_DIR = Path("/etc/cropsentinel")
    CONFIG_PATH = PROGRAM_DATA_DIR / "config.env"
    CACHE_DIR = INSTALL_DIR
    MANIFEST_PATH = INSTALL_DIR / PAYLOAD_MANIFEST
    AGENT_SERVICE_EXE = INSTALL_DIR / "app" / "linux agent.py"
    WATCHDOG_SERVICE_EXE = INSTALL_DIR / "app" / "watchdog.py"
else:
    INSTALL_DIR = Path("/Applications/CropSentinel Agent")
    PROGRAM_DATA_DIR = Path.home() / "Library" / "Application Support" / "CropSentinel"
    CONFIG_PATH = PROGRAM_DATA_DIR / "config.env"
    CACHE_DIR = INSTALL_DIR
    MANIFEST_PATH = INSTALL_DIR / PAYLOAD_MANIFEST
    AGENT_SERVICE_EXE = INSTALL_DIR / "agent.py"
    WATCHDOG_SERVICE_EXE = INSTALL_DIR / "watchdog.py"


def _resolve_log_path() -> Path:
    candidates = []
    if OS == "Windows":
        candidates.extend([
            PROGRAM_DATA_DIR,
            Path.home() / ".cropsentinel_agent",
            Path(tempfile.gettempdir()) / "cropsentinel_agent",
        ])
    elif OS == "Linux":
        candidates.extend([
            Path("/var/log/cropsentinel"),
            Path.home() / ".cropsentinel_agent",
            Path(tempfile.gettempdir()) / "cropsentinel_agent",
        ])
    else:
        candidates.extend([
            Path.home() / ".cropsentinel_agent",
            Path(tempfile.gettempdir()) / "cropsentinel_agent",
        ])

    for directory in candidates:
        try:
            directory.mkdir(parents=True, exist_ok=True)
            log_path = directory / "watchdog.log"
            with log_path.open("a", encoding="utf-8"):
                pass
            return log_path
        except Exception:
            continue
    return Path()


_LOG_PATH = _resolve_log_path()
if _LOG_PATH:
    logging.basicConfig(
        filename=str(_LOG_PATH),
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
else:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
logger = logging.getLogger("cropsentinel.watchdog")

_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_tick_counter = 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().lower()


def _copy_file(source: Path, destination: Path) -> bool:
    try:
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return True
    except Exception as exc:
        logger.error("Failed to copy %s -> %s: %s", source, destination, exc)
        return False


def _win_run_sc(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sc.exe", *args],
        capture_output=True,
        text=True,
        creationflags=_NO_WINDOW,
    )


def _win_service_exists(service_name: str) -> bool:
    result = _win_run_sc(["qc", service_name])
    return result.returncode == 0


def _win_service_running(service_name: str) -> bool:
    result = _win_run_sc(["query", service_name])
    if result.returncode != 0:
        return False
    return "RUNNING" in (result.stdout or "")


def _win_wait_for_service_state(service_name: str, expected: str, timeout_seconds: int = 15) -> bool:
    deadline = time.time() + max(1, timeout_seconds)
    expected = expected.upper()
    while time.time() < deadline:
        result = _win_run_sc(["query", service_name])
        if result.returncode == 0 and expected in (result.stdout or "").upper():
            return True
        time.sleep(1)
    return False


def _win_start_service(service_name: str) -> bool:
    result = _win_run_sc(["start", service_name])
    if result.returncode != 0 and "service has already been started" not in (result.stdout + result.stderr).lower():
        logger.error("Failed to start service %s: %s", service_name, (result.stdout or result.stderr).strip())
        return False
    return _win_wait_for_service_state(service_name, "RUNNING", timeout_seconds=20)


def _win_configure_service_recovery(service_name: str) -> None:
    _win_run_sc([
        "failure",
        service_name,
        "reset=",
        "86400",
        "actions=",
        "restart/5000/restart/5000/restart/5000",
    ])
    _win_run_sc(["failureflag", service_name, "1"])


def _win_create_or_update_service(
    service_name: str,
    binary_path: Path,
    display_name: str,
    description: str,
) -> bool:
    if not binary_path.exists():
        logger.critical("Service binary missing for %s: %s", service_name, binary_path)
        return False

    quoted_path = f'"{binary_path}"'
    if _win_service_exists(service_name):
        result = _win_run_sc([
            "config",
            service_name,
            "binPath=",
            quoted_path,
            "start=",
            "auto",
            "obj=",
            "LocalSystem",
            "type=",
            "own",
        ])
    else:
        result = _win_run_sc([
            "create",
            service_name,
            "binPath=",
            quoted_path,
            "start=",
            "auto",
            "obj=",
            "LocalSystem",
            "type=",
            "own",
            "DisplayName=",
            display_name,
        ])
    if result.returncode != 0:
        logger.error("Failed to create/update service %s: %s", service_name, (result.stdout or result.stderr).strip())
        return False

    _win_run_sc(["description", service_name, description])
    _win_configure_service_recovery(service_name)
    return True


def _win_re_register_service(service_name: str) -> bool:
    if service_name == AGENT_SERVICE_NAME:
        return _win_create_or_update_service(
            service_name,
            AGENT_SERVICE_EXE,
            "CropSentinel Agent",
            "CropSentinel monitoring agent service.",
        )
    if service_name == WATCHDOG_SERVICE_NAME:
        return _win_create_or_update_service(
            service_name,
            WATCHDOG_SERVICE_EXE,
            "CropSentinel Watchdog",
            "CropSentinel self-heal watchdog service.",
        )
    logger.error("Unknown Windows service requested for re-registration: %s", service_name)
    return False


def _restore_cache_file(relative_path: str, install_file: Path) -> bool:
    cache_file = CACHE_DIR / Path(relative_path.replace("/", os.sep))
    return _copy_file(install_file, cache_file)


def _restore_install_file(relative_path: str, cache_file: Path) -> bool:
    install_file = INSTALL_DIR / Path(relative_path.replace("/", os.sep))
    return _copy_file(cache_file, install_file)


def _check_payload_integrity(issues: list[str]) -> None:
    if not MANIFEST_PATH.exists():
        logger.warning("TAMPER DETECTED: payload manifest missing at %s", MANIFEST_PATH)
        issues.append("manifest_missing")
        return

    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.error("Could not read payload manifest: %s", exc)
        issues.append("manifest_unreadable")
        return

    files = manifest.get("files") or []
    if not isinstance(files, list) or not files:
        logger.warning("TAMPER DETECTED: payload manifest is empty")
        issues.append("manifest_empty")
        return

    for entry in files:
        relative = str(entry.get("path") or "").strip()
        expected_hash = str(entry.get("sha256") or "").strip().lower()
        if not relative or not expected_hash:
            logger.warning("TAMPER DETECTED: payload manifest contains an invalid entry")
            issues.append("manifest_invalid")
            return

        relative_path = Path(relative.replace("/", os.sep))
        cache_file = CACHE_DIR / relative_path
        install_file = INSTALL_DIR / relative_path
        cache_hash = ""
        install_hash = ""

        if cache_file.exists():
            try:
                cache_hash = _sha256(cache_file)
            except Exception as exc:
                logger.error("Could not hash cached payload file %s: %s", cache_file, exc)
                issues.append("cache_hash_failed")

        if install_file.exists():
            try:
                install_hash = _sha256(install_file)
            except Exception as exc:
                logger.error("Could not hash installed payload file %s: %s", install_file, exc)
                issues.append("install_hash_failed")

        cache_ok = cache_hash == expected_hash
        install_ok = install_hash == expected_hash

        if not cache_file.exists() and install_ok:
            logger.warning("TAMPER DETECTED: payload cache file missing for %s", relative)
            issues.append("cache_missing")
            if _restore_cache_file(relative, install_file):
                logger.info("Restored cache copy for %s from install payload", relative)
                cache_ok = True
        elif cache_file.exists() and not cache_ok and install_ok:
            logger.warning("TAMPER DETECTED: payload cache file changed for %s", relative)
            issues.append("cache_hash_mismatch")
            if _restore_cache_file(relative, install_file):
                logger.info("Restored cache copy for %s from install payload", relative)
                cache_ok = True

        if not cache_ok and not install_ok:
            logger.critical("Both cached and installed payload copies are invalid for %s", relative)
            issues.append("payload_unrecoverable")
            continue

        if not install_file.exists():
            logger.warning("TAMPER DETECTED: installed payload file missing: %s", install_file)
            issues.append("install_missing")
            if cache_ok and _restore_install_file(relative, cache_file):
                logger.info("Restored missing installed payload file from cache: %s", install_file)
            continue

        if not install_ok and cache_ok:
            logger.warning("TAMPER DETECTED: installed payload file changed: %s", install_file)
            issues.append("install_hash_mismatch")
            if _restore_install_file(relative, cache_file):
                logger.info("Restored changed installed payload file from cache: %s", install_file)


def _check_windows() -> None:
    global _tick_counter
    issues: list[str] = []

    if not _win_service_exists(AGENT_SERVICE_NAME):
        logger.warning("TAMPER DETECTED: %s service missing - re-registering", AGENT_SERVICE_NAME)
        issues.append("agent_service_missing")
        if _win_re_register_service(AGENT_SERVICE_NAME):
            logger.info("%s service re-registered successfully", AGENT_SERVICE_NAME)
        else:
            logger.error("Failed to re-register %s service", AGENT_SERVICE_NAME)

    if not _win_service_exists(WATCHDOG_SERVICE_NAME):
        logger.warning("TAMPER DETECTED: %s service missing - re-registering", WATCHDOG_SERVICE_NAME)
        issues.append("watchdog_service_missing")
        if _win_re_register_service(WATCHDOG_SERVICE_NAME):
            logger.info("%s service re-registered successfully", WATCHDOG_SERVICE_NAME)
        else:
            logger.error("Failed to re-register %s service", WATCHDOG_SERVICE_NAME)

    if _win_service_exists(AGENT_SERVICE_NAME) and not _win_service_running(AGENT_SERVICE_NAME):
        logger.warning("%s service is not running - restarting", AGENT_SERVICE_NAME)
        issues.append("agent_service_stopped")
        if _win_start_service(AGENT_SERVICE_NAME):
            logger.info("%s service restarted successfully", AGENT_SERVICE_NAME)
        else:
            logger.error("Failed to restart %s service", AGENT_SERVICE_NAME)

    _check_config(issues)
    _tick_counter += 1
    if _tick_counter % INTEGRITY_CHECK_EVERY == 0:
        _check_payload_integrity(issues)

    if not issues:
        logger.debug("Watchdog tick: all checks passed")


def _macos_label() -> str:
    return f"com.cropsentinel.{AGENT_SERVICE}"


def _macos_agent_running() -> bool:
    try:
        out = subprocess.check_output(
            ["launchctl", "list", _macos_label()],
            stderr=subprocess.DEVNULL,
        ).decode()
        match = re.search(r'"PID"\s*=\s*(\d+)', out)
        return bool(match and int(match.group(1)) > 0)
    except Exception:
        return False


def _check_macos() -> None:
    issues: list[str] = []
    if not _macos_agent_running():
        logger.warning("CropSentinel agent launchd entry is not running - restarting")
        issues.append("agent_stopped")
        subprocess.run(
            ["launchctl", "start", _macos_label()],
            capture_output=True,
        )
    _check_config(issues)
    if not issues:
        logger.debug("Watchdog tick: all checks passed")


def _check_linux() -> None:
    issues: list[str] = []
    result = subprocess.run(
        ["systemctl", "is-active", f"{AGENT_SERVICE}.service"],
        capture_output=True,
    )
    if result.returncode != 0:
        logger.warning("CropSentinel systemd service is not active - restarting")
        issues.append("service_inactive")
        subprocess.run(
            ["systemctl", "start", f"{AGENT_SERVICE}.service"],
            capture_output=True,
        )
    _check_config(issues)
    if not issues:
        logger.debug("Watchdog tick: all checks passed")


def _check_config(issues: list[str]) -> None:
    if not CONFIG_PATH.exists():
        logger.warning("TAMPER DETECTED: config.env is missing at %s", CONFIG_PATH)
        issues.append("config_missing")
        return
    try:
        text = CONFIG_PATH.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        logger.error("Could not read config.env: %s", exc)
        return
    if not text.strip():
        logger.warning("TAMPER DETECTED: config.env is empty")
        issues.append("config_empty")
        return
    if "CROPSENTINEL_ENROLL_TOKEN" not in text:
        logger.warning("TAMPER DETECTED: CROPSENTINEL_ENROLL_TOKEN missing from config.env")
        issues.append("token_missing")


def run_watchdog(stop_event=None) -> None:
    logger.info("CropSentinel Watchdog starting (OS=%s, interval=%ds)", OS, CHECK_INTERVAL)
    while True:
        if stop_event is not None and stop_event.is_set():
            logger.info("Watchdog stop requested")
            return
        try:
            if OS == "Windows":
                _check_windows()
            elif OS == "Darwin":
                _check_macos()
            else:
                _check_linux()
        except Exception as exc:
            logger.error("Watchdog tick raised an unexpected error: %s", exc)

        if stop_event is not None:
            if stop_event.wait(CHECK_INTERVAL):
                logger.info("Watchdog stop requested")
                return
        else:
            time.sleep(CHECK_INTERVAL)


def main() -> None:
    run_watchdog(stop_event=None)


if __name__ == "__main__":
    main()
