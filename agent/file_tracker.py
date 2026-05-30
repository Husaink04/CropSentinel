"""
CropSentinel — File Activity Tracker (v2)
======================================
Monitors file system events in key directories using the watchdog library.
Tracks create, delete, rename, move operations on user-accessible folders.
On delete: reads file content and sends base64 backup to server (secret vault).

v2 additions:
  - DLP file fingerprinting (SHA-256 tracking across copies/renames)
  - Weighted risk scoring with context modifiers
  - Destination-aware scanning (USB, upload, cloud sync detection)
  - Enriched DLP events with file_hash, risk_score, destination, is_known_sensitive
"""
import os
import subprocess
import sys
import time
import base64
import hashlib
import json
import logging
import platform
import sqlite3
import threading
from pathlib import Path
from datetime import datetime, timezone

try:
    from watchdog.events import FileSystemEventHandler
except ImportError:
    FileSystemEventHandler = object

logger = logging.getLogger("croppro.file")

FILE_TRACKER_BUILD = "vault-cache-v3"
MAX_BACKUP_SIZE = 50 * 1024 * 1024  # 50 MB max for backup
DELETE_CACHE_MAX_ITEMS = 250
DELETE_CACHE_MAX_BYTES = 200 * 1024 * 1024
DELETE_CACHE_RETRY_DELAYS = (0.5, 1.5, 3.0)
DELETE_CACHE_FAST_SWEEP_SECONDS = 10.0
DELETE_CACHE_SWEEP_SECONDS = 120.0
LOCAL_VAULT_CACHE_MAX_ITEMS = 500
LOCAL_VAULT_CACHE_DIR = Path.home() / ".croppro_agent" / "vault_cache"

# ── DLP integration (lazy-loaded) ────────────────────────────────────────────
_dlp_engine = None
_live_document_parser = None


def _get_dlp_engine():
    """Lazy-load the DLP engine so file_tracker works even without dlp_engine.py."""
    global _dlp_engine
    if _dlp_engine is None:
        try:
            from dlp_engine import DLPEngine
            _dlp_engine = DLPEngine(enabled=True)
            logger.info("DLP engine v2 loaded for file content scanning")
        except ImportError:
            logger.debug("DLP engine not available — DLP scanning disabled")
            _dlp_engine = False  # sentinel: tried and failed
    return _dlp_engine if _dlp_engine is not False else None


def _get_live_document_parser():
    global _live_document_parser
    if _live_document_parser is None:
        try:
            from baseline_inventory import BaselineInventoryConfig, BaselineParser

            cfg = BaselineInventoryConfig(
                enabled=True,
                max_parser_file_size=25 * 1024 * 1024,
                max_ocr_file_size=10 * 1024 * 1024,
            )
            _live_document_parser = BaselineParser(cfg)
            logger.info("Live DLP document parser loaded")
        except Exception as exc:
            logger.debug("Live document parser unavailable: %s", exc)
            _live_document_parser = False
    return _live_document_parser if _live_document_parser is not False else None


# ── Destination detector (shared instance, fed by agent.py) ──────────────────
_destination_detector = None


def get_destination_detector():
    """Get or create the singleton DestinationDetector."""
    global _destination_detector
    if _destination_detector is None:
        try:
            from dlp_destination import DestinationDetector
            _destination_detector = DestinationDetector()
            logger.info("DLP destination detector loaded")
        except ImportError:
            logger.debug("Destination detector not available")
            _destination_detector = False
    return _destination_detector if _destination_detector is not False else None


def _utcnow_iso():
    return datetime.now(timezone.utc).isoformat()


def _normalize_path(path: str) -> str:
    try:
        normalized = os.path.normpath(os.path.abspath(path))
    except Exception:
        normalized = os.path.normpath(path or "")
    if platform.system() == "Windows":
        return normalized.lower()
    return normalized


def _get_removable_watch_roots():
    roots = []
    if platform.system() != "Windows":
        return roots
    try:
        import ctypes
        import string as _string

        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for i, letter in enumerate(_string.ascii_uppercase):
            if bitmask & (1 << i):
                root = f"{letter}:\\"
                dtype = ctypes.windll.kernel32.GetDriveTypeW(root)
                if dtype == 2:
                    roots.append(root)
    except Exception:
        return roots
    return roots


def _get_windows_profile_homes():
    profiles = []
    if platform.system() != "Windows":
        return profiles
    users_root = Path(os.environ.get("SystemDrive", "C:")) / "Users"
    excluded = {
        "all users",
        "default",
        "default user",
        "defaultapppool",
        "public",
        "wdagutilityaccount",
        "defaultuser0",
    }
    try:
        for child in users_root.iterdir():
            if not child.is_dir():
                continue
            if child.name.lower() in excluded:
                continue
            profiles.append(child)
    except Exception as exc:
        logger.debug("Windows profile enumeration failed: %s", exc)
    return profiles


# Directories to monitor
def _get_watched_dirs():
    homes = [Path.home()]
    if platform.system() == "Windows":
        windows_homes = _get_windows_profile_homes()
        if windows_homes:
            homes = windows_homes
    candidates = []
    for home in homes:
        candidates.extend(
            [
                home / "Desktop",
                home / "Documents",
                home / "Downloads",
            ]
        )
    if platform.system() == "Windows":
        for home in homes:
            onedrive = home / "OneDrive"
            if onedrive.exists():
                for sub in ("Desktop", "Documents", "Downloads"):
                    od_sub = onedrive / sub
                    if od_sub.exists():
                        candidates.append(od_sub)
        candidates.extend(Path(root) for root in _get_removable_watch_roots())
    elif platform.system() == "Linux":
        home = Path.home()
        for extra in ["Projects", "workspace", "Work"]:
            p = home / extra
            if p.exists():
                candidates.append(p)
    # Deduplicate (resolve symlinks / junctions) and filter to existing
    seen = set()
    result = []
    for d in candidates:
        if not d.exists():
            continue
        try:
            resolved = str(d.resolve())
        except OSError:
            resolved = str(d)
        if resolved not in seen:
            seen.add(resolved)
            result.append(resolved)
    return result


# Extensions worth DLP-scanning (text-based files that could contain sensitive data)
DLP_SCAN_EXTENSIONS = {
    ".txt", ".csv", ".json", ".xml", ".yml", ".yaml", ".log",
    ".env", ".cfg", ".conf", ".ini", ".properties",
    ".sql", ".md", ".rst", ".html", ".htm",
    ".py", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".cs", ".go", ".rb", ".php",
    ".sh", ".bash", ".bat", ".ps1", ".cmd",
}

LIVE_PARSER_EXTENSIONS = {
    ".pdf", ".docx", ".xlsx", ".pptx", ".zip", ".jar", ".war",
    ".eml",
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp",
}


# File extensions considered sensitive
SENSITIVE_EXTENSIONS = {
    ".pdf", ".docx", ".xlsx", ".pptx", ".csv", ".txt", ".zip", ".rar",
    ".7z", ".tar", ".gz", ".sql", ".db", ".bak", ".key", ".pem", ".pfx",
    ".conf", ".cfg", ".json", ".xml", ".env",
}

# Extensions to skip backup (binaries, caches, etc.)
SKIP_BACKUP_EXTENSIONS = {
    ".exe", ".dll", ".so", ".dylib", ".o", ".obj", ".pyc", ".pyo",
    ".class", ".jar", ".war", ".pyd", ".bin", ".msi", ".msix",
    ".iso", ".img", ".vmdk", ".vdi",
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico",
    ".mp4", ".mkv", ".avi", ".mov", ".mp3", ".wav", ".flac",
}

SKIP_WALK_DIR_NAMES = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules",
    ".venv", "venv", ".tox", ".pytest_cache", ".mypy_cache",
    "dist", "build", ".next", ".vite",
}


class FileTracker:
    """Uses watchdog to monitor file system events in key directories."""

    def __init__(
        self,
        machine_id: str,
        enqueue_fn,
        fast_sweep_seconds: float = DELETE_CACHE_FAST_SWEEP_SECONDS,
        recursive_sweep_seconds: float = DELETE_CACHE_SWEEP_SECONDS,
        cache_sweeper_enabled: bool = True,
    ):
        self.machine_id = machine_id
        self.enqueue = enqueue_fn
        self.running = True
        self._observer = None
        self._cache_sweeper_enabled = bool(cache_sweeper_enabled)
        self._fast_sweep_seconds = max(2.0, float(fast_sweep_seconds))
        self._recursive_sweep_seconds = max(self._fast_sweep_seconds, float(recursive_sweep_seconds))
        self._dlp_policy = {}
        self._actor_username = ""
        self._watched_dirs = set()

    def update_runtime_config(self, fast_sweep_seconds: float, recursive_sweep_seconds: float, sweeper_enabled: bool):
        self._fast_sweep_seconds = max(2.0, float(fast_sweep_seconds))
        self._recursive_sweep_seconds = max(self._fast_sweep_seconds, float(recursive_sweep_seconds))
        self._cache_sweeper_enabled = bool(sweeper_enabled)

    def set_dlp_context(self, policy: dict | None, actor_username: str = ""):
        self._dlp_policy = dict(policy or {})
        self._actor_username = str(actor_username or "")

    def _runtime_context(self):
        return {
            "policy": dict(self._dlp_policy or {}),
            "actor_username": self._actor_username,
        }

    def run(self):
        try:
            from watchdog.observers import Observer
            _ = Observer  # keep local import lint-clean
        except ImportError:
            logger.warning("watchdog not installed - switching file tracker to polling fallback mode")
            self._run_polling_fallback()
            return

        dirs = _get_watched_dirs()
        if not dirs:
            logger.warning("No directories to watch for file activity")
            return

        logger.info(
            "File tracker build=%s vault_cache=%s watched_dirs=%s",
            FILE_TRACKER_BUILD,
            str(LOCAL_VAULT_CACHE_DIR),
            dirs,
        )
        handler = _Handler(self.machine_id, self.enqueue, runtime_context_getter=self._runtime_context)
        self._start_cache_sweeper(dirs, handler)
        self._observer = Observer()
        for d in dirs:
            try:
                self._observer.schedule(handler, d, recursive=True)
                self._watched_dirs.add(_normalize_path(str(d)))
                logger.info(f"File tracker watching: {d}")
            except Exception as e:
                logger.warning(f"Cannot watch {d}: {e}")

        self._observer.start()
        self._start_dynamic_watch_refresh(handler)
        logger.info("File tracker started (DLP v2 pipeline active)")

        try:
            while self.running:
                time.sleep(2)
        finally:
            self._observer.stop()
            self._observer.join()

    def _collect_snapshot(self, dirs):
        """
        Build a lightweight filesystem snapshot:
        path -> (mtime_ns, size, is_directory)
        """
        snap = {}
        for root_dir in dirs:
            for root, dirnames, filenames in os.walk(root_dir):
                dirnames[:] = [d for d in dirnames if d.lower() not in SKIP_WALK_DIR_NAMES]
                # Capture directories so folder create/delete is also visible.
                for name in dirnames:
                    path = os.path.join(root, name)
                    try:
                        st = os.stat(path)
                    except OSError:
                        continue
                    snap[path] = (int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))), 0, True)
                for name in filenames:
                    path = os.path.join(root, name)
                    try:
                        st = os.stat(path)
                    except OSError:
                        continue
                    snap[path] = (
                        int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
                        int(st.st_size),
                        False,
                    )
        return snap

    def _collect_top_level_snapshot(self, root_dir):
        """
        Capture direct children first. This prevents short-lived Desktop files
        from being missed while a recursive scan is busy inside large folders.
        """
        snap = {}
        try:
            with os.scandir(root_dir) as entries:
                for entry in entries:
                    try:
                        is_dir = entry.is_dir(follow_symlinks=False)
                    except OSError:
                        continue
                    if is_dir and entry.name.lower() in SKIP_WALK_DIR_NAMES:
                        continue
                    try:
                        st = entry.stat(follow_symlinks=False)
                    except OSError:
                        continue
                    snap[entry.path] = (
                        int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9))),
                        0 if is_dir else int(st.st_size),
                        is_dir,
                    )
        except OSError:
            pass
        return snap

    def _start_cache_sweeper(self, dirs, handler):
        """
        Periodically primes backup cache for existing files. This covers Windows
        and sync-folder cases where create/modify events are missed or arrive
        before file content is readable.
        """
        if not self._cache_sweeper_enabled:
            logger.info("File backup cache sweeper disabled")
            return

        def _prime_snapshot(root_dir, snap):
            newest_first = sorted(
                snap.items(),
                key=lambda item: int(item[1][0] or 0),
                reverse=True,
            )
            for path, (mtime_ns, size, is_dir) in newest_first:
                handler._prime_from_snapshot(path, mtime_ns, size, is_dir)

        def _fast_loop(root_dir):
            logger.info(f"File backup fast cache sweeper started: {root_dir}")
            while self.running:
                try:
                    _prime_snapshot(root_dir, self._collect_top_level_snapshot(root_dir))
                except Exception as exc:
                    logger.debug(f"File backup fast sweeper error for {root_dir}: {exc}")
                time.sleep(self._fast_sweep_seconds)

        def _recursive_loop(root_dir):
            logger.info(f"File backup recursive cache sweeper started: {root_dir}")
            while self.running:
                try:
                    _prime_snapshot(root_dir, self._collect_snapshot([root_dir]))
                except Exception as exc:
                    logger.debug(f"File backup cache sweeper error for {root_dir}: {exc}")
                time.sleep(self._recursive_sweep_seconds)

        for root_dir in dirs:
            threading.Thread(target=_fast_loop, args=(root_dir,), daemon=True).start()
            threading.Thread(target=_recursive_loop, args=(root_dir,), daemon=True).start()

    def _start_dynamic_watch_refresh(self, handler):
        def _refresh_loop():
            while self.running and self._observer:
                try:
                    for watch_dir in _get_watched_dirs():
                        normalized = _normalize_path(str(watch_dir))
                        if normalized in self._watched_dirs:
                            continue
                        try:
                            self._observer.schedule(handler, str(watch_dir), recursive=True)
                            self._watched_dirs.add(normalized)
                            logger.info("File tracker dynamically watching: %s", watch_dir)
                        except Exception as exc:
                            logger.debug("Dynamic watch skip for %s: %s", watch_dir, exc)
                except Exception as exc:
                    logger.debug("Dynamic watch refresh failed: %s", exc)
                time.sleep(10)

        threading.Thread(target=_refresh_loop, daemon=True).start()

    def _run_polling_fallback(self):
        """
        Fallback when watchdog isn't available. Uses periodic snapshots and emits:
          - create (new path)
          - delete (missing path)
          - modify (mtime/size changed for files)
        """
        dirs = _get_watched_dirs()
        if not dirs:
            logger.warning("No directories to watch for file activity")
            return

        logger.info(
            "File tracker build=%s vault_cache=%s watched_dirs=%s",
            FILE_TRACKER_BUILD,
            str(LOCAL_VAULT_CACHE_DIR),
            dirs,
        )
        handler = _Handler(self.machine_id, self.enqueue, runtime_context_getter=self._runtime_context)
        self._start_cache_sweeper(dirs, handler)
        logger.info("File tracker started in polling fallback mode")
        prev = self._collect_snapshot(dirs)

        try:
            while self.running:
                time.sleep(5)
                current_dirs = _get_watched_dirs()
                curr = self._collect_snapshot(current_dirs)

                prev_keys = set(prev.keys())
                curr_keys = set(curr.keys())

                created = curr_keys - prev_keys
                deleted = prev_keys - curr_keys
                common = prev_keys & curr_keys

                for path in sorted(created):
                    _mtime, _size, is_dir = curr[path]
                    if not is_dir:
                        handler._schedule_backup_prime(path)
                    handler._send("create", path, is_directory=is_dir)

                for path in sorted(deleted):
                    _mtime, _size, is_dir = prev[path]
                    cached = handler._drop_cached_backup(path)
                    if cached is None:
                        cached = handler._read_local_vault_cache(path)
                    backup = cached.get("data", "") if cached is not None else None
                    skip_reason = ""
                    if backup is None and not is_dir:
                        backup = _read_file_base64(path)
                        if backup == "":
                            backup = None
                    if backup is not None:
                        logger.info(f"Delete captured with backup: {path}")
                        handler._drop_local_vault_cache(path)
                    else:
                        skip_reason = handler._fallback_backup_reason(path, is_dir)
                        logger.info(f"Delete not recoverable: {path} ({skip_reason})")
                    handler._send("delete", path, is_directory=is_dir, file_data=backup, backup_skip_reason=skip_reason)

                for path in sorted(common):
                    prev_mtime, prev_size, prev_is_dir = prev[path]
                    cur_mtime, cur_size, cur_is_dir = curr[path]
                    if prev_is_dir or cur_is_dir:
                        continue
                    if prev_mtime != cur_mtime or prev_size != cur_size:
                        handler._schedule_backup_prime(path)
                        handler._send("modify", path, is_directory=False)

                prev = curr
        except Exception as e:
            logger.error(f"File tracker polling fallback failed: {e}")

    def stop(self):
        self.running = False
        if self._observer:
            self._observer.stop()


def _read_file_base64(path: str, retries: int = 0, delay: float = 0.15) -> str:
    """Read a file and return base64-encoded content. Returns '' on failure."""
    attempts = max(1, int(retries) + 1)
    for idx in range(attempts):
        try:
            size = os.path.getsize(path)
            if size > MAX_BACKUP_SIZE or size == 0:
                if idx < attempts - 1:
                    time.sleep(delay)
                    continue
                return ""
            ext = os.path.splitext(path)[1].lower()
            if ext in SKIP_BACKUP_EXTENSIONS:
                return ""
            with open(path, "rb") as f:
                raw = f.read()
            if not raw:
                if idx < attempts - 1:
                    time.sleep(delay)
                    continue
                return ""
            return base64.b64encode(raw).decode("ascii")
        except (OSError, PermissionError, FileNotFoundError):
            if idx < attempts - 1:
                time.sleep(delay)
                continue
            return ""
    return ""


class _Handler(FileSystemEventHandler):
    """Watchdog event handler that enqueues file events with DLP v2 enrichment."""

    # Paths/fragments that indicate temp or sync files — skip entirely
    _SKIP_FRAGMENTS = {
        ".tmp", "~$", ".crdownload", ".partial", ".download",
        ".swp", ".swo", "__pycache__", "node_modules", ".git",
        "\\.venv\\", "/.venv/", "\\venv\\", "/venv/",
    }

    def __init__(self, machine_id, enqueue_fn, runtime_context_getter=None):
        self.machine_id = machine_id
        self.enqueue = enqueue_fn
        self._runtime_context_getter = runtime_context_getter or (lambda: {})
        self._recent = {}
        self._dlp_scan_recent = {}    # Fix 6: 30s debounce for content scans
        self._dlp_move_recent = {}    # Fix 6: 5s debounce for move/destination checks
        # Pre-read cache: when a file is about to be deleted, we may
        # have already cached its content from a prior modify event
        self._delete_cache = {}
        self._delete_cache_bytes = 0
        self._snapshot_cache_state = {}
        LOCAL_VAULT_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        # v2: track recent DLP alert count for "repeated" scoring
        self._dlp_alert_count = 0
        self._dlp_alert_window_start = time.time()
        self._recent_sensitive_records = []

    def _cache_key(self, path):
        if not path:
            return ""
        try:
            normalized = os.path.abspath(path)
        except Exception:
            normalized = path
        return os.path.normcase(normalized)

    def _cache_digest(self, path):
        return hashlib.sha256(self._cache_key(path).encode("utf-8", errors="ignore")).hexdigest()

    def _local_vault_paths(self, path):
        digest = self._cache_digest(path)
        return LOCAL_VAULT_CACHE_DIR / f"{digest}.b64", LOCAL_VAULT_CACHE_DIR / f"{digest}.json"

    def _write_local_vault_cache(self, path, file_data, size):
        data_path, meta_path = self._local_vault_paths(path)
        meta = {
            "path": path,
            "size": int(size or 0),
            "cached_at": time.time(),
        }
        data_path.write_text(file_data, encoding="ascii")
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        self._trim_local_vault_cache()

    def _read_local_vault_cache(self, path):
        data_path, meta_path = self._local_vault_paths(path)
        if not data_path.exists():
            return None
        try:
            file_data = data_path.read_text(encoding="ascii")
            meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else {}
            return {"data": file_data, "size": int(meta.get("size", 0) or 0)}
        except Exception:
            return None

    def _drop_local_vault_cache(self, path):
        data_path, meta_path = self._local_vault_paths(path)
        for item in (data_path, meta_path):
            try:
                item.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

    def _trim_local_vault_cache(self):
        try:
            metas = sorted(
                LOCAL_VAULT_CACHE_DIR.glob("*.json"),
                key=lambda p: p.stat().st_mtime,
            )
            while len(metas) > LOCAL_VAULT_CACHE_MAX_ITEMS:
                meta_path = metas.pop(0)
                data_path = meta_path.with_suffix(".b64")
                try:
                    meta_path.unlink()
                except OSError:
                    pass
                try:
                    data_path.unlink()
                except OSError:
                    pass
        except Exception:
            pass

    def _drop_cached_backup(self, path):
        cached = self._delete_cache.pop(self._cache_key(path), None)
        if cached:
            self._delete_cache_bytes = max(0, self._delete_cache_bytes - int(cached.get("size", 0) or 0))
        return cached

    def _evict_delete_cache(self):
        while self._delete_cache and (
            len(self._delete_cache) > DELETE_CACHE_MAX_ITEMS
            or self._delete_cache_bytes > DELETE_CACHE_MAX_BYTES
        ):
            oldest_path = next(iter(self._delete_cache))
            self._drop_cached_backup(oldest_path)

    def _cache_backup_candidate(self, path):
        if self._should_skip(path):
            return False, "skip_fragment"
        if not path or os.path.isdir(path):
            return False, "directory_not_backed_up"
        ext = os.path.splitext(path)[1].lower()
        if ext in SKIP_BACKUP_EXTENSIONS:
            return False, "excluded_extension"
        try:
            size = os.path.getsize(path)
        except OSError:
            return False, "missing_or_unreadable"
        if size < 0:
            return False, "invalid_size"
        if size > MAX_BACKUP_SIZE:
            return False, "file_too_large"
        file_data = "" if size == 0 else _read_file_base64(path, retries=3, delay=0.2)
        if size > 0 and file_data == "":
            return False, "read_failed"
        cache_key = self._cache_key(path)
        self._drop_cached_backup(path)
        self._delete_cache[cache_key] = {"data": file_data, "size": size, "cached_at": time.time()}
        self._delete_cache_bytes += size
        try:
            self._write_local_vault_cache(path, file_data, size)
        except Exception as exc:
            logger.debug(f"Local vault cache write failed for {path}: {exc}")
        self._evict_delete_cache()
        logger.info(f"Delete backup primed: {path} ({size} bytes)")
        return True, ""

    def _schedule_backup_prime(self, path):
        if not path or os.path.isdir(path) or self._should_skip(path):
            return
        self._cache_backup_candidate(path)
        for delay in DELETE_CACHE_RETRY_DELAYS:
            timer = threading.Timer(delay, self._cache_backup_candidate, args=(path,))
            timer.daemon = True
            timer.start()

    def _prime_from_snapshot(self, path, mtime_ns, size, is_directory):
        if is_directory or not path or size < 0 or size > MAX_BACKUP_SIZE:
            return
        if self._should_skip(path):
            return
        ext = os.path.splitext(path)[1].lower()
        if ext in SKIP_BACKUP_EXTENSIONS:
            return
        key = self._cache_key(path)
        state = (int(mtime_ns or 0), int(size or 0))
        if self._snapshot_cache_state.get(key) == state and key in self._delete_cache:
            return
        ok, reason = self._cache_backup_candidate(path)
        if ok:
            self._snapshot_cache_state[key] = state
        else:
            logger.debug(f"Snapshot backup prime skipped: {path} ({reason})")

    def _move_cached_backup(self, src_path, dest_path):
        if not src_path or not dest_path:
            return False
        src_key = self._cache_key(src_path)
        dest_key = self._cache_key(dest_path)
        if not src_key or not dest_key or src_key == dest_key:
            return False
        cached = self._delete_cache.pop(src_key, None)
        if not cached:
            return False
        old = self._delete_cache.pop(dest_key, None)
        if old:
            self._delete_cache_bytes = max(0, self._delete_cache_bytes - int(old.get("size", 0) or 0))
        self._delete_cache[dest_key] = cached
        local_cached = self._read_local_vault_cache(src_path)
        if local_cached is not None:
            try:
                self._write_local_vault_cache(dest_path, local_cached.get("data", ""), local_cached.get("size", 0))
                self._drop_local_vault_cache(src_path)
            except Exception:
                pass
        logger.info(f"Delete backup cache moved: {src_path} -> {dest_path}")
        return True

    def _fallback_backup_reason(self, path, is_directory):
        if is_directory:
            return "directory_not_backed_up"
        ext = os.path.splitext(path)[1].lower()
        if ext in SKIP_BACKUP_EXTENSIONS:
            return "excluded_extension"
        return "unavailable_at_delete"

    def _should_skip(self, path):
        """Skip temp files, sync artifacts, and noisy paths."""
        basename = os.path.basename(path)
        for frag in self._SKIP_FRAGMENTS:
            if frag in basename or frag in path:
                return True
        return False

    def _debounce(self, key, window=1.0):
        now = time.time()
        if key in self._recent and (now - self._recent[key]) < window:
            return True
        self._recent[key] = now
        if len(self._recent) > 500:
            cutoff = now - 5.0
            self._recent = {k: v for k, v in self._recent.items() if v > cutoff}
        return False

    def _dlp_scan_debounce(self, file_path):
        """
        Fix 6: 30-second window for content scans (avoids re-reading the same
        file repeatedly when it's being saved by an editor).
        """
        now = time.time()
        if file_path in self._dlp_scan_recent and (now - self._dlp_scan_recent[file_path]) < 30.0:
            return True
        self._dlp_scan_recent[file_path] = now
        if len(self._dlp_scan_recent) > 200:
            cutoff = now - 60.0
            self._dlp_scan_recent = {
                k: v for k, v in self._dlp_scan_recent.items() if v > cutoff
            }
        return False

    def _dlp_move_debounce(self, key):
        """
        Fix 6: 5-second window for move/destination checks. Movement events
        are rare and we want to react quickly to USB/cloud transfers, so the
        window is much shorter than the content-scan one.
        """
        now = time.time()
        if key in self._dlp_move_recent and (now - self._dlp_move_recent[key]) < 5.0:
            return True
        self._dlp_move_recent[key] = now
        if len(self._dlp_move_recent) > 200:
            cutoff = now - 30.0
            self._dlp_move_recent = {
                k: v for k, v in self._dlp_move_recent.items() if v > cutoff
            }
        return False

    def _is_repeated_behaviour(self) -> bool:
        """Check if this machine has triggered multiple DLP alerts recently."""
        now = time.time()
        # Reset window every 10 minutes
        if now - self._dlp_alert_window_start > 600:
            self._dlp_alert_count = 0
            self._dlp_alert_window_start = now
        return self._dlp_alert_count >= 3

    def _bump_dlp_alert(self):
        """Record a DLP alert for repeated-behaviour tracking."""
        now = time.time()
        if now - self._dlp_alert_window_start > 600:
            self._dlp_alert_count = 0
            self._dlp_alert_window_start = now
        self._dlp_alert_count += 1

    def _runtime_context(self):
        try:
            return dict(self._runtime_context_getter() or {})
        except Exception:
            return {}

    def _current_actor_username(self):
        return str(self._runtime_context().get("actor_username") or "")

    def _current_dlp_policy(self):
        return dict(self._runtime_context().get("policy") or {})

    def _remember_sensitive_file(self, alert_data, extracted_text=""):
        if not alert_data.get("findings"):
            return
        self._recent_sensitive_records.append(
            {
                "captured_at": time.time(),
                "file_path": str(alert_data.get("file_path", "") or ""),
                "file_name": str(alert_data.get("file_name", "") or ""),
                "file_hash": str(alert_data.get("file_hash", "") or ""),
                "content_fingerprint": str(alert_data.get("content_fingerprint", "") or ""),
                "enterprise_label": str(alert_data.get("enterprise_label", "") or ""),
                "findings": list(alert_data.get("findings", []) or []),
                "risk_level": str(alert_data.get("risk_level", "") or "medium"),
                "risk_score": int(alert_data.get("risk_score", 0) or 0),
                "source_text_excerpt": extracted_text[:4096] if extracted_text else "",
            }
        )
        cutoff = time.time() - 900
        self._recent_sensitive_records = [item for item in self._recent_sensitive_records[-50:] if item.get("captured_at", 0) >= cutoff]

    def _recent_sensitive_candidates(self, *, file_name="", content_fingerprint="", within_seconds=180):
        cutoff = time.time() - max(30, int(within_seconds or 180))
        matches = []
        target_name = str(file_name or "").lower()
        target_fp = str(content_fingerprint or "")
        for item in reversed(self._recent_sensitive_records):
            if item.get("captured_at", 0) < cutoff:
                break
            if not target_fp and not target_name:
                matches.append(item)
                continue
            if target_fp and item.get("content_fingerprint") == target_fp:
                matches.append(item)
                continue
            if target_name and item.get("file_name", "").lower() == target_name:
                matches.append(item)
        return matches

    def _match_policy_exception(self, event, classifier_hits):
        policy = self._current_dlp_policy()
        path = str(event.get("file_path", "") or "")
        actor = str(event.get("actor_username", "") or "")
        destination = str(event.get("destination_type", "") or "")
        app_name = str(event.get("app_name", "") or "")
        hit_names = {str(hit.get("name", "") or "") for hit in classifier_hits}
        now = datetime.now(timezone.utc)
        for exc in list(policy.get("exceptions", []) or []):
            try:
                expires_at = exc.get("expires_at")
                if expires_at:
                    expiry = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
                    if expiry.tzinfo is None:
                        expiry = expiry.replace(tzinfo=timezone.utc)
                    if expiry < now:
                        continue
                scope_type = str(exc.get("scope_type", "") or "")
                scope_value = str(exc.get("scope_value", "") or "")
                if scope_type == "machine" and scope_value and scope_value != self.machine_id:
                    continue
                if scope_type == "user" and scope_value and scope_value != actor:
                    continue
                path_pattern = str(exc.get("path_pattern", "") or "")
                if scope_type == "path" and path_pattern and path_pattern not in path:
                    continue
                classifier_name = str(exc.get("classifier_name", "") or "")
                if classifier_name and classifier_name not in hit_names:
                    continue
                exc_destination = str(exc.get("destination_type", "") or "")
                if exc_destination and exc_destination != destination:
                    continue
                exc_app_name = str(exc.get("app_name", "") or "")
                if exc_app_name and exc_app_name != app_name:
                    continue
                return {
                    "id": exc.get("id"),
                    "reason": str(exc.get("reason", "") or ""),
                    "scope_type": scope_type,
                }
            except Exception:
                continue
        return None

    def _evaluate_dlp_policy(self, *, findings, destination_type, risk_level, block_candidate, file_path="", app_name=""):
        policy = self._current_dlp_policy()
        hit_names = {str(item.get("type", "") or "") for item in list(findings or [])}
        classifier_map = {item.get("id"): item for item in list(policy.get("classifiers", []) or []) if item.get("id") is not None}
        matched_rule = None
        classifier_hits = []
        sorted_rules = sorted(
            list(policy.get("rules", []) or []),
            key=lambda rule: (
                {"low": 1, "medium": 2, "warning": 2, "high": 3, "critical": 4}.get(str(rule.get("severity", "low")), 0),
                float(rule.get("confidence", 0) or 0),
            ),
            reverse=True,
        )
        event = {
            "channel": "file",
            "destination_type": destination_type,
            "file_path": file_path,
            "actor_username": self._current_actor_username(),
            "app_name": app_name,
        }
        for rule in sorted_rules:
            channels = set(rule.get("channels", ["file"]) or ["file"])
            if "any" not in channels and "file" not in channels:
                continue
            destinations = set(rule.get("destination_scope", ["any"]) or ["any"])
            if "any" not in destinations and destination_type not in destinations:
                continue
            local_hits = []
            for classifier_id in list(rule.get("classifier_ids", []) or []):
                classifier = classifier_map.get(classifier_id)
                if not classifier:
                    continue
                cname = str(classifier.get("name", "") or "")
                builtin_name = str((classifier.get("config") or {}).get("builtin_name", "") or "")
                if cname in hit_names or builtin_name in hit_names or any(item.startswith(cname) for item in hit_names):
                    local_hits.append(
                        {
                            "classifier_id": classifier_id,
                            "name": cname,
                            "category": classifier.get("category", "custom"),
                            "severity": classifier.get("severity", "medium"),
                        }
                    )
            if local_hits:
                classifier_hits = local_hits
                matched_rule = rule
                break

        action = str(matched_rule.get("action", "monitor") if matched_rule else "monitor")
        severity = str(matched_rule.get("severity", risk_level or "medium") if matched_rule else (risk_level or "medium"))
        confidence = float(matched_rule.get("confidence", 0.5) if matched_rule else 0.5)
        if not matched_rule and block_candidate and destination_type in {"usb", "upload", "cloud_sync", "clipboard"}:
            action = "block_transfer"
            severity = "high" if severity not in {"high", "critical"} else severity
            confidence = max(confidence, 0.9)

        exception = self._match_policy_exception(event, classifier_hits)
        if exception:
            return {
                "action_taken": "monitor",
                "action_result": "exception_applied",
                "severity": severity,
                "confidence": confidence,
                "policy_rule_id": matched_rule.get("id") if matched_rule else None,
                "policy_rule_name": matched_rule.get("name", "") if matched_rule else "",
                "classifier_hits": classifier_hits,
                "exception_applied": exception,
                "justification_required": False,
            }

        rollout_mode = str(policy.get("rollout_mode") or "monitor_only")
        if rollout_mode == "monitor_only":
            action = "monitor"
        elif rollout_mode == "soft_block" and action == "block_transfer":
            action = "warn_user"

        return {
            "action_taken": action,
            "action_result": "observed",
            "severity": severity,
            "confidence": confidence,
            "policy_rule_id": matched_rule.get("id") if matched_rule else None,
            "policy_rule_name": matched_rule.get("name", "") if matched_rule else "",
            "classifier_hits": classifier_hits,
            "exception_applied": {},
            "justification_required": action == "require_justification",
        }

    def _show_dlp_message(self, title, message, *, allow_continue=False):
        try:
            if platform.system() == "Windows":
                import ctypes

                flags = 0x30 | (0x0001 if allow_continue else 0x0000)
                result = ctypes.windll.user32.MessageBoxW(0, message, title, flags)
                return bool(result == 1)
            if platform.system() == "Darwin":
                button_clause = 'buttons {"Continue", "Cancel"} default button "Continue"' if allow_continue else 'buttons {"OK"} default button "OK"'
                script = f'display dialog "{message.replace(chr(34), "")}" with title "{title.replace(chr(34), "")}" {button_clause}'
                completed = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=15)
                return "Continue" in (completed.stdout or "") if allow_continue else completed.returncode == 0
            if allow_continue:
                completed = subprocess.run(["zenity", "--question", "--text", message, "--title", title], capture_output=True, timeout=15)
                return completed.returncode == 0
            subprocess.run(["zenity", "--warning", "--text", message, "--title", title], capture_output=True, timeout=15)
            return True
        except Exception:
            logger.info("dlp_message_fallback title=%s allow_continue=%s", title, allow_continue)
            return True

    def _block_destination_write(self, src_path, dest_path):
        try:
            if not dest_path or not os.path.exists(dest_path):
                return False, "destination_missing"
            if src_path and not os.path.exists(src_path):
                os.replace(dest_path, src_path)
                return True, "reverted_to_source"
            os.remove(dest_path)
            return True, "destination_removed"
        except Exception as exc:
            logger.warning("dlp_block_failed src=%s dest=%s error=%s", src_path, dest_path, exc)
            return False, str(exc)

    def _clear_clipboard_contents(self):
        try:
            import pyperclip  # type: ignore

            pyperclip.copy("")
            return True, "clipboard_cleared"
        except Exception as exc:
            logger.warning("dlp_clipboard_clear_failed error=%s", exc)
            return False, str(exc)

    def _apply_endpoint_decision(self, alert_data, *, src_path="", dest_path="", allow_continue=False):
        decision = self._evaluate_dlp_policy(
            findings=alert_data.get("findings", []),
            destination_type=str(alert_data.get("destination_type") or alert_data.get("destination") or "local"),
            risk_level=str(alert_data.get("risk_level") or "medium"),
            block_candidate=bool(alert_data.get("block_candidate", False)),
            file_path=str(alert_data.get("file_path", "") or ""),
            app_name=str(alert_data.get("app_name", "") or ""),
        )
        alert_data.update(
            {
                "actor_username": self._current_actor_username(),
                "policy_rule_id": decision.get("policy_rule_id"),
                "confidence": decision.get("confidence"),
                "action_taken": decision.get("action_taken"),
                "action_result": decision.get("action_result"),
                "justification_required": decision.get("justification_required", False),
                "exception_applied": decision.get("exception_applied", {}),
                "classifier_hits": decision.get("classifier_hits", []),
                "unsupported_reason": "",
            }
        )

        if decision.get("action_result") == "exception_applied":
            return alert_data

        title = "CropSentinel Data Protection"
        activity_target = str(alert_data.get("destination_label") or alert_data.get("destination_type") or "external destination")
        data_label = str(alert_data.get("enterprise_label") or "Sensitive data")
        if decision.get("action_taken") == "block_transfer" and dest_path:
            blocked, block_detail = self._block_destination_write(src_path, dest_path)
            alert_data["action_result"] = "blocked" if blocked else "block_failed"
            alert_data["blocking_supported"] = True
            alert_data["blocking_mode"] = "agent_enforced"
            alert_data["unsupported_reason"] = "" if blocked else block_detail
            self._show_dlp_message(
                title,
                f"{data_label} was blocked from leaving this device through {activity_target}. Contact your security team if this work is required.",
                allow_continue=False,
            )
            return alert_data

        if decision.get("action_taken") == "block_transfer" and str(alert_data.get("destination_type", "")) == "clipboard":
            blocked, block_detail = self._clear_clipboard_contents()
            alert_data["action_result"] = "blocked" if blocked else "block_failed"
            alert_data["blocking_supported"] = True
            alert_data["blocking_mode"] = "agent_enforced"
            alert_data["unsupported_reason"] = "" if blocked else block_detail
            self._show_dlp_message(
                title,
                f"{data_label} was removed from the clipboard because policy blocks this type of copy action.",
                allow_continue=False,
            )
            return alert_data

        if decision.get("action_taken") == "warn_user":
            user_allowed = self._show_dlp_message(
                title,
                f"{data_label} is being sent through {activity_target}. Continue only if this is a valid business need.",
                allow_continue=allow_continue,
            )
            if allow_continue and not user_allowed and dest_path:
                blocked, block_detail = self._block_destination_write(src_path, dest_path)
                alert_data["action_result"] = "blocked" if blocked else "block_failed"
                alert_data["blocking_supported"] = True
                alert_data["blocking_mode"] = "agent_enforced" if blocked else alert_data.get("blocking_mode", "detect_only")
                alert_data["unsupported_reason"] = "" if blocked else block_detail
            else:
                alert_data["action_result"] = "warning_shown"
            return alert_data

        return alert_data

    def _emit_contextual_dlp_alert(self, alert_data, *, allow_continue=False):
        alert_data = self._apply_endpoint_decision(alert_data, allow_continue=allow_continue)
        self.enqueue("dlp_alert", alert_data)
        self._bump_dlp_alert()
        return alert_data

    def handle_print_event(self, event):
        document_name = str(event.get("document", "") or "")
        if not document_name:
            return None
        candidates = self._recent_sensitive_candidates(file_name=document_name, within_seconds=1800)
        if not candidates:
            return None
        source = candidates[0]
        alert_data = {
            "machine_id": self.machine_id,
            "timestamp": str(event.get("timestamp") or _utcnow_iso()),
            "file_path": source.get("file_path", ""),
            "file_name": source.get("file_name", document_name),
            "file_ext": Path(source.get("file_name", document_name)).suffix.lower(),
            "file_size": 0,
            "file_hash": source.get("file_hash", ""),
            "destination": "print",
            "device": str(event.get("printer", "") or ""),
            "destination_type": "print",
            "destination_label": str(event.get("printer", "") or "printer"),
            "channel": "print",
            "event_type": "print_job",
            "risk_level": source.get("risk_level", "medium"),
            "risk_score": source.get("risk_score", 0),
            "is_known_sensitive": True,
            "findings": list(source.get("findings", []) or []),
            "enterprise_label": source.get("enterprise_label", ""),
            "sensitivity_score": int(source.get("risk_score", 0) or 0),
            "label_source": "print_document_correlation",
            "label_reason": f"Printed document matched recent sensitive file {source.get('file_name', document_name)}",
            "block_candidate": False,
            "block_reason": "",
            "blocking_supported": False,
            "blocking_mode": "detect_only",
            "content_fingerprint": source.get("content_fingerprint", ""),
            "actor_username": self._current_actor_username(),
            "app_name": str(event.get("printer", "") or ""),
            "scoring": {"channel": "print", "pages": int(event.get("pages", 0) or 0)},
        }
        return self._emit_contextual_dlp_alert(alert_data, allow_continue=False)

    def handle_browser_upload_event(self, event):
        domain = str(event.get("domain", "") or "").lower()
        if not domain:
            return None
        try:
            from dlp_destination import EMAIL_ATTACHMENT_DOMAINS, UPLOAD_DOMAINS
        except Exception:
            EMAIL_ATTACHMENT_DOMAINS = set()
            UPLOAD_DOMAINS = set()
        if domain not in UPLOAD_DOMAINS and domain not in EMAIL_ATTACHMENT_DOMAINS:
            return None
        candidates = self._recent_sensitive_candidates(within_seconds=180)
        if not candidates:
            return None
        source = candidates[0]
        destination_type = "email" if domain in EMAIL_ATTACHMENT_DOMAINS else "upload"
        alert_data = {
            "machine_id": self.machine_id,
            "timestamp": str(event.get("timestamp") or _utcnow_iso()),
            "file_path": source.get("file_path", ""),
            "file_name": source.get("file_name", ""),
            "file_ext": Path(source.get("file_name", "")).suffix.lower(),
            "file_size": 0,
            "file_hash": source.get("file_hash", ""),
            "destination": destination_type,
            "device": domain,
            "destination_type": destination_type,
            "destination_label": domain,
            "channel": "upload" if destination_type == "upload" else "file",
            "event_type": "browser_upload_correlation",
            "risk_level": source.get("risk_level", "medium"),
            "risk_score": source.get("risk_score", 0),
            "is_known_sensitive": True,
            "findings": list(source.get("findings", []) or []),
            "enterprise_label": source.get("enterprise_label", ""),
            "sensitivity_score": int(source.get("risk_score", 0) or 0),
            "label_source": "browser_upload_correlation",
            "label_reason": f"Recent sensitive file activity correlated with browser visit to {domain}",
            "block_candidate": destination_type == "upload",
            "block_reason": f"Recent sensitive file may be leaving through {domain}",
            "blocking_supported": False,
            "blocking_mode": "detect_only",
            "content_fingerprint": source.get("content_fingerprint", ""),
            "actor_username": self._current_actor_username(),
            "app_name": str(event.get("browser", "") or ""),
            "scoring": {"channel": "browser", "domain": domain, "url": str(event.get("url", "") or "")},
        }
        return self._emit_contextual_dlp_alert(alert_data, allow_continue=False)

    def handle_clipboard_text(self, event):
        text = str(event.get("text", "") or "")
        if len(text.strip()) < 8:
            return None
        engine = _get_dlp_engine()
        if engine is None:
            return None
        scan = engine.scan(text[:500_000])
        findings = list(scan.get("findings", []) or [])
        if not findings:
            return None
        from enterprise_labels import derive_block_metadata, derive_enterprise_label

        label_summary = derive_enterprise_label(
            findings,
            risk=scan.get("risk", "none"),
            risk_score=int(scan.get("total_weight", 0) or 0),
            inspect_status="inspected",
        )
        block_summary = derive_block_metadata("modify", label_summary, destination_type="clipboard")
        alert_data = {
            "machine_id": self.machine_id,
            "timestamp": str(event.get("timestamp") or _utcnow_iso()),
            "file_path": "",
            "file_name": "Clipboard",
            "file_ext": "",
            "file_size": len(text.encode("utf-8", errors="ignore")),
            "file_hash": "",
            "destination": "clipboard",
            "device": "clipboard",
            "destination_type": "clipboard",
            "destination_label": "clipboard",
            "channel": "clipboard",
            "event_type": "clipboard_copy",
            "risk_level": scan.get("risk", "medium"),
            "risk_score": int(scan.get("total_weight", 0) or 0),
            "is_known_sensitive": False,
            "findings": findings,
            "enterprise_label": label_summary.get("enterprise_label", ""),
            "sensitivity_score": int(label_summary.get("sensitivity_score", 0) or 0),
            "label_source": "clipboard_inspection",
            "label_reason": label_summary.get("label_reason", ""),
            "block_candidate": bool(block_summary.get("block_candidate", False)) or int(label_summary.get("sensitivity_score", 0) or 0) >= 3,
            "block_reason": block_summary.get("block_reason", "") or "Sensitive content copied to clipboard",
            "blocking_supported": True,
            "blocking_mode": "agent_enforced",
            "content_fingerprint": str(event.get("content_fingerprint", "") or hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()),
            "actor_username": self._current_actor_username(),
            "app_name": "clipboard",
            "scoring": {"channel": "clipboard", "preview_chars": min(len(text), 120)},
        }
        self._remember_sensitive_file(alert_data, text)
        return self._emit_contextual_dlp_alert(alert_data, allow_continue=False)

    def _classify_destination(self, file_path, file_size):
        destination = "local"
        device = ""
        detector = get_destination_detector()
        if detector:
            try:
                destination, device = detector.classify(file_path, file_size=file_size)
            except Exception:
                return "local", ""
        return destination or "local", device or ""

    def _extract_live_text(self, file_path, file_ext, file_size):
        parser = _get_live_document_parser()
        if parser is None:
            return None
        try:
            result = parser.inspect(file_path, file_ext, file_size)
        except Exception as exc:
            logger.debug("Live parser inspect error for %s: %s", file_path, exc)
            return None
        extracted = str(result.get("extracted_text", "") or "")
        if not extracted.strip():
            return None
        return {
            "content": extracted,
            "parser_type": str(result.get("parser_type", "") or ""),
            "inspect_status": str(result.get("inspect_status", "") or ""),
            "inspect_reason": str(result.get("inspect_reason", "") or ""),
        }

    def _default_label_payload(self, action, destination_type="local", *, device=""):
        from enterprise_labels import derive_block_metadata

        label_summary = {
            "enterprise_label": "Public",
            "sensitivity_score": 0,
            "label_source": "event_default",
            "label_reason": "No stored content label available",
            "finding_types": [],
            "findings_count": 0,
            "risk": "none",
            "risk_score": 0,
        }
        block = derive_block_metadata(action, label_summary, destination_type=destination_type)
        return {
            **label_summary,
            **block,
            "destination_type": destination_type,
            "destination_label": device or destination_type,
        }

    def _lookup_inventory_label(self, path, *, action="modify", destination_type="local", device=""):
        if not path:
            return None
        try:
            from dlp_fingerprint import DB_PATH, hash_file
            from enterprise_labels import derive_block_metadata, derive_enterprise_label

            normalized = _normalize_path(path)
            conn = sqlite3.connect(str(DB_PATH), timeout=2)
            conn.row_factory = sqlite3.Row
            try:
                row = conn.execute(
                    "SELECT label_summary FROM file_inventory WHERE machine_id = ? AND normalized_path = ?",
                    (self.machine_id, normalized),
                ).fetchone()
            finally:
                conn.close()
            if row and row["label_summary"]:
                summary = json.loads(row["label_summary"])
                block = derive_block_metadata(action, summary, destination_type=destination_type)
                return {
                    **summary,
                    **block,
                    "destination_type": destination_type,
                    "destination_label": device or destination_type,
                }

            engine = _get_dlp_engine()
            fp_store = engine._get_fingerprint_store() if engine else None
            if fp_store:
                file_hash = hash_file(path)
                if file_hash:
                    existing = fp_store.lookup(file_hash)
                    if existing and existing.findings_json:
                        findings = json.loads(existing.findings_json)
                        summary = derive_enterprise_label(
                            findings,
                            risk=existing.risk_level,
                            risk_score=int(existing.risk_score or 0),
                            inspect_status="fingerprint_lookup",
                        )
                        block = derive_block_metadata(action, summary, destination_type=destination_type)
                        return {
                            **summary,
                            **block,
                            "destination_type": destination_type,
                            "destination_label": device or destination_type,
                        }
        except Exception:
            return None
        return None

    def _lookup_label_for_event(self, src_path, dest_path, action):
        destination_type = "local"
        device = ""
        if action == "move" and dest_path:
            destination_type, device = self._classify_destination(dest_path, 0)
        label_data = self._lookup_inventory_label(
            src_path,
            action=action,
            destination_type=destination_type,
            device=device,
        )
        if not label_data and dest_path:
            label_data = self._lookup_inventory_label(
                dest_path,
                action=action,
                destination_type=destination_type,
                device=device,
            )
        return label_data or self._default_label_payload(action, destination_type, device=device)

    def _send(self, action, src_path, dest_path="", is_directory=False,
              file_data=None, backup_skip_reason="", backup_size=None):
        if self._should_skip(src_path):
            return
        if self._debounce(f"{action}:{src_path}"):
            return

        name = os.path.basename(src_path)
        # Skip hidden files
        if name.startswith("."):
            return

        ext = ""
        if not is_directory:
            raw_ext = os.path.splitext(src_path)[1].lower()
            if raw_ext and len(raw_ext) <= 10 and raw_ext[1:].isalpha():
                ext = raw_ext
        try:
            size = os.path.getsize(src_path) if os.path.exists(src_path) else 0
        except OSError:
            size = 0
        if action == "delete" and backup_size is not None:
            size = int(backup_size or 0)

        data = {
            "machine_id": self.machine_id,
            "timestamp": _utcnow_iso(),
            "action": action,
            "file_path": src_path,
            "file_name": name,
            "file_ext": ext,
            "file_size": size,
            "destination": dest_path,
            "is_directory": is_directory,
            "actor_username": self._current_actor_username(),
        }
        label_data = self._lookup_label_for_event(src_path, dest_path, action)
        if action in ("create", "modify") and not is_directory:
            label_data = self._dlp_check_external_write(src_path, name, ext, size, action) or self._dlp_scan_v2(src_path, name, ext, size) or label_data
        elif action == "move" and not is_directory and dest_path:
            label_data = self._dlp_check_move(src_path, dest_path, name, ext, size) or label_data
        data.update(label_data)

        # Attach base64 backup for deleted files
        if action == "delete":
            data["backup_available"] = file_data is not None
            data["backup_skip_reason"] = "" if file_data is not None else backup_skip_reason
            if file_data is not None:
                data["file_data"] = file_data

        self.enqueue("file", data)
        logger.debug(f"File {action}: {src_path}")
        return

        # ── DLP v2 scan on create / modify ───────────────────────────────
        if action in ("create", "modify") and not is_directory:
            self._dlp_scan_v2(src_path, name, ext, size)

        # ── DLP: check moved files for USB/upload destination ────────────
        if action == "move" and not is_directory and dest_path:
            self._dlp_check_move(src_path, dest_path, name, ext, size)

    def _dlp_scan_v2(self, file_path, file_name, file_ext, file_size):
        """
        DLP v2 scan pipeline:
        1. Extension / debounce guard
        2. Read file content
        3. Detect destination (USB / upload / cloud_sync / local)
        4. Run engine.scan_file_v2() with full context
        5. Enqueue enriched dlp_alert event
        """
        try:
            from enterprise_labels import derive_block_metadata, derive_enterprise_label
            from dlp_fingerprint import hash_file

            # Only scan supported live-inspection extensions.
            if file_ext not in DLP_SCAN_EXTENSIONS and file_ext not in LIVE_PARSER_EXTENSIONS:
                return self._default_label_payload("create")

            # Fix 6: 30-second per-file content-scan debounce
            if self._dlp_scan_debounce(file_path):
                return self._lookup_inventory_label(file_path) or self._default_label_payload("modify")

            engine = _get_dlp_engine()
            if engine is None:
                return self._default_label_payload("modify")
            if not engine.should_scan_file(file_path, file_size):
                return self._default_label_payload("modify")

            parser_meta = {}
            if file_ext in DLP_SCAN_EXTENSIONS:
                try:
                    with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read(500_000)
                except (OSError, PermissionError, FileNotFoundError):
                    return self._lookup_inventory_label(file_path) or self._default_label_payload("modify")
            else:
                parsed = self._extract_live_text(file_path, file_ext, file_size)
                if not parsed:
                    return self._lookup_inventory_label(file_path) or self._default_label_payload("modify")
                content = parsed.get("content", "")
                parser_meta = parsed

            if not content or len(content.strip()) < 10:
                return self._default_label_payload("modify")

            destination, device = self._classify_destination(file_path, file_size)
            scan_summary = engine.scan(content)
            label_summary = derive_enterprise_label(
                scan_summary.get("findings", []),
                risk=scan_summary.get("risk", "none"),
                risk_score=int(scan_summary.get("total_weight", 0) or 0),
                inspect_status="inspected",
            )
            block_summary = derive_block_metadata("modify", label_summary, destination_type=destination)
            file_label_data = {
                **label_summary,
                **block_summary,
                "destination_type": destination,
                "destination_label": device or destination,
            }

            # Run v2 pipeline (Fix 3: pass file_size/ext for scoring)
            result = engine.scan_file_v2(
                file_path=file_path,
                content=content,
                destination=destination,
                device=device,
                is_repeated=self._is_repeated_behaviour(),
                file_size=file_size,
                file_ext=file_ext,
                file_hash=hash_file(file_path) or "",
            )

            if result is None:
                return file_label_data

            # Build enriched alert
            alert_label = dict(result.get("label_summary") or label_summary)
            alert_block = derive_block_metadata("modify", alert_label, destination_type=destination)
            alert_data = {
                "machine_id":         self.machine_id,
                "timestamp":          _utcnow_iso(),
                "file_path":          file_path,
                "file_name":          file_name,
                "file_ext":           file_ext,
                "file_size":          file_size,
                "file_hash":          result["file_hash"],
                "destination":        result["destination"],
                "device":             result.get("device", ""),
                "risk_level":         result["risk_level"],
                "risk_score":         result["risk_score"],
                "is_known_sensitive": result["is_known_sensitive"],
                "findings":           result["findings"],
                "scoring":            result.get("scoring", {}),
                "enterprise_label":   alert_label.get("enterprise_label", ""),
                "sensitivity_score":  int(alert_label.get("sensitivity_score", 0) or 0),
                "label_source":       alert_label.get("label_source", ""),
                "label_reason":       alert_label.get("label_reason", ""),
                "block_candidate":    bool(alert_block.get("block_candidate", False)),
                "block_reason":       alert_block.get("block_reason", ""),
                "blocking_supported": bool(alert_block.get("blocking_supported", False)),
                "blocking_mode":      alert_block.get("blocking_mode", "detect_only"),
                "destination_type":   result["destination"],
                "destination_label":  result.get("device", "") or result["destination"],
                "content_fingerprint": hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest(),
            }
            if parser_meta:
                alert_data["scoring"] = {
                    **(result.get("scoring", {}) or {}),
                    "parser_type": parser_meta.get("parser_type", ""),
                    "inspect_status": parser_meta.get("inspect_status", ""),
                    "inspect_reason": parser_meta.get("inspect_reason", ""),
                }

            if "fingerprint" in result:
                alert_data["fingerprint"] = result["fingerprint"]

            self._remember_sensitive_file(alert_data, content)
            alert_data = self._apply_endpoint_decision(alert_data, src_path=file_path, allow_continue=False)
            self.enqueue("dlp_alert", alert_data)
            self._bump_dlp_alert()
            logger.info(
                f"DLP v2 {result['risk_level'].upper()} (score={result['risk_score']}): "
                f"{file_path} → {destination}"
                f" ({len(result['findings'])} finding types)"
            )

            return file_label_data
        except Exception as e:
            logger.debug(f"DLP v2 scan error for {file_path}: {e}")
        return self._lookup_inventory_label(file_path) or self._default_label_payload("modify")

    def _dlp_check_move(self, src_path, dest_path, file_name, file_ext, file_size):
        """
        When a file is moved, check if the destination is USB or upload.
        If we have a fingerprint for the file, re-score with the new
        destination context and emit an alert if warranted.
        """
        try:
            from dlp_destination import is_usb_path, is_cloud_sync_path
            from enterprise_labels import derive_block_metadata, derive_enterprise_label

            usb, device = is_usb_path(dest_path)
            if not usb and not is_cloud_sync_path(dest_path):
                return self._lookup_inventory_label(src_path, action="move") or self._default_label_payload("move")

            destination = "usb" if usb else "cloud_sync"

            # Fix 6: 5s debounce for moves (separate from content-scan debounce)
            if self._dlp_move_debounce(f"{src_path}->{dest_path}"):
                return self._lookup_inventory_label(src_path, action="move", destination_type=destination, device=device) or self._default_label_payload("move", destination, device=device)

            # Check if this file is known sensitive via fingerprint
            engine = _get_dlp_engine()
            if engine is None:
                return self._lookup_inventory_label(src_path, action="move", destination_type=destination, device=device) or self._default_label_payload("move", destination, device=device)

            fp_store = engine._get_fingerprint_store()
            if fp_store is None:
                return self._lookup_inventory_label(src_path, action="move", destination_type=destination, device=device) or self._default_label_payload("move", destination, device=device)

            # Try to hash the file at the source path (may still exist)
            from dlp_fingerprint import hash_file
            file_hash = hash_file(src_path) or hash_file(dest_path)
            if not file_hash:
                return self._lookup_inventory_label(src_path, action="move", destination_type=destination, device=device) or self._default_label_payload("move", destination, device=device)

            # Fix 1: retry lookup to handle race against in-progress scan
            existing = fp_store.lookup_with_retry(file_hash, retries=2, delay=0.2)
            if not existing or not existing.is_sensitive:
                return self._lookup_inventory_label(src_path, action="move", destination_type=destination, device=device) or self._default_label_payload("move", destination, device=device)

            # Known sensitive file moving to USB/cloud — emit alert
            import json
            findings = json.loads(existing.findings_json) if existing.findings_json else []

            from dlp_scoring import score_dlp_event, is_outside_working_hours
            scoring = score_dlp_event(
                findings=findings,
                destination=destination,
                is_outside_hours=is_outside_working_hours(),
                repeated=self._is_repeated_behaviour(),
                is_known_sensitive=True,
                file_size=file_size,
                file_ext=file_ext,
                fingerprint_known=True,
            )

            alert_data = {
                "machine_id":         self.machine_id,
                "timestamp":          _utcnow_iso(),
                "file_path":          dest_path,
                "file_name":          file_name,
                "file_ext":           file_ext,
                "file_size":          file_size,
                "file_hash":          file_hash,
                "destination":        destination,
                "device":             device,
                "risk_level":         scoring.risk_level,
                "risk_score":         scoring.total_score,
                "is_known_sensitive": True,
                "findings":           findings,
                "scoring":            scoring.to_dict(),
                "fingerprint": {
                    "source": "copied",
                    "first_seen": existing.first_seen,
                    "original_path": existing.file_path,
                },
            }
            label_summary = derive_enterprise_label(
                findings,
                risk=scoring.risk_level,
                risk_score=int(scoring.total_score or 0),
                inspect_status="fingerprint_lookup",
            )
            block_summary = derive_block_metadata("move", label_summary, destination_type=destination)
            alert_data.update(
                {
                    "enterprise_label": label_summary.get("enterprise_label", ""),
                    "sensitivity_score": int(label_summary.get("sensitivity_score", 0) or 0),
                    "label_source": label_summary.get("label_source", ""),
                    "label_reason": label_summary.get("label_reason", ""),
                    "block_candidate": bool(block_summary.get("block_candidate", False)),
                    "block_reason": block_summary.get("block_reason", ""),
                    "blocking_supported": bool(block_summary.get("blocking_supported", False)),
                    "blocking_mode": block_summary.get("blocking_mode", "detect_only"),
                    "destination_type": destination,
                    "destination_label": device or destination,
                }
            )

            self._remember_sensitive_file(alert_data)
            alert_data = self._apply_endpoint_decision(alert_data, src_path=src_path, dest_path=dest_path, allow_continue=True)
            self.enqueue("dlp_alert", alert_data)
            self._bump_dlp_alert()
            logger.info(
                f"DLP v2 MOVE {scoring.risk_level.upper()} (score={scoring.total_score}): "
                f"known sensitive file → {destination} ({device})"
            )

            return {
                **label_summary,
                **block_summary,
                "destination_type": destination,
                "destination_label": device or destination,
            }
        except Exception as e:
            logger.debug(f"DLP move check error: {e}")
        return self._lookup_inventory_label(src_path, action="move") or self._default_label_payload("move")

    def _dlp_check_external_write(self, file_path, file_name, file_ext, file_size, action):
        """
        Harden copy coverage by treating files newly written onto removable or
        cloud-synced destinations as transfer attempts, even when the source
        path is unknown to watchdog.
        """
        try:
            destination, device = self._classify_destination(file_path, file_size)
            if destination not in {"usb", "cloud_sync"}:
                return None

            debounce_key = f"external:{action}:{file_path}"
            if self._dlp_move_debounce(debounce_key):
                return self._lookup_inventory_label(
                    file_path,
                    action="move",
                    destination_type=destination,
                    device=device,
                ) or self._default_label_payload("move", destination, device=device)

            from dlp_fingerprint import hash_file
            from dlp_scoring import is_outside_working_hours, score_dlp_event
            from enterprise_labels import derive_block_metadata, derive_enterprise_label

            engine = _get_dlp_engine()
            fp_store = engine._get_fingerprint_store() if engine else None
            file_hash = hash_file(file_path)
            if not fp_store or not file_hash:
                return None

            existing = fp_store.lookup_with_retry(file_hash, retries=2, delay=0.2)
            if not existing or not existing.is_sensitive:
                return None

            findings = json.loads(existing.findings_json) if existing.findings_json else []
            scoring = score_dlp_event(
                findings=findings,
                destination=destination,
                is_outside_hours=is_outside_working_hours(),
                repeated=self._is_repeated_behaviour(),
                is_known_sensitive=True,
                file_size=file_size,
                file_ext=file_ext,
                fingerprint_known=True,
            )
            label_summary = derive_enterprise_label(
                findings,
                risk=scoring.risk_level,
                risk_score=int(scoring.total_score or 0),
                inspect_status="fingerprint_lookup",
            )
            block_summary = derive_block_metadata("move", label_summary, destination_type=destination)
            alert_data = {
                "machine_id": self.machine_id,
                "timestamp": _utcnow_iso(),
                "file_path": file_path,
                "file_name": file_name,
                "file_ext": file_ext,
                "file_size": file_size,
                "file_hash": file_hash,
                "destination": destination,
                "device": device,
                "risk_level": scoring.risk_level,
                "risk_score": scoring.total_score,
                "is_known_sensitive": True,
                "findings": findings,
                "scoring": scoring.to_dict(),
                "fingerprint": {
                    "source": "copied",
                    "first_seen": existing.first_seen,
                    "original_path": existing.file_path,
                },
                "enterprise_label": label_summary.get("enterprise_label", ""),
                "sensitivity_score": int(label_summary.get("sensitivity_score", 0) or 0),
                "label_source": label_summary.get("label_source", ""),
                "label_reason": label_summary.get("label_reason", ""),
                "block_candidate": bool(block_summary.get("block_candidate", False)),
                "block_reason": block_summary.get("block_reason", ""),
                "blocking_supported": bool(block_summary.get("blocking_supported", False)),
                "blocking_mode": block_summary.get("blocking_mode", "detect_only"),
                "destination_type": destination,
                "destination_label": device or destination,
            }
            alert_data = self._apply_endpoint_decision(alert_data, dest_path=file_path, allow_continue=True)
            self._remember_sensitive_file(alert_data)
            self.enqueue("dlp_alert", alert_data)
            self._bump_dlp_alert()
            logger.info(
                "DLP external write %s (score=%s): known sensitive file -> %s (%s)",
                scoring.risk_level.upper(),
                scoring.total_score,
                destination,
                device,
            )
            return {
                **label_summary,
                **block_summary,
                "destination_type": destination,
                "destination_label": device or destination,
            }
        except Exception as exc:
            logger.debug("DLP external write check error for %s: %s", file_path, exc)
        return None

    def dispatch(self, event):
        is_dir = event.is_directory
        etype = event.event_type
        src = event.src_path

        if etype == "created":
            if not is_dir:
                self._schedule_backup_prime(src)
            self._send("create", src, is_directory=is_dir)
        elif etype == "deleted":
            # Try to read backup from cache first, then from disk
            cached = self._drop_cached_backup(src)
            if cached is None:
                cached = self._read_local_vault_cache(src)
            backup = cached.get("data", "") if cached is not None else None
            backup_size = cached.get("size") if cached is not None else None
            skip_reason = ""
            if backup is None and not is_dir:
                backup = _read_file_base64(src)
                if backup == "":
                    backup = None
            if backup is not None:
                if (backup_size is None or int(backup_size or 0) == 0) and backup:
                    try:
                        backup_size = len(base64.b64decode(backup.encode("ascii"), validate=False))
                    except Exception:
                        backup_size = backup_size
                logger.info(f"Delete captured with backup: {src}")
                self._drop_local_vault_cache(src)
            else:
                skip_reason = self._fallback_backup_reason(src, is_dir)
                logger.info(f"Delete not recoverable: {src} ({skip_reason})")
            self._send(
                "delete",
                src,
                is_directory=is_dir,
                file_data=backup,
                backup_skip_reason=skip_reason,
                backup_size=backup_size,
            )
        elif etype == "modified":
            if is_dir:
                return
            ext = os.path.splitext(src)[1].lower()
            self._schedule_backup_prime(src)
            if ext in SENSITIVE_EXTENSIONS:
                self._send("modify", src)
        elif etype == "moved":
            dest = getattr(event, "dest_path", "")
            if not is_dir and dest:
                moved = self._move_cached_backup(src, dest)
                if not moved:
                    self._schedule_backup_prime(dest)
            self._send("move", src, getattr(event, "dest_path", ""),
                       is_directory=is_dir)

    def on_created(self, event):
        self.dispatch(event)

    def on_modified(self, event):
        self.dispatch(event)

    def on_deleted(self, event):
        self.dispatch(event)

    def on_moved(self, event):
        self.dispatch(event)
