"""Extracted DB methods mixin."""

import base64
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

class FileNetworkDlpMethodsMixin:

    # FILE ACTIVITY â€” create / read / delete
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def insert_file_activity(self, data: dict):
        data = dict(data)
        data["timestamp"] = data.get("timestamp") or utcnow()
        ensure_monthly_partition("file_activity", data.get("timestamp"))
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO file_activity
                        (tenant_id, machine_id, machine_ref, timestamp, action, file_path,
                         file_name, file_ext, file_size, destination, is_directory,
                         backup_available, backup_skip_reason, destination_type,
                         destination_label, enterprise_label, sensitivity_score,
                         label_source, label_reason, block_candidate, block_reason,
                         blocking_supported, blocking_mode)
                    VALUES
                        (%(tenant_id)s, %(machine_id)s, %(machine_ref)s, %(timestamp)s, %(action)s,
                         %(file_path)s, %(file_name)s, %(file_ext)s, %(file_size)s,
                         %(destination)s, %(is_directory)s, %(backup_available)s,
                         %(backup_skip_reason)s, %(destination_type)s,
                         %(destination_label)s, %(enterprise_label)s, %(sensitivity_score)s,
                         %(label_source)s, %(label_reason)s, %(block_candidate)s,
                         %(block_reason)s, %(blocking_supported)s, %(blocking_mode)s)
                """, {
                    "tenant_id":    _tid(),
                    "machine_id":   data.get("machine_id"),
                    "machine_ref":  self.get_machine_ref(data.get("machine_id", ""), _tid()),
                    "timestamp":    data.get("timestamp"),
                    "action":       data.get("action", ""),
                    "file_path":    data.get("file_path", ""),
                    "file_name":    data.get("file_name", ""),
                    "file_ext":     data.get("file_ext", ""),
                    "file_size":    data.get("file_size", 0),
                    "destination":  data.get("destination", ""),
                    "is_directory": data.get("is_directory", False),
                    "backup_available": bool(data.get("backup_available", False)),
                    "backup_skip_reason": data.get("backup_skip_reason", ""),
                    "destination_type": data.get("destination_type", ""),
                    "destination_label": data.get("destination_label", ""),
                    "enterprise_label": data.get("enterprise_label", ""),
                    "sensitivity_score": int(data.get("sensitivity_score", 0) or 0),
                    "label_source": data.get("label_source", ""),
                    "label_reason": data.get("label_reason", ""),
                    "block_candidate": bool(data.get("block_candidate", False)),
                    "block_reason": data.get("block_reason", ""),
                    "blocking_supported": bool(data.get("blocking_supported", False)),
                    "blocking_mode": data.get("blocking_mode", ""),
                })

    def store_deleted_backup_from_activity(self, data: dict, file_data: str | None) -> dict:
        result = {
            "backup_available": False,
            "backup_skip_reason": data.get("backup_skip_reason", ""),
            "backup_id": None,
        }
        if data.get("action") != "delete":
            return result
        if data.get("is_directory", False):
            result["backup_skip_reason"] = result["backup_skip_reason"] or "directory_not_backed_up"
            logger.info(
                "vault_capture machine_id=%s action=delete backup_present=false skip_reason=%s file_path=%s",
                data.get("machine_id", ""),
                result["backup_skip_reason"],
                data.get("file_path", ""),
            )
            return result
        if file_data is None:
            result["backup_skip_reason"] = result["backup_skip_reason"] or "backup_missing"
            logger.info(
                "vault_capture machine_id=%s action=delete backup_present=false skip_reason=%s file_path=%s",
                data.get("machine_id", ""),
                result["backup_skip_reason"],
                data.get("file_path", ""),
            )
            return result
        try:
            file_size = int(data.get("file_size", 0) or 0)
            if file_size <= 0 and file_data:
                try:
                    file_size = len(base64.b64decode(file_data.encode("ascii"), validate=False))
                    data["file_size"] = file_size
                except Exception:
                    file_size = int(data.get("file_size", 0) or 0)
            machine = self.get_machine(data.get("machine_id", ""))
            backup_id = self.insert_deleted_backup(
                {
                    "machine_id": data.get("machine_id", ""),
                    "timestamp": data.get("timestamp"),
                    "original_path": data.get("file_path", ""),
                    "file_name": data.get("file_name", ""),
                    "file_ext": data.get("file_ext", ""),
                    "file_size": file_size,
                    "file_data": file_data,
                    "is_directory": data.get("is_directory", False),
                    "username": machine.get("username", "") if machine else "",
                }
            )
            result["backup_available"] = True
            result["backup_skip_reason"] = ""
            result["backup_id"] = backup_id
            logger.info(
                "vault_capture machine_id=%s action=delete backup_present=true backup_id=%s file_path=%s",
                data.get("machine_id", ""),
                backup_id,
                data.get("file_path", ""),
            )
        except Exception as exc:
            result["backup_skip_reason"] = "backup_store_failed"
            logger.warning(
                "vault_capture machine_id=%s action=delete backup_present=false skip_reason=%s file_path=%s error=%s",
                data.get("machine_id", ""),
                result["backup_skip_reason"],
                data.get("file_path", ""),
                exc,
            )
        return result

    def get_file_activity(self, machine_id: str = "", action: str = "",
                          search: str = "", date: str = "",
                          limit: int = 100, offset: int = 0) -> List[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                parts: list = ["f.tenant_id = %s"]
                params: list = [_tid()]
                if machine_id:
                    parts.append("f.machine_id = %s")
                    params.append(machine_id)
                if action:
                    parts.append("f.action = %s")
                    params.append(action)
                if search:
                    parts.append("(f.file_path ILIKE %s OR f.file_name ILIKE %s)")
                    s = f"%{search}%"
                    params += [s, s]
                if date:
                    parts.append("f.timestamp::date = %s")
                    params.append(date)
                where = ("WHERE " + " AND ".join(parts)) if parts else ""
                cur.execute(f"""
                    SELECT f.*, m.hostname, m.username
                    FROM file_activity f
                    LEFT JOIN machines m ON f.machine_id = m.machine_id
                    {where}
                    ORDER BY f.timestamp DESC
                    LIMIT %s OFFSET %s
                """, params + [limit, offset])
                return [dict(r) for r in cur.fetchall()]

    def count_file_activity(self, machine_id: str = "", action: str = "",
                            search: str = "", date: str = "") -> int:
        with _Conn() as conn:
            with conn.cursor() as cur:
                parts: list = ["tenant_id = %s"]
                params: list = [_tid()]
                if machine_id:
                    parts.append("machine_id = %s")
                    params.append(machine_id)
                if action:
                    parts.append("action = %s")
                    params.append(action)
                if search:
                    parts.append("(file_path ILIKE %s OR file_name ILIKE %s)")
                    s = f"%{search}%"
                    params += [s, s]
                if date:
                    parts.append("timestamp::date = %s")
                    params.append(date)
                where = ("WHERE " + " AND ".join(parts)) if parts else ""
                cur.execute(f"SELECT COUNT(*) AS cnt FROM file_activity {where}", params)
                return cur.fetchone()["cnt"]

    def get_file_activity_stats(self, machine_id: str = "") -> dict:
        tid = _tid()
        with _Conn() as conn:
            with conn.cursor() as cur:
                if machine_id:
                    mfilter = "WHERE machine_id = %s AND tenant_id = %s"
                    mparams = [machine_id, tid]
                else:
                    mfilter = "WHERE tenant_id = %s"
                    mparams = [tid]
                cur.execute(f"SELECT COUNT(*) AS total FROM file_activity {mfilter}", mparams)
                total = cur.fetchone()["total"]
                cur.execute(f"""
                    SELECT COUNT(*) AS cnt FROM file_activity
                    {mfilter} AND timestamp >= NOW() - INTERVAL '24 hours'
                """, mparams)
                last_24h = cur.fetchone()["cnt"]
                cur.execute(f"""
                    SELECT action, COUNT(*) AS cnt FROM file_activity
                    {mfilter} GROUP BY action ORDER BY cnt DESC
                """, mparams)
                by_action = [dict(r) for r in cur.fetchall()]
                return {"total": total, "last_24h": last_24h, "by_action": by_action}

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # DELETED FILE BACKUPS â€” secret admin storage
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def insert_deleted_backup(self, data: dict) -> int:
        tenant_id = _tid()
        machine_id = data.get("machine_id", "")
        machine_ref = self.get_machine_ref(machine_id, tenant_id)
        stored = evidence_storage.store_base64(
            base64_data=data.get("file_data", ""),
            tenant_id=tenant_id,
            machine_id=machine_id or "unknown",
            category="deleted_backups",
            filename_hint=data.get("file_name", "") or "backup.bin",
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
                        "deleted_backups",
                        "restore_backup",
                        "application/octet-stream",
                        stored.backend,
                        stored.storage_key,
                        stored.sha256,
                        stored.size_bytes,
                        "active",
                        json.dumps({"original_path": data.get("original_path", "")}),
                        utcnow(),
                        utcnow(),
                    ),
                )
                evidence_id = cur.fetchone()["id"]
                cur.execute("""
                    INSERT INTO deleted_file_backups
                        (machine_id, machine_ref, timestamp, original_path, file_name,
                         file_ext, file_size, file_data, evidence_id, storage_key, storage_backend,
                         sha256, content_type, is_directory, username, tenant_id)
                    VALUES
                        (%(machine_id)s, %(machine_ref)s, %(timestamp)s, %(original_path)s, %(file_name)s,
                         %(file_ext)s, %(file_size)s, '', %(evidence_id)s, %(storage_key)s, %(storage_backend)s,
                         %(sha256)s, %(content_type)s, %(is_directory)s, %(username)s, %(tenant_id)s)
                    RETURNING id
                """, {
                    "machine_id":    data.get("machine_id"),
                    "machine_ref":   machine_ref,
                    "timestamp":     data.get("timestamp"),
                    "original_path": data.get("original_path", ""),
                    "file_name":     data.get("file_name", ""),
                    "file_ext":      data.get("file_ext", ""),
                    "file_size":     data.get("file_size", 0),
                    "evidence_id":   evidence_id,
                    "storage_key":   stored.storage_key,
                    "storage_backend": stored.backend,
                    "sha256":        stored.sha256,
                    "content_type":  "application/octet-stream",
                    "is_directory":  data.get("is_directory", False),
                    "username":      data.get("username", ""),
                    "tenant_id":     tenant_id,
                })
                return cur.fetchone()["id"]

    def get_deleted_backups(self, machine_id: str = "", search: str = "",
                            limit: int = 50, offset: int = 0) -> List[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                parts: list = ["d.tenant_id = %s"]
                params: list = [_tid()]
                if machine_id:
                    parts.append("d.machine_id = %s")
                    params.append(machine_id)
                if search:
                    parts.append("(d.original_path ILIKE %s OR d.file_name ILIKE %s)")
                    s = f"%{search}%"
                    params += [s, s]
                where = "WHERE " + " AND ".join(parts)
                cur.execute(f"""
                    SELECT d.id, d.machine_id, d.timestamp, d.original_path,
                           d.file_name, d.file_ext, d.file_size, d.is_directory,
                           d.username, m.hostname
                    FROM deleted_file_backups d
                    LEFT JOIN machines m ON d.machine_id = m.machine_id
                    {where}
                    ORDER BY d.timestamp DESC
                    LIMIT %s OFFSET %s
                """, params + [limit, offset])
                return [dict(r) for r in cur.fetchall()]

    def count_deleted_backups(self, machine_id: str = "", search: str = "") -> int:
        with _Conn() as conn:
            with conn.cursor() as cur:
                parts: list = ["tenant_id = %s"]
                params: list = [_tid()]
                if machine_id:
                    parts.append("machine_id = %s")
                    params.append(machine_id)
                if search:
                    parts.append("(original_path ILIKE %s OR file_name ILIKE %s)")
                    s = f"%{search}%"
                    params += [s, s]
                where = "WHERE " + " AND ".join(parts)
                cur.execute(f"SELECT COUNT(*) AS cnt FROM deleted_file_backups {where}", params)
                return cur.fetchone()["cnt"]

    def get_deleted_backup_file(self, backup_id: int) -> Optional[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM deleted_file_backups WHERE id = %s AND tenant_id = %s", (backup_id, _tid()))
                row = cur.fetchone()
                if not row:
                    return None
                payload = dict(row)
                if payload.get("storage_key"):
                    try:
                        payload["file_data"] = evidence_storage.load_base64(payload["storage_key"])
                    except FileNotFoundError:
                        payload["file_data"] = ""
                return payload

    def delete_backup(self, backup_id: int) -> bool:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT storage_key, evidence_id FROM deleted_file_backups WHERE id = %s AND tenant_id = %s",
                    (backup_id, _tid()),
                )
                row = cur.fetchone()
                if not row:
                    return False
                cur.execute("DELETE FROM deleted_file_backups WHERE id = %s AND tenant_id = %s", (backup_id, _tid()))
                ok = cur.rowcount > 0
                if row.get("evidence_id"):
                    cur.execute(
                        "DELETE FROM evidence_objects WHERE id = %s AND tenant_id = %s",
                        (row["evidence_id"], _tid()),
                    )
        if ok and row.get("storage_key"):
            evidence_storage.delete(row["storage_key"])
        return ok

    # â”€â”€ Network activity â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

    def insert_network_activity(self, data: dict):
        data = dict(data)
        data["timestamp"] = data.get("timestamp") or utcnow()
        ensure_monthly_partition("network_activity", data.get("timestamp"))
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO network_activity
                        (machine_id, machine_ref, timestamp, bytes_sent, bytes_recv,
                         total_sent, total_recv, listen_count, conn_count,
                         listening_ports, connections, tenant_id)
                    VALUES (%(machine_id)s, %(machine_ref)s, %(timestamp)s, %(bytes_sent)s, %(bytes_recv)s,
                            %(total_sent)s, %(total_recv)s, %(listen_count)s, %(conn_count)s,
                            %(listening_ports)s, %(connections)s, %(tenant_id)s)
                """, {
                    "machine_id":      data.get("machine_id", ""),
                    "machine_ref":     self.get_machine_ref(data.get("machine_id", ""), _tid()),
                    "timestamp":       data.get("timestamp"),
                    "bytes_sent":      data.get("bytes_sent", 0),
                    "bytes_recv":      data.get("bytes_recv", 0),
                    "total_sent":      data.get("total_sent", 0),
                    "total_recv":      data.get("total_recv", 0),
                    "listen_count":    data.get("listen_count", 0),
                    "conn_count":      data.get("conn_count", 0),
                    "listening_ports": json.dumps(data.get("listening_ports", [])),
                    "connections":     json.dumps(data.get("connections", [])),
                    "tenant_id":       _tid(),
                })

    def get_network_activity(self, machine_id: str = "", search: str = "",
                              date: str = "", limit: int = 50, offset: int = 0) -> list:
        with _Conn() as conn:
            with conn.cursor() as cur:
                parts, params = ["n.tenant_id = %s"], [_tid()]
                if machine_id:
                    parts.append("n.machine_id = %s"); params.append(machine_id)
                if search:
                    parts.append("(n.listening_ports::text ILIKE %s OR n.connections::text ILIKE %s)")
                    s = f"%{search}%"; params += [s, s]
                if date:
                    parts.append("n.timestamp::date = %s"); params.append(date)
                where = "WHERE " + " AND ".join(parts)
                cur.execute(f"""
                    SELECT n.*, m.hostname, m.username
                    FROM network_activity n
                    LEFT JOIN machines m ON n.machine_id = m.machine_id
                    {where}
                    ORDER BY n.timestamp DESC
                    LIMIT %s OFFSET %s
                """, params + [limit, offset])
                return [dict(r) for r in cur.fetchall()]

    def count_network_activity(self, machine_id: str = "", search: str = "",
                                date: str = "") -> int:
        with _Conn() as conn:
            with conn.cursor() as cur:
                parts, params = ["tenant_id = %s"], [_tid()]
                if machine_id:
                    parts.append("machine_id = %s")
                    params.append(machine_id)
                if search:
                    parts.append("(listening_ports::text ILIKE %s OR connections::text ILIKE %s)")
                    s = f"%{search}%"; params += [s, s]
                if date:
                    parts.append("timestamp::date = %s"); params.append(date)
                where = "WHERE " + " AND ".join(parts)
                cur.execute(f"SELECT COUNT(*) AS cnt FROM network_activity {where}", params)
                return cur.fetchone()["cnt"]

    def get_network_stats(self, machine_id: str = "") -> dict:
        with _Conn() as conn:
            with conn.cursor() as cur:
                base = "WHERE tenant_id = %s"
                bp = [_tid()]
                if machine_id:
                    base += " AND machine_id = %s"
                    bp.append(machine_id)

                cur.execute(f"SELECT COUNT(*) AS total FROM network_activity {base}", bp)
                total = cur.fetchone()["total"]

                cur.execute(f"SELECT COUNT(*) AS cnt FROM network_activity {base} AND timestamp > NOW() - INTERVAL '24 hours'", bp)
                last_24h = cur.fetchone()["cnt"]

                # Latest snapshot per machine (for "current" open ports)
                cur.execute(f"""
                    SELECT DISTINCT ON (machine_id) machine_id, listening_ports, connections,
                           listen_count, conn_count, bytes_sent, bytes_recv, timestamp
                    FROM network_activity
                    {base}
                    ORDER BY machine_id, timestamp DESC
                """, bp)
                latest = [dict(r) for r in cur.fetchall()]

                return {
                    "total_snapshots": total,
                    "last_24h": last_24h,
                    "latest_by_machine": latest,
                }


    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    # DLP EVENTS â€” Data Loss Prevention
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def insert_dlp_event(self, data: dict) -> int:
        data = dict(data)
        data["timestamp"] = data.get("timestamp") or utcnow()
        machine_id = data.get("machine_id", "")
        ensure_monthly_partition("dlp_events", data.get("timestamp"))
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO dlp_events
                        (machine_id, machine_ref, timestamp, file_path, file_name, file_ext,
                         file_size, risk_level, risk_score, findings,
                         file_hash, destination, device, is_known_sensitive, scoring, tenant_id,
                         event_type, channel, policy_version, policy_rule_id, classifier_hits,
                         confidence, action_taken, action_result, justification_required,
                         justification_text, exception_applied, masked_evidence, actor_username,
                         app_name, destination_type, destination_label, content_fingerprint, incident_id,
                         enterprise_label, sensitivity_score, label_source, label_reason,
                         block_candidate, block_reason, blocking_supported, blocking_mode)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    machine_id,
                    self.get_machine_ref(machine_id, _tid()),
                    data.get("timestamp") or utcnow(),
                    data.get("file_path", ""),
                    data.get("file_name", ""),
                    data.get("file_ext", ""),
                    data.get("file_size", 0),
                    data.get("risk_level", data.get("risk", "low")),
                    data.get("risk_score", 0),
                    json.dumps(data.get("findings", [])),
                    data.get("file_hash", ""),
                    data.get("destination", "local"),
                    data.get("device", ""),
                    data.get("is_known_sensitive", False),
                    json.dumps(data.get("scoring", {})),
                    _tid(),
                    data.get("event_type", "file_transfer"),
                    data.get("channel", "file"),
                    data.get("policy_version", 1),
                    data.get("policy_rule_id"),
                    json.dumps(data.get("classifier_hits", [])),
                    data.get("confidence", 0),
                    data.get("action_taken", "monitor"),
                    data.get("action_result", "observed"),
                    data.get("justification_required", False),
                    data.get("justification_text", ""),
                    json.dumps(data.get("exception_applied", {})),
                    json.dumps(data.get("masked_evidence", [])),
                    data.get("actor_username", ""),
                    data.get("app_name", ""),
                    data.get("destination_type", data.get("destination", "")),
                    data.get("destination_label", data.get("device", "")),
                    data.get("content_fingerprint", data.get("file_hash", "")),
                    data.get("incident_id"),
                    data.get("enterprise_label", ""),
                    int(data.get("sensitivity_score", 0) or 0),
                    data.get("label_source", ""),
                    data.get("label_reason", ""),
                    bool(data.get("block_candidate", False)),
                    data.get("block_reason", ""),
                    bool(data.get("blocking_supported", False)),
                    data.get("blocking_mode", ""),
                ))
                return cur.fetchone()["id"]

    def update_dlp_event_incident(self, event_id: int, incident_id: int) -> bool:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE dlp_events SET incident_id = %s WHERE id = %s AND tenant_id = %s",
                    (incident_id, event_id, _tid()),
                )
                return cur.rowcount > 0

    def get_dlp_events(
        self,
        machine_id: str = "",
        risk_level: str = "",
        destination: str = "",
        destination_type: str = "",
        date_from: str = "",
        date_to: str = "",
        search: str = "",
        limit: int = 50,
        offset: int = 0,
        incident_id: Optional[int] = None,
        file_hash: str = "",
        content_fingerprint: str = "",
        actor_username: str = "",
    ) -> List[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                clauses, params = ["e.tenant_id = %s"], [_tid()]
                if machine_id:
                    clauses.append("e.machine_id = %s"); params.append(machine_id)
                if incident_id is not None:
                    clauses.append("e.incident_id = %s"); params.append(incident_id)
                if risk_level:
                    clauses.append("e.risk_level = %s"); params.append(risk_level)
                if destination:
                    clauses.append("e.destination = %s"); params.append(destination)
                if destination_type:
                    clauses.append("e.destination_type = %s"); params.append(destination_type)
                if file_hash:
                    clauses.append("e.file_hash = %s"); params.append(file_hash)
                elif content_fingerprint:
                    clauses.append("e.content_fingerprint = %s"); params.append(content_fingerprint)
                if actor_username:
                    clauses.append("e.actor_username = %s"); params.append(actor_username)
                if date_from:
                    clauses.append("e.timestamp >= %s"); params.append(date_from)
                if date_to:
                    clauses.append("e.timestamp <= %s"); params.append(date_to)
                if search:
                    clauses.append("(e.file_path ILIKE %s OR e.file_name ILIKE %s)")
                    params += [f"%{search}%", f"%{search}%"]
                where = "WHERE " + " AND ".join(clauses)
                cur.execute(
                    f"SELECT e.*, m.hostname FROM dlp_events e LEFT JOIN machines m ON e.machine_id = m.machine_id {where} "
                    f"ORDER BY e.timestamp DESC LIMIT %s OFFSET %s",
                    params + [limit, offset]
                )
                return [dict(r) for r in cur.fetchall()]

    def count_dlp_events(
        self,
        machine_id: str = "",
        risk_level: str = "",
        destination: str = "",
        destination_type: str = "",
        date_from: str = "",
        date_to: str = "",
        search: str = "",
        incident_id: Optional[int] = None,
        file_hash: str = "",
        content_fingerprint: str = "",
        actor_username: str = "",
    ) -> int:
        with _Conn() as conn:
            with conn.cursor() as cur:
                clauses, params = ["tenant_id = %s"], [_tid()]
                if machine_id:
                    clauses.append("machine_id = %s"); params.append(machine_id)
                if incident_id is not None:
                    clauses.append("incident_id = %s"); params.append(incident_id)
                if risk_level:
                    clauses.append("risk_level = %s"); params.append(risk_level)
                if destination:
                    clauses.append("destination = %s"); params.append(destination)
                if destination_type:
                    clauses.append("destination_type = %s"); params.append(destination_type)
                if file_hash:
                    clauses.append("file_hash = %s"); params.append(file_hash)
                elif content_fingerprint:
                    clauses.append("content_fingerprint = %s"); params.append(content_fingerprint)
                if actor_username:
                    clauses.append("actor_username = %s"); params.append(actor_username)
                if date_from:
                    clauses.append("timestamp >= %s"); params.append(date_from)
                if date_to:
                    clauses.append("timestamp <= %s"); params.append(date_to)
                if search:
                    clauses.append("(file_path ILIKE %s OR file_name ILIKE %s)")
                    params += [f"%{search}%", f"%{search}%"]
                where = "WHERE " + " AND ".join(clauses)
                cur.execute(f"SELECT COUNT(*) AS c FROM dlp_events {where}", params)
                return cur.fetchone()["c"]

    def get_dlp_stats(self, machine_id: str = "") -> dict:
        with _Conn() as conn:
            with conn.cursor() as cur:
                base = "WHERE tenant_id = %s"
                bp = [_tid()]
                if machine_id:
                    base += " AND machine_id = %s"
                    bp.append(machine_id)

                cur.execute(f"SELECT COUNT(*) AS c FROM dlp_events {base}", bp)
                total = cur.fetchone()["c"]

                cur.execute(
                    f"SELECT risk_level, COUNT(*) AS count FROM dlp_events {base} GROUP BY risk_level",
                    bp,
                )
                by_risk = {r["risk_level"]: r["count"] for r in cur.fetchall()}

                cur.execute(f"SELECT COUNT(*) AS c FROM dlp_events {base} AND timestamp > NOW() - INTERVAL '24 hours'", bp)
                last_24h = cur.fetchone()["c"]

                # Top 5 most flagged files
                cur.execute(f"""
                    SELECT file_path, file_name, risk_level, COUNT(*) AS hit_count
                    FROM dlp_events {base}
                    GROUP BY file_path, file_name, risk_level
                    ORDER BY hit_count DESC
                    LIMIT 5
                """, bp)
                top_files = [dict(r) for r in cur.fetchall()]

                # v2: breakdown by destination
                cur.execute(
                    f"SELECT destination, COUNT(*) AS count FROM dlp_events {base} GROUP BY destination",
                    bp,
                )
                by_destination = {r["destination"]: r["count"] for r in cur.fetchall()}

                # v2: average risk score
                cur.execute(
                    f"SELECT COALESCE(AVG(risk_score), 0) AS avg_score FROM dlp_events {base}",
                    bp,
                )
                avg_score = round(cur.fetchone()["avg_score"], 1)

                # v2: count of unique sensitive file hashes
                cur.execute(
                    f"SELECT COUNT(DISTINCT file_hash) AS c FROM dlp_events {base} AND file_hash != ''",
                    bp,
                )
                unique_files = cur.fetchone()["c"]

                return {
                    "total": total,
                    "last_24h": last_24h,
                    "by_risk": by_risk,
                    "by_destination": by_destination,
                    "avg_risk_score": avg_score,
                    "unique_sensitive_files": unique_files,
                    "top_files": top_files,
                }

    def acknowledge_dlp_event(self, event_id: int) -> bool:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE dlp_events SET acknowledged = TRUE WHERE id = %s AND tenant_id = %s",
                    (event_id, _tid()),
                )
                return cur.rowcount > 0

    def delete_dlp_events_for_machine(self, machine_id: str) -> int:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM dlp_events WHERE machine_id = %s AND tenant_id = %s", (machine_id, _tid()))
                return cur.rowcount


