from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

pytestmark = pytest.mark.integration

AGENT_KEY_HEADER = {"X-CropPro-Agent-Key": "test-agent-key"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _register_payload(machine_id: str, hostname: str = "phish-lab") -> dict:
    return {
        "machine_id": machine_id,
        "hostname": hostname,
        "os": "Windows",
        "os_version": "11",
        "username": "analyst",
        "ip_address": "10.20.30.40",
        "mac_address": "aa:bb:cc:dd:ee:11",
        "consent_given": True,
        "consent_timestamp": _now_iso(),
        "first_seen": _now_iso(),
        "agent_version": "1.0.0-test",
    }


def _phishing_payload(machine_id: str, *, domain: str, url: str | None = None, title: str = "Sign in") -> dict:
    return {
        "machine_id": machine_id,
        "timestamp": _now_iso(),
        "event_type": "browser_visit",
        "channel": "browser",
        "url": url or f"https://{domain}/login",
        "domain": domain,
        "page_title": title,
        "app_name": "Chrome",
        "process_name": "chrome.exe",
        "remote_ip": "203.0.113.10",
        "actor_username": "analyst",
    }


@pytest.fixture
async def enrolled_machine(api, make_tenant, make_user):
    async def _factory(slug: str = "phish-tenant"):
        tenant = make_tenant(slug=f"{slug}-{uuid.uuid4().hex[:6]}")
        user = make_user(tenant_id=tenant["id"], username=f"{slug}-admin", password="Passw0rd!Test", role="admin")
        login = await api.post("/api/auth/login", data={"username": user["username"], "password": user["password"]})
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        machine_id = f"m-{uuid.uuid4().hex[:8]}"
        register = await api.post(
            "/api/machines/register",
            json=_register_payload(machine_id, hostname=f"{slug}-host"),
            headers={**AGENT_KEY_HEADER, "X-CropPro-Enroll-Token": tenant["enrollment_token"]},
        )
        assert register.status_code == 200, register.text
        return {"tenant": tenant, "headers": headers, "machine_id": machine_id}

    return _factory


async def test_effective_phishing_policy_exists_for_default_and_non_default_tenant(api, enrolled_machine, auth_headers):
    default_headers = await auth_headers(role="admin", tenant_id=1)
    tenant_ctx = await enrolled_machine("effective")

    default_policy = await api.get("/api/phishing/policy/effective", headers=default_headers)
    tenant_policy = await api.get("/api/phishing/policy/effective", headers=tenant_ctx["headers"])

    assert default_policy.status_code == 200, default_policy.text
    assert tenant_policy.status_code == 200, tenant_policy.text

    default_body = default_policy.json()
    tenant_body = tenant_policy.json()
    assert default_body["rollout_mode"] == "warn_only"
    assert tenant_body["rollout_mode"] == "warn_only"
    assert default_body["policy_version"] >= 1
    assert tenant_body["policy_version"] >= 1
    assert "browser" in tenant_body["protected_channels"]


async def test_tenant_rollout_mode_persists_after_policy_update(api, enrolled_machine):
    ctx = await enrolled_machine("rollout-mode")

    update = await api.put(
        "/api/phishing/policy",
        json={
            "name": "Tenant Phishing Protection",
            "description": "Updated rollout mode regression test",
            "scope": "tenant_override",
            "status": "published",
            "priority": 100,
            "rollout_mode": "detect_only",
            "intel_mode": "intel_plus_heuristics",
            "phishing_enabled": True,
            "protected_channels": ["browser", "download"],
            "severity_thresholds": {"medium": 55, "high": 75, "critical": 90},
            "allowlists": {"domains": [], "apps": [], "users": [], "paths": []},
            "suspicious_tlds": ["zip", "click", "work"],
            "brand_watchlist": ["microsoft", "google", "okta"],
            "download_risk_rules": {"dangerous_extensions": ["exe", "msi", "bat"], "warn_unknown_downloads": True},
            "evidence_controls": {"capture_title": True, "store_masked_indicators": True, "store_url": True},
            "config": {},
        },
        headers=ctx["headers"],
    )
    assert update.status_code == 200, update.text
    assert update.json()["rollout_mode"] == "detect_only"

    effective = await api.get("/api/phishing/policy/effective", headers=ctx["headers"])
    assert effective.status_code == 200, effective.text
    assert effective.json()["rollout_mode"] == "detect_only"


async def test_known_malicious_domain_creates_event_incident_and_alert(api, enrolled_machine):
    ctx = await enrolled_machine("knownbad")
    resp = await api.post(
        "/api/activity/phishing",
        json=_phishing_payload(ctx["machine_id"], domain="login-microsoftonline-security.com"),
        headers=AGENT_KEY_HEADER,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["event_id"] > 0
    assert body["incident_id"] is not None

    incidents = await api.get("/api/phishing/incidents", headers=ctx["headers"])
    assert incidents.status_code == 200, incidents.text
    items = incidents.json()["items"]
    assert len(items) == 1
    assert items[0]["domain"] == "login-microsoftonline-security.com"
    assert items[0]["warning_shown"] is True

    alerts = await api.get("/api/alerts/logs", headers=ctx["headers"])
    alert_rows = alerts.json().get("alerts", alerts.json()) if isinstance(alerts.json(), dict) else alerts.json()
    assert any("Phishing" in (row.get("message") or "") for row in alert_rows)


async def test_suspicious_tld_and_login_title_raise_incident_threshold(api, enrolled_machine):
    ctx = await enrolled_machine("suspicious")
    resp = await api.post(
        "/api/activity/phishing",
        json=_phishing_payload(
            ctx["machine_id"],
            domain="secure-payroll-login.zip",
            url="https://secure-payroll-login.zip/verify",
            title="Payroll sign in verification",
        ),
        headers=AGENT_KEY_HEADER,
    )
    assert resp.status_code == 200, resp.text

    events = await api.get("/api/phishing/events", headers=ctx["headers"])
    assert events.status_code == 200, events.text
    event = events.json()["events"][0]
    assert event["domain"] == "secure-payroll-login.zip"
    assert event["severity"] in ("medium", "high", "critical")
    assert "suspicious_tld" in event["reason_codes"]


async def test_allowlisted_domain_is_downgraded_and_does_not_create_incident(api, enrolled_machine):
    ctx = await enrolled_machine("allowlist")
    allow = await api.post(
        "/api/phishing/allowlists",
        json={"domain": "login-microsoftonline-security.com", "reason": "approved simulation"},
        headers=ctx["headers"],
    )
    assert allow.status_code == 200, allow.text

    ingest = await api.post(
        "/api/activity/phishing",
        json=_phishing_payload(ctx["machine_id"], domain="login-microsoftonline-security.com"),
        headers=AGENT_KEY_HEADER,
    )
    assert ingest.status_code == 200, ingest.text
    assert ingest.json()["incident_id"] is None

    events = await api.get("/api/phishing/events", headers=ctx["headers"])
    event = events.json()["events"][0]
    assert event["action_result"] == "allowlisted"

    incidents = await api.get("/api/phishing/incidents", headers=ctx["headers"])
    assert incidents.json()["items"] == []


async def test_repeated_same_domain_hits_group_into_one_incident(api, enrolled_machine):
    ctx = await enrolled_machine("grouping")
    payload = _phishing_payload(ctx["machine_id"], domain="github-verify-login.com")

    first = await api.post("/api/activity/phishing", json=payload, headers=AGENT_KEY_HEADER)
    second = await api.post("/api/activity/phishing", json={**payload, "timestamp": _now_iso()}, headers=AGENT_KEY_HEADER)

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["incident_id"] == second.json()["incident_id"]

    incidents = await api.get("/api/phishing/incidents", headers=ctx["headers"])
    items = incidents.json()["items"]
    assert len(items) == 1
    assert items[0]["event_count"] == 2
