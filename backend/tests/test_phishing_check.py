from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.integration

AGENT_KEY_HEADER = {"X-CropSentinel-Agent-Key": "test-agent-key"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _register_payload(machine_id: str) -> dict:
    return {
        "machine_id": machine_id,
        "hostname": "phish-check-host",
        "os": "Windows",
        "os_version": "11",
        "username": "labuser",
        "ip_address": "10.0.0.44",
        "mac_address": "aa:bb:cc:11:22:77",
        "consent_given": True,
        "consent_timestamp": _now_iso(),
        "first_seen": _now_iso(),
        "agent_version": "1.2.0-test",
    }


async def _enroll_machine(api, make_tenant, make_user, slug: str = "phish-check"):
    tenant = make_tenant(slug=f"{slug}-{uuid.uuid4().hex[:6]}")
    user = make_user(tenant_id=tenant["id"], role="admin")
    login = await api.post("/api/auth/login", data={"username": user["username"], "password": user["password"]})
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    machine_id = f"m-{uuid.uuid4().hex[:8]}"
    resp = await api.post(
        "/api/machines/register",
        json=_register_payload(machine_id),
        headers={**AGENT_KEY_HEADER, "X-CropSentinel-Enroll-Token": tenant["enrollment_token"]},
    )
    assert resp.status_code == 200, resp.text
    return tenant, headers, machine_id


async def test_phishing_check_returns_malicious_for_tenant_blocklist(api, make_tenant, make_user):
    tenant, headers, machine_id = await _enroll_machine(api, make_tenant, make_user, "blocklist-check")
    block = await api.post(
        "/api/phishing/blacklists",
        json={"domain": "evil-login.example", "reason": "known bad"},
        headers=headers,
    )
    assert block.status_code == 200, block.text

    resp = await api.post(
        "/api/phishing/check",
        json={
            "machine_id": machine_id,
            "url": "https://evil-login.example/login",
            "user_id": "labuser",
            "app_name": "Chrome",
            "process_name": "chrome.exe",
            "page_title": "Sign in",
            "initial_agent_verdict": "suspicious",
            "local_features": {"uses_https": True},
        },
        headers=AGENT_KEY_HEADER,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["verdict"] == "malicious"
    assert "blocklisted_domain" in body["reason_codes"]


async def test_phishing_report_attaches_feedback_to_incident(api, make_tenant, make_user):
    tenant, headers, machine_id = await _enroll_machine(api, make_tenant, make_user, "report-feedback")
    ingest = await api.post(
        "/api/activity/phishing",
        json={
            "machine_id": machine_id,
            "timestamp": _now_iso(),
            "event_type": "browser_visit",
            "channel": "browser",
            "url": "https://github-verify-login.com/login",
            "domain": "github-verify-login.com",
            "page_title": "GitHub sign in",
            "app_name": "Chrome",
            "process_name": "chrome.exe",
            "actor_username": "labuser",
        },
        headers=AGENT_KEY_HEADER,
    )
    assert ingest.status_code == 200, ingest.text
    incident_id = ingest.json()["incident_id"]
    assert incident_id is not None

    report = await api.post(
        "/api/phishing/report",
        json={
            "machine_id": machine_id,
            "incident_id": incident_id,
            "url": "https://github-verify-login.com/login",
            "domain": "github-verify-login.com",
            "feedback": "false_positive",
            "verdict": "clean",
            "note": "approved internal simulation",
        },
        headers=AGENT_KEY_HEADER,
    )
    assert report.status_code == 200, report.text
    assert report.json()["stored"] is True

    detail = await api.get(f"/api/phishing/incidents/{incident_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    notes = detail.json()["notes"]
    assert any("approved internal simulation" in (note.get("note") or "") for note in notes)
