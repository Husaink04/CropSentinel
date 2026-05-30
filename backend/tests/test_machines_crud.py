"""Day-6 machines CRUD tests.

Day 3 already proved the permission *gate* fires (403 for wrong roles).
Day 6 proves the *behavior behind the gate*:

1. **Mutation lands.** PUT /api/machines/{id} actually updates the row.
2. **Deletion lands and cascades.** DELETE removes the machine and its
   activity (FKs are ``ON DELETE CASCADE`` — we verify the contract).
3. **Cross-tenant writes are silently scoped out.** An admin of Tenant A
   calling PUT/DELETE against Tenant B's machine_id must NOT mutate B.
   The DB layer filters by ``WHERE tenant_id = _tid()``, so the handler
   sees rowcount=0 and returns 404 "Machine not found". Any behavior
   other than that is a cross-tenant write vulnerability.
4. **Per-machine viewer scoping.** A user with ``assigned_machines`` set
   to ``[m1]`` can see m1 but gets 403 on m2 (same tenant), and their
   /api/machines list only contains m1.
5. **Edge cases.** Unknown id → 404. Unknown fields silently ignored
   (whitelist). Empty/no-op update → 404 "no valid fields".
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Tuple

import pytest

from app.db.core import set_tenant_context, clear_tenant_context

pytestmark = pytest.mark.integration


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _seed_machine(db, tenant_id: int, machine_id: str, hostname: str = "host") -> None:
    """Insert a machine row under the given tenant, bypassing HTTP."""
    set_tenant_context(tenant_id)
    try:
        db.upsert_machine(
            {
                "machine_id": machine_id,
                "hostname": hostname,
                "os": "Windows",
                "os_version": "10",
                "username": "user",
                "ip_address": "10.0.0.1",
                "mac_address": "",
                "consent_given": True,
                "consent_timestamp": _now(),
                "first_seen": _now(),
                "last_seen": _now(),
                "agent_version": "1.0.0",
            }
        )
    finally:
        clear_tenant_context()


@pytest.fixture
def two_tenants_with_machines(make_tenant, make_user, db):
    """Return (A, B) fixture bundles, each with a machine + admin headers
    ready to use. Tenants are fresh so UUID-based machine ids never clash."""

    async def _factory(api):
        out = {}
        for key, slug_prefix in (("a", "mcrud-a"), ("b", "mcrud-b")):
            t = make_tenant(slug=f"{slug_prefix}-{uuid.uuid4().hex[:6]}")
            mid = f"m-{uuid.uuid4().hex[:8]}"
            _seed_machine(db, t["id"], mid, hostname=f"{key}-host")

            user = make_user(tenant_id=t["id"], role="admin")
            login = await api.post(
                "/api/auth/login",
                data={"username": user["username"], "password": user["password"]},
            )
            assert login.status_code == 200, login.text
            out[key] = {
                "tenant": t,
                "machine_id": mid,
                "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
            }
        return out

    return _factory


# ═══════════════════════════════════════════════════════════════════════════
# 1. PUT happy path
# ═══════════════════════════════════════════════════════════════════════════
async def test_admin_can_update_own_tenant_machine(api, two_tenants_with_machines, db):
    tt = await two_tenants_with_machines(api)
    a = tt["a"]

    resp = await api.put(
        f"/api/machines/{a['machine_id']}",
        json={"hostname": "renamed-host", "username": "alice"},
        headers=a["headers"],
    )
    assert resp.status_code == 200, resp.text

    set_tenant_context(a["tenant"]["id"])
    try:
        row = db.get_machine(a["machine_id"])
    finally:
        clear_tenant_context()
    assert row["hostname"] == "renamed-host"
    assert row["username"] == "alice"


async def test_update_unknown_machine_returns_404(api, auth_headers):
    headers = await auth_headers(role="admin")
    resp = await api.put(
        "/api/machines/m-does-not-exist",
        json={"hostname": "anything"},
        headers=headers,
    )
    assert resp.status_code == 404


async def test_update_with_only_non_whitelisted_fields_returns_404(
    api, two_tenants_with_machines
):
    """The handler's contract: if no whitelisted field is supplied, the
    DB method returns False and the handler returns 404 ("no valid
    fields"). This doubles as a guard against caller-supplied
    ``tenant_id`` attempting to move a machine between tenants."""
    tt = await two_tenants_with_machines(api)
    a = tt["a"]

    resp = await api.put(
        f"/api/machines/{a['machine_id']}",
        json={"tenant_id": 999, "id": 1, "created_at": "2000-01-01"},
        headers=a["headers"],
    )
    assert resp.status_code == 404


async def test_update_silently_drops_non_whitelisted_fields(
    api, two_tenants_with_machines, db
):
    """Mixing a whitelisted field with ``tenant_id`` must succeed for the
    whitelisted field but must NOT rewrite ``tenant_id``."""
    tt = await two_tenants_with_machines(api)
    a = tt["a"]
    original_tid = a["tenant"]["id"]

    resp = await api.put(
        f"/api/machines/{a['machine_id']}",
        json={"hostname": "legit-rename", "tenant_id": 99999},
        headers=a["headers"],
    )
    assert resp.status_code == 200

    # The tenant_id did not move.
    assert db.get_machine_tenant_id(a["machine_id"]) == original_tid


# ═══════════════════════════════════════════════════════════════════════════
# 2. Cross-tenant PUT must be a no-op from B's perspective
# ═══════════════════════════════════════════════════════════════════════════
async def test_admin_cannot_update_other_tenant_machine(
    api, two_tenants_with_machines, db
):
    """Tenant A admin calling PUT on B's machine must return 404 (the DB
    WHERE clause filtered it out) and B's row must be unchanged."""
    tt = await two_tenants_with_machines(api)
    a, b = tt["a"], tt["b"]

    # Capture B's current hostname.
    set_tenant_context(b["tenant"]["id"])
    try:
        before = db.get_machine(b["machine_id"])
    finally:
        clear_tenant_context()
    hostname_before = before["hostname"]

    resp = await api.put(
        f"/api/machines/{b['machine_id']}",
        json={"hostname": "PWNED-BY-A"},
        headers=a["headers"],  # Tenant A's token
    )
    assert resp.status_code == 404, (
        f"Cross-tenant PUT should return 404, got {resp.status_code}: {resp.text}"
    )

    set_tenant_context(b["tenant"]["id"])
    try:
        after = db.get_machine(b["machine_id"])
    finally:
        clear_tenant_context()
    assert after["hostname"] == hostname_before, (
        f"LEAK: Tenant A's PUT mutated Tenant B's machine "
        f"({hostname_before!r} → {after['hostname']!r})"
    )


# ═══════════════════════════════════════════════════════════════════════════
# 3. DELETE happy path + cascade
# ═══════════════════════════════════════════════════════════════════════════
async def test_admin_can_delete_own_tenant_machine(
    api, two_tenants_with_machines, db
):
    tt = await two_tenants_with_machines(api)
    a = tt["a"]

    resp = await api.delete(
        f"/api/machines/{a['machine_id']}", headers=a["headers"]
    )
    assert resp.status_code == 200
    assert a["machine_id"] in resp.json()["message"]

    set_tenant_context(a["tenant"]["id"])
    try:
        assert db.get_machine(a["machine_id"]) is None
    finally:
        clear_tenant_context()


async def test_delete_machine_cascades_activity_rows(
    api, two_tenants_with_machines, db
):
    """FK ON DELETE CASCADE: removing a machine row must remove its
    browser_activity rows. This pins the schema-level contract."""
    tt = await two_tenants_with_machines(api)
    a = tt["a"]

    # Seed one browser_activity row under A.
    set_tenant_context(a["tenant"]["id"])
    try:
        db.insert_browser_activity(
            {
                "machine_id": a["machine_id"],
                "timestamp": _now(),
                "browser": "chrome",
                "url": "https://x.test/",
                "title": "t",
                "domain": "x.test",
                "duration_seconds": 1,
            }
        )
        before = db.get_browser_history(a["machine_id"], limit=10)
        assert any(r["machine_id"] == a["machine_id"] for r in before)
    finally:
        clear_tenant_context()

    resp = await api.delete(
        f"/api/machines/{a['machine_id']}", headers=a["headers"]
    )
    assert resp.status_code == 200

    set_tenant_context(a["tenant"]["id"])
    try:
        after = db.get_browser_history(a["machine_id"], limit=10)
        assert after == [], (
            f"CASCADE FAILED: browser_activity rows still present for "
            f"deleted machine {a['machine_id']}: {after}"
        )
    finally:
        clear_tenant_context()


async def test_admin_cannot_delete_other_tenant_machine(
    api, two_tenants_with_machines, db
):
    tt = await two_tenants_with_machines(api)
    a, b = tt["a"], tt["b"]

    resp = await api.delete(
        f"/api/machines/{b['machine_id']}", headers=a["headers"]
    )
    assert resp.status_code == 404

    set_tenant_context(b["tenant"]["id"])
    try:
        assert db.get_machine(b["machine_id"]) is not None, (
            "LEAK: Tenant A's DELETE removed Tenant B's machine"
        )
    finally:
        clear_tenant_context()


async def test_delete_unknown_machine_returns_404(api, auth_headers):
    headers = await auth_headers(role="admin")
    resp = await api.delete(
        "/api/machines/m-does-not-exist", headers=headers
    )
    assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════════
# 4. /api/machines/{id}/activity — clears rows but keeps the machine
# ═══════════════════════════════════════════════════════════════════════════
async def test_delete_activity_endpoint_clears_rows_but_keeps_machine(
    api, two_tenants_with_machines, db
):
    tt = await two_tenants_with_machines(api)
    a = tt["a"]

    set_tenant_context(a["tenant"]["id"])
    try:
        db.insert_browser_activity(
            {
                "machine_id": a["machine_id"],
                "timestamp": _now(),
                "browser": "chrome",
                "url": "https://y.test/",
                "title": "t",
                "domain": "y.test",
                "duration_seconds": 1,
            }
        )
    finally:
        clear_tenant_context()

    resp = await api.delete(
        f"/api/machines/{a['machine_id']}/activity",
        headers=a["headers"],
    )
    assert resp.status_code == 200
    counts = resp.json()["counts"]
    assert counts["browser_activity"] >= 1

    set_tenant_context(a["tenant"]["id"])
    try:
        # Machine row still there.
        assert db.get_machine(a["machine_id"]) is not None
        # Activity gone.
        assert db.get_browser_history(a["machine_id"], limit=10) == []
    finally:
        clear_tenant_context()


# ═══════════════════════════════════════════════════════════════════════════
# 5. Per-machine viewer scoping (assigned_machines whitelist)
# ═══════════════════════════════════════════════════════════════════════════
@pytest.fixture
async def viewer_with_one_assigned_machine(api, make_tenant, make_user, db):
    """Seed a tenant with TWO machines, create a viewer whose
    ``assigned_machines`` = [m1]. Return the pieces needed to exercise the
    scoping logic."""
    t = make_tenant(slug=f"scoped-{uuid.uuid4().hex[:6]}")
    m1 = f"m-{uuid.uuid4().hex[:8]}"
    m2 = f"m-{uuid.uuid4().hex[:8]}"
    _seed_machine(db, t["id"], m1, hostname="assigned")
    _seed_machine(db, t["id"], m2, hostname="unassigned")

    user = make_user(tenant_id=t["id"], role="viewer")
    # update_user is tenant-scoped; set context so the UPDATE matches.
    set_tenant_context(t["id"])
    try:
        assert db.update_user(user["id"], {"assigned_machines": json.dumps([m1])})
    finally:
        clear_tenant_context()

    login = await api.post(
        "/api/auth/login",
        data={"username": user["username"], "password": user["password"]},
    )
    assert login.status_code == 200, login.text
    return {
        "headers": {"Authorization": f"Bearer {login.json()['access_token']}"},
        "allowed_machine_id": m1,
        "forbidden_machine_id": m2,
        "tenant": t,
    }


async def test_viewer_can_see_only_assigned_machine_in_list(
    api, viewer_with_one_assigned_machine
):
    v = viewer_with_one_assigned_machine
    resp = await api.get("/api/machines", headers=v["headers"])
    assert resp.status_code == 200
    ids = {m["machine_id"] for m in resp.json()}
    assert v["allowed_machine_id"] in ids
    assert v["forbidden_machine_id"] not in ids, (
        f"LEAK: viewer with assigned_machines=[{v['allowed_machine_id']!r}] "
        f"saw {v['forbidden_machine_id']!r} in their machine list"
    )


async def test_viewer_can_get_assigned_machine(
    api, viewer_with_one_assigned_machine
):
    v = viewer_with_one_assigned_machine
    resp = await api.get(
        f"/api/machines/{v['allowed_machine_id']}", headers=v["headers"]
    )
    assert resp.status_code == 200
    assert resp.json()["machine_id"] == v["allowed_machine_id"]


async def test_viewer_cannot_get_unassigned_machine_in_same_tenant(
    api, viewer_with_one_assigned_machine
):
    """Same tenant, different machine → check_machine_access raises 403."""
    v = viewer_with_one_assigned_machine
    resp = await api.get(
        f"/api/machines/{v['forbidden_machine_id']}", headers=v["headers"]
    )
    assert resp.status_code == 403
    assert "no access" in resp.json()["detail"].lower()
