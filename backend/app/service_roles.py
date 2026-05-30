"""Service role helpers for staged runtime extraction."""

from __future__ import annotations

import os

FULL_BACKEND_ROLE = "backend"
AGENT_CONTROL_ROLE = "agent-control"
MONITORING_ROLE = "monitoring"
REALTIME_ROLE = "realtime"


def normalize_service_role(role: str | None) -> str:
    return ((role or "").strip().lower() or FULL_BACKEND_ROLE)


def current_service_role() -> str:
    return normalize_service_role(os.environ.get("APP_SERVICE_ROLE", FULL_BACKEND_ROLE))


def role_name(role: str | None = None) -> str:
    return normalize_service_role(role if role is not None else current_service_role())


def is_full_backend(role: str | None = None) -> bool:
    return role_name(role) == FULL_BACKEND_ROLE


def enables_agent_control(role: str | None = None) -> bool:
    return role_name(role) in {FULL_BACKEND_ROLE, AGENT_CONTROL_ROLE}


def enables_monitoring(role: str | None = None) -> bool:
    return role_name(role) in {FULL_BACKEND_ROLE, MONITORING_ROLE}


def enables_realtime(role: str | None = None) -> bool:
    return role_name(role) in {FULL_BACKEND_ROLE, REALTIME_ROLE}


def enables_analytics_pipeline(role: str | None = None) -> bool:
    return enables_monitoring(role)


def enables_event_workers(role: str | None = None) -> bool:
    return enables_monitoring(role)


def enables_redis_fanout(role: str | None = None) -> bool:
    return enables_realtime(role)


def owns_schema_management(role: str | None = None) -> bool:
    return is_full_backend(role)


def runs_startup_backfill(role: str | None = None) -> bool:
    return owns_schema_management(role)


def runs_startup_seeding(role: str | None = None) -> bool:
    return owns_schema_management(role)
