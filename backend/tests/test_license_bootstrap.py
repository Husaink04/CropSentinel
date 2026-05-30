from __future__ import annotations

from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.integration

AGENT_KEY_HEADER = {"X-CropPro-Agent-Key": "test-agent-key"}


async def test_bootstrap_mode_exposes_unlicensed_state(api, auth_headers, app):
    app.state.license = None
    app.state.license_bootstrap = True
    app.state.license_error = "License file not found"
    headers = await auth_headers(role="admin")

    resp = await api.get("/api/license/info", headers=headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["licensed"] is False
    assert body["bootstrap_mode"] is True
    assert "not found" in body["reason"].lower()


async def test_bootstrap_mode_blocks_feature_gated_reports(api, auth_headers, app):
    app.state.license = None
    app.state.license_bootstrap = True
    app.state.license_error = "License file not found"
    headers = await auth_headers(role="admin")

    resp = await api.get("/api/reports/generate/m-test", headers=headers)

    assert resp.status_code == 402
    assert "license" in resp.json()["detail"].lower()


async def test_bootstrap_mode_blocks_agent_registration(api, make_tenant, app):
    app.state.license = None
    app.state.license_bootstrap = True
    app.state.license_error = "License file not found"
    tenant = make_tenant(slug="bootstrap-tenant")

    resp = await api.post(
        "/api/machines/register",
        json={
            "machine_id": "m-bootstrap-1",
            "hostname": "bootstrap-host",
            "os": "Windows",
            "os_version": "11",
            "username": "bootstrap-user",
            "ip_address": "10.2.2.2",
            "mac_address": "aa:aa:aa:aa:aa:aa",
            "consent_given": True,
            "consent_timestamp": datetime.now(timezone.utc).isoformat(),
            "first_seen": datetime.now(timezone.utc).isoformat(),
            "agent_version": "test",
        },
        headers={**AGENT_KEY_HEADER, "X-CropPro-Enroll-Token": tenant["enrollment_token"]},
    )

    assert resp.status_code == 402, resp.text
    assert "license" in resp.json()["detail"].lower()
