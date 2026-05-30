"""Enterprise DLP persistence helpers."""

import json
from typing import Optional

from app.db.core import Connection as _Conn, get_tenant_id as _tid, utcnow


class DlpEnterpriseMethodsMixin:
    def list_dlp_policies(self, tenant_id: Optional[int] = None, scope: str = "") -> list[dict]:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                clauses = ["tenant_id = %s"]
                params = [tid]
                if scope:
                    clauses.append("scope = %s")
                    params.append(scope)
                cur.execute(
                    f"""
                    SELECT *
                    FROM dlp_policies
                    WHERE {" AND ".join(clauses)}
                    ORDER BY is_baseline DESC, priority DESC, updated_at DESC
                    """,
                    params,
                )
                return [dict(r) for r in cur.fetchall()]

    def get_dlp_policy(self, policy_id: int, tenant_id: Optional[int] = None) -> Optional[dict]:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM dlp_policies WHERE id = %s AND tenant_id = %s",
                    (policy_id, tid),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def create_dlp_policy(self, data: dict, tenant_id: Optional[int] = None) -> int:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO dlp_policies
                        (tenant_id, scope, name, description, mode, status, priority,
                         version, rollout_mode, is_baseline, is_mandatory, config,
                         published_at, published_by, created_at, updated_at)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        tid,
                        data.get("scope", "tenant_override"),
                        data.get("name", "DLP Policy"),
                        data.get("description", ""),
                        data.get("mode", "detect_then_block"),
                        data.get("status", "draft"),
                        int(data.get("priority", 100)),
                        int(data.get("version", 1)),
                        data.get("rollout_mode", "monitor_only"),
                        bool(data.get("is_baseline", False)),
                        bool(data.get("is_mandatory", False)),
                        json.dumps(data.get("config", {})),
                        data.get("published_at"),
                        data.get("published_by", ""),
                        utcnow(),
                        utcnow(),
                    ),
                )
                return cur.fetchone()["id"]

    def update_dlp_policy(self, policy_id: int, data: dict, tenant_id: Optional[int] = None) -> bool:
        tid = int(tenant_id or _tid())
        allowed = {
            "name", "description", "mode", "status", "priority", "version",
            "rollout_mode", "is_baseline", "is_mandatory", "config",
            "published_at", "published_by", "scope",
        }
        sets = []
        params = []
        for key, value in data.items():
            if key not in allowed:
                continue
            sets.append(f"{key} = %s")
            if key == "config":
                params.append(json.dumps(value or {}))
            else:
                params.append(value)
        if not sets:
            return False
        sets.append("updated_at = %s")
        params.append(utcnow())
        params.extend([policy_id, tid])
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE dlp_policies SET {', '.join(sets)} WHERE id = %s AND tenant_id = %s",
                    params,
                )
                return cur.rowcount > 0

    def list_dlp_rules(self, policy_id: Optional[int] = None, tenant_id: Optional[int] = None) -> list[dict]:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                if policy_id is None:
                    cur.execute(
                        "SELECT * FROM dlp_rules WHERE tenant_id = %s ORDER BY enabled DESC, id ASC",
                        (tid,),
                    )
                else:
                    cur.execute(
                        "SELECT * FROM dlp_rules WHERE tenant_id = %s AND policy_id = %s ORDER BY enabled DESC, id ASC",
                        (tid, policy_id),
                    )
                return [dict(r) for r in cur.fetchall()]

    def create_dlp_rule(self, data: dict, tenant_id: Optional[int] = None) -> int:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO dlp_rules
                        (tenant_id, policy_id, name, description, classifier_ids,
                         channels, destination_scope, severity, confidence, action,
                         mandatory, enabled, config, created_at, updated_at)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        tid,
                        data.get("policy_id"),
                        data.get("name", "DLP Rule"),
                        data.get("description", ""),
                        json.dumps(data.get("classifier_ids", [])),
                        json.dumps(data.get("channels", ["file"])),
                        json.dumps(data.get("destination_scope", ["any"])),
                        data.get("severity", "medium"),
                        float(data.get("confidence", 0.8)),
                        data.get("action", "monitor"),
                        bool(data.get("mandatory", False)),
                        bool(data.get("enabled", True)),
                        json.dumps(data.get("config", {})),
                        utcnow(),
                        utcnow(),
                    ),
                )
                return cur.fetchone()["id"]

    def update_dlp_rule(self, rule_id: int, data: dict, tenant_id: Optional[int] = None) -> bool:
        tid = int(tenant_id or _tid())
        json_keys = {"classifier_ids", "channels", "destination_scope", "config"}
        allowed = json_keys | {"name", "description", "severity", "confidence", "action", "mandatory", "enabled", "policy_id"}
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
        params.extend([rule_id, tid])
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE dlp_rules SET {', '.join(sets)} WHERE id = %s AND tenant_id = %s",
                    params,
                )
                return cur.rowcount > 0

    def list_dlp_classifiers(self, tenant_id: Optional[int] = None, include_disabled: bool = True) -> list[dict]:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                if include_disabled:
                    cur.execute("SELECT * FROM dlp_classifiers WHERE tenant_id = %s ORDER BY builtin DESC, name ASC", (tid,))
                else:
                    cur.execute("SELECT * FROM dlp_classifiers WHERE tenant_id = %s AND enabled = TRUE ORDER BY builtin DESC, name ASC", (tid,))
                return [dict(r) for r in cur.fetchall()]

    def get_dlp_classifier_by_name(self, name: str, tenant_id: Optional[int] = None) -> Optional[dict]:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM dlp_classifiers WHERE tenant_id = %s AND name = %s",
                    (tid, name),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def create_dlp_classifier(self, data: dict, tenant_id: Optional[int] = None) -> int:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO dlp_classifiers
                        (tenant_id, scope, name, category, classifier_type, builtin,
                         enabled, severity, config, created_at, updated_at)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        tid,
                        data.get("scope", "tenant"),
                        data.get("name"),
                        data.get("category", "custom"),
                        data.get("classifier_type", "regex"),
                        bool(data.get("builtin", False)),
                        bool(data.get("enabled", True)),
                        data.get("severity", "medium"),
                        json.dumps(data.get("config", {})),
                        utcnow(),
                        utcnow(),
                    ),
                )
                return cur.fetchone()["id"]

    def update_dlp_classifier(self, classifier_id: int, data: dict, tenant_id: Optional[int] = None) -> bool:
        tid = int(tenant_id or _tid())
        json_keys = {"config"}
        allowed = {"scope", "name", "category", "classifier_type", "builtin", "enabled", "severity"} | json_keys
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
        params.extend([classifier_id, tid])
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE dlp_classifiers SET {', '.join(sets)} WHERE id = %s AND tenant_id = %s",
                    params,
                )
                return cur.rowcount > 0

    def list_dlp_exceptions(self, tenant_id: Optional[int] = None, status: str = "") -> list[dict]:
        tid = int(tenant_id or _tid())
        clauses = ["tenant_id = %s"]
        params = [tid]
        if status:
            clauses.append("status = %s")
            params.append(status)
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT * FROM dlp_exceptions WHERE {' AND '.join(clauses)} ORDER BY created_at DESC",
                    params,
                )
                return [dict(r) for r in cur.fetchall()]

    def create_dlp_exception(self, data: dict, tenant_id: Optional[int] = None) -> int:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO dlp_exceptions
                        (tenant_id, scope_type, scope_value, classifier_name, app_name,
                         destination_type, path_pattern, reason, expires_at, created_by,
                         status, metadata, created_at, updated_at)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        tid,
                        data.get("scope_type", "path"),
                        data.get("scope_value", ""),
                        data.get("classifier_name", ""),
                        data.get("app_name", ""),
                        data.get("destination_type", ""),
                        data.get("path_pattern", ""),
                        data.get("reason", ""),
                        data.get("expires_at"),
                        data.get("created_by", ""),
                        data.get("status", "active"),
                        json.dumps(data.get("metadata", {})),
                        utcnow(),
                        utcnow(),
                    ),
                )
                return cur.fetchone()["id"]

    def update_dlp_exception(self, exception_id: int, data: dict, tenant_id: Optional[int] = None) -> bool:
        tid = int(tenant_id or _tid())
        json_keys = {"metadata"}
        allowed = {"scope_type", "scope_value", "classifier_name", "app_name", "destination_type", "path_pattern", "reason", "expires_at", "created_by", "status"} | json_keys
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
        params.extend([exception_id, tid])
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE dlp_exceptions SET {', '.join(sets)} WHERE id = %s AND tenant_id = %s",
                    params,
                )
                return cur.rowcount > 0

    def create_dlp_incident(self, data: dict, tenant_id: Optional[int] = None) -> int:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO dlp_incidents
                        (tenant_id, state, severity, title, summary, policy_rule_id,
                         file_hash, content_fingerprint, machine_id, actor_username,
                         channel, destination_type, destination_label, first_seen,
                         last_seen, event_count, assignee, metadata, created_at, updated_at)
                    VALUES
                        (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (
                        tid,
                        data.get("state", "open"),
                        data.get("severity", "medium"),
                        data.get("title", "DLP Incident"),
                        data.get("summary", ""),
                        data.get("policy_rule_id"),
                        data.get("file_hash", ""),
                        data.get("content_fingerprint", ""),
                        data.get("machine_id", ""),
                        data.get("actor_username", ""),
                        data.get("channel", "file"),
                        data.get("destination_type", ""),
                        data.get("destination_label", ""),
                        data.get("first_seen", utcnow()),
                        data.get("last_seen", utcnow()),
                        int(data.get("event_count", 1)),
                        data.get("assignee", ""),
                        json.dumps(data.get("metadata", {})),
                        utcnow(),
                        utcnow(),
                    ),
                )
                return cur.fetchone()["id"]

    def update_dlp_incident(self, incident_id: int, data: dict, tenant_id: Optional[int] = None) -> bool:
        tid = int(tenant_id or _tid())
        json_keys = {"metadata"}
        allowed = {"state", "severity", "title", "summary", "policy_rule_id", "file_hash", "content_fingerprint", "machine_id", "actor_username", "channel", "destination_type", "destination_label", "first_seen", "last_seen", "event_count", "assignee"} | json_keys
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
                    f"UPDATE dlp_incidents SET {', '.join(sets)} WHERE id = %s AND tenant_id = %s",
                    params,
                )
                return cur.rowcount > 0

    def get_dlp_incident(self, incident_id: int, tenant_id: Optional[int] = None) -> Optional[dict]:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM dlp_incidents WHERE id = %s AND tenant_id = %s", (incident_id, tid))
                row = cur.fetchone()
                return dict(row) if row else None

    def list_dlp_incidents(
        self,
        tenant_id: Optional[int] = None,
        state: str = "",
        severity: str = "",
        assignee: str = "",
        limit: int = 50,
        offset: int = 0,
        actor_username: str = "",
        machine_id: str = "",
        file_hash: str = "",
        content_fingerprint: str = "",
        destination_type: str = "",
        disposition: str = "",
        date_from: str = "",
        date_to: str = "",
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
        if actor_username:
            clauses.append("actor_username = %s")
            params.append(actor_username)
        if machine_id:
            clauses.append("machine_id = %s")
            params.append(machine_id)
        if file_hash:
            clauses.append("file_hash = %s")
            params.append(file_hash)
        elif content_fingerprint:
            clauses.append("content_fingerprint = %s")
            params.append(content_fingerprint)
        if destination_type:
            clauses.append("destination_type = %s")
            params.append(destination_type)
        if disposition:
            clauses.append("COALESCE(metadata->>'disposition', '') = %s")
            params.append(disposition)
        if date_from:
            clauses.append("last_seen >= %s")
            params.append(date_from)
        if date_to:
            clauses.append("last_seen <= %s")
            params.append(date_to)
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT *
                    FROM dlp_incidents
                    WHERE {' AND '.join(clauses)}
                    ORDER BY last_seen DESC
                    LIMIT %s OFFSET %s
                    """,
                    params + [limit, offset],
                )
                return [dict(r) for r in cur.fetchall()]

    def count_dlp_incidents(
        self,
        tenant_id: Optional[int] = None,
        state: str = "",
        severity: str = "",
        assignee: str = "",
        actor_username: str = "",
        machine_id: str = "",
        file_hash: str = "",
        content_fingerprint: str = "",
        destination_type: str = "",
        disposition: str = "",
        date_from: str = "",
        date_to: str = "",
    ) -> int:
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
        if actor_username:
            clauses.append("actor_username = %s")
            params.append(actor_username)
        if machine_id:
            clauses.append("machine_id = %s")
            params.append(machine_id)
        if file_hash:
            clauses.append("file_hash = %s")
            params.append(file_hash)
        elif content_fingerprint:
            clauses.append("content_fingerprint = %s")
            params.append(content_fingerprint)
        if destination_type:
            clauses.append("destination_type = %s")
            params.append(destination_type)
        if disposition:
            clauses.append("COALESCE(metadata->>'disposition', '') = %s")
            params.append(disposition)
        if date_from:
            clauses.append("last_seen >= %s")
            params.append(date_from)
        if date_to:
            clauses.append("last_seen <= %s")
            params.append(date_to)
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"SELECT COUNT(*) AS c FROM dlp_incidents WHERE {' AND '.join(clauses)}",
                    params,
                )
                return cur.fetchone()["c"]

    def add_dlp_incident_note(self, incident_id: int, note: str, created_by: str, tenant_id: Optional[int] = None) -> int:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO dlp_incident_notes
                        (tenant_id, incident_id, note, created_by, created_at)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (tid, incident_id, note, created_by, utcnow()),
                )
                return cur.fetchone()["id"]

    def list_dlp_incident_notes(self, incident_id: int, tenant_id: Optional[int] = None) -> list[dict]:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM dlp_incident_notes WHERE tenant_id = %s AND incident_id = %s ORDER BY created_at ASC",
                    (tid, incident_id),
                )
                return [dict(r) for r in cur.fetchall()]

    def add_dlp_incident_timeline(self, incident_id: int, action: str, actor: str, payload: dict | None = None, tenant_id: Optional[int] = None) -> int:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO dlp_incident_timeline
                        (tenant_id, incident_id, action, actor, payload, created_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                    """,
                    (tid, incident_id, action, actor, json.dumps(payload or {}), utcnow()),
                )
                return cur.fetchone()["id"]

    def list_dlp_incident_timeline(self, incident_id: int, tenant_id: Optional[int] = None) -> list[dict]:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM dlp_incident_timeline WHERE tenant_id = %s AND incident_id = %s ORDER BY created_at ASC",
                    (tid, incident_id),
                )
                return [dict(r) for r in cur.fetchall()]

    def list_related_dlp_incidents(
        self,
        incident_id: int,
        *,
        tenant_id: Optional[int] = None,
        file_hash: str = "",
        content_fingerprint: str = "",
        actor_username: str = "",
        machine_id: str = "",
        destination_type: str = "",
        destination_label: str = "",
        date_from: str = "",
        limit: int = 6,
    ) -> list[dict]:
        tid = int(tenant_id or _tid())
        clauses = ["tenant_id = %s", "id <> %s"]
        params: list = [tid, incident_id]
        identity_clauses: list[str] = []
        if file_hash:
            identity_clauses.append("file_hash = %s")
            params.append(file_hash)
        elif content_fingerprint:
            identity_clauses.append("content_fingerprint = %s")
            params.append(content_fingerprint)
        if actor_username:
            identity_clauses.append("actor_username = %s")
            params.append(actor_username)
        if machine_id:
            identity_clauses.append("machine_id = %s")
            params.append(machine_id)
        if destination_type:
            identity_clauses.append("destination_type = %s")
            params.append(destination_type)
        if destination_label:
            identity_clauses.append("destination_label = %s")
            params.append(destination_label)
        if identity_clauses:
            clauses.append("(" + " OR ".join(identity_clauses) + ")")
        if date_from:
            clauses.append("last_seen >= %s")
            params.append(date_from)
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT *
                    FROM dlp_incidents
                    WHERE {' AND '.join(clauses)}
                    ORDER BY last_seen DESC
                    LIMIT %s
                    """,
                    params + [limit],
                )
                return [dict(r) for r in cur.fetchall()]

    def list_evidence_objects_for_machine(
        self,
        machine_id: str,
        *,
        tenant_id: Optional[int] = None,
        limit: int = 8,
    ) -> list[dict]:
        tid = int(tenant_id or _tid())
        if not machine_id:
            return []
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT *
                    FROM evidence_objects
                    WHERE tenant_id = %s AND machine_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s
                    """,
                    (tid, machine_id, limit),
                )
                return [dict(r) for r in cur.fetchall()]

    def count_recent_dlp_history_metrics(self, *, tenant_id: Optional[int] = None, horizon_days: int = 90) -> dict:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM dlp_incidents WHERE tenant_id = %s AND last_seen >= NOW() - (%s || ' days')::interval) AS incident_count,
                        (SELECT COUNT(*) FROM dlp_incident_notes n JOIN dlp_incidents i ON i.id = n.incident_id
                            WHERE n.tenant_id = %s AND i.last_seen >= NOW() - (%s || ' days')::interval) AS note_count,
                        (SELECT COUNT(*) FROM dlp_incident_timeline t JOIN dlp_incidents i ON i.id = t.incident_id
                            WHERE t.tenant_id = %s AND i.last_seen >= NOW() - (%s || ' days')::interval) AS timeline_count,
                        (SELECT COUNT(*) FROM dlp_events WHERE tenant_id = %s AND timestamp >= NOW() - (%s || ' days')::interval) AS event_count
                    """,
                    (tid, horizon_days, tid, horizon_days, tid, horizon_days, tid, horizon_days),
                )
                row = dict(cur.fetchone() or {})
                return row

    def find_recent_matching_dlp_incident(
        self,
        *,
        tenant_id: Optional[int] = None,
        policy_rule_id: Optional[int] = None,
        file_hash: str = "",
        content_fingerprint: str = "",
        machine_id: str = "",
        actor_username: str = "",
        channel: str = "",
        window_minutes: int = 240,
    ) -> Optional[dict]:
        tid = int(tenant_id or _tid())
        clauses = ["tenant_id = %s", "last_seen >= NOW() - (%s || ' minutes')::interval"]
        params = [tid, str(window_minutes)]
        if policy_rule_id:
            clauses.append("policy_rule_id = %s")
            params.append(policy_rule_id)
        if file_hash:
            clauses.append("file_hash = %s")
            params.append(file_hash)
        elif content_fingerprint:
            clauses.append("content_fingerprint = %s")
            params.append(content_fingerprint)
        if machine_id:
            clauses.append("machine_id = %s")
            params.append(machine_id)
        if actor_username:
            clauses.append("actor_username = %s")
            params.append(actor_username)
        if channel:
            clauses.append("channel = %s")
            params.append(channel)
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"""
                    SELECT *
                    FROM dlp_incidents
                    WHERE {' AND '.join(clauses)}
                    ORDER BY last_seen DESC
                    LIMIT 1
                    """,
                    params,
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def get_latest_dlp_diagnostics_for_machine(self, machine_id: str, tenant_id: Optional[int] = None) -> Optional[dict]:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT machine_id, actor_username, app_name, channel, policy_version,
                           action_taken, action_result, destination_type, destination_label,
                           confidence, timestamp, masked_evidence
                    FROM dlp_events
                    WHERE tenant_id = %s AND machine_id = %s
                    ORDER BY timestamp DESC
                    LIMIT 1
                    """,
                    (tid, machine_id),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def upsert_dlp_file_inventory(self, data: dict, tenant_id: Optional[int] = None) -> int:
        tid = int(tenant_id or _tid())
        machine_id = data.get("machine_id", "")
        machine_ref = self.get_machine_ref(machine_id, tid)
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO dlp_file_inventory(
                        tenant_id, machine_id, machine_ref, root_id, scan_job_id, absolute_path, normalized_path,
                        file_name, extension, size_bytes, mtime_ns, ctime_ns, owner_name,
                        sha256, content_fingerprint, scan_version, scan_status, inspect_status,
                        inspect_reason, parser_type, findings_summary, label_summary,
                        first_seen_at, last_seen_at, last_scanned_at, uploaded_at, created_at, updated_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s,
                        %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT(tenant_id, machine_id, normalized_path) DO UPDATE SET
                        machine_ref = EXCLUDED.machine_ref,
                        root_id = EXCLUDED.root_id,
                        scan_job_id = EXCLUDED.scan_job_id,
                        absolute_path = EXCLUDED.absolute_path,
                        file_name = EXCLUDED.file_name,
                        extension = EXCLUDED.extension,
                        size_bytes = EXCLUDED.size_bytes,
                        mtime_ns = EXCLUDED.mtime_ns,
                        ctime_ns = EXCLUDED.ctime_ns,
                        owner_name = EXCLUDED.owner_name,
                        sha256 = EXCLUDED.sha256,
                        content_fingerprint = EXCLUDED.content_fingerprint,
                        scan_version = EXCLUDED.scan_version,
                        scan_status = EXCLUDED.scan_status,
                        inspect_status = EXCLUDED.inspect_status,
                        inspect_reason = EXCLUDED.inspect_reason,
                        parser_type = EXCLUDED.parser_type,
                        findings_summary = EXCLUDED.findings_summary,
                        label_summary = EXCLUDED.label_summary,
                        last_seen_at = EXCLUDED.last_seen_at,
                        last_scanned_at = EXCLUDED.last_scanned_at,
                        uploaded_at = EXCLUDED.uploaded_at,
                        updated_at = EXCLUDED.updated_at
                    RETURNING id
                    """,
                    (
                        tid,
                        machine_id,
                        machine_ref,
                        data.get("root_id", ""),
                        data.get("scan_job_id"),
                        data.get("absolute_path", ""),
                        data.get("normalized_path", ""),
                        data.get("file_name", ""),
                        data.get("extension", ""),
                        int(data.get("size_bytes", 0) or 0),
                        int(data.get("mtime_ns", 0) or 0),
                        int(data.get("ctime_ns", 0) or 0),
                        data.get("owner_name", ""),
                        data.get("sha256", ""),
                        data.get("content_fingerprint", ""),
                        data.get("scan_version", ""),
                        data.get("scan_status", "scanned"),
                        data.get("inspect_status", "pending"),
                        data.get("inspect_reason", ""),
                        data.get("parser_type", ""),
                        json.dumps(data.get("findings_summary", {})),
                        json.dumps(data.get("label_summary", {})),
                        data.get("first_seen_at") or utcnow(),
                        data.get("last_seen_at") or utcnow(),
                        data.get("last_scanned_at") or utcnow(),
                        utcnow(),
                        utcnow(),
                        utcnow(),
                    ),
                )
                return int(cur.fetchone()["id"])

    def upsert_dlp_file_inventory_sync_status(self, data: dict, tenant_id: Optional[int] = None) -> int:
        tid = int(tenant_id or _tid())
        machine_id = data.get("machine_id", "")
        machine_ref = self.get_machine_ref(machine_id, tid)
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO dlp_file_inventory_sync_status(
                        tenant_id, machine_id, machine_ref, root_id, scan_job_id, pending_upload_count,
                        total_inventory_count, parser_failure_count, oldest_unsynced_at,
                        last_batch_at, metadata, created_at, updated_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT(tenant_id, machine_id, root_id) DO UPDATE SET
                        machine_ref = EXCLUDED.machine_ref,
                        scan_job_id = EXCLUDED.scan_job_id,
                        pending_upload_count = EXCLUDED.pending_upload_count,
                        total_inventory_count = EXCLUDED.total_inventory_count,
                        parser_failure_count = EXCLUDED.parser_failure_count,
                        oldest_unsynced_at = EXCLUDED.oldest_unsynced_at,
                        last_batch_at = EXCLUDED.last_batch_at,
                        metadata = EXCLUDED.metadata,
                        updated_at = EXCLUDED.updated_at
                    RETURNING id
                    """,
                    (
                        tid,
                        machine_id,
                        machine_ref,
                        data.get("root_id", ""),
                        data.get("scan_job_id"),
                        int(data.get("pending_upload_count", 0) or 0),
                        int(data.get("total_inventory_count", 0) or 0),
                        int(data.get("parser_failure_count", 0) or 0),
                        data.get("oldest_unsynced_at"),
                        utcnow(),
                        json.dumps(data.get("metadata", {})),
                        utcnow(),
                        utcnow(),
                    ),
                )
                row_id = int(cur.fetchone()["id"])
        self.refresh_machine_inventory_rollup(machine_id, tenant_id=tid)
        return row_id

    def refresh_machine_inventory_rollup(self, machine_id: str, tenant_id: Optional[int] = None) -> Optional[dict]:
        tid = int(tenant_id or _tid())
        machine_ref = self.get_machine_ref(machine_id, tid)
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    WITH inv AS (
                        SELECT
                            COUNT(*) AS total_inventory_count,
                            COUNT(*) FILTER (WHERE COALESCE(label_summary->>'label', '') = 'Public') AS public_count,
                            COUNT(*) FILTER (WHERE COALESCE(label_summary->>'label', '') = 'Internal') AS internal_count,
                            COUNT(*) FILTER (WHERE COALESCE(label_summary->>'label', '') = 'Sensitive') AS sensitive_count,
                            COUNT(*) FILTER (WHERE COALESCE(label_summary->>'label', '') = 'Confidential') AS confidential_count,
                            COUNT(*) FILTER (WHERE COALESCE(label_summary->>'label', '') = 'Highly Confidential') AS highly_confidential_count,
                            MAX(last_scanned_at) AS last_inventory_scan_at,
                            MAX(uploaded_at) AS last_inventory_upload_at
                        FROM dlp_file_inventory
                        WHERE tenant_id = %s AND machine_id = %s
                    ),
                    sync AS (
                        SELECT
                            COALESCE(SUM(pending_upload_count), 0) AS pending_upload_count,
                            COALESCE(SUM(parser_failure_count), 0) AS parser_failure_count,
                            MIN(oldest_unsynced_at) AS oldest_unsynced_at
                        FROM dlp_file_inventory_sync_status
                        WHERE tenant_id = %s AND machine_id = %s
                    )
                    INSERT INTO machine_inventory_rollups(
                        tenant_id, machine_id, machine_ref, total_inventory_count, public_count, internal_count,
                        sensitive_count, confidential_count, highly_confidential_count, pending_upload_count,
                        parser_failure_count, oldest_unsynced_at, last_inventory_scan_at, last_inventory_upload_at,
                        created_at, updated_at
                    )
                    SELECT
                        %s, %s, %s, inv.total_inventory_count, inv.public_count, inv.internal_count,
                        inv.sensitive_count, inv.confidential_count, inv.highly_confidential_count, sync.pending_upload_count,
                        sync.parser_failure_count, sync.oldest_unsynced_at, inv.last_inventory_scan_at, inv.last_inventory_upload_at,
                        %s, %s
                    FROM inv CROSS JOIN sync
                    ON CONFLICT(tenant_id, machine_id) DO UPDATE SET
                        machine_ref = EXCLUDED.machine_ref,
                        total_inventory_count = EXCLUDED.total_inventory_count,
                        public_count = EXCLUDED.public_count,
                        internal_count = EXCLUDED.internal_count,
                        sensitive_count = EXCLUDED.sensitive_count,
                        confidential_count = EXCLUDED.confidential_count,
                        highly_confidential_count = EXCLUDED.highly_confidential_count,
                        pending_upload_count = EXCLUDED.pending_upload_count,
                        parser_failure_count = EXCLUDED.parser_failure_count,
                        oldest_unsynced_at = EXCLUDED.oldest_unsynced_at,
                        last_inventory_scan_at = EXCLUDED.last_inventory_scan_at,
                        last_inventory_upload_at = EXCLUDED.last_inventory_upload_at,
                        updated_at = EXCLUDED.updated_at
                    RETURNING *
                    """,
                    (tid, machine_id, tid, machine_id, tid, machine_id, machine_ref, utcnow(), utcnow()),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def get_dlp_file_inventory_status(self, machine_id: str, tenant_id: Optional[int] = None) -> dict:
        tid = int(tenant_id or _tid())
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        COUNT(*) AS total_files,
                        COUNT(*) FILTER (WHERE inspect_status = 'inspected') AS inspected_files,
                        COUNT(*) FILTER (WHERE inspect_status <> 'inspected') AS uninspectable_files,
                        MAX(last_scanned_at) AS last_scanned_at,
                        MAX(uploaded_at) AS last_uploaded_at
                    FROM dlp_file_inventory
                    WHERE tenant_id = %s AND machine_id = %s
                    """,
                    (tid, machine_id),
                )
                totals = dict(cur.fetchone() or {})
                cur.execute(
                    """
                    SELECT root_id, scan_job_id, pending_upload_count, total_inventory_count,
                           parser_failure_count, oldest_unsynced_at, last_batch_at, metadata
                    FROM dlp_file_inventory_sync_status
                    WHERE tenant_id = %s AND machine_id = %s
                    ORDER BY last_batch_at DESC
                    """,
                    (tid, machine_id),
                )
                sync_rows = [dict(row) for row in cur.fetchall()]
                cur.execute(
                    "SELECT * FROM machine_inventory_rollups WHERE tenant_id = %s AND machine_id = %s",
                    (tid, machine_id),
                )
                rollup = dict(cur.fetchone() or {})
        return {
            "machine_id": machine_id,
            "totals": totals,
            "sync_status": sync_rows,
            "rollup": rollup,
        }
