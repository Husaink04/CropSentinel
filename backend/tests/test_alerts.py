from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.db.core import clear_tenant_context, set_tenant_context

pytestmark = pytest.mark.integration


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def seeded_machine(db, make_tenant):
    def _factory(slug: str = "alerts-tenant") -> dict:
        tenant = make_tenant(slug=slug)
        machine_id = f"{slug}-machine"
        set_tenant_context(tenant["id"])
        try:
            db.upsert_machine(
                {
                    "machine_id": machine_id,
                    "hostname": f"{slug}-host",
                    "os": "Windows",
                    "os_version": "11",
                    "username": "alert-user",
                    "ip_address": "10.1.1.10",
                    "mac_address": "00:11:22:33:44:66",
                    "consent_given": True,
                    "consent_timestamp": _now_iso(),
                    "first_seen": _now_iso(),
                    "last_seen": _now_iso(),
                    "agent_version": "test",
                }
            )
        finally:
            clear_tenant_context()
        return {"tenant": tenant, "machine_id": machine_id}

    return _factory


async def test_alert_rule_crud_round_trip(api, auth_headers):
    headers = await auth_headers(role="admin")
    payload = {
        "name": "CPU Spike",
        "description": "Detect high CPU",
        "rule_type": "system",
        "condition": "cpu_percent_gt",
        "threshold": "90",
        "machine_id": "all",
        "severity": "high",
        "enabled": True,
    }

    create = await api.post("/api/alerts/rules", json=payload, headers=headers)
    assert create.status_code == 200, create.text
    rule_id = create.json()["id"]

    listing = await api.get("/api/alerts/rules", headers=headers)
    assert listing.status_code == 200
    assert any(rule["id"] == rule_id and rule["name"] == "CPU Spike" for rule in listing.json())

    update = await api.put(
        f"/api/alerts/rules/{rule_id}",
        json={**payload, "threshold": "95", "description": "Updated"},
        headers=headers,
    )
    assert update.status_code == 200, update.text

    toggle = await api.patch(f"/api/alerts/rules/{rule_id}/toggle?enabled=false", headers=headers)
    assert toggle.status_code == 200, toggle.text

    refreshed = await api.get("/api/alerts/rules", headers=headers)
    rule = next(rule for rule in refreshed.json() if rule["id"] == rule_id)
    assert str(rule["threshold"]) == "95"
    assert rule["enabled"] in (False, 0)


async def test_acknowledge_alert_log_marks_it_acknowledged(api, auth_headers, db, seeded_machine):
    seeded = seeded_machine("ack-alerts")
    headers = await auth_headers(role="admin", tenant_id=seeded["tenant"]["id"])

    set_tenant_context(seeded["tenant"]["id"])
    try:
        log_id = db.create_alert_log(
            {
                "rule_id": 0,
                "rule_name": "Manual",
                "machine_id": seeded["machine_id"],
                "hostname": "ack-host",
                "severity": "warning",
                "message": "Needs acknowledgement",
                "details": "",
            }
        )
    finally:
        clear_tenant_context()

    resp = await api.post(f"/api/alerts/logs/{log_id}/acknowledge", headers=headers)
    assert resp.status_code == 200, resp.text

    logs = await api.get("/api/alerts/logs", headers=headers)
    assert logs.status_code == 200
    row = next(item for item in logs.json() if item["id"] == log_id)
    assert row["acknowledged"] is True


async def test_browser_rule_creates_alert_on_match(api, auth_headers, seeded_machine):
    seeded = seeded_machine("browser-alerts")
    headers = await auth_headers(role="admin", tenant_id=seeded["tenant"]["id"])

    create_rule = await api.post(
        "/api/alerts/rules",
        json={
            "name": "Blocked Domain",
            "description": "",
            "rule_type": "browser",
            "condition": "domain_in_blacklist",
            "threshold": "phishing.test",
            "machine_id": "all",
            "severity": "critical",
            "enabled": True,
        },
        headers=headers,
    )
    assert create_rule.status_code == 200, create_rule.text

    ingest = await api.post(
        "/api/activity/browser",
        json={
            "machine_id": seeded["machine_id"],
            "timestamp": _now_iso(),
            "browser": "chrome",
            "url": "https://phishing.test/login",
            "title": "Suspicious Login",
            "domain": "phishing.test",
            "duration_seconds": 30,
        },
        headers={"X-CropPro-Agent-Key": "test-agent-key"},
    )
    assert ingest.status_code == 200, ingest.text

    logs = await api.get("/api/alerts/logs", headers=headers)
    assert logs.status_code == 200
    assert any("phishing.test" in (row.get("message") or "") for row in logs.json())
