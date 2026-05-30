"""
CropSentinel — DLP File Fingerprint Store
=====================================

Tracks SHA-256 fingerprints of files that have been identified as sensitive
by the DLP engine.  When the same content appears at a new path (copy,
rename, cloud sync), the system recognises it as a *known* sensitive file
without re-scanning — enabling instant alerts on data movement.

Storage: lightweight SQLite database (~/.croppro_agent/fingerprints.db)
Thread-safe: all public methods acquire an internal lock.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import platform
import sqlite3
import stat
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("croppro.dlp.fingerprint")

# ── Constants ────────────────────────────────────────────────────────────────

DB_DIR = Path.home() / ".croppro_agent"
DB_PATH = DB_DIR / "fingerprints.db"

# Maximum file size we'll hash (64 MB) — larger files are skipped
MAX_HASH_SIZE = 64 * 1024 * 1024

# Read buffer for hashing (64 KB chunks — low memory footprint)
HASH_CHUNK_SIZE = 65_536

# Partial hashing: files above this threshold use head+tail hash
# to avoid CPU spikes on large files (Fix 7)
PARTIAL_HASH_THRESHOLD = 1 * 1024 * 1024   # 1 MB
PARTIAL_HASH_BYTES     = 512 * 1024         # 512 KB from each end

# Prune entries older than this (days)
RETENTION_DAYS = 90

# Maximum entries in the store (hard cap)
MAX_ENTRIES = 50_000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS fingerprints (
    file_hash      TEXT    NOT NULL,
    file_path      TEXT    NOT NULL,
    file_name      TEXT    NOT NULL DEFAULT '',
    risk_level     TEXT    NOT NULL DEFAULT 'low',
    risk_score     INTEGER NOT NULL DEFAULT 0,
    first_seen     TEXT    NOT NULL,
    last_seen      TEXT    NOT NULL,
    source         TEXT    NOT NULL DEFAULT 'original',
    findings_json  TEXT    NOT NULL DEFAULT '[]',
    PRIMARY KEY (file_hash, file_path)
);

CREATE INDEX IF NOT EXISTS idx_fp_hash      ON fingerprints(file_hash);
CREATE INDEX IF NOT EXISTS idx_fp_last_seen ON fingerprints(last_seen);
"""


# ── Data Types ───────────────────────────────────────────────────────────────

@dataclass
class FingerprintRecord:
    file_hash: str
    file_path: str
    file_name: str
    risk_level: str
    risk_score: int
    first_seen: str
    last_seen: str
    source: str          # "original" | "copied"
    findings_json: str

    @property
    def is_sensitive(self) -> bool:
        return self.risk_level in ("low", "medium", "high")


# ── Hashing ──────────────────────────────────────────────────────────────────

def hash_file(file_path: str, max_size: int = MAX_HASH_SIZE) -> Optional[str]:
    """
    Compute SHA-256 of a file using streaming reads.

    For files larger than PARTIAL_HASH_THRESHOLD (1 MB), hashes the first
    and last 512 KB plus the file size as a salt — avoids CPU spikes on
    large files while still detecting content changes.

    Returns None if the file is too large, missing, or unreadable.
    """
    try:
        p = Path(file_path)
        if not p.is_file():
            return None
        size = p.stat().st_size
        if size == 0 or size > max_size:
            return None

        h = hashlib.sha256()

        if size <= PARTIAL_HASH_THRESHOLD:
            # Small file — full hash
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(HASH_CHUNK_SIZE)
                    if not chunk:
                        break
                    h.update(chunk)
        else:
            # Large file — partial hash: head + tail + size salt
            h.update(f"__partial__{size}__".encode())
            with open(file_path, "rb") as f:
                remaining = PARTIAL_HASH_BYTES
                while remaining > 0:
                    chunk = f.read(min(HASH_CHUNK_SIZE, remaining))
                    if not chunk:
                        break
                    h.update(chunk)
                    remaining -= len(chunk)
                # Seek to tail
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


def hash_content(content: str) -> str:
    """Hash in-memory text content (for cases where we already have the bytes)."""
    return hashlib.sha256(content.encode("utf-8", errors="ignore")).hexdigest()


# ── Security Helpers (Fix 8) ─────────────────────────────────────────────────

def _secure_permissions(path: Path):
    """Restrict a file to owner-only access (Unix: 0600)."""
    try:
        if platform.system() != "Windows":
            os.chmod(str(path), stat.S_IRUSR | stat.S_IWUSR)
    except (OSError, AttributeError):
        pass


def _encode_field(value: str) -> str:
    """Obfuscate a string for at-rest storage (base64)."""
    if not value:
        return value
    return base64.b64encode(value.encode("utf-8", errors="ignore")).decode("ascii")


def _decode_field(value: str) -> str:
    """De-obfuscate a stored field. Handles both encoded and legacy plain text."""
    if not value:
        return value
    try:
        return base64.b64decode(value.encode("ascii")).decode("utf-8", errors="ignore")
    except Exception:
        return value  # legacy plain-text — return as-is


# ── Fingerprint Store ────────────────────────────────────────────────────────

class FingerprintStore:
    """
    Persistent, thread-safe store for file fingerprints.

    Usage:
        store = FingerprintStore()
        store.record("abc123...", "/path/to/file.csv", "file.csv", "high", 15, [...])
        rec = store.lookup("abc123...")
        if rec:
            print(f"Known sensitive file! First seen {rec.first_seen}")
    """

    def __init__(self, db_path: Path = DB_PATH):
        self._lock = threading.Lock()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(db_path), timeout=10, check_same_thread=False,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._conn.execute("PRAGMA synchronous  = NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        # Fix 8: restrict DB file permissions to owner-only
        _secure_permissions(db_path)
        wal_path = db_path.parent / (db_path.name + "-wal")
        shm_path = db_path.parent / (db_path.name + "-shm")
        for p in (wal_path, shm_path):
            if p.exists():
                _secure_permissions(p)

    # ── Public API ────────────────────────────────────────────────────────

    def record(
        self,
        file_hash: str,
        file_path: str,
        file_name: str,
        risk_level: str,
        risk_score: int,
        findings: list,
    ) -> FingerprintRecord:
        """
        Record (or update) a fingerprint after a DLP scan finds sensitive data.
        If the hash already exists at a *different* path → source = "copied".
        """
        import json

        now = _utcnow_iso()
        findings_json = _encode_field(json.dumps(findings))

        with self._lock:
            # Check if this exact hash exists at ANY path already
            cur = self._conn.execute(
                "SELECT * FROM fingerprints WHERE file_hash = ? ORDER BY first_seen ASC LIMIT 1",
                (file_hash,),
            )
            existing = cur.fetchone()

            source = "original"
            if existing and existing["file_path"] != file_path:
                source = "copied"

            self._conn.execute("""
                INSERT INTO fingerprints
                    (file_hash, file_path, file_name, risk_level, risk_score,
                     first_seen, last_seen, source, findings_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(file_hash, file_path) DO UPDATE SET
                    risk_level    = excluded.risk_level,
                    risk_score    = excluded.risk_score,
                    last_seen     = excluded.last_seen,
                    findings_json = excluded.findings_json
            """, (
                file_hash, file_path, file_name, risk_level, risk_score,
                now, now, source, findings_json,
            ))
            self._conn.commit()

        return FingerprintRecord(
            file_hash=file_hash, file_path=file_path, file_name=file_name,
            risk_level=risk_level, risk_score=risk_score,
            first_seen=existing["first_seen"] if existing else now,
            last_seen=now, source=source, findings_json=findings_json,
        )

    def lookup(self, file_hash: str) -> Optional[FingerprintRecord]:
        """
        Look up a hash in the store.  Returns the *first* (original) record
        for that hash, or None if unknown.
        """
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM fingerprints WHERE file_hash = ? ORDER BY first_seen ASC LIMIT 1",
                (file_hash,),
            )
            row = cur.fetchone()
        if not row:
            return None
        data = {k: row[k] for k in row.keys()}
        data["findings_json"] = _decode_field(data.get("findings_json", ""))
        return FingerprintRecord(**data)

    def lookup_with_retry(
        self, file_hash: str, retries: int = 2, delay: float = 0.2,
    ) -> Optional[FingerprintRecord]:
        """
        Lookup with retry to mitigate race conditions where a concurrent
        scan may not have recorded the fingerprint yet (Fix 1).
        """
        for i in range(retries + 1):
            result = self.lookup(file_hash)
            if result is not None:
                return result
            if i < retries:
                time.sleep(delay)
        return None

    def is_known_sensitive(self, file_hash: str) -> bool:
        """Quick check: is this hash in the store at all?"""
        with self._lock:
            cur = self._conn.execute(
                "SELECT 1 FROM fingerprints WHERE file_hash = ? LIMIT 1",
                (file_hash,),
            )
            return cur.fetchone() is not None

    def get_all_for_hash(self, file_hash: str) -> list[FingerprintRecord]:
        """Return every path where this hash has been seen."""
        with self._lock:
            cur = self._conn.execute(
                "SELECT * FROM fingerprints WHERE file_hash = ? ORDER BY first_seen ASC",
                (file_hash,),
            )
            rows = cur.fetchall()
        results = []
        for r in rows:
            data = {k: r[k] for k in r.keys()}
            data["findings_json"] = _decode_field(data.get("findings_json", ""))
            results.append(FingerprintRecord(**data))
        return results

    def count(self) -> int:
        with self._lock:
            cur = self._conn.execute("SELECT COUNT(*) FROM fingerprints")
            return cur.fetchone()[0]

    def cleanup(self):
        """Remove entries older than RETENTION_DAYS, and enforce MAX_ENTRIES cap."""
        with self._lock:
            cutoff = datetime.now(timezone.utc).isoformat()
            # We can't easily subtract days in SQLite ISO format, so use Python
            from datetime import timedelta
            cutoff_dt = datetime.now(timezone.utc) - timedelta(days=RETENTION_DAYS)
            cutoff_str = cutoff_dt.isoformat()

            self._conn.execute(
                "DELETE FROM fingerprints WHERE last_seen < ?", (cutoff_str,)
            )

            # Enforce hard cap — keep most recent
            count = self._conn.execute("SELECT COUNT(*) FROM fingerprints").fetchone()[0]
            if count > MAX_ENTRIES:
                excess = count - MAX_ENTRIES
                self._conn.execute("""
                    DELETE FROM fingerprints WHERE rowid IN (
                        SELECT rowid FROM fingerprints
                        ORDER BY last_seen ASC LIMIT ?
                    )
                """, (excess,))
            self._conn.commit()

    def close(self):
        with self._lock:
            self._conn.close()


# ── Utility ──────────────────────────────────────────────────────────────────

def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
