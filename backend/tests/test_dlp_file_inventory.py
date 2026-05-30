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
        "hostname": "inventory-host",
        "os": "Windows",
        "os_version": "11",
        "username": "labuser",
        "ip_address": "10.0.0.88",
        "mac_address": "aa:bb:cc:77:88:99",
        "consent_given": True,
        "consent_timestamp": _now_iso(),
        "first_seen": _now_iso(),
        "agent_version": "1.0.0-test",
    }


async def _enroll_machine(api, make_tenant, machine_id: str | None = None):
    tenant = make_tenant(slug=f"inventory-{uuid.uuid4().hex[:6]}")
    machine_id = machine_id or f"m-{uuid.uuid4().hex[:8]}"
    resp = await api.post(
        "/api/machines/register",
        json=_register_payload(machine_id),
        headers={**AGENT_KEY_HEADER, "X-CropSentinel-Enroll-Token": tenant["enrollment_token"]},
    )
    assert resp.status_code == 200, resp.text
    return tenant, machine_id


def _inventory_record(inventory_id: int, path: str, sha256: str = "hash-a", size_bytes: int = 123) -> dict:
    return {
        "inventory_id": inventory_id,
        "absolute_path": path,
        "normalized_path": path.lower(),
        "file_name": path.split("\\")[-1],
        "extension": ".txt",
        "size_bytes": size_bytes,
        "mtime_ns": 100,
        "ctime_ns": 90,
        "owner_name": "labuser",
        "sha256": sha256,
        "content_fingerprint": f"content-{sha256}",
        "scan_version": "baseline-v1",
        "scan_status": "scanned",
        "inspect_status": "inspected",
        "inspect_reason": "",
        "parser_type": "text",
        "findings_summary": {"risk": "low", "findings": [{"type": "email", "count": 1}]},
        "label_summary": {"risk": "low", "risk_score": 2, "finding_types": ["email"], "findings_count": 1},
        "last_scanned_at": _now_iso(),
        "first_seen_at": _now_iso(),
        "last_seen_at": _now_iso(),
    }


async def test_dlp_file_inventory_batch_ingests_and_reports_status(api, make_tenant, make_user):
    tenant, machine_id = await _enroll_machine(api, make_tenant)
    admin = make_user(tenant_id=tenant["id"], role="admin")
    login = await api.post("/api/auth/login", data={"username": admin["username"], "password": admin["password"]})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    batch = await api.post(
        "/api/dlp/file-inventory/batch",
        json={
            "machine_id": machine_id,
            "scan_job_id": 1,
            "root_id": "root-1",
            "records": [
                _inventory_record(1, r"C:\Users\labuser\Documents\a.txt", sha256="hash-a"),
                _inventory_record(2, r"C:\Users\labuser\Documents\b.txt", sha256="hash-b", size_bytes=456),
            ],
            "stats": {
                "pending_upload_count": 2,
                "total_inventory_count": 2,
                "parser_failure_count": 0,
                "oldest_unsynced_at": _now_iso(),
            },
        },
        headers=AGENT_KEY_HEADER,
    )
    assert batch.status_code == 200, batch.text
    body = batch.json()
    assert body["processed"] == 2
    assert body["success_ids"] == [1, 2]

    status = await api.get(f"/api/dlp/file-inventory/status/{machine_id}", headers=headers)
    assert status.status_code == 200, status.text
    payload = status.json()
    assert payload["totals"]["total_files"] == 2
    assert payload["totals"]["inspected_files"] == 2
    assert payload["sync_status"][0]["pending_upload_count"] == 2


async def test_dlp_file_inventory_upsert_keeps_single_row_per_path(api, make_tenant, db):
    tenant, machine_id = await _enroll_machine(api, make_tenant)

    first = await api.post(
        "/api/dlp/file-inventory/batch",
        json={
            "machine_id": machine_id,
            "scan_job_id": 2,
            "root_id": "root-2",
            "records": [_inventory_record(10, r"C:\Data\same.txt", sha256="hash-first", size_bytes=111)],
            "stats": {"pending_upload_count": 1, "total_inventory_count": 1, "parser_failure_count": 0},
        },
        headers=AGENT_KEY_HEADER,
    )
    assert first.status_code == 200, first.text

    second = await api.post(
        "/api/dlp/file-inventory/batch",
        json={
            "machine_id": machine_id,
            "scan_job_id": 2,
            "root_id": "root-2",
            "records": [_inventory_record(11, r"C:\Data\same.txt", sha256="hash-updated", size_bytes=999)],
            "stats": {"pending_upload_count": 1, "total_inventory_count": 1, "parser_failure_count": 0},
        },
        headers=AGENT_KEY_HEADER,
    )
    assert second.status_code == 200, second.text

    set_tenant_context(tenant["id"])
    try:
        status = db.get_dlp_file_inventory_status(machine_id, tenant_id=tenant["id"])
        assert status["totals"]["total_files"] == 1
    finally:
        clear_tenant_context()


async def test_dlp_file_inventory_status_is_tenant_scoped(api, make_tenant, make_user):
    tenant_a, machine_id = await _enroll_machine(api, make_tenant)
    tenant_b = make_tenant(slug=f"inventory-b-{uuid.uuid4().hex[:6]}")
    user_b = make_user(tenant_id=tenant_b["id"], role="admin")
    login_b = await api.post("/api/auth/login", data={"username": user_b["username"], "password": user_b["password"]})
    headers_b = {"Authorization": f"Bearer {login_b.json()['access_token']}"}

    batch = await api.post(
        "/api/dlp/file-inventory/batch",
        json={
            "machine_id": machine_id,
            "scan_job_id": 3,
            "root_id": "root-3",
            "records": [_inventory_record(22, r"C:\Scoped\tenant-a.txt")],
            "stats": {"pending_upload_count": 1, "total_inventory_count": 1, "parser_failure_count": 0},
        },
        headers=AGENT_KEY_HEADER,
    )
    assert batch.status_code == 200, batch.text

    leaked = await api.get(f"/api/dlp/file-inventory/status/{machine_id}", headers=headers_b)
    assert leaked.status_code == 200, leaked.text
    payload = leaked.json()
    assert payload["totals"]["total_files"] == 0
    assert payload["sync_status"] == []
