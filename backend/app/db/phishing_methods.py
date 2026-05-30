"""Tenant-scoped persistence helpers for phishing protection."""

import json
from typing import Optional

from app.db.core import Connection as _Conn, ensure_monthly_partition, get_tenant_id as _tid, utcnow


class PhishingMethodsMixin:
    def list_phishing_policies(self, tenant_id: Optional[int] = None, scope: str = "") -> list[dict]:
        tid = int(tenant_id or _tid())
        clauses = ["tenant_id = %s"]
        params = [tid]
        if scope:
            clauses.append("scope = %s")
            params.append(scope)
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT *
                    FROM phishing_policies
                    WHERE {" AND ".join(clauses)}
                    ORDER BY is_baseline DESC, priority DESC, updated_at DESC
                    """,
                    params,
                )
                return [dict(r) for r in cur.fetchall()]

    def get_phishing_policy(self, policy_id: int, tenant_id: Optional[int] = None) -> Optional[dict]:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM phishing_policies WHERE id = %s AND tenant_id = %s",
                    (policy_id, tid),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def create_phishing_policy(self, data: dict, tenant_id: Optional[int] = None) -> int:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO phishing_policies
                        (tenant_id, scope, name, description, status, priority, version,
                         rollout_mode, intel_mode, protected_channels, severity_thresholds,
                         allowlists, suspicious_tlds, brand_watchlist, download_risk_rules,
                         evidence_controls, config, is_baseline, is_mandatory, published_at,
                         published_by, created_at, updated_at)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        tid,
                        data.get("scope", "tenant_override"),
                        data.get("name", "Phishing Policy"),
                        data.get("description", ""),
                        data.get("status", "published"),
                        int(data.get("priority", 100)),
                        int(data.get("version", 1)),
                        data.get("rollout_mode", "warn_only"),
                        data.get("intel_mode", "intel_plus_heuristics"),
                        json.dumps(data.get("protected_channels", ["browser", "download", "desktop_link_open", "email_client_open"])),
                        json.dumps(data.get("severity_thresholds", {"medium": 55, "high": 75, "critical": 90})),
                        json.dumps(data.get("allowlists", {"domains": [], "apps": [], "users": [], "paths": []})),
                        json.dumps(data.get("suspicious_tlds", ["zip", "click", "work"])),
                        json.dumps(data.get("brand_watchlist", ["microsoft", "google", "okta"])),
                        json.dumps(data.get("download_risk_rules", {"dangerous_extensions": ["exe", "msi", "bat"], "warn_unknown_downloads": True})),
                        json.dumps(data.get("evidence_controls", {"capture_title": True, "store_masked_indicators": True, "store_url": True})),
                        json.dumps(data.get("config", {})),
                        bool(data.get("is_baseline", False)),
                        bool(data.get("is_mandatory", False)),
                        data.get("published_at"),
                        data.get("published_by", ""),
                        utcnow(),
                        utcnow(),
                    ),
                )
                return cur.fetchone()["id"]

    def update_phishing_policy(self, policy_id: int, data: dict, tenant_id: Optional[int] = None) -> bool:
        tid = int(tenant_id or _tid())
        json_keys = {
            "protected_channels",
            "severity_thresholds",
            "allowlists",
            "suspicious_tlds",
            "brand_watchlist",
            "download_risk_rules",
            "evidence_controls",
            "config",
        }
        allowed = {
            "scope", "name", "description", "status", "priority", "version",
            "rollout_mode", "intel_mode", "is_baseline", "is_mandatory",
            "published_at", "published_by",
        } | json_keys
        sets = []
        params = []
        for key, value in data.items():
            if key not in allowed:
                continue
            sets.append(f"{key} = %s")
            params.append(json.dumps(value) if key in json_keys else value)
        if not sets:
            return False
        sets.append("updated_at = %s")
        params.append(utcnow())
        params.extend([policy_id, tid])
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE phishing_policies SET {', '.join(sets)} WHERE id = %s AND tenant_id = %s",
                    params,
                )
                return cur.rowcount > 0

    def list_phishing_allowlist_exceptions(self, tenant_id: Optional[int] = None) -> list[dict]:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM phishing_allowlist_exceptions WHERE tenant_id = %s ORDER BY created_at DESC",
                    (tid,),
                )
                return [dict(r) for r in cur.fetchall()]

    def create_phishing_allowlist_exception(self, data: dict, tenant_id: Optional[int] = None) -> int:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO phishing_allowlist_exceptions
                        (tenant_id, domain, app_name, username, path_pattern, reason, expires_at, created_by, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        tid,
                        data.get("domain", ""),
                        data.get("app_name", ""),
                        data.get("username", ""),
                        data.get("path_pattern", ""),
                        data.get("reason", ""),
                        data.get("expires_at"),
                        data.get("created_by", ""),
                        utcnow(),
                        utcnow(),
                    ),
                )
                return cur.fetchone()["id"]

    def list_phishing_blocklist_exceptions(self, tenant_id: Optional[int] = None) -> list[dict]:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM phishing_blocklist_exceptions WHERE tenant_id = %s ORDER BY created_at DESC",
                    (tid,),
                )
                return [dict(r) for r in cur.fetchall()]

    def create_phishing_blocklist_exception(self, data: dict, tenant_id: Optional[int] = None) -> int:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO phishing_blocklist_exceptions
                        (tenant_id, domain, url_pattern, reason, expires_at, created_by, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        tid,
                        data.get("domain", ""),
                        data.get("url_pattern", ""),
                        data.get("reason", ""),
                        data.get("expires_at"),
                        data.get("created_by", ""),
                        utcnow(),
                        utcnow(),
                    ),
                )
                return cur.fetchone()["id"]

    def delete_phishing_blocklist_exception(self, blocklist_id: int, tenant_id: Optional[int] = None) -> bool:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM phishing_blocklist_exceptions WHERE id = %s AND tenant_id = %s",
                    (blocklist_id, tid),
                )
                return cur.rowcount > 0

    def delete_phishing_allowlist_exception(self, allowlist_id: int, tenant_id: Optional[int] = None) -> bool:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM phishing_allowlist_exceptions WHERE id = %s AND tenant_id = %s",
                    (allowlist_id, tid),
                )
                return cur.rowcount > 0

    def insert_phishing_event(self, data: dict, tenant_id: Optional[int] = None) -> int:
        tid = int(tenant_id or _tid())
        data = dict(data)
        data["timestamp"] = data.get("timestamp") or utcnow()
        machine_id = data.get("machine_id", "")
        ensure_monthly_partition("phishing_events", data.get("timestamp"))
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO phishing_events
                        (tenant_id, machine_id, machine_ref, timestamp, event_type, channel, url, domain,
                         page_title, app_name, process_name, remote_ip, destination_label,
                         actor_username, policy_version, policy_hash, rule_id, risk_score,
                         confidence, severity, action_taken, action_result, reason_codes,
                         evidence, screenshot_ref, unsupported_reason, incident_id, created_at)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        tid,
                        machine_id,
                        self.get_machine_ref(machine_id, tid),
                        data.get("timestamp") or utcnow(),
                        data.get("event_type", "browser_visit"),
                        data.get("channel", "browser"),
                        data.get("url", ""),
                        data.get("domain", ""),
                        data.get("page_title", ""),
                        data.get("app_name", ""),
                        data.get("process_name", ""),
                        data.get("remote_ip", ""),
                        data.get("destination_label", ""),
                        data.get("actor_username", ""),
                        int(data.get("policy_version", 1) or 1),
                        data.get("policy_hash", ""),
                        data.get("rule_id", ""),
                        float(data.get("risk_score", 0) or 0),
                        float(data.get("confidence", 0) or 0),
                        data.get("severity", "low"),
                        data.get("action_taken", "monitor"),
                        data.get("action_result", "observed"),
                        json.dumps(data.get("reason_codes", [])),
                        json.dumps(data.get("evidence", [])),
                        data.get("screenshot_ref", ""),
                        data.get("unsupported_reason", ""),
                        data.get("incident_id"),
                        utcnow(),
                    ),
                )
                return cur.fetchone()["id"]

    def update_phishing_event_incident(self, event_id: int, incident_id: int, tenant_id: Optional[int] = None) -> bool:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE phishing_events SET incident_id = %s WHERE id = %s AND tenant_id = %s",
                    (incident_id, event_id, tid),
                )
                return cur.rowcount > 0

    def list_phishing_events(self, tenant_id: Optional[int] = None, limit: int = 50, offset: int = 0) -> list[dict]:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM phishing_events
                    WHERE tenant_id = %s
                    ORDER BY timestamp DESC
                    LIMIT %s OFFSET %s
                    """,
                    (tid, limit, offset),
                )
                return [dict(r) for r in cur.fetchall()]

    def count_phishing_events(self, tenant_id: Optional[int] = None) -> int:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS c FROM phishing_events WHERE tenant_id = %s", (tid,))
                return int(cur.fetchone()["c"])

    def create_phishing_incident(self, data: dict, tenant_id: Optional[int] = None) -> int:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO phishing_incidents
                        (tenant_id, state, severity, confidence, title, summary, machine_id,
                         actor_username, app_name, process_name, channel, domain, url,
                         destination_label, rule_id, warning_shown, event_count, first_seen,
                         last_seen, assignee, metadata, created_at, updated_at)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        tid,
                        data.get("state", "open"),
                        data.get("severity", "medium"),
                        float(data.get("confidence", 0) or 0),
                        data.get("title", "Phishing incident"),
                        data.get("summary", ""),
                        data.get("machine_id", ""),
                        data.get("actor_username", ""),
                        data.get("app_name", ""),
                        data.get("process_name", ""),
                        data.get("channel", "browser"),
                        data.get("domain", ""),
                        data.get("url", ""),
                        data.get("destination_label", ""),
                        data.get("rule_id", ""),
                        bool(data.get("warning_shown", False)),
                        int(data.get("event_count", 1) or 1),
                        data.get("first_seen") or utcnow(),
                        data.get("last_seen") or utcnow(),
                        data.get("assignee", ""),
                        json.dumps(data.get("metadata", {})),
                        utcnow(),
                        utcnow(),
                    ),
                )
                return cur.fetchone()["id"]

    def update_phishing_incident(self, incident_id: int, data: dict, tenant_id: Optional[int] = None) -> bool:
        tid = int(tenant_id or _tid())
        json_keys = {"metadata"}
        allowed = {
            "state", "severity", "confidence", "title", "summary", "machine_id",
            "actor_username", "app_name", "process_name", "channel", "domain", "url",
            "destination_label", "rule_id", "warning_shown", "event_count",
            "first_seen", "last_seen", "assignee",
        } | json_keys
        sets = []
        params = []
        for key, value in data.items():
            if key not in allowed:
                continue
            sets.append(f"{key} = %s")
            params.append(json.dumps(value) if key in json_keys else value)
        if not sets:
            return False
        sets.append("updated_at = %s")
        params.append(utcnow())
        params.extend([incident_id, tid])
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE phishing_incidents SET {', '.join(sets)} WHERE id = %s AND tenant_id = %s",
                    params,
                )
                return cur.rowcount > 0

    def get_phishing_incident(self, incident_id: int, tenant_id: Optional[int] = None) -> Optional[dict]:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM phishing_incidents WHERE id = %s AND tenant_id = %s", (incident_id, tid))
                row = cur.fetchone()
                return dict(row) if row else None

    def list_phishing_incidents(
        self,
        tenant_id: Optional[int] = None,
        state: str = "",
        severity: str = "",
        assignee: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict]:
        tid = int(tenant_id or _tid())
        clauses = ["tenant_id = %s"]
        params = [tid]
        if state:
            clauses.append("state = %s")
            params.append(state)
        if severity:
            clauses.append("severity = %s")
            params.append(severity)
        if assignee:
            clauses.append("assignee = %s")
            params.append(assignee)
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT *
                    FROM phishing_incidents
                    WHERE {' AND '.join(clauses)}
                    ORDER BY last_seen DESC
                    LIMIT %s OFFSET %s
                    """,
                    params + [limit, offset],
                )
                return [dict(r) for r in cur.fetchall()]

    def count_phishing_incidents(self, tenant_id: Optional[int] = None, state: str = "", severity: str = "", assignee: str = "") -> int:
        tid = int(tenant_id or _tid())
        clauses = ["tenant_id = %s"]
        params = [tid]
        if state:
            clauses.append("state = %s")
            params.append(state)
        if severity:
            clauses.append("severity = %s")
            params.append(severity)
        if assignee:
            clauses.append("assignee = %s")
            params.append(assignee)
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*) AS c FROM phishing_incidents WHERE {' AND '.join(clauses)}",
                    params,
                )
                return int(cur.fetchone()["c"])

    def add_phishing_incident_note(self, incident_id: int, note: str, created_by: str, tenant_id: Optional[int] = None) -> int:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO phishing_incident_notes
                        (tenant_id, incident_id, note, created_by, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (tid, incident_id, note, created_by, utcnow()),
                )
                return cur.fetchone()["id"]

    def list_phishing_incident_notes(self, incident_id: int, tenant_id: Optional[int] = None) -> list[dict]:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM phishing_incident_notes
                    WHERE tenant_id = %s AND incident_id = %s
                    ORDER BY created_at ASC
                    """,
                    (tid, incident_id),
                )
                return [dict(r) for r in cur.fetchall()]

    def add_phishing_incident_timeline(self, incident_id: int, action: str, actor: str, payload: dict, tenant_id: Optional[int] = None) -> int:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO phishing_incident_timeline
                        (tenant_id, incident_id, action, actor, payload, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (tid, incident_id, action, actor, json.dumps(payload or {}), utcnow()),
                )
                return cur.fetchone()["id"]

    def list_phishing_incident_timeline(self, incident_id: int, tenant_id: Optional[int] = None) -> list[dict]:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM phishing_incident_timeline
                    WHERE tenant_id = %s AND incident_id = %s
                    ORDER BY created_at ASC
                    """,
                    (tid, incident_id),
                )
                return [dict(r) for r in cur.fetchall()]

    def find_recent_matching_phishing_incident(
        self,
        tenant_id: int,
        domain: str,
        machine_id: str,
        actor_username: str,
        channel: str,
        window_minutes: int = 30,
    ) -> Optional[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM phishing_incidents
                    WHERE tenant_id = %s
                      AND domain = %s
                      AND machine_id = %s
                      AND actor_username = %s
                      AND channel = %s
                      AND last_seen >= NOW() - (%s || ' minutes')::INTERVAL
                    ORDER BY last_seen DESC
                    LIMIT 1
                    """,
                    (tenant_id, domain, machine_id, actor_username, channel, str(window_minutes)),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def get_latest_phishing_event_for_machine(self, machine_id: str, tenant_id: Optional[int] = None) -> Optional[dict]:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM phishing_events
                    WHERE tenant_id = %s AND machine_id = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (tid, machine_id),
                )
                row = cur.fetchone()
                return dict(row) if row else None
