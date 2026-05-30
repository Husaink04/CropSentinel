"""Shared activity event normalization for agent trackers."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

SCHEMA_VERSION = 1

HIGH_PRIORITY_KINDS = {"heartbeat", "screenshot"}
NORMAL_PRIORITY_KINDS = {
    "app",
    "browser",
    "file",
    "network",
    "input",
    "dlp_alert",
    "phishing_alert",
    "print",
    "usb",
}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_activity_payload(kind: str, data: dict) -> dict:
    payload = dict(data or {})
    payload.setdefault("event_id", uuid.uuid4().hex)
    payload.setdefault("captured_at", utcnow_iso())
    payload.setdefault("event_source", "agent")
    payload.setdefault("schema_version", SCHEMA_VERSION)
    payload.setdefault("activity_kind", kind)
    return payload


def resolve_activity_priority(kind: str, high_priority: int, normal_priority: int) -> int:
    if kind in HIGH_PRIORITY_KINDS:
        return high_priority
    return normal_priority
