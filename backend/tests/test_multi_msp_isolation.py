from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def _platform_login(api, username: str, password: str) -> dict:
    resp = await api.post(
        "/api/platform/login",
        data={"username": username, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


async def test_msp_platform_stats_hide_other_msp_subtenants(api, make_tenant, make_user):
    msp_a = make_tenant(slug="msp-a", name="MSP A", tier="msp", max_seats=100)
    msp_b = make_tenant(slug="msp-b", name="MSP B", tier="msp", max_seats=100)
    make_tenant(slug="acme-a", name="Acme A", parent_tenant_id=msp_a["id"])

    make_user(tenant_id=msp_a["id"], username="msp-a-admin", password="Passw0rd!Test", role="admin")
    make_user(tenant_id=msp_b["id"], username="msp-b-admin", password="Passw0rd!Test", role="admin")

    headers_b = await _platform_login(api, "msp-b-admin", "Passw0rd!Test")

    resp = await api.get("/api/platform/stats", headers=headers_b)
    assert resp.status_code == 200, resp.text
    body = resp.json()

    assert body["scope"] == "msp"
    slugs = {row["slug"] for row in body.get("tenant_list", [])}
    assert "acme-a" not in slugs, "MSP B must not see MSP A sub-tenants in platform stats"


async def test_msp_cannot_read_or_assign_users_to_other_msp_subtenant(api, make_tenant, make_user):
    msp_a = make_tenant(slug="msp-a", name="MSP A", tier="msp", max_seats=100)
    msp_b = make_tenant(slug="msp-b", name="MSP B", tier="msp", max_seats=100)
    acme_a = make_tenant(slug="acme-a", name="Acme A", parent_tenant_id=msp_a["id"])

    make_user(tenant_id=msp_b["id"], username="msp-b-admin", password="Passw0rd!Test", role="admin")
    headers_b = await _platform_login(api, "msp-b-admin", "Passw0rd!Test")

    detail = await api.get(f"/api/tenants/{acme_a['id']}", headers=headers_b)
    assert detail.status_code == 404

    create_user_resp = await api.post(
        "/api/users",
        json={
            "tenant_id": acme_a["id"],
            "username": "forbidden-cross-tenant-user",
            "password": "Passw0rd!Test",
            "display_name": "Forbidden User",
            "role": "viewer",
            "assigned_machines": [],
        },
        headers=headers_b,
    )
    assert create_user_resp.status_code == 403


async def test_msp_subtenant_seat_quota_is_enforced(api, make_tenant, make_user):
    msp = make_tenant(slug="msp-seat", name="MSP Seat", tier="msp", max_seats=100)
    make_user(tenant_id=msp["id"], username="msp-seat-admin", password="Passw0rd!Test", role="admin")
    headers = await _platform_login(api, "msp-seat-admin", "Passw0rd!Test")

    first = await api.post(
        "/api/tenants",
        json={
            "slug": "quota-a",
            "name": "Quota A",
            "customer_name": "Quota A",
            "tier": "starter",
            "max_seats": 60,
            "valid_days": 365,
            "grace_days": 14,
        },
        headers=headers,
    )
    assert first.status_code == 200, first.text

    second = await api.post(
        "/api/tenants",
        json={
            "slug": "quota-b",
            "name": "Quota B",
            "customer_name": "Quota B",
            "tier": "starter",
            "max_seats": 50,
            "valid_days": 365,
            "grace_days": 14,
        },
        headers=headers,
    )
    assert second.status_code == 402
    assert "seat quota exceeded" in second.json()["detail"].lower()
