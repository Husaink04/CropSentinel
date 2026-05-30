"""Shared activity ingestion service for HTTP and WebSocket agent events."""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi.encoders import jsonable_encoder

from database import db, utcnow_iso
from app.db.core import get_tenant_id as _tid
from app.event_bus import EventTopics, internal_event_bus

logger = logging.getLogger("croppro")

_DEDUP_TTL_SECONDS = int(os.environ.get("ACTIVITY_EVENT_DEDUP_TTL_SECONDS", "900"))
_MAX_GENERIC_JSON_BYTES = int(os.environ.get("ACTIVITY_MAX_JSON_BYTES", str(256 * 1024)))
_MAX_SCREENSHOT_JSON_BYTES = int(os.environ.get("SCREENSHOT_MAX_JSON_BYTES", str(6 * 1024 * 1024)))
_MAX_FILE_JSON_BYTES = int(os.environ.get("FILE_ACTIVITY_MAX_JSON_BYTES", str(2 * 1024 * 1024)))
_MAX_NETWORK_JSON_BYTES = int(os.environ.get("NETWORK_ACTIVITY_MAX_JSON_BYTES", str(768 * 1024)))
_MAX_NETWORK_CONNECTIONS = int(os.environ.get("NETWORK_ACTIVITY_MAX_CONNECTIONS", "2048"))
_MAX_NETWORK_PORTS = int(os.environ.get("NETWORK_ACTIVITY_MAX_PORTS", "512"))


class ActivityValidationError(ValueError):
    def __init__(self, code: str, message: str, *, status_code: int = 422):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


@dataclass
class IngestResult:
    response: dict[str, Any] = field(default_factory=lambda: {"status": "ok"})
    broadcasts: list[dict[str, Any]] = field(default_factory=list)
    duplicate: bool = False


class _EventDeduper:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._seen: dict[tuple[str, str, str], float] = {}

    def _purge_locked(self, now: float) -> None:
        expired = [key for key, expiry in self._seen.items() if expiry <= now]
        for key in expired:
            self._seen.pop(key, None)

    def remember(self, machine_id: str, event_type: str, event_id: str | None) -> bool:
        if not event_id:
            return False
        now = time.time()
        key = (machine_id or "", event_type or "", str(event_id))
        with self._lock:
            self._purge_locked(now)
            expiry = self._seen.get(key)
            if expiry and expiry > now:
                return True
            self._seen[key] = now + _DEDUP_TTL_SECONDS
        return False


_deduper = _EventDeduper()


def _json_size_bytes(payload: dict[str, Any]) -> int:
    encoded = json.dumps(jsonable_encoder(payload), ensure_ascii=False, separators=(",", ":"))
    return len(encoded.encode("utf-8"))


def _require_payload_cap(event_type: str, payload: dict[str, Any]) -> None:
    limit = _MAX_GENERIC_JSON_BYTES
    if event_type == "screenshot":
        limit = _MAX_SCREENSHOT_JSON_BYTES
    elif event_type == "file":
        limit = _MAX_FILE_JSON_BYTES
    elif event_type == "network":
        limit = _MAX_NETWORK_JSON_BYTES
    size = _json_size_bytes(payload)
    if size > limit:
        raise ActivityValidationError(
            "payload_too_large",
            f"{event_type} payload exceeds limit ({size} > {limit} bytes)",
            status_code=413,
        )


def _normalize_machine_payload(machine_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = dict(payload or {})
    data["machine_id"] = machine_id
    return data


def _tenant_id_for_machine(machine_id: str) -> int | None:
    tenant_id = _tid()
    if tenant_id:
        return int(tenant_id)
    resolved = db.get_machine_tenant_id(machine_id)
    return int(resolved) if resolved else None


def _emit(topic: str, event_type: str, machine_id: str, payload: dict[str, Any]) -> None:
    internal_event_bus.publish(
        topic=topic,
        event_type=event_type,
        tenant_id=_tenant_id_for_machine(machine_id),
        machine_id=machine_id,
        payload=payload,
        occurred_at=payload.get("timestamp"),
    )


def _validate_network_payload(payload: dict[str, Any]) -> None:
    connections = payload.get("connections") or []
    listening_ports = payload.get("listening_ports") or []
    if len(connections) > _MAX_NETWORK_CONNECTIONS:
        raise ActivityValidationError(
            "network_connections_limit",
            f"connections exceeds limit ({len(connections)} > {_MAX_NETWORK_CONNECTIONS})",
        )
    if len(listening_ports) > _MAX_NETWORK_PORTS:
        raise ActivityValidationError(
            "network_ports_limit",
            f"listening_ports exceeds limit ({len(listening_ports)} > {_MAX_NETWORK_PORTS})",
        )


def _backup_meta_payload(machine_id: str, payload: dict[str, Any]) -> None:
    if payload.get("file_name"):
        return
    payload["file_name"] = os.path.basename(payload.get("file_path", ""))


class ActivityIngestService:
    def ingest_browser(self, machine_id: str, payload: dict[str, Any]) -> IngestResult:
        data = _normalize_machine_payload(machine_id, payload)
        if _deduper.remember(machine_id, "browser", data.get("event_id")):
            return IngestResult(response={"status": "ok", "duplicate": True}, duplicate=True)
        _require_payload_cap("browser", data)
        db.insert_browser_activity(data)
        _emit(EventTopics.ACTIVITY_LOGS, "activity.browser.ingested", machine_id, data)
        broadcasts = [{"type": "browser_update", "machine_id": machine_id, "data": data}]
        for alert in db.evaluate_alerts_for_browser(machine_id, data.get("domain", "")):
            broadcasts.append({"type": "new_alert", **alert})
        return IngestResult(broadcasts=broadcasts)

    def ingest_application(self, machine_id: str, payload: dict[str, Any]) -> IngestResult:
        data = _normalize_machine_payload(machine_id, payload)
        if _deduper.remember(machine_id, "application", data.get("event_id")):
            return IngestResult(response={"status": "ok", "duplicate": True}, duplicate=True)
        _require_payload_cap("application", data)
        db.insert_app_activity(data)
        _emit(EventTopics.ACTIVITY_LOGS, "activity.application.ingested", machine_id, data)
        return IngestResult(broadcasts=[{"type": "app_update", "machine_id": machine_id, "data": data}])

    def ingest_screenshot(self, machine_id: str, payload: dict[str, Any]) -> IngestResult:
        data = _normalize_machine_payload(machine_id, payload)
        if _deduper.remember(machine_id, "screenshot", data.get("event_id")):
            return IngestResult(response={"status": "ok", "duplicate": True}, duplicate=True)
        _require_payload_cap("screenshot", data)
        db.insert_screenshot(data)
        _emit(EventTopics.SCREENSHOT_EVENTS, "activity.screenshot.ingested", machine_id, data)
        return IngestResult(
            broadcasts=[
                {
                    "type": "screenshot",
                    "machine_id": machine_id,
                    "timestamp": data.get("timestamp", ""),
                    "image_data": data.get("image_data", ""),
                    "trigger": data.get("trigger", "scheduled"),
                }
            ]
        )

    def ingest_heartbeat(
        self,
        machine_id: str,
        payload: dict[str, Any],
        *,
        client_geo: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None,
    ) -> IngestResult:
        data = _normalize_machine_payload(machine_id, payload)
        if client_geo:
            data["_geo"] = client_geo
        if _deduper.remember(machine_id, "heartbeat", data.get("event_id")):
            return IngestResult(response={"status": "ok", "duplicate": True, "config": config or {}})
        _require_payload_cap("heartbeat", data)
        db.update_machine_heartbeat(machine_id, data)
        _emit(EventTopics.AGENT_EVENTS, "agent.heartbeat.ingested", machine_id, data)
        broadcasts: list[dict[str, Any]] = []
        for alert in db.evaluate_alerts_for_heartbeat(machine_id, data):
            broadcasts.append({"type": "new_alert", **alert})
        return IngestResult(response={"status": "ok", "server_time": utcnow_iso(), "config": config or {}}, broadcasts=broadcasts)

    def ingest_input(self, machine_id: str, payload: dict[str, Any]) -> IngestResult:
        data = _normalize_machine_payload(machine_id, payload)
        if _deduper.remember(machine_id, "input", data.get("event_id")):
            return IngestResult(response={"status": "ok", "duplicate": True}, duplicate=True)
        _require_payload_cap("input", data)
        db.insert_input_activity(data)
        _emit(EventTopics.ACTIVITY_LOGS, "activity.input.ingested", machine_id, data)
        return IngestResult(broadcasts=[{"type": "input_update", "machine_id": machine_id, "data": data}])

    def ingest_file(self, machine_id: str, payload: dict[str, Any]) -> IngestResult:
        data = _normalize_machine_payload(machine_id, payload)
        if _deduper.remember(machine_id, "file", data.get("event_id")):
            return IngestResult(response={"status": "ok", "duplicate": True}, duplicate=True)
        _require_payload_cap("file", data)
        _backup_meta_payload(machine_id, data)
        file_data = data.pop("file_data", None)
        backup_meta = db.store_deleted_backup_from_activity(data, file_data)
        data["backup_available"] = backup_meta["backup_available"]
        data["backup_skip_reason"] = backup_meta["backup_skip_reason"]
        db.insert_file_activity(data)
        _emit(EventTopics.ACTIVITY_LOGS, "activity.file.ingested", machine_id, data)
        if data.get("action") == "delete":
            logger.info(
                "file_delete_ingest machine_id=%s backup_present=%s skip_reason=%s file_path=%s",
                machine_id,
                data.get("backup_available", False),
                data.get("backup_skip_reason", ""),
                data.get("file_path", ""),
            )
        return IngestResult(broadcasts=[{"type": "file_update", "machine_id": machine_id, "data": data}])

    def ingest_network(self, machine_id: str, payload: dict[str, Any]) -> IngestResult:
        data = _normalize_machine_payload(machine_id, payload)
        if _deduper.remember(machine_id, "network", data.get("event_id")):
            return IngestResult(response={"status": "ok", "duplicate": True}, duplicate=True)
        _validate_network_payload(data)
        _require_payload_cap("network", data)
        db.insert_network_activity(data)
        _emit(EventTopics.ACTIVITY_LOGS, "activity.network.ingested", machine_id, data)
        return IngestResult(broadcasts=[{"type": "network_update", "machine_id": machine_id, "data": data}])


activity_ingest_service = ActivityIngestService()
