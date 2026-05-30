from __future__ import annotations

import asyncio
import base64
import uuid

import pytest

from app.analytics_pipeline import analytics_pipeline
from app.core import agent_public_config
from app.db.core import clear_tenant_context, set_tenant_context
from app.event_bus import EventTopics, internal_event_bus

pytestmark = pytest.mark.integration


AGENT_KEY_HEADER = {"X-CropPro-Agent-Key": "test-agent-key"}


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _register_payload(machine_id: str) -> dict:
    return {
        "machine_id": machine_id,
        "hostname": "nextgen-host",
        "os": "Windows",
        "os_version": "11",
        "username": "labuser",
        "ip_address": "10.0.0.50",
        "mac_address": "aa:bb:cc:dd:ee:50",
        "consent_given": True,
        "consent_timestamp": _now_iso(),
        "first_seen": _now_iso(),
        "agent_version": "1.0.0-test",
    }


def _heartbeat_payload(machine_id: str) -> dict:
    return {
        "machine_id": machine_id,
        "timestamp": _now_iso(),
        "cpu_percent": 10.0,
        "memory_percent": 30.0,
        "active_app": "chrome.exe",
        "idle_seconds": 0,
    }


def _browser_payload(machine_id: str) -> dict:
    return {
        "machine_id": machine_id,
        "timestamp": _now_iso(),
        "browser": "chrome",
        "url": "https://example.com/nextgen",
        "title": "NextGen",
        "domain": "example.com",
        "duration_seconds": 4,
        "event_id": f"evt-{uuid.uuid4().hex[:8]}",
    }


def _screenshot_payload(machine_id: str) -> dict:
    return {
        "machine_id": machine_id,
        "timestamp": _now_iso(),
        "image_data": base64.b64encode(b"nextgen-screenshot").decode("ascii"),
        "trigger": "manual",
        "event_id": f"evt-{uuid.uuid4().hex[:8]}",
    }


async def test_edge_middleware_adds_request_and_trace_headers(api):
    resp = await api.get("/_internal/health/live")
    assert resp.status_code == 200
    assert resp.headers.get("X-Request-ID")
    assert resp.headers.get("X-Trace-ID")


async def test_internal_ready_requires_service_token(api, monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "internal-secret")

    denied = await api.get("/_internal/health/ready")
    assert denied.status_code == 401

    ok = await api.get(
        "/_internal/health/ready",
        headers={
            "X-Internal-Service": "gateway",
            "X-Internal-Service-Token": "internal-secret",
        },
    )
    assert ok.status_code == 200
    body = ok.json()
    assert body["service"] == "gateway"
    assert "event_bus" in body
    assert "analytics_pipeline" in body
    assert "backup" in body
    assert "agent-control" in body["internal_services"]


async def test_internal_service_catalog_and_health(api, monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "internal-secret")
    headers = {
        "X-Internal-Service": "gateway",
        "X-Internal-Service-Token": "internal-secret",
    }

    catalog = await api.get("/_internal/services", headers=headers)
    assert catalog.status_code == 200, catalog.text
    payload = catalog.json()
    assert payload["caller"] == "gateway"
    assert {"agent-control", "monitoring", "realtime"} <= set(payload["services"].keys())

    health = await api.get("/_internal/services/realtime/health", headers=headers)
    assert health.status_code == 200, health.text
    health_body = health.json()
    assert health_body["service"]["internal_prefix"] == "/_internal/services/realtime"
    assert "ws_routes" in health_body["realtime"]


async def test_heartbeat_config_exposes_nextgen_protocol(api, make_tenant):
    tenant = make_tenant(slug="nextgen-tenant")
    machine_id = f"m-{uuid.uuid4().hex[:8]}"

    registered = await api.post(
        "/api/machines/register",
        json=_register_payload(machine_id),
        headers={**AGENT_KEY_HEADER, "X-CropPro-Enroll-Token": tenant["enrollment_token"]},
    )
    assert registered.status_code == 200, registered.text

    heartbeat = await api.post(
        "/api/activity/heartbeat",
        json=_heartbeat_payload(machine_id),
        headers={**AGENT_KEY_HEADER, "X-CropPro-Enroll-Token": tenant["enrollment_token"]},
    )
    assert heartbeat.status_code == 200, heartbeat.text
    config = heartbeat.json()["config"]
    assert config["schema_version"] == 1
    assert config["agent_protocol"]["schema_version"] == 1
    assert config["agent_protocol"]["capabilities"]["config_push"] is True
    assert "/ws/agent/{machine_id}" == config["agent_protocol"]["paths"]["agent_ws"]


async def test_activity_ingest_publishes_internal_event(api, make_tenant, monkeypatch):
    tenant = make_tenant(slug="event-publish-tenant")
    machine_id = f"m-{uuid.uuid4().hex[:8]}"
    calls = []

    def _capture(**kwargs):
        calls.append(kwargs)

    monkeypatch.setattr(internal_event_bus, "publish", _capture)

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
    assert calls, "Expected internal event bus publish from browser ingest"
    assert calls[0]["topic"] == EventTopics.ACTIVITY_LOGS
    assert calls[0]["event_type"] == "activity.browser.ingested"
    assert calls[0]["tenant_id"] == tenant["id"]


async def test_screenshot_quota_gc_runs_in_background_worker(api, make_tenant, monkeypatch):
    tenant = make_tenant(slug="screenshot-worker-tenant")
    machine_id = f"m-{uuid.uuid4().hex[:8]}"
    calls = []

    monkeypatch.setenv("SCREENSHOT_QUOTA_SAMPLE", "1")

    def _capture_gc(tenant_id, max_bytes):
        calls.append((tenant_id, max_bytes))
        return 0

    monkeypatch.setattr("database.db.enforce_screenshot_quota", _capture_gc)

    registered = await api.post(
        "/api/machines/register",
        json=_register_payload(machine_id),
        headers={**AGENT_KEY_HEADER, "X-CropPro-Enroll-Token": tenant["enrollment_token"]},
    )
    assert registered.status_code == 200, registered.text

    response = await api.post(
        "/api/activity/screenshot",
        json=_screenshot_payload(machine_id),
        headers={**AGENT_KEY_HEADER, "X-CropPro-Enroll-Token": tenant["enrollment_token"]},
    )
    assert response.status_code == 200, response.text

    for _ in range(20):
        if calls:
            break
        await asyncio.sleep(0.05)
    assert calls
    assert calls[0][0] == tenant["id"]


async def test_internal_agent_control_and_monitoring_routes(api, make_tenant, monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "internal-secret")
    tenant = make_tenant(slug="internal-svc-tenant")
    machine_id = f"m-{uuid.uuid4().hex[:8]}"
    headers = {
        "X-Internal-Service": "gateway",
        "X-Internal-Service-Token": "internal-secret",
        "X-CropPro-Enroll-Token": tenant["enrollment_token"],
    }

    registered = await api.post(
        "/_internal/services/agent-control/machines/register",
        json=_register_payload(machine_id),
        headers=headers,
    )
    assert registered.status_code == 200, registered.text

    heartbeat = await api.post(
        "/_internal/services/agent-control/machines/heartbeat",
        json=_heartbeat_payload(machine_id),
        headers=headers,
    )
    assert heartbeat.status_code == 200, heartbeat.text
    assert heartbeat.json()["config"]["schema_version"] == 1

    browser = await api.post(
        "/_internal/services/monitoring/ingest/browser",
        json=_browser_payload(machine_id),
        headers=headers,
    )
    assert browser.status_code == 200, browser.text

    config = await api.get(
        f"/_internal/services/agent-control/machines/{machine_id}/config",
        headers=headers,
    )
    assert config.status_code == 200, config.text
    assert config.json()["online"] is False


def test_agent_public_config_contains_protocol_contract(db):
    set_tenant_context(1)
    try:
        cfg = agent_public_config()
    finally:
        clear_tenant_context()
    assert cfg["schema_version"] == 1
    assert cfg["agent_protocol"]["event_envelope_version"] == 1
    assert "http_fallback" in cfg["agent_protocol"]["transport"]
