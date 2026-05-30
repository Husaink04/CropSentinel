"""Day-4 tenant isolation tests — the most critical file in this suite.

Every test here simulates a cross-tenant attack: Tenant A's admin logs in and
attempts to read, modify, or delete data that belongs to Tenant B. If any test
fails, treat it as a P0 — Sprint 2 priority shifts to fixing the leak before
continuing to Day 5.

How isolation is supposed to work
---------------------------------
1. A user's JWT carries their ``tenant_id`` claim.
2. ``tenant_context_middleware`` reads that claim and calls
   ``set_tenant_context(tenant_id)`` (a ContextVar).
3. Every tenant-scoped DB method reads the ContextVar via ``get_tenant_id()``
   (aliased ``_tid()``) and adds ``WHERE tenant_id = %s`` to its query.

So a Tenant-A admin hitting ``GET /api/machines`` *must* see only A's rows,
and hitting ``GET /api/machines/<B-machine>`` *must* get 404 — because from
A's perspective that machine does not exist in their tenant.
"""

from __future__ import annotations

import uuid
from typing import Callable

import pytest

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Seeding helpers. Because DB methods read tenant_id from a ContextVar, we
# temporarily set that context, insert, then clear it.
# ---------------------------------------------------------------------------
@pytest.fixture
def seed_machine(db) -> Callable:
    from app.db.core import clear_tenant_context, set_tenant_context

    def _seed(tenant_id: int, machine_id: str | None = None, **overrides) -> str:
        machine_id = machine_id or f"m-{uuid.uuid4().hex[:8]}"
        set_tenant_context(tenant_id)
        try:
            db.upsert_machine({
                "machine_id":        machine_id,
                "hostname":          overrides.get("hostname", f"host-{machine_id}"),
                "os":                overrides.get("os", "Windows"),
                "os_version":        overrides.get("os_version", "10"),
                "username":          overrides.get("username", "test-user"),
                "ip_address":        overrides.get("ip_address", "10.0.0.1"),
                "mac_address":       overrides.get("mac_address", "00:11:22:33:44:55"),
                "consent_given":     overrides.get("consent_given", True),
                "consent_timestamp": None,
                "first_seen":        None,
                "last_seen":         None,
                "agent_version":     "1.0.0",
            })
        finally:
            clear_tenant_context()
        return machine_id

    return _seed


@pytest.fixture
def seed_file_activity(db) -> Callable:
    from app.db.core import clear_tenant_context, set_tenant_context

    def _seed(tenant_id: int, machine_id: str, file_path: str = "C:/secret.docx"):
        set_tenant_context(tenant_id)
        try:
            db.insert_file_activity({
                "machine_id": machine_id,
                "timestamp":  None,
                "file_path":  file_path,
                "file_name":  file_path.rsplit("/", 1)[-1],
                "file_ext":   ".docx",
                "file_size":  1024,
                "action":     "create",
                "process":    "word.exe",
            })
        finally:
            clear_tenant_context()

    return _seed


@pytest.fixture
def seed_alert_log(db) -> Callable:
    from app.db.core import clear_tenant_context, set_tenant_context

    def _seed(tenant_id: int, machine_id: str, message: str = "Test alert"):
        set_tenant_context(tenant_id)
        try:
            return db.create_alert_log({
                "rule_id":   0,
                "rule_name": "Test",
                "machine_id": machine_id,
                "hostname":  "host",
                "severity":  "warning",
                "message":   message,
                "details":   "",
            })
        finally:
            clear_tenant_context()

    return _seed


@pytest.fixture
async def two_tenants(make_tenant, make_user, auth_headers, seed_machine):
    """Set up two isolated tenants, each with an admin + a machine.

    Returns a dict so tests can reference ``ctx['a']['headers']``,
    ``ctx['b']['machine_id']``, etc. without tuple unpacking sprawl.
    """
    tenant_a = make_tenant(slug="tenant-a")
    tenant_b = make_tenant(slug="tenant-b")

    make_user(tenant_id=tenant_a["id"], username="admin-a",
              password="Passw0rd!Test", role="admin")
    make_user(tenant_id=tenant_b["id"], username="admin-b",
              password="Passw0rd!Test", role="admin")

    headers_a = await auth_headers(role="admin", tenant_id=tenant_a["id"],
                                   username=f"a-{uuid.uuid4().hex[:6]}")
    headers_b = await auth_headers(role="admin", tenant_id=tenant_b["id"],
                                   username=f"b-{uuid.uuid4().hex[:6]}")

    machine_a = seed_machine(tenant_a["id"], machine_id="m-tenant-a")
    machine_b = seed_machine(tenant_b["id"], machine_id="m-tenant-b")

    return {
        "a": {"tenant": tenant_a, "headers": headers_a, "machine_id": machine_a},
        "b": {"tenant": tenant_b, "headers": headers_b, "machine_id": machine_b},
    }


# ═══════════════════════════════════════════════════════════════════════════
# 1. Machines — list, read, update, delete
# ═══════════════════════════════════════════════════════════════════════════
async def test_machines_list_only_returns_own_tenant(api, two_tenants):
    resp = await api.get("/api/machines", headers=two_tenants["a"]["headers"])
    assert resp.status_code == 200
    machine_ids = [m["machine_id"] for m in resp.json()]
    assert two_tenants["a"]["machine_id"] in machine_ids
    assert two_tenants["b"]["machine_id"] not in machine_ids, (
        "LEAK: Tenant A can see Tenant B's machine in the list endpoint"
    )


async def test_machine_detail_cross_tenant_returns_404(api, two_tenants):
    """Tenant A asking for Tenant B's machine by ID must get 404, not 200."""
    resp = await api.get(
        f"/api/machines/{two_tenants['b']['machine_id']}",
        headers=two_tenants["a"]["headers"],
    )
    assert resp.status_code == 404, (
        f"LEAK: Tenant A reached Tenant B's machine detail: {resp.status_code} {resp.text}"
    )


async def test_machine_update_cross_tenant_returns_404(api, two_tenants):
    resp = await api.put(
        f"/api/machines/{two_tenants['b']['machine_id']}",
        json={"hostname": "hacked"},
        headers=two_tenants["a"]["headers"],
    )
    assert resp.status_code == 404, (
        "LEAK: Tenant A was able to update Tenant B's machine"
    )


async def test_machine_delete_cross_tenant_returns_404(api, two_tenants, db):
    """Most dangerous leak: must not be able to delete another tenant's data."""
    target = two_tenants["b"]["machine_id"]
    resp = await api.delete(
        f"/api/machines/{target}",
        headers=two_tenants["a"]["headers"],
    )
    assert resp.status_code == 404, "LEAK: cross-tenant machine delete succeeded"

    # Prove the machine still exists under Tenant B.
    from app.db.core import clear_tenant_context, set_tenant_context
    set_tenant_context(two_tenants["b"]["tenant"]["id"])
    try:
        assert db.get_machine(target) is not None, (
            "CATASTROPHIC LEAK: Tenant B's machine was deleted by Tenant A"
        )
    finally:
        clear_tenant_context()


# ═══════════════════════════════════════════════════════════════════════════
# 2. Activity logs (files / network / DLP)
# ═══════════════════════════════════════════════════════════════════════════
async def test_file_activity_scoped_to_tenant(api, two_tenants, seed_file_activity):
    seed_file_activity(two_tenants["b"]["tenant"]["id"],
                       two_tenants["b"]["machine_id"],
                       file_path="C:/tenant-b-secret.docx")

    resp = await api.get("/api/files?limit=500", headers=two_tenants["a"]["headers"])
    assert resp.status_code == 200
    files = resp.json().get("files", [])
    leaked = [f for f in files if "tenant-b-secret" in (f.get("file_path") or "")]
    assert not leaked, f"LEAK: Tenant A saw {len(leaked)} of Tenant B's files"


async def test_file_activity_filter_by_other_tenant_machine_returns_empty(
    api, two_tenants, seed_file_activity,
):
    """Even if A knows B's machine_id and passes it as a filter, nothing leaks."""
    seed_file_activity(two_tenants["b"]["tenant"]["id"],
                       two_tenants["b"]["machine_id"])

    resp = await api.get(
        f"/api/files?machine_id={two_tenants['b']['machine_id']}&limit=500",
        headers=two_tenants["a"]["headers"],
    )
    assert resp.status_code == 200
    assert resp.json().get("files", []) == [], (
        "LEAK: Tenant A retrieved Tenant B's file activity via machine_id filter"
    )


async def test_network_activity_scoped_to_tenant(api, two_tenants):
    resp = await api.get("/api/network?limit=500", headers=two_tenants["a"]["headers"])
    assert resp.status_code == 200
    logs = resp.json().get("logs", [])
    for row in logs:
        # Tenant A should only ever see their own machines here.
        assert row.get("machine_id") != two_tenants["b"]["machine_id"]


async def test_dlp_events_scoped_to_tenant(api, two_tenants):
    resp = await api.get("/api/dlp/events?limit=500", headers=two_tenants["a"]["headers"])
    assert resp.status_code == 200
    events = resp.json().get("events", [])
    for ev in events:
        assert ev.get("machine_id") != two_tenants["b"]["machine_id"]


async def test_phishing_events_scoped_to_tenant(api, two_tenants):
    ingest = await api.post(
        "/api/activity/phishing",
        json={
            "machine_id": two_tenants["b"]["machine_id"],
            "timestamp": "2026-04-26T10:00:00+00:00",
            "event_type": "browser_visit",
            "channel": "browser",
            "url": "https://login-microsoftonline-security.com/login",
            "domain": "login-microsoftonline-security.com",
            "page_title": "Sign in to continue",
            "app_name": "Chrome",
            "process_name": "chrome.exe",
            "remote_ip": "203.0.113.44",
            "actor_username": "tenant-b-user",
        },
        headers={"X-CropPro-Agent-Key": "test-agent-key"},
    )
    assert ingest.status_code == 200, ingest.text
    resp = await api.get("/api/phishing/events?limit=500", headers=two_tenants["a"]["headers"])
    assert resp.status_code == 200
    events = resp.json().get("events", [])
    for ev in events:
        assert ev.get("machine_id") != two_tenants["b"]["machine_id"]


async def test_phishing_incidents_scoped_to_tenant(api, two_tenants):
    ingest = await api.post(
        "/api/activity/phishing",
        json={
            "machine_id": two_tenants["b"]["machine_id"],
            "timestamp": "2026-04-26T10:00:05+00:00",
            "event_type": "browser_visit",
            "channel": "browser",
            "url": "https://github-verify-login.com/login",
            "domain": "github-verify-login.com",
            "page_title": "Sign in to GitHub",
            "app_name": "Chrome",
            "process_name": "chrome.exe",
            "remote_ip": "203.0.113.45",
            "actor_username": "tenant-b-user",
        },
        headers={"X-CropPro-Agent-Key": "test-agent-key"},
    )
    assert ingest.status_code == 200, ingest.text
    resp = await api.get("/api/phishing/incidents?limit=500", headers=two_tenants["a"]["headers"])
    assert resp.status_code == 200
    incidents = resp.json().get("items", [])
    for item in incidents:
        assert item.get("machine_id") != two_tenants["b"]["machine_id"]


# ═══════════════════════════════════════════════════════════════════════════
# 3. Screenshots
# ═══════════════════════════════════════════════════════════════════════════
async def test_screenshots_cross_tenant_returns_empty_or_404(api, two_tenants):
    resp = await api.get(
        f"/api/screenshots/{two_tenants['b']['machine_id']}?limit=50",
        headers=two_tenants["a"]["headers"],
    )
    # Acceptable: 200 with [] (tenant_id filter returns no rows) OR 403/404.
    assert resp.status_code in (200, 403, 404)
    if resp.status_code == 200:
        assert resp.json() == [], "LEAK: Tenant A received Tenant B's screenshots"


# ═══════════════════════════════════════════════════════════════════════════
# 4. Alerts
# ═══════════════════════════════════════════════════════════════════════════
async def test_alert_logs_scoped_to_tenant(api, two_tenants, seed_alert_log):
    seed_alert_log(two_tenants["b"]["tenant"]["id"],
                   two_tenants["b"]["machine_id"],
                   message="TENANT-B-ONLY-SIGNAL")

    resp = await api.get("/api/alerts/logs", headers=two_tenants["a"]["headers"])
    assert resp.status_code == 200
    body = resp.json()
    # /api/alerts/logs shape is implementation-dependent — accept list or dict.
    rows = body.get("alerts", body) if isinstance(body, dict) else body
    leaked = [r for r in rows if "TENANT-B-ONLY-SIGNAL" in (r.get("message") or "")]
    assert not leaked, "LEAK: Tenant A saw Tenant B's alert log rows"


async def test_alert_stats_scoped_to_tenant(api, two_tenants, seed_alert_log):
    """Counts must not aggregate across tenants."""
    for i in range(3):
        seed_alert_log(two_tenants["b"]["tenant"]["id"],
                       two_tenants["b"]["machine_id"], message=f"b-{i}")

    resp_a = await api.get("/api/alerts/stats", headers=two_tenants["a"]["headers"])
    resp_b = await api.get("/api/alerts/stats", headers=two_tenants["b"]["headers"])
    assert resp_a.status_code == 200 and resp_b.status_code == 200

    # B should see >=3 alerts, A should see 0. The exact key depends on the
    # implementation; what matters is they are not equal.
    assert resp_a.json() != resp_b.json(), (
        "LEAK: alert stats returned identical numbers for both tenants, "
        "suggesting the query is not scoped by tenant_id"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 5. Audit logs
# ═══════════════════════════════════════════════════════════════════════════
async def test_audit_logs_scoped_to_tenant(api, two_tenants):
    """Tenant A's login produced audit rows; Tenant B must not see them."""
    resp = await api.get("/api/audit-logs", headers=two_tenants["b"]["headers"])
    assert resp.status_code == 200
    body = resp.json()
    rows = body.get("logs", body) if isinstance(body, dict) else body
    leaked_usernames = {r.get("username") for r in rows}
    # Tenant-A admin usernames begin with "a-" from the fixture.
    assert not any(u and u.startswith("a-") for u in leaked_usernames), (
        f"LEAK: Tenant B's audit log contained Tenant A usernames: {leaked_usernames}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 6. Settings — a PUT from Tenant A must not touch Tenant B's config
# ═══════════════════════════════════════════════════════════════════════════
async def test_settings_update_does_not_affect_other_tenant(api, two_tenants):
    before_b = await api.get("/api/settings", headers=two_tenants["b"]["headers"])
    assert before_b.status_code == 200
    b_company_before = before_b.json().get("company_name")

    put_a = await api.put(
        "/api/settings",
        json={"company_name": "TENANT-A-RENAMED"},
        headers=two_tenants["a"]["headers"],
    )
    assert put_a.status_code in (200, 204)

    after_b = await api.get("/api/settings", headers=two_tenants["b"]["headers"])
    assert after_b.status_code == 200
    b_company_after = after_b.json().get("company_name")

    assert b_company_after == b_company_before, (
        f"LEAK: Tenant A's settings PUT mutated Tenant B's config "
        f"({b_company_before!r} → {b_company_after!r})"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 7. Users list
# ═══════════════════════════════════════════════════════════════════════════
async def test_users_list_scoped_to_tenant(api, two_tenants):
    resp = await api.get("/api/users", headers=two_tenants["a"]["headers"])
    assert resp.status_code == 200
    body = resp.json()
    rows = body.get("users", body) if isinstance(body, dict) else body
    usernames = {r.get("username") for r in rows}
    assert "admin-b" not in usernames, (
        "LEAK: Tenant A's user list exposed Tenant B's admin account"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 8. Agent bundle + platform-only routes
# ═══════════════════════════════════════════════════════════════════════════
async def test_tenant_admin_cannot_download_other_tenants_agent_bundle(api, two_tenants):
    """Agent download is a platform-admin endpoint. A tenant admin must be blocked."""
    resp = await api.post(
        f"/api/tenants/{two_tenants['b']['tenant']['id']}/download-agent",
        json={},
        headers=two_tenants["a"]["headers"],
    )
    assert resp.status_code == 403, (
        f"LEAK: non-platform admin downloaded another tenant's bundle ({resp.status_code})"
    )


async def test_tenant_admin_cannot_rotate_other_tenants_enrollment_token(api, two_tenants):
    resp = await api.post(
        f"/api/tenants/{two_tenants['b']['tenant']['id']}/rotate-token",
        headers=two_tenants["a"]["headers"],
    )
    assert resp.status_code == 403


async def test_tenant_admin_cannot_access_platform_phishing_baseline(api, two_tenants):
    resp = await api.get("/api/platform/phishing/baseline", headers=two_tenants["a"]["headers"])
    assert resp.status_code == 403


async def test_tenant_admin_cannot_delete_other_tenant(api, two_tenants, db):
    resp = await api.delete(
        f"/api/tenants/{two_tenants['b']['tenant']['id']}",
        headers=two_tenants["a"]["headers"],
    )
    assert resp.status_code == 403
    assert db.get_tenant(two_tenants["b"]["tenant"]["id"]) is not None, (
        "CATASTROPHIC LEAK: a non-platform tenant admin deleted another tenant"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 9. Positive controls — proves the seeding actually worked and the other
# tenant's admin CAN see their own data. If this fails, any "no leak" result
# above is suspect.
# ═══════════════════════════════════════════════════════════════════════════
async def test_positive_control_each_tenant_sees_own_machine(api, two_tenants):
    resp_a = await api.get("/api/machines", headers=two_tenants["a"]["headers"])
    resp_b = await api.get("/api/machines", headers=two_tenants["b"]["headers"])
    assert resp_a.status_code == 200 and resp_b.status_code == 200
    ids_a = {m["machine_id"] for m in resp_a.json()}
    ids_b = {m["machine_id"] for m in resp_b.json()}
    assert two_tenants["a"]["machine_id"] in ids_a
    assert two_tenants["b"]["machine_id"] in ids_b
