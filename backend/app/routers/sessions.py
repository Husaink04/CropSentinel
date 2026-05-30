"""Session capability endpoints for live view and remote access."""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel

from app.core import audit_log, check_machine_access, require_feature, require_permission
from app.services.session_service import normalize_session_kind, require_session_access, session_capabilities
from app.ws_service import manager
from licensing import has_feature as license_has_feature

router = APIRouter()


class SessionStartRequest(BaseModel):
    session_kind: str = "live"


@router.get("/api/sessions/machines/{machine_id}/capabilities")
async def get_session_capabilities(request: Request, machine_id: str, user=Depends(require_permission("machines.view"))):
    check_machine_access(user, machine_id)
    live_remote_feature = license_has_feature(getattr(request.app.state, "license", None), "remote_access")
    capabilities = session_capabilities(user, machine_id, remote_access_licensed=live_remote_feature)
    capabilities["online"] = machine_id in manager.online()
    return capabilities


@router.post("/api/sessions/machines/{machine_id}/start")
async def start_session_handshake(
    request: Request,
    machine_id: str,
    req: SessionStartRequest,
    user=Depends(require_permission("machines.view")),
):
    kind = normalize_session_kind(req.session_kind)
    if kind == "remote":
        await require_feature("remote_access")(request)
    require_session_access(user, machine_id, kind)
    audit_log(request, user, "session_start_requested", "machine", machine_id, {"session_kind": kind})
    return {
        "machine_id": machine_id,
        "session_kind": kind,
        "online": machine_id in manager.online(),
        "requires_websocket": True,
    }
