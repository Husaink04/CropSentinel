"""Optional ClickHouse analytics pipeline for high-volume read offload."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections import deque
from datetime import datetime, timezone
from typing import Any
from urllib import error, parse, request

from app.db.core import get_tenant_id as _tid
from app.event_bus import EventEnvelope, EventTopics, internal_event_bus

logger = logging.getLogger("cropsentinel.analytics_pipeline")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _analytics_backend() -> str:
    return (os.environ.get("ANALYTICS_BACKEND", "noop").strip().lower() or "noop")


def _clickhouse_url() -> str:
    return os.environ.get("CLICKHOUSE_URL", "").strip()


def _read_enabled() -> bool:
    return os.environ.get("CLICKHOUSE_ANALYTICS_READS", "0").strip().lower() in {"1", "true", "yes", "on"}


def _flush_batch_size() -> int:
    try:
        return max(10, int(os.environ.get("CLICKHOUSE_ANALYTICS_FLUSH_BATCH", "250")))
    except ValueError:
        return 250


def _flush_interval_seconds() -> float:
    try:
        return max(0.2, float(os.environ.get("CLICKHOUSE_ANALYTICS_FLUSH_INTERVAL_SECONDS", "2.0")))
    except ValueError:
        return 2.0


class AnalyticsPipeline:
    def __init__(self) -> None:
        self.backend = _analytics_backend()
        self.url = _clickhouse_url()
        self._started = False
        self._ready = False
        self._queue: deque[dict[str, Any]] = deque()
        self._lock = asyncio.Lock()
        self._flush_task: asyncio.Task | None = None
        self._published = 0
        self._failed = 0
        self._last_error = ""

    async def start(self) -> None:
        if self._started:
            return
        self._started = True
        for topic in (
            EventTopics.ACTIVITY_LOGS,
            EventTopics.AGENT_EVENTS,
            EventTopics.SCREENSHOT_EVENTS,
            EventTopics.DLP_EVENTS,
            EventTopics.PHISHING_EVENTS,
            EventTopics.ALERT_EVENTS,
            EventTopics.AUDIT_EVENTS,
        ):
            internal_event_bus.subscribe(topic, self._handle_event)
        if self.backend == "clickhouse" and self.url:
            try:
                await asyncio.to_thread(self._ensure_clickhouse_schema)
                self._ready = True
                self._flush_task = asyncio.create_task(self._flush_loop())
            except Exception as exc:
                self._last_error = str(exc)
                logger.warning("Analytics pipeline schema init failed: %s", exc)
        else:
            self._ready = False

    async def stop(self) -> None:
        if not self._started:
            return
        for topic in (
            EventTopics.ACTIVITY_LOGS,
            EventTopics.AGENT_EVENTS,
            EventTopics.SCREENSHOT_EVENTS,
            EventTopics.DLP_EVENTS,
            EventTopics.PHISHING_EVENTS,
            EventTopics.ALERT_EVENTS,
            EventTopics.AUDIT_EVENTS,
        ):
            internal_event_bus.unsubscribe(topic, self._handle_event)
        if self._flush_task:
            self._flush_task.cancel()
            try:
                await self._flush_task
            except asyncio.CancelledError:
                pass
            self._flush_task = None
        self._started = False
        self._ready = False

    def read_enabled(self) -> bool:
        return self.backend == "clickhouse" and self._ready and _read_enabled()

    def status(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "ready": self._ready,
            "started": self._started,
            "read_enabled": self.read_enabled(),
            "queue_depth": len(self._queue),
            "published": self._published,
            "failed": self._failed,
            "last_error": self._last_error,
        }

    async def _handle_event(self, topic: str, envelope: EventEnvelope) -> None:
        if self.backend != "clickhouse" or not self.url:
            return
        row = {
            "tenant_id": int(envelope.tenant_id or 0),
            "machine_id": envelope.machine_id or "",
            "event_topic": topic,
            "event_type": envelope.event_type,
            "occurred_at": envelope.occurred_at,
            "produced_at": envelope.produced_at,
            "schema_version": int(envelope.schema_version or 1),
            "trace_id": envelope.trace_id or "",
            "payload_json": json.dumps(envelope.payload or {}, default=str, separators=(",", ":")),
        }
        async with self._lock:
            self._queue.append(row)

    async def _flush_loop(self) -> None:
        while True:
            await asyncio.sleep(_flush_interval_seconds())
            if not self._ready:
                continue
            rows = await self._dequeue_batch()
            if not rows:
                continue
            try:
                await asyncio.to_thread(self._insert_rows, rows)
                self._published += len(rows)
            except Exception as exc:
                self._failed += len(rows)
                self._last_error = str(exc)
                logger.warning("Analytics pipeline flush failed: %s", exc)
                async with self._lock:
                    for row in reversed(rows):
                        self._queue.appendleft(row)

    async def _dequeue_batch(self) -> list[dict[str, Any]]:
        batch_size = _flush_batch_size()
        async with self._lock:
            rows: list[dict[str, Any]] = []
            while self._queue and len(rows) < batch_size:
                rows.append(self._queue.popleft())
            return rows

    def _clickhouse_request(self, sql: str, *, data: bytes | None = None, content_type: str = "text/plain") -> bytes:
        if not self.url:
            raise RuntimeError("CLICKHOUSE_URL is not configured")
        query = parse.urlencode({"query": sql})
        target = f"{self.url}/?{query}"
        req = request.Request(target, data=data, method="POST" if data is not None else "GET")
        req.add_header("Content-Type", content_type)
        try:
            with request.urlopen(req, timeout=15) as response:
                return response.read()
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"ClickHouse HTTP {exc.code}: {detail}") from exc

    def _ensure_clickhouse_schema(self) -> None:
        self._clickhouse_request(
            """
            CREATE TABLE IF NOT EXISTS analytics_events (
                tenant_id UInt32,
                machine_id String,
                event_topic String,
                event_type String,
                occurred_at DateTime64(3, 'UTC'),
                produced_at DateTime64(3, 'UTC'),
                schema_version UInt32,
                trace_id String,
                payload_json String
            ) ENGINE = MergeTree
            ORDER BY (tenant_id, machine_id, occurred_at, event_type)
            """
        )

    def _insert_rows(self, rows: list[dict[str, Any]]) -> None:
        payload = "\n".join(json.dumps(row, separators=(",", ":")) for row in rows).encode("utf-8")
        self._clickhouse_request(
            "INSERT INTO analytics_events FORMAT JSONEachRow",
            data=payload,
            content_type="application/json",
        )

    def _query_json(self, sql: str) -> dict[str, Any]:
        raw = self._clickhouse_request(f"{sql} FORMAT JSON")
        return json.loads(raw.decode("utf-8"))

    @staticmethod
    def _time_filters(start_date: str | None = None, end_date: str | None = None) -> str:
        parts: list[str] = []
        if start_date:
            parts.append(f"occurred_at >= parseDateTimeBestEffort('{start_date}')")
        if end_date:
            parts.append(f"occurred_at <= parseDateTimeBestEffort('{end_date}T23:59:59')")
        return (" AND " + " AND ".join(parts)) if parts else ""

    def get_overview_stats(self, tenant_id: int) -> dict[str, Any]:
        if not self.read_enabled():
            raise RuntimeError("ClickHouse analytics reads are not enabled")
        total_rows = self._query_json(
            f"""
            SELECT
                countDistinctIf(machine_id, event_type = 'agent.heartbeat.ingested') AS total_machines,
                countDistinctIf(machine_id, event_type = 'activity.application.ingested' AND toDate(occurred_at) = today()) AS active_today
            FROM analytics_events
            WHERE tenant_id = {int(tenant_id)}
            """
        )
        top_apps_rows = self._query_json(
            f"""
            SELECT
                JSONExtractString(payload_json, 'app_name') AS app_name,
                sum(toInt64OrZero(JSONExtract(payload_json, 'duration_seconds', 'Int64'))) AS total
            FROM analytics_events
            WHERE tenant_id = {int(tenant_id)}
              AND event_type = 'activity.application.ingested'
            GROUP BY app_name
            HAVING app_name != ''
            ORDER BY total DESC
            LIMIT 10
            """
        )
        top_domain_rows = self._query_json(
            f"""
            SELECT
                JSONExtractString(payload_json, 'domain') AS domain,
                count() AS visits
            FROM analytics_events
            WHERE tenant_id = {int(tenant_id)}
              AND event_type = 'activity.browser.ingested'
            GROUP BY domain
            HAVING domain != ''
            ORDER BY visits DESC
            LIMIT 10
            """
        )
        daily_rows = self._query_json(
            f"""
            SELECT
                toString(toDate(occurred_at)) AS date,
                countDistinct(machine_id) AS machines,
                sum(toInt64OrZero(JSONExtract(payload_json, 'duration_seconds', 'Int64'))) AS total_seconds
            FROM analytics_events
            WHERE tenant_id = {int(tenant_id)}
              AND event_type = 'activity.application.ingested'
              AND occurred_at >= now() - INTERVAL 7 DAY
            GROUP BY date
            ORDER BY date ASC
            """
        )
        summary_row = (total_rows.get("data") or [{}])[0]
        return {
            "total_machines": int(summary_row.get("total_machines", 0) or 0),
            "active_today": int(summary_row.get("active_today", 0) or 0),
            "top_apps": [{"app_name": row.get("app_name", ""), "total": int(row.get("total", 0) or 0)} for row in top_apps_rows.get("data", [])],
            "top_domains": [{"domain": row.get("domain", ""), "visits": int(row.get("visits", 0) or 0)} for row in top_domain_rows.get("data", [])],
            "daily_activity": [
                {
                    "date": row.get("date", ""),
                    "machines": int(row.get("machines", 0) or 0),
                    "total_seconds": int(row.get("total_seconds", 0) or 0),
                }
                for row in daily_rows.get("data", [])
            ],
        }

    def get_machine_analytics(self, tenant_id: int, machine_id: str, start_date: str | None = None, end_date: str | None = None) -> dict[str, Any]:
        if not self.read_enabled():
            raise RuntimeError("ClickHouse analytics reads are not enabled")
        filters = self._time_filters(start_date, end_date)
        safe_machine = machine_id.replace("'", "''")
        safe_tenant = int(tenant_id)
        app_rows = self._query_json(
            f"""
            SELECT
                JSONExtractString(payload_json, 'app_name') AS app_name,
                sum(toInt64OrZero(JSONExtract(payload_json, 'duration_seconds', 'Int64'))) AS total_seconds,
                count() AS sessions
            FROM analytics_events
            WHERE tenant_id = {safe_tenant}
              AND machine_id = '{safe_machine}'
              AND event_type = 'activity.application.ingested'
              {filters}
            GROUP BY app_name
            HAVING app_name != ''
            ORDER BY total_seconds DESC
            LIMIT 15
            """
        )
        browser_rows = self._query_json(
            f"""
            SELECT
                JSONExtractString(payload_json, 'domain') AS domain,
                count() AS visits,
                sum(toInt64OrZero(JSONExtract(payload_json, 'duration_seconds', 'Int64'))) AS total_seconds
            FROM analytics_events
            WHERE tenant_id = {safe_tenant}
              AND machine_id = '{safe_machine}'
              AND event_type = 'activity.browser.ingested'
              {filters}
            GROUP BY domain
            HAVING domain != ''
            ORDER BY visits DESC
            LIMIT 15
            """
        )
        hourly_rows = self._query_json(
            f"""
            SELECT
                toHour(occurred_at) AS hour,
                sum(toInt64OrZero(JSONExtract(payload_json, 'duration_seconds', 'Int64'))) AS total_seconds
            FROM analytics_events
            WHERE tenant_id = {safe_tenant}
              AND machine_id = '{safe_machine}'
              AND event_type = 'activity.application.ingested'
              {filters}
            GROUP BY hour
            ORDER BY hour ASC
            """
        )
        daily_rows = self._query_json(
            f"""
            SELECT
                toString(toDate(occurred_at)) AS date,
                sum(toInt64OrZero(JSONExtract(payload_json, 'duration_seconds', 'Int64'))) AS total_seconds
            FROM analytics_events
            WHERE tenant_id = {safe_tenant}
              AND machine_id = '{safe_machine}'
              AND event_type = 'activity.application.ingested'
              {filters}
            GROUP BY date
            ORDER BY date DESC
            LIMIT 30
            """
        )
        totals = self._query_json(
            f"""
            SELECT
                sumIf(toInt64OrZero(JSONExtract(payload_json, 'duration_seconds', 'Int64')), event_type = 'activity.application.ingested') AS total_active_seconds,
                countIf(event_type = 'activity.browser.ingested') AS browser_visits
            FROM analytics_events
            WHERE tenant_id = {safe_tenant}
              AND machine_id = '{safe_machine}'
              {filters}
            """
        )
        total_row = (totals.get("data") or [{}])[0]
        return {
            "app_usage": [
                {
                    "app_name": row.get("app_name", ""),
                    "total_seconds": int(row.get("total_seconds", 0) or 0),
                    "sessions": int(row.get("sessions", 0) or 0),
                }
                for row in app_rows.get("data", [])
            ],
            "browser_usage": [
                {
                    "domain": row.get("domain", ""),
                    "visits": int(row.get("visits", 0) or 0),
                    "total_seconds": int(row.get("total_seconds", 0) or 0),
                }
                for row in browser_rows.get("data", [])
            ],
            "hourly_activity": [
                {
                    "hour": str(int(row.get("hour", 0) or 0)).zfill(2),
                    "total_seconds": int(row.get("total_seconds", 0) or 0),
                }
                for row in hourly_rows.get("data", [])
            ],
            "daily_activity": [
                {
                    "date": row.get("date", ""),
                    "total_seconds": int(row.get("total_seconds", 0) or 0),
                }
                for row in daily_rows.get("data", [])
            ],
            "total_active_seconds": int(total_row.get("total_active_seconds", 0) or 0),
            "browser_visits": int(total_row.get("browser_visits", 0) or 0),
        }


analytics_pipeline = AnalyticsPipeline()
