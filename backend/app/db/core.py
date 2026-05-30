"""Shared tenant, connection-pool, and UTC helpers for the DB layer."""

import os
import threading
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Optional

import psycopg2.extras
import psycopg2.pool

_current_tenant_id: ContextVar[Optional[int]] = ContextVar(
    "current_tenant_id",
    default=None,
)


def set_tenant_context(tenant_id: int) -> None:
    _current_tenant_id.set(tenant_id)


def clear_tenant_context() -> None:
    _current_tenant_id.set(None)


def get_tenant_id() -> int:
    return _current_tenant_id.get() or 1


DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://postgres:Husain%400404@localhost:5432/croppro",
)

_pool: Optional[psycopg2.pool.ThreadedConnectionPool] = None
_partition_lock = threading.Lock()
_known_partitions: set[tuple[str, str]] = set()
_partitioned_tables = {
    "browser_activity",
    "app_activity",
    "file_activity",
    "network_activity",
    "dlp_events",
    "phishing_events",
}


def _safe_int(value: str, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


DB_POOL_MIN = max(1, _safe_int(os.environ.get("DB_POOL_MIN", "2"), 2))
DB_POOL_MAX = max(DB_POOL_MIN, _safe_int(os.environ.get("DB_POOL_MAX", "20"), 20))


def get_pool() -> psycopg2.pool.ThreadedConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg2.pool.ThreadedConnectionPool(
            minconn=DB_POOL_MIN,
            maxconn=DB_POOL_MAX,
            dsn=DATABASE_URL,
            cursor_factory=psycopg2.extras.RealDictCursor,
        )
    return _pool


class Connection:
    """Context manager: borrow from pool, auto-commit or rollback."""

    def __enter__(self):
        self.conn = get_pool().getconn()
        self.conn.autocommit = False
        return self.conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type:
            self.conn.rollback()
        else:
            self.conn.commit()
        get_pool().putconn(self.conn)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def tz_safe(ts) -> datetime:
    if ts is None:
        return utcnow()
    if hasattr(ts, "tzinfo") and ts.tzinfo is None:
        return ts.replace(tzinfo=timezone.utc)
    return ts


def ensure_monthly_partition(table_name: str, ts) -> None:
    if table_name not in _partitioned_tables:
        return
    if isinstance(ts, str):
        value = ts.strip()
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        ts = datetime.fromisoformat(value)
    target = tz_safe(ts).astimezone(timezone.utc)
    start = target.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end_year = start.year + (1 if start.month == 12 else 0)
    end_month = 1 if start.month == 12 else start.month + 1
    end = start.replace(year=end_year, month=end_month, day=1)
    partition_name = f"{table_name}_{start.strftime('%Y%m')}"
    cache_key = (table_name, partition_name)
    if cache_key in _known_partitions:
        return
    with _partition_lock:
        if cache_key in _known_partitions:
            return
        with Connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {partition_name}
                    PARTITION OF {table_name}
                    FOR VALUES FROM (%s) TO (%s)
                    """,
                    (start, end),
                )
        _known_partitions.add(cache_key)
