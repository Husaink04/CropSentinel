"""
CropSentinel Employee Monitoring Agent
Monitor. Detect. Protect.
Cross-platform: Windows / macOS / Linux

- Consent popup on first run (stored, never shown again)
- Password-protected stop (admin only)
- Browser history tracking (Chrome, Firefox, Edge, Safari)
- Active application tracking
- Screenshots at configurable intervals
- WebSocket real-time sync + REST fallback
- Silent background operation (no CMD/terminal popups)
"""

import os, sys, json, time, uuid, hashlib, platform, socket, threading
import subprocess, base64, io, logging, traceback,asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from activity_runtime import normalize_activity_payload, resolve_activity_priority

def _utcnow_iso():
    """Timezone-aware UTC ISO string â€” no deprecation warnings."""
    return datetime.now(timezone.utc).isoformat()


def _agent_capabilities():
    return {
        "protocol_schema_version": 1,
        "transport": ["websocket", "http_fallback"],
        "event_ack": True,
        "config_push": True,
        "baseline_inventory": True,
        "self_throttle": True,
        "dlp_policy": True,
        "phishing_policy": True,
    }

# â”€â”€â”€ CONFIG FILE LOADER â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
# Populates os.environ from a config.env file BEFORE the CONFIGURATION block
# below reads env vars. First hit wins:
#   1. Platform install location (Windows/Linux/macOS)
#   2. <agent.py dir>/.env                â€” developer override for local runs
# os.environ.setdefault() means real env vars always take precedence, so a
# developer can still override any value by exporting it before launch.
def _load_config_env():
    from pathlib import Path as _P
    alias_keys = {
        "CROPSENTINEL_SERVER": "CROPPRO_SERVER",
        "CROPPRO_SERVER_URL": "CROPPRO_SERVER",
        "CROPSENTINEL_ENROLL_TOKEN": "CROPPRO_ENROLL_TOKEN",
        "AGENT_ENROLL_TOKEN": "CROPPRO_ENROLL_TOKEN",
        "CROPSENTINEL_AGENT_KEY": "CROPPRO_AGENT_KEY",
        "CROPSENTINEL_SCREENSHOT_INTERVAL": "CROPPRO_SCREENSHOT_INTERVAL",
        "CROPSENTINEL_SYNC_INTERVAL": "CROPPRO_SYNC_INTERVAL",
    }
    system_name = platform.system()
    candidates = []
    if system_name == "Windows":
        candidates.append(_P(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "CropSentinel" / "config.env")
    elif system_name == "Linux":
        candidates.extend([
            _P("/etc/cropsentinel/config.env"),
            _P("/opt/cropsentinel-agent/config.env"),
        ])
    elif system_name == "Darwin":
        candidates.extend([
            _P("/Library/Application Support/CropSentinel/config.env"),
            _P.home() / "Library" / "Application Support" / "CropSentinel" / "config.env",
        ])
    candidates.append(_P(__file__).parent / ".env")
    for cf in candidates:
        try:
            if not cf.exists():
                continue
            for ln in cf.read_text(encoding="utf-8").splitlines():
                ln = ln.strip()
                if not ln or ln.startswith("#") or "=" not in ln:
                    continue
                k, _, v = ln.partition("=")
                key = k.strip()
                value = v.strip().strip('"').strip("'")
                key = alias_keys.get(key, key)
                os.environ.setdefault(key, value)
        except Exception:
            pass  # malformed config must never crash the agent
        break  # first hit wins
_load_config_env()

def _env_first(*keys, default=None):
    """Return the first non-empty env var among keys, else default."""
    for key in keys:
        value = os.environ.get(key)
        if value is not None and str(value).strip() != "":
            return value
    return default

# â”€â”€â”€ CONFIGURATION â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
AGENT_VERSION = "1.3.0"
AGENT_PROTOCOL_SCHEMA_VERSION = 1
SERVER_URL = _env_first("CROPSENTINEL_SERVER", "CROPPRO_SERVER", default="http://localhost:8000")
if SERVER_URL == "http://localhost:8000" and not _env_first("CROPSENTINEL_SERVER", "CROPPRO_SERVER"):
    logging.getLogger("cropsentinel.agent").warning(
        "CropSentinel server URL not set - defaulting to http://localhost:8000. Set CROPSENTINEL_SERVER in config.env for production."
    )
WS_URL = SERVER_URL.replace("http://", "ws://").replace("https://", "wss://")
# Must match server AGENT_API_KEY when set (optional in development).
AGENT_API_KEY = _env_first("CROPSENTINEL_AGENT_KEY", "CROPPRO_AGENT_KEY")
# Per-tenant enrollment token (cpet_...). Required on multi-tenant installs;
# determines which tenant this agent joins on first registration.
AGENT_ENROLL_TOKEN = _env_first("CROPSENTINEL_ENROLL_TOKEN", "CROPPRO_ENROLL_TOKEN", "AGENT_ENROLL_TOKEN")

# SHA-256 hash of the agent stop password (set via AGENT_STOP_PASSWORD_HASH in .env)
AGENT_STOP_PASSWORD_HASH = os.environ.get("AGENT_STOP_PASSWORD_HASH", "")

ALLOWED_REMOTE_COMMANDS = {
    "lock_screen",
    "show_message",
    "open_url",
    "mute_audio",
    "unmute_audio",
    "sleep",
    "logout_user",
    "ctrl_alt_del",
}

def _safe_int(env_key: str, default: int) -> int:
    """Parse an env var as int, falling back to default on any error."""
    try:
        return int(os.environ.get(env_key, str(default)))
    except (ValueError, TypeError):
        return default


def _safe_float(env_key: str, default: float) -> float:
    """Parse an env var as float, falling back to default on any error."""
    try:
        return float(os.environ.get(env_key, str(default)))
    except (ValueError, TypeError):
        return default


def _safe_bool(env_key: str, default: bool) -> bool:
    value = os.environ.get(env_key)
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}

SCREENSHOT_INTERVAL = _safe_int("CROPSENTINEL_SCREENSHOT_INTERVAL", _safe_int("CROPPRO_SCREENSHOT_INTERVAL", 180))
ACTIVITY_SYNC_INTERVAL = _safe_int("CROPSENTINEL_SYNC_INTERVAL", _safe_int("CROPPRO_SYNC_INTERVAL", 60))
HEARTBEAT_INTERVAL = _safe_int("CROPSENTINEL_HEARTBEAT_INTERVAL", 30)
APP_TRACKER_INTERVAL = _safe_int("CROPSENTINEL_APP_TRACKER_INTERVAL", 10)
NETWORK_TRACKER_INTERVAL = _safe_int("CROPSENTINEL_NETWORK_INTERVAL", 60)
USB_TRACKER_INTERVAL = _safe_int("CROPSENTINEL_USB_INTERVAL", 10)
PRINT_TRACKER_INTERVAL = _safe_int("CROPSENTINEL_PRINT_INTERVAL", 20)
FILE_CACHE_FAST_SWEEP_SECONDS = _safe_float("CROPSENTINEL_FILE_CACHE_FAST_SWEEP_SECONDS", 10.0)
FILE_CACHE_SWEEP_SECONDS = _safe_float("CROPSENTINEL_FILE_CACHE_SWEEP_SECONDS", 120.0)
FILE_CACHE_SWEEPER_ENABLED = _safe_bool("CROPSENTINEL_FILE_CACHE_SWEEPER_ENABLED", True)
SELF_THROTTLE_ENABLED = _safe_bool("CROPSENTINEL_SELF_THROTTLE_ENABLED", True)
SELF_THROTTLE_CPU_PERCENT = _safe_int("CROPSENTINEL_SELF_THROTTLE_CPU_PERCENT", 85)
SELF_THROTTLE_MEMORY_PERCENT = _safe_int("CROPSENTINEL_SELF_THROTTLE_MEMORY_PERCENT", 80)
SELF_THROTTLE_QUEUE_DEPTH = _safe_int("CROPSENTINEL_SELF_THROTTLE_QUEUE_DEPTH", 500)
SELF_THROTTLE_INTERVAL_MULTIPLIER = _safe_float("CROPSENTINEL_SELF_THROTTLE_INTERVAL_MULTIPLIER", 2.0)
SELF_THROTTLE_COOLDOWN_SECONDS = _safe_int("CROPSENTINEL_SELF_THROTTLE_COOLDOWN_SECONDS", 300)
STARTUP_RAMP_STEP_SECONDS = _safe_int("CROPSENTINEL_STARTUP_RAMP_STEP_SECONDS", 20)
STARTUP_STABLE_SAMPLES_REQUIRED = _safe_int("CROPSENTINEL_STARTUP_STABLE_SAMPLES_REQUIRED", 3)
RESOURCE_MONITOR_INTERVAL = _safe_int("CROPSENTINEL_RESOURCE_MONITOR_INTERVAL", 15)
RESOURCE_HIGH_CPU_PERCENT = _safe_int("CROPSENTINEL_RESOURCE_HIGH_CPU_PERCENT", 80)
RESOURCE_HIGH_MEMORY_PERCENT = _safe_int("CROPSENTINEL_RESOURCE_HIGH_MEMORY_PERCENT", 80)
RESOURCE_CRITICAL_CPU_PERCENT = _safe_int("CROPSENTINEL_RESOURCE_CRITICAL_CPU_PERCENT", 92)
RESOURCE_CRITICAL_MEMORY_PERCENT = _safe_int("CROPSENTINEL_RESOURCE_CRITICAL_MEMORY_PERCENT", 90)

DATA_DIR = Path.home() / ".cropsentinel_agent"
DATA_DIR.mkdir(exist_ok=True)
CONSENT_FILE = DATA_DIR / "consent.json"
CONFIG_FILE = DATA_DIR / "config.json"
LOG_FILE = DATA_DIR / "agent.log"
REGISTRATION_STATUS_FILE = DATA_DIR / "registration_status.json"

logging.basicConfig(
    filename=str(LOG_FILE),
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("cropsentinel")

OS = platform.system()  # Windows / Darwin / Linux


# â”€â”€â”€ SYSTEM INFO â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def get_machine_id():
    """Stable machine GUID across reboots"""
    id_file = DATA_DIR / "machine_id"
    if id_file.exists():
        return id_file.read_text().strip()
    # Try OS-specific IDs
    try:
        if OS == "Windows":
            # wmic was removed in Windows 11 24H2+. Use Get-CimInstance instead,
            # with a wmic fallback for older Windows versions.
            out = ""
            try:
                out = subprocess.check_output(
                    ["powershell", "-NoProfile", "-NonInteractive", "-Command",
                     "(Get-CimInstance Win32_ComputerSystemProduct).UUID"],
                    stderr=subprocess.DEVNULL,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                ).decode().strip()
            except Exception:
                try:
                    out = subprocess.check_output(
                        "wmic csproduct get UUID",
                        shell=True, stderr=subprocess.DEVNULL,
                    ).decode().split("\n")[1].strip()
                except Exception:
                    pass
            if out and out != "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF":
                mid = out
            else:
                mid = str(uuid.uuid4())
        elif OS == "Darwin":
            out = subprocess.check_output(
                ["ioreg", "-rd1", "-c", "IOPlatformExpertDevice"],
                stderr=subprocess.DEVNULL
            ).decode()
            import re
            match = re.search(r'"IOPlatformUUID"\s*=\s*"([^"]+)"', out)
            mid = match.group(1) if match else str(uuid.uuid4())
        else:
            # Linux
            if Path("/etc/machine-id").exists():
                mid = Path("/etc/machine-id").read_text().strip()
            elif Path("/var/lib/dbus/machine-id").exists():
                mid = Path("/var/lib/dbus/machine-id").read_text().strip()
            else:
                mid = str(uuid.uuid4())
    except:
        mid = str(uuid.uuid4())
    id_file.write_text(mid)
    return mid


def get_ip_address():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except:
        return "127.0.0.1"


def get_mac_address():
    try:
        import uuid as _uuid
        mac = _uuid.getnode()
        return ':'.join(('%012X' % mac)[i:i+2] for i in range(0, 12, 2))
    except:
        return ""


# â”€â”€â”€ CONSENT â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def check_consent() -> bool:
    if CONSENT_FILE.exists():
        data = json.loads(CONSENT_FILE.read_text())
        return data.get("consented", False)
    return False


def show_consent_dialog() -> bool:
    """Show consent dialog - returns True if accepted"""
    company = "CropSentinel"
    try:
        cfg = json.loads(CONFIG_FILE.read_text()) if CONFIG_FILE.exists() else {}
        company = cfg.get("company_name", company)
    except:
        pass

    msg = f"""{company} - Employee Monitoring Notice

Your employer uses CropSentinel to monitor work activity on this device.

What is monitored:
  â€¢ Active application usage and window titles
  â€¢ Browser history and visited websites
  â€¢ Periodic screenshots of your screen
  â€¢ System resource usage (CPU, memory)

What is NOT monitored:
  â€¢ Keystrokes or passwords
  â€¢ Personal devices or accounts
  â€¢ Activity outside work hours (configurable)

This monitoring is performed for legitimate business purposes.
Data is stored securely and accessible only to authorized admins.

By clicking Accept, you acknowledge and consent to this monitoring.
This notice will not appear again. The agent runs in the background.

Do you accept?"""

    try:
        if OS == "Windows":
            import ctypes
            result = ctypes.windll.user32.MessageBoxW(
                0, msg,
                f"{company} - Monitoring Consent Required",
                0x00000001 | 0x00000040  # OK/Cancel + Info icon
            )
            return result == 1  # 1 = OK, 2 = Cancel
        elif OS == "Darwin":
            escaped_msg = msg.replace('"', '\\"')
            script = (
                f'set result to display dialog "{escaped_msg}" '
                f'with title "{company} - Monitoring Consent" '
                f'buttons {{"Decline", "Accept"}} '
                f'default button "Accept" with icon caution\n'
                f'return button returned of result'
            )
            result = subprocess.check_output(
                ["osascript", "-e", script], stderr=subprocess.DEVNULL
            ).decode().strip()
            return result == "Accept"
        else:
            # Linux - try zenity, then tkinter
            try:
                result = subprocess.run(
                    ["zenity", "--question", "--title",
                     f"{company} - Monitoring Consent",
                     "--text", msg, "--ok-label=Accept", "--cancel-label=Decline",
                     "--width=500"],
                    capture_output=True
                )
                return result.returncode == 0
            except:
                # Fallback to tkinter
                import tkinter as tk
                from tkinter import messagebox
                root = tk.Tk()
                root.withdraw()
                root.attributes("-topmost", True)
                accepted = messagebox.askyesno(
                    f"{company} - Monitoring Consent",
                    msg
                )
                root.destroy()
                return accepted
    except Exception as e:
        logger.error(f"Consent dialog error: {e}")
        # If dialog fails, log and proceed (check your deployment policy)
        return True


def save_consent(accepted: bool):
    data = {
        "consented": accepted,
        "timestamp": _utcnow_iso(),
        "machine_id": get_machine_id(),
        "hostname": socket.gethostname(),
    }
    CONSENT_FILE.write_text(json.dumps(data, indent=2))


# â”€â”€â”€ ACTIVE WINDOW â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def get_active_window():
    """Returns (app_name, window_title, process_name)"""
    try:
        if OS == "Windows":
            import ctypes
            hwnd = ctypes.windll.user32.GetForegroundWindow()
            length = ctypes.windll.user32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(length + 1)
            ctypes.windll.user32.GetWindowTextW(hwnd, buf, length + 1)
            title = buf.value

            pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            import psutil
            try:
                proc = psutil.Process(pid.value)
                return proc.name().replace(".exe",""), title, proc.name()
            except:
                return "Unknown", title, "unknown"

        elif OS == "Darwin":
            script = '''
            tell application "System Events"
                set frontApp to first application process whose frontmost is true
                set appName to name of frontApp
            end tell
            return appName
            '''
            app = subprocess.check_output(
                ["osascript", "-e", script], stderr=subprocess.DEVNULL
            ).decode().strip()

            title_script = '''
            tell application "System Events"
                set frontApp to first application process whose frontmost is true
                try
                    set win to front window of frontApp
                    return name of win
                end try
                return ""
            end tell
            '''
            try:
                title = subprocess.check_output(
                    ["osascript", "-e", title_script], stderr=subprocess.DEVNULL
                ).decode().strip()
            except:
                title = app
            return app, title, app.lower()

        else:
            # Linux - try xdotool
            try:
                wid = subprocess.check_output(
                    ["xdotool", "getactivewindow"], stderr=subprocess.DEVNULL
                ).decode().strip()
                name = subprocess.check_output(
                    ["xdotool", "getwindowname", wid], stderr=subprocess.DEVNULL
                ).decode().strip()
                pid_out = subprocess.check_output(
                    ["xdotool", "getwindowpid", wid], stderr=subprocess.DEVNULL
                ).decode().strip()
                import psutil
                proc = psutil.Process(int(pid_out))
                return proc.name(), name, proc.name()
            except:
                return "Unknown", "Unknown", "unknown"
    except Exception as e:
        logger.debug(f"get_active_window error: {e}")
        return "Unknown", "Unknown", "unknown"


# â”€â”€â”€ BROWSER HISTORY â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def get_browser_history_entries(since_timestamp: Optional[float] = None):
    """Fetch recent browser history entries across all installed browsers"""
    entries = []

    def _collect_chromium_profiles(user_data_dir: Path):
        profiles = []
        if not user_data_dir.exists():
            return profiles
        preferred = ["Default"] + [f"Profile {i}" for i in range(1, 10)]
        seen = set()
        for name in preferred:
            profile = user_data_dir / name
            if profile.exists() and (profile / "History").exists():
                profiles.append(profile)
                seen.add(str(profile))
        try:
            for child in user_data_dir.iterdir():
                if not child.is_dir():
                    continue
                if str(child) in seen:
                    continue
                if (child / "History").exists():
                    profiles.append(child)
        except Exception:
            pass
        return profiles

    def chrome_like(profile_paths, browser_name):
        import sqlite3, shutil, tempfile
        for p in profile_paths:
            hist_file = p / "History"
            if not hist_file.exists():
                continue
            tmp = Path(tempfile.mktemp(suffix=".db"))
            try:
                shutil.copy2(hist_file, tmp)
                conn = sqlite3.connect(str(tmp))
                conn.row_factory = sqlite3.Row
                # Chrome epoch: microseconds since Jan 1, 1601
                # Convert since_timestamp (unix) to chrome time
                since_chrome = 0
                if since_timestamp:
                    since_chrome = int((since_timestamp + 11644473600) * 1_000_000)
                rows = conn.execute("""
                    SELECT url, title, last_visit_time,
                        CAST((last_visit_time - 11644473600000000) / 1000000 AS INTEGER) as unix_ts
                    FROM urls WHERE last_visit_time > ?
                    ORDER BY last_visit_time DESC LIMIT 50
                """, (since_chrome,)).fetchall()
                for r in rows:
                    try:
                        from urllib.parse import urlparse
                        domain = urlparse(r["url"]).netloc
                        entries.append({
                            "browser": browser_name,
                            "url": r["url"],
                            "title": r["title"] or "",
                            "domain": domain,
                            "timestamp": datetime.fromtimestamp(r["unix_ts"], tz=timezone.utc).isoformat(),
                            "duration_seconds": 0,
                        })
                    except:
                        pass
                conn.close()
            except Exception as e:
                logger.debug(f"Browser history error {browser_name}: {e}")
            finally:
                try: tmp.unlink()
                except: pass

    def firefox_like(profile_root: Path, browser_name: str):
        import sqlite3, shutil, tempfile
        if not profile_root.exists():
            return
        try:
            profiles = [p for p in profile_root.iterdir() if p.is_dir() and (p / "places.sqlite").exists()]
        except Exception:
            return
        for profile in profiles:
            places_file = profile / "places.sqlite"
            tmp = Path(tempfile.mktemp(suffix=".db"))
            try:
                shutil.copy2(places_file, tmp)
                conn = sqlite3.connect(str(tmp))
                conn.row_factory = sqlite3.Row
                since_firefox = int(since_timestamp * 1_000_000) if since_timestamp else 0
                rows = conn.execute(
                    """
                    SELECT p.url, p.title, h.visit_date
                    FROM moz_historyvisits h
                    JOIN moz_places p ON h.place_id = p.id
                    WHERE h.visit_date > ?
                    ORDER BY h.visit_date DESC
                    LIMIT 50
                    """,
                    (since_firefox,),
                ).fetchall()
                for r in rows:
                    try:
                        from urllib.parse import urlparse
                        unix_ts = int(r["visit_date"] // 1_000_000)
                        entries.append(
                            {
                                "browser": browser_name,
                                "url": r["url"],
                                "title": r["title"] or "",
                                "domain": urlparse(r["url"]).netloc,
                                "timestamp": datetime.fromtimestamp(unix_ts, tz=timezone.utc).isoformat(),
                                "duration_seconds": 0,
                            }
                        )
                    except Exception:
                        pass
                conn.close()
            except Exception as e:
                logger.debug(f"Browser history error {browser_name}: {e}")
            finally:
                try:
                    tmp.unlink()
                except Exception:
                    pass

    home = Path.home()
    if OS == "Windows":
        local = Path(os.environ.get("LOCALAPPDATA", home / "AppData" / "Local"))
        roaming = Path(os.environ.get("APPDATA", home / "AppData" / "Roaming"))
        chrome_like(_collect_chromium_profiles(local / "Google" / "Chrome" / "User Data"), "Chrome")
        chrome_like(_collect_chromium_profiles(local / "Microsoft" / "Edge" / "User Data"), "Edge")
        firefox_like(roaming / "Mozilla" / "Firefox" / "Profiles", "Firefox")

    elif OS == "Darwin":
        chrome_like([
            home / "Library" / "Application Support" / "Google" / "Chrome" / "Default",
        ], "Chrome")
        chrome_like([
            home / "Library" / "Application Support" / "Microsoft Edge" / "Default",
        ], "Edge")
        # Safari - use plist
        try:
            safari_hist = home / "Library" / "Safari" / "History.db"
            if safari_hist.exists():
                import sqlite3, shutil, tempfile
                tmp = Path(tempfile.mktemp(suffix=".db"))
                shutil.copy2(safari_hist, tmp)
                conn = sqlite3.connect(str(tmp))
                rows = conn.execute("""
                    SELECT url, title, visit_time
                    FROM history_visits v JOIN history_items i ON v.history_item=i.id
                    ORDER BY visit_time DESC LIMIT 50
                """).fetchall()
                for r in rows:
                    from urllib.parse import urlparse
                    entries.append({
                        "browser": "Safari",
                        "url": r[0], "title": r[1] or "",
                        "domain": urlparse(r[0]).netloc,
                        "timestamp": datetime.fromtimestamp(r[2] + 978307200, tz=timezone.utc).isoformat(),
                        "duration_seconds": 0,
                    })
                conn.close()
                tmp.unlink()
        except Exception as e:
            logger.debug(f"Safari history: {e}")

    else:  # Linux
        chrome_like([
            home / ".config" / "google-chrome" / "Default",
            home / ".config" / "chromium" / "Default",
        ], "Chrome")
        chrome_like([
            home / ".config" / "microsoft-edge" / "Default",
        ], "Edge")
        # Firefox
        ff_dir = home / ".mozilla" / "firefox"
        if ff_dir.exists():
            for profile in ff_dir.iterdir():
                if profile.is_dir() and (profile / "places.sqlite").exists():
                    chrome_like([profile], "Firefox")
                    break

    return entries


# â”€â”€â”€ SCREENSHOT â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def take_screenshot() -> Optional[str]:
    """Returns base64 encoded JPEG screenshot"""
    try:
        from PIL import ImageGrab, Image
        img = ImageGrab.grab()
        # Resize for bandwidth
        img.thumbnail((1280, 720), Image.Resampling.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=60)
        return base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        try:
            if OS == "Linux":
                import subprocess, tempfile
                tmp = tempfile.mktemp(suffix=".png")
                subprocess.run(["scrot", tmp], capture_output=True)
                with open(tmp, "rb") as f:
                    data = base64.b64encode(f.read()).decode()
                os.unlink(tmp)
                return data
        except:
            pass
    except Exception as e:
        logger.error(f"Screenshot error: {e}")
    return None


# â”€â”€â”€ SYSTEM METRICS â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def get_system_metrics():
    try:
        import psutil
        return {
            "cpu_percent": psutil.cpu_percent(interval=None),
            "memory_percent": psutil.virtual_memory().percent,
        }
    except:
        return {"cpu_percent": 0, "memory_percent": 0}


# â”€â”€â”€ IDLE TIME â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def get_idle_seconds():
    try:
        if OS == "Windows":
            import ctypes
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]
            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii))
            millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
            return millis // 1000
        elif OS == "Darwin":
            out = subprocess.check_output(
                ["ioreg", "-c", "IOHIDSystem"], stderr=subprocess.DEVNULL
            ).decode()
            import re
            match = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', out)
            if match:
                return int(match.group(1)) // 1_000_000_000
        else:
            out = subprocess.check_output(
                ["xprintidle"], stderr=subprocess.DEVNULL
            ).decode().strip()
            return int(out) // 1000
    except:
        return 0


# â”€â”€â”€ HTTP CLIENT â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _agent_http_headers():
    h = {"Content-Type": "application/json"}
    if AGENT_API_KEY:
        h["X-CropSentinel-Agent-Key"] = AGENT_API_KEY
    if AGENT_ENROLL_TOKEN:
        h["X-CropSentinel-Enroll-Token"] = AGENT_ENROLL_TOKEN
    return h


def _safe_consent_timestamp() -> str:
    """Read consent timestamp safely, returning empty string on any error."""
    try:
        return json.loads(CONSENT_FILE.read_text()).get("timestamp", "")
    except Exception:
        return ""


def http_post(endpoint: str, data: dict) -> bool:
    try:
        import urllib.request
        url = f"{SERVER_URL}{endpoint}"
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers=_agent_http_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        logger.debug(f"HTTP POST {endpoint} failed: {e}")
        return False


def http_post_with_status(endpoint: str, data: dict):
    """POST JSON and return (ok, status_code, detail)."""
    try:
        import urllib.request
        import urllib.error
        url = f"{SERVER_URL}{endpoint}"
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers=_agent_http_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            detail = ""
            if body:
                try:
                    parsed = json.loads(body)
                    detail = str(parsed.get("detail", ""))
                except Exception:
                    detail = body[:300]
            return resp.status == 200, int(resp.status), detail
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            body = e.read().decode("utf-8", errors="ignore")
            if body:
                parsed = json.loads(body)
                detail = str(parsed.get("detail", body[:300]))
        except Exception:
            detail = str(e)
        return False, int(getattr(e, "code", 0) or 0), detail
    except Exception as e:
        logger.debug(f"HTTP POST (status) {endpoint} failed: {e}")
        return False, 0, str(e)


def http_post_json(endpoint: str, data: dict):
    """POST and parse JSON body (used for heartbeat config)."""
    try:
        import urllib.request
        url = f"{SERVER_URL}{endpoint}"
        payload = json.dumps(data).encode("utf-8")
        req = urllib.request.Request(url, data=payload, headers=_agent_http_headers())
        with urllib.request.urlopen(req, timeout=10) as resp:
            body = resp.read().decode()
            return json.loads(body) if body else {}
    except Exception as e:
        logger.debug(f"HTTP POST JSON {endpoint} failed: {e}")
        return None


# â”€â”€â”€ AGENT CORE â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
class CropSentinelAgent:
    _STARTUP_SUBSYSTEM_SPECS = {
        "app_tracker": {
            "mode": "gate",
            "ramp_order": 10,
            "pause_on_high": False,
            "pause_on_critical": True,
        },
        "network_tracker": {
            "mode": "restart",
            "ramp_order": 20,
            "pause_on_high": False,
            "pause_on_critical": True,
        },
        "usb_tracker": {
            "mode": "restart",
            "ramp_order": 30,
            "pause_on_high": False,
            "pause_on_critical": True,
        },
        "print_tracker": {
            "mode": "restart",
            "ramp_order": 40,
            "pause_on_high": False,
            "pause_on_critical": True,
        },
        "browser_tracker": {
            "mode": "gate",
            "ramp_order": 50,
            "pause_on_high": True,
            "pause_on_critical": True,
        },
        "clipboard_tracker": {
            "mode": "restart",
            "ramp_order": 60,
            "pause_on_high": False,
            "pause_on_critical": True,
        },
        "screenshot_loop": {
            "mode": "gate",
            "ramp_order": 70,
            "pause_on_high": True,
            "pause_on_critical": True,
        },
        "file_tracker": {
            "mode": "restart",
            "ramp_order": 80,
            "pause_on_high": True,
            "pause_on_critical": True,
        },
        "baseline_inventory": {
            "mode": "restart",
            "ramp_order": 90,
            "pause_on_high": True,
            "pause_on_critical": True,
        },
    }

    def __init__(self):
        # â”€â”€ DPI awareness (Windows) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Required so pyautogui coordinates match mss screen capture pixels
        if platform.system() == "Windows":
            try:
                import ctypes
                ctypes.windll.shcore.SetProcessDpiAwareness(2)  # PROCESS_PER_MONITOR_DPI_AWARE
            except Exception:
                try:
                    import ctypes
                    ctypes.windll.user32.SetProcessDPIAware()
                except Exception:
                    pass

        self.machine_id = get_machine_id()
        self.hostname = socket.gethostname()
        self.username = os.environ.get("USERNAME") or os.environ.get("USER", "unknown")
        self.running = True
        self.ws = None
        self.ws_connected = False
        self.last_browser_check = 0.0
        self.last_app: str = ""
        self.last_app_start: float = time.time()

        # â”€â”€ Offline sync queue (SQLite-backed, encrypted, crash-safe) â”€â”€â”€â”€
        from offline_queue import OfflineQueue, PRIORITY_HIGH, PRIORITY_NORMAL
        self._queue = OfflineQueue(
            machine_id        = self.machine_id,
            ws_send_fn        = None,              # set on WS connect
            http_post_fn      = http_post,
            http_post_json_fn = http_post_json,    # v2: partial batch support
        )
        self._PRIORITY_HIGH   = PRIORITY_HIGH
        self._PRIORITY_NORMAL = PRIORITY_NORMAL
        # asyncio event loop for WebRTC (runs in a dedicated thread)
        self._loop = asyncio.new_event_loop()
        self._loop_thread = None
        # WebRTC session registry
        try:
            from webrtc_agent import registry as _webrtc_registry
            self._webrtc = _webrtc_registry
        except Exception as exc:
            logger.warning(f"WebRTC features disabled during startup: {exc}")
            self._webrtc = None
        self._input_tracker = None
        self._input_bucket = None
        self._file_tracker = None
        self._network_tracker = None
        self._usb_tracker = None
        self._print_tracker = None
        self._clipboard_tracker = None
        self._baseline_inventory = None
        self._last_register_status = 0
        self._last_register_detail = ""
        self._config_screenshot_interval = max(30, SCREENSHOT_INTERVAL)
        self._config_browser_interval = max(30, ACTIVITY_SYNC_INTERVAL)
        self._config_heartbeat_interval = max(15, HEARTBEAT_INTERVAL)
        self._config_app_tracker_interval = max(5, APP_TRACKER_INTERVAL)
        self._config_network_interval = max(15, NETWORK_TRACKER_INTERVAL)
        self._config_usb_interval = max(5, USB_TRACKER_INTERVAL)
        self._config_print_interval = max(10, PRINT_TRACKER_INTERVAL)
        self._config_file_cache_fast_sweep_seconds = max(2.0, FILE_CACHE_FAST_SWEEP_SECONDS)
        self._config_file_cache_sweep_seconds = max(self._config_file_cache_fast_sweep_seconds, FILE_CACHE_SWEEP_SECONDS)
        self._config_file_cache_sweeper_enabled = bool(FILE_CACHE_SWEEPER_ENABLED)
        self._agent_self_throttle_enabled = bool(SELF_THROTTLE_ENABLED)
        self._agent_self_throttle_cpu_percent = max(50, SELF_THROTTLE_CPU_PERCENT)
        self._agent_self_throttle_memory_percent = max(50, SELF_THROTTLE_MEMORY_PERCENT)
        self._agent_self_throttle_queue_depth = max(50, SELF_THROTTLE_QUEUE_DEPTH)
        self._agent_self_throttle_multiplier = max(1.2, SELF_THROTTLE_INTERVAL_MULTIPLIER)
        self._agent_self_throttle_cooldown_seconds = max(30, SELF_THROTTLE_COOLDOWN_SECONDS)
        self._throttle_until_monotonic = 0.0
        self._throttle_reason = ""
        self._screenshot_interval = self._config_screenshot_interval
        self._browser_interval = self._config_browser_interval
        self._heartbeat_interval = self._config_heartbeat_interval
        self._app_tracker_interval = self._config_app_tracker_interval
        self._network_interval = self._config_network_interval
        self._usb_interval = self._config_usb_interval
        self._print_interval = self._config_print_interval
        self._file_cache_fast_sweep_seconds = self._config_file_cache_fast_sweep_seconds
        self._file_cache_sweep_seconds = self._config_file_cache_sweep_seconds
        self._file_cache_sweeper_enabled = self._config_file_cache_sweeper_enabled
        self._dlp_policy_version = 1
        self._dlp_policy_hash = ""
        self._dlp_rollout_mode = "monitor_only"
        self._dlp_policy_status = "legacy"
        self._phishing_policy_version = 1
        self._phishing_policy_hash = ""
        self._phishing_rollout_mode = "warn_only"
        self._phishing_policy_status = "legacy"
        try:
            from phishing_protection import PhishingProtection
            self._phishing = PhishingProtection(self.machine_id, self.username, post_json_fn=http_post_json)
        except Exception as exc:
            logger.debug(f"Phishing subsystem unavailable: {exc}")
            self._phishing = None
        try:
            from baseline_inventory import BaselineInventoryConfig

            self._baseline_inventory_config = BaselineInventoryConfig()
        except Exception as exc:
            logger.debug(f"Baseline inventory config unavailable: {exc}")
            self._baseline_inventory_config = None
        self._resource_monitor_interval = max(5, RESOURCE_MONITOR_INTERVAL)
        self._startup_ramp_step_seconds = max(5, STARTUP_RAMP_STEP_SECONDS)
        self._startup_stable_samples_required = max(1, STARTUP_STABLE_SAMPLES_REQUIRED)
        self._resource_high_cpu_percent = max(50, RESOURCE_HIGH_CPU_PERCENT)
        self._resource_high_memory_percent = max(50, RESOURCE_HIGH_MEMORY_PERCENT)
        self._resource_critical_cpu_percent = max(self._resource_high_cpu_percent, RESOURCE_CRITICAL_CPU_PERCENT)
        self._resource_critical_memory_percent = max(self._resource_high_memory_percent, RESOURCE_CRITICAL_MEMORY_PERCENT)
        self._subsystem_lock = threading.Lock()
        self._managed_subsystems = self._build_managed_subsystems()
        self._resource_state = {
            "timestamp": "",
            "cpu_percent": 0.0,
            "memory_percent": 0.0,
            "queue_depth": 0,
            "pressure": "startup",
            "stable": False,
            "stable_samples": 0,
            "reason": "startup",
        }
        self._refresh_effective_runtime()

    def _persist_registration_status(self, ok: bool, status: int, detail: str):
        payload = {
            "timestamp": _utcnow_iso(),
            "ok": bool(ok),
            "status": int(status or 0),
            "detail": (detail or "").strip(),
            "server_url": SERVER_URL,
            "machine_id": self.machine_id,
            "enroll_token_present": bool(AGENT_ENROLL_TOKEN),
        }
        try:
            REGISTRATION_STATUS_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.debug(f"Failed to persist registration status: {exc}")

    @staticmethod
    def _registration_reason(status: int, detail: str) -> str:
        if status == 401 and "enrollment" in (detail or "").lower():
            return "missing_or_invalid_enrollment_token"
        if status == 402:
            return "tenant_plan_or_license_restriction"
        if status == 403:
            return "tenant_mismatch_for_machine"
        if status == 0:
            return "connectivity_or_server_unreachable"
        return "unknown"

    def _build_managed_subsystems(self) -> dict[str, dict]:
        subsystems = {}
        for name, spec in self._STARTUP_SUBSYSTEM_SPECS.items():
            subsystems[name] = {
                "mode": spec["mode"],
                "ramp_order": int(spec["ramp_order"]),
                "pause_on_high": bool(spec["pause_on_high"]),
                "pause_on_critical": bool(spec["pause_on_critical"]),
                "ramp_ready": False,
                "enabled": False,
                "thread_started": False,
                "last_changed_at": "",
                "last_reason": "startup_deferred",
            }
        return subsystems

    def _set_subsystem_thread_started(self, name: str):
        with self._subsystem_lock:
            if name in self._managed_subsystems:
                self._managed_subsystems[name]["thread_started"] = True

    def _mark_subsystem_ramp_ready(self, name: str, reason: str):
        with self._subsystem_lock:
            if name not in self._managed_subsystems:
                return
            self._managed_subsystems[name]["ramp_ready"] = True
        self._reconcile_subsystem_states(reason)

    def _is_subsystem_enabled(self, name: str) -> bool:
        with self._subsystem_lock:
            state = self._managed_subsystems.get(name)
            return bool(state and state.get("enabled"))

    def _next_ramp_candidate(self) -> str | None:
        with self._subsystem_lock:
            pending = [
                (name, state["ramp_order"])
                for name, state in self._managed_subsystems.items()
                if not state["ramp_ready"]
            ]
        if not pending:
            return None
        pending.sort(key=lambda item: item[1])
        return pending[0][0]

    def _reconcile_subsystem_states(self, reason: str):
        with self._subsystem_lock:
            pressure = self._resource_state.get("pressure", "startup")
            changed = []
            for name, state in self._managed_subsystems.items():
                target_enabled = bool(state["ramp_ready"])
                if pressure == "startup":
                    target_enabled = False
                elif pressure == "critical" and state["pause_on_critical"]:
                    target_enabled = False
                elif pressure == "high" and state["pause_on_high"]:
                    target_enabled = False
                if state["enabled"] != target_enabled:
                    state["enabled"] = target_enabled
                    state["last_changed_at"] = _utcnow_iso()
                    state["last_reason"] = reason
                    changed.append((name, target_enabled))
        for name, enabled in changed:
            logger.info(
                "Startup controller %s subsystem=%s reason=%s",
                "enabled" if enabled else "paused",
                name,
                reason,
            )
            if not enabled:
                attr_name = self._subsystem_runtime_attr(name)
                if attr_name:
                    tracker = getattr(self, attr_name, None)
                    if tracker:
                        try:
                            tracker.stop()
                        except Exception:
                            pass

    def _subsystem_wait_until_enabled(self, name: str, poll_seconds: float = 1.0) -> bool:
        while self.running:
            if self._is_subsystem_enabled(name):
                return True
            time.sleep(poll_seconds)
        return False

    def _sleep_managed_interval(self, name: str, seconds: float, interrupt_on_pause: bool = True) -> bool:
        deadline = time.time() + max(0.0, float(seconds))
        while self.running and time.time() < deadline:
            if interrupt_on_pause and not self._is_subsystem_enabled(name):
                return False
            time.sleep(min(1.0, max(0.0, deadline - time.time())))
        return self.running and (not interrupt_on_pause or self._is_subsystem_enabled(name))

    def _snapshot_managed_subsystems(self) -> dict[str, dict]:
        with self._subsystem_lock:
            snapshot = {}
            for name, state in self._managed_subsystems.items():
                snapshot[name] = {
                    "mode": state["mode"],
                    "ramp_order": state["ramp_order"],
                    "ramp_ready": state["ramp_ready"],
                    "enabled": state["enabled"],
                    "thread_started": state["thread_started"],
                    "last_reason": state["last_reason"],
                    "last_changed_at": state["last_changed_at"],
                }
            return snapshot

    @staticmethod
    def _subsystem_runtime_attr(name: str) -> str | None:
        return {
            "print_tracker": "_print_tracker",
            "clipboard_tracker": "_clipboard_tracker",
            "file_tracker": "_file_tracker",
            "usb_tracker": "_usb_tracker",
            "network_tracker": "_network_tracker",
            "baseline_inventory": "_baseline_inventory",
        }.get(name)

    def _self_throttle_active(self) -> bool:
        return self._agent_self_throttle_enabled and time.monotonic() < self._throttle_until_monotonic

    def _refresh_effective_runtime(self, log_change: bool = False):
        was = (
            self._screenshot_interval,
            self._browser_interval,
            self._heartbeat_interval,
            self._app_tracker_interval,
            self._network_interval,
            self._usb_interval,
            self._print_interval,
            self._file_cache_fast_sweep_seconds,
            self._file_cache_sweep_seconds,
            self._file_cache_sweeper_enabled,
        )
        scale = self._agent_self_throttle_multiplier if self._self_throttle_active() else 1.0
        self._screenshot_interval = max(30, int(round(self._config_screenshot_interval * scale)))
        self._browser_interval = max(30, int(round(self._config_browser_interval * scale)))
        self._heartbeat_interval = max(15, int(round(self._config_heartbeat_interval * scale)))
        self._app_tracker_interval = max(5, int(round(self._config_app_tracker_interval * scale)))
        self._network_interval = max(15, int(round(self._config_network_interval * scale)))
        self._usb_interval = max(5, int(round(self._config_usb_interval * scale)))
        self._print_interval = max(10, int(round(self._config_print_interval * scale)))
        self._file_cache_fast_sweep_seconds = max(2.0, self._config_file_cache_fast_sweep_seconds * scale)
        self._file_cache_sweep_seconds = max(self._file_cache_fast_sweep_seconds, self._config_file_cache_sweep_seconds * scale)
        self._file_cache_sweeper_enabled = bool(self._config_file_cache_sweeper_enabled)

        if self._network_tracker:
            self._network_tracker.interval = self._network_interval
        if self._usb_tracker:
            self._usb_tracker.interval = self._usb_interval
        if self._print_tracker:
            self._print_tracker.interval = self._print_interval
        if self._file_tracker and hasattr(self._file_tracker, "update_runtime_config"):
            self._file_tracker.update_runtime_config(
                fast_sweep_seconds=self._file_cache_fast_sweep_seconds,
                recursive_sweep_seconds=self._file_cache_sweep_seconds,
                sweeper_enabled=self._file_cache_sweeper_enabled,
            )

        now = (
            self._screenshot_interval,
            self._browser_interval,
            self._heartbeat_interval,
            self._app_tracker_interval,
            self._network_interval,
            self._usb_interval,
            self._print_interval,
            self._file_cache_fast_sweep_seconds,
            self._file_cache_sweep_seconds,
            self._file_cache_sweeper_enabled,
        )
        if log_change and now != was:
            logger.info(
                "Agent effective runtime screenshot=%ss browser=%ss heartbeat=%ss app=%ss network=%ss usb=%ss print=%ss file_fast=%.1fs file_recursive=%.1fs sweeper=%s throttle=%s reason=%s",
                self._screenshot_interval,
                self._browser_interval,
                self._heartbeat_interval,
                self._app_tracker_interval,
                self._network_interval,
                self._usb_interval,
                self._print_interval,
                self._file_cache_fast_sweep_seconds,
                self._file_cache_sweep_seconds,
                self._file_cache_sweeper_enabled,
                self._self_throttle_active(),
                self._throttle_reason or "none",
            )

    def _evaluate_self_throttle(self, metrics: dict, queue_health: dict | None = None):
        if queue_health is None:
            try:
                queue_health = self._queue.get_health()
            except Exception:
                queue_health = {}

        if not self._agent_self_throttle_enabled:
            if self._throttle_until_monotonic:
                self._throttle_until_monotonic = 0.0
                self._throttle_reason = ""
                self._refresh_effective_runtime(log_change=True)
            return queue_health

        reasons = []
        cpu_percent = float(metrics.get("cpu_percent") or 0)
        memory_percent = float(metrics.get("memory_percent") or 0)
        queue_depth = int(queue_health.get("queue_depth") or 0)
        if cpu_percent >= self._agent_self_throttle_cpu_percent:
            reasons.append(f"cpu {cpu_percent:.0f}%")
        if memory_percent >= self._agent_self_throttle_memory_percent:
            reasons.append(f"memory {memory_percent:.0f}%")
        if queue_depth >= self._agent_self_throttle_queue_depth:
            reasons.append(f"queue {queue_depth}")

        now_mono = time.monotonic()
        if reasons:
            was_active = self._self_throttle_active()
            new_reason = ", ".join(reasons)
            self._throttle_until_monotonic = now_mono + self._agent_self_throttle_cooldown_seconds
            reason_changed = self._throttle_reason != new_reason
            self._throttle_reason = new_reason
            self._refresh_effective_runtime(log_change=(not was_active) or reason_changed)
        elif self._throttle_until_monotonic and now_mono >= self._throttle_until_monotonic:
            self._throttle_until_monotonic = 0.0
            self._throttle_reason = ""
            self._refresh_effective_runtime(log_change=True)

        return queue_health

    def _update_resource_state(self, metrics: dict, queue_health: dict):
        cpu_percent = float(metrics.get("cpu_percent") or 0)
        memory_percent = float(metrics.get("memory_percent") or 0)
        queue_depth = int(queue_health.get("queue_depth") or 0)
        pressure = "normal"
        reasons = []
        if cpu_percent >= self._resource_high_cpu_percent:
            reasons.append(f"cpu {cpu_percent:.0f}%")
        if memory_percent >= self._resource_high_memory_percent:
            reasons.append(f"memory {memory_percent:.0f}%")
        if queue_depth >= self._agent_self_throttle_queue_depth:
            reasons.append(f"queue {queue_depth}")
        if cpu_percent >= self._resource_critical_cpu_percent or memory_percent >= self._resource_critical_memory_percent:
            pressure = "critical"
        elif reasons:
            pressure = "high"
        stable_sample = pressure == "normal"
        with self._subsystem_lock:
            prior_pressure = self._resource_state.get("pressure", "startup")
            stable_samples = int(self._resource_state.get("stable_samples", 0))
            if stable_sample:
                stable_samples += 1
            else:
                stable_samples = 0
            stable = stable_samples >= self._startup_stable_samples_required
            reason = ", ".join(reasons) if reasons else "stable"
            self._resource_state = {
                "timestamp": _utcnow_iso(),
                "cpu_percent": cpu_percent,
                "memory_percent": memory_percent,
                "queue_depth": queue_depth,
                "pressure": pressure,
                "stable": stable,
                "stable_samples": stable_samples,
                "reason": reason,
            }
        if prior_pressure != pressure:
            self._reconcile_subsystem_states(f"resource_pressure:{pressure}:{reason}")

    def _resource_monitor_loop(self):
        while self.running:
            try:
                metrics = get_system_metrics()
                queue_health = self._evaluate_self_throttle(metrics)
                self._update_resource_state(metrics, queue_health or {})
            except Exception as exc:
                logger.debug(f"Resource monitor: {exc}")
            time.sleep(self._resource_monitor_interval)

    def _ramp_up_manager_loop(self):
        while self.running:
            try:
                candidate = self._next_ramp_candidate()
                if not candidate:
                    time.sleep(self._startup_ramp_step_seconds)
                    continue
                with self._subsystem_lock:
                    stable = bool(self._resource_state.get("stable"))
                    pressure = str(self._resource_state.get("pressure") or "startup")
                if not stable or pressure != "normal":
                    time.sleep(max(2, min(self._startup_ramp_step_seconds, self._resource_monitor_interval)))
                    continue
                self._mark_subsystem_ramp_ready(candidate, "startup_ramp_complete")
                time.sleep(self._startup_ramp_step_seconds)
            except Exception as exc:
                logger.debug(f"Ramp-up manager: {exc}")
                time.sleep(max(2, min(self._startup_ramp_step_seconds, self._resource_monitor_interval)))

    def _apply_agent_config(self, cfg: dict):
        """Apply server-pushed config: input tracker + DLP/phishing policy."""
        if not cfg:
            return

        performance = cfg.get("agent_performance") or {}
        startup_cfg = cfg.get("startup_controller") or performance.get("startup_controller") or {}
        resource_cfg = cfg.get("resource_monitor") or performance.get("resource_monitor") or {}
        try:
            screenshot_interval = int(performance.get("screenshot_interval_seconds", cfg.get("screenshot_interval_seconds", self._config_screenshot_interval)))
            self._config_screenshot_interval = max(30, screenshot_interval)
        except (TypeError, ValueError):
            pass
        try:
            browser_interval = int(performance.get("browser_sync_interval_seconds", cfg.get("browser_sync_interval_seconds", self._config_browser_interval)))
            self._config_browser_interval = max(30, browser_interval)
        except (TypeError, ValueError):
            pass
        try:
            heartbeat_interval = int(performance.get("heartbeat_interval_seconds", cfg.get("heartbeat_interval_seconds", self._config_heartbeat_interval)))
            self._config_heartbeat_interval = max(15, heartbeat_interval)
        except (TypeError, ValueError):
            pass
        try:
            app_interval = int(performance.get("app_tracker_interval_seconds", cfg.get("app_tracker_interval_seconds", self._config_app_tracker_interval)))
            self._config_app_tracker_interval = max(5, app_interval)
        except (TypeError, ValueError):
            pass
        try:
            network_interval = int(performance.get("network_interval_seconds", cfg.get("network_interval_seconds", self._config_network_interval)))
            self._config_network_interval = max(15, network_interval)
        except (TypeError, ValueError):
            pass
        try:
            usb_interval = int(performance.get("usb_interval_seconds", cfg.get("usb_interval_seconds", self._config_usb_interval)))
            self._config_usb_interval = max(5, usb_interval)
        except (TypeError, ValueError):
            pass
        try:
            print_interval = int(performance.get("print_interval_seconds", cfg.get("print_interval_seconds", self._config_print_interval)))
            self._config_print_interval = max(10, print_interval)
        except (TypeError, ValueError):
            pass
        try:
            fast_sweep = float(performance.get("file_cache_fast_sweep_seconds", cfg.get("file_cache_fast_sweep_seconds", self._config_file_cache_fast_sweep_seconds)))
            self._config_file_cache_fast_sweep_seconds = max(2.0, fast_sweep)
        except (TypeError, ValueError):
            pass
        try:
            recursive_sweep = float(performance.get("file_cache_recursive_sweep_seconds", cfg.get("file_cache_recursive_sweep_seconds", self._config_file_cache_sweep_seconds)))
            self._config_file_cache_sweep_seconds = max(self._config_file_cache_fast_sweep_seconds, recursive_sweep)
        except (TypeError, ValueError):
            pass
        sweeper_enabled = performance.get("file_cache_sweeper_enabled", cfg.get("file_cache_sweeper_enabled"))
        if sweeper_enabled is not None:
            self._config_file_cache_sweeper_enabled = bool(sweeper_enabled)

        self_throttle = performance.get("self_throttle") or {}
        enabled = self_throttle.get("enabled", cfg.get("agent_self_throttle_enabled"))
        if enabled is not None:
            self._agent_self_throttle_enabled = bool(enabled)
        try:
            cpu_threshold = int(self_throttle.get("cpu_percent_threshold", cfg.get("agent_self_throttle_cpu_percent", self._agent_self_throttle_cpu_percent)))
            self._agent_self_throttle_cpu_percent = max(50, cpu_threshold)
        except (TypeError, ValueError):
            pass
        try:
            memory_threshold = int(self_throttle.get("memory_percent_threshold", cfg.get("agent_self_throttle_memory_percent", self._agent_self_throttle_memory_percent)))
            self._agent_self_throttle_memory_percent = max(50, memory_threshold)
        except (TypeError, ValueError):
            pass
        try:
            queue_threshold = int(self_throttle.get("queue_depth_threshold", cfg.get("agent_self_throttle_queue_depth", self._agent_self_throttle_queue_depth)))
            self._agent_self_throttle_queue_depth = max(50, queue_threshold)
        except (TypeError, ValueError):
            pass
        try:
            interval_multiplier = float(self_throttle.get("interval_multiplier", cfg.get("agent_self_throttle_multiplier", self._agent_self_throttle_multiplier)))
            self._agent_self_throttle_multiplier = max(1.2, interval_multiplier)
        except (TypeError, ValueError):
            pass
        try:
            cooldown_seconds = int(self_throttle.get("cooldown_seconds", cfg.get("agent_self_throttle_cooldown_seconds", self._agent_self_throttle_cooldown_seconds)))
            self._agent_self_throttle_cooldown_seconds = max(30, cooldown_seconds)
        except (TypeError, ValueError):
            pass
        try:
            self._startup_ramp_step_seconds = max(
                5,
                int(startup_cfg.get("ramp_step_seconds", self._startup_ramp_step_seconds)),
            )
        except (TypeError, ValueError):
            pass
        try:
            self._startup_stable_samples_required = max(
                1,
                int(startup_cfg.get("stable_samples_required", self._startup_stable_samples_required)),
            )
        except (TypeError, ValueError):
            pass
        try:
            self._resource_monitor_interval = max(
                5,
                int(resource_cfg.get("interval_seconds", self._resource_monitor_interval)),
            )
        except (TypeError, ValueError):
            pass
        try:
            self._resource_high_cpu_percent = max(
                50,
                int(resource_cfg.get("high_cpu_percent", self._resource_high_cpu_percent)),
            )
        except (TypeError, ValueError):
            pass
        try:
            self._resource_high_memory_percent = max(
                50,
                int(resource_cfg.get("high_memory_percent", self._resource_high_memory_percent)),
            )
        except (TypeError, ValueError):
            pass
        try:
            self._resource_critical_cpu_percent = max(
                self._resource_high_cpu_percent,
                int(resource_cfg.get("critical_cpu_percent", self._resource_critical_cpu_percent)),
            )
        except (TypeError, ValueError):
            pass
        try:
            self._resource_critical_memory_percent = max(
                self._resource_high_memory_percent,
                int(resource_cfg.get("critical_memory_percent", self._resource_critical_memory_percent)),
            )
        except (TypeError, ValueError):
            pass

        self._refresh_effective_runtime(log_change=True)
        self._reconcile_subsystem_states("backend_config_update")
        logger.info(
            "Agent throttle policy enabled=%s cpu=%s memory=%s queue=%s multiplier=%.2f cooldown=%ss",
            self._agent_self_throttle_enabled,
            self._agent_self_throttle_cpu_percent,
            self._agent_self_throttle_memory_percent,
            self._agent_self_throttle_queue_depth,
            self._agent_self_throttle_multiplier,
            self._agent_self_throttle_cooldown_seconds,
        )

        # â”€â”€ DLP policy hot-reload â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            effective = cfg.get("dlp_policy") or {}
            self._dlp_policy_version = int(cfg.get("dlp_policy_version") or effective.get("policy_version") or 1)
            self._dlp_policy_hash = str(cfg.get("dlp_policy_hash") or effective.get("policy_hash") or "")
            self._dlp_rollout_mode = str(effective.get("rollout_mode") or "monitor_only")
            self._dlp_policy_status = "effective_policy_loaded" if effective else "legacy_policy_loaded"
            from file_tracker import _get_dlp_engine
            engine = _get_dlp_engine()
            if engine and hasattr(engine, "update_config"):
                engine.update_config(
                    enabled=cfg.get("dlp_enabled", effective.get("dlp_enabled")),
                    keywords=cfg.get("dlp_keywords", effective.get("keywords")),
                    custom_patterns=cfg.get("dlp_custom_patterns", effective.get("custom_patterns")),
                    risk_thresholds=cfg.get("dlp_risk_thresholds", effective.get("risk_thresholds")),
                )
            if getattr(self, "_file_tracker", None) and hasattr(self._file_tracker, "set_dlp_context"):
                self._file_tracker.set_dlp_context(effective, actor_username=self.username)
            logger.info(
                "DLP policy update version=%s rollout=%s hash=%s status=%s",
                self._dlp_policy_version,
                self._dlp_rollout_mode,
                self._dlp_policy_hash[:12] if self._dlp_policy_hash else "n/a",
                self._dlp_policy_status,
            )
        except Exception as e:
            logger.debug(f"DLP config update: {e}")

        # â”€â”€ Phishing policy hot-reload â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            effective_phishing = cfg.get("phishing_policy") or {}
            self._phishing_policy_version = int(
                cfg.get("phishing_policy_version") or effective_phishing.get("policy_version") or 1
            )
            self._phishing_policy_hash = str(
                cfg.get("phishing_policy_hash") or effective_phishing.get("policy_hash") or ""
            )
            self._phishing_rollout_mode = str(effective_phishing.get("rollout_mode") or "warn_only")
            self._phishing_policy_status = "effective_policy_loaded" if effective_phishing else "legacy_policy_loaded"
            if self._phishing:
                self._phishing.update_policy(
                    effective_phishing,
                    version=self._phishing_policy_version,
                    policy_hash=self._phishing_policy_hash,
                )
            logger.info(
                "Phishing policy update version=%s rollout=%s hash=%s status=%s",
                self._phishing_policy_version,
                self._phishing_rollout_mode,
                self._phishing_policy_hash[:12] if self._phishing_policy_hash else "n/a",
                self._phishing_policy_status,
            )
        except Exception as e:
            logger.debug(f"Phishing config update: {e}")

        # Baseline inventory subsystem config
        try:
            baseline_cfg = cfg.get("baseline_inventory") or {}
            if self._baseline_inventory_config is not None:
                from baseline_inventory import BaselineInventoryConfig

                self._baseline_inventory_config = BaselineInventoryConfig.from_payload(baseline_cfg)
                if self._baseline_inventory:
                    self._baseline_inventory.update_config(self._baseline_inventory_config)
                logger.info(
                    "Baseline inventory config enabled=%s workers=%s upload_batch=%s upload_interval=%ss",
                    self._baseline_inventory_config.enabled,
                    self._baseline_inventory_config.worker_count,
                    self._baseline_inventory_config.upload_batch_size,
                    self._baseline_inventory_config.upload_interval_seconds,
                )
        except Exception as e:
            logger.debug(f"Baseline inventory config update: {e}")

        # â”€â”€ Input tracker â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        try:
            from input_tracker import InputTracker, supported_platform
        except ImportError:
            return
        if not supported_platform():
            return
        want = bool(cfg.get("track_input_activity"))
        try:
            bucket = int(cfg.get("input_bucket_seconds", 30))
        except (TypeError, ValueError):
            bucket = 30
        if want:
            need = self._input_tracker is None or self._input_bucket != bucket
            if need:
                if self._input_tracker:
                    self._input_tracker.stop()
                self._input_bucket = bucket
                self._input_tracker = InputTracker(
                    self.machine_id,
                    _utcnow_iso,
                    get_active_window,
                    lambda k, d: self._enqueue(k, d),
                    bucket_seconds=bucket,
                )
                self._input_tracker.start()
                logger.info("Input activity tracking (Tier B) enabled")
        else:
            if self._input_tracker:
                self._input_tracker.stop()
                self._input_tracker = None
                self._input_bucket = None
                logger.info("Input activity tracking disabled")

    def _run_event_loop(self):
        """Run the asyncio loop in a background thread for WebRTC."""
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def register(self):
        data = {
            "machine_id": self.machine_id,
            "hostname": self.hostname,
            "os": OS,
            "os_version": platform.version(),
            "username": self.username,
            "ip_address": get_ip_address(),
            "mac_address": get_mac_address(),
            "consent_given": True,
            "consent_timestamp": _safe_consent_timestamp(),
            "first_seen": _utcnow_iso(),
            "agent_version": AGENT_VERSION,
        }
        ok, status, detail = http_post_with_status("/api/machines/register", data)
        self._last_register_status = int(status or 0)
        self._last_register_detail = (detail or "").strip()
        self._persist_registration_status(ok=ok, status=self._last_register_status, detail=self._last_register_detail)
        return ok

    def _register_with_retry(self, max_attempts: int = 10, base_delay: float = 5.0):
        """Retry registration until success or max_attempts exhausted.
        Uses exponential backoff capped at 120 s. Returns True on success."""
        permanent_statuses = {401, 402, 403}
        for attempt in range(1, max_attempts + 1):
            if self.register():
                logger.info(f"Machine registered successfully (attempt {attempt})")
                return True
            if self._last_register_status in permanent_statuses:
                reason = self._registration_reason(self._last_register_status, self._last_register_detail)
                logger.error(
                    "Registration rejected permanently status=%s reason=%s detail=%s",
                    self._last_register_status,
                    reason,
                    self._last_register_detail or "No detail from server",
                )
                return False
            delay = min(base_delay * (2 ** (attempt - 1)), 120.0)
            logger.warning(
                f"Registration failed (attempt {attempt}/{max_attempts}). "
                f"status={self._last_register_status or 'n/a'} "
                f"detail={self._last_register_detail or 'n/a'}. "
                f"Check CROPSENTINEL_ENROLL_TOKEN and server connectivity. "
                f"Retrying in {delay:.0f}sâ€¦"
            )
            # Sleep in short increments so self.running=False can abort the loop.
            deadline = time.time() + delay
            while time.time() < deadline:
                if not self.running:
                    return False
                time.sleep(1)
        logger.error(
            "Registration failed after %d attempts. Agent startup is blocked "
            "until enrollment or connectivity is fixed.", max_attempts
        )
        return False

    def start(self):
        logger.info(f"CropSentinel Agent starting. Machine: {self.machine_id} | Host: {self.hostname}")
        if not self._register_with_retry():
            logger.error(
                "Agent startup aborted because machine registration did not succeed. "
                "No telemetry threads were started."
            )
            self.running = False
            return

        # Start the offline sync queue (background threads for sync + cleanup)
        self._queue.start()

        # Start dedicated asyncio loop thread (needed for WebRTC)
        self._loop_thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self._loop_thread.start()

        logger.info(
            "Agent performance profile screenshot=%ss browser=%ss heartbeat=%ss app=%ss network=%ss usb=%ss print=%ss file_fast=%.1fs file_recursive=%.1fs sweeper=%s",
            self._screenshot_interval,
            self._browser_interval,
            self._heartbeat_interval,
            self._app_tracker_interval,
            self._network_interval,
            self._usb_interval,
            self._print_interval,
            self._file_cache_fast_sweep_seconds,
            self._file_cache_sweep_seconds,
            self._file_cache_sweeper_enabled,
        )

        core_threads = [
            threading.Thread(target=self._ws_loop, daemon=True, name="agent-ws"),
            threading.Thread(target=self._heartbeat_loop, daemon=True, name="agent-heartbeat"),
            threading.Thread(target=self._resource_monitor_loop, daemon=True, name="agent-resource-monitor"),
            threading.Thread(target=self._ramp_up_manager_loop, daemon=True, name="agent-ramp-up"),
        ]
        for thread in core_threads:
            thread.start()

        managed_threads = {
            "app_tracker": self._app_tracker,
            "browser_tracker": self._browser_tracker,
            "screenshot_loop": self._screenshot_loop,
            "print_tracker": self._print_tracker_loop,
            "clipboard_tracker": self._clipboard_tracker_loop,
            "file_tracker": self._file_tracker_loop,
            "usb_tracker": self._usb_tracker_loop,
            "network_tracker": self._network_tracker_loop,
            "baseline_inventory": self._baseline_inventory_loop,
        }
        for name, target in managed_threads.items():
            thread = threading.Thread(target=target, daemon=True, name=f"agent-{name}")
            thread.start()
            self._set_subsystem_thread_started(name)

        # Main thread keeps running
        try:
            while self.running:
                time.sleep(5)
        except KeyboardInterrupt:
            pass
        finally:
            self._graceful_shutdown()

    def _graceful_shutdown(self):
        """Flush buffers, stop trackers, and clean up all subsystems."""
        logger.info("Graceful shutdown initiated")
        self.running = False

        # Stop all trackers
        for name in ("_input_tracker", "_file_tracker", "_network_tracker",
                      "_usb_tracker", "_print_tracker", "_clipboard_tracker"):
            tracker = getattr(self, name, None)
            if tracker:
                try:
                    tracker.stop()
                    logger.debug(f"Stopped {name}")
                except Exception:
                    pass
                setattr(self, name, None)

        if self._baseline_inventory:
            try:
                self._baseline_inventory.stop()
                logger.debug("Stopped baseline inventory subsystem")
            except Exception as exc:
                logger.debug(f"Baseline inventory shutdown error: {exc}")
            self._baseline_inventory = None

        # Stop offline queue (flushes write buffer + pending WS acks)
        try:
            self._queue.stop()
            logger.info("Offline queue stopped cleanly")
        except Exception as e:
            logger.error(f"Queue shutdown error: {e}")

        # Clean up WebRTC sessions
        if self._webrtc and self._loop:
            try:
                asyncio.run_coroutine_threadsafe(
                    self._webrtc.stop_all(), self._loop
                ).result(timeout=3)
            except Exception:
                pass

        # Stop asyncio loop
        if self._loop and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)

        logger.info("Shutdown complete")

    def _ws_loop(self):
        """WebSocket connection with auto-reconnect"""
        while self.running:
            try:
                import websocket as ws_lib  # websocket-client
                ws_url = f"{WS_URL}/ws/agent/{self.machine_id}"
                logger.info(f"Connecting WS: {ws_url}")
                ws_headers = []
                if AGENT_API_KEY:
                    ws_headers.append(f"X-CropSentinel-Agent-Key: {AGENT_API_KEY}")
                if AGENT_ENROLL_TOKEN:
                    ws_headers.append(f"X-CropSentinel-Enroll-Token: {AGENT_ENROLL_TOKEN}")

                def on_message(ws, msg):
                    try:
                        data = json.loads(msg)
                    except (json.JSONDecodeError, TypeError):
                        logger.warning(f"Invalid JSON from server: {msg[:100]}")
                        return
                    if not isinstance(data, dict):
                        return
                    msg_type = data.get("type", "")

                    if msg_type == "take_screenshot":
                        self._send_screenshot()

                    elif msg_type == "remote_command":
                        import threading as _t
                        _t.Thread(target=self._handle_remote_command, args=(data,), daemon=True).start()

                    # â”€â”€ WebRTC signalling â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
                    elif msg_type == "webrtc_offer_req":
                        sid = data.get("session_id", "")
                        session_kind = str(data.get("session_kind", "live") or "live").lower()
                        logger.info(f"WebRTC offer requested for session {sid[:8]}")
                        import threading as _t
                        _t.Thread(
                            target=self._start_webrtc_session,
                            args=(sid, session_kind),
                            daemon=True,
                        ).start()

                    elif msg_type == "webrtc_answer":
                        sid         = data.get("session_id", "")
                        sdp         = data.get("sdp")
                        ice_restart = bool(data.get("ice_restart", False))
                        asyncio.run_coroutine_threadsafe(
                            self._webrtc_handle_answer(sid, sdp, ice_restart),
                            self._loop,
                        )

                    elif msg_type == "webrtc_ice":
                        sid       = data.get("session_id", "")
                        candidate = data.get("candidate")
                        asyncio.run_coroutine_threadsafe(
                            self._webrtc_handle_ice(sid, candidate),
                            self._loop,
                        )

                    elif msg_type == "webrtc_end":
                        sid = data.get("session_id", "")
                        asyncio.run_coroutine_threadsafe(
                            self._webrtc_end_session(sid),
                            self._loop,
                        )

                    elif msg_type == "event_ack":
                        # v2: ACK-based WebSocket delivery confirmation
                        self._queue.handle_ws_ack(data)

                    elif msg_type == "ack":
                        c = data.get("config")
                        if c:
                            self._apply_agent_config(c)

                def on_open(ws):
                    self.ws_connected = True
                    self._queue.set_ws(lambda msg: ws.send(msg))
                    logger.info("WS connected")

                def on_close(ws, code, msg):
                    self.ws_connected = False
                    self._queue.set_ws(None)
                    logger.info(f"WS closed: {code}")

                def on_error(ws, err):
                    logger.debug(f"WS error: {err}")

                self.ws = ws_lib.WebSocketApp(
                    ws_url,
                    header=ws_headers,
                    on_message=on_message,
                    on_open=on_open,
                    on_close=on_close,
                    on_error=on_error,
                )
                self.ws.run_forever(reconnect=5)
            except ImportError:
                logger.info("websocket-client not installed, using HTTP fallback")
                break
            except Exception as e:
                logger.error(f"WS loop error: {e}")
            time.sleep(10)

    # â”€â”€ WebRTC helpers (called from the asyncio loop thread) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _ws_send_json(self, data: dict):
        """Thread-safe JSON send on the WebSocket (websocket-client)."""
        if self.ws_connected and self.ws:
            try:
                self.ws.send(json.dumps(data))
            except Exception as e:
                logger.debug(f"WS send error: {e}")

    def _start_webrtc_session(self, session_id: str, session_kind: str = "live"):
        """Blocking wrapper â€” starts WebRTC session on the asyncio loop."""
        if not self._webrtc or not self._loop:
            logger.warning("WebRTC registry not available")
            return
        future = asyncio.run_coroutine_threadsafe(
            self._webrtc.handle_offer_req(session_id, self._ws_send_json, session_kind=session_kind),
            self._loop,
        )
        try:
            future.result(timeout=10)
        except Exception as e:
            logger.error(f"WebRTC session start error: {e}")

    async def _webrtc_handle_answer(self, session_id: str, sdp: dict, ice_restart: bool = False):
        if self._webrtc and sdp:
            await self._webrtc.handle_answer(session_id, sdp, ice_restart=ice_restart)

    async def _webrtc_handle_ice(self, session_id: str, candidate: dict):
        if self._webrtc and candidate:
            await self._webrtc.handle_ice(session_id, candidate)

    async def _webrtc_end_session(self, session_id: str):
        if self._webrtc:
            await self._webrtc.handle_end(session_id)

    def _app_tracker(self):
        """Track active application every 5 seconds"""
        app_start = time.time()
        current_app = ""
        current_title = ""

        while self.running:
            if not self._subsystem_wait_until_enabled("app_tracker"):
                break
            try:
                app_name, title, proc = get_active_window()
                now = time.time()

                if app_name != current_app:
                    if current_app:
                        dur = int(now - app_start)
                        entry = {
                            "machine_id": self.machine_id,
                            "timestamp": _utcnow_iso(),
                            "app_name": current_app,
                            "window_title": current_title,
                            "process_name": current_app.lower(),
                            "duration_seconds": dur,
                            "is_active": True,
                        }
                        self._enqueue("app", entry)
                    current_app = app_name
                    current_title = title
                    app_start = now
            except Exception as e:
                logger.debug(f"App tracker: {e}")
            if not self._sleep_managed_interval("app_tracker", self._app_tracker_interval):
                app_start = time.time()
                current_app = ""
                current_title = ""

    def _browser_tracker(self):
        """Check browser history every 30 seconds"""
        while self.running:
            if not self._subsystem_wait_until_enabled("browser_tracker"):
                break
            try:
                now = time.time()
                entries = get_browser_history_entries(self.last_browser_check or None)
                for e in entries:
                    e["machine_id"] = self.machine_id
                    self._enqueue("browser", e)
                    if getattr(self, "_file_tracker", None) and hasattr(self._file_tracker, "handle_browser_upload_event"):
                        try:
                            self._file_tracker.handle_browser_upload_event(e)
                        except Exception as exc:
                            logger.debug(f"Browser DLP correlation: {exc}")
                    app_name, _, process_name = get_active_window()
                    if self._phishing:
                        phishing_event = self._phishing.evaluate_browser_entry(
                            e,
                            app_name=app_name,
                            process_name=process_name,
                        )
                        if phishing_event:
                            self._enqueue("phishing_alert", phishing_event)
                            self._phishing.warn_user(phishing_event)
                    # v2: feed browser domains to DLP destination detector
                    domain = e.get("domain", "")
                    if domain:
                        self._push_browser_to_dlp(domain)
                self.last_browser_check = now
            except Exception as ex:
                logger.debug(f"Browser tracker: {ex}")
            if not self._sleep_managed_interval("browser_tracker", self._browser_interval):
                self.last_browser_check = 0.0

    def _screenshot_loop(self):
        """Take screenshots at configured interval"""
        while self.running:
            if not self._subsystem_wait_until_enabled("screenshot_loop"):
                break
            if not self._sleep_managed_interval("screenshot_loop", 10):
                continue
            try:
                self._send_screenshot()
            except Exception as e:
                logger.debug(f"Screenshot loop: {e}")
            self._sleep_managed_interval("screenshot_loop", self._screenshot_interval)

    def _send_screenshot(self, trigger="scheduled"):
        img_b64 = take_screenshot()
        if img_b64:
            data = {
                "machine_id": self.machine_id,
                "timestamp": _utcnow_iso(),
                "image_data": img_b64,
                "trigger": trigger,
            }
            if self.ws_connected and self.ws:
                try:
                    self.ws.send(json.dumps({"type": "screenshot", **data}))
                    return
                except:
                    pass
            http_post("/api/activity/screenshot", data)

    def _build_agent_health_snapshot(self, queue_health: dict | None = None):
        if queue_health is None:
            queue_health = {}
            try:
                queue_health = self._queue.get_health()
            except Exception as exc:
                logger.debug(f"Queue health unavailable: {exc}")
        with self._subsystem_lock:
            resource_state = dict(self._resource_state)
        return {
            "ws_connected": bool(self.ws_connected and self.ws),
            "runtime": {
                "screenshot_interval_seconds": self._screenshot_interval,
                "browser_sync_interval_seconds": self._browser_interval,
                "heartbeat_interval_seconds": self._heartbeat_interval,
                "app_tracker_interval_seconds": self._app_tracker_interval,
                "network_interval_seconds": self._network_interval,
                "usb_interval_seconds": self._usb_interval,
                "print_interval_seconds": self._print_interval,
                "file_cache_fast_sweep_seconds": self._file_cache_fast_sweep_seconds,
                "file_cache_recursive_sweep_seconds": self._file_cache_sweep_seconds,
                "file_cache_sweeper_enabled": self._file_cache_sweeper_enabled,
                "configured_screenshot_interval_seconds": self._config_screenshot_interval,
                "configured_browser_sync_interval_seconds": self._config_browser_interval,
                "configured_heartbeat_interval_seconds": self._config_heartbeat_interval,
                "configured_app_tracker_interval_seconds": self._config_app_tracker_interval,
                "configured_network_interval_seconds": self._config_network_interval,
                "configured_usb_interval_seconds": self._config_usb_interval,
                "configured_print_interval_seconds": self._config_print_interval,
            },
            "queue": queue_health,
            "policy": {
                "dlp_policy_version": self._dlp_policy_version,
                "dlp_policy_hash": self._dlp_policy_hash,
                "phishing_policy_version": self._phishing_policy_version,
                "phishing_policy_hash": self._phishing_policy_hash,
            },
            "self_throttle": {
                "enabled": self._agent_self_throttle_enabled,
                "active": self._self_throttle_active(),
                "reason": self._throttle_reason,
                "cpu_percent_threshold": self._agent_self_throttle_cpu_percent,
                "memory_percent_threshold": self._agent_self_throttle_memory_percent,
                "queue_depth_threshold": self._agent_self_throttle_queue_depth,
                "interval_multiplier": self._agent_self_throttle_multiplier,
                "cooldown_seconds": self._agent_self_throttle_cooldown_seconds,
            },
            "startup_controller": {
                "ramp_step_seconds": self._startup_ramp_step_seconds,
                "stable_samples_required": self._startup_stable_samples_required,
                "resource_monitor_interval_seconds": self._resource_monitor_interval,
                "resource_pressure": resource_state,
                "subsystems": self._snapshot_managed_subsystems(),
            },
        }

    def _heartbeat_loop(self):
        """Send heartbeat every 15 seconds"""
        _hb_count = 0
        while self.running:
            try:
                metrics = get_system_metrics()
                queue_health = self._evaluate_self_throttle(metrics)
                app_name, _, _ = get_active_window()
                data = {
                    "machine_id": self.machine_id,
                    "timestamp": _utcnow_iso(),
                    "schema_version": AGENT_PROTOCOL_SCHEMA_VERSION,
                    "agent_version": AGENT_VERSION,
                    "cpu_percent": metrics["cpu_percent"],
                    "memory_percent": metrics["memory_percent"],
                    "active_app": app_name,
                    "idle_seconds": get_idle_seconds(),
                    "phishing_policy_version": self._phishing_policy_version,
                    "phishing_policy_hash": self._phishing_policy_hash,
                    "dlp_policy_version": self._dlp_policy_version,
                    "dlp_policy_hash": self._dlp_policy_hash,
                    "capabilities": _agent_capabilities(),
                    "agent_health": self._build_agent_health_snapshot(queue_health=queue_health),
                }
                if self.ws_connected and self.ws:
                    try:
                        self.ws.send(json.dumps({"type": "heartbeat", **data}))
                    except Exception:
                        j = http_post_json("/api/activity/heartbeat", data)
                        if j and j.get("config"):
                            self._apply_agent_config(j["config"])
                else:
                    j = http_post_json("/api/activity/heartbeat", data)
                    if j and j.get("config"):
                        self._apply_agent_config(j["config"])
            except Exception as e:
                logger.debug(f"Heartbeat: {e}")

            # v2: periodic fingerprint store cleanup (~every 25 min)
            _hb_count += 1
            if _hb_count % 100 == 0:
                try:
                    from file_tracker import _get_dlp_engine
                    engine = _get_dlp_engine()
                    if engine:
                        engine.cleanup_fingerprints()
                except Exception:
                    pass

            time.sleep(self._heartbeat_interval)

    def _handle_remote_command(self, data: dict):
        """
        Execute a remote command sent by the admin dashboard.
        Supported actions: screenshot, lock_screen, open_url, show_message,
                           mute_audio, unmute_audio, sleep, logout_user
        """
        action = data.get('action', '')
        value  = data.get('value', '')
        status = 'ok'
        detail = ''

        try:
            if action not in ALLOWED_REMOTE_COMMANDS:
                raise ValueError(f"Unsupported action: {action}")

            if action == 'screenshot':
                self._send_screenshot(trigger='remote')
                detail = 'Screenshot taken'

            elif action == 'lock_screen':
                if OS == 'Windows':
                    import ctypes
                    ctypes.windll.user32.LockWorkStation()
                elif OS == 'Darwin':
                    subprocess.Popen(['pmset', 'displaysleepnow'])
                else:
                    subprocess.Popen(['xdg-screensaver', 'lock'])
                detail = 'Screen locked'

            elif action == 'open_url':
                import webbrowser
                webbrowser.open(value)
                detail = f'Opened: {value}'

            elif action == 'show_message':
                if OS == 'Windows':
                    import ctypes
                    ctypes.windll.user32.MessageBoxW(0, value, 'Message from Admin', 0x40)
                elif OS == 'Darwin':
                    msg_script = ('display dialog "' + value + '" with title "Admin Message" buttons {"OK"} default button "OK"')
                    subprocess.Popen(['osascript', '-e', msg_script])
                else:
                    try:
                        subprocess.Popen(['zenity', '--info', '--text', value, '--title', 'Admin Message'])
                    except Exception:
                        subprocess.Popen(['notify-send', 'Admin Message', value])
                detail = 'Message shown'

            elif action == 'mute_audio':
                if OS == 'Windows':
                    subprocess.run(['powershell', '-Command',
                        '(New-Object -ComObject WScript.Shell).SendKeys([char]173)'],
                        capture_output=True)
                elif OS == 'Darwin':
                    subprocess.run(['osascript', '-e', 'set volume output muted true'], capture_output=True)
                else:
                    subprocess.run(['amixer', '-D', 'pulse', 'sset', 'Master', 'mute'], capture_output=True)
                detail = 'Audio muted'

            elif action == 'unmute_audio':
                if OS == 'Windows':
                    subprocess.run(['powershell', '-Command',
                        '(New-Object -ComObject WScript.Shell).SendKeys([char]173)'],
                        capture_output=True)
                elif OS == 'Darwin':
                    subprocess.run(['osascript', '-e', 'set volume output muted false'], capture_output=True)
                else:
                    subprocess.run(['amixer', '-D', 'pulse', 'sset', 'Master', 'unmute'], capture_output=True)
                detail = 'Audio unmuted'

            elif action == 'sleep':
                if OS == 'Windows':
                    subprocess.Popen(['rundll32.exe', 'powrprof.dll,SetSuspendState', '0,1,0'])
                elif OS == 'Darwin':
                    subprocess.Popen(['pmset', 'sleepnow'])
                else:
                    subprocess.Popen(['systemctl', 'suspend'])
                detail = 'Sleep command sent'

            elif action == 'logout_user':
                if OS == 'Windows':
                    subprocess.Popen(['shutdown', '/l'])
                elif OS == 'Darwin':
                    subprocess.Popen(['osascript', '-e', 'tell application "System Events" to log out'])
                else:
                    subprocess.Popen(['pkill', '-KILL', '-u', os.environ.get('USER', '')])
                detail = 'Logout command sent'

            else:
                status = 'unknown'
                detail = f'Unknown action: {action}'

        except Exception as e:
            status = 'error'
            detail = str(e)
            logger.error(f'Remote command {action} failed: {e}')

        # Report result back
        result = {
            'type': 'remote_command',
            'action': action,
            'status': status,
            'detail': detail,
        }
        if self.ws_connected and self.ws:
            try:
                self.ws.send(json.dumps(result))
            except Exception:
                pass
        logger.info(f'Remote command: {action} -> {status}: {detail}')

    # â”€â”€ Insider Threat Trackers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _print_tracker_loop(self):
        while self.running:
            if not self._subsystem_wait_until_enabled("print_tracker"):
                break
            try:
                from print_tracker import PrintTracker

                tracker = PrintTracker(self.machine_id, self._enqueue, interval=self._print_interval)
                self._print_tracker = tracker
                tracker.run()
            except Exception as e:
                logger.error(f"Print tracker failed: {e}")
            finally:
                if self._print_tracker:
                    try:
                        self._print_tracker.stop()
                    except Exception:
                        pass
                self._print_tracker = None
            if self.running and self._is_subsystem_enabled("print_tracker"):
                time.sleep(5)

    def _clipboard_tracker_loop(self):
        while self.running:
            if not self._subsystem_wait_until_enabled("clipboard_tracker"):
                break
            try:
                from clipboard_tracker import ClipboardTracker

                def _on_clipboard(payload):
                    tracker = getattr(self, "_file_tracker", None)
                    if tracker and hasattr(tracker, "handle_clipboard_text"):
                        tracker.handle_clipboard_text(payload)

                tracker = ClipboardTracker(_on_clipboard)
                self._clipboard_tracker = tracker
                tracker.run()
            except Exception as e:
                logger.error(f"Clipboard tracker failed: {e}")
            finally:
                if self._clipboard_tracker:
                    try:
                        self._clipboard_tracker.stop()
                    except Exception:
                        pass
                self._clipboard_tracker = None
            if self.running and self._is_subsystem_enabled("clipboard_tracker"):
                time.sleep(5)

    def _file_tracker_loop(self):
        while self.running:
            if not self._subsystem_wait_until_enabled("file_tracker"):
                break
            try:
                from file_tracker import FileTracker

                tracker = FileTracker(
                    self.machine_id,
                    self._enqueue,
                    fast_sweep_seconds=self._file_cache_fast_sweep_seconds,
                    recursive_sweep_seconds=self._file_cache_sweep_seconds,
                    cache_sweeper_enabled=self._file_cache_sweeper_enabled,
                )
                tracker.set_dlp_context(
                    {
                        "rollout_mode": self._dlp_rollout_mode,
                        "policy_version": self._dlp_policy_version,
                        "policy_hash": self._dlp_policy_hash,
                    },
                    actor_username=self.username,
                )
                self._file_tracker = tracker
                tracker.run()
            except Exception as e:
                logger.error(f"File tracker failed: {e}")
            finally:
                if self._file_tracker:
                    try:
                        self._file_tracker.stop()
                    except Exception:
                        pass
                self._file_tracker = None
            if self.running and self._is_subsystem_enabled("file_tracker"):
                time.sleep(5)

    def _usb_tracker_loop(self):
        while self.running:
            if not self._subsystem_wait_until_enabled("usb_tracker"):
                break
            try:
                from usb_tracker import USBTracker

                tracker = USBTracker(self.machine_id, self._enqueue, interval=self._usb_interval)
                self._usb_tracker = tracker
                tracker.run()
            except Exception as e:
                logger.error(f"USB tracker failed: {e}")
            finally:
                if self._usb_tracker:
                    try:
                        self._usb_tracker.stop()
                    except Exception:
                        pass
                self._usb_tracker = None
            if self.running and self._is_subsystem_enabled("usb_tracker"):
                time.sleep(5)

    def _network_tracker_loop(self):
        while self.running:
            if not self._subsystem_wait_until_enabled("network_tracker"):
                break
            try:
                from network_tracker import NetworkTracker

                def _network_enqueue(kind, data):
                    """Wrapper that feeds network connections to DLP destination detector."""
                    self._enqueue(kind, data)
                    if kind == "network":
                        for conn in data.get("connections", []):
                            domain = conn.get("domain", "")
                            remote_ip = conn.get("remote_ip", "")
                            if domain or remote_ip:
                                self._push_network_to_dlp(
                                    domain, remote_ip, data.get("bytes_sent", 0)
                                )

                tracker = NetworkTracker(self.machine_id, _network_enqueue, interval=self._network_interval)
                self._network_tracker = tracker
                tracker.run()
            except Exception as e:
                logger.error(f"Network tracker failed: {e}")
            finally:
                if self._network_tracker:
                    try:
                        self._network_tracker.stop()
                    except Exception:
                        pass
                self._network_tracker = None
            if self.running and self._is_subsystem_enabled("network_tracker"):
                time.sleep(5)

    def _baseline_inventory_loop(self):
        while self.running:
            if not self._subsystem_wait_until_enabled("baseline_inventory"):
                break
            if self._baseline_inventory_config is None or not getattr(self._baseline_inventory_config, "enabled", True):
                time.sleep(5)
                continue
            try:
                from baseline_inventory import BaselineInventoryScanner

                scanner = BaselineInventoryScanner(
                    machine_id=self.machine_id,
                    config=self._baseline_inventory_config,
                    post_json_fn=http_post_json,
                )
                self._baseline_inventory = scanner
                scanner.start()
                logger.info("Baseline inventory subsystem started")
                while self.running and self._is_subsystem_enabled("baseline_inventory"):
                    time.sleep(1)
            except Exception as exc:
                logger.error(f"Baseline inventory subsystem failed: {exc}")
                time.sleep(5)
            finally:
                if self._baseline_inventory:
                    try:
                        self._baseline_inventory.stop()
                    except Exception:
                        pass
                self._baseline_inventory = None

    # â”€â”€ DLP v2: cross-tracker correlation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def _push_browser_to_dlp(self, domain: str):
        """Feed browser domain visits to DLP destination detector."""
        try:
            from file_tracker import get_destination_detector
            detector = get_destination_detector()
            if detector:
                detector.push_browser_domain(domain)
        except Exception:
            pass

    def _push_network_to_dlp(self, domain: str, remote_ip: str, bytes_sent: int):
        """Feed network activity to DLP destination detector."""
        try:
            from file_tracker import get_destination_detector
            detector = get_destination_detector()
            if detector:
                detector.push_network_activity(domain, remote_ip, bytes_sent)
        except Exception:
            pass

    def _enqueue(self, kind: str, data: dict):
        """
        Push an event into the offline sync queue.  All agent modules call
        this instead of sending directly â€” the queue handles WS/HTTP delivery,
        retries, persistence, and encryption transparently.
        """
        payload = normalize_activity_payload(kind, data)
        if kind == "print" and getattr(self, "_file_tracker", None) and hasattr(self._file_tracker, "handle_print_event"):
            try:
                self._file_tracker.handle_print_event(payload)
            except Exception as exc:
                logger.debug(f"Print DLP correlation: {exc}")
        priority = resolve_activity_priority(kind, self._PRIORITY_HIGH, self._PRIORITY_NORMAL)
        self._queue.enqueue(kind, payload, priority=priority)


# â”€â”€â”€ STOP PROTECTION â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def _verify_local_stop_hash(password: str, stored: str) -> bool:
    """Verify password against local AGENT_STOP_PASSWORD_HASH.

    Supports two formats:
      - bcrypt hash  (starts with $2b$ or $2a$) â€” current, secure
      - SHA-256 hex  (64 lowercase hex chars)   â€” legacy, accepted but warns

    Prefer bcrypt: generate with `python -c "import bcrypt; print(bcrypt.hashpw(
    b'YourPassword', bcrypt.gensalt()).decode())"` and set as
    AGENT_STOP_PASSWORD_HASH in config.env.
    """
    if not stored:
        return False
    stored = stored.strip()
    if stored.startswith(("$2b$", "$2a$", "$2y$")):
        try:
            import bcrypt as _bcrypt
            return _bcrypt.checkpw(password.encode(), stored.encode())
        except Exception as e:
            logger.error(f"bcrypt local hash check failed: {e}")
            return False
    # Legacy SHA-256 path â€” brute-force risk; warn once per process run.
    if len(stored) == 64 and all(c in "0123456789abcdef" for c in stored.lower()):
        logger.warning(
            "AGENT_STOP_PASSWORD_HASH uses SHA-256 â€” upgrade to bcrypt for security. "
            "Generate with: python -c \"import bcrypt; "
            "print(bcrypt.hashpw(b'<password>', bcrypt.gensalt()).decode())\""
        )
        return hashlib.sha256(password.encode()).hexdigest() == stored.lower()
    logger.error("AGENT_STOP_PASSWORD_HASH format unrecognised â€” local verification skipped")
    return False


def verify_stop_password(password: str) -> bool:
    # Always try the server first â€” it uses bcrypt and honours admin password changes.
    try:
        import urllib.request
        url = f"{SERVER_URL}/api/auth/verify-agent-password"
        payload = json.dumps({"password": password}).encode()
        req = urllib.request.Request(url, data=payload, headers=_agent_http_headers())
        with urllib.request.urlopen(req, timeout=5) as resp:
            result = json.loads(resp.read())
            return result.get("valid", False)
    except Exception:
        pass  # Server unreachable â€” fall through to local offline check.

    # Offline fallback: local hash from config.env / env var.
    if AGENT_STOP_PASSWORD_HASH:
        return _verify_local_stop_hash(password, AGENT_STOP_PASSWORD_HASH)
    logger.warning("Server unreachable and AGENT_STOP_PASSWORD_HASH not set â€” cannot verify stop password")
    return False


def prompt_stop_password() -> bool:
    """Show password dialog to stop the agent"""
    try:
        if OS == "Windows":
            import ctypes
            # Simple input box via PowerShell
            result = subprocess.check_output([
                "powershell", "-Command",
                "$pwd = Read-Host -Prompt 'Enter admin password to stop CropSentinel agent' -AsSecureString; "
                "[Runtime.InteropServices.Marshal]::PtrToStringAuto("
                "[Runtime.InteropServices.Marshal]::SecureStringToBSTR($pwd))"
            ], stderr=subprocess.DEVNULL, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).decode().strip()
            return verify_stop_password(result)

        elif OS == "Darwin":
            script = 'set pwd to text returned of (display dialog "Enter admin password to stop CropSentinel agent:" with title "CropSentinel - Stop Agent" default answer "" with hidden answer buttons {"Cancel", "OK"} default button "OK")\nreturn pwd'
            try:
                result = subprocess.check_output(
                    ["osascript", "-e", script], stderr=subprocess.DEVNULL
                ).decode().strip()
                return verify_stop_password(result)
            except:
                return False

        else:
            try:
                result = subprocess.check_output(
                    ["zenity", "--password", "--title=CropSentinel - Stop Agent"],
                    stderr=subprocess.DEVNULL
                ).decode().strip()
                return verify_stop_password(result)
            except:
                import tkinter as tk
                from tkinter import simpledialog
                root = tk.Tk()
                root.withdraw()
                pwd = simpledialog.askstring(
                    "CropSentinel - Stop Agent",
                    "Enter admin password to stop the agent:",
                    show="*"
                )
                root.destroy()
                return verify_stop_password(pwd or "")

    except Exception as e:
        logger.error(f"Stop password dialog: {e}")
        return False


# â”€â”€â”€ ENTRY POINT â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
def run_agent(interactive: bool = True, stop_event=None):
    if interactive:
        if not check_consent():
            accepted = show_consent_dialog()
            save_consent(accepted)
            if not accepted:
                logger.info("Consent declined. Agent will not start.")
                sys.exit(0)
            logger.info("Consent given. Starting agent.")
        else:
            logger.info("Consent already on record. Starting agent.")
    else:
        logger.info("Starting agent in non-interactive service mode.")

    # Warn early if enrollment token is absent â€” data will land in the wrong
    # tenant on multi-tenant installs.  Single-tenant installs are fine without it.
    if not AGENT_ENROLL_TOKEN:
        logger.warning(
            "CROPSENTINEL_ENROLL_TOKEN is not set. On multi-tenant installs registration "
            "will fail closed (401) and agent telemetry will not start. "
            "Set CROPSENTINEL_ENROLL_TOKEN in config.env to the per-tenant token shown "
            "in the platform portal."
        )

    agent = CropSentinelAgent()
    if stop_event is not None:
        def _service_stop_bridge():
            stop_event.wait()
            agent.running = False

        threading.Thread(target=_service_stop_bridge, daemon=True, name="agent-service-stop").start()
    agent.start()


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--service-worker":
        run_agent(interactive=False)
        return

    # Check for stop command
    if len(sys.argv) > 1 and sys.argv[1] == "--stop":
        if prompt_stop_password():
            print("Agent stopped by authorized admin.")
            # Remove from startup
            try:
                if OS == "Windows":
                    subprocess.run([
                        "reg", "delete",
                        r"HKCU\Software\Microsoft\Windows\CurrentVersion\Run",
                        "/v", "CropSentinelAgent", "/f"
                    ], capture_output=True)
                elif OS == "Darwin":
                    plist = Path.home() / "Library" / "LaunchAgents" / "com.cropsentinel.agent.plist"
                    if plist.exists():
                        plist.unlink()
                else:
                    for service in (
                        Path("/etc/systemd/system/cropsentinel-agent.service"),
                        Path("/etc/systemd/system/cropsentinel-watchdog.service"),
                        Path.home() / ".config" / "systemd" / "user" / "cropsentinel-agent.service",
                    ):
                        if service.exists():
                            service.unlink()
            except Exception as e:
                logger.error(f"Uninstall error: {e}")
        else:
            print("Invalid password.")
        return

    run_agent(interactive=True)


if __name__ == "__main__":
    main()

