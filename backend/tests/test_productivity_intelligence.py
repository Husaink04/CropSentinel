from __future__ import annotations

from datetime import datetime, timedelta, timezone
import uuid

import pytest

pytestmark = pytest.mark.integration

AGENT_KEY_HEADER = {"X-CropPro-Agent-Key": "test-agent-key"}


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _register_payload(machine_id: str, hostname: str, username: str = "worker") -> dict:
    now = datetime.now(timezone.utc)
    return {
        "machine_id": machine_id,
        "hostname": hostname,
        "os": "Windows",
        "os_version": "11",
        "username": username,
        "ip_address": "10.0.0.20",
        "mac_address": f"aa:bb:cc:{machine_id[-2:]}:11:22",
        "consent_given": True,
        "consent_timestamp": _iso(now),
        "first_seen": _iso(now),
        "agent_version": "1.0.0-test",
    }


async def _register_machine(api, tenant: dict, machine_id: str, hostname: str, username: str = "worker") -> None:
    resp = await api.post(
        "/api/machines/register",
        json=_register_payload(machine_id, hostname, username),
        headers={**AGENT_KEY_HEADER, "X-CropPro-Enroll-Token": tenant["enrollment_token"]},
    )
    assert resp.status_code == 200, resp.text


async def _post_app(api, tenant: dict, machine_id: str, when: datetime, app_name: str, duration_seconds: int, process_name: str = "") -> None:
    resp = await api.post(
        "/api/activity/application",
        json={
            "machine_id": machine_id,
            "timestamp": _iso(when),
            "app_name": app_name,
            "window_title": app_name,
            "process_name": process_name or app_name.lower(),
            "duration_seconds": duration_seconds,
            "is_active": True,
        },
        headers={**AGENT_KEY_HEADER, "X-CropPro-Enroll-Token": tenant["enrollment_token"]},
    )
    assert resp.status_code == 200, resp.text


async def _post_browser(api, tenant: dict, machine_id: str, when: datetime, domain: str, duration_seconds: int) -> None:
    resp = await api.post(
        "/api/activity/browser",
        json={
            "machine_id": machine_id,
            "timestamp": _iso(when),
            "browser": "chrome",
            "url": f"https://{domain}/page",
            "title": domain,
            "domain": domain,
            "duration_seconds": duration_seconds,
        },
        headers={**AGENT_KEY_HEADER, "X-CropPro-Enroll-Token": tenant["enrollment_token"]},
    )
    assert resp.status_code == 200, resp.text


async def _post_input(api, tenant: dict, machine_id: str, start: datetime, end: datetime, key_count: int = 8, click_count: int = 2) -> None:
    resp = await api.post(
        "/api/activity/input",
        json={
            "machine_id": machine_id,
            "timestamp": _iso(end),
            "bucket_start": _iso(start),
            "bucket_end": _iso(end),
            "process_name": "code.exe",
            "window_title": "Coding",
            "key_event_count": key_count,
            "mouse_click_count": click_count,
            "mouse_scroll_count": 0,
            "pattern_hashes": [],
            "ngram_size": 8,
        },
        headers={**AGENT_KEY_HEADER, "X-CropPro-Enroll-Token": tenant["enrollment_token"]},
    )
    assert resp.status_code == 200, resp.text


async def test_productivity_endpoints_share_canonical_score(api, auth_headers, make_tenant):
    tenant = make_tenant(slug="productivity-intel")
    admin_headers = await auth_headers(role="admin", tenant_id=tenant["id"])
    machine_id = f"m-{uuid.uuid4().hex[:8]}"
    base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=3)

    await _register_machine(api, tenant, machine_id, "focus-box")
    await _post_app(api, tenant, machine_id, base, "Code", 3600, "code.exe")
    await _post_app(api, tenant, machine_id, base + timedelta(hours=1), "Slack", 1800, "slack.exe")
    await _post_browser(api, tenant, machine_id, base + timedelta(hours=1, minutes=5), "github.com", 1200)
    await _post_browser(api, tenant, machine_id, base + timedelta(hours=1, minutes=30), "youtube.com", 600)
    await _post_input(api, tenant, machine_id, base, base + timedelta(minutes=30))
    await _post_input(api, tenant, machine_id, base + timedelta(minutes=30), base + timedelta(hours=1))

    machine_resp = await api.get(f"/api/productivity/machines/{machine_id}", headers=admin_headers)
    team_alias_resp = await api.get(f"/api/machines/{machine_id}/productivity", headers=admin_headers)
    analytics_alias_resp = await api.get(f"/api/analytics/productivity/{machine_id}", headers=admin_headers)

    assert machine_resp.status_code == 200, machine_resp.text
    assert team_alias_resp.status_code == 200, team_alias_resp.text
    assert analytics_alias_resp.status_code == 200, analytics_alias_resp.text

    canonical = machine_resp.json()
    team_alias = team_alias_resp.json()
    analytics_alias = analytics_alias_resp.json()

    assert canonical["summary"]["productivity_score"] == team_alias["productivity_score"]
    assert canonical["summary"]["productivity_score"] == analytics_alias["score"]
    assert canonical["score_components"]["supportive_time_seconds"] > 0
    assert canonical["score_components"]["distracting_time_seconds"] > 0
    assert canonical["findings"]


async def test_productivity_overview_and_policy_settings(api, auth_headers, make_tenant):
    tenant = make_tenant(slug="productivity-policy")
    admin_headers = await auth_headers(role="admin", tenant_id=tenant["id"])
    machine_a = f"m-{uuid.uuid4().hex[:8]}"
    machine_b = f"m-{uuid.uuid4().hex[:8]}"
    base = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0) - timedelta(hours=2)

    await _register_machine(api, tenant, machine_a, "alpha")
    await _register_machine(api, tenant, machine_b, "bravo")

    update_resp = await api.put(
        "/api/settings",
        json={
            "productivity_apps": [
                {"match_value": "code", "match_type": "contains", "category": "productive", "weight": 1, "always_active": False},
                {"match_value": "teams", "match_type": "contains", "category": "supportive", "weight": 0.8, "always_active": True},
            ],
            "productivity_domains": [
                {"match_value": "github.com", "match_type": "contains", "category": "productive", "weight": 1, "always_active": False},
                {"match_value": "youtube.com", "match_type": "contains", "category": "distracting", "weight": 0, "always_active": False},
            ],
        },
        headers=admin_headers,
    )
    assert update_resp.status_code == 200, update_resp.text

    await _post_app(api, tenant, machine_a, base, "Code", 2400, "code.exe")
    await _post_browser(api, tenant, machine_a, base + timedelta(minutes=10), "github.com", 1200)
    await _post_input(api, tenant, machine_a, base, base + timedelta(minutes=30))

    await _post_app(api, tenant, machine_b, base, "Chrome", 2400, "chrome.exe")
    await _post_browser(api, tenant, machine_b, base + timedelta(minutes=10), "youtube.com", 1800)

    overview_resp = await api.get("/api/productivity/overview", headers=admin_headers)
    machines_resp = await api.get("/api/productivity/machines", headers=admin_headers)
    settings_resp = await api.get("/api/settings", headers=admin_headers)

    assert overview_resp.status_code == 200, overview_resp.text
    assert machines_resp.status_code == 200, machines_resp.text
    assert settings_resp.status_code == 200, settings_resp.text

    overview = overview_resp.json()
    machine_rows = machines_resp.json()["items"]
    settings_body = settings_resp.json()

    assert overview["summary"]["machine_count"] == 2
    assert overview["top_distraction_drivers"]
    assert machine_rows[0]["productivity_score"] >= machine_rows[1]["productivity_score"]
    assert settings_body["productivity_apps"]
    assert settings_body["productivity_domains"]
