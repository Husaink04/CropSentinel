"""Internal service routes for staged Wave 3 service extraction."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app.analytics_pipeline import analytics_pipeline
from app.core import agent_public_config as _agent_public_config
from app.event_bus import internal_event_bus
from app.event_workers import internal_event_workers
from app.internal_service_registry import SERVICE_CATALOG, service_catalog_snapshot
from app.routers.machines_activity import (
    heartbeat as public_heartbeat,
    receive_app_activity as public_receive_app_activity,
    receive_browser_activity as public_receive_browser_activity,
    receive_input_activity as public_receive_input_activity,
    receive_phishing_activity as public_receive_phishing_activity,
    receive_screenshot as public_receive_screenshot,
    receive_activity_batch as public_receive_activity_batch,
    register_machine as public_register_machine,
)
from app.service_auth import require_internal_service, require_internal_service_scope
from app.ws_service import manager
from database import db
from models import (
    AppActivityRequest,
    BrowserActivityRequest,
    HeartbeatRequest,
    InputActivityRequest,
    MachineRegisterRequest,
    PhishingEventRequest,
    ScreenshotRequest,
)

router = APIRouter()


class InternalBroadcastRequest(BaseModel):
    payload: dict


class InternalAgentCommandRequest(BaseModel):
    payload: dict


def _bind_internal_tenant_from_enroll_token(request: Request) -> None:
    token = (
        request.headers.get("X-CropSentinel-Enroll-Token")
        or request.headers.get("x-cropsentinel-enroll-token")
        or request.headers.get("X-CropPro-Enroll-Token")
        or request.headers.get("x-croppro-enroll-token")
        or ""
    ).strip()
    if not token:
        return
    tenant = db.get_tenant_by_enrollment_token(token)
    if tenant:
        request.state.tenant_id = int(tenant["id"])


def _service_metadata(name: str) -> dict:
    meta = SERVICE_CATALOG.get(name)
    if not meta:
        raise HTTPException(status_code=404, detail="Internal service not found")
    return {"name": name, **dict(meta)}


@router.get("/_internal/services")
async def list_internal_services(service=Depends(require_internal_service)):
    return {
        "caller": service,
        "services": service_catalog_snapshot(),
        "event_bus": internal_event_bus.status(),
    }


@router.get("/_internal/services/{service_name}")
async def get_internal_service_metadata(service_name: str, caller=Depends(require_internal_service)):
    return {
        "caller": caller,
        "service": _service_metadata(service_name),
    }


@router.get("/_internal/services/{service_name}/health")
async def get_internal_service_health(service_name: str, caller=Depends(require_internal_service)):
    meta = _service_metadata(service_name)
    payload = {
        "status": "ok",
        "caller": caller,
        "service": meta,
        "event_bus": internal_event_bus.status(),
    }
    if service_name == "realtime":
        payload["realtime"] = {
            "online_agents": manager.online(),
            "online_count": len(manager.online()),
            "ws_routes": ["/ws/admin", "/ws/agent/{machine_id}"],
        }
    if service_name == "monitoring":
        payload["analytics_pipeline"] = analytics_pipeline.status()
        payload["event_workers"] = internal_event_workers.status()
    return payload


@router.post("/_internal/services/agent-control/machines/register")
async def internal_register_machine(
    req: MachineRegisterRequest,
    request: Request,
    _svc=Depends(require_internal_service_scope("gateway", "agent-control")),
):
    _bind_internal_tenant_from_enroll_token(request)
    return await public_register_machine(req, request, None)


@router.post("/_internal/services/agent-control/machines/heartbeat")
async def internal_heartbeat(
    req: HeartbeatRequest,
    request: Request,
    _svc=Depends(require_internal_service_scope("gateway", "agent-control", "monitoring")),
):
    return await public_heartbeat(req, request, None)


@router.get("/_internal/services/agent-control/machines/{machine_id}/config")
async def internal_agent_config(
    machine_id: str,
    _svc=Depends(require_internal_service_scope("gateway", "agent-control", "realtime")),
):
    return {
        "machine_id": machine_id,
        "tenant_id": db.get_machine_tenant_id(machine_id) or 1,
        "online": machine_id in manager.online(),
        "config": _agent_public_config(),
    }


@router.post("/_internal/services/monitoring/ingest/browser")
async def internal_ingest_browser(
    req: BrowserActivityRequest,
    _svc=Depends(require_internal_service_scope("gateway", "monitoring", "agent-control")),
):
    return await public_receive_browser_activity(req, None)


@router.post("/_internal/services/monitoring/ingest/application")
async def internal_ingest_application(
    req: AppActivityRequest,
    _svc=Depends(require_internal_service_scope("gateway", "monitoring", "agent-control")),
):
    return await public_receive_app_activity(req, None)


@router.post("/_internal/services/monitoring/ingest/screenshot")
async def internal_ingest_screenshot(
    req: ScreenshotRequest,
    _svc=Depends(require_internal_service_scope("gateway", "monitoring", "agent-control")),
):
    return await public_receive_screenshot(req, None)


@router.post("/_internal/services/monitoring/ingest/input")
async def internal_ingest_input(
    req: InputActivityRequest,
    _svc=Depends(require_internal_service_scope("gateway", "monitoring", "agent-control")),
):
    return await public_receive_input_activity(req, None)


@router.post("/_internal/services/monitoring/ingest/phishing")
async def internal_ingest_phishing(
    req: PhishingEventRequest,
    request: Request,
    _svc=Depends(require_internal_service_scope("gateway", "monitoring", "agent-control")),
):
    return await public_receive_phishing_activity(req, request, None)


@router.post("/_internal/services/monitoring/ingest/batch")
async def internal_ingest_batch(
    request: Request,
    _svc=Depends(require_internal_service_scope("gateway", "monitoring", "agent-control")),
):
    return await public_receive_activity_batch(request, None)


@router.get("/_internal/services/realtime/presence")
async def internal_realtime_presence(_svc=Depends(require_internal_service_scope("gateway", "realtime", "agent-control"))):
    online = manager.online()
    return {
        "online_agents": online,
        "online_count": len(online),
    }


@router.post("/_internal/services/realtime/broadcast")
async def internal_realtime_broadcast(
    req: InternalBroadcastRequest,
    _svc=Depends(require_internal_service_scope("gateway", "realtime", "monitoring", "agent-control")),
):
    await manager.broadcast(req.payload)
    return {"status": "ok"}


@router.post("/_internal/services/realtime/agents/{machine_id}/command")
async def internal_send_agent_command(
    machine_id: str,
    req: InternalAgentCommandRequest,
    _svc=Depends(require_internal_service_scope("gateway", "realtime", "agent-control")),
):
    delivered = await manager.send_to_agent(machine_id, req.payload)
    return {
        "status": "ok" if delivered else "queued",
        "machine_id": machine_id,
        "delivered": delivered,
    }
