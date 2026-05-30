"""
CropSentinel — Enterprise Offline Sync Queue v2.0
==============================================

High-performance, crash-safe event queue with encrypted local storage,
ACK-based WebSocket delivery, adaptive batching, backpressure, and
OS-level key protection.

Architecture:

    Agent Modules (10+ threads)
        │ enqueue()              ~0.01 ms  (in-memory append, no I/O)
        ▼
    ┌───────────────────┐
    │  WriteBuffer       │  Lock-free ring → flushed every 250 ms or 200 items
    │  (in-memory)       │  Compression (zlib) for payloads > 1 KB
    └────────┬──────────┘
             │  batch INSERT (single transaction)
             ▼
    ┌───────────────────┐
    │  SQLite WAL DB     │  ~/.croppro_agent/offline.db
    │  AES-128-CBC enc.  │  Eviction when > MAX_QUEUE_SIZE
    └────────┬──────────┘
             │
             ▼
    ┌───────────────────┐
    │  SyncWorker        │  Adaptive interval (1–8 s)
    │  WS (ACK-based)    │  → mark sent only on server ACK
    │  HTTP batch         │  → partial success (success_ids / failed_ids)
    │  Exp. backoff       │  2^n cap 300 s, max 5 retries → failed
    │  Fair scheduling    │  Every 5th batch forces low-priority drain
    └───────────────────┘

Public API:
    q = OfflineQueue(machine_id, http_post_json_fn=...)
    q.enqueue("browser", {...})
    q.enqueue("heartbeat", {...}, priority=PRIORITY_HIGH)
    q.start()
    q.handle_ws_ack({"ack_ids": [...]})   # called from WS on_message
    q.stop()                               # flushes write buffer, then exits
    q.get_health()                         # queue depth, error rate, sync status
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
import platform
import sqlite3
import stat
import struct
import threading
import time
import uuid
import zlib
from collections import deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Deque, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("croppro.queue")

# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ═══════════════════════════════════════════════════════════════════════════════

DB_DIR  = Path.home() / ".croppro_agent"
DB_PATH = DB_DIR / "offline.db"

# ── Write buffer ──────────────────────────────────────────────────────────────
WRITE_BUFFER_MAX       = 200       # flush after N events accumulated
WRITE_BUFFER_INTERVAL  = 0.25      # flush every 250 ms regardless

# ── Sync worker ───────────────────────────────────────────────────────────────
SYNC_INTERVAL_MIN      = 1         # fastest sync cadence (WS connected, light load)
SYNC_INTERVAL_MAX      = 8         # slowest (offline or idle)
BATCH_SIZE_DEFAULT     = 50
BATCH_SIZE_MAX         = 200       # under high load
MAX_RETRIES            = 5
WS_ACK_TIMEOUT         = 5.0       # seconds to wait for server ACK per WS send

# ── Queue limits ──────────────────────────────────────────────────────────────
MAX_QUEUE_SIZE         = 50_000    # hard cap (rows in DB)
EVICTION_BATCH         = 1_000     # how many oldest low-pri rows to drop at once
BACKPRESSURE_THRESHOLD = 40_000    # start dropping PRIORITY_LOW above this
MAX_PAYLOAD_BYTES      = 5_242_880 # 5 MB — larger payloads are rejected

# ── Compression ───────────────────────────────────────────────────────────────
COMPRESS_THRESHOLD     = 1024      # zlib-compress payloads larger than 1 KB

# ── Housekeeping ──────────────────────────────────────────────────────────────
CLEANUP_SENT_HOURS     = 48
CLEANUP_INTERVAL       = 3600      # once per hour

# ── Fair scheduling ───────────────────────────────────────────────────────────
LOW_PRI_EVERY_N        = 5         # every 5th sync cycle, drain low-priority

# ── Deduplication ─────────────────────────────────────────────────────────────
DEDUP_WINDOW_SECONDS   = 3         # suppress identical events within this window

# ── Priority levels ───────────────────────────────────────────────────────────
PRIORITY_HIGH   = 0
PRIORITY_NORMAL = 5
PRIORITY_LOW    = 9


# ═══════════════════════════════════════════════════════════════════════════════
#  SECURE KEY MANAGEMENT
# ═══════════════════════════════════════════════════════════════════════════════

_KEY_FILE = DB_DIR / ".queue_key"


def _get_hardware_fingerprint() -> str:
    """Collect machine-specific identifiers for key derivation."""
    parts = [platform.node(), platform.machine(), platform.processor()]
    try:
        import uuid as _uuid
        parts.append(str(_uuid.getnode()))  # MAC-based
    except Exception:
        pass
    try:
        if platform.system() == "Windows":
            import subprocess
            out = subprocess.check_output(
                "wmic csproduct get uuid", shell=True, timeout=3
            ).decode().strip().split("\n")[-1].strip()
            if out and out != "FFFFFFFF-FFFF-FFFF-FFFF-FFFFFFFFFFFF":
                parts.append(out)
        elif platform.system() == "Linux":
            for path in ("/etc/machine-id", "/var/lib/dbus/machine-id"):
                try:
                    parts.append(Path(path).read_text().strip())
                    break
                except OSError:
                    continue
    except Exception:
        pass
    return "|".join(parts)


def _os_protect_key(raw_key: bytes) -> bytes:
    """
    Use OS-level secure storage to protect the encryption key.
    Windows → DPAPI (CryptProtectData)
    macOS / Linux → fall through to file-based storage
    """
    if platform.system() == "Windows":
        try:
            import ctypes
            import ctypes.wintypes

            class DATA_BLOB(ctypes.Structure):
                _fields_ = [("cbData", ctypes.wintypes.DWORD),
                            ("pbData", ctypes.POINTER(ctypes.c_char))]

            _crypt32 = ctypes.windll.crypt32
            blob_in = DATA_BLOB(len(raw_key), ctypes.create_string_buffer(raw_key, len(raw_key)))
            blob_out = DATA_BLOB()
            if _crypt32.CryptProtectData(
                ctypes.byref(blob_in), "CropPro", None, None, None, 0,
                ctypes.byref(blob_out)
            ):
                protected = ctypes.string_at(blob_out.pbData, blob_out.cbData)
                ctypes.windll.kernel32.LocalFree(blob_out.pbData)
                return protected
        except Exception:
            pass
    return raw_key  # fallback: no OS protection


def _os_unprotect_key(protected: bytes) -> bytes:
    """Reverse of _os_protect_key."""
    if platform.system() == "Windows":
        try:
            import ctypes
            import ctypes.wintypes

            class DATA_BLOB(ctypes.Structure):
                _fields_ = [("cbData", ctypes.wintypes.DWORD),
                            ("pbData", ctypes.POINTER(ctypes.c_char))]

            _crypt32 = ctypes.windll.crypt32
            blob_in = DATA_BLOB(len(protected), ctypes.create_string_buffer(protected, len(protected)))
            blob_out = DATA_BLOB()
            if _crypt32.CryptUnprotectData(
                ctypes.byref(blob_in), None, None, None, None, 0,
                ctypes.byref(blob_out)
            ):
                raw = ctypes.string_at(blob_out.pbData, blob_out.cbData)
                ctypes.windll.kernel32.LocalFree(blob_out.pbData)
                return raw
        except Exception:
            pass
    return protected


def _load_or_create_key(machine_id: str) -> bytes:
    """
    Load the Fernet key from a locally stored, OS-protected file.
    If no key file exists, derive one from hardware fingerprint + random salt,
    protect it, and save.
    """
    DB_DIR.mkdir(parents=True, exist_ok=True)
    if _KEY_FILE.exists():
        try:
            protected = _KEY_FILE.read_bytes()
            raw_key = _os_unprotect_key(protected)
            # Validate it's a valid Fernet key (32 bytes, base64url-encoded)
            if len(raw_key) == 44:
                return raw_key
        except Exception:
            pass  # corrupt — regenerate

    # Derive a new key
    fingerprint = _get_hardware_fingerprint()
    random_salt = os.urandom(16)
    material = f"{machine_id}:{fingerprint}".encode() + random_salt
    raw = hashlib.pbkdf2_hmac("sha256", material, random_salt, 200_000)
    fernet_key = base64.urlsafe_b64encode(raw)  # 44 bytes

    # Protect and save
    protected = _os_protect_key(fernet_key)
    try:
        _KEY_FILE.write_bytes(protected)
        if platform.system() != "Windows":
            os.chmod(str(_KEY_FILE), stat.S_IRUSR | stat.S_IWUSR)
    except OSError as e:
        logger.warning(f"Could not save key file: {e}")

    return fernet_key


# ═══════════════════════════════════════════════════════════════════════════════
#  ENCRYPTION + COMPRESSION
# ═══════════════════════════════════════════════════════════════════════════════

# Payload format:  FLAG_BYTE + encrypted_data
# FLAG_BYTE: 0x00 = plain encrypted, 0x01 = zlib-compressed then encrypted
_FLAG_PLAIN      = b"\x00"
_FLAG_COMPRESSED = b"\x01"


class _Cipher:
    """AES-128-CBC encryption via Fernet with optional zlib compression."""

    def __init__(self, key: bytes):
        self._fernet = None
        try:
            from cryptography.fernet import Fernet
            self._fernet = Fernet(key)
        except ImportError:
            logger.warning(
                "cryptography not installed — payloads will be "
                "base64-encoded only.  pip install cryptography"
            )

    def encrypt(self, plaintext: str) -> str:
        raw = plaintext.encode("utf-8")
        if len(raw) > COMPRESS_THRESHOLD:
            compressed = zlib.compress(raw, level=6)
            if len(compressed) < len(raw) * 0.9:  # only if ≥10% savings
                raw = _FLAG_COMPRESSED + compressed
            else:
                raw = _FLAG_PLAIN + raw
        else:
            raw = _FLAG_PLAIN + raw

        if self._fernet:
            return self._fernet.encrypt(raw).decode("ascii")
        return base64.urlsafe_b64encode(raw).decode("ascii")

    def decrypt(self, token: str) -> str:
        if self._fernet:
            raw = self._fernet.decrypt(token.encode("ascii"))
        else:
            raw = base64.urlsafe_b64decode(token.encode("ascii"))

        flag = raw[:1]
        data = raw[1:]
        if flag == _FLAG_COMPRESSED:
            data = zlib.decompress(data)
        return data.decode("utf-8")


# ═══════════════════════════════════════════════════════════════════════════════
#  SQLITE SCHEMA + INIT
# ═══════════════════════════════════════════════════════════════════════════════

_SCHEMA = """
CREATE TABLE IF NOT EXISTS event_queue (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type  TEXT    NOT NULL,
    payload     TEXT    NOT NULL,
    payload_len INTEGER NOT NULL DEFAULT 0,
    priority    INTEGER NOT NULL DEFAULT 5,
    created_at  TEXT    NOT NULL,
    status      TEXT    NOT NULL DEFAULT 'pending',
    retry_count INTEGER NOT NULL DEFAULT 0,
    next_retry  TEXT    DEFAULT NULL,
    sent_at     TEXT    DEFAULT NULL
);
CREATE INDEX IF NOT EXISTS idx_eq_pending
    ON event_queue(status, priority, id)
    WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_eq_sending
    ON event_queue(status) WHERE status = 'sending';
CREATE INDEX IF NOT EXISTS idx_eq_cleanup
    ON event_queue(status, sent_at)
    WHERE status = 'sent';
"""


def _init_db(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10, check_same_thread=False,
                           isolation_level="DEFERRED")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous  = NORMAL")
    conn.execute("PRAGMA wal_autocheckpoint = 1000")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA cache_size = -4000")       # 4 MB
    conn.execute("PRAGMA mmap_size = 67108864")      # 64 MB mmap for reads
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.executescript(_SCHEMA)
    conn.commit()

    if platform.system() != "Windows":
        try:
            os.chmod(str(path), stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
    return conn


# ═══════════════════════════════════════════════════════════════════════════════
#  METRICS
# ═══════════════════════════════════════════════════════════════════════════════

class _Metrics:
    __slots__ = (
        "enqueued", "sent", "failed", "retried", "dropped",
        "ws_sent", "http_sent", "cleaned", "compressed",
        "deduped", "ack_timeouts", "partial_failures",
        "_lock",
    )

    def __init__(self):
        self.enqueued = 0
        self.sent = 0
        self.failed = 0
        self.retried = 0
        self.dropped = 0
        self.ws_sent = 0
        self.http_sent = 0
        self.cleaned = 0
        self.compressed = 0
        self.deduped = 0
        self.ack_timeouts = 0
        self.partial_failures = 0
        self._lock = threading.Lock()

    def bump(self, **kw):
        with self._lock:
            for k, v in kw.items():
                setattr(self, k, getattr(self, k) + v)

    def snapshot(self) -> dict:
        with self._lock:
            return {s: getattr(self, s) for s in self.__slots__ if not s.startswith("_")}


# ═══════════════════════════════════════════════════════════════════════════════
#  WRITE BUFFER (in-memory → batched DB writes)
# ═══════════════════════════════════════════════════════════════════════════════

class _WriteBuffer:
    """
    In-memory buffer that collects enqueued events and flushes them to SQLite
    in a single transaction.  This eliminates per-insert commits (the #1
    performance bottleneck in v1).

    Thread safety: a simple Lock guards the deque.  The flush is done by a
    dedicated timer thread OR triggered when the buffer is full.
    """

    def __init__(self, conn: sqlite3.Connection, db_lock: threading.Lock,
                 cipher: _Cipher, metrics: _Metrics):
        self._conn    = conn
        self._db_lock = db_lock
        self._cipher  = cipher
        self._metrics = metrics
        self._buf: Deque[tuple] = deque()
        self._buf_lock = threading.Lock()
        self._running  = False
        self._timer    = None

    def start(self):
        self._running = True
        self._schedule_flush()

    def stop(self):
        """Flush remaining items, then stop the timer."""
        self._running = False
        if self._timer:
            self._timer.cancel()
        self.flush()

    def append(self, event_type: str, payload_json: str, priority: int,
               created_at: str, payload_len: int):
        encrypted = self._cipher.encrypt(payload_json)
        with self._buf_lock:
            self._buf.append((event_type, encrypted, priority, created_at,
                              "pending", 0, payload_len))
            if len(self._buf) >= WRITE_BUFFER_MAX:
                self._do_flush()

    def flush(self):
        with self._buf_lock:
            self._do_flush()

    def _do_flush(self):
        """Must be called with _buf_lock held."""
        if not self._buf:
            return
        items = list(self._buf)
        self._buf.clear()
        with self._db_lock:
            self._conn.executemany(
                """INSERT INTO event_queue
                       (event_type, payload, priority, created_at, status,
                        retry_count, payload_len)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                items,
            )
            self._conn.commit()

    def _schedule_flush(self):
        if not self._running:
            return
        self._timer = threading.Timer(WRITE_BUFFER_INTERVAL, self._timer_flush)
        self._timer.daemon = True
        self._timer.start()

    def _timer_flush(self):
        try:
            self.flush()
        except Exception as e:
            logger.error(f"Write buffer flush error: {e}")
        self._schedule_flush()

    @property
    def size(self) -> int:
        with self._buf_lock:
            return len(self._buf)


# ═══════════════════════════════════════════════════════════════════════════════
#  ACK TRACKER (for WS delivery guarantee)
# ═══════════════════════════════════════════════════════════════════════════════

class _AckTracker:
    """
    Tracks event IDs that have been sent over WebSocket but not yet
    acknowledged by the server.  If ACK is not received within the timeout,
    the events are returned to 'pending' status.
    """

    def __init__(self):
        self._pending: Dict[int, float] = {}   # row_id → sent_timestamp
        self._lock = threading.Lock()

    def register(self, row_ids: List[int]):
        now = time.monotonic()
        with self._lock:
            for rid in row_ids:
                self._pending[rid] = now

    def acknowledge(self, row_ids: List[int]) -> List[int]:
        """Remove acknowledged IDs.  Returns the list of IDs that were actually pending."""
        confirmed = []
        with self._lock:
            for rid in row_ids:
                if rid in self._pending:
                    del self._pending[rid]
                    confirmed.append(rid)
        return confirmed

    def collect_timed_out(self, timeout: float = WS_ACK_TIMEOUT) -> List[int]:
        """Return IDs that have been pending longer than `timeout` seconds."""
        now = time.monotonic()
        expired = []
        with self._lock:
            to_remove = []
            for rid, ts in self._pending.items():
                if now - ts > timeout:
                    expired.append(rid)
                    to_remove.append(rid)
            for rid in to_remove:
                del self._pending[rid]
        return expired

    @property
    def pending_count(self) -> int:
        with self._lock:
            return len(self._pending)


# ═══════════════════════════════════════════════════════════════════════════════
#  OFFLINE QUEUE (main class)
# ═══════════════════════════════════════════════════════════════════════════════

class OfflineQueue:
    """
    Enterprise-grade offline event queue with encrypted local persistence,
    ACK-based WebSocket delivery, adaptive batching, compression, backpressure,
    and OS-level key protection.
    """

    def __init__(
        self,
        machine_id: str,
        ws_send_fn:       Optional[Callable] = None,
        http_post_fn:     Optional[Callable] = None,
        http_post_json_fn: Optional[Callable] = None,
        db_path:          Path = DB_PATH,
    ):
        self._machine_id       = machine_id
        self._ws_send          = ws_send_fn
        self._http_post        = http_post_fn
        self._http_post_json   = http_post_json_fn
        self._db_path          = db_path
        self._running          = False

        # Encryption
        key = _load_or_create_key(machine_id)
        self._cipher = _Cipher(key)

        # SQLite
        self._conn    = _init_db(db_path)
        self._db_lock = threading.Lock()

        # Subsystems
        self.metrics    = _Metrics()
        self._ack       = _AckTracker()
        self._buf       = _WriteBuffer(self._conn, self._db_lock,
                                       self._cipher, self.metrics)

        # Deduplication (in-memory, short-lived)
        self._dedup_cache: Dict[str, float] = {}
        self._dedup_lock = threading.Lock()

        # Adaptive sync state
        self._sync_interval = SYNC_INTERVAL_MIN
        self._sync_cycle    = 0

        # Backpressure flag (read by external callers)
        self.backpressure = False

        # Recover stuck rows from prior crash
        self._recover_stuck()

    # ══════════════════════════════════════════════════════════════════════
    #  PUBLIC API
    # ══════════════════════════════════════════════════════════════════════

    def enqueue(self, event_type: str, payload: dict,
                priority: int = PRIORITY_NORMAL) -> bool:
        """
        Add an event to the queue.  Returns False if the event was dropped
        (backpressure, too large, or duplicate).
        """
        # ── Payload size check ────────────────────────────────────────
        payload_json = json.dumps(payload, default=str, separators=(",", ":"))
        payload_len = len(payload_json)
        if payload_len > MAX_PAYLOAD_BYTES:
            logger.warning(
                f"Payload too large ({payload_len:,} B > {MAX_PAYLOAD_BYTES:,} B), "
                f"event_type={event_type} — dropped"
            )
            self.metrics.bump(dropped=1)
            return False

        # ── Backpressure ──────────────────────────────────────────────
        if self.backpressure and priority >= PRIORITY_LOW:
            self.metrics.bump(dropped=1)
            return False

        # ── Deduplication ─────────────────────────────────────────────
        dedup_key = f"{event_type}:{hashlib.md5(payload_json.encode()).hexdigest()}"
        now = time.monotonic()
        with self._dedup_lock:
            last = self._dedup_cache.get(dedup_key)
            if last and (now - last) < DEDUP_WINDOW_SECONDS:
                self.metrics.bump(deduped=1)
                return False
            self._dedup_cache[dedup_key] = now
            # Trim cache periodically
            if len(self._dedup_cache) > 5000:
                cutoff = now - DEDUP_WINDOW_SECONDS * 2
                self._dedup_cache = {
                    k: v for k, v in self._dedup_cache.items() if v > cutoff
                }

        # ── Buffer the event ──────────────────────────────────────────
        created_at = datetime.now(timezone.utc).isoformat()
        self._buf.append(event_type, payload_json, priority, created_at,
                         payload_len)
        self.metrics.bump(enqueued=1)
        if payload_len > COMPRESS_THRESHOLD:
            self.metrics.bump(compressed=1)
        return True

    def start(self):
        if self._running:
            return
        self._running = True
        self._buf.start()
        threading.Thread(target=self._sync_loop, name="q-sync", daemon=True).start()
        threading.Thread(target=self._cleanup_loop, name="q-clean", daemon=True).start()
        threading.Thread(target=self._ack_timeout_loop, name="q-ack", daemon=True).start()
        logger.info(f"Queue v2 started (db={self._db_path}, max={MAX_QUEUE_SIZE:,})")

    def stop(self):
        """Graceful shutdown: flush write buffer, then signal workers to exit."""
        self._running = False
        self._buf.stop()
        logger.info("Queue v2 stopped (buffer flushed)")

    def set_ws(self, ws_send_fn: Optional[Callable]):
        self._ws_send = ws_send_fn

    def handle_ws_ack(self, data: dict):
        """
        Called by the agent's WS on_message handler when the server sends
        an event_ack message:  {"type": "event_ack", "ack_ids": [1, 2, 3]}
        """
        ack_ids = data.get("ack_ids", [])
        if not ack_ids:
            return
        confirmed = self._ack.acknowledge(ack_ids)
        if confirmed:
            self._mark_sent(confirmed)
            self.metrics.bump(ws_sent=len(confirmed))

    def queue_depth(self) -> int:
        with self._db_lock:
            r = self._conn.execute(
                "SELECT COUNT(*) FROM event_queue WHERE status IN ('pending','sending')"
            ).fetchone()
            return r[0] if r else 0

    def get_health(self) -> dict:
        """Comprehensive health snapshot for monitoring."""
        m = self.metrics.snapshot()
        depth = self.queue_depth()
        total_attempted = max(m["sent"] + m["failed"] + m["retried"], 1)
        return {
            "queue_depth":      depth,
            "buffer_size":      self._buf.size,
            "ws_ack_pending":   self._ack.pending_count,
            "backpressure":     self.backpressure,
            "sync_interval_s":  self._sync_interval,
            "error_rate":       round(m["failed"] / total_attempted, 4),
            "retry_rate":       round(m["retried"] / total_attempted, 4),
            **m,
        }

    def get_metrics(self) -> dict:
        """Backward-compatible alias."""
        return self.get_health()

    # ══════════════════════════════════════════════════════════════════════
    #  SYNC WORKER
    # ══════════════════════════════════════════════════════════════════════

    def _sync_loop(self):
        while self._running:
            try:
                self._sync_cycle += 1
                sent_count = self._sync_batch()
                self._adapt_interval(sent_count)
                self._enforce_limits()
            except Exception as e:
                logger.error(f"Sync error: {e}", exc_info=True)

            # Responsive sleep
            slices = max(1, int(self._sync_interval / 0.2))
            for _ in range(slices):
                if not self._running:
                    return
                time.sleep(0.2)

    def _sync_batch(self) -> int:
        """Fetch pending events and deliver.  Returns count sent."""
        now_iso = datetime.now(timezone.utc).isoformat()

        # Fair scheduling: every N-th cycle, include low-priority events
        fair_round = (self._sync_cycle % LOW_PRI_EVERY_N == 0)
        max_pri = 10 if fair_round else PRIORITY_LOW  # exclude LOW on normal rounds

        # Compute batch size BEFORE acquiring db_lock (avoids deadlock
        # since _current_batch_size -> queue_depth also acquires db_lock)
        batch_sz = self._current_batch_size()

        with self._db_lock:
            rows = self._conn.execute(
                """SELECT id, event_type, payload, retry_count, payload_len
                   FROM event_queue
                   WHERE status = 'pending'
                     AND priority < ?
                     AND (next_retry IS NULL OR next_retry <= ?)
                   ORDER BY priority ASC, id ASC
                   LIMIT ?""",
                (max_pri, now_iso, batch_sz),
            ).fetchall()

        if not rows:
            return 0

        ids = [r[0] for r in rows]
        self._set_status(ids, "sending")

        ws_sent: set = set()

        # ── WebSocket path (ACK-based) ────────────────────────────────
        if self._ws_send:
            ws_sent = self._send_via_ws(rows)
            if ws_sent:
                remaining = [r for r in rows if r[0] not in ws_sent]
                if not remaining:
                    return len(ws_sent)
                rows = remaining

        # ── HTTP batch fallback ───────────────────────────────────────
        if self._http_post_json or self._http_post:
            http_sent = self._send_via_http(rows)
            return len(ws_sent) + http_sent

        # No transport — revert to pending
        self._set_status([r[0] for r in rows], "pending")
        return 0

    def _send_via_ws(self, rows: list) -> Set[int]:
        """
        Send events over WebSocket with ACK tracking.
        Events are marked 'sending' (not 'sent') until the server ACKs.
        Returns set of row IDs that were successfully transmitted.
        """
        transmitted: Set[int] = set()
        for row_id, etype, enc_payload, _, _ in rows:
            try:
                payload = json.loads(self._cipher.decrypt(enc_payload))
                msg = json.dumps({
                    "type": f"{etype}_activity",
                    "_queue_id": row_id,     # server echoes this in ACK
                    **payload,
                })
                self._ws_send(msg)
                transmitted.add(row_id)
            except Exception:
                break  # WS disconnected

        if transmitted:
            self._ack.register(list(transmitted))
            # Events stay in 'sending' until ACK arrives or timeout
        return transmitted

    def _send_via_http(self, rows: list) -> int:
        """
        Send events as an HTTP batch.  Supports partial success response.
        Returns count of successfully processed events.
        """
        events = []
        id_map: Dict[int, dict] = {}
        for row_id, etype, enc_payload, retry_count, _ in rows:
            try:
                payload = json.loads(self._cipher.decrypt(enc_payload))
            except Exception:
                self._mark_failed([row_id])
                continue
            evt = {"queue_id": row_id, "event_type": etype, "data": payload}
            events.append(evt)
            id_map[row_id] = {"retry_count": retry_count}

        if not events:
            return 0

        body = {"machine_id": self._machine_id, "events": events}

        # Try JSON-returning POST first (partial success support)
        resp = None
        if self._http_post_json:
            try:
                resp = self._http_post_json("/api/activity/batch", body)
            except Exception as e:
                logger.debug(f"Batch POST failed: {e}")

        if resp and isinstance(resp, dict):
            return self._handle_batch_response(resp, id_map)

        # Fallback: boolean POST
        if self._http_post:
            try:
                ok = self._http_post("/api/activity/batch", body)
            except Exception:
                ok = False
            all_ids = list(id_map.keys())
            if ok:
                self._mark_sent(all_ids)
                self.metrics.bump(http_sent=len(all_ids))
                return len(all_ids)

        # Total failure
        self._handle_retries(
            [(rid, info["retry_count"]) for rid, info in id_map.items()]
        )
        return 0

    def _handle_batch_response(self, resp: dict, id_map: dict) -> int:
        """
        Process a partial-success batch response from the server:
        { "status": "ok", "processed": N, "success_ids": [...], "failed_ids": [...] }
        """
        success_ids = resp.get("success_ids")
        failed_ids  = resp.get("failed_ids")

        # If server returns granular IDs, use them
        if success_ids is not None:
            sent = [i for i in success_ids if i in id_map]
            fail = [i for i in (failed_ids or []) if i in id_map]
            unknown = [i for i in id_map if i not in set(sent) and i not in set(fail)]
            if sent:
                self._mark_sent(sent)
                self.metrics.bump(http_sent=len(sent))
            if fail:
                self._handle_retries(
                    [(i, id_map[i]["retry_count"]) for i in fail]
                )
                self.metrics.bump(partial_failures=len(fail))
            if unknown:
                # Treat unknowns as retryable
                self._handle_retries(
                    [(i, id_map[i]["retry_count"]) for i in unknown]
                )
            return len(sent)

        # Fallback: "processed" count only (all-or-nothing)
        processed = resp.get("processed", 0)
        all_ids = list(id_map.keys())
        if processed >= len(all_ids):
            self._mark_sent(all_ids)
            self.metrics.bump(http_sent=len(all_ids))
            return len(all_ids)
        elif processed > 0:
            # Assume first N were successful (order matches)
            self._mark_sent(all_ids[:processed])
            self.metrics.bump(http_sent=processed)
            self._handle_retries(
                [(i, id_map[i]["retry_count"]) for i in all_ids[processed:]]
            )
            return processed
        else:
            self._handle_retries(
                [(i, id_map[i]["retry_count"]) for i in all_ids]
            )
            return 0

    # ══════════════════════════════════════════════════════════════════════
    #  ADAPTIVE SYNC
    # ══════════════════════════════════════════════════════════════════════

    def _adapt_interval(self, sent_count: int):
        """Speed up when busy, slow down when idle."""
        if sent_count > 20:
            self._sync_interval = SYNC_INTERVAL_MIN
        elif sent_count > 0:
            self._sync_interval = max(SYNC_INTERVAL_MIN,
                                      self._sync_interval - 1)
        else:
            self._sync_interval = min(SYNC_INTERVAL_MAX,
                                      self._sync_interval + 1)

    def _current_batch_size(self) -> int:
        """Increase batch size under high queue pressure."""
        depth = self.queue_depth()
        if depth > 10_000:
            return BATCH_SIZE_MAX
        if depth > 1_000:
            return min(BATCH_SIZE_MAX, BATCH_SIZE_DEFAULT * 2)
        return BATCH_SIZE_DEFAULT

    # ══════════════════════════════════════════════════════════════════════
    #  ACK TIMEOUT WORKER
    # ══════════════════════════════════════════════════════════════════════

    def _ack_timeout_loop(self):
        """Check for WS events that were never ACKed."""
        while self._running:
            try:
                expired = self._ack.collect_timed_out(WS_ACK_TIMEOUT)
                if expired:
                    self._set_status(expired, "pending")
                    self.metrics.bump(ack_timeouts=len(expired))
                    logger.debug(f"ACK timeout: {len(expired)} events returned to pending")
            except Exception as e:
                logger.error(f"ACK timeout check error: {e}")
            time.sleep(WS_ACK_TIMEOUT / 2)

    # ══════════════════════════════════════════════════════════════════════
    #  QUEUE LIMITS + EVICTION + BACKPRESSURE
    # ══════════════════════════════════════════════════════════════════════

    def _enforce_limits(self):
        """Check queue size and apply eviction / backpressure as needed."""
        depth = self.queue_depth()

        # Backpressure signal
        self.backpressure = depth > BACKPRESSURE_THRESHOLD

        if depth <= MAX_QUEUE_SIZE:
            return

        # Eviction: drop oldest low-priority events first
        with self._db_lock:
            cur = self._conn.execute(
                """DELETE FROM event_queue WHERE id IN (
                       SELECT id FROM event_queue
                       WHERE status = 'pending' AND priority >= ?
                       ORDER BY priority DESC, id ASC
                       LIMIT ?
                   )""",
                (PRIORITY_LOW, EVICTION_BATCH),
            )
            evicted = cur.rowcount
            if evicted < EVICTION_BATCH // 2:
                # Not enough low-pri — escalate to normal
                cur2 = self._conn.execute(
                    """DELETE FROM event_queue WHERE id IN (
                           SELECT id FROM event_queue
                           WHERE status = 'pending' AND priority >= ?
                           ORDER BY priority DESC, id ASC
                           LIMIT ?
                       )""",
                    (PRIORITY_NORMAL, EVICTION_BATCH - evicted),
                )
                evicted += cur2.rowcount
            self._conn.commit()

        if evicted:
            self.metrics.bump(dropped=evicted)
            logger.warning(f"Queue eviction: dropped {evicted} events (depth was {depth})")

    # ══════════════════════════════════════════════════════════════════════
    #  DB HELPERS
    # ══════════════════════════════════════════════════════════════════════

    def _set_status(self, ids: list, status: str):
        if not ids:
            return
        ph = ",".join("?" * len(ids))
        with self._db_lock:
            self._conn.execute(
                f"UPDATE event_queue SET status = ? WHERE id IN ({ph})",
                [status] + ids,
            )
            self._conn.commit()

    def _mark_sent(self, ids: list):
        if not ids:
            return
        now = datetime.now(timezone.utc).isoformat()
        ph = ",".join("?" * len(ids))
        with self._db_lock:
            self._conn.execute(
                f"UPDATE event_queue SET status='sent', sent_at=? WHERE id IN ({ph})",
                [now] + ids,
            )
            self._conn.commit()
        self.metrics.bump(sent=len(ids))

    def _mark_failed(self, ids: list):
        if not ids:
            return
        ph = ",".join("?" * len(ids))
        with self._db_lock:
            self._conn.execute(
                f"UPDATE event_queue SET status='failed' WHERE id IN ({ph})",
                ids,
            )
            self._conn.commit()
        self.metrics.bump(failed=len(ids))

    def _handle_retries(self, id_retry_pairs: list):
        failed_ids = []
        retry_rows: list = []
        for row_id, rc in id_retry_pairs:
            new_count = rc + 1
            if new_count > MAX_RETRIES:
                failed_ids.append(row_id)
            else:
                delay = min(2 ** new_count, 300)
                next_ts = (datetime.now(timezone.utc) + timedelta(seconds=delay)).isoformat()
                retry_rows.append((new_count, next_ts, row_id))

        if retry_rows:
            with self._db_lock:
                self._conn.executemany(
                    "UPDATE event_queue SET status='pending', retry_count=?, next_retry=? WHERE id=?",
                    retry_rows,
                )
                self._conn.commit()
            self.metrics.bump(retried=len(retry_rows))

        if failed_ids:
            self._mark_failed(failed_ids)

    def _recover_stuck(self):
        with self._db_lock:
            cur = self._conn.execute(
                "UPDATE event_queue SET status='pending' WHERE status='sending'"
            )
            self._conn.commit()
            if cur.rowcount:
                logger.info(f"Crash recovery: {cur.rowcount} stuck events → pending")

    # ══════════════════════════════════════════════════════════════════════
    #  CLEANUP WORKER
    # ══════════════════════════════════════════════════════════════════════

    def _cleanup_loop(self):
        while self._running:
            try:
                cutoff = (datetime.now(timezone.utc)
                          - timedelta(hours=CLEANUP_SENT_HOURS)).isoformat()
                with self._db_lock:
                    cur = self._conn.execute(
                        "DELETE FROM event_queue WHERE status='sent' AND sent_at < ?",
                        (cutoff,),
                    )
                    self._conn.commit()
                    if cur.rowcount:
                        self.metrics.bump(cleaned=cur.rowcount)
                        logger.debug(f"Cleaned {cur.rowcount} old sent events")
            except Exception as e:
                logger.error(f"Cleanup error: {e}")

            for _ in range(CLEANUP_INTERVAL * 5):
                if not self._running:
                    return
                time.sleep(0.2)
