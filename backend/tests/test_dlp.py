from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.db.core import clear_tenant_context, set_tenant_context

pytestmark = pytest.mark.integration


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@pytest.fixture
def dlp_machine(db, make_tenant):
    tenant = make_tenant(slug="dlp-tenant")
    machine_id = "m-dlp-1"
    set_tenant_context(tenant["id"])
    try:
        db.upsert_machine(
            {
                "machine_id": machine_id,
                "hostname": "dlp-host",
                "os": "Windows",
                "os_version": "11",
                "username": "dlp-user",
                "ip_address": "10.5.0.2",
                "mac_address": "aa:bb:cc:dd:ee:00",
                "consent_given": True,
                "consent_timestamp": _now_iso(),
                "first_seen": _now_iso(),
                "last_seen": _now_iso(),
                "agent_version": "test",
            }
        )
    finally:
        clear_tenant_context()
    return {"tenant": tenant, "machine_id": machine_id}


async def test_dlp_policy_round_trip(api, auth_headers):
    headers = await auth_headers(role="admin")
    update = await api.put(
        "/api/dlp/policy",
        json={
            "dlp_enabled": True,
            "dlp_keywords": ["ssn", "passport"],
            "dlp_custom_patterns": {"employee_id": "\\d{6}"},
            "dlp_risk_thresholds": {"low": 1, "medium": 2, "high": 4},
        },
        headers=headers,
    )
    assert update.status_code == 200, update.text

    get_resp = await api.get("/api/dlp/policy", headers=headers)
    assert get_resp.status_code == 200
    body = get_resp.json()
    assert body["dlp_enabled"] is True
    assert body["dlp_keywords"] == ["ssn", "passport"]
    assert body["dlp_custom_patterns"]["employee_id"] == "\\d{6}"
    assert body["dlp_risk_thresholds"]["high"] == 4


async def test_high_risk_dlp_event_creates_alert(api, auth_headers, dlp_machine):
    headers = await auth_headers(role="admin", tenant_id=dlp_machine["tenant"]["id"])

    resp = await api.post(
        "/api/dlp/events",
        json={
            "machine_id": dlp_machine["machine_id"],
            "timestamp": _now_iso(),
            "file_path": "C:/secret/payroll.xlsx",
            "file_name": "payroll.xlsx",
            "file_ext": ".xlsx",
            "file_size": 4096,
            "risk_level": "high",
            "risk_score": 9,
            "destination": "usb",
            "findings": [{"type": "ssn", "count": 3}],
        },
        headers={"X-CropPro-Agent-Key": "test-agent-key"},
    )
    assert resp.status_code == 200, resp.text
    event_id = resp.json()["id"]

    events = await api.get("/api/dlp/events?risk_level=high", headers=headers)
    assert events.status_code == 200
    assert any(event["id"] == event_id for event in events.json()["events"])

    alerts = await api.get("/api/alerts/logs", headers=headers)
    assert alerts.status_code == 200
    assert any("DLP HIGH" in (row.get("message") or "") for row in alerts.json())


async def test_dlp_event_filters_and_acknowledge(api, auth_headers, dlp_machine):
    headers = await auth_headers(role="admin", tenant_id=dlp_machine["tenant"]["id"])

    for risk_level, destination, file_name in [
        ("low", "local", "notes.txt"),
        ("medium", "email", "finance.csv"),
    ]:
        resp = await api.post(
            "/api/dlp/events",
            json={
                "machine_id": dlp_machine["machine_id"],
                "timestamp": _now_iso(),
                "file_path": f"C:/{file_name}",
                "file_name": file_name,
                "file_ext": "." + file_name.split(".")[-1],
                "file_size": 123,
                "risk_level": risk_level,
                "risk_score": 4 if risk_level == "medium" else 1,
                "destination": destination,
                "findings": [{"type": "keyword", "count": 1}],
            },
            headers={"X-CropPro-Agent-Key": "test-agent-key"},
        )
        assert resp.status_code == 200, resp.text

    filtered = await api.get(
        "/api/dlp/events?risk_level=medium&destination=email&search=finance",
        headers=headers,
    )
    assert filtered.status_code == 200
    events = filtered.json()["events"]
    assert len(events) == 1
    assert events[0]["file_name"] == "finance.csv"

    ack = await api.put(
        f"/api/dlp/events/{events[0]['id']}/acknowledge",
        headers=headers,
    )
    assert ack.status_code == 200, ack.text

    all_events = await api.get("/api/dlp/events", headers=headers)
    row = next(event for event in all_events.json()["events"] if event["id"] == events[0]["id"])
    assert row["acknowledged"] is True


async def test_agent_block_result_is_preserved(api, auth_headers, dlp_machine):
    headers = await auth_headers(role="admin", tenant_id=dlp_machine["tenant"]["id"])

    resp = await api.post(
        "/api/dlp/events",
        json={
            "machine_id": dlp_machine["machine_id"],
            "timestamp": _now_iso(),
            "file_path": "E:/USB/payroll.xlsx",
            "file_name": "payroll.xlsx",
            "file_ext": ".xlsx",
            "file_size": 4096,
            "risk_level": "high",
            "risk_score": 10,
            "destination": "usb",
            "destination_type": "usb",
            "destination_label": "Kingston USB",
            "findings": [{"type": "ssn", "count": 3}],
            "action_taken": "block_transfer",
            "action_result": "blocked",
            "blocking_supported": True,
            "blocking_mode": "agent_enforced",
        },
        headers={"X-CropPro-Agent-Key": "test-agent-key"},
    )
    assert resp.status_code == 200, resp.text

    events = await api.get("/api/dlp/events?risk_level=high", headers=headers)
    assert events.status_code == 200
    row = next(event for event in events.json()["events"] if event["file_name"] == "payroll.xlsx")
    assert row["action_taken"] == "block_transfer"
    assert row["action_result"] == "blocked"


async def test_dlp_exception_allows_matching_event(api, auth_headers, dlp_machine):
    headers = await auth_headers(role="admin", tenant_id=dlp_machine["tenant"]["id"])

    create_exception = await api.post(
        "/api/dlp/exceptions",
        json={
            "scope_type": "path",
            "scope_value": "",
            "classifier_name": "pii_ssn",
            "destination_type": "usb",
            "path_pattern": "approved-payroll.xlsx",
            "reason": "Approved HR export",
            "status": "active",
            "metadata": {"source": "test"},
        },
        headers=headers,
    )
    assert create_exception.status_code == 200, create_exception.text

    resp = await api.post(
        "/api/dlp/events",
        json={
            "machine_id": dlp_machine["machine_id"],
            "timestamp": _now_iso(),
            "file_path": "E:/USB/approved-payroll.xlsx",
            "file_name": "approved-payroll.xlsx",
            "file_ext": ".xlsx",
            "file_size": 4096,
            "risk_level": "high",
            "risk_score": 10,
            "destination": "usb",
            "destination_type": "usb",
            "findings": [{"type": "ssn", "count": 2}],
        },
        headers={"X-CropPro-Agent-Key": "test-agent-key"},
    )
    assert resp.status_code == 200, resp.text

    events = await api.get("/api/dlp/events?search=approved-payroll", headers=headers)
    assert events.status_code == 200
    row = next(event for event in events.json()["events"] if event["file_name"] == "approved-payroll.xlsx")
    assert row["action_taken"] == "monitor"
    assert row["action_result"] == "exception_applied"


async def test_dlp_incident_detail_and_review_flow(api, auth_headers, dlp_machine):
    headers = await auth_headers(role="admin", tenant_id=dlp_machine["tenant"]["id"])

    old_ts = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    old_resp = await api.post(
        "/api/dlp/events",
        json={
            "machine_id": dlp_machine["machine_id"],
            "timestamp": old_ts,
            "file_path": "C:/secret/payroll.xlsx",
            "file_name": "payroll.xlsx",
            "file_ext": ".xlsx",
            "file_size": 4096,
            "risk_level": "medium",
            "risk_score": 6,
            "destination": "usb",
            "destination_type": "usb",
            "destination_label": "Earlier USB",
            "actor_username": "dlp-user",
            "enterprise_label": "Confidential",
            "classifier_hits": [{"name": "pii_ssn", "severity": "high", "category": "pii"}],
            "findings": [{"type": "ssn", "count": 1}],
        },
        headers={"X-CropPro-Agent-Key": "test-agent-key"},
    )
    assert old_resp.status_code == 200, old_resp.text

    for destination_type in ["usb", "print"]:
        resp = await api.post(
            "/api/dlp/events",
            json={
                "machine_id": dlp_machine["machine_id"],
                "timestamp": _now_iso(),
                "file_path": "C:/secret/payroll.xlsx",
                "file_name": "payroll.xlsx",
                "file_ext": ".xlsx",
                "file_size": 4096,
                "risk_level": "high",
                "risk_score": 10,
                "destination": destination_type,
                "destination_type": destination_type,
                "destination_label": "Analyst test target",
                "enterprise_label": "Confidential",
                "classifier_hits": [{"name": "pii_ssn", "severity": "high", "category": "pii"}],
                "masked_evidence": [{"type": "preview", "preview": "Employee SSN <masked>"}],
                "findings": [{"type": "ssn", "count": 2}],
            },
            headers={"X-CropPro-Agent-Key": "test-agent-key"},
        )
        assert resp.status_code == 200, resp.text

    incidents = await api.get("/api/dlp/incidents?limit=20", headers=headers)
    assert incidents.status_code == 200, incidents.text
    incident = next(
        item
        for item in incidents.json()["items"]
        if item["metadata"]["file_name"] == "payroll.xlsx"
        and (item.get("destination_type") == "usb" or item["metadata"].get("destination_type") == "usb")
    )

    detail = await api.get(f"/api/dlp/incidents/{incident['id']}", headers=headers)
    assert detail.status_code == 200, detail.text
    payload = detail.json()
    assert payload["policy_name"]
    assert payload["events"]
    assert payload["evidence_summary"]
    assert payload["timeline"]
    assert payload["recommended_actions"]
    assert payload["history_summary"]["repeat_incident_count"] >= 1
    assert payload["historical_incidents"]
    assert payload["history_filters_applied"]["actor_username"] == "dlp-user"
    assert payload["retention_summary"]["window_days"] == 90

    update = await api.put(
        f"/api/dlp/incidents/{incident['id']}",
        json={
            "state": "contained",
            "severity": "critical",
            "assignee": "soc-1",
            "disposition": "contained",
            "resolution_reason": "Blocked USB attempt confirmed by analyst",
            "note": "Linked print activity reviewed and contained.",
        },
        headers=headers,
    )
    assert update.status_code == 200, update.text
    updated = update.json()
    assert updated["state"] == "contained"
    assert updated["severity"] == "critical"
    assert updated["assignee"] == "soc-1"
    assert updated["metadata"]["disposition"] == "contained"
    assert updated["metadata"]["resolution_reason"] == "Blocked USB attempt confirmed by analyst"
    assert any("Linked print activity reviewed" in (note.get("note") or "") for note in updated["notes"])
    assert any(entry.get("action") == "incident_review_updated" for entry in updated["timeline"])

    filtered = await api.get(
        f"/api/dlp/incidents?actor_username=dlp-user&machine_id={dlp_machine['machine_id']}&destination_type=usb&date_from={old_ts[:10]}T00:00:00+00:00",
        headers=headers,
    )
    assert filtered.status_code == 200, filtered.text
    filtered_rows = filtered.json()["items"]
    assert filtered_rows
    assert any(row["id"] == incident["id"] for row in filtered_rows)


async def test_dlp_user_risk_summary_and_detail(api, auth_headers, dlp_machine, db):
    headers = await auth_headers(role="admin", tenant_id=dlp_machine["tenant"]["id"])
    second_machine_id = "m-dlp-2"
    set_tenant_context(dlp_machine["tenant"]["id"])
    try:
        db.upsert_machine(
            {
                "machine_id": second_machine_id,
                "hostname": "dlp-host-2",
                "os": "Windows",
                "os_version": "11",
                "username": "usb-risk-user",
                "ip_address": "10.5.0.3",
                "mac_address": "aa:bb:cc:dd:ee:02",
                "consent_given": True,
                "consent_timestamp": _now_iso(),
                "first_seen": _now_iso(),
                "last_seen": _now_iso(),
                "agent_version": "test",
            }
        )
    finally:
        clear_tenant_context()

    async def send_event(payload):
        resp = await api.post(
            "/api/dlp/events",
            json=payload,
            headers={"X-CropPro-Agent-Key": "test-agent-key"},
        )
        assert resp.status_code == 200, resp.text
        return resp.json()

    after_hours = (datetime.now(timezone.utc) - timedelta(hours=2)).replace(hour=22, minute=15, second=0, microsecond=0)
    older_high = datetime.now(timezone.utc) - timedelta(days=5)
    older_low = datetime.now(timezone.utc) - timedelta(days=25)

    await send_event(
        {
            "machine_id": dlp_machine["machine_id"],
            "timestamp": after_hours.isoformat(),
            "file_path": "E:/USB/payroll-q2.xlsx",
            "file_name": "payroll-q2.xlsx",
            "file_ext": ".xlsx",
            "file_size": 4096,
            "risk_level": "high",
            "risk_score": 10,
            "destination": "usb",
            "destination_type": "usb",
            "destination_label": "Kingston USB",
            "actor_username": "usb-risk-user",
            "file_hash": "hash-payroll-shared",
            "content_fingerprint": "fingerprint-payroll-shared",
            "findings": [{"type": "ssn", "count": 3}],
            "action_taken": "block_transfer",
            "action_result": "blocked",
        }
    )
    await send_event(
        {
            "machine_id": second_machine_id,
            "timestamp": older_high.isoformat(),
            "file_path": "E:/USB/payroll-q2-copy.xlsx",
            "file_name": "payroll-q2-copy.xlsx",
            "file_ext": ".xlsx",
            "file_size": 4096,
            "risk_level": "critical",
            "risk_score": 12,
            "destination": "usb",
            "destination_type": "usb",
            "destination_label": "Kingston USB",
            "actor_username": "usb-risk-user",
            "file_hash": "hash-payroll-shared",
            "content_fingerprint": "fingerprint-payroll-shared",
            "findings": [{"type": "ssn", "count": 5}],
            "action_taken": "block_transfer",
            "action_result": "blocked",
        }
    )

    await send_event(
        {
            "machine_id": dlp_machine["machine_id"],
            "timestamp": (datetime.now(timezone.utc) - timedelta(days=1)).isoformat(),
            "file_path": "C:/exports/customer-list.csv",
            "file_name": "customer-list.csv",
            "file_ext": ".csv",
            "file_size": 1400,
            "risk_level": "medium",
            "risk_score": 6,
            "destination": "email",
            "destination_type": "email",
            "destination_label": "Mail client",
            "actor_username": "warn-user",
            "findings": [{"type": "customer_record", "count": 2}],
            "action_taken": "warn_user",
            "action_result": "warning_shown",
        }
    )
    await send_event(
        {
            "machine_id": dlp_machine["machine_id"],
            "timestamp": _now_iso(),
            "file_path": "C:/exports/customer-list.csv",
            "file_name": "customer-list.csv",
            "file_ext": ".csv",
            "file_size": 1400,
            "risk_level": "high",
            "risk_score": 8,
            "destination": "email",
            "destination_type": "email",
            "destination_label": "Mail client",
            "actor_username": "warn-user",
            "findings": [{"type": "customer_record", "count": 2}],
            "action_taken": "warn_user",
            "action_result": "warning_shown",
        }
    )
    await send_event(
        {
            "machine_id": dlp_machine["machine_id"],
            "timestamp": (datetime.now(timezone.utc) - timedelta(hours=6)).isoformat(),
            "file_path": "C:/exports/customer-list-2.csv",
            "file_name": "customer-list-2.csv",
            "file_ext": ".csv",
            "file_size": 1400,
            "risk_level": "high",
            "risk_score": 8,
            "destination": "email",
            "destination_type": "email",
            "destination_label": "Mail client",
            "actor_username": "warn-user",
            "findings": [{"type": "customer_record", "count": 2}],
            "action_taken": "warn_user",
            "action_result": "warning_shown",
        }
    )

    await send_event(
        {
            "machine_id": dlp_machine["machine_id"],
            "timestamp": _now_iso(),
            "file_path": "C:/approved/hr-export.xlsx",
            "file_name": "hr-export.xlsx",
            "file_ext": ".xlsx",
            "file_size": 2048,
            "risk_level": "high",
            "risk_score": 8,
            "destination": "email",
            "destination_type": "email",
            "destination_label": "Approved partner mailbox",
            "actor_username": "approved-user",
            "findings": [{"type": "employee_record", "count": 2}],
            "action_taken": "monitor",
            "action_result": "observed",
        }
    )

    await send_event(
        {
            "machine_id": dlp_machine["machine_id"],
            "timestamp": older_low.isoformat(),
            "file_path": "C:/notes/meeting.txt",
            "file_name": "meeting.txt",
            "file_ext": ".txt",
            "file_size": 128,
            "risk_level": "low",
            "risk_score": 1,
            "destination": "local",
            "destination_type": "local",
            "destination_label": "Desktop",
            "actor_username": "low-user",
            "findings": [{"type": "keyword", "count": 1}],
            "action_taken": "monitor",
            "action_result": "observed",
        }
    )

    approved_incidents = await api.get("/api/dlp/incidents?actor_username=approved-user&limit=10", headers=headers)
    assert approved_incidents.status_code == 200, approved_incidents.text
    approved_incident = approved_incidents.json()["items"][0]
    approved_update = await api.put(
        f"/api/dlp/incidents/{approved_incident['id']}",
        json={
            "state": "approved_business_use",
            "disposition": "approved_business_use",
            "resolution_reason": "Approved recurring HR export",
        },
        headers=headers,
    )
    assert approved_update.status_code == 200, approved_update.text

    summary = await api.get("/api/dlp/risk/users?window_days=90&limit=20", headers=headers)
    assert summary.status_code == 200, summary.text
    summary_payload = summary.json()
    items = summary_payload["items"]
    assert items

    by_actor = {row["actor_username"]: row for row in items}
    assert "usb-risk-user" in by_actor
    assert "warn-user" in by_actor
    assert "approved-user" in by_actor
    assert "low-user" in by_actor
    assert by_actor["usb-risk-user"]["risk_score"] > by_actor["low-user"]["risk_score"]
    assert by_actor["warn-user"]["trend"] == "rising"
    assert "repeat_warning_attempts" in by_actor["warn-user"]["reason_codes"]
    assert "approved_business_use" in by_actor["approved-user"]["reason_codes"]
    assert by_actor["approved-user"]["risk_score"] < by_actor["usb-risk-user"]["risk_score"]

    filtered = await api.get(
        f"/api/dlp/risk/users?window_days=90&machine_id={second_machine_id}&destination_type=usb",
        headers=headers,
    )
    assert filtered.status_code == 200, filtered.text
    filtered_items = filtered.json()["items"]
    assert filtered_items
    assert all(item["actor_username"] == "usb-risk-user" for item in filtered_items)

    high_only = await api.get("/api/dlp/risk/users?window_days=90&min_risk_level=high", headers=headers)
    assert high_only.status_code == 200, high_only.text
    assert high_only.json()["items"]
    assert all(item["risk_level"] in {"high", "critical"} for item in high_only.json()["items"])

    detail = await api.get("/api/dlp/risk/users/usb-risk-user?window_days=90", headers=headers)
    assert detail.status_code == 200, detail.text
    detail_payload = detail.json()
    assert detail_payload["actor_username"] == "usb-risk-user"
    assert detail_payload["blocked_event_count"] >= 2
    assert detail_payload["after_hours_event_count"] >= 1
    assert detail_payload["related_machine_count"] >= 2
    assert any(reason["code"] == "repeat_sensitive_file" for reason in detail_payload["reason_history"])
    assert detail_payload["recent_events"]
    assert detail_payload["recent_incidents"]
    assert detail_payload["recommended_actions"]
    assert detail_payload["filters_applied"]["window_days"] == 90
