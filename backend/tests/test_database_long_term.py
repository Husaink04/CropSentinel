from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone

import pytest

from app.db.core import clear_tenant_context, set_tenant_context

pytestmark = pytest.mark.integration


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def test_screenshot_payload_moves_out_of_postgres(api, db, make_tenant):
    tenant = make_tenant(slug="storage-tenant")
    set_tenant_context(tenant["id"])
    try:
        db.upsert_machine(
            {
                "machine_id": "m-storage",
                "hostname": "storage-host",
                "os": "Windows",
                "os_version": "11",
                "username": "operator",
                "ip_address": "10.0.0.50",
                "mac_address": "00:11:22:33:44:55",
                "consent_given": True,
                "consent_timestamp": _now_iso(),
                "first_seen": _now_iso(),
                "last_seen": _now_iso(),
                "agent_version": "1.2.0",
            }
        )
        db.insert_screenshot(
            {
                "machine_id": "m-storage",
                "timestamp": _now_iso(),
                "image_data": base64.b64encode(b"fakepngbytes").decode("ascii"),
                "trigger": "manual",
            }
        )
    finally:
        clear_tenant_context()

    set_tenant_context(tenant["id"])
    try:
        latest = db.get_latest_screenshot("m-storage")
        assert latest is not None
        assert latest["storage_key"]
        assert latest["image_data"] == base64.b64encode(b"fakepngbytes").decode("ascii")
        overview = db.get_database_overview()
        assert overview["object_backed_screenshots"] == 1
        assert overview["legacy_inline_screenshots"] == 0
    finally:
        clear_tenant_context()


async def test_settings_write_populates_typed_documents(api, db, make_tenant):
    tenant = make_tenant(slug="typed-settings")
    set_tenant_context(tenant["id"])
    try:
        db.update_settings(
            {
                "company_name": "Typed Co",
                "browser_activity_days": 21,
                "evidence_backend": "filesystem",
            }
        )
        docs = {
            "platform": db.get_config_document("platform_settings"),
            "retention": db.get_config_document("retention_settings"),
            "storage": db.get_config_document("storage_settings"),
        }
        assert docs["platform"]["payload"]["company_name"] == "Typed Co"
        assert docs["retention"]["payload"]["browser_activity_days"] == 21
        assert docs["storage"]["payload"]["evidence_backend"] == "filesystem"
    finally:
        clear_tenant_context()


async def test_retention_endpoint_reports_old_rows(api, db, make_tenant, auth_headers):
    tenant = make_tenant(slug="retention-tenant")
    headers = await auth_headers(role="admin", tenant_id=tenant["id"], username="ret-admin")
    old_ts = (datetime.now(timezone.utc) - timedelta(days=45)).isoformat()

    set_tenant_context(tenant["id"])
    try:
        db.upsert_machine(
            {
                "machine_id": "m-ret",
                "hostname": "ret-host",
                "os": "Windows",
                "os_version": "11",
                "username": "operator",
                "ip_address": "10.0.0.51",
                "mac_address": "00:11:22:33:44:56",
                "consent_given": True,
                "consent_timestamp": _now_iso(),
                "first_seen": _now_iso(),
                "last_seen": _now_iso(),
                "agent_version": "1.2.0",
            }
        )
        db.insert_browser_activity(
            {
                "machine_id": "m-ret",
                "timestamp": old_ts,
                "browser": "chrome",
                "url": "https://expired.example",
                "title": "Expired",
                "domain": "expired.example",
                "duration_seconds": 3,
            }
        )
        db.update_settings({"browser_activity_days": 30})
    finally:
        clear_tenant_context()

    resp = await api.post("/api/admin/database/retention/run?dry_run=true", headers=headers)
    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert payload["dry_run"] is True
    assert payload["deleted"]["browser_activity"] >= 1
    assert "history_impact" in payload

    overview = await api.get("/api/admin/database/overview", headers=headers)
    assert overview.status_code == 200, overview.text
    overview_payload = overview.json()
    assert "dlp_history_health" in overview_payload


async def test_browser_activity_uses_monthly_partitions(db, make_tenant):
    tenant = make_tenant(slug="partition-tenant")
    set_tenant_context(tenant["id"])
    try:
        db.upsert_machine(
            {
                "machine_id": "m-part",
                "hostname": "partition-host",
                "os": "Windows",
                "os_version": "11",
                "username": "operator",
                "ip_address": "10.0.0.52",
                "mac_address": "00:11:22:33:44:57",
                "consent_given": True,
                "consent_timestamp": _now_iso(),
                "first_seen": _now_iso(),
                "last_seen": _now_iso(),
                "agent_version": "1.2.0",
            }
        )
        db.insert_browser_activity(
            {
                "machine_id": "m-part",
                "timestamp": "2026-01-15T10:00:00+00:00",
                "browser": "chrome",
                "url": "https://partition.example",
                "title": "Partition",
                "domain": "partition.example",
                "duration_seconds": 4,
            }
        )
        from app.db.core import Connection as _Conn

        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT c.relname AS child_name
                    FROM pg_inherits i
                    JOIN pg_class c ON c.oid = i.inhrelid
                    JOIN pg_class p ON p.oid = i.inhparent
                    WHERE p.relname = 'browser_activity'
                    ORDER BY c.relname
                    """
                )
                children = [row["child_name"] for row in cur.fetchall()]
        assert "browser_activity_202601" in children
    finally:
        clear_tenant_context()
