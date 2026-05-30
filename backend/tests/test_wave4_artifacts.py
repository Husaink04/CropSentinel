from __future__ import annotations

import pytest
from pathlib import Path

pytestmark = pytest.mark.integration


def test_latest_installer_prefers_highest_version_over_newer_mtime(tmp_path: Path):
    from app.routers.tenants import _latest_installer

    older_version_newer_time = tmp_path / "cropsentinel-agent-1.2.9-setup.exe"
    newer_version_older_time = tmp_path / "cropsentinel-agent-1.3.0-setup.exe"
    older_version_newer_time.write_bytes(b"old")
    newer_version_older_time.write_bytes(b"new")

    newer_timestamp = 1_800_000_000
    older_timestamp = 1_700_000_000
    older_version_newer_time.touch()
    newer_version_older_time.touch()

    import os

    os.utime(older_version_newer_time, (newer_timestamp, newer_timestamp))
    os.utime(newer_version_older_time, (older_timestamp, older_timestamp))

    selected = _latest_installer(tmp_path, ["cropsentinel-agent-*.exe"])
    assert selected == newer_version_older_time


async def test_audit_export_is_persisted_as_object_artifact(api, auth_headers, db):
    headers = await auth_headers(role="admin", tenant_id=1)

    resp = await api.get("/api/audit-logs/export?format=json", headers=headers)
    assert resp.status_code == 200, resp.text
    artifact_id = resp.headers.get("X-Artifact-ID")
    assert artifact_id

    evidence = db.get_evidence_object(int(artifact_id), tenant_id=1)
    assert evidence is not None
    assert evidence["category"] == "exports"
    assert evidence["evidence_classification"] == "audit_export"
    payload = db.load_evidence_object_bytes(int(artifact_id), tenant_id=1)
    assert payload.startswith(b"[")


async def test_tenant_agent_bundle_is_persisted_as_object_artifact(api, auth_headers, make_tenant, db, monkeypatch, tmp_path):
    tenant = make_tenant(slug="bundle-tenant")
    headers = await auth_headers(role="admin", tenant_id=1)

    installer_path = tmp_path / "cropsentinel-agent-9.9.9.exe"
    installer_path.write_bytes(b"fake-installer-binary")
    monkeypatch.setattr("app.routers.tenants._latest_installer", lambda dist_dir, patterns: installer_path)

    resp = await api.post(
        f"/api/tenants/{tenant['id']}/download-agent",
        json={"server_url": "http://example.test"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    artifact_id = resp.headers.get("X-Artifact-ID")
    assert artifact_id

    evidence = db.get_evidence_object(int(artifact_id), tenant_id=tenant["id"])
    assert evidence is not None
    assert evidence["category"] == "installer_bundles"
    payload = db.load_evidence_object_bytes(int(artifact_id), tenant_id=tenant["id"])
    assert payload[:2] == b"PK"


async def test_generic_windows_agent_installer_download_uses_fixed_url(api, monkeypatch):
    monkeypatch.setenv("CROPSENTINEL_WINDOWS_AGENT_URL", "https://downloads.example.test/cropsentinel-agent.exe")

    resp = await api.get("/api/agent-installers/windows/latest", follow_redirects=False)
    assert resp.status_code in (302, 307)
    assert resp.headers["location"] == "https://downloads.example.test/cropsentinel-agent.exe"


async def test_legacy_inline_backfill_moves_binary_to_object_storage(db):
    from app.db.core import Connection as _Conn
    from app.db.core import clear_tenant_context, set_tenant_context

    set_tenant_context(1)
    try:
        db.upsert_machine(
            {
                "machine_id": "m-backfill-1",
                "hostname": "backfill-host",
                "os": "Windows",
                "os_version": "11",
                "username": "tester",
                "ip_address": "10.0.0.20",
                "mac_address": "aa:bb:cc:dd:ee:99",
                "consent_given": True,
                "consent_timestamp": "2026-01-01T00:00:00+00:00",
                "first_seen": "2026-01-01T00:00:00+00:00",
                "last_seen": "2026-01-01T00:00:00+00:00",
                "agent_version": "test",
            }
        )
    finally:
        clear_tenant_context()

    with _Conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO deleted_file_backups
                    (tenant_id, machine_id, timestamp, original_path, file_name, file_ext,
                     file_size, file_data, username)
                VALUES
                    (1, 'm-backfill-1', NOW(), 'C:/secret.txt', 'secret.txt', '.txt', 0, 'aGVsbG8=', 'tester')
                RETURNING id
                """
            )
            backup_id = cur.fetchone()["id"]

    migrated = db.backfill_legacy_binary_evidence(limit=10)
    assert migrated["deleted_backups"] >= 1

    backup = db.get_deleted_backup_file(backup_id)
    assert backup is not None
    assert backup["storage_key"]
    assert backup["file_data"] == "aGVsbG8="
