"""Extracted DB methods mixin."""

import json
import logging
import uuid
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

class AnalyticsMethodsMixin:

    # ANALYTICS â€” read-only aggregations
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def create_report_job(self, data: dict[str, Any]) -> dict:
        tid = int(data.get("tenant_id") or _tid())
        payload = {
            "id": data.get("id") or str(uuid.uuid4()),
            "tenant_id": tid,
            "machine_id": data.get("machine_id", ""),
            "report_type": data.get("report_type", "machine_pdf"),
            "status": data.get("status", "queued"),
            "requested_by": data.get("requested_by", ""),
            "start_date": data.get("start_date") or "",
            "end_date": data.get("end_date") or "",
            "output_path": data.get("output_path") or "",
            "evidence_id": data.get("evidence_id"),
            "storage_key": data.get("storage_key") or "",
            "storage_backend": data.get("storage_backend") or "",
            "content_type": data.get("content_type") or "application/pdf",
            "filename": data.get("filename") or "",
            "error_message": data.get("error_message") or "",
            "metadata": json.dumps(data.get("metadata") or {}),
        }
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO report_jobs
                        (id, tenant_id, machine_id, report_type, status, requested_by,
                         start_date, end_date, output_path, evidence_id, storage_key, storage_backend,
                         content_type, filename, error_message, metadata)
                    VALUES
                        (%(id)s, %(tenant_id)s, %(machine_id)s, %(report_type)s, %(status)s, %(requested_by)s,
                         %(start_date)s, %(end_date)s, %(output_path)s, %(evidence_id)s, %(storage_key)s, %(storage_backend)s,
                         %(content_type)s, %(filename)s, %(error_message)s, %(metadata)s)
                    RETURNING *
                    """,
                    payload,
                )
                row = dict(cur.fetchone())
        return self._deserialize_report_job(row)

    def get_report_job(self, job_id: str) -> Optional[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM report_jobs WHERE id = %s AND tenant_id = %s",
                    (job_id, _tid()),
                )
                row = cur.fetchone()
        return self._deserialize_report_job(dict(row)) if row else None

    def mark_report_job_running(self, job_id: str) -> Optional[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE report_jobs
                    SET status = 'running',
                        started_at = COALESCE(started_at, NOW()),
                        error_message = ''
                    WHERE id = %s AND tenant_id = %s
                    RETURNING *
                    """,
                    (job_id, _tid()),
                )
                row = cur.fetchone()
        return self._deserialize_report_job(dict(row)) if row else None

    def complete_report_job(
        self,
        job_id: str,
        *,
        output_path: str,
        evidence_id: int | None = None,
        storage_key: str = "",
        storage_backend: str = "",
        content_type: str = "application/pdf",
        filename: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> Optional[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE report_jobs
                    SET status = 'completed',
                        output_path = %s,
                        evidence_id = COALESCE(%s, evidence_id),
                        storage_key = %s,
                        storage_backend = %s,
                        content_type = %s,
                        filename = %s,
                        error_message = '',
                        metadata = COALESCE(%s::jsonb, metadata),
                        completed_at = NOW(),
                        started_at = COALESCE(started_at, NOW())
                    WHERE id = %s AND tenant_id = %s
                    RETURNING *
                    """,
                    (
                        output_path,
                        evidence_id,
                        storage_key,
                        storage_backend,
                        content_type,
                        filename,
                        json.dumps(metadata) if metadata is not None else None,
                        job_id,
                        _tid(),
                    ),
                )
                row = cur.fetchone()
        return self._deserialize_report_job(dict(row)) if row else None

    def fail_report_job(self, job_id: str, error_message: str) -> Optional[dict]:
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE report_jobs
                    SET status = 'failed',
                        error_message = %s,
                        completed_at = NOW(),
                        started_at = COALESCE(started_at, NOW())
                    WHERE id = %s AND tenant_id = %s
                    RETURNING *
                    """,
                    (error_message[:2000], job_id, _tid()),
                )
                row = cur.fetchone()
        return self._deserialize_report_job(dict(row)) if row else None

    @staticmethod
    def _deserialize_report_job(row: dict[str, Any]) -> dict[str, Any]:
        metadata = row.get("metadata")
        if isinstance(metadata, str):
            try:
                row["metadata"] = json.loads(metadata)
            except Exception:
                row["metadata"] = {}
        elif metadata is None:
            row["metadata"] = {}
        for key in ("created_at", "started_at", "completed_at"):
            value = row.get(key)
            if hasattr(value, "isoformat"):
                row[key] = value.isoformat()
        return row

    def get_overview_stats(self) -> dict:
        tid = _tid()
        with _Conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) AS c FROM machines WHERE tenant_id = %s", (tid,))
                total = cur.fetchone()["c"]

                today = utcnow().date()
                cur.execute("""
                    SELECT COUNT(DISTINCT machine_id) AS c FROM app_activity
                    WHERE timestamp::date = %s AND tenant_id = %s
                """, (today, tid))
                active_today = cur.fetchone()["c"]

                cur.execute("""
                    SELECT app_name, SUM(duration_seconds) AS total
                    FROM app_activity WHERE tenant_id = %s
                    GROUP BY app_name ORDER BY total DESC LIMIT 10
                """, (tid,))
                top_apps = [dict(r) for r in cur.fetchall()]

                cur.execute("""
                    SELECT domain, COUNT(*) AS visits
                    FROM browser_activity WHERE tenant_id = %s
                    GROUP BY domain ORDER BY visits DESC LIMIT 10
                """, (tid,))
                top_domains = [dict(r) for r in cur.fetchall()]

                daily = []
                for i in range(6, -1, -1):
                    d = (utcnow() - timedelta(days=i)).date()
                    cur.execute("""
                        SELECT COUNT(DISTINCT machine_id) AS machines,
                               COALESCE(SUM(duration_seconds), 0) AS total_seconds
                        FROM app_activity WHERE timestamp::date = %s AND tenant_id = %s
                    """, (d, tid))
                    row = cur.fetchone()
                    daily.append({
                        "date":         str(d),
                        "machines":     row["machines"],
                        "total_seconds":int(row["total_seconds"]),
                    })

        return {
            "total_machines": total,
            "active_today":   active_today,
            "top_apps":       top_apps,
            "top_domains":    top_domains,
            "daily_activity": daily,
        }

    def get_machine_analytics(self, machine_id: str,
                               start_date=None, end_date=None) -> dict:
        with _Conn() as conn:
            with conn.cursor() as cur:
                tid = _tid()
                fa = "machine_id = %s AND tenant_id = %s"
                fb = "machine_id = %s AND tenant_id = %s"
                pa: list = [machine_id, tid]
                pb: list = [machine_id, tid]
                if start_date:
                    fa += " AND timestamp >= %s"; pa.append(start_date)
                    fb += " AND timestamp >= %s"; pb.append(start_date)
                if end_date:
                    fa += " AND timestamp <= %s"; pa.append(end_date + "T23:59:59")
                    fb += " AND timestamp <= %s"; pb.append(end_date + "T23:59:59")

                cur.execute(f"""
                    SELECT app_name, SUM(duration_seconds) AS total_seconds,
                           COUNT(*) AS sessions
                    FROM app_activity WHERE {fa}
                    GROUP BY app_name ORDER BY total_seconds DESC LIMIT 15
                """, pa)
                app_usage = [dict(r) for r in cur.fetchall()]

                cur.execute(f"""
                    SELECT domain, COUNT(*) AS visits,
                           SUM(duration_seconds) AS total_seconds
                    FROM browser_activity WHERE {fb}
                    GROUP BY domain ORDER BY visits DESC LIMIT 15
                """, pb)
                browser_usage = [dict(r) for r in cur.fetchall()]

                cur.execute(f"""
                    SELECT EXTRACT(HOUR FROM timestamp)::int AS hour,
                           SUM(duration_seconds) AS total_seconds
                    FROM app_activity WHERE {fa}
                    GROUP BY hour ORDER BY hour
                """, pa)
                hourly = [
                    {"hour": str(r["hour"]).zfill(2),
                     "total_seconds": int(r["total_seconds"])}
                    for r in cur.fetchall()
                ]

                cur.execute(f"""
                    SELECT timestamp::date AS date,
                           SUM(duration_seconds) AS total_seconds
                    FROM app_activity WHERE {fa}
                    GROUP BY date ORDER BY date DESC LIMIT 30
                """, pa)
                daily = [
                    {"date": str(r["date"]),
                     "total_seconds": int(r["total_seconds"])}
                    for r in cur.fetchall()
                ]

                cur.execute(
                    f"SELECT COALESCE(SUM(duration_seconds),0) AS t FROM app_activity WHERE {fa}",
                    pa
                )
                total_active = int(cur.fetchone()["t"])

                cur.execute(
                    f"SELECT COUNT(*) AS c FROM browser_activity WHERE {fb}",
                    pb
                )
                browser_count = cur.fetchone()["c"]

        return {
            "app_usage":           app_usage,
            "browser_usage":       browser_usage,
            "hourly_activity":     hourly,
            "daily_activity":      daily,
            "total_active_seconds":total_active,
            "browser_visits":      browser_count,
        }

    def get_productivity_score(self, machine_id: str) -> dict:
        from app.services.productivity_service import productivity_service

        return productivity_service.get_machine_productivity_alias(machine_id)

    def get_productivity_logs(self, machine_id: str = "",
                               date: str = "", limit: int = 200) -> List[dict]:
        from app.services.productivity_service import productivity_service

        return productivity_service.get_productivity_logs(machine_id, date, limit)

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
