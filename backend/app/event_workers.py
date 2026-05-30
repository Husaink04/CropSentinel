"""Background consumers for next-gen internal events."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path

from app.db.core import clear_tenant_context, set_tenant_context
from app.event_bus import EventEnvelope, EventTopics, internal_event_bus
from database import db
from pdf_generator import generate_report

logger = logging.getLogger("cropsentinel.event_workers")


def _screenshot_quota_mb() -> int:
    try:
        return int(os.environ.get("SCREENSHOT_QUOTA_MB", "500"))
    except ValueError:
        return 500


def _screenshot_quota_sample() -> int:
    try:
        return max(1, int(os.environ.get("SCREENSHOT_QUOTA_SAMPLE", "20")))
    except ValueError:
        return 20


def _report_filename(hostname: str) -> str:
    safe_hostname = (hostname or "machine").replace(" ", "_")
    from database import utcnow  # noqa: PLC0415

    return f"CropSentinel_{safe_hostname}_{utcnow().strftime('%Y%m%d')}.pdf"


def _event_sink_root() -> Path:
    raw = os.environ.get("EVENT_SINK_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path(__file__).resolve().parents[1] / "storage" / "ops" / "event-sinks").resolve()


def _event_sinks_enabled() -> bool:
    return os.environ.get("EVENT_SINKS_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}


class InternalEventWorkers:
    def __init__(self) -> None:
        self._started = False
        self._screenshot_insert_count: dict[int, int] = {}
        self._sink_counts: dict[str, int] = {
            "audit": 0,
            "dlp": 0,
            "phishing": 0,
            "reports": 0,
        }

    async def start(self) -> None:
        if self._started:
            return
        internal_event_bus.subscribe(EventTopics.SCREENSHOT_EVENTS, self._handle_screenshot_event)
        internal_event_bus.subscribe(EventTopics.SYSTEM_EVENTS, self._handle_system_event)
        if _event_sinks_enabled():
            internal_event_bus.subscribe(EventTopics.AUDIT_EVENTS, self._handle_audit_event)
            internal_event_bus.subscribe(EventTopics.DLP_EVENTS, self._handle_dlp_event)
            internal_event_bus.subscribe(EventTopics.PHISHING_EVENTS, self._handle_phishing_event)
        self._started = True

    async def stop(self) -> None:
        if not self._started:
            return
        internal_event_bus.unsubscribe(EventTopics.SCREENSHOT_EVENTS, self._handle_screenshot_event)
        internal_event_bus.unsubscribe(EventTopics.SYSTEM_EVENTS, self._handle_system_event)
        if _event_sinks_enabled():
            internal_event_bus.unsubscribe(EventTopics.AUDIT_EVENTS, self._handle_audit_event)
            internal_event_bus.unsubscribe(EventTopics.DLP_EVENTS, self._handle_dlp_event)
            internal_event_bus.unsubscribe(EventTopics.PHISHING_EVENTS, self._handle_phishing_event)
        self._started = False
        self._screenshot_insert_count.clear()
        for key in list(self._sink_counts.keys()):
            self._sink_counts[key] = 0

    def status(self) -> dict:
        return {
            "started": self._started,
            "screenshot_quota_tenants": len(self._screenshot_insert_count),
            "event_sinks": dict(self._sink_counts),
            "sink_root": str(_event_sink_root()),
        }

    async def _handle_screenshot_event(self, topic: str, envelope: EventEnvelope) -> None:
        if topic != EventTopics.SCREENSHOT_EVENTS or envelope.event_type != "activity.screenshot.ingested":
            return
        tenant_id = int(envelope.tenant_id or 0)
        quota_mb = _screenshot_quota_mb()
        if tenant_id <= 0 or quota_mb <= 0:
            return
        count = self._screenshot_insert_count.get(tenant_id, 0) + 1
        self._screenshot_insert_count[tenant_id] = count
        if count % _screenshot_quota_sample() != 0:
            return
        await asyncio.to_thread(self._enforce_screenshot_quota, tenant_id, quota_mb)

    async def _handle_system_event(self, topic: str, envelope: EventEnvelope) -> None:
        if topic != EventTopics.SYSTEM_EVENTS or envelope.event_type != "report.generate.requested":
            if topic == EventTopics.SYSTEM_EVENTS and envelope.event_type in {"report.generate.completed", "report.generate.failed"}:
                await asyncio.to_thread(self._append_sink_record, "reports", envelope)
            return
        await asyncio.to_thread(self._generate_report_job, envelope)

    async def _handle_audit_event(self, topic: str, envelope: EventEnvelope) -> None:
        if topic == EventTopics.AUDIT_EVENTS:
            await asyncio.to_thread(self._append_sink_record, "audit", envelope)

    async def _handle_dlp_event(self, topic: str, envelope: EventEnvelope) -> None:
        if topic == EventTopics.DLP_EVENTS:
            await asyncio.to_thread(self._append_sink_record, "dlp", envelope)

    async def _handle_phishing_event(self, topic: str, envelope: EventEnvelope) -> None:
        if topic == EventTopics.PHISHING_EVENTS:
            await asyncio.to_thread(self._append_sink_record, "phishing", envelope)

    def _enforce_screenshot_quota(self, tenant_id: int, quota_mb: int) -> None:
        max_bytes = quota_mb * 1024 * 1024
        try:
            removed = db.enforce_screenshot_quota(tenant_id, max_bytes)
            if removed:
                logger.info("Tenant %s screenshot quota GC removed %s old screenshots", tenant_id, removed)
        except Exception as exc:
            logger.warning("Screenshot quota GC failed for tenant %s: %s", tenant_id, exc)

    def _generate_report_job(self, envelope: EventEnvelope) -> None:
        payload = envelope.payload or {}
        tenant_id = int(envelope.tenant_id or payload.get("tenant_id") or 1)
        job_id = str(payload.get("job_id") or "")
        machine_id = str(payload.get("machine_id") or "")
        start_date = payload.get("start_date")
        end_date = payload.get("end_date")
        if not job_id or not machine_id:
            logger.warning("Skipping malformed report job event: %s", payload)
            return
        try:
            set_tenant_context(tenant_id)
            db.mark_report_job_running(job_id)
            machine = db.get_machine(machine_id)
            if not machine:
                raise RuntimeError("Machine not found")
            analytics = db.get_machine_analytics(machine_id, start_date, end_date)
            browser = db.get_browser_history(machine_id, 50)
            apps = db.get_app_usage(machine_id)
            settings = db.get_settings()
            pdf_path = generate_report(machine, analytics, browser, apps, settings, start_date, end_date)
            output_path = str(Path(pdf_path).resolve())
            filename = _report_filename(machine.get("hostname", machine_id))
            artifact = db.create_generated_artifact(
                category="report_exports",
                evidence_classification="generated_report",
                content_type="application/pdf",
                filename=filename,
                raw_bytes=Path(pdf_path).read_bytes(),
                machine_id=machine_id,
                metadata={
                    "machine_id": machine_id,
                    "hostname": machine.get("hostname", machine_id),
                    "start_date": start_date or "",
                    "end_date": end_date or "",
                },
            )
            db.complete_report_job(
                job_id,
                output_path="",
                evidence_id=artifact["id"],
                storage_key=artifact["storage_key"],
                storage_backend=artifact["storage_backend"],
                content_type="application/pdf",
                filename=filename,
                metadata={"hostname": machine.get("hostname", machine_id), "artifact_id": artifact["id"]},
            )
            try:
                Path(pdf_path).unlink(missing_ok=True)
            except Exception:
                pass
            internal_event_bus.publish(
                topic=EventTopics.SYSTEM_EVENTS,
                event_type="report.generate.completed",
                tenant_id=tenant_id,
                machine_id=machine_id,
                payload={"job_id": job_id, "machine_id": machine_id, "artifact_id": artifact["id"]},
            )
        except Exception as exc:
            logger.warning("Report job failed job_id=%s machine_id=%s: %s", job_id, machine_id, exc)
            db.fail_report_job(job_id, str(exc))
            internal_event_bus.publish(
                topic=EventTopics.SYSTEM_EVENTS,
                event_type="report.generate.failed",
                tenant_id=tenant_id,
                machine_id=machine_id,
                payload={"job_id": job_id, "machine_id": machine_id, "error": str(exc)},
            )
        finally:
            clear_tenant_context()

    def _append_sink_record(self, sink_name: str, envelope: EventEnvelope) -> None:
        root = _event_sink_root()
        root.mkdir(parents=True, exist_ok=True)
        target = root / f"{sink_name}.jsonl"
        record = {
            "topic": sink_name,
            "event_id": envelope.event_id,
            "event_type": envelope.event_type,
            "tenant_id": envelope.tenant_id,
            "machine_id": envelope.machine_id,
            "occurred_at": envelope.occurred_at,
            "produced_at": envelope.produced_at,
            "schema_version": envelope.schema_version,
            "trace_id": envelope.trace_id,
            "payload": envelope.payload,
        }
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, default=str, ensure_ascii=True, separators=(",", ":")) + "\n")
        self._sink_counts[sink_name] = self._sink_counts.get(sink_name, 0) + 1


internal_event_workers = InternalEventWorkers()
