"""Day-5 agent ingestion tests.

Covers the ``machines_activity`` router — the surface every deployed agent
posts to. Three risk classes:

1. **Authentication.** The shared ``X-CropPro-Agent-Key`` header must be
   required on every activity endpoint; missing or wrong key → 401.

2. **Enrollment.** When multiple tenants exist, registering a new agent
   requires ``X-CropPro-Enroll-Token`` so the server can bind the machine
   to a tenant. Registering the same ``machine_id`` a second time under a
   *different* tenant's token must be refused (403) — otherwise a noisy
   neighbor could hijack an existing enrolled agent.

3. **Attribution.** Once a machine is enrolled to Tenant A, any activity
   posted with that ``machine_id`` (heartbeat, browser, app, etc.) must
   land in Tenant A's data — and must not appear in Tenant B's reads.

The agent API key used here is ``test-agent-key`` (pytest.ini sets
``AGENT_API_KEY=test-agent-key`` before app import).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

from app.db.core import set_tenant_context, clear_tenant_context

pytestmark = pytest.mark.integration


AGENT_KEY_HEADER = {"X-CropPro-Agent-Key": "test-agent-key"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _register_payload(machine_id: str, hostname: str = "lab-pc") -> dict:
    """Minimal valid body for POST /api/machines/register."""
    return {
        "machine_id": machine_id,
        "hostname": hostname,
        "os": "Windows",
        "os_version": "10.0.19045",
        "username": "labuser",
        "ip_address": "10.0.0.42",
        "mac_address": "aa:bb:cc:dd:ee:ff",
        "consent_given": True,
        "consent_timestamp": _now_iso(),
        "first_seen": _now_iso(),
        "agent_version": "1.0.0-test",
    }


def _heartbeat_payload(machine_id: str) -> dict:
    return {
        "machine_id": machine_id,
        "timestamp": _now_iso(),
        "cpu_percent": 12.5,
        "memory_percent": 48.0,
        "active_app": "chrome.exe",
        "active_browser": "chrome",
        "active_url": "https://example.com",
        "idle_seconds": 0,
    }


def _browser_payload(machine_id: str) -> dict:
    return {
        "machine_id": machine_id,
        "timestamp": _now_iso(),
        "browser": "chrome",
        "url": "https://example.com/page",
        "title": "Example",
        "domain": "example.com",
        "duration_seconds": 5,
    }


def _phishing_payload(machine_id: str, domain: str = "login-microsoftonline-security.com") -> dict:
    return {
        "machine_id": machine_id,
        "timestamp": _now_iso(),
        "event_type": "browser_visit",
        "channel": "browser",
        "url": f"https://{domain}/login",
        "domain": domain,
        "page_title": "Sign in to continue",
        "app_name": "Chrome",
        "process_name": "chrome.exe",
        "remote_ip": "203.0.113.55",
        "actor_username": "labuser",
    }


# ═══════════════════════════════════════════════════════════════════════════
# 1. Agent-key authentication on every /api/activity/* endpoint
# ═══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize(
    "method,path,body",
    [
        ("POST", "/api/activity/heartbeat", None),   # body filled in test
        ("POST", "/api/activity/browser",   None),
        ("POST", "/api/activity/application", None),
        ("POST", "/api/activity/input", None),
        ("POST", "/api/machines/register", None),
    ],
    ids=lambda v: str(v),
)
async def test_activity_requires_agent_api_key(api, method, path, body):
    """No header → 401."""
    payload = _heartbeat_payload("m-nokey-test")
    if path.endswith("/browser"):
        payload = _browser_payload("m-nokey-test")
    elif path.endswith("/application"):
        payload = {
            "machine_id": "m-nokey-test",
            "timestamp": _now_iso(),
            "app_name": "chrome.exe",
            "window_title": "Example",
            "process_name": "chrome.exe",
        }
    elif path.endswith("/input"):
        payload = {
            "machine_id": "m-nokey-test",
            "timestamp": _now_iso(),
            "bucket_start": _now_iso(),
            "bucket_end": _now_iso(),
        }
    elif path.endswith("/register"):
        payload = _register_payload("m-nokey-test")

    resp = await api.post(path, json=payload)  # no AGENT_KEY_HEADER
    assert resp.status_code == 401, (
        f"Expected 401 without agent key on {path}; got {resp.status_code}: {resp.text}"
    )


async def test_activity_rejects_wrong_agent_api_key(api):
    resp = await api.post(
        "/api/activity/heartbeat",
        json=_heartbeat_payload("m-wrongkey-test"),
        headers={"X-CropPro-Agent-Key": "not-the-real-key"},
    )
    assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════
# 2. Enrollment — new agent must prove its tenant
# ═══════════════════════════════════════════════════════════════════════════
async def test_register_rejects_new_machine_without_enrollment_token(
    api, make_tenant
):
    """When multiple tenants exist and no enrollment token is supplied,
    the server cannot attribute the new machine — must refuse (401).
    Reseeded default tenant + a second tenant = 2 tenants."""
    make_tenant(slug="extra-tenant-for-enroll-check")

    resp = await api.post(
        "/api/machines/register",
        json=_register_payload(f"m-{uuid.uuid4().hex[:8]}"),
        headers=AGENT_KEY_HEADER,  # no enroll token
    )
    assert resp.status_code == 401
    assert "enrollment" in resp.json()["detail"].lower()


async def test_register_with_enrollment_token_binds_machine_to_that_tenant(
    api, make_tenant, db
):
    """Register with Tenant B's enrollment token → machine row's tenant_id == B."""
    tenant_b = make_tenant(slug="agent-host-tenant", name="Agent Host Co")
    machine_id = f"m-{uuid.uuid4().hex[:8]}"

    resp = await api.post(
        "/api/machines/register",
        json=_register_payload(machine_id, hostname="lab-b"),
        headers={
            **AGENT_KEY_HEADER,
            "X-CropPro-Enroll-Token": tenant_b["enrollment_token"],
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "registered"

    # Verify server-side attribution. Read bypasses the ContextVar by calling
    # the raw lookup directly.
    assert db.get_machine_tenant_id(machine_id) == tenant_b["id"]


async def test_register_rejects_cross_tenant_reregister(api, make_tenant):
    """Machine enrolled under Tenant A cannot be silently re-enrolled under
    Tenant B — that would let a noisy neighbor hijack an existing agent."""
    tenant_a = make_tenant(slug="original-owner")
    tenant_b = make_tenant(slug="would-be-hijacker")
    machine_id = f"m-{uuid.uuid4().hex[:8]}"

    # A enrolls the machine.
    r1 = await api.post(
        "/api/machines/register",
        json=_register_payload(machine_id, hostname="lab-a"),
        headers={
            **AGENT_KEY_HEADER,
            "X-CropPro-Enroll-Token": tenant_a["enrollment_token"],
        },
    )
    assert r1.status_code == 200, r1.text

    # B tries to re-enroll the same machine_id.
    r2 = await api.post(
        "/api/machines/register",
        json=_register_payload(machine_id, hostname="hijacked"),
        headers={
            **AGENT_KEY_HEADER,
            "X-CropPro-Enroll-Token": tenant_b["enrollment_token"],
        },
    )
    assert r2.status_code == 403
    assert "different tenant" in r2.json()["detail"].lower()


async def test_activity_rejects_cross_tenant_token_for_existing_machine(api, make_tenant):
    """If a machine already belongs to tenant A, posting activity with tenant B's
    enrollment token must be rejected (403) instead of being re-attributed."""
    tenant_a = make_tenant(slug="tenant-a-activity")
    tenant_b = make_tenant(slug="tenant-b-activity")
    machine_id = f"m-{uuid.uuid4().hex[:8]}"

    r1 = await api.post(
        "/api/machines/register",
        json=_register_payload(machine_id, hostname="a-host"),
        headers={
            **AGENT_KEY_HEADER,
            "X-CropPro-Enroll-Token": tenant_a["enrollment_token"],
        },
    )
    assert r1.status_code == 200, r1.text

    bad = await api.post(
        "/api/activity/heartbeat",
        json=_heartbeat_payload(machine_id),
        headers={
            **AGENT_KEY_HEADER,
            "X-CropPro-Enroll-Token": tenant_b["enrollment_token"],
        },
    )
    assert bad.status_code == 403
    assert "different tenant" in bad.json()["detail"].lower()


async def test_register_rejects_invalid_enrollment_token(api):
    resp = await api.post(
        "/api/machines/register",
        json=_register_payload(f"m-{uuid.uuid4().hex[:8]}"),
        headers={
            **AGENT_KEY_HEADER,
            "X-CropPro-Enroll-Token": "cpet_definitely-not-a-real-token",
        },
    )
    assert resp.status_code == 401
    assert "invalid_enrollment_token" in resp.json()["detail"].lower()


async def test_reregister_same_machine_keeps_original_tenant(api, make_tenant, db):
    """Re-registering an existing machine must preserve its tenant binding."""
    tenant_a = make_tenant(slug="tenant-a-reregister")
    make_tenant(slug="tenant-b-reregister")
    machine_id = f"m-{uuid.uuid4().hex[:8]}"

    first = await api.post(
        "/api/machines/register",
        json=_register_payload(machine_id, hostname="stable-host"),
        headers={
            **AGENT_KEY_HEADER,
            "X-CropPro-Enroll-Token": tenant_a["enrollment_token"],
        },
    )
    assert first.status_code == 200, first.text
    assert db.get_machine_tenant_id(machine_id) == tenant_a["id"]

    second = await api.post(
        "/api/machines/register",
        json=_register_payload(machine_id, hostname="stable-host"),
        headers=AGENT_KEY_HEADER,
    )
    assert second.status_code == 200, second.text
    assert db.get_machine_tenant_id(machine_id) == tenant_a["id"]


# ═══════════════════════════════════════════════════════════════════════════
# 3. Attribution — activity lands in the owning tenant, not others
# ═══════════════════════════════════════════════════════════════════════════
@pytest.fixture
def seed_enrolled_machine(make_tenant, make_user, db):
    """Seed one tenant with one enrolled machine; return the pieces the
    tests need to drive the agent and verify as an admin."""

    async def _factory(api, slug_prefix: str = "ingest"):
        tenant = make_tenant(slug=f"{slug_prefix}-{uuid.uuid4().hex[:6]}")
        machine_id = f"m-{uuid.uuid4().hex[:8]}"

        # Enroll via the public API so the bound tenant_id path runs.
        r = await api.post(
            "/api/machines/register",
            json=_register_payload(machine_id, hostname=f"{slug_prefix}-host"),
            headers={
                **AGENT_KEY_HEADER,
                "X-CropPro-Enroll-Token": tenant["enrollment_token"],
            },
        )
        assert r.status_code == 200, r.text

        # An admin user in that tenant so we can inspect scoped reads.
        user = make_user(tenant_id=tenant["id"], role="admin")
        login = await api.post(
            "/api/auth/login",
            data={"username": user["username"], "password": user["password"]},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        return {
            "tenant": tenant,
            "machine_id": machine_id,
            "admin_headers": headers,
        }

    return _factory


async def test_heartbeat_attributes_data_to_machines_tenant(
    api, seed_enrolled_machine, auth_headers
):
    """A heartbeat for Tenant A's machine must show up in Tenant A's view
    of that machine, and must NOT leak into Tenant B's machines list."""
    a = await seed_enrolled_machine(api, slug_prefix="hb-a")

    # Tenant B, an unrelated tenant — its admin must not see A's machine.
    b_headers = await auth_headers(role="admin", tenant_id=1)  # default tenant

    # Agent posts heartbeat for A's machine.
    hb = await api.post(
        "/api/activity/heartbeat",
        json=_heartbeat_payload(a["machine_id"]),
        headers=AGENT_KEY_HEADER,
    )
    assert hb.status_code == 200, hb.text

    # Tenant A's admin sees the machine with the updated heartbeat fields.
    a_view = await api.get(
        f"/api/machines/{a['machine_id']}", headers=a["admin_headers"]
    )
    assert a_view.status_code == 200, a_view.text
    assert a_view.json()["machine_id"] == a["machine_id"]

    # Tenant B's admin (the default tenant) must not see A's machine in
    # their list.
    b_list = await api.get("/api/machines", headers=b_headers)
    assert b_list.status_code == 200
    ids = {m["machine_id"] for m in b_list.json()}
    assert a["machine_id"] not in ids, (
        f"LEAK: Tenant B's /api/machines included Tenant A's machine "
        f"{a['machine_id']!r}"
    )


async def test_browser_activity_routes_to_owning_tenant(
    api, seed_enrolled_machine, db
):
    """POST /api/activity/browser for Tenant A's machine stores under A."""
    a = await seed_enrolled_machine(api, slug_prefix="br-a")

    r = await api.post(
        "/api/activity/browser",
        json=_browser_payload(a["machine_id"]),
        headers=AGENT_KEY_HEADER,
    )
    assert r.status_code == 200, r.text

    # Read back as Tenant A: activity present under that tenant_id scope.
    set_tenant_context(a["tenant"]["id"])
    try:
        rows_a = db.get_browser_history(a["machine_id"], limit=100)
        assert any(r.get("machine_id") == a["machine_id"] for r in rows_a), (
            "Tenant A should see its own browser activity"
        )
    finally:
        clear_tenant_context()


async def test_direct_phishing_ingestion_creates_scoped_incident_and_diagnostics(
    api, seed_enrolled_machine, auth_headers
):
    a = await seed_enrolled_machine(api, slug_prefix="phish-direct")
    b_headers = await auth_headers(role="admin", tenant_id=1)

    resp = await api.post(
        "/api/activity/phishing",
        json=_phishing_payload(a["machine_id"]),
        headers=AGENT_KEY_HEADER,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["incident_id"] is not None

    diag = await api.get(f"/api/phishing/diagnostics/machines/{a['machine_id']}", headers=a["admin_headers"])
    assert diag.status_code == 200, diag.text
    diag_body = diag.json()
    assert diag_body["latest_event"]["domain"] == "login-microsoftonline-security.com"
    assert diag_body["effective_policy_version"] >= 1

    leaked = await api.get("/api/phishing/incidents", headers=b_headers)
    assert leaked.status_code == 200, leaked.text
    assert leaked.json()["items"] == []


async def test_batch_phishing_event_is_accepted_and_alert_is_tenant_scoped(api, seed_enrolled_machine, auth_headers):
    a = await seed_enrolled_machine(api, slug_prefix="phish-batch")
    b_headers = await auth_headers(role="admin", tenant_id=1)

    batch = await api.post(
        "/api/activity/batch",
        json={
            "machine_id": a["machine_id"],
            "events": [
                {
                    "queue_id": "q-phish-1",
                    "event_type": "phishing_alert",
                    "data": _phishing_payload(a["machine_id"], domain="github-verify-login.com"),
                }
            ],
        },
        headers=AGENT_KEY_HEADER,
    )
    assert batch.status_code == 200, batch.text
    body = batch.json()
    assert body["processed"] == 1
    assert body["success_ids"] == ["q-phish-1"]

    incidents = await api.get("/api/phishing/incidents", headers=a["admin_headers"])
    assert incidents.status_code == 200, incidents.text
    assert incidents.json()["items"][0]["domain"] == "github-verify-login.com"

    tenant_alerts = await api.get("/api/alerts/logs", headers=a["admin_headers"])
    tenant_rows = tenant_alerts.json().get("alerts", tenant_alerts.json()) if isinstance(tenant_alerts.json(), dict) else tenant_alerts.json()
    assert any("Phishing" in (row.get("message") or "") for row in tenant_rows)

    other_alerts = await api.get("/api/alerts/logs", headers=b_headers)
    other_rows = other_alerts.json().get("alerts", other_alerts.json()) if isinstance(other_alerts.json(), dict) else other_alerts.json()
    assert not any("github-verify-login.com" in (row.get("details") or "") for row in other_rows)


async def test_batch_browser_duplicate_event_id_is_deduplicated(api, seed_enrolled_machine, db):
    a = await seed_enrolled_machine(api, slug_prefix="browser-dedup")
    payload = _browser_payload(a["machine_id"])
    payload["event_id"] = f"evt-{uuid.uuid4().hex[:10]}"

    set_tenant_context(a["tenant"]["id"])
    try:
        before_count = db.count_browser_history(a["machine_id"])
    finally:
        clear_tenant_context()

    batch = await api.post(
        "/api/activity/batch",
        json={
            "machine_id": a["machine_id"],
            "events": [
                {"queue_id": "q-browser-1", "event_type": "browser", "data": payload},
                {"queue_id": "q-browser-2", "event_type": "browser", "data": dict(payload)},
            ],
        },
        headers=AGENT_KEY_HEADER,
    )
    assert batch.status_code == 200, batch.text
    assert batch.json()["processed"] == 2

    set_tenant_context(a["tenant"]["id"])
    try:
        after_count = db.count_browser_history(a["machine_id"])
        assert after_count == before_count + 1
    finally:
        clear_tenant_context()


async def test_network_activity_rejects_excessive_connections_with_reason(api, seed_enrolled_machine):
    a = await seed_enrolled_machine(api, slug_prefix="network-cap")
    payload = {
        "machine_id": a["machine_id"],
        "timestamp": _now_iso(),
        "bytes_sent": 10,
        "bytes_recv": 10,
        "total_sent": 10,
        "total_recv": 10,
        "listen_count": 0,
        "conn_count": 2050,
        "listening_ports": [],
        "connections": [{"remote_ip": f"203.0.113.{i % 255}", "remote_port": 443} for i in range(2050)],
    }

    resp = await api.post("/api/activity/network", json=payload, headers=AGENT_KEY_HEADER)
    assert resp.status_code == 422, resp.text
    assert "network_connections_limit" in resp.json()["detail"]


def test_websocket_phishing_alert_activity_contract_routes_to_backend(app, make_tenant):
    tenant = make_tenant(slug=f"ws-phish-{uuid.uuid4().hex[:6]}")
    machine_id = f"m-{uuid.uuid4().hex[:8]}"

    from app.db.core import clear_tenant_context, set_tenant_context
    from database import db

    set_tenant_context(tenant["id"])
    try:
        db.upsert_machine(
            {
                "machine_id": machine_id,
                "hostname": "ws-phish-host",
                "os": "Windows",
                "os_version": "11",
                "username": "labuser",
                "ip_address": "10.0.0.55",
                "mac_address": "aa:bb:cc:11:22:33",
                "consent_given": True,
                "consent_timestamp": None,
                "first_seen": None,
                "last_seen": None,
                "agent_version": "1.0.0-test",
            }
        )
    finally:
        clear_tenant_context()

    with TestClient(app) as client:
        with client.websocket_connect(
            f"/ws/agent/{machine_id}",
            headers={"X-CropPro-Agent-Key": "test-agent-key"},
        ) as ws:
            ws.send_json({"type": "phishing_alert_activity", **_phishing_payload(machine_id, domain="okta-authenticate-secure.com")})
            ws.send_json({"type": "heartbeat", **_heartbeat_payload(machine_id)})
            ack = ws.receive_json()
            assert ack["type"] == "ack"

    set_tenant_context(tenant["id"])
    try:
        rows = db.list_phishing_events(limit=20, offset=0)
        assert any(row.get("domain") == "okta-authenticate-secure.com" for row in rows)
    finally:
        clear_tenant_context()
