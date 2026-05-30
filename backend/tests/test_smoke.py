"""Day-1 smoke tests: prove the fixtures + FastAPI app + Postgres wiring work.

These are intentionally thin. Their job is to fail loudly if the test harness
itself is broken, not to cover behavior. Real behavioral tests land from
Day 2 onward (test_auth.py, test_permissions.py, test_tenant_isolation.py).
"""

import pytest

pytestmark = pytest.mark.integration


async def test_app_boots_and_openapi_is_reachable(api):
    """Sanity: the FastAPI app mounts, routes are registered, OpenAPI serves."""
    resp = await api.get("/openapi.json")
    assert resp.status_code == 200
    spec = resp.json()
    # A handful of known routes must be present — catches accidental router
    # un-registration (like the JSONResponse import bug we fixed earlier).
    paths = spec.get("paths", {})
    assert "/api/auth/login" in paths
    assert "/api/machines" in paths
    assert "/api/tenants" in paths


async def test_default_tenant_exists(default_tenant):
    """The per-test _clean_db fixture must reseed tenant id=1."""
    assert default_tenant["id"] == 1
    assert default_tenant["slug"] == "default"
    assert default_tenant["status"] == "active"


async def test_make_tenant_factory_isolates_rows(make_tenant, db):
    """Factories create real rows and rows disappear between tests."""
    t1 = make_tenant(slug="acme")
    t2 = make_tenant(slug="globex")
    assert t1["id"] != t2["id"]
    assert t1["slug"] == "acme"
    assert t2["slug"] == "globex"
    # Default + 2 freshly created = 3
    assert db.count_tenants() == 3


async def test_make_user_can_login(api, make_user):
    """End-to-end: factory creates a user, we log in, we get a JWT back."""
    user = make_user(username="alice", password="S3cret-Pass!", role="admin")

    resp = await api.post(
        "/api/auth/login",
        data={"username": user["username"], "password": user["password"]},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "access_token" in body
    assert body.get("token_type", "").lower() == "bearer"


async def test_auth_headers_fixture_unlocks_protected_route(api, auth_headers):
    """The auth_headers factory produces headers that satisfy require_permission."""
    headers = await auth_headers(role="admin")
    resp = await api.get("/api/auth/me", headers=headers)
    assert resp.status_code == 200
    me = resp.json()
    assert me.get("role") == "admin"


async def test_protected_route_rejects_missing_token(api):
    """Negative sanity: no token = 401, not 200 or 500."""
    resp = await api.get("/api/auth/me")
    assert resp.status_code == 401
