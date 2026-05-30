"""Shared pytest fixtures for the CropSentinel test suite.

Design notes
------------
* The backend speaks Postgres (psycopg2 + a module-level pool), so tests cannot
  run against an in-memory SQLite. Instead we point at a dedicated *test*
  Postgres database via the ``CROPPRO_TEST_DATABASE_URL`` env var. If that var
  is not set, integration tests are skipped with a clear message - unit-only
  tests (e.g. ``test_passwords.py``) still run.

* Schema is initialised once per session. Between tests we TRUNCATE every
  tenant-scoped table so each test starts from a clean slate without paying
  the cost of DROP/CREATE.

* The FastAPI app is exercised via ``httpx.AsyncClient`` bound to an ASGI
  transport - no sockets, no event-loop juggling, fast.

Fixture index
-------------
``test_db``      - session fixture; guarantees schema + truncates between tests
``api``          - async HTTP client bound to the FastAPI app
``make_tenant``  - factory: create tenant, returns row dict
``make_user``    - factory: create user under a tenant, returns row dict
``auth_headers`` - factory: login as a given user, returns Bearer headers
``default_tenant`` - the tenant auto-seeded with id=1
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import uuid
import zlib
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import pytest
import psycopg2


# ---------------------------------------------------------------------------
# Test database bootstrap - must happen BEFORE importing app modules.
# ---------------------------------------------------------------------------
_TEST_DB_URL = os.environ.get("CROPPRO_TEST_DATABASE_URL", "").strip()
_TEST_DB_SCHEMA = ""


def _with_search_path(database_url: str, schema_name: str) -> str:
    split = urlsplit(database_url)
    query = dict(parse_qsl(split.query, keep_blank_values=True))
    options = query.get("options", "").strip()
    search_path_opt = f"-csearch_path={schema_name}"
    query["options"] = f"{options} {search_path_opt}".strip() if options else search_path_opt
    return urlunsplit((split.scheme, split.netloc, split.path, urlencode(query), split.fragment))


def _resolve_test_schema_name() -> str:
    worker = os.environ.get("PYTEST_XDIST_WORKER", "").strip().lower()
    if worker:
        return f"test_{worker}"
    return "test_main"


def _ensure_test_schema_exists(database_url: str, schema_name: str) -> None:
    conn = psycopg2.connect(database_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema_name}"')
    finally:
        conn.close()

if _TEST_DB_URL:
    _TEST_DB_SCHEMA = _resolve_test_schema_name()
    _ensure_test_schema_exists(_TEST_DB_URL, _TEST_DB_SCHEMA)
    # The app reads DATABASE_URL at import time in app/db/core.py, so we
    # have to set it before any `from database import db` happens.
    os.environ["DATABASE_URL"] = _with_search_path(_TEST_DB_URL, _TEST_DB_SCHEMA)
    os.environ.setdefault("EVENT_SINKS_ENABLED", "0")
    from app.ops_metrics import ops_metrics
else:
    ops_metrics = None


def _skip_if_no_test_db():
    if not _TEST_DB_URL:
        pytest.skip(
            "CROPPRO_TEST_DATABASE_URL is not set. "
            "Set it to a disposable Postgres DSN to run integration tests "
            "(e.g. postgresql://postgres:postgres@localhost:5432/croppro_test).",
            allow_module_level=False,
        )


def _parallel_workers_requested(config: pytest.Config) -> bool:
    try:
        numprocesses = config.getoption("numprocesses")
    except Exception:
        return False
    if numprocesses in (None, 0, "0"):
        return False
    return True


def pytest_configure(config: pytest.Config) -> None:
    if _parallel_workers_requested(config) and not _TEST_DB_URL:
        raise pytest.UsageError(
            "Parallel CropSentinel backend tests require CROPPRO_TEST_DATABASE_URL "
            "so each worker can isolate itself in its own Postgres schema."
        )


# ---------------------------------------------------------------------------
# Session-scoped: import app lazily, init schema once.
# ---------------------------------------------------------------------------
@pytest.fixture(scope="session")
def _app_module():
    _skip_if_no_test_db()
    # Deferred import so the skip above fires before psycopg2 connects.
    from database import db
    from app.analytics_pipeline import analytics_pipeline
    from main import app
    from app import core as _app_core
    from app.event_workers import internal_event_workers

    with _shared_test_db_lock():
        db.init_db()
    asyncio.run(internal_event_workers.start())
    asyncio.run(analytics_pipeline.start())

    # slowapi's in-memory limiter is keyed on client IP. Every test hits
    # 127.0.0.1, so after ~10 logins the "10/15minute" gate trips 429 and
    # poisons every downstream test. We still want to exercise the
    # per-username lockout (tested in test_auth.py), so we disable slowapi
    # globally here rather than reset-between-tests.
    _app_core.limiter.enabled = False

    # httpx.ASGITransport does NOT run FastAPI's lifespan events, so
    # app.state.{license, seat_enforcer} are never initialized by the
    # normal startup path. Set the minimum state the routes look for:
    #   - license = None   -> has_feature() returns True only when bootstrap mode is off
    #   - seat_enforcer    -> required by /api/machines/register
    from licensing import SeatEnforcer

    app.state.license = None
    app.state.license_bootstrap = False
    app.state.license_error = ""
    app.state.seat_enforcer = SeatEnforcer(
        db=db,
        license_info_provider=lambda: getattr(app.state, "license", None),
        bootstrap_mode_provider=lambda: getattr(app.state, "license_bootstrap", False),
    )

    return app, db


@pytest.fixture(scope="session")
def app(_app_module):
    return _app_module[0]


@pytest.fixture(scope="session")
def db(_app_module):
    return _app_module[1]


# ---------------------------------------------------------------------------
# Per-test: truncate tenant-scoped tables so each test starts clean.
# The tenants table is reset too, then id=1 ("default") is reseeded, matching
# how a fresh install looks.
# ---------------------------------------------------------------------------
_TRUNCATE_TABLES = [
    "machine_inventory_rollups",
    "audit_logs",
    "alert_logs",
    "alert_rules",
    "tenant_config_documents",
    "evidence_objects",
    "phishing_incident_timeline",
    "phishing_incident_notes",
    "phishing_incidents",
    "phishing_events",
    "phishing_blocklist_exceptions",
    "phishing_allowlist_exceptions",
    "phishing_policies",
    "dlp_incident_timeline",
    "dlp_incident_notes",
    "dlp_incidents",
    "dlp_file_inventory_sync_status",
    "dlp_file_inventory",
    "dlp_exceptions",
    "dlp_rules",
    "dlp_classifiers",
    "dlp_policies",
    "dlp_events",
    "network_activity",
    "file_activity",
    "deleted_file_backups",
    "report_jobs",
    "browser_activity",
    "app_usage",
    "input_activity",
    "productivity_logs",
    "screenshots",
    "settings",
    "users",
    "machines",
    "tenants",
]

_TEST_DB_LOCK_KEY = zlib.crc32(
    f"CropSentinel/backend/tests/shared-postgres-lock:{_TEST_DB_SCHEMA or 'default'}".encode("utf-8")
) & 0x7FFFFFFF


@contextlib.contextmanager
def _shared_test_db_lock():
    from app.db.core import get_pool

    pool = get_pool()
    conn = pool.getconn()
    conn.autocommit = False
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT pg_advisory_lock(%s)", (_TEST_DB_LOCK_KEY,))
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(%s)", (_TEST_DB_LOCK_KEY,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            pool.putconn(conn)


@pytest.fixture(autouse=True)
def _clean_db():
    """Reset shared state before every test.

    When multiple pytest workers or sessions point at the same Postgres test
    database, keep one test active at a time. This prevents TRUNCATE deadlocks
    and avoids wiping tenant rows while another ASGI request is mid-flight.
    """
    if not _TEST_DB_URL:
        yield
        return

    from app import core as _app_core
    from app.analytics_pipeline import analytics_pipeline
    from app.db.core import clear_tenant_context
    from app.evidence_storage import evidence_storage
    from app.event_workers import internal_event_workers
    from database import db  # noqa: F401 - ensures schema-init path is reachable
    from main import app

    # In-process login-throttle state is a module-level dict. If tests leave
    # entries in it, later tests hit 429 instead of 401 and failures look
    # like race conditions. Wipe it between every test.
    _app_core._login_fails.clear()
    _app_core._login_lockouts.clear()
    app.state.license = None
    internal_event_workers._screenshot_insert_count.clear()
    for key in list(internal_event_workers._sink_counts.keys()):
        internal_event_workers._sink_counts[key] = 0
    if not internal_event_workers._started:
        asyncio.run(internal_event_workers.start())
    if not analytics_pipeline._started:
        asyncio.run(analytics_pipeline.start())
    analytics_pipeline._queue.clear()
    analytics_pipeline.backend = "noop"
    analytics_pipeline.url = ""
    analytics_pipeline._ready = False
    if ops_metrics is not None:
        ops_metrics.reset()

    clear_tenant_context()
    try:
        with _shared_test_db_lock() as lock_conn:
            with lock_conn.cursor() as cur:
                cur.execute("SELECT tablename FROM pg_tables WHERE schemaname = current_schema()")
                rows = cur.fetchall() or []
                present = {row["tablename"] for row in rows}
                targets = [table for table in _TRUNCATE_TABLES if table in present]
                if targets:
                    cur.execute(f"TRUNCATE {', '.join(targets)} RESTART IDENTITY CASCADE")
                cur.execute(
                    """
                    INSERT INTO tenants (id, slug, name, status, enrollment_token,
                                         customer_name, tier, max_seats, grace_days)
                    VALUES (1, 'default', 'Default Tenant', 'active',
                            'cpet_test_default', 'Default', 'enterprise', 0, 14)
                    ON CONFLICT (id) DO NOTHING
                    """
                )
                cur.execute(
                    "SELECT setval('tenants_id_seq', GREATEST((SELECT MAX(id) FROM tenants), 1))"
                )
            # The advisory lock is session-scoped and survives commit. Commit
            # the cleanup work here so the app's other pooled connections can
            # see the reset tenant state during the test body.
            lock_conn.commit()

        if evidence_storage.root.exists():
            shutil.rmtree(evidence_storage.root, ignore_errors=True)
        Path(evidence_storage.root).mkdir(parents=True, exist_ok=True)
        yield
    finally:
        clear_tenant_context()


# ---------------------------------------------------------------------------
# HTTP client bound to the FastAPI app (no real network).
# ---------------------------------------------------------------------------
@pytest.fixture
async def api(app):
    import httpx

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


# ---------------------------------------------------------------------------
# Factories
# ---------------------------------------------------------------------------
@pytest.fixture
def default_tenant(db) -> dict:
    t = db.get_tenant(1)
    assert t is not None, "Default tenant (id=1) must exist after _clean_db"
    return t


@pytest.fixture
def make_tenant(db) -> Callable[..., dict]:
    def _factory(
        slug: Optional[str] = None,
        name: str = "",
        tier: str = "professional",
        max_seats: int = 10,
        grace_days: int = 14,
    ) -> dict:
        slug = slug or f"t-{uuid.uuid4().hex[:8]}"
        tenant_id = db.create_tenant(
            slug=slug,
            name=name or slug,
            customer_name=name or slug,
            tier=tier,
            max_seats=max_seats,
            grace_days=grace_days,
        )
        return db.get_tenant(tenant_id)

    return _factory


@pytest.fixture
def make_user(db) -> Callable[..., dict]:
    """Create a user under a specific tenant. Defaults to tenant 1 + admin."""
    from passwords import hash_password

    def _factory(
        tenant_id: int = 1,
        username: Optional[str] = None,
        password: str = "Passw0rd!Test",
        role: str = "admin",
        display_name: str = "Test User",
        active: bool = True,
    ) -> dict:
        username = username or f"user-{uuid.uuid4().hex[:8]}"
        user_id = db.create_user(
            {
                "tenant_id": tenant_id,
                "username": username,
                "password_hash": hash_password(password),
                "display_name": display_name,
                "role": role,
                "active": active,
                "created_by": "pytest",
            }
        )
        return {
            "id": user_id,
            "tenant_id": tenant_id,
            "username": username,
            "password": password,
            "role": role,
            "display_name": display_name,
            "active": active,
        }

    return _factory


@pytest.fixture
async def auth_headers(api, make_user) -> Callable[..., dict]:
    """Log in as a freshly-created user and return Bearer headers."""

    async def _factory(
        role: str = "admin",
        tenant_id: int = 1,
        username: Optional[str] = None,
    ) -> dict:
        from app.core import create_access_token
        from database import db

        user = make_user(tenant_id=tenant_id, username=username, role=role)
        resp = await api.post(
            "/api/auth/login",
            data={"username": user["username"], "password": user["password"]},
        )
        stored_user = db.get_user_by_username(user["username"])
        if resp.status_code != 200 and stored_user and db.get_tenant(tenant_id):
            token = create_access_token(
                {
                    "sub": user["username"],
                    "role": user["role"],
                    "user_id": user["id"],
                    "tenant_id": tenant_id,
                    "display_name": user.get("display_name", ""),
                    "assigned_machines": [],
                }
            )
            return {"Authorization": f"Bearer {token}"}
        assert resp.status_code == 200, f"Login failed: {resp.status_code} {resp.text}"
        token = resp.json()["access_token"]
        return {"Authorization": f"Bearer {token}"}

    return _factory
