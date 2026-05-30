"""
CropSentinel — DLP Destination Detection
=====================================

Determines *where* a file is going or came from:

  - **USB**        — file path is on a removable drive (Windows: E:, F: etc.,
                     Linux/macOS: /media/*, /mnt/*, /Volumes/*)
  - **upload**     — correlated with recent browser activity on known
                     cloud/upload domains, or recent large outbound POST
  - **cloud_sync** — file lives inside a known cloud sync folder
                     (OneDrive, Google Drive, Dropbox, iCloud)
  - **local**      — none of the above

Thread-safe.  The module is stateless except for a shared recent-activity
buffer that other trackers push into.
"""

from __future__ import annotations

import logging
import os
import platform
import re
import string
import threading
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

logger = logging.getLogger("croppro.dlp.destination")

OS = platform.system()


# ═════════════════════════════════════════════════════════════════════════════
#  USB DETECTION
# ═════════════════════════════════════════════════════════════════════════════

def _get_removable_drives_win() -> Set[str]:
    """Windows: return set of single-letter removable drive roots like 'E:\\\\'."""
    drives: Set[str] = set()
    try:
        import ctypes
        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i, letter in enumerate(string.ascii_uppercase):
            if bitmask & (1 << i):
                root = f"{letter}:\\"
                dtype = ctypes.windll.kernel32.GetDriveTypeW(root)
                if dtype == 2:  # DRIVE_REMOVABLE
                    drives.add(root)
    except Exception:
        pass
    return drives


# Linux / macOS external mount points
_EXTERNAL_MOUNT_PREFIXES_LINUX = ("/media/", "/mnt/", "/run/media/")
_EXTERNAL_MOUNT_PREFIXES_MAC   = ("/Volumes/",)


def is_usb_path(file_path: str) -> tuple[bool, str]:
    """
    Check if file_path resides on a USB / removable drive.

    Returns:
        (is_usb, device_label)
        device_label: "E:" on Windows, "/media/usb0" on Linux, etc.
    """
    path = os.path.normpath(file_path)

    if OS == "Windows":
        # Fast check: drive letter in known removable set
        if len(path) >= 2 and path[1] == ":":
            root = path[:3]   # "E:\\"
            for rd in _get_removable_drives_win():
                if root.upper() == rd.upper():
                    return True, path[:2]   # "E:"
        return False, ""

    elif OS == "Linux":
        for prefix in _EXTERNAL_MOUNT_PREFIXES_LINUX:
            if path.startswith(prefix):
                # Device label is the next path component
                parts = path[len(prefix):].split("/", 1)
                label = parts[0] if parts else prefix
                return True, f"{prefix}{label}"
        return False, ""

    elif OS == "Darwin":
        for prefix in _EXTERNAL_MOUNT_PREFIXES_MAC:
            if path.startswith(prefix):
                # Skip "Macintosh HD" — that's the internal disk
                parts = path[len(prefix):].split("/", 1)
                vol_name = parts[0] if parts else ""
                if vol_name.lower() in ("macintosh hd", ""):
                    return False, ""
                return True, f"{prefix}{vol_name}"
        return False, ""

    return False, ""


# ═════════════════════════════════════════════════════════════════════════════
#  CLOUD SYNC DETECTION
# ═════════════════════════════════════════════════════════════════════════════

# Normalised lowercase fragments that indicate a cloud sync folder
_CLOUD_SYNC_MARKERS = (
    "onedrive",
    "google drive",
    "googledrive",
    "dropbox",
    "icloud",
    "iclouddrive",
    "box sync",
    "box drive",
    "mega",
    "syncthing",
    "pcloud",
)


def is_cloud_sync_path(file_path: str) -> bool:
    """Check if file resides inside a known cloud sync directory."""
    low = file_path.lower().replace("\\", "/")
    return any(marker in low for marker in _CLOUD_SYNC_MARKERS)


# ═════════════════════════════════════════════════════════════════════════════
#  UPLOAD DETECTION (Browser + Network correlation)
# ═════════════════════════════════════════════════════════════════════════════

# Domains where a visit + file event strongly suggests an upload
UPLOAD_DOMAINS: Set[str] = {
    # Cloud storage
    "drive.google.com", "docs.google.com",
    "www.dropbox.com", "dropbox.com",
    "onedrive.live.com",
    "box.com", "app.box.com",
    "mega.nz", "mega.io",
    "wetransfer.com",
    # File sharing
    "file.io", "transfer.sh", "send.tresorit.com",
    "gofile.io", "anonfiles.com", "mediafire.com",
    # Messaging / email (attachment upload)
    "mail.google.com", "outlook.live.com", "outlook.office.com",
    "outlook.office365.com", "mail.yahoo.com", "mail.proton.me",
    "mail.protonmail.com", "mail.zoho.com",
    "web.telegram.org", "web.whatsapp.com",
    "discord.com",
    "slack.com", "app.slack.com",
    # Paste / code sharing
    "pastebin.com", "paste.ee", "hastebin.com",
    "gist.github.com", "github.com",
    "gitlab.com", "bitbucket.org",
}

EMAIL_ATTACHMENT_DOMAINS: Set[str] = {
    "mail.google.com",
    "outlook.live.com",
    "outlook.office.com",
    "outlook.office365.com",
    "mail.yahoo.com",
    "mail.proton.me",
    "mail.protonmail.com",
    "mail.zoho.com",
}


@dataclass
class _BrowserActivity:
    """Lightweight record of a recent browser domain visit."""
    domain: str
    timestamp: float     # monotonic


@dataclass
class _NetworkActivity:
    """Lightweight record of a recent large outbound POST."""
    domain: str
    remote_ip: str
    bytes_sent: int
    timestamp: float


# File extensions strongly associated with data exfiltration
_EXFIL_EXTENSIONS = frozenset({
    ".csv", ".xlsx", ".xls", ".sql", ".db", ".bak", ".zip", ".rar",
    ".7z", ".tar", ".gz", ".json", ".xml", ".pem", ".key", ".env",
    ".docx", ".pdf", ".pptx",
})


class DestinationDetector:
    """
    Correlates file events with browser/network activity to detect uploads.

    Other trackers push activity into this detector via push_browser_domain()
    and push_network_activity().  When the file_tracker asks classify(), the
    detector checks if any recent browser/network activity matches an upload
    pattern.
    """

    # How far back (seconds) to look for correlated activity
    # Fix 2: tightened from 60s to 10s to reduce false positives
    CORRELATION_WINDOW = 10
    # Looser window used when file extension is a known exfil type
    CORRELATION_WINDOW_EXFIL = 30

    def __init__(self):
        self._lock = threading.Lock()
        self._browser_recent: List[_BrowserActivity] = []
        self._network_recent: List[_NetworkActivity] = []

    # ── Push events from other trackers ───────────────────────────────────

    def push_browser_domain(self, domain: str):
        """Called by browser_tracker when a domain is visited."""
        now = time.monotonic()
        with self._lock:
            self._browser_recent.append(_BrowserActivity(domain=domain.lower(), timestamp=now))
            self._prune_browser()

    def push_network_activity(self, domain: str, remote_ip: str, bytes_sent: int):
        """Called by network_tracker on large outbound connections."""
        now = time.monotonic()
        with self._lock:
            self._network_recent.append(
                _NetworkActivity(domain=domain.lower(), remote_ip=remote_ip,
                                 bytes_sent=bytes_sent, timestamp=now)
            )
            self._prune_network()

    # ── Classification ────────────────────────────────────────────────────

    def classify(self, file_path: str, file_size: int = 0) -> tuple[str, str]:
        """
        Determine the destination category for a file event.

        Priority: usb > cloud_sync > upload > local
        (Fix 5: cloud_sync takes precedence over upload — a file written to a
        sync folder is unambiguously cloud_sync, even if a browser tab to a
        cloud domain is also open.)

        Returns:
            (destination, device)
            destination: "usb" | "upload" | "cloud_sync" | "local"
            device: drive letter / mount point / domain / ""
        """
        # 1. USB check (cheapest — pure path analysis)
        usb, device = is_usb_path(file_path)
        if usb:
            return "usb", device

        # 2. Cloud sync check (path analysis — deterministic, no correlation)
        if is_cloud_sync_path(file_path):
            return "cloud_sync", ""

        # 3. Upload check (correlation with recent browser/network activity)
        ext = ""
        try:
            import os as _os
            ext = _os.path.splitext(file_path)[1].lower()
        except Exception:
            pass
        upload_domain = self._check_upload_correlation(
            file_ext=ext, file_size=file_size,
        )
        if upload_domain:
            return "upload", upload_domain

        return "local", ""

    def _check_upload_correlation(
        self, file_ext: str = "", file_size: int = 0,
    ) -> Optional[str]:
        """
        Check if any recent browser or network activity matches an upload
        domain within the correlation window.

        Fix 2: Stricter correlation:
          - Default 10s window (down from 60s)
          - 30s window only when file extension is a known exfil type
          - Network match additionally requires bytes_sent within 50%-200%
            of file_size when file_size is known
        """
        now = time.monotonic()
        is_exfil = file_ext in _EXFIL_EXTENSIONS
        window = self.CORRELATION_WINDOW_EXFIL if is_exfil else self.CORRELATION_WINDOW
        cutoff = now - window

        with self._lock:
            # Browser domain match
            for ba in reversed(self._browser_recent):
                if ba.timestamp < cutoff:
                    break
                if ba.domain in UPLOAD_DOMAINS:
                    return ba.domain

            # Network domain match (large outbound) — size-aware
            for na in reversed(self._network_recent):
                if na.timestamp < cutoff:
                    break
                if na.domain not in UPLOAD_DOMAINS:
                    continue
                # If we know the file size, require bytes_sent in plausible range
                if file_size > 0 and na.bytes_sent > 0:
                    lo = file_size * 0.5
                    hi = file_size * 5.0  # multipart/encoding overhead
                    if not (lo <= na.bytes_sent <= hi):
                        continue
                return na.domain

        return None

    # ── Housekeeping ──────────────────────────────────────────────────────

    def _prune_browser(self):
        """Remove browser entries older than 2x correlation window."""
        cutoff = time.monotonic() - (self.CORRELATION_WINDOW_EXFIL * 2)
        self._browser_recent = [
            b for b in self._browser_recent if b.timestamp > cutoff
        ]
        # Hard cap
        if len(self._browser_recent) > 500:
            self._browser_recent = self._browser_recent[-250:]

    def _prune_network(self):
        """Remove network entries older than 2x correlation window."""
        cutoff = time.monotonic() - (self.CORRELATION_WINDOW_EXFIL * 2)
        self._network_recent = [
            n for n in self._network_recent if n.timestamp > cutoff
        ]
        if len(self._network_recent) > 500:
            self._network_recent = self._network_recent[-250:]
