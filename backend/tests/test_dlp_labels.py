from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.db.core import clear_tenant_context, set_tenant_context

pytestmark = pytest.mark.integration

AGENT_KEY_HEADER = {"X-CropSentinel-Agent-Key": "test-agent-key"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _register_payload(machine_id: str) -> dict:
    return {
        "machine_id": machine_id,
        "hostname": "labels-host",
        "os": "Windows",
        "os_version": "11",
        "username": "labuser",
        "ip_address": "10.0.0.42",
        "mac_address": "aa:bb:cc:11:22:33",
        "consent_given": True,
        "consent_timestamp": _now_iso(),
        "first_seen": _now_iso(),
        "agent_version": "1.2.0-test",
    }


async def _enroll_machine(api, make_tenant, machine_id: str | None = None):
    tenant = make_tenant(slug=f"labels-{uuid.uuid4().hex[:6]}")
    machine_id = machine_id or f"m-{uuid.uuid4().hex[:8]}"
    resp = await api.post(
        "/api/machines/register",
        json=_register_payload(machine_id),
        headers={**AGENT_KEY_HEADER, "X-CropSentinel-Enroll-Token": tenant["enrollment_token"]},
    )
    assert resp.status_code == 200, resp.text
    return tenant, machine_id


async def test_file_activity_persists_enterprise_label_fields(api, make_tenant, db):
    tenant, machine_id = await _enroll_machine(api, make_tenant)
    resp = await api.post(
        "/api/activity/file",
        json={
            "machine_id": machine_id,
            "timestamp": _now_iso(),
            "action": "modify",
            "file_path": r"C:\Sensitive\plan.xlsx",
            "file_name": "plan.xlsx",
            "file_ext": ".xlsx",
            "file_size": 4096,
            "destination": "",
            "destination_type": "local",
            "destination_label": "local",
            "enterprise_label": "Confidential",
            "sensitivity_score": 3,
            "label_source": "content_inspection",
            "label_reason": "credit_card detected",
            "block_candidate": True,
            "block_reason": "Confidential file modify detected",
            "blocking_supported": False,
            "blocking_mode": "detect_only",
        },
        headers=AGENT_KEY_HEADER,
    )
    assert resp.status_code == 200, resp.text

    set_tenant_context(tenant["id"])
    try:
        rows = db.get_file_activity(machine_id=machine_id, limit=5, offset=0)
        assert rows
        row = rows[0]
        assert row["enterprise_label"] == "Confidential"
        assert row["sensitivity_score"] == 3
        assert row["block_candidate"] is True
        assert row["blocking_mode"] == "detect_only"
    finally:
        clear_tenant_context()


async def test_dlp_event_persists_enterprise_label_fields(api, make_tenant, db):
    tenant, machine_id = await _enroll_machine(api, make_tenant)
    resp = await api.post(
        "/api/dlp/events",
        json={
            "machine_id": machine_id,
            "timestamp": _now_iso(),
            "file_path": r"C:\Sensitive\keys.txt",
            "file_name": "keys.txt",
            "file_ext": ".txt",
            "file_size": 512,
            "risk_level": "high",
            "risk_score": 18,
            "findings": [{"type": "api_key", "count": 1}],
            "file_hash": "hash-key-1",
            "destination": "local",
            "device": "",
            "is_known_sensitive": False,
            "scoring": {"total_score": 18},
            "destination_type": "local",
            "destination_label": "local",
            "content_fingerprint": "hash-key-1",
            "enterprise_label": "Highly Confidential",
            "sensitivity_score": 4,
            "label_source": "content_inspection",
            "label_reason": "api_key detected",
            "block_candidate": True,
            "block_reason": "Highly Confidential file modify detected",
            "blocking_supported": False,
            "blocking_mode": "detect_only",
        },
        headers=AGENT_KEY_HEADER,
    )
    assert resp.status_code == 200, resp.text

    set_tenant_context(tenant["id"])
    try:
        rows = db.get_dlp_events(machine_id=machine_id, limit=5, offset=0)
        assert rows
        row = rows[0]
        assert row["enterprise_label"] == "Highly Confidential"
        assert row["sensitivity_score"] == 4
        assert row["block_candidate"] is True
        assert row["blocking_mode"] == "detect_only"
    finally:
        clear_tenant_context()
