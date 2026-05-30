from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from licensing import LicenseError

pytestmark = pytest.mark.integration
AGENT_KEY_HEADER = {"X-CropPro-Agent-Key": "test-agent-key"}


async def _seed_machine(api, tenant: dict, machine_id: str = "m-report-1") -> str:
    registered = await api.post(
        "/api/machines/register",
        json={
            "machine_id": machine_id,
            "hostname": "report-host",
            "os": "Windows",
            "os_version": "11",
            "username": "report-user",
            "ip_address": "10.2.2.2",
            "mac_address": "aa:aa:aa:aa:aa:aa",
            "consent_given": True,
            "consent_timestamp": datetime.now(timezone.utc).isoformat(),
            "first_seen": datetime.now(timezone.utc).isoformat(),
            "agent_version": "test",
        },
        headers={**AGENT_KEY_HEADER, "X-CropPro-Enroll-Token": tenant["enrollment_token"]},
    )
    assert registered.status_code == 200, registered.text
    return machine_id


def _fake_license(max_tenants: int = 10) -> SimpleNamespace:
    expires_at = datetime.now(timezone.utc) + timedelta(days=30)
    return SimpleNamespace(
        license_id="lic-test-123",
        customer="Test Customer",
        tier="professional",
        max_seats=25,
        max_tenants=max_tenants,
        expires_at=expires_at,
        to_public_dict=lambda: {
            "license_id": "lic-test-123",
            "customer": "Test Customer",
            "tier": "professional",
            "max_seats": 25,
            "max_tenants": max_tenants,
            "expires_at": expires_at.isoformat(),
        },
    )


async def test_report_generation_returns_pdf(api, auth_headers, make_tenant, monkeypatch, tmp_path):
    tenant = make_tenant(slug="report-sync-tenant")
    machine_id = await _seed_machine(api, tenant, machine_id="m-report-sync")
    headers = await auth_headers(role="admin", tenant_id=tenant["id"])

    pdf_path = tmp_path / "report.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% test pdf\n")

    monkeypatch.setattr("app.routers.analytics.generate_report", lambda *args, **kwargs: str(pdf_path))

    resp = await api.get(f"/api/reports/generate/{machine_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.headers["content-type"].startswith("application/pdf")


async def test_async_report_job_completes_and_downloads(api, auth_headers, make_tenant, monkeypatch, tmp_path):
    tenant = make_tenant(slug="report-async-tenant")
    machine_id = await _seed_machine(api, tenant, machine_id="m-report-async")
    headers = await auth_headers(role="admin", tenant_id=tenant["id"])

    pdf_path = tmp_path / "report-async.pdf"
    pdf_path.write_bytes(b"%PDF-1.4\n% async test pdf\n")
    monkeypatch.setattr("app.routers.analytics.generate_report", lambda *args, **kwargs: str(pdf_path))
    monkeypatch.setattr("app.event_workers.generate_report", lambda *args, **kwargs: str(pdf_path))

    queued = await api.get(f"/api/reports/generate/{machine_id}?async=true", headers=headers)
    assert queued.status_code == 200, queued.text
    body = queued.json()
    assert body["status"] == "queued"
    assert body["download_url"] is None

    for _ in range(20):
        await asyncio.sleep(0.05)
        status = await api.get(f"/api/reports/jobs/{body['id']}", headers=headers)
        assert status.status_code == 200, status.text
        status_body = status.json()
        if status_body["status"] == "completed":
            break
    else:
        pytest.fail(f"Report job did not complete: {status_body}")

    assert status_body["download_url"] == f"/api/reports/jobs/{body['id']}/download"
    assert status_body["evidence_id"]
    assert status_body["storage_key"]
    assert status_body["output_path"] == ""
    download = await api.get(status_body["download_url"], headers=headers)
    assert download.status_code == 200, download.text
    assert download.headers["content-type"].startswith("application/pdf")


async def test_report_generation_missing_machine_returns_404(api, auth_headers):
    headers = await auth_headers(role="admin")
    resp = await api.get("/api/reports/generate/missing-machine", headers=headers)
    assert resp.status_code == 404


async def test_license_upload_accepts_valid_license(api, auth_headers, app, monkeypatch, tmp_path):
    headers = await auth_headers(role="admin")
    target_path = tmp_path / "license.key"
    monkeypatch.setenv("CROPPRO_LICENSE_PATH", str(target_path))
    monkeypatch.setattr("app.routers.analytics.load_and_verify_license", lambda license_path: _fake_license(10))

    resp = await api.post(
        "/api/license/upload",
        files={"file": ("license.key", b"valid-license", "application/octet-stream")},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert target_path.exists()
    assert getattr(app.state, "license", None) is not None
    assert resp.json()["license"]["license_id"] == "lic-test-123"


async def test_license_upload_rejects_invalid_license(api, auth_headers, monkeypatch, tmp_path):
    headers = await auth_headers(role="admin")
    monkeypatch.setenv("CROPPRO_LICENSE_PATH", str(tmp_path / "bad.key"))

    def _raise_invalid(*args, **kwargs):
        raise LicenseError("signature check failed")

    monkeypatch.setattr("app.routers.analytics.load_and_verify_license", _raise_invalid)

    resp = await api.post(
        "/api/license/upload",
        files={"file": ("license.key", b"invalid-license", "application/octet-stream")},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "Invalid license" in resp.json()["detail"]


async def test_license_upload_rejects_when_tenant_count_exceeds_limit(
    api, auth_headers, make_tenant, monkeypatch, tmp_path
):
    make_tenant(slug="tenant-two")
    headers = await auth_headers(role="admin")
    monkeypatch.setenv("CROPPRO_LICENSE_PATH", str(tmp_path / "limited.key"))
    monkeypatch.setattr("app.routers.analytics.load_and_verify_license", lambda license_path: _fake_license(1))

    resp = await api.post(
        "/api/license/upload",
        files={"file": ("license.key", b"limited-license", "application/octet-stream")},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "allows only 1 tenant" in resp.json()["detail"].lower()
