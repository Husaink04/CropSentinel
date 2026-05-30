"""Extracted DB methods mixin."""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, List, Optional

from app.db.core import (
    Connection as _Conn,
    get_tenant_id as _tid,
    tz_safe as _tz_safe,
    utcnow,
    utcnow_iso,
)

logger = logging.getLogger("croppro.db")

_PLATFORM_DOC_TYPE = "platform_settings"
_RETENTION_DOC_TYPE = "retention_settings"
_STORAGE_DOC_TYPE = "storage_settings"

DEFAULT_RETENTION_SETTINGS = {
    "browser_activity_days": 30,
    "app_activity_days": 30,
    "input_activity_days": 14,
    "file_activity_days": 30,
    "network_activity_days": 30,
    "dlp_events_days": 90,
    "phishing_events_days": 90,
    "screenshots_days": 30,
    "deleted_backups_days": 30,
}

DEFAULT_STORAGE_SETTINGS = {
    "evidence_backend": "filesystem",
    "evidence_encryption_status": "plaintext_at_rest",
    "move_binary_evidence_out_of_db": True,
}

class SettingsUserAuditMethodsMixin:

    # SETTINGS â€” read / write
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def get_config_document(self, doc_type: str) -> Optional[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT * FROM tenant_config_documents
                    WHERE tenant_id = %s AND doc_type = %s
                    """,
                    (_tid(), doc_type),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def upsert_config_document(
        self,
        doc_type: str,
        payload: dict[str, Any],
        *,
        schema_version: int = 1,
    ) -> None:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO tenant_config_documents
                        (tenant_id, doc_type, schema_version, payload, created_at, updated_at)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (tenant_id, doc_type) DO UPDATE SET
                        schema_version = EXCLUDED.schema_version,
                        payload = EXCLUDED.payload,
                        updated_at = EXCLUDED.updated_at
                    """,
                    (_tid(), doc_type, schema_version, json.dumps(payload or {}), utcnow(), utcnow()),
                )

    def get_settings(self) -> dict:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT key, value FROM settings WHERE tenant_id = %s",
                    (_tid(),),
                )
                result: dict = {}
                for row in cur.fetchall():
                    try:
                        result[row["key"]] = json.loads(row["value"])
                    except Exception:
                        result[row["key"]] = row["value"]
                platform_doc = self.get_config_document(_PLATFORM_DOC_TYPE) or {}
                result.update((platform_doc.get("payload") or {}))
                return result

    def update_settings(self, data: dict):
        tid = _tid()
        platform_payload = dict((self.get_config_document(_PLATFORM_DOC_TYPE) or {}).get("payload") or {})
        retention_payload = dict((self.get_config_document(_RETENTION_DOC_TYPE) or {}).get("payload") or {})
        storage_payload = dict((self.get_config_document(_STORAGE_DOC_TYPE) or {}).get("payload") or {})
        with _Conn() as conn:
            with conn.cursor() as cur:
                for k, v in data.items():
                    val = json.dumps(v) if isinstance(v, (list, dict, bool)) else str(v)
                    cur.execute("""
                        INSERT INTO settings (tenant_id, key, value) VALUES (%s, %s, %s)
                        ON CONFLICT (tenant_id, key) DO UPDATE SET value = EXCLUDED.value
                    """, (tid, k, val))
                    if k.endswith("_days"):
                        retention_payload[k] = v
                    elif k.startswith("evidence_") or k.startswith("storage_"):
                        storage_payload[k] = v
                    else:
                        platform_payload[k] = v
        self.upsert_config_document(_PLATFORM_DOC_TYPE, platform_payload)
        self.upsert_config_document(_RETENTION_DOC_TYPE, retention_payload)
        self.upsert_config_document(_STORAGE_DOC_TYPE, storage_payload)

    def delete_setting(self, key: str) -> bool:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM settings WHERE tenant_id = %s AND key = %s",
                    (_tid(), key),
                )
                return cur.rowcount > 0

    def get_retention_settings(self) -> dict[str, Any]:
        payload = dict(DEFAULT_RETENTION_SETTINGS)
        doc = self.get_config_document(_RETENTION_DOC_TYPE) or {}
        payload.update(doc.get("payload") or {})
        return payload

    def get_storage_settings(self) -> dict[str, Any]:
        payload = dict(DEFAULT_STORAGE_SETTINGS)
        doc = self.get_config_document(_STORAGE_DOC_TYPE) or {}
        payload.update(doc.get("payload") or {})
        return payload

    def get_database_overview(self) -> dict[str, Any]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM machines WHERE tenant_id = %s) AS machine_count,
                        (SELECT COUNT(*) FROM evidence_objects WHERE tenant_id = %s) AS evidence_count,
                        (SELECT COUNT(*) FROM screenshots WHERE tenant_id = %s AND storage_key <> '') AS object_backed_screenshots,
                        (SELECT COUNT(*) FROM screenshots WHERE tenant_id = %s AND COALESCE(image_data, '') <> '') AS legacy_inline_screenshots,
                        (SELECT COUNT(*) FROM deleted_file_backups WHERE tenant_id = %s AND storage_key <> '') AS object_backed_backups,
                        (SELECT COUNT(*) FROM deleted_file_backups WHERE tenant_id = %s AND COALESCE(file_data, '') <> '') AS legacy_inline_backups,
                        (SELECT COUNT(*) FROM tenant_config_documents WHERE tenant_id = %s) AS config_doc_count,
                        (SELECT COUNT(*) FROM machine_inventory_rollups WHERE tenant_id = %s) AS inventory_rollup_count
                    """,
                    (_tid(), _tid(), _tid(), _tid(), _tid(), _tid(), _tid(), _tid()),
                )
                counts = dict(cur.fetchone() or {})
                cur.execute(
                    """
                    SELECT relname AS table_name,
                           pg_total_relation_size(relid) AS total_bytes
                    FROM pg_catalog.pg_statio_user_tables
                    ORDER BY total_bytes DESC
                    LIMIT 12
                    """
                )
                table_sizes = [dict(r) for r in cur.fetchall()]
                cur.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM dlp_incidents WHERE tenant_id = %s AND last_seen >= NOW() - INTERVAL '90 days') AS dlp_recent_incident_count,
                        (SELECT COUNT(*) FROM dlp_incident_notes n JOIN dlp_incidents i ON i.id = n.incident_id
                            WHERE n.tenant_id = %s AND i.last_seen >= NOW() - INTERVAL '90 days') AS dlp_recent_note_count,
                        (SELECT COUNT(*) FROM dlp_incident_timeline t JOIN dlp_incidents i ON i.id = t.incident_id
                            WHERE t.tenant_id = %s AND i.last_seen >= NOW() - INTERVAL '90 days') AS dlp_recent_timeline_count,
                        (SELECT COUNT(*) FROM evidence_objects WHERE tenant_id = %s AND category IN ('screenshots', 'deleted_backups')
                            AND created_at >= NOW() - INTERVAL '90 days') AS dlp_recent_artifact_count,
                        (SELECT COUNT(*) FROM evidence_objects WHERE tenant_id = %s AND retention_expires_at IS NOT NULL
                            AND retention_expires_at BETWEEN NOW() AND NOW() + INTERVAL '14 days') AS upcoming_expiry_count
                    """,
                    (_tid(), _tid(), _tid(), _tid(), _tid()),
                )
                dlp_history = dict(cur.fetchone() or {})
        return {
            **counts,
            "retention": self.get_retention_settings(),
            "storage": self.get_storage_settings(),
            "largest_tables": table_sizes,
            "partition_health": self.get_partition_health(),
            "dlp_history_health": dlp_history,
        }

    def get_partition_health(self) -> list[dict[str, Any]]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        p.relname AS parent_table,
                        c.relname AS partition_table,
                        pg_total_relation_size(c.oid) AS total_bytes
                    FROM pg_inherits i
                    JOIN pg_class c ON c.oid = i.inhrelid
                    JOIN pg_class p ON p.oid = i.inhparent
                    JOIN pg_namespace n ON n.oid = p.relnamespace
                    WHERE n.nspname = 'public'
                    ORDER BY p.relname, c.relname
                    """
                )
                return [dict(r) for r in cur.fetchall()]

    def run_retention_cleanup(self, dry_run: bool = True) -> dict[str, Any]:
        retention = self.get_retention_settings()
        results: dict[str, Any] = {"dry_run": dry_run, "deleted": {}, "history_impact": {}}
        table_specs = [
            ("browser_activity", "timestamp", retention["browser_activity_days"]),
            ("app_activity", "timestamp", retention["app_activity_days"]),
            ("input_activity", "timestamp", retention["input_activity_days"]),
            ("file_activity", "timestamp", retention["file_activity_days"]),
            ("network_activity", "timestamp", retention["network_activity_days"]),
            ("dlp_events", "timestamp", retention["dlp_events_days"]),
            ("phishing_events", "timestamp", retention["phishing_events_days"]),
        ]
        with _Conn() as conn:
            with conn.cursor() as cur:
                for table_name, ts_col, days in table_specs:
                    cur.execute(
                        f"SELECT COUNT(*) AS cnt FROM {table_name} WHERE tenant_id = %s AND {ts_col} < NOW() - (%s || ' days')::interval",
                        (_tid(), int(days)),
                    )
                    count = int((cur.fetchone() or {}).get("cnt") or 0)
                    results["deleted"][table_name] = count
                    if not dry_run and count:
                        cur.execute(
                            f"DELETE FROM {table_name} WHERE tenant_id = %s AND {ts_col} < NOW() - (%s || ' days')::interval",
                            (_tid(), int(days)),
                        )

                for table_name, ts_col, days in (
                    ("screenshots", "timestamp", retention["screenshots_days"]),
                    ("deleted_file_backups", "timestamp", retention["deleted_backups_days"]),
                ):
                    cur.execute(
                        f"SELECT COUNT(*) AS cnt FROM {table_name} WHERE tenant_id = %s AND {ts_col} < NOW() - (%s || ' days')::interval",
                        (_tid(), int(days)),
                    )
                    count = int((cur.fetchone() or {}).get("cnt") or 0)
                    results["deleted"][table_name] = count
                cur.execute(
                    """
                    SELECT
                        (SELECT COUNT(*) FROM dlp_incidents WHERE tenant_id = %s AND last_seen < NOW() - (%s || ' days')::interval) AS incidents_before_window,
                        (SELECT COUNT(*) FROM dlp_events WHERE tenant_id = %s AND timestamp < NOW() - (%s || ' days')::interval) AS events_before_window,
                        (SELECT COUNT(*) FROM dlp_incident_notes n JOIN dlp_incidents i ON i.id = n.incident_id
                            WHERE n.tenant_id = %s AND i.last_seen < NOW() - (%s || ' days')::interval) AS notes_linked_to_old_incidents,
                        (SELECT COUNT(*) FROM dlp_incident_timeline t JOIN dlp_incidents i ON i.id = t.incident_id
                            WHERE t.tenant_id = %s AND i.last_seen < NOW() - (%s || ' days')::interval) AS timeline_entries_linked_to_old_incidents,
                        (SELECT COUNT(*) FROM evidence_objects WHERE tenant_id = %s
                            AND retention_expires_at IS NOT NULL
                            AND retention_expires_at < NOW() + INTERVAL '14 days') AS evidence_objects_near_expiry
                    """,
                    (
                        _tid(),
                        int(retention["dlp_events_days"]),
                        _tid(),
                        int(retention["dlp_events_days"]),
                        _tid(),
                        int(retention["dlp_events_days"]),
                        _tid(),
                        int(retention["dlp_events_days"]),
                        _tid(),
                    ),
                )
                results["history_impact"] = dict(cur.fetchone() or {})
        return results

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # USERS â€” RBAC user management
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def create_user(self, data: dict) -> int:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO users (tenant_id, username, password_hash, display_name,
                                       role, assigned_machines, active, created_by)
                    VALUES (%(tenant_id)s, %(username)s, %(password_hash)s,
                            %(display_name)s, %(role)s, %(assigned_machines)s,
                            %(active)s, %(created_by)s)
                    RETURNING id
                """, {
                    "tenant_id":         data.get("tenant_id") or _tid(),
                    "username":          data.get("username"),
                    "password_hash":     data.get("password_hash"),
                    "display_name":      data.get("display_name", ""),
                    "role":              data.get("role", "viewer"),
                    "assigned_machines": data.get("assigned_machines", "[]"),
                    "active":            data.get("active", True),
                    "created_by":        data.get("created_by", "system"),
                })
                return cur.fetchone()["id"]

    def get_user_by_username(self, username: str) -> Optional[dict]:
        """Cross-tenant â€” login must look up user before we know their tenant."""
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM users WHERE username = %s", (username,))
                row = cur.fetchone()
                return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> Optional[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM users WHERE id = %s AND tenant_id = %s",
                    (user_id, _tid()),
                )
                row = cur.fetchone()
                return dict(row) if row else None

    def get_all_users(self) -> List[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM users WHERE tenant_id = %s ORDER BY created_at DESC",
                    (_tid(),),
                )
                return [dict(r) for r in cur.fetchall()]

    def get_all_users_cross_tenant(self, tenant_id: Optional[int] = None) -> List[dict]:
        """Platform-admin only: list users across all tenants, or filter to one.
        Joins tenants table so callers can display tenant_name alongside each user.
        """
        with _Conn() as conn:
            with conn.cursor() as cur:
                if tenant_id is not None:
                    cur.execute(
                        """
                        SELECT u.*, t.name AS tenant_name, t.slug AS tenant_slug
                        FROM users u
                        LEFT JOIN tenants t ON t.id = u.tenant_id
                        WHERE u.tenant_id = %s
                        ORDER BY u.created_at DESC
                        """,
                        (tenant_id,),
                    )
                else:
                    cur.execute(
                        """
                        SELECT u.*, t.name AS tenant_name, t.slug AS tenant_slug
                        FROM users u
                        LEFT JOIN tenants t ON t.id = u.tenant_id
                        ORDER BY u.tenant_id ASC, u.created_at DESC
                        """
                    )
                return [dict(r) for r in cur.fetchall()]

    def update_user(self, user_id: int, data: dict) -> bool:
        if not data:
            return False
        allowed = {"password_hash", "display_name", "role", "assigned_machines", "active"}
        filtered = {k: v for k, v in data.items() if k in allowed}
        if not filtered:
            return False
        filtered["updated_at"] = utcnow()
        set_clause = ", ".join(f"{k} = %({k})s" for k in filtered)
        filtered["_id"] = user_id
        filtered["_tid"] = _tid()
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE users SET {set_clause} WHERE id = %(_id)s AND tenant_id = %(_tid)s",
                    filtered,
                )
                return cur.rowcount > 0

    def delete_user(self, user_id: int) -> bool:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM users WHERE id = %s AND tenant_id = %s",
                    (user_id, _tid()),
                )
                return cur.rowcount > 0

    def count_users_by_role(self, role: str) -> int:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS cnt FROM users WHERE role = %s AND tenant_id = %s",
                    (role, _tid()),
                )
                return cur.fetchone()["cnt"]

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # AUDIT LOGS â€” immutable append-only logging
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def insert_audit_log(self, data: dict) -> int:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO audit_logs
                        (tenant_id, timestamp, user_id, username, role, action,
                         resource_type, resource_id, ip_address, metadata)
                    VALUES (%(tenant_id)s, %(timestamp)s, %(user_id)s, %(username)s,
                            %(role)s, %(action)s, %(resource_type)s, %(resource_id)s,
                            %(ip_address)s, %(metadata)s)
                    RETURNING id
                """, {
                    "tenant_id":     _tid(),
                    "timestamp":     data.get("timestamp", utcnow()),
                    "user_id":       data.get("user_id", 0),
                    "username":      data.get("username", ""),
                    "role":          data.get("role", ""),
                    "action":        data.get("action", ""),
                    "resource_type": data.get("resource_type", ""),
                    "resource_id":   str(data.get("resource_id", "")),
                    "ip_address":    data.get("ip_address", ""),
                    "metadata":      data.get("metadata", "{}"),
                })
                return cur.fetchone()["id"]

    def get_audit_logs(self, filters: dict | None = None, limit: int = 200, offset: int = 0) -> List[dict]:
        filters = filters or {}
        clauses: list[str] = ["tenant_id = %s"]
        params: list[Any] = [_tid()]

        if filters.get("username"):
            clauses.append("username = %s")
            params.append(filters["username"])
        if filters.get("action"):
            clauses.append("action = %s")
            params.append(filters["action"])
        if filters.get("resource_type"):
            clauses.append("resource_type = %s")
            params.append(filters["resource_type"])
        if filters.get("start_date"):
            clauses.append("timestamp >= %s")
            params.append(filters["start_date"])
        if filters.get("end_date"):
            clauses.append("timestamp <= %s")
            params.append(filters["end_date"] + "T23:59:59Z")
        if filters.get("search"):
            clauses.append("(username ILIKE %s OR action ILIKE %s OR resource_type ILIKE %s OR metadata ILIKE %s)")
            s = f"%{filters['search']}%"
            params.extend([s, s, s, s])

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        params.extend([limit, offset])
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT * FROM audit_logs{where} ORDER BY timestamp DESC LIMIT %s OFFSET %s", params)
                return [dict(r) for r in cur.fetchall()]

    def count_audit_logs(self, filters: dict | None = None) -> int:
        filters = filters or {}
        clauses, params = ["tenant_id = %s"], [_tid()]

        if filters.get("username"):
            clauses.append("username = %s")
            params.append(filters["username"])
        if filters.get("action"):
            clauses.append("action = %s")
            params.append(filters["action"])
        if filters.get("resource_type"):
            clauses.append("resource_type = %s")
            params.append(filters["resource_type"])
        if filters.get("start_date"):
            clauses.append("timestamp >= %s")
            params.append(filters["start_date"])
        if filters.get("end_date"):
            clauses.append("timestamp <= %s")
            params.append(filters["end_date"] + "T23:59:59Z")
        if filters.get("search"):
            clauses.append("(username ILIKE %s OR action ILIKE %s OR resource_type ILIKE %s OR metadata ILIKE %s)")
            s = f"%{filters['search']}%"
            params += [s, s, s, s]

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) AS cnt FROM audit_logs{where}", params)
                return cur.fetchone()["cnt"]

    def get_audit_actions(self) -> List[str]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT DISTINCT action FROM audit_logs "
                    "WHERE tenant_id = %s ORDER BY action",
                    (_tid(),),
                )
                return [r["action"] for r in cur.fetchall()]

    def get_audit_stats(self) -> dict:
        tid = _tid()
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*) AS total FROM audit_logs WHERE tenant_id = %s",
                    (tid,),
                )
                total = cur.fetchone()["total"]
                cur.execute("""
                    SELECT COUNT(*) AS cnt FROM audit_logs
                    WHERE timestamp >= NOW() - INTERVAL '24 hours' AND tenant_id = %s
                """, (tid,))
                last_24h = cur.fetchone()["cnt"]
                cur.execute("""
                    SELECT action, COUNT(*) AS cnt FROM audit_logs
                    WHERE tenant_id = %s
                    GROUP BY action ORDER BY cnt DESC LIMIT 5
                """, (tid,))
                top_actions = [dict(r) for r in cur.fetchall()]
                return {"total": total, "last_24h": last_24h, "top_actions": top_actions}

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
