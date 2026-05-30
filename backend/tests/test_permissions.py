"""Day-3 permission matrix tests.

Proves that every ``require_permission(...)`` decorator in the API blocks the
roles it should and admits the roles it should, and that every
``require_feature(...)`` gate returns 402 when the license lacks the feature.

How this works
--------------
* ``ENDPOINTS`` is a table of (method, path, required_permission). We iterate
  all 4 product roles against every row; the ROLE_PERMISSIONS mapping in
  ``app.core`` is the source of truth for the expected outcome.
* Rows where the endpoint takes path parameters (e.g. ``/api/users/{id}``)
  use a seeded fixture ID so the auth check runs before any 404 path.
* The tests assert *only* that the permission gate fires correctly — they do
  NOT care whether the handler then returns 200/404/422. A 403 on a permitted
  role would be the bug we're hunting; a 422 on a permitted role is fine
  because it means auth passed and validation then kicked in.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from app.core import ROLE_PERMISSIONS

pytestmark = pytest.mark.integration


# ---------------------------------------------------------------------------
# Endpoint × permission matrix. Keep narrowly focused: one row per *distinct*
# permission string in the codebase, plus a couple of multi-permission probes.
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Endpoint:
    method: str
    path: str
    permission: str
    # Optional JSON body / form payload for POST/PUT so validation doesn't
    # short-circuit before the auth check completes.
    body: Optional[dict] = None


ENDPOINTS = [
    # machines
    Endpoint("GET", "/api/machines", "machines.view"),
    # activity / logs
    Endpoint("GET", "/api/files", "activity.view"),
    Endpoint("GET", "/api/network", "activity.view"),
    Endpoint("GET", "/api/dlp/events", "activity.view"),
    # analytics / productivity
    Endpoint("GET", "/api/analytics/overview", "analytics.view"),
    Endpoint("GET", "/api/analytics/productivity-logs", "productivity.view"),
    # screenshots
    Endpoint("GET", "/api/screenshots/m-test", "screenshots.view"),
    # alerts
    Endpoint("GET", "/api/alerts/rules", "alerts.view"),
    Endpoint("GET", "/api/alerts/logs", "alerts.view"),
    Endpoint("POST", "/api/alerts/logs/1/acknowledge", "alerts.manage"),
    # reports (separately also feature-gated — tested below)
    Endpoint("GET", "/api/reports/generate/m-test", "reports.generate"),
    # settings / license
    Endpoint("GET", "/api/settings", "settings.view"),
    Endpoint("GET", "/api/audit-logs", "settings.view"),
    Endpoint("GET", "/api/files/vault", "settings.view"),
    # users
    Endpoint("GET", "/api/users", "users.view"),
    Endpoint("POST", "/api/users", "users.manage", body={
        "username": "new-user", "password": "Passw0rd!Test",
        "display_name": "X", "role": "viewer",
    }),
]


ROLES = ["admin", "manager", "viewer", "remote_operator"]


async def _call(api, ep: Endpoint, headers: dict):
    if ep.method == "GET":
        return await api.get(ep.path, headers=headers)
    if ep.method == "POST":
        return await api.post(ep.path, json=ep.body or {}, headers=headers)
    if ep.method == "PUT":
        return await api.put(ep.path, json=ep.body or {}, headers=headers)
    if ep.method == "DELETE":
        return await api.delete(ep.path, headers=headers)
    raise AssertionError(f"unsupported method: {ep.method}")


# ---------------------------------------------------------------------------
# Core matrix test — parametrized across every (role, endpoint) pair.
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", ROLES)
@pytest.mark.parametrize("ep", ENDPOINTS, ids=lambda e: f"{e.method}:{e.path}:{e.permission}")
async def test_permission_matrix(api, auth_headers, role, ep):
    """Every (role × endpoint) pair must obey ROLE_PERMISSIONS."""
    headers = await auth_headers(role=role)
    role_perms = ROLE_PERMISSIONS.get(role, set())
    expected_allowed = ep.permission in role_perms

    resp = await _call(api, ep, headers)

    if expected_allowed:
        # Anything EXCEPT 403 is acceptable — 200/404/422/500 all mean the
        # permission gate let the request through to the handler.
        assert resp.status_code != 403, (
            f"{role} should be permitted for {ep.permission} "
            f"({ep.method} {ep.path}) but got 403: {resp.text}"
        )
    else:
        assert resp.status_code == 403, (
            f"{role} should be blocked for {ep.permission} "
            f"({ep.method} {ep.path}) but got {resp.status_code}: {resp.text}"
        )
        assert "Permission denied" in resp.json().get("detail", "")


# ---------------------------------------------------------------------------
# Platform admin gate — require_platform_admin is not in ROLE_PERMISSIONS;
# it's enforced inline (role==admin AND tenant_id==1).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("role", ["manager", "viewer", "remote_operator"])
async def test_platform_admin_endpoint_rejects_non_admin_roles(api, auth_headers, role):
    headers = await auth_headers(role=role)
    resp = await api.get("/api/tenants", headers=headers)
    assert resp.status_code == 403


async def test_platform_admin_endpoint_rejects_admin_of_non_default_tenant(
    api, auth_headers, make_tenant
):
    """A tenant admin on tenant_id != 1 must not reach platform endpoints."""
    t = make_tenant(slug="acme-co")
    headers = await auth_headers(role="admin", tenant_id=t["id"])

    resp = await api.get("/api/tenants", headers=headers)
    assert resp.status_code == 403
    assert "platform" in resp.json()["detail"].lower()


async def test_platform_admin_endpoint_admits_default_tenant_admin(api, auth_headers):
    headers = await auth_headers(role="admin", tenant_id=1)
    resp = await api.get("/api/tenants", headers=headers)
    assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Feature gates — require_feature returns 402 when license lacks the feature.
#
# In test mode app.state.license is None → has_feature() returns True for
# everything (dev-unlocked). To exercise the 402 path we install a stub
# license object that reports "no features available" for the duration of
# the test.
# ---------------------------------------------------------------------------
class _NoFeaturesLicense:
    def has_feature(self, name: str) -> bool:  # noqa: D401
        return False


@pytest.fixture
def no_features_license(app):
    original = getattr(app.state, "license", None)
    app.state.license = _NoFeaturesLicense()
    try:
        yield
    finally:
        app.state.license = original


async def test_require_feature_reports_returns_402_when_not_licensed(
    api, auth_headers, no_features_license
):
    """/api/reports/generate is gated by require_feature('reports')."""
    headers = await auth_headers(role="admin")
    resp = await api.get("/api/reports/generate/m-test", headers=headers)
    assert resp.status_code == 402
    assert "license" in resp.json()["detail"].lower()


async def test_require_feature_audit_export_returns_402_when_not_licensed(
    api, auth_headers, no_features_license
):
    """/api/audit-logs/export is gated by require_feature('audit_export')."""
    headers = await auth_headers(role="admin")
    resp = await api.get("/api/audit-logs/export?format=csv", headers=headers)
    assert resp.status_code == 402


async def test_require_feature_alerts_returns_402_when_not_licensed(
    api, auth_headers, no_features_license
):
    """POST /api/alerts/rules is gated by require_feature('alerts')."""
    headers = await auth_headers(role="admin")
    resp = await api.post(
        "/api/alerts/rules",
        json={
            "name": "Test Rule", "rule_type": "system",
            "condition": "cpu_percent_gt", "threshold": "99",
            "severity": "high", "enabled": True,
        },
        headers=headers,
    )
    assert resp.status_code == 402


async def test_require_feature_remote_access_returns_402_when_not_licensed(
    api, auth_headers, no_features_license
):
    """POST /api/remote/command is gated by require_feature('remote_access')."""
    headers = await auth_headers(role="admin")
    resp = await api.post(
        "/api/remote/command",
        json={"machine_id": "m-test", "command": "lock"},
        headers=headers,
    )
    assert resp.status_code == 402


# ---------------------------------------------------------------------------
# Sanity checks on the role matrix itself — catch regressions where someone
# accidentally grants a permission to too broad a role.
# ---------------------------------------------------------------------------
def test_only_admin_has_settings_edit():
    assert "settings.edit" in ROLE_PERMISSIONS["admin"]
    for role in ("manager", "viewer", "remote_operator"):
        assert "settings.edit" not in ROLE_PERMISSIONS[role], (
            f"settings.edit must not leak to {role}"
        )


def test_only_admin_has_user_management():
    assert "users.manage" in ROLE_PERMISSIONS["admin"]
    for role in ("manager", "viewer", "remote_operator"):
        assert "users.manage" not in ROLE_PERMISSIONS[role]


def test_viewer_cannot_manage_alerts_or_remote():
    viewer = ROLE_PERMISSIONS["viewer"]
    assert "alerts.manage" not in viewer
    assert "remote.access" not in viewer
    assert "settings.edit" not in viewer


def test_remote_operator_has_remote_but_not_manage():
    ro = ROLE_PERMISSIONS["remote_operator"]
    assert "remote.access" in ro
    assert "alerts.manage" not in ro
    assert "users.manage" not in ro
