"""Machine management and agent activity ingestion routes."""

from typing import Optional
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from app.core import (
    agent_public_config as _agent_public_config,
    audit_log,
    check_machine_access as _check_machine_access,
    filter_machines_for_user as _filter_machines_for_user,
    limiter,
    require_agent_api_key,
    require_permission,
)
from app.services.dlp_service import dlp_service
from app.services.phishing_service import phishing_service
from app.services.activity_ingest_service import ActivityValidationError, activity_ingest_service
from app.monitoring import set_sentry_tags
from app.ws_service import manager
from database import db, set_tenant_context, utcnow_iso
from geo_lookup import lookup as geo_lookup
from licensing import SeatEnforcer
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
logger = logging.getLogger("croppro")
ONLINE_HEARTBEAT_WINDOW_SECONDS = 120


def _annotate_machine_presence(machine: dict, realtime_online: set[str], recently_seen: set[str]) -> dict:
    machine_id = str(machine.get("machine_id") or "")
    ws_online = machine_id in realtime_online
    heartbeat_online = machine_id in recently_seen
    machine["realtime_connected"] = ws_online
    machine["online"] = ws_online or heartbeat_online
    return machine


@router.get("/api/machines")
async def get_machines(
    response: Response,
    user=Depends(require_permission("machines.view")),
    limit: Optional[int] = None,
    offset: int = 0,
    search: Optional[str] = None,
    status: Optional[str] = None,
):
    machines = db.get_all_machines()
    realtime_online = set(manager.online())
    recently_seen = db.get_recently_seen_machine_ids(ONLINE_HEARTBEAT_WINDOW_SECONDS)
    for machine in machines:
        _annotate_machine_presence(machine, realtime_online, recently_seen)
    machines = _filter_machines_for_user(machines, user)

    if search:
        query = search.lower().strip()
        machines = [
            m for m in machines
            if query in (m.get("hostname") or "").lower()
            or query in (m.get("username") or "").lower()
            or query in (m.get("ip_address") or "").lower()
            or query in (m.get("machine_id") or "").lower()
        ]
    if status == "online":
        machines = [m for m in machines if m.get("online")]
    elif status == "offline":
        machines = [m for m in machines if not m.get("online")]

    response.headers["X-Total-Count"] = str(len(machines))
    response.headers["Access-Control-Expose-Headers"] = "X-Total-Count"

    if limit is None:
        return machines
    lim = max(1, min(limit, 500))
    off = max(0, offset)
    return machines[off:off + lim]


@router.get("/api/machines/{machine_id}")
async def get_machine(machine_id: str, user=Depends(require_permission("machines.view"))):
    _check_machine_access(user, machine_id)
    machine = db.get_machine(machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    _annotate_machine_presence(
        machine,
        set(manager.online()),
        db.get_recently_seen_machine_ids(ONLINE_HEARTBEAT_WINDOW_SECONDS),
    )
    return machine


@router.put("/api/machines/{machine_id}")
async def update_machine(request: Request, machine_id: str, data: dict, user=Depends(require_permission("machines.edit"))):
    updated = db.update_machine(machine_id, data)
    if not updated:
        raise HTTPException(status_code=404, detail="Machine not found or no valid fields")
    audit_log(request, user, "machine_updated", "machine", machine_id)
    return {"message": "Machine updated"}


@router.delete("/api/machines/{machine_id}")
async def delete_machine(request: Request, machine_id: str, user=Depends(require_permission("machines.delete"))):
    machine = db.get_machine(machine_id)
    deleted = db.delete_machine(machine_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Machine not found")
    audit_log(request, user, "machine_deleted", "machine", machine_id, {"hostname": (machine or {}).get("hostname", "")})
    return {"message": f"Machine {machine_id} deleted"}


@router.delete("/api/machines/{machine_id}/activity")
async def delete_machine_activity(
    request: Request,
    machine_id: str,
    before_date: Optional[str] = None,
    user=Depends(require_permission("machines.delete")),
):
    counts = db.delete_all_activity_for_machine(machine_id)
    audit_log(request, user, "machine_activity_deleted", "machine", machine_id, {"counts": counts})
    return {"message": "Activity deleted", "counts": counts}


@router.post("/api/machines/register")
@limiter.limit("30/minute")
async def register_machine(req: MachineRegisterRequest, request: Request, _a=Depends(require_agent_api_key)):
    enroll_token_present = bool(
        request.headers.get("X-CropSentinel-Enroll-Token")
        or request.headers.get("x-cropsentinel-enroll-token")
        or request.headers.get("X-CropPro-Enroll-Token")
        or request.headers.get("x-croppro-enroll-token")
    )
    caller_tid = getattr(request.state, "tenant_id", None)
    existing_tid = db.get_machine_tenant_id(req.machine_id)
    if existing_tid and caller_tid and int(existing_tid) != int(caller_tid):
        logger.warning(
            "agent_register_denied reason_code=tenant_mismatch machine_id_prefix=%s existing_tid=%s caller_tid=%s",
            req.machine_id[:12],
            existing_tid,
            caller_tid,
        )
        set_sentry_tags(
                {
                    "registration_status": 403,
                    "registration_error_type": "tenant_mismatch",
                    "enroll_token_present": enroll_token_present,
                }
            )
        raise HTTPException(
            status_code=403,
            detail="tenant_mismatch: Machine already registered under a different tenant",
        )
    if not existing_tid and caller_tid is None:
        if db.count_tenants() > 1:
            logger.warning(
                "agent_register_denied reason_code=missing_enrollment_token machine_id_prefix=%s",
                req.machine_id[:12],
            )
            set_sentry_tags(
                {
                    "registration_status": 401,
                    "registration_error_type": "missing_enrollment_token",
                    "enroll_token_present": enroll_token_present,
                }
            )
            raise HTTPException(
                status_code=401,
                detail="missing_enrollment_token: Enrollment token required (X-CropPro-Enroll-Token header)",
            )
        set_tenant_context(1)

    active_tid = int(caller_tid or 1)
    tenant_lic = db.get_tenant_license_info(active_tid)
    if tenant_lic:
        if tenant_lic.get("is_past_grace"):
            logger.warning(
                "agent_register_denied reason_code=tenant_subscription_expired tenant_id=%s machine_id_prefix=%s",
                active_tid,
                req.machine_id[:12],
            )
            set_sentry_tags(
                {
                    "registration_status": 402,
                    "registration_error_type": "tenant_subscription_expired",
                    "enroll_token_present": enroll_token_present,
                }
            )
            raise HTTPException(
                status_code=402,
                detail="tenant_subscription_expired: Tenant subscription has expired. Please renew to enroll new agents.",
            )
        tenant_max = int(tenant_lic.get("max_seats") or 0)
        if tenant_max > 0 and not existing_tid:
            tenant_used = int(tenant_lic.get("seats_used") or 0)
            if tenant_used >= tenant_max:
                audit_log(
                    request,
                    None,
                    "agent_register_denied",
                    "machine",
                    req.machine_id,
                    {"reason": "tenant_seat_cap", "used": tenant_used, "max": tenant_max, "tenant_id": active_tid},
                )
                logger.warning(
                    "agent_register_denied reason_code=tenant_seat_cap tenant_id=%s machine_id_prefix=%s used=%s max=%s",
                    active_tid,
                    req.machine_id[:12],
                    tenant_used,
                    tenant_max,
                )
                set_sentry_tags(
                    {
                        "registration_status": 402,
                        "registration_error_type": "tenant_seat_cap",
                        "enroll_token_present": enroll_token_present,
                    }
                )
                raise HTTPException(
                    status_code=402,
                    detail=(
                        f"tenant_seat_cap: Tenant seat limit reached ({tenant_used}/{tenant_max}). "
                        "Contact your administrator to add more seats."
                    ),
                )

    enforcer: SeatEnforcer = request.app.state.seat_enforcer
    decision = enforcer.check_registration(req.machine_id)
    if not decision.allowed:
        audit_log(
            request,
            None,
            "agent_register_denied",
            "machine",
            req.machine_id,
            {
                "hostname": req.hostname,
                "reason": decision.reason,
                "active_seats": decision.active_seats,
                "max_seats": decision.max_seats,
            },
        )
        logger.warning(
            "agent_register_denied reason_code=global_seat_cap machine_id_prefix=%s hostname=%s detail=%s",
            req.machine_id[:12],
            req.hostname,
            decision.reason,
        )
        set_sentry_tags(
            {
                "registration_status": 402,
                "registration_error_type": "global_seat_cap",
                "enroll_token_present": enroll_token_present,
            }
        )
        raise HTTPException(status_code=402, detail=decision.reason)

    db.upsert_machine(
        {
            "machine_id": req.machine_id,
            "hostname": req.hostname,
            "os": req.os,
            "os_version": req.os_version,
            "username": req.username,
            "ip_address": req.ip_address,
            "mac_address": req.mac_address,
            "consent_given": req.consent_given,
            "consent_timestamp": req.consent_timestamp,
            "first_seen": req.first_seen,
            "last_seen": utcnow_iso(),
            "agent_version": req.agent_version,
        }
    )
    if decision.is_new_machine:
        enforcer.invalidate()
    set_sentry_tags(
        {
            "registration_status": 200,
            "registration_error_type": "none",
            "enroll_token_present": enroll_token_present,
        }
    )
    return {"status": "registered", "machine_id": req.machine_id}


@router.post("/api/activity/browser")
async def receive_browser_activity(req: BrowserActivityRequest, _a=Depends(require_agent_api_key)):
    try:
        result = activity_ingest_service.ingest_browser(req.machine_id, req.model_dump())
    except ActivityValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=f"{exc.code}: {exc.message}") from exc
    for event in result.broadcasts:
        await manager.broadcast(event)
    return result.response


@router.post("/api/activity/application")
async def receive_app_activity(req: AppActivityRequest, _a=Depends(require_agent_api_key)):
    try:
        result = activity_ingest_service.ingest_application(req.machine_id, req.model_dump())
    except ActivityValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=f"{exc.code}: {exc.message}") from exc
    for event in result.broadcasts:
        await manager.broadcast(event)
    return result.response


@router.post("/api/activity/screenshot")
async def receive_screenshot(req: ScreenshotRequest, _a=Depends(require_agent_api_key)):
    try:
        result = activity_ingest_service.ingest_screenshot(req.machine_id, req.model_dump())
    except ActivityValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=f"{exc.code}: {exc.message}") from exc
    for event in result.broadcasts:
        await manager.broadcast(event)
    return result.response


@router.post("/api/activity/heartbeat")
async def heartbeat(req: HeartbeatRequest, request: Request, _a=Depends(require_agent_api_key)):
    client_ip = request.client.host if request.client else ""
    try:
        result = activity_ingest_service.ingest_heartbeat(
            req.machine_id,
            req.model_dump(),
            client_geo=await geo_lookup(client_ip),
            config=_agent_public_config(),
        )
    except ActivityValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=f"{exc.code}: {exc.message}") from exc
    for event in result.broadcasts:
        await manager.broadcast(event)
    return result.response


@router.post("/api/activity/input")
async def receive_input_activity(req: InputActivityRequest, _a=Depends(require_agent_api_key)):
    try:
        result = activity_ingest_service.ingest_input(req.machine_id, req.model_dump())
    except ActivityValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=f"{exc.code}: {exc.message}") from exc
    for event in result.broadcasts:
        await manager.broadcast(event)
    return result.response


@router.post("/api/activity/phishing")
async def receive_phishing_activity(req: PhishingEventRequest, request: Request, _a=Depends(require_agent_api_key)):
    tenant_id = int(getattr(request.state, "tenant_id", None) or db.get_machine_tenant_id(req.machine_id) or 1)
    result = phishing_service.ingest_event(tenant_id, req.model_dump())
    incident = result.get("incident") or {}
    await manager.broadcast({"type": "phishing_update", "tenant_id": tenant_id, "machine_id": req.machine_id, "data": {**result["event"], "id": result["event_id"]}})
    if incident:
        await manager.broadcast({"type": "phishing_incident_update", "tenant_id": tenant_id, "machine_id": req.machine_id, "data": incident})
        if incident.get("_new_alert"):
            machine = db.get_machine(req.machine_id) or {}
            set_tenant_context(tenant_id)
            alert_id = db.create_alert_log(
                {
                    "rule_id": 0,
                    "rule_name": "Phishing Auto-Alert",
                    "machine_id": req.machine_id,
                    "hostname": machine.get("hostname", req.machine_id),
                    "severity": incident.get("severity", "warning"),
                    "message": incident.get("title", "Phishing incident"),
                    "details": incident.get("summary", ""),
                }
            )
            await manager.broadcast(
                {
                    "type": "new_alert",
                    "tenant_id": tenant_id,
                    "id": alert_id,
                    "severity": incident.get("severity", "warning"),
                    "machine_id": req.machine_id,
                    "message": incident.get("title", "Phishing incident"),
                }
            )
    return {"status": "ok", "event_id": result["event_id"], "incident_id": incident.get("id")}


@router.post("/api/activity/batch")
async def receive_activity_batch(request: Request, _a=Depends(require_agent_api_key)):
    try:
        body = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"detail": "Invalid JSON body"})
    machine_id = body.get("machine_id", "")
    events = body.get("events", [])
    if not machine_id or not events:
        return {"status": "ok", "processed": 0, "success_ids": [], "failed_ids": []}

    success_ids = []
    failed_ids = []

    for event in events:
        etype = event.get("event_type", "")
        data = event.get("data", {})
        event_id = event.get("queue_id")
        data["machine_id"] = machine_id
        try:
            if etype == "browser":
                result = activity_ingest_service.ingest_browser(machine_id, data)
                for broadcast in result.broadcasts:
                    await manager.broadcast(broadcast)
            elif etype == "app":
                result = activity_ingest_service.ingest_application(machine_id, data)
                for broadcast in result.broadcasts:
                    await manager.broadcast(broadcast)
            elif etype == "screenshot":
                result = activity_ingest_service.ingest_screenshot(machine_id, data)
                for broadcast in result.broadcasts:
                    await manager.broadcast(broadcast)
            elif etype == "heartbeat":
                result = activity_ingest_service.ingest_heartbeat(
                    machine_id,
                    data,
                    config=_agent_public_config(),
                )
                for broadcast in result.broadcasts:
                    await manager.broadcast(broadcast)
            elif etype == "input":
                result = activity_ingest_service.ingest_input(machine_id, data)
                for broadcast in result.broadcasts:
                    await manager.broadcast(broadcast)
            elif etype == "file":
                result = activity_ingest_service.ingest_file(machine_id, data)
                for broadcast in result.broadcasts:
                    await manager.broadcast(broadcast)
            elif etype == "network":
                result = activity_ingest_service.ingest_network(machine_id, data)
                for broadcast in result.broadcasts:
                    await manager.broadcast(broadcast)
            elif etype == "dlp_alert":
                tenant_id = int(getattr(request.state, "tenant_id", None) or db.get_machine_tenant_id(machine_id) or 1)
                result = dlp_service.ingest_dlp_event(tenant_id, data)
                event_db_id = result["event_id"]
                incident = result.get("incident") or {}
                event = result["event"]
                if result.get("new_alert"):
                    sev = "critical" if event.get("risk_level") in ("high", "critical") else "warning"
                    machine = db.get_machine(machine_id) or {}
                    alert_id = db.create_alert_log(
                        {
                            "rule_id": event.get("policy_rule_id") or 0,
                            "rule_name": event.get("policy_rule_name", "DLP Incident"),
                            "machine_id": machine_id,
                            "hostname": machine.get("hostname", machine_id),
                            "severity": sev,
                            "message": incident.get("title", f"DLP {event.get('risk_level', 'medium').upper()}"),
                            "details": incident.get("summary", event.get("file_path", "")),
                        }
                    )
                await manager.broadcast(
                    {
                        "type": "new_alert",
                        "tenant_id": tenant_id,
                        "id": alert_id,
                        "severity": sev,
                        "machine_id": machine_id,
                        "message": incident.get("title", f"DLP {event.get('risk_level', 'medium').upper()}"),
                    }
                    )
                await manager.broadcast({"type": "dlp_update", "machine_id": machine_id, "data": {**event, "id": event_db_id}})
                if incident:
                    await manager.broadcast({"type": "dlp_incident_update", "machine_id": machine_id, "data": incident})
            elif etype == "phishing_alert":
                tenant_id = int(getattr(request.state, "tenant_id", None) or db.get_machine_tenant_id(machine_id) or 1)
                result = phishing_service.ingest_event(tenant_id, data)
                incident = result.get("incident") or {}
                await manager.broadcast({"type": "phishing_update", "tenant_id": tenant_id, "machine_id": machine_id, "data": {**result["event"], "id": result["event_id"]}})
                if incident:
                    await manager.broadcast({"type": "phishing_incident_update", "tenant_id": tenant_id, "machine_id": machine_id, "data": incident})
                    if incident.get("_new_alert"):
                        machine = db.get_machine(machine_id) or {}
                        set_tenant_context(tenant_id)
                        alert_id = db.create_alert_log(
                            {
                                "rule_id": 0,
                                "rule_name": "Phishing Auto-Alert",
                                "machine_id": machine_id,
                                "hostname": machine.get("hostname", machine_id),
                                "severity": incident.get("severity", "warning"),
                                "message": incident.get("title", "Phishing incident"),
                                "details": incident.get("summary", ""),
                            }
                        )
                        await manager.broadcast(
                            {
                                "type": "new_alert",
                                "tenant_id": tenant_id,
                                "id": alert_id,
                                "severity": incident.get("severity", "warning"),
                                "machine_id": machine_id,
                                "message": incident.get("title", "Phishing incident"),
                            }
                        )
            else:
                logger.debug("Batch: unknown event_type '%s', skipping", etype)
                if event_id is not None:
                    failed_ids.append(event_id)
                continue
            if event_id is not None:
                success_ids.append(event_id)
        except Exception as exc:
            logger.error("Batch event error (%s): %s", etype, exc)
            if event_id is not None:
                failed_ids.append(event_id)

    return {"status": "ok", "processed": len(success_ids), "success_ids": success_ids, "failed_ids": failed_ids}
