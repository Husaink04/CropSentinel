from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.event_bus import EventEnvelope
from app.event_workers import internal_event_workers

pytestmark = pytest.mark.integration


async def test_internal_metrics_exposes_runtime_counters(api, monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "internal-secret")

    live = await api.get("/_internal/health/live")
    assert live.status_code == 200

    metrics = await api.get(
        "/_internal/metrics",
        headers={
            "X-Internal-Service": "gateway",
            "X-Internal-Service-Token": "internal-secret",
        },
    )
    assert metrics.status_code == 200, metrics.text
    body = metrics.text
    assert "cropsentinel_http_requests_total" in body
    assert 'path="/_internal/health/live"' in body
    assert "cropsentinel_event_bus_queue_depth" in body
    assert "cropsentinel_analytics_queue_depth" in body


async def test_internal_ops_status_reports_backup_runtime(api, monkeypatch, tmp_path):
    monkeypatch.setenv("INTERNAL_SERVICE_TOKEN", "internal-secret")
    status_path = tmp_path / "backup-status.json"
    status_path.write_text(
        json.dumps(
            {
                "started_at": "2026-05-12T09:00:00+00:00",
                "completed_at": "2026-05-12T09:05:00+00:00",
                "targets": {
                    "postgres": {"status": "ok", "last_success_at": "2026-05-12T09:05:00+00:00"},
                    "redis": {"status": "ok", "last_success_at": "2026-05-12T09:05:00+00:00"},
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("BACKUP_STATUS_FILE", str(status_path))

    resp = await api.get(
        "/_internal/ops/status",
        headers={
            "X-Internal-Service": "gateway",
            "X-Internal-Service-Token": "internal-secret",
        },
    )
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["backup"]["status_file"] == str(Path(status_path).resolve())
    assert payload["backup"]["targets"]["postgres"]["enabled"] is True
    assert payload["backup"]["last_success"]["postgres"] > 0
    assert "event_workers" in payload


def test_event_worker_sink_writes_jsonl(monkeypatch, tmp_path):
    monkeypatch.setenv("EVENT_SINK_DIR", str(tmp_path))
    envelope = EventEnvelope(
        event_id="evt-1",
        event_type="audit.logged",
        tenant_id=1,
        machine_id="",
        occurred_at="2026-05-12T00:00:00+00:00",
        produced_at="2026-05-12T00:00:01+00:00",
        schema_version=1,
        payload={"action": "test"},
        trace_id="trace-1",
    )
    internal_event_workers._append_sink_record("audit", envelope)
    sink = tmp_path / "audit.jsonl"
    assert sink.exists()
    lines = sink.read_text(encoding="utf-8").strip().splitlines()
    assert lines
    payload = json.loads(lines[-1])
    assert payload["event_id"] == "evt-1"
    assert payload["payload"]["action"] == "test"
