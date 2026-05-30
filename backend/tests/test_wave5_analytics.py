from __future__ import annotations

import asyncio
import uuid

import pytest

from app.analytics_pipeline import analytics_pipeline

pytestmark = pytest.mark.integration

AGENT_KEY_HEADER = {"X-CropPro-Agent-Key": "test-agent-key"}


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _register_payload(machine_id: str) -> dict:
    return {
        "machine_id": machine_id,
        "hostname": "analytics-host",
        "os": "Windows",
        "os_version": "11",
        "username": "labuser",
        "ip_address": "10.0.0.52",
        "mac_address": "aa:bb:cc:dd:ee:52",
        "consent_given": True,
        "consent_timestamp": _now_iso(),
        "first_seen": _now_iso(),
        "agent_version": "1.0.0-test",
    }


def _browser_payload(machine_id: str) -> dict:
    return {
        "machine_id": machine_id,
        "timestamp": _now_iso(),
        "browser": "chrome",
        "url": "https://example.com/clickhouse",
        "title": "ClickHouse",
        "domain": "example.com",
        "duration_seconds": 7,
        "event_id": f"evt-{uuid.uuid4().hex[:8]}",
    }


async def test_activity_events_are_enqueued_for_clickhouse_pipeline(api, make_tenant, monkeypatch):
    tenant = make_tenant(slug="analytics-pipeline-tenant")
    machine_id = f"m-{uuid.uuid4().hex[:8]}"
    analytics_pipeline.backend = "clickhouse"
    analytics_pipeline.url = "http://clickhouse.test"
    analytics_pipeline._ready = True
    analytics_pipeline._queue.clear()

    registered = await api.post(
        "/api/machines/register",
        json=_register_payload(machine_id),
        headers={**AGENT_KEY_HEADER, "X-CropPro-Enroll-Token": tenant["enrollment_token"]},
    )
    assert registered.status_code == 200, registered.text

    browser = await api.post(
        "/api/activity/browser",
        json=_browser_payload(machine_id),
        headers={**AGENT_KEY_HEADER, "X-CropPro-Enroll-Token": tenant["enrollment_token"]},
    )
    assert browser.status_code == 200, browser.text

    for _ in range(20):
        if analytics_pipeline.status()["queue_depth"] > 0:
            break
        await asyncio.sleep(0.05)
    assert analytics_pipeline.status()["queue_depth"] > 0
    analytics_pipeline._queue.clear()
    analytics_pipeline.backend = "noop"
    analytics_pipeline.url = ""
    analytics_pipeline._ready = False


async def test_overview_route_uses_clickhouse_pipeline_when_enabled(api, auth_headers, monkeypatch):
    headers = await auth_headers(role="admin", tenant_id=1)
    analytics_pipeline.backend = "clickhouse"
    analytics_pipeline.url = "http://clickhouse.test"
    analytics_pipeline._ready = True
    monkeypatch.setenv("CLICKHOUSE_ANALYTICS_READS", "1")
    monkeypatch.setattr(
        analytics_pipeline,
        "get_overview_stats",
        lambda tenant_id: {
            "total_machines": 9,
            "active_today": 4,
            "top_apps": [{"app_name": "code.exe", "total": 12}],
            "top_domains": [{"domain": "example.com", "visits": 5}],
            "daily_activity": [],
        },
    )

    resp = await api.get("/api/analytics/overview", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_machines"] == 9
    assert body["top_apps"][0]["app_name"] == "code.exe"

    analytics_pipeline.backend = "noop"
    analytics_pipeline.url = ""
    analytics_pipeline._ready = False


async def test_machine_analytics_falls_back_when_clickhouse_query_fails(api, auth_headers, make_tenant, monkeypatch):
    tenant = make_tenant(slug="analytics-fallback-tenant")
    headers = await auth_headers(role="admin", tenant_id=tenant["id"])
    machine_id = f"m-{uuid.uuid4().hex[:8]}"

    registered = await api.post(
        "/api/machines/register",
        json=_register_payload(machine_id),
        headers={**AGENT_KEY_HEADER, "X-CropPro-Enroll-Token": tenant["enrollment_token"]},
    )
    assert registered.status_code == 200, registered.text

    analytics_pipeline.backend = "clickhouse"
    analytics_pipeline.url = "http://clickhouse.test"
    analytics_pipeline._ready = True
    monkeypatch.setenv("CLICKHOUSE_ANALYTICS_READS", "1")
    monkeypatch.setattr(analytics_pipeline, "get_machine_analytics", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))

    resp = await api.get(f"/api/analytics/machine/{machine_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "app_usage" in body
    assert "browser_usage" in body

    analytics_pipeline.backend = "noop"
    analytics_pipeline.url = ""
    analytics_pipeline._ready = False
