"""Internal-only service routes for health and control-plane status."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import PlainTextResponse

from app.analytics_pipeline import analytics_pipeline
from app.event_bus import internal_event_bus
from app.event_workers import internal_event_workers
from app.internal_service_registry import service_catalog_snapshot
from app.ops_metrics import ops_metrics
from app.ops_runtime import backup_runtime_status
from app.service_auth import require_internal_observer, require_internal_service

router = APIRouter()


@router.get("/_internal/health/live")
async def internal_live_health():
    return {"status": "ok"}


@router.get("/_internal/health/ready")
async def internal_ready_health(request: Request, service=Depends(require_internal_service)):
    app = request.app
    return {
        "status": "ok",
        "service": service,
        "runtime": {
            "service_role": getattr(app.state, "service_role", "unknown"),
            "schema_init_enabled": bool(getattr(app.state, "schema_init_enabled", False)),
            "route_families": list(getattr(app.state, "route_families", ()) or []),
        },
        "event_bus": internal_event_bus.status(),
        "analytics_pipeline": analytics_pipeline.status(),
        "event_workers": internal_event_workers.status(),
        "internal_services": service_catalog_snapshot(),
        "backup": backup_runtime_status(),
    }


@router.get("/_internal/ops/status")
async def internal_ops_status(request: Request, service=Depends(require_internal_service)):
    app = request.app
    return {
        "status": "ok",
        "service": service,
        "runtime": {
            "service_role": getattr(app.state, "service_role", "unknown"),
            "schema_init_enabled": bool(getattr(app.state, "schema_init_enabled", False)),
            "route_families": list(getattr(app.state, "route_families", ()) or []),
        },
        "event_bus": internal_event_bus.status(),
        "analytics_pipeline": analytics_pipeline.status(),
        "event_workers": internal_event_workers.status(),
        "backup": backup_runtime_status(),
    }


@router.get("/_internal/runtime")
async def internal_runtime_status(request: Request, service=Depends(require_internal_service)):
    app = request.app
    role = getattr(app.state, "service_role", "unknown")
    route_families = list(getattr(app.state, "route_families", ()) or [])
    route_paths: list[str] = []
    if role != "unknown":
        from app.routers.registry import route_paths_for_role

        route_paths = route_paths_for_role(role)
    return {
        "status": "ok",
        "service": service,
        "service_role": role,
        "schema_init_enabled": bool(getattr(app.state, "schema_init_enabled", False)),
        "route_families": route_families,
        "route_paths": route_paths,
    }


@router.get("/_internal/metrics", response_class=PlainTextResponse)
async def internal_metrics(service=Depends(require_internal_observer)):
    return PlainTextResponse(
        ops_metrics.render_prometheus_text(backup_status=backup_runtime_status()),
        media_type="text/plain; version=0.0.4; charset=utf-8",
        headers={"X-Internal-Service": service},
    )
