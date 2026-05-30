"""
CropSentinel - Baseline file inventory scanner and uploader.

Builds a resumable per-machine inventory over mounted roots, stores the latest
file fingerprint/label summary in the existing local fingerprint SQLite DB, and
uploads bounded batches to the backend using a dedicated low-priority channel.
"""

from __future__ import annotations

import concurrent.futures
import hashlib
import io
import json
import logging
import os
import platform
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional
from xml.etree import ElementTree as ET

from dlp_fingerprint import (
    DB_PATH,
    FingerprintStore,
    HASH_CHUNK_SIZE,
    PARTIAL_HASH_BYTES,
    PARTIAL_HASH_THRESHOLD,
    _secure_permissions,
)
from enterprise_labels import derive_enterprise_label

logger = logging.getLogger("croppro.baseline_inventory")

SCAN_VERSION = "baseline-v1"
DISCOVERY_INTERVAL_SECONDS = 300
MAX_TEXT_EXTRACT_CHARS = 250_000
MAX_ZIP_MEMBER_BYTES = 2 * 1024 * 1024
MAX_NESTED_PARSE_DEPTH = 2
FILE_BATCH_MULTIPLIER = 4
SQLITE_TIMEOUT = 30

TEXT_EXTENSIONS = {
    ".txt", ".csv", ".json", ".xml", ".yml", ".yaml", ".log", ".ini",
    ".cfg", ".conf", ".properties", ".env", ".md", ".rst", ".html",
    ".htm", ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".go", ".rb",
    ".php", ".ps1", ".bat", ".cmd", ".sh", ".sql", ".cs", ".cpp", ".c",
    ".h", ".hpp", ".dockerfile",
}

OFFICE_EXTENSIONS = {".docx", ".xlsx", ".pptx"}
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp"}
ZIP_EXTENSIONS = {".zip", ".jar", ".war"}
EMAIL_EXTENSIONS = {".eml"}
SKIP_DIR_NAMES = {
    "$recycle.bin", "system volume information", ".git", ".hg", ".svn",
    "__pycache__", "node_modules", ".venv", "venv", ".tox", ".pytest_cache",
    ".mypy_cache", ".next", "dist", "build",
}
WINDOWS_SYSTEM_ROOTS = {
    r"c:\windows",
    r"c:\program files",
    r"c:\program files (x86)",
    r"c:\programdata",
}
PSEUDO_MOUNT_PREFIXES = (
    "/proc", "/sys", "/dev", "/run", "/var/run", "/snap",
)


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _normalize_path(path: str) -> str:
    try:
        normalized = os.path.normpath(os.path.abspath(path))
    except Exception:
        normalized = os.path.normpath(path)
    if platform.system() == "Windows":
        return normalized.lower()
    return normalized


def _root_id(root_path: str) -> str:
    normalized = _normalize_path(root_path)
    return hashlib.sha1(normalized.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _is_cloud_virtual_mount(path: str) -> bool:
    low = _normalize_path(path)
    if platform.system() == "Windows":
        return low.startswith(r"\\?\volume{")
    return False


def enumerate_mounted_roots() -> list[str]:
    os_name = platform.system()
    roots: list[str] = []
    if os_name == "Windows":
        roots = _enumerate_windows_roots()
    else:
        roots = _enumerate_posix_roots()
    seen = set()
    result = []
    for root in roots:
        norm = _normalize_path(root)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        result.append(root)
    return result


def _enumerate_windows_roots() -> list[str]:
    roots = []
    try:
        import ctypes

        bitmask = ctypes.windll.kernel32.GetLogicalDrives()
        for idx, letter in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
            if not (bitmask & (1 << idx)):
                continue
            root = f"{letter}:\\"
            try:
                dtype = ctypes.windll.kernel32.GetDriveTypeW(root)
            except Exception:
                dtype = 0
            # 2 removable, 3 fixed, 4 network
            if dtype not in (2, 3, 4):
                continue
            if os.path.exists(root) and os.access(root, os.R_OK):
                roots.append(root)
    except Exception as exc:
        logger.debug("Windows drive enumeration failed: %s", exc)
    return roots


def _enumerate_posix_roots() -> list[str]:
    roots = ["/"]
    mtab = "/proc/mounts" if Path("/proc/mounts").exists() else "/etc/mtab"
    try:
        with open(mtab, "r", encoding="utf-8", errors="ignore") as handle:
            for line in handle:
                parts = line.split()
                if len(parts) < 2:
                    continue
                mountpoint = parts[1]
                if any(mountpoint.startswith(prefix) for prefix in PSEUDO_MOUNT_PREFIXES):
                    continue
                if os.path.exists(mountpoint) and os.access(mountpoint, os.R_OK):
                    roots.append(mountpoint)
    except Exception as exc:
        logger.debug("POSIX mount enumeration failed: %s", exc)
    return roots


def _hash_file_unbounded(file_path: str, max_size: Optional[int]) -> Optional[str]:
    try:
        p = Path(file_path)
        if not p.is_file():
            return None
        size = p.stat().st_size
        if size == 0:
            return hashlib.sha256(b"").hexdigest()
        if max_size and size > max_size:
            return None

        h = hashlib.sha256()
        if size <= PARTIAL_HASH_THRESHOLD:
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(HASH_CHUNK_SIZE)
                    if not chunk:
                        break
                    h.update(chunk)
        else:
            h.update(f"__partial__{size}__".encode("utf-8"))
            with open(file_path, "rb") as f:
                remaining = PARTIAL_HASH_BYTES
                while remaining > 0:
                    chunk = f.read(min(HASH_CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    h.update(chunk)
                    remaining -= len(chunk)
                tail_start = max(size - PARTIAL_HASH_BYTES, PARTIAL_HASH_BYTES)
                f.seek(tail_start)
                while True:
                    chunk = f.read(HASH_CHUNK_SIZE)
                    if not chunk:
                        break
                    h.update(chunk)
        return h.hexdigest()
    except (OSError, PermissionError):
        return None


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()


@dataclass
class BaselineInventoryConfig:
    enabled: bool = True
    worker_count: int = 2
    io_throttle_seconds: float = 0.02
    upload_interval_seconds: int = 30
    upload_batch_size: int = 100
    max_hash_file_size: int = 0
    max_parser_file_size: int = 25 * 1024 * 1024
    max_ocr_file_size: int = 10 * 1024 * 1024
    rescan_unchanged_after_seconds: int = 24 * 3600
    mount_discovery_interval_seconds: int = DISCOVERY_INTERVAL_SECONDS

    @classmethod
    def from_payload(cls, payload: dict[str, Any] | None) -> "BaselineInventoryConfig":
        data = payload or {}
        return cls(
            enabled=_safe_bool(data.get("enabled"), True),
            worker_count=max(1, min(_safe_int(data.get("worker_count"), 2), 8)),
            io_throttle_seconds=max(0.0, min(_safe_float(data.get("io_throttle_seconds"), 0.02), 2.0)),
            upload_interval_seconds=max(5, min(_safe_int(data.get("upload_interval_seconds"), 30), 3600)),
            upload_batch_size=max(10, min(_safe_int(data.get("upload_batch_size"), 100), 1000)),
            max_hash_file_size=max(0, _safe_int(data.get("max_hash_file_size"), 0)),
            max_parser_file_size=max(64 * 1024, _safe_int(data.get("max_parser_file_size"), 25 * 1024 * 1024)),
            max_ocr_file_size=max(64 * 1024, _safe_int(data.get("max_ocr_file_size"), 10 * 1024 * 1024)),
            rescan_unchanged_after_seconds=max(3600, _safe_int(data.get("rescan_unchanged_after_seconds"), 24 * 3600)),
            mount_discovery_interval_seconds=max(60, _safe_int(data.get("mount_discovery_interval_seconds"), DISCOVERY_INTERVAL_SECONDS)),
        )


class InventoryStore:
    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS file_inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        machine_id TEXT NOT NULL,
        root_id TEXT NOT NULL,
        scan_job_id INTEGER,
        absolute_path TEXT NOT NULL,
        normalized_path TEXT NOT NULL,
        file_name TEXT NOT NULL DEFAULT '',
        extension TEXT NOT NULL DEFAULT '',
        size_bytes INTEGER NOT NULL DEFAULT 0,
        mtime_ns INTEGER NOT NULL DEFAULT 0,
        ctime_ns INTEGER NOT NULL DEFAULT 0,
        owner_name TEXT NOT NULL DEFAULT '',
        sha256 TEXT NOT NULL DEFAULT '',
        content_fingerprint TEXT NOT NULL DEFAULT '',
        scan_version TEXT NOT NULL DEFAULT '',
        scan_status TEXT NOT NULL DEFAULT 'pending',
        inspect_status TEXT NOT NULL DEFAULT 'pending',
        inspect_reason TEXT NOT NULL DEFAULT '',
        parser_type TEXT NOT NULL DEFAULT '',
        findings_summary TEXT NOT NULL DEFAULT '{}',
        label_summary TEXT NOT NULL DEFAULT '{}',
        extracted_text_hash TEXT NOT NULL DEFAULT '',
        parser_cache_key TEXT NOT NULL DEFAULT '',
        first_seen_at TEXT NOT NULL DEFAULT '',
        last_seen_at TEXT NOT NULL DEFAULT '',
        last_scanned_at TEXT NOT NULL DEFAULT '',
        upload_status TEXT NOT NULL DEFAULT 'pending',
        uploaded_at TEXT DEFAULT NULL,
        dirty INTEGER NOT NULL DEFAULT 1,
        last_upload_error TEXT NOT NULL DEFAULT '',
        UNIQUE(machine_id, normalized_path)
    );
    CREATE INDEX IF NOT EXISTS idx_file_inventory_machine_path
        ON file_inventory(machine_id, normalized_path);
    CREATE INDEX IF NOT EXISTS idx_file_inventory_norm_hash
        ON file_inventory(normalized_path, sha256);
    CREATE INDEX IF NOT EXISTS idx_file_inventory_upload
        ON file_inventory(upload_status, dirty, id);

    CREATE TABLE IF NOT EXISTS scan_jobs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        machine_id TEXT NOT NULL,
        root_id TEXT NOT NULL,
        root_path TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        cursor_path TEXT NOT NULL DEFAULT '',
        scan_version TEXT NOT NULL DEFAULT '',
        started_at TEXT DEFAULT NULL,
        completed_at TEXT DEFAULT NULL,
        updated_at TEXT NOT NULL DEFAULT '',
        last_error TEXT NOT NULL DEFAULT '',
        UNIQUE(machine_id, root_id)
    );
    CREATE INDEX IF NOT EXISTS idx_scan_jobs_status
        ON scan_jobs(machine_id, status, updated_at);

    CREATE TABLE IF NOT EXISTS upload_state (
        state_key TEXT PRIMARY KEY,
        state_value TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL DEFAULT ''
    );
    """

    def __init__(self, db_path: Path = DB_PATH):
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), timeout=SQLITE_TIMEOUT, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous = NORMAL")
        self._conn.executescript(self._SCHEMA)
        self._conn.commit()
        _secure_permissions(db_path)

    def close(self):
        with self._lock:
            self._conn.close()

    def ensure_scan_job(self, machine_id: str, root_id: str, root_path: str, scan_version: str) -> int:
        now = _utcnow_iso()
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO scan_jobs(machine_id, root_id, root_path, status, cursor_path, scan_version, updated_at)
                VALUES (?, ?, ?, 'pending', '', ?, ?)
                ON CONFLICT(machine_id, root_id) DO UPDATE SET
                    root_path = excluded.root_path,
                    scan_version = excluded.scan_version,
                    updated_at = excluded.updated_at
                """,
                (machine_id, root_id, root_path, scan_version, now),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT id FROM scan_jobs WHERE machine_id = ? AND root_id = ?",
                (machine_id, root_id),
            ).fetchone()
            return int(row["id"])

    def reset_due_jobs(self, machine_id: str, rescan_before: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE scan_jobs
                SET status = 'pending', cursor_path = '', updated_at = ?
                WHERE machine_id = ? AND status = 'completed' AND completed_at IS NOT NULL AND completed_at <= ?
                """,
                (_utcnow_iso(), machine_id, rescan_before),
            )
            self._conn.commit()

    def next_scan_job(self, machine_id: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM scan_jobs
                WHERE machine_id = ? AND status IN ('pending', 'scanning')
                ORDER BY CASE status WHEN 'scanning' THEN 0 ELSE 1 END, updated_at ASC, id ASC
                LIMIT 1
                """,
                (machine_id,),
            ).fetchone()
        return dict(row) if row else None

    def start_scan_job(self, job_id: int) -> None:
        now = _utcnow_iso()
        with self._lock:
            self._conn.execute(
                """
                UPDATE scan_jobs
                SET status = 'scanning',
                    started_at = COALESCE(started_at, ?),
                    updated_at = ?,
                    last_error = ''
                WHERE id = ?
                """,
                (now, now, job_id),
            )
            self._conn.commit()

    def update_scan_cursor(self, job_id: int, cursor_path: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE scan_jobs SET cursor_path = ?, updated_at = ? WHERE id = ?",
                (cursor_path, _utcnow_iso(), job_id),
            )
            self._conn.commit()

    def complete_scan_job(self, job_id: int) -> None:
        now = _utcnow_iso()
        with self._lock:
            self._conn.execute(
                """
                UPDATE scan_jobs
                SET status = 'completed', cursor_path = '', completed_at = ?, updated_at = ?, last_error = ''
                WHERE id = ?
                """,
                (now, now, job_id),
            )
            self._conn.commit()

    def fail_scan_job(self, job_id: int, error: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                UPDATE scan_jobs
                SET status = 'pending', updated_at = ?, last_error = ?
                WHERE id = ?
                """,
                (_utcnow_iso(), (error or "")[:500], job_id),
            )
            self._conn.commit()

    def get_inventory_row(self, machine_id: str, normalized_path: str) -> Optional[dict]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM file_inventory WHERE machine_id = ? AND normalized_path = ?",
                (machine_id, normalized_path),
            ).fetchone()
        return dict(row) if row else None

    def touch_existing_row(self, row_id: int) -> None:
        now = _utcnow_iso()
        with self._lock:
            self._conn.execute(
                """
                UPDATE file_inventory
                SET last_seen_at = ?, last_scanned_at = ?, scan_status = 'unchanged'
                WHERE id = ?
                """,
                (now, now, row_id),
            )
            self._conn.commit()

    def upsert_inventory_record(self, record: dict[str, Any]) -> int:
        now = _utcnow_iso()
        findings_summary = json.dumps(record.get("findings_summary", {}))
        label_summary = json.dumps(record.get("label_summary", {}))
        with self._lock:
            existing = self._conn.execute(
                "SELECT id, first_seen_at FROM file_inventory WHERE machine_id = ? AND normalized_path = ?",
                (record["machine_id"], record["normalized_path"]),
            ).fetchone()
            first_seen_at = existing["first_seen_at"] if existing and existing["first_seen_at"] else now
            self._conn.execute(
                """
                INSERT INTO file_inventory(
                    machine_id, root_id, scan_job_id, absolute_path, normalized_path,
                    file_name, extension, size_bytes, mtime_ns, ctime_ns, owner_name,
                    sha256, content_fingerprint, scan_version, scan_status, inspect_status,
                    inspect_reason, parser_type, findings_summary, label_summary,
                    extracted_text_hash, parser_cache_key, first_seen_at, last_seen_at,
                    last_scanned_at, upload_status, uploaded_at, dirty, last_upload_error
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', NULL, 1, '')
                ON CONFLICT(machine_id, normalized_path) DO UPDATE SET
                    root_id = excluded.root_id,
                    scan_job_id = excluded.scan_job_id,
                    absolute_path = excluded.absolute_path,
                    file_name = excluded.file_name,
                    extension = excluded.extension,
                    size_bytes = excluded.size_bytes,
                    mtime_ns = excluded.mtime_ns,
                    ctime_ns = excluded.ctime_ns,
                    owner_name = excluded.owner_name,
                    sha256 = excluded.sha256,
                    content_fingerprint = excluded.content_fingerprint,
                    scan_version = excluded.scan_version,
                    scan_status = excluded.scan_status,
                    inspect_status = excluded.inspect_status,
                    inspect_reason = excluded.inspect_reason,
                    parser_type = excluded.parser_type,
                    findings_summary = excluded.findings_summary,
                    label_summary = excluded.label_summary,
                    extracted_text_hash = excluded.extracted_text_hash,
                    parser_cache_key = excluded.parser_cache_key,
                    last_seen_at = excluded.last_seen_at,
                    last_scanned_at = excluded.last_scanned_at,
                    upload_status = 'pending',
                    uploaded_at = NULL,
                    dirty = 1,
                    last_upload_error = ''
                """,
                (
                    record["machine_id"], record["root_id"], record.get("scan_job_id"), record["absolute_path"],
                    record["normalized_path"], record["file_name"], record["extension"],
                    int(record.get("size_bytes", 0)), int(record.get("mtime_ns", 0)),
                    int(record.get("ctime_ns", 0)), record.get("owner_name", ""),
                    record.get("sha256", ""), record.get("content_fingerprint", ""),
                    record.get("scan_version", SCAN_VERSION), record.get("scan_status", "scanned"),
                    record.get("inspect_status", "uninspectable"), record.get("inspect_reason", ""),
                    record.get("parser_type", ""), findings_summary, label_summary,
                    record.get("extracted_text_hash", ""), record.get("parser_cache_key", ""),
                    first_seen_at, now, now,
                ),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT id FROM file_inventory WHERE machine_id = ? AND normalized_path = ?",
                (record["machine_id"], record["normalized_path"]),
            ).fetchone()
            return int(row["id"])

    def fetch_upload_batch(self, machine_id: str, limit: int) -> tuple[Optional[dict], list[dict]]:
        with self._lock:
            first = self._conn.execute(
                """
                SELECT root_id, scan_job_id
                FROM file_inventory
                WHERE machine_id = ? AND dirty = 1
                ORDER BY id ASC
                LIMIT 1
                """,
                (machine_id,),
            ).fetchone()
            if not first:
                return None, []
            rows = self._conn.execute(
                """
                SELECT *
                FROM file_inventory
                WHERE machine_id = ? AND dirty = 1 AND root_id = ? AND COALESCE(scan_job_id, 0) = COALESCE(?, 0)
                ORDER BY id ASC
                LIMIT ?
                """,
                (machine_id, first["root_id"], first["scan_job_id"], limit),
            ).fetchall()
        group = {"root_id": first["root_id"], "scan_job_id": first["scan_job_id"]}
        return group, [dict(row) for row in rows]

    def mark_uploaded(self, inventory_ids: Iterable[int]) -> None:
        ids = [int(i) for i in inventory_ids]
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        now = _utcnow_iso()
        with self._lock:
            self._conn.execute(
                f"""
                UPDATE file_inventory
                SET dirty = 0, upload_status = 'uploaded', uploaded_at = ?, last_upload_error = ''
                WHERE id IN ({placeholders})
                """,
                [now] + ids,
            )
            self._conn.commit()

    def mark_upload_retry(self, inventory_ids: Iterable[int], error: str) -> None:
        ids = [int(i) for i in inventory_ids]
        if not ids:
            return
        placeholders = ",".join("?" * len(ids))
        with self._lock:
            self._conn.execute(
                f"""
                UPDATE file_inventory
                SET upload_status = 'pending', last_upload_error = ?
                WHERE id IN ({placeholders})
                """,
                [(error or "")[:500]] + ids,
            )
            self._conn.commit()

    def metrics(self, machine_id: str) -> dict[str, Any]:
        with self._lock:
            total = self._conn.execute(
                "SELECT COUNT(*) AS c FROM file_inventory WHERE machine_id = ?",
                (machine_id,),
            ).fetchone()["c"]
            pending = self._conn.execute(
                "SELECT COUNT(*) AS c FROM file_inventory WHERE machine_id = ? AND dirty = 1",
                (machine_id,),
            ).fetchone()["c"]
            parser_failures = self._conn.execute(
                """
                SELECT COUNT(*) AS c FROM file_inventory
                WHERE machine_id = ? AND inspect_status IN ('parser_unavailable', 'read_error', 'ocr_unavailable')
                """,
                (machine_id,),
            ).fetchone()["c"]
            row = self._conn.execute(
                """
                SELECT MIN(last_scanned_at) AS oldest_unsynced_at
                FROM file_inventory
                WHERE machine_id = ? AND dirty = 1
                """,
                (machine_id,),
            ).fetchone()
        return {
            "total_inventory_count": int(total or 0),
            "pending_upload_count": int(pending or 0),
            "parser_failure_count": int(parser_failures or 0),
            "oldest_unsynced_at": row["oldest_unsynced_at"] if row else None,
        }


class BaselineParser:
    def __init__(self, config: BaselineInventoryConfig):
        self._config = config

    def inspect(self, file_path: str, extension: str, file_size: int) -> dict[str, Any]:
        if file_size > self._config.max_parser_file_size:
            return {
                "inspect_status": "uninspectable",
                "inspect_reason": "parser_size_limit_exceeded",
                "parser_type": "",
                "extracted_text": "",
            }
        ext = extension.lower()
        try:
            if ext in TEXT_EXTENSIONS or os.path.basename(file_path).lower() in {"dockerfile"}:
                text = self._read_text_file(file_path)
                return self._result("inspected", "", "text", text)
            if ext in OFFICE_EXTENSIONS:
                return self._inspect_office_zip(file_path, ext)
            if ext in ZIP_EXTENSIONS:
                return self._inspect_zip(file_path)
            if ext in EMAIL_EXTENSIONS:
                return self._inspect_eml(file_path)
            if ext == ".pdf":
                return self._inspect_pdf(file_path, file_size)
            if ext in IMAGE_EXTENSIONS:
                return self._inspect_image(file_path, file_size)
            return self._result("uninspectable", "unsupported_extension", "", "")
        except Exception as exc:
            return self._result("read_error", str(exc)[:200], "", "")

    @staticmethod
    def _result(status: str, reason: str, parser_type: str, text: str) -> dict[str, Any]:
        return {
            "inspect_status": status,
            "inspect_reason": reason,
            "parser_type": parser_type,
            "extracted_text": text[:MAX_TEXT_EXTRACT_CHARS] if text else "",
        }

    def _read_text_file(self, file_path: str) -> str:
        with open(file_path, "r", encoding="utf-8", errors="ignore") as handle:
            return handle.read(MAX_TEXT_EXTRACT_CHARS)

    def _inspect_bytes(self, file_name: str, data: bytes, depth: int = 0) -> str:
        if depth > MAX_NESTED_PARSE_DEPTH or not data:
            return ""
        ext = Path(file_name).suffix.lower()
        if ext in TEXT_EXTENSIONS or Path(file_name).name.lower() in {"dockerfile"}:
            return _decode_bytes(data)
        if ext in OFFICE_EXTENSIONS:
            return self._extract_office_zip_bytes(data, ext, depth + 1)
        if ext in ZIP_EXTENSIONS:
            return self._extract_zip_bytes(data, depth + 1)
        if ext in EMAIL_EXTENSIONS:
            return self._extract_eml_bytes(data, depth + 1)
        if ext == ".pdf":
            return self._extract_pdf_text_bytes(data)
        return ""

    def _inspect_office_zip(self, file_path: str, extension: str) -> dict[str, Any]:
        try:
            with open(file_path, "rb") as handle:
                raw = handle.read(min(self._config.max_parser_file_size, 8 * 1024 * 1024))
        except Exception as exc:
            return self._result("read_error", str(exc)[:200], extension.lstrip("."), "")
        text = self._extract_office_zip_bytes(raw, extension, 0).strip()
        if not text:
            return self._result("uninspectable", "no_extractable_text", extension.lstrip("."), "")
        return self._result("inspected", "", extension.lstrip("."), text)

    def _inspect_zip(self, file_path: str) -> dict[str, Any]:
        try:
            with open(file_path, "rb") as handle:
                raw = handle.read(min(self._config.max_parser_file_size, 8 * 1024 * 1024))
        except Exception as exc:
            return self._result("read_error", str(exc)[:200], "zip", "")
        combined = self._extract_zip_bytes(raw, 0)
        if not combined.strip():
            return self._result("uninspectable", "zip_without_extractable_members", "zip", "")
        return self._result("inspected", "", "zip", combined)

    def _extract_office_zip_bytes(self, data: bytes, extension: str, depth: int) -> str:
        text_parts: list[str] = []
        wanted_prefixes = {
            ".docx": ("word/",),
            ".xlsx": ("xl/",),
            ".pptx": ("ppt/",),
        }.get(extension, ())
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for info in archive.infolist():
                    if info.file_size <= 0 or info.file_size > MAX_ZIP_MEMBER_BYTES:
                        continue
                    name = info.filename.lower()
                    if wanted_prefixes and not any(name.startswith(prefix) for prefix in wanted_prefixes):
                        continue
                    if not name.endswith(".xml"):
                        continue
                    try:
                        member_data = archive.read(info)[:MAX_ZIP_MEMBER_BYTES]
                        text_parts.append(_xml_text(member_data))
                    except Exception:
                        continue
        except Exception:
            return ""
        return "\n".join([part for part in text_parts if part]).strip()

    def _extract_zip_bytes(self, data: bytes, depth: int) -> str:
        text_parts: list[str] = []
        names: list[str] = []
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for info in archive.infolist()[:128]:
                    names.append(info.filename)
                    if info.is_dir() or info.file_size <= 0 or info.file_size > MAX_ZIP_MEMBER_BYTES:
                        continue
                    try:
                        member_data = archive.read(info)[:MAX_ZIP_MEMBER_BYTES]
                    except Exception:
                        continue
                    extracted = self._inspect_bytes(info.filename, member_data, depth)
                    if extracted:
                        text_parts.append(extracted)
        except Exception:
            return ""
        combined = "\n".join(names[:64] + text_parts)
        return combined[:MAX_TEXT_EXTRACT_CHARS]

    def _inspect_eml(self, file_path: str) -> dict[str, Any]:
        try:
            with open(file_path, "rb") as handle:
                raw = handle.read(min(self._config.max_parser_file_size, 8 * 1024 * 1024))
        except Exception as exc:
            return self._result("read_error", str(exc)[:200], "eml", "")
        text = self._extract_eml_bytes(raw, 0)
        if not text.strip():
            return self._result("uninspectable", "eml_without_extractable_text", "eml", "")
        return self._result("inspected", "", "eml", text)

    def _extract_eml_bytes(self, data: bytes, depth: int) -> str:
        from email import policy
        from email.parser import BytesParser

        try:
            message = BytesParser(policy=policy.default).parsebytes(data)
        except Exception:
            return ""

        parts: list[str] = []
        subject = str(message.get("subject", "") or "").strip()
        if subject:
            parts.append(subject)

        for part in message.walk():
            if part.is_multipart():
                continue
            filename = part.get_filename() or ""
            payload = part.get_payload(decode=True) or b""
            content_type = part.get_content_type()
            if filename:
                parts.append(filename)
                extracted = self._inspect_bytes(filename, payload, depth)
                if extracted:
                    parts.append(extracted)
                continue
            if content_type.startswith("text/"):
                text = _decode_bytes(payload)
                if text:
                    parts.append(text)
        return "\n".join([part for part in parts if part]).strip()[:MAX_TEXT_EXTRACT_CHARS]

    def _inspect_pdf(self, file_path: str, file_size: int) -> dict[str, Any]:
        text = self._extract_pdf_text(file_path)
        if text.strip():
            return self._result("inspected", "", "pdf", text)
        if file_size <= self._config.max_ocr_file_size:
            ocr = self._ocr_pdf(file_path)
            if ocr.get("text"):
                return self._result("inspected", "", "pdf_ocr", ocr["text"])
            return self._result(ocr["status"], ocr["reason"], "pdf_ocr", "")
        return self._result("uninspectable", "pdf_no_extractable_text", "pdf", "")

    def _inspect_image(self, file_path: str, file_size: int) -> dict[str, Any]:
        if file_size > self._config.max_ocr_file_size:
            return self._result("uninspectable", "ocr_size_limit_exceeded", "image", "")
        ocr = self._ocr_image(file_path)
        if ocr.get("text"):
            return self._result("inspected", "", "image_ocr", ocr["text"])
        return self._result(ocr["status"], ocr["reason"], "image_ocr", "")

    def _extract_pdf_text(self, file_path: str) -> str:
        try:
            with open(file_path, "rb") as handle:
                raw = handle.read(min(self._config.max_parser_file_size, 4 * 1024 * 1024))
        except Exception:
            return ""
        return self._extract_pdf_text_bytes(raw)

    def _extract_pdf_text_bytes(self, raw: bytes) -> str:
        text_parts: list[str] = []
        for chunk in re.findall(rb"\(([^)]{3,512})\)", raw):
            text = _decode_bytes(chunk)
            if text:
                text_parts.append(text)
        if not text_parts:
            for chunk in re.findall(rb"[A-Za-z0-9][A-Za-z0-9\s,./:@_-]{8,512}", raw):
                text = _decode_bytes(chunk)
                if text:
                    text_parts.append(text)
        return "\n".join(text_parts)[:MAX_TEXT_EXTRACT_CHARS]

    def _ocr_image(self, file_path: str) -> dict[str, str]:
        try:
            import pytesseract  # type: ignore
            from PIL import Image  # type: ignore

            image = Image.open(file_path)
            text = pytesseract.image_to_string(image)
            if text.strip():
                return {"status": "inspected", "reason": "", "text": text[:MAX_TEXT_EXTRACT_CHARS]}
        except Exception:
            pass

        tesseract = shutil.which("tesseract")
        if not tesseract:
            return {"status": "ocr_unavailable", "reason": "tesseract_not_installed", "text": ""}
        try:
            proc = subprocess.run(
                [tesseract, file_path, "stdout"],
                capture_output=True,
                timeout=30,
                check=False,
                text=True,
                encoding="utf-8",
                errors="ignore",
            )
            text = (proc.stdout or "").strip()
            if text:
                return {"status": "inspected", "reason": "", "text": text[:MAX_TEXT_EXTRACT_CHARS]}
            return {"status": "ocr_unavailable", "reason": "no_ocr_text", "text": ""}
        except Exception as exc:
            return {"status": "ocr_unavailable", "reason": str(exc)[:120], "text": ""}

    def _ocr_pdf(self, file_path: str) -> dict[str, str]:
        pdftoppm = shutil.which("pdftoppm")
        tesseract = shutil.which("tesseract")
        if not pdftoppm or not tesseract:
            return {"status": "ocr_unavailable", "reason": "pdf_ocr_tools_missing", "text": ""}
        tmp_prefix = Path(file_path).with_suffix("").name
        tmp_dir = Path(os.environ.get("TEMP", Path.home() / ".croppro_agent"))
        tmp_dir.mkdir(parents=True, exist_ok=True)
        out_prefix = tmp_dir / f"{tmp_prefix}-{int(time.time() * 1000)}"
        try:
            convert = subprocess.run(
                [pdftoppm, "-f", "1", "-l", "2", "-png", file_path, str(out_prefix)],
                capture_output=True,
                timeout=60,
                check=False,
            )
            if convert.returncode != 0:
                return {"status": "ocr_unavailable", "reason": "pdftoppm_failed", "text": ""}
            texts = []
            for image in sorted(tmp_dir.glob(f"{out_prefix.name}-*.png"))[:2]:
                result = subprocess.run(
                    [tesseract, str(image), "stdout"],
                    capture_output=True,
                    timeout=30,
                    check=False,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                )
                if result.stdout:
                    texts.append(result.stdout)
            text = "\n".join(texts).strip()
            if text:
                return {"status": "inspected", "reason": "", "text": text[:MAX_TEXT_EXTRACT_CHARS]}
            return {"status": "ocr_unavailable", "reason": "pdf_ocr_empty", "text": ""}
        except Exception as exc:
            return {"status": "ocr_unavailable", "reason": str(exc)[:120], "text": ""}
        finally:
            for image in tmp_dir.glob(f"{out_prefix.name}-*.png"):
                try:
                    image.unlink()
                except OSError:
                    pass


class BaselineInventoryScanner:
    def __init__(self, machine_id: str, config: BaselineInventoryConfig, post_json_fn):
        self.machine_id = machine_id
        self._config = config
        self._post_json = post_json_fn
        self._config_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._store = InventoryStore()
        self._fingerprints = FingerprintStore()
        self._parser = BaselineParser(config)
        self._threads: list[threading.Thread] = []
        self._last_discovery = 0.0

    def start(self):
        self._threads = [
            threading.Thread(target=self._scan_loop, daemon=True, name="baseline-scan"),
            threading.Thread(target=self._upload_loop, daemon=True, name="baseline-upload"),
        ]
        for thread in self._threads:
            thread.start()

    def stop(self):
        self._stop_event.set()
        for thread in self._threads:
            thread.join(timeout=2)
        self._store.close()
        self._fingerprints.close()

    def update_config(self, config: BaselineInventoryConfig):
        with self._config_lock:
            self._config = config
            self._parser = BaselineParser(config)

    def _cfg(self) -> BaselineInventoryConfig:
        with self._config_lock:
            return self._config

    def _scan_loop(self):
        while not self._stop_event.is_set():
            cfg = self._cfg()
            if not cfg.enabled:
                self._stop_event.wait(5)
                continue

            now = time.time()
            if now - self._last_discovery >= cfg.mount_discovery_interval_seconds:
                self._discover_roots(cfg)
                self._last_discovery = now

            job = self._store.next_scan_job(self.machine_id)
            if not job:
                self._stop_event.wait(2)
                continue
            try:
                self._scan_job(job, cfg)
            except Exception as exc:
                logger.error("Baseline scan job failed root=%s err=%s", job.get("root_path", ""), exc)
                self._store.fail_scan_job(int(job["id"]), str(exc))
                self._stop_event.wait(2)

    def _discover_roots(self, cfg: BaselineInventoryConfig):
        cutoff = datetime.now(timezone.utc).timestamp() - cfg.rescan_unchanged_after_seconds
        self._store.reset_due_jobs(self.machine_id, datetime.fromtimestamp(cutoff, tz=timezone.utc).isoformat())
        for root_path in enumerate_mounted_roots():
            if self._should_skip_root(root_path):
                continue
            self._store.ensure_scan_job(self.machine_id, _root_id(root_path), root_path, SCAN_VERSION)

    def _should_skip_root(self, root_path: str) -> bool:
        norm = _normalize_path(root_path)
        if not norm or _is_cloud_virtual_mount(root_path):
            return True
        if platform.system() == "Windows":
            if norm in WINDOWS_SYSTEM_ROOTS:
                return True
            if norm.startswith(_normalize_path(str(Path.home() / ".croppro_agent"))):
                return True
            return False
        if any(norm.startswith(prefix) for prefix in PSEUDO_MOUNT_PREFIXES):
            return True
        return False

    def _scan_job(self, job: dict[str, Any], cfg: BaselineInventoryConfig):
        job_id = int(job["id"])
        root_path = job["root_path"]
        root_id = job["root_id"]
        cursor_path = _normalize_path(job.get("cursor_path", ""))
        self._store.start_scan_job(job_id)
        batch_size = max(cfg.worker_count * FILE_BATCH_MULTIPLIER, cfg.worker_count)
        executor = concurrent.futures.ThreadPoolExecutor(max_workers=cfg.worker_count)
        try:
            pending: list[str] = []
            for file_path in self._iter_files(root_path, cursor_path):
                if self._stop_event.is_set():
                    break
                pending.append(file_path)
                if len(pending) >= batch_size:
                    self._process_path_batch(executor, pending, root_id, job_id, cfg)
                    pending = []
                    if cfg.io_throttle_seconds:
                        self._stop_event.wait(cfg.io_throttle_seconds)
            if pending and not self._stop_event.is_set():
                self._process_path_batch(executor, pending, root_id, job_id, cfg)
            if not self._stop_event.is_set():
                self._store.complete_scan_job(job_id)
        finally:
            executor.shutdown(wait=True)

    def _iter_files(self, root_path: str, cursor_path: str) -> Iterable[str]:
        for current_root, dirnames, filenames in os.walk(root_path, topdown=True, followlinks=False):
            dirnames[:] = [
                d for d in sorted(dirnames)
                if d.lower() not in SKIP_DIR_NAMES and not self._skip_dir(os.path.join(current_root, d))
            ]
            for filename in sorted(filenames):
                file_path = os.path.join(current_root, filename)
                normalized = _normalize_path(file_path)
                if cursor_path and normalized <= cursor_path:
                    continue
                if self._skip_file(file_path):
                    continue
                yield file_path

    def _skip_dir(self, path: str) -> bool:
        norm = _normalize_path(path)
        if platform.system() == "Windows":
            if norm.startswith(_normalize_path(str(Path.home() / ".croppro_agent"))):
                return True
            if any(norm.startswith(root) for root in WINDOWS_SYSTEM_ROOTS):
                return True
        else:
            if any(norm.startswith(prefix) for prefix in PSEUDO_MOUNT_PREFIXES):
                return True
        return False

    def _skip_file(self, path: str) -> bool:
        norm = _normalize_path(path)
        if norm.startswith(_normalize_path(str(Path.home() / ".croppro_agent"))):
            return True
        return False

    def _process_path_batch(
        self,
        executor: concurrent.futures.ThreadPoolExecutor,
        paths: list[str],
        root_id: str,
        scan_job_id: int,
        cfg: BaselineInventoryConfig,
    ):
        results = list(executor.map(lambda p: self._scan_single_file(p, root_id, scan_job_id, cfg), paths))
        for path, result in zip(paths, results):
            if result:
                self._store.upsert_inventory_record(result)
            self._store.update_scan_cursor(scan_job_id, _normalize_path(path))

    def _scan_single_file(
        self,
        file_path: str,
        root_id: str,
        scan_job_id: int,
        cfg: BaselineInventoryConfig,
    ) -> Optional[dict[str, Any]]:
        try:
            stat_result = os.stat(file_path)
        except (OSError, PermissionError):
            return None
        if not os.path.isfile(file_path):
            return None
        normalized_path = _normalize_path(file_path)
        existing = self._store.get_inventory_row(self.machine_id, normalized_path)
        size_bytes = int(getattr(stat_result, "st_size", 0) or 0)
        mtime_ns = int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1e9)))
        ctime_ns = int(getattr(stat_result, "st_ctime_ns", int(stat_result.st_ctime * 1e9)))
        if existing and self._can_skip_existing(existing, size_bytes, mtime_ns, cfg):
            self._store.touch_existing_row(int(existing["id"]))
            return None

        extension = Path(file_path).suffix.lower()
        owner_name = self._owner_name(stat_result)
        file_hash = _hash_file_unbounded(file_path, cfg.max_hash_file_size or None)
        if not file_hash:
            return {
                "machine_id": self.machine_id,
                "root_id": root_id,
                "scan_job_id": scan_job_id,
                "absolute_path": file_path,
                "normalized_path": normalized_path,
                "file_name": Path(file_path).name,
                "extension": extension,
                "size_bytes": size_bytes,
                "mtime_ns": mtime_ns,
                "ctime_ns": ctime_ns,
                "owner_name": owner_name,
                "sha256": "",
                "content_fingerprint": "",
                "scan_version": SCAN_VERSION,
                "scan_status": "scan_error",
                "inspect_status": "uninspectable",
                "inspect_reason": "hash_unavailable",
                "parser_type": "",
                "findings_summary": {},
                "label_summary": {
                    "risk": "unknown",
                    "risk_score": 0,
                    "findings_count": 0,
                    "enterprise_label": "Internal",
                    "sensitivity_score": 1,
                    "label_source": "hash_only",
                    "label_reason": "File hash could not be computed",
                    "finding_types": [],
                },
                "extracted_text_hash": "",
                "parser_cache_key": f"{size_bytes}:{mtime_ns}",
            }

        inspection = self._parser.inspect(file_path, extension, size_bytes)
        extracted_text = inspection.get("extracted_text", "") or ""
        scan_summary = self._run_dlp_scan(extracted_text)
        content_fingerprint = _sha256_text(extracted_text) if extracted_text else file_hash
        findings = scan_summary.get("findings", [])
        risk = scan_summary.get("risk", "none")
        if findings and file_hash:
            try:
                self._fingerprints.record(
                    file_hash=file_hash,
                    file_path=file_path,
                    file_name=Path(file_path).name,
                    risk_level=risk if risk in {"low", "medium", "high"} else "low",
                    risk_score=int(scan_summary.get("total_weight", 0) or 0),
                    findings=findings,
                )
            except Exception:
                pass
        findings_summary = {
            "risk": risk,
            "total_weight": int(scan_summary.get("total_weight", 0) or 0),
            "findings": findings,
            "finding_types": [item.get("type", "") for item in findings],
            "finding_count": len(findings),
            "extracted_chars": len(extracted_text),
        }
        label_summary = derive_enterprise_label(
            findings,
            risk=risk,
            risk_score=int(scan_summary.get("total_weight", 0) or 0),
            inspect_status=inspection.get("inspect_status", ""),
        )
        return {
            "machine_id": self.machine_id,
            "root_id": root_id,
            "scan_job_id": scan_job_id,
            "absolute_path": file_path,
            "normalized_path": normalized_path,
            "file_name": Path(file_path).name,
            "extension": extension,
            "size_bytes": size_bytes,
            "mtime_ns": mtime_ns,
            "ctime_ns": ctime_ns,
            "owner_name": owner_name,
            "sha256": file_hash,
            "content_fingerprint": content_fingerprint,
            "scan_version": SCAN_VERSION,
            "scan_status": "scanned",
            "inspect_status": inspection.get("inspect_status", "uninspectable"),
            "inspect_reason": inspection.get("inspect_reason", ""),
            "parser_type": inspection.get("parser_type", ""),
            "findings_summary": findings_summary,
            "label_summary": label_summary,
            "extracted_text_hash": _sha256_text(extracted_text) if extracted_text else "",
            "parser_cache_key": f"{size_bytes}:{mtime_ns}:{inspection.get('parser_type', '')}",
        }

    def _can_skip_existing(self, existing: dict[str, Any], size_bytes: int, mtime_ns: int, cfg: BaselineInventoryConfig) -> bool:
        if int(existing.get("size_bytes", -1) or -1) != size_bytes:
            return False
        if int(existing.get("mtime_ns", -1) or -1) != mtime_ns:
            return False
        last = existing.get("last_scanned_at", "")
        if not last:
            return False
        try:
            last_dt = datetime.fromisoformat(str(last))
        except Exception:
            return False
        return (datetime.now(timezone.utc) - last_dt).total_seconds() < cfg.rescan_unchanged_after_seconds

    def _owner_name(self, stat_result: os.stat_result) -> str:
        try:
            if platform.system() != "Windows":
                import pwd

                return pwd.getpwuid(stat_result.st_uid).pw_name
        except Exception:
            pass
        return ""

    def _run_dlp_scan(self, extracted_text: str) -> dict[str, Any]:
        if not extracted_text.strip():
            return {"risk": "none", "findings": [], "total_weight": 0}
        try:
            from file_tracker import _get_dlp_engine

            engine = _get_dlp_engine()
            if engine and hasattr(engine, "scan"):
                return engine.scan(extracted_text[:MAX_TEXT_EXTRACT_CHARS])
        except Exception:
            pass
        return {"risk": "none", "findings": [], "total_weight": 0}

    def _upload_loop(self):
        while not self._stop_event.is_set():
            cfg = self._cfg()
            if not cfg.enabled:
                self._stop_event.wait(5)
                continue
            try:
                self._upload_once(cfg)
            except Exception as exc:
                logger.debug("Baseline upload loop error: %s", exc)
            self._stop_event.wait(cfg.upload_interval_seconds)

    def _upload_once(self, cfg: BaselineInventoryConfig):
        group, rows = self._store.fetch_upload_batch(self.machine_id, cfg.upload_batch_size)
        if not rows or not group:
            return
        payload = {
            "machine_id": self.machine_id,
            "scan_job_id": group.get("scan_job_id"),
            "root_id": group.get("root_id"),
            "records": [self._to_upload_record(row) for row in rows],
            "stats": self._store.metrics(self.machine_id),
        }
        response = self._post_json("/api/dlp/file-inventory/batch", payload)
        if not isinstance(response, dict):
            self._store.mark_upload_retry([row["id"] for row in rows], "upload_failed")
            return
        success_ids = {int(i) for i in response.get("success_ids", [])}
        failed_ids = {int(i) for i in response.get("failed_ids", [])}
        if success_ids:
            self._store.mark_uploaded(success_ids)
        unknown_ids = {int(row["id"]) for row in rows} - success_ids - failed_ids
        if failed_ids or unknown_ids:
            self._store.mark_upload_retry(failed_ids | unknown_ids, "partial_failure")

    @staticmethod
    def _to_upload_record(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "inventory_id": int(row["id"]),
            "absolute_path": row["absolute_path"],
            "normalized_path": row["normalized_path"],
            "file_name": row["file_name"],
            "extension": row["extension"],
            "size_bytes": int(row.get("size_bytes", 0) or 0),
            "mtime_ns": int(row.get("mtime_ns", 0) or 0),
            "ctime_ns": int(row.get("ctime_ns", 0) or 0),
            "owner_name": row.get("owner_name", ""),
            "sha256": row.get("sha256", ""),
            "content_fingerprint": row.get("content_fingerprint", ""),
            "scan_version": row.get("scan_version", SCAN_VERSION),
            "scan_status": row.get("scan_status", "scanned"),
            "inspect_status": row.get("inspect_status", "uninspectable"),
            "inspect_reason": row.get("inspect_reason", ""),
            "parser_type": row.get("parser_type", ""),
            "findings_summary": _json_loads(row.get("findings_summary"), {}),
            "label_summary": _json_loads(row.get("label_summary"), {}),
            "last_scanned_at": row.get("last_scanned_at", ""),
            "first_seen_at": row.get("first_seen_at", ""),
            "last_seen_at": row.get("last_seen_at", ""),
        }


def _json_loads(value: Any, default: Any):
    if value is None:
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except Exception:
        return default


def _decode_bytes(data: bytes) -> str:
    return data.decode("utf-8", errors="ignore")[:MAX_TEXT_EXTRACT_CHARS]


def _xml_text(data: bytes) -> str:
    try:
        root = ET.fromstring(data)
        parts = []
        for elem in root.iter():
            if elem.text and elem.text.strip():
                parts.append(elem.text.strip())
        return "\n".join(parts)[:MAX_TEXT_EXTRACT_CHARS]
    except Exception:
        return _decode_bytes(data)
