"""Extracted DB methods mixin."""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from app.evidence_storage import evidence_storage
from app.db.core import (
    Connection as _Conn,
    ensure_monthly_partition,
    get_tenant_id as _tid,
    tz_safe as _tz_safe,
    utcnow,
    utcnow_iso,
)

logger = logging.getLogger("croppro.db")

class MachineMethodsMixin:

    # MACHINES â€” full CRUD
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def upsert_machine(self, data: dict):
        data = dict(data)
        data["tenant_id"] = _tid()
        for key in ("consent_timestamp", "first_seen", "last_seen"):
            if data.get(key) == "":
                data[key] = None
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO machines
                        (machine_id, tenant_id, hostname, os, os_version, username,
                         ip_address, mac_address, consent_given, consent_timestamp,
                         first_seen, last_seen, agent_version)
                    VALUES
                        (%(machine_id)s, %(tenant_id)s, %(hostname)s, %(os)s,
                         %(os_version)s, %(username)s, %(ip_address)s,
                         %(mac_address)s, %(consent_given)s,
                         %(consent_timestamp)s, %(first_seen)s,
                         %(last_seen)s, %(agent_version)s)
                    ON CONFLICT (machine_id) DO UPDATE SET
                        hostname      = EXCLUDED.hostname,
                        os            = EXCLUDED.os,
                        username      = EXCLUDED.username,
                        ip_address    = EXCLUDED.ip_address,
                        last_seen     = EXCLUDED.last_seen,
                        agent_version = EXCLUDED.agent_version
                """, data)

    def get_all_machines(self) -> List[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM machines WHERE tenant_id = %s "
                    "ORDER BY last_seen DESC NULLS LAST",
                    (_tid(),),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_recently_seen_machine_ids(self, window_seconds: int = 120) -> set[str]:
        """Tenant-scoped recent-presence helper for UI online status."""
        seconds = max(15, int(window_seconds))
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT machine_id
                    FROM machines
                    WHERE tenant_id = %s
                      AND last_seen >= NOW() - (%s || ' seconds')::interval
                    """,
                    (_tid(), seconds),
                )
                return {str(r["machine_id"]) for r in cur.fetchall() if r.get("machine_id")}

    # â”€â”€ Cross-tenant helpers (license seat enforcement) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # These intentionally do NOT filter by tenant because the license cap
    # applies to the whole install, not a single tenant.

    def count_total_machines(self) -> int:
        """Total machines across ALL tenants (license-level metric)."""
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS c FROM machines")
                row = cur.fetchone()
                return int(row["c"]) if row else 0

    def count_active_machines(self, window_minutes: int = 15) -> int:
        """Active machines across ALL tenants (license seat enforcement)."""
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT COUNT(*) AS c
                    FROM machines
                    WHERE last_seen >= NOW() - (%s || ' minutes')::interval
                    """,
                    (window_minutes,),
                )
                row = cur.fetchone()
                return int(row["c"]) if row else 0

    def machine_exists(self, machine_id: str) -> bool:
        """Cross-tenant existence check for seat re-registration logic."""
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM machines WHERE machine_id = %s LIMIT 1",
                    (machine_id,),
                )
                return cur.fetchone() is not None

    def get_machine_tenant_id(self, machine_id: str) -> Optional[int]:
        """Cross-tenant lookup â€” returns the tenant_id a machine belongs to.
        Used by agent endpoints to set the tenant context before processing."""
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT tenant_id FROM machines WHERE machine_id = %s LIMIT 1",
                    (machine_id,),
                )
                row = cur.fetchone()
                return int(row["tenant_id"]) if row else None

    def get_machine_ref(self, machine_id: str, tenant_id: Optional[int] = None) -> Optional[int]:
        params = [machine_id]
        sql = "SELECT id FROM machines WHERE machine_id = %s"
        if tenant_id is not None:
            sql += " AND tenant_id = %s"
            params.append(int(tenant_id))
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                row = cur.fetchone()
                return int(row["id"]) if row and row.get("id") is not None else None

    # â”€â”€ Tenant-scoped machine methods â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def get_machine(self, machine_id: str) -> Optional[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM machines WHERE machine_id = %s AND tenant_id = %s",
                    (machine_id, _tid()),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def update_machine_field(self, machine_id: str, field: str, value):
        """Update a single whitelisted column on a machine row."""
        ALLOWED = {
            "hostname", "os", "os_version", "username", "ip_address",
            "mac_address", "consent_given", "consent_timestamp",
            "first_seen", "last_seen", "agent_version",
            "cpu_percent", "memory_percent", "active_app", "idle_seconds",
            "geo_country", "geo_country_code", "geo_city",
            "geo_isp", "geo_org", "geo_lat", "geo_lon",
        }
        if field not in ALLOWED:
            raise ValueError(f"Field '{field}' is not updatable")
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE machines SET {field} = %s "
                    f"WHERE machine_id = %s AND tenant_id = %s",
                    (value, machine_id, _tid()),
                )

    def update_machine(self, machine_id: str, data: dict) -> bool:
        EDITABLE = {"hostname", "username", "os", "os_version", "ip_address"}
        data = {k: v for k, v in data.items() if k in EDITABLE}
        if not data:
            return False
        sets = ", ".join(f"{k} = %s" for k in data)
        vals = list(data.values()) + [machine_id, _tid()]
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE machines SET {sets} WHERE machine_id = %s AND tenant_id = %s",
                    vals,
                )
                return cur.rowcount > 0

    def delete_machine(self, machine_id: str) -> bool:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM machines WHERE machine_id = %s AND tenant_id = %s",
                    (machine_id, _tid()),
                )
                return cur.rowcount > 0

    def update_machine_heartbeat(self, machine_id: str, data: dict):
        geo = data.get("_geo", {}) or {}
        agent_health = data.get("agent_health")
        agent_health_json = json.dumps(agent_health) if isinstance(agent_health, dict) else None
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE machines
                    SET last_seen        = %s,
                        cpu_percent      = %s,
                        memory_percent   = %s,
                        active_app       = %s,
                        idle_seconds     = %s,
                        geo_country      = COALESCE(NULLIF(%s, ''), geo_country),
                        geo_country_code = COALESCE(NULLIF(%s, ''), geo_country_code),
                        geo_city         = COALESCE(NULLIF(%s, ''), geo_city),
                        geo_isp          = COALESCE(NULLIF(%s, ''), geo_isp),
                        geo_org          = COALESCE(NULLIF(%s, ''), geo_org),
                        geo_lat          = COALESCE(%s, geo_lat),
                        geo_lon          = COALESCE(%s, geo_lon),
                        agent_health     = COALESCE(%s::jsonb, agent_health)
                    WHERE machine_id = %s AND tenant_id = %s
                """, (
                    utcnow(),
                    data.get("cpu_percent",    0),
                    data.get("memory_percent", 0),
                    data.get("active_app",     ""),
                    data.get("idle_seconds",   0),
                    geo.get("geo_country",      ""),
                    geo.get("geo_country_code", ""),
                    geo.get("geo_city",         ""),
                    geo.get("geo_isp",          ""),
                    geo.get("geo_org",          ""),
                    geo.get("geo_lat"),
                    geo.get("geo_lon"),
                    agent_health_json,
                    machine_id,
                    _tid(),
                ))

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # BROWSER ACTIVITY â€” create / read / delete
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def insert_browser_activity(self, data: dict):
        data["tenant_id"] = _tid()
        data["machine_ref"] = self.get_machine_ref(data.get("machine_id", ""), data["tenant_id"])
        data["timestamp"] = data.get("timestamp") or utcnow()
        ensure_monthly_partition("browser_activity", data.get("timestamp"))
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO browser_activity
                        (tenant_id, machine_id, machine_ref, timestamp, browser, url, title,
                         domain, duration_seconds)
                    VALUES
                        (%(tenant_id)s, %(machine_id)s, %(machine_ref)s, %(timestamp)s, %(browser)s,
                         %(url)s, %(title)s, %(domain)s, %(duration_seconds)s)
                """, data)

    def get_browser_history(self, machine_id: str, limit: int = 100,
                             search: str = "", date: str = "", offset: int = 0) -> List[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                parts  = ["machine_id = %s", "tenant_id = %s"]
                params: list = [machine_id, _tid()]
                if search:
                    parts.append("(url ILIKE %s OR title ILIKE %s OR domain ILIKE %s)")
                    s = f"%{search}%"
                    params += [s, s, s]
                if date:
                    parts.append("timestamp::date = %s")
                    params.append(date)
                cur.execute(
                    f"SELECT * FROM browser_activity WHERE {' AND '.join(parts)} "
                    f"ORDER BY timestamp DESC LIMIT %s OFFSET %s",
                    params + [limit, offset]
                )
                return [dict(r) for r in cur.fetchall()]

    def count_browser_history(self, machine_id: str, search: str = "", date: str = "") -> int:
        with _Conn() as conn:
            with conn.cursor() as cur:
                parts = ["machine_id = %s", "tenant_id = %s"]
                params: list = [machine_id, _tid()]
                if search:
                    parts.append("(url ILIKE %s OR title ILIKE %s OR domain ILIKE %s)")
                    s = f"%{search}%"
                    params += [s, s, s]
                if date:
                    parts.append("timestamp::date = %s")
                    params.append(date)
                cur.execute(
                    f"SELECT COUNT(*) AS total FROM browser_activity WHERE {' AND '.join(parts)}",
                    params,
                )
                row = cur.fetchone()
                return int((dict(row) if row else {}).get("total") or 0)

    def delete_browser_activity(self, record_id: int) -> bool:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM browser_activity WHERE id = %s AND tenant_id = %s",
                    (record_id, _tid()),
                )
                return cur.rowcount > 0

    def delete_browser_activity_for_machine(self, machine_id: str,
                                              before_date: Optional[str] = None) -> int:
        with _Conn() as conn:
            with conn.cursor() as cur:
                if before_date:
                    cur.execute(
                        "DELETE FROM browser_activity WHERE machine_id = %s "
                        "AND timestamp::date < %s AND tenant_id = %s",
                        (machine_id, before_date, _tid()),
                    )
                else:
                    cur.execute(
                        "DELETE FROM browser_activity WHERE machine_id = %s AND tenant_id = %s",
                        (machine_id, _tid()),
                    )
                return cur.rowcount

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # APP ACTIVITY â€” create / read / delete
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def insert_app_activity(self, data: dict):
        data["tenant_id"] = _tid()
        data["machine_ref"] = self.get_machine_ref(data.get("machine_id", ""), data["tenant_id"])
        data["timestamp"] = data.get("timestamp") or utcnow()
        ensure_monthly_partition("app_activity", data.get("timestamp"))
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO app_activity
                        (tenant_id, machine_id, machine_ref, timestamp, app_name, window_title,
                         process_name, duration_seconds, is_active)
                    VALUES
                        (%(tenant_id)s, %(machine_id)s, %(machine_ref)s, %(timestamp)s, %(app_name)s,
                         %(window_title)s, %(process_name)s, %(duration_seconds)s,
                         %(is_active)s)
                """, data)

    def get_app_usage(
        self,
        machine_id: str,
        date: Optional[str] = None,
        search: str = "",
        limit: Optional[int] = 20,
        offset: int = 0,
    ) -> List[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                params: list = [machine_id, _tid()]
                filters = ["machine_id = %s", "tenant_id = %s"]
                if date:
                    filters.append("timestamp::date = %s")
                    params.append(date)
                if search:
                    filters.append("(app_name ILIKE %s OR process_name ILIKE %s OR window_title ILIKE %s)")
                    s = f"%{search}%"
                    params += [s, s, s]
                where = " AND ".join(filters)
                limit_sql = ""
                if limit is not None:
                    limit_sql = " LIMIT %s OFFSET %s"
                    params += [limit, offset]

                cur.execute(f"""
                    SELECT app_name, process_name,
                           SUM(duration_seconds) AS total_seconds,
                           COUNT(*) AS sessions
                    FROM app_activity
                    WHERE {where}
                    GROUP BY app_name, process_name
                    ORDER BY total_seconds DESC
                    {limit_sql}
                """, params)
                return [dict(r) for r in cur.fetchall()]

    def count_app_usage(self, machine_id: str, date: Optional[str] = None, search: str = "") -> int:
        with _Conn() as conn:
            with conn.cursor() as cur:
                params: list = [machine_id, _tid()]
                filters = ["machine_id = %s", "tenant_id = %s"]
                if date:
                    filters.append("timestamp::date = %s")
                    params.append(date)
                if search:
                    filters.append("(app_name ILIKE %s OR process_name ILIKE %s OR window_title ILIKE %s)")
                    s = f"%{search}%"
                    params += [s, s, s]
                where = " AND ".join(filters)
                cur.execute(f"""
                    SELECT COUNT(*) AS total
                    FROM (
                        SELECT 1
                        FROM app_activity
                        WHERE {where}
                        GROUP BY app_name, process_name
                    ) grouped_apps
                """, params)
                row = cur.fetchone()
                return int((dict(row) if row else {}).get("total") or 0)

    def delete_app_activity(self, record_id: int) -> bool:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM app_activity WHERE id = %s AND tenant_id = %s",
                    (record_id, _tid()),
                )
                return cur.rowcount > 0

    def delete_app_activity_for_machine(self, machine_id: str,
                                          before_date: Optional[str] = None) -> int:
        with _Conn() as conn:
            with conn.cursor() as cur:
                if before_date:
                    cur.execute(
                        "DELETE FROM app_activity WHERE machine_id = %s "
                        "AND timestamp::date < %s AND tenant_id = %s",
                        (machine_id, before_date, _tid()),
                    )
                else:
                    cur.execute(
                        "DELETE FROM app_activity WHERE machine_id = %s AND tenant_id = %s",
                        (machine_id, _tid()),
                    )
                return cur.rowcount

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # SCREENSHOTS â€” create / read / delete
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def insert_screenshot(self, data: dict):
        tenant_id = _tid()
        machine_id = data.get("machine_id", "")
        machine_ref = self.get_machine_ref(machine_id, tenant_id)
        stored = evidence_storage.store_base64(
            base64_data=data.get("image_data", ""),
            tenant_id=tenant_id,
            machine_id=machine_id or "unknown",
            category="screenshots",
            filename_hint="capture.png",
        )
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO evidence_objects
                        (tenant_id, machine_id, machine_ref, category, evidence_classification,
                         content_type, storage_backend, storage_key, sha256, size_bytes,
                         retention_status, metadata, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        tenant_id,
                        machine_id,
                        machine_ref,
                        "screenshots",
                        "screen_capture",
                        "image/png",
                        stored.backend,
                        stored.storage_key,
                        stored.sha256,
                        stored.size_bytes,
                        "active",
                        json.dumps({"trigger": data.get("trigger", "scheduled")}),
                        utcnow(),
                        utcnow(),
                    ),
                )
                evidence_id = cur.fetchone()["id"]
                cur.execute("""
                    INSERT INTO screenshots
                        (tenant_id, machine_id, machine_ref, timestamp, image_data, trigger,
                         evidence_id, storage_key, storage_backend, sha256, size_bytes, content_type)
                    VALUES (%s, %s, %s, %s, '', %s, %s, %s, %s, %s, %s, %s)
                """, (
                    tenant_id,
                    machine_id,
                    machine_ref,
                    data.get("timestamp"),
                    data.get("trigger", "scheduled"),
                    evidence_id,
                    stored.storage_key,
                    stored.backend,
                    stored.sha256,
                    stored.size_bytes,
                    "image/png",
                ))

    def insert_input_activity(self, data: dict):
        row = dict(data)
        row["tenant_id"] = _tid()
        row["machine_ref"] = self.get_machine_ref(row.get("machine_id", ""), row["tenant_id"])
        ph = row.get("pattern_hashes", [])
        if isinstance(ph, list):
            row["pattern_hashes"] = json.dumps(ph)
        elif not isinstance(row.get("pattern_hashes"), str):
            row["pattern_hashes"] = "[]"
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO input_activity
                        (tenant_id, machine_id, machine_ref, timestamp, bucket_start, bucket_end,
                         process_name, window_title, key_event_count, mouse_click_count,
                         mouse_scroll_count, pattern_hashes, ngram_size)
                    VALUES
                        (%(tenant_id)s, %(machine_id)s, %(machine_ref)s, %(timestamp)s, %(bucket_start)s,
                         %(bucket_end)s, %(process_name)s, %(window_title)s,
                         %(key_event_count)s, %(mouse_click_count)s,
                         %(mouse_scroll_count)s, %(pattern_hashes)s, %(ngram_size)s)
                """, row)

    def get_input_activity(self, machine_id: str, limit: int = 100,
                           date: str = "", search: str = "") -> List[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                parts = ["machine_id = %s", "tenant_id = %s"]
                params: list = [machine_id, _tid()]
                if date:
                    parts.append("timestamp::date = %s")
                    params.append(date)
                if search:
                    parts.append("(process_name ILIKE %s OR window_title ILIKE %s)")
                    s = f"%{search}%"
                    params += [s, s]
                cur.execute(
                    f"SELECT * FROM input_activity WHERE {' AND '.join(parts)} "
                    f"ORDER BY timestamp DESC LIMIT %s",
                    params + [limit],
                )
                rows = [dict(r) for r in cur.fetchall()]
        for r in rows:
            try:
                raw = r.get("pattern_hashes")
                r["pattern_hashes"] = json.loads(raw) if raw else []
            except Exception:
                r["pattern_hashes"] = []
        return rows

    # â”€â”€ Storage quota enforcement â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def get_tenant_screenshot_bytes(self, tenant_id: Optional[int] = None) -> int:
        """Total stored screenshot bytes for a tenant."""
        tid = tenant_id if tenant_id is not None else _tid()
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COALESCE(SUM(CASE WHEN size_bytes > 0 THEN size_bytes ELSE OCTET_LENGTH(image_data) END), 0) AS bytes "
                    "FROM screenshots WHERE tenant_id = %s",
                    (tid,),
                )
                row = cur.fetchone()
                return int((dict(row) if row else {}).get("bytes") or 0)

    def enforce_screenshot_quota(self, tenant_id: int, max_bytes: int,
                                 batch: int = 50) -> int:
        """
        Oldest-first GC for a tenant's screenshots. Deletes in batches of
        `batch` until usage is back under `max_bytes`. Returns the number
        of screenshots deleted. Safe to call concurrently â€” each batch is
        a single SQL DELETE so there's no race between SELECT and DELETE.
        """
        if max_bytes <= 0:
            return 0
        used = self.get_tenant_screenshot_bytes(tenant_id)
        if used <= max_bytes:
            return 0
        deleted = 0
        for _ in range(200):
            with _Conn() as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT id, storage_key, evidence_id
                        FROM screenshots
                        WHERE tenant_id = %s
                        ORDER BY timestamp ASC
                        LIMIT %s
                        """,
                        (tenant_id, batch),
                    )
                    rows = [dict(r) for r in cur.fetchall()]
                    if not rows:
                        break
                    ids = [row["id"] for row in rows]
                    cur.execute("DELETE FROM screenshots WHERE id = ANY(%s)", (ids,))
                    evidence_ids = [row["evidence_id"] for row in rows if row.get("evidence_id")]
                    if evidence_ids:
                        cur.execute(
                            "DELETE FROM evidence_objects WHERE id = ANY(%s) AND tenant_id = %s",
                            (evidence_ids, tenant_id),
                        )
            if not rows:
                break
            for row in rows:
                if row.get("storage_key"):
                    evidence_storage.delete(row["storage_key"])
            deleted += len(rows)
            used = self.get_tenant_screenshot_bytes(tenant_id)
            if used <= max_bytes:
                break
        return deleted

    def get_screenshots(self, machine_id: str, limit: int = 20) -> List[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, machine_id, timestamp, trigger
                    FROM screenshots WHERE machine_id = %s AND tenant_id = %s
                    ORDER BY timestamp DESC LIMIT %s
                """, (machine_id, _tid(), limit))
                return [dict(r) for r in cur.fetchall()]

    def get_latest_screenshot(self, machine_id: str) -> Optional[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT * FROM screenshots
                    WHERE machine_id = %s AND tenant_id = %s
                    ORDER BY timestamp DESC LIMIT 1
                """, (machine_id, _tid()))
                row = cur.fetchone()
                if not row:
                    return None
                payload = dict(row)
                if payload.get("storage_key"):
                    try:
                        payload["image_data"] = evidence_storage.load_base64(payload["storage_key"])
                    except FileNotFoundError:
                        payload["image_data"] = ""
                return payload

    def delete_screenshot(self, screenshot_id: int) -> bool:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT storage_key, evidence_id FROM screenshots WHERE id = %s AND tenant_id = %s",
                    (screenshot_id, _tid()),
                )
                row = cur.fetchone()
                if not row:
                    return False
                cur.execute(
                    "DELETE FROM screenshots WHERE id = %s AND tenant_id = %s",
                    (screenshot_id, _tid()),
                )
                if row.get("evidence_id"):
                    cur.execute(
                        "DELETE FROM evidence_objects WHERE id = %s AND tenant_id = %s",
                        (row["evidence_id"], _tid()),
                    )
                ok = cur.rowcount > 0
        if ok and row.get("storage_key"):
            evidence_storage.delete(row["storage_key"])
        return ok

    def delete_screenshots_for_machine(self, machine_id: str,
                                        before_date: Optional[str] = None) -> int:
        rows: list[dict] = []
        with _Conn() as conn:
            with conn.cursor() as cur:
                if before_date:
                    cur.execute(
                        "SELECT id, storage_key, evidence_id FROM screenshots WHERE machine_id = %s "
                        "AND timestamp::date < %s AND tenant_id = %s",
                        (machine_id, before_date, _tid()),
                    )
                else:
                    cur.execute(
                        "SELECT id, storage_key, evidence_id FROM screenshots WHERE machine_id = %s AND tenant_id = %s",
                        (machine_id, _tid()),
                    )
                rows = [dict(r) for r in cur.fetchall()]
                if not rows:
                    return 0
                if before_date:
                    cur.execute(
                        "DELETE FROM screenshots WHERE machine_id = %s "
                        "AND timestamp::date < %s AND tenant_id = %s",
                        (machine_id, before_date, _tid()),
                    )
                else:
                    cur.execute(
                        "DELETE FROM screenshots WHERE machine_id = %s AND tenant_id = %s",
                        (machine_id, _tid()),
                    )
                deleted = cur.rowcount
                evidence_ids = [row["evidence_id"] for row in rows if row.get("evidence_id")]
                if evidence_ids:
                    cur.execute(
                        "DELETE FROM evidence_objects WHERE id = ANY(%s) AND tenant_id = %s",
                        (evidence_ids, _tid()),
                    )
        for row in rows:
            if row.get("storage_key"):
                evidence_storage.delete(row["storage_key"])
        return deleted

    def delete_input_activity_for_machine(self, machine_id: str,
                                          before_date: Optional[str] = None) -> int:
        with _Conn() as conn:
            with conn.cursor() as cur:
                if before_date:
                    cur.execute(
                        "DELETE FROM input_activity WHERE machine_id = %s "
                        "AND timestamp::date < %s AND tenant_id = %s",
                        (machine_id, before_date, _tid()),
                    )
                else:
                    cur.execute(
                        "DELETE FROM input_activity WHERE machine_id = %s AND tenant_id = %s",
                        (machine_id, _tid()),
                    )
                return cur.rowcount

    def delete_all_activity_for_machine(self, machine_id: str) -> dict:
        counts = {}
        counts["app_activity"]     = self.delete_app_activity_for_machine(machine_id)
        counts["browser_activity"] = self.delete_browser_activity_for_machine(machine_id)
        counts["screenshots"]      = self.delete_screenshots_for_machine(machine_id)
        counts["input_activity"]    = self.delete_input_activity_for_machine(machine_id)
        return counts

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
