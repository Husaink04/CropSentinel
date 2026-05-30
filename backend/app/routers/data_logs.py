"""File, network, and DLP log routes."""

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core import audit_log, require_agent_api_key, require_permission
from app.services.activity_ingest_service import ActivityValidationError, activity_ingest_service
from app.services.dlp_service import dlp_service
from app.ws_service import manager
from database import db
from models import DLPEventRequest, FileActivityRequest, NetworkActivityRequest

router = APIRouter()
logger = logging.getLogger("croppro")


@router.post("/api/activity/file")
async def receive_file_activity(req: FileActivityRequest, _a=Depends(require_agent_api_key)):
    try:
        result = activity_ingest_service.ingest_file(req.machine_id, req.model_dump() if hasattr(req, "model_dump") else req.dict())
    except ActivityValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=f"{exc.code}: {exc.message}") from exc
    for event in result.broadcasts:
        await manager.broadcast(event)
    return result.response


@router.get("/api/files")
async def get_file_logs(
    machine_id: str = "",
    action: str = "",
    search: str = "",
    date: str = "",
    limit: int = 100,
    offset: int = 0,
    user=Depends(require_permission("activity.view")),
):
    items = db.get_file_activity(machine_id, action, search, date, limit, offset)
    total = db.count_file_activity(machine_id, action, search, date)
    return {"files": items, "total": total}


@router.get("/api/files/stats")
async def get_file_stats(machine_id: str = "", user=Depends(require_permission("activity.view"))):
    return db.get_file_activity_stats(machine_id)


@router.get("/api/files/vault")
async def get_deleted_vault(
    machine_id: str = "",
    search: str = "",
    limit: int = 50,
    offset: int = 0,
    user=Depends(require_permission("settings.view")),
):
    items = db.get_deleted_backups(machine_id, search, limit, offset)
    total = db.count_deleted_backups(machine_id, search)
    return {"backups": items, "total": total}


@router.get("/api/files/vault/{backup_id}")
async def download_vault_file(backup_id: int, user=Depends(require_permission("settings.view"))):
    backup = db.get_deleted_backup_file(backup_id)
    if not backup:
        raise HTTPException(404, "Backup not found")
    return backup


@router.delete("/api/files/vault/{backup_id}")
async def delete_vault_file(request: Request, backup_id: int, user=Depends(require_permission("settings.edit"))):
    ok = db.delete_backup(backup_id)
    if not ok:
        raise HTTPException(404, "Backup not found")
    audit_log(request, user, "vault_file_deleted", "deleted_backup", str(backup_id))
    return {"status": "ok"}


@router.post("/api/activity/network")
async def receive_network_activity(req: NetworkActivityRequest, _a=Depends(require_agent_api_key)):
    try:
        result = activity_ingest_service.ingest_network(req.machine_id, req.model_dump() if hasattr(req, "model_dump") else req.dict())
    except ActivityValidationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=f"{exc.code}: {exc.message}") from exc
    for event in result.broadcasts:
        await manager.broadcast(event)
    return result.response


@router.get("/api/network")
async def get_network_logs(
    machine_id: str = "",
    search: str = "",
    date: str = "",
    limit: int = 50,
    offset: int = 0,
    user=Depends(require_permission("activity.view")),
):
    items = db.get_network_activity(machine_id, search, date, limit, offset)
    total = db.count_network_activity(machine_id, search, date)
    return {"logs": items, "total": total}


@router.get("/api/network/stats")
async def get_network_stats(machine_id: str = "", user=Depends(require_permission("activity.view"))):
    return db.get_network_stats(machine_id)


@router.post("/api/dlp/events")
async def receive_dlp_event(req: DLPEventRequest, request: Request, _a=Depends(require_agent_api_key)):
    tenant_id = int(getattr(request.state, "tenant_id", None) or db.get_machine_tenant_id(req.machine_id) or 1)
    result = dlp_service.ingest_dlp_event(tenant_id, req.model_dump())
    event_id = result["event_id"]
    event = result["event"]
    incident = result.get("incident") or {}
    if result.get("new_alert"):
        severity = "critical" if event.get("risk_level") in ("high", "critical") else "warning"
        machine = db.get_machine(req.machine_id) or {}
        alert = db.create_alert_log(
            {
                "rule_id": event.get("policy_rule_id") or 0,
                "rule_name": event.get("policy_rule_name", "DLP Incident"),
                "machine_id": req.machine_id,
                "hostname": machine.get("hostname", req.machine_id),
                "severity": severity,
                "message": incident.get("title", f"DLP {event.get('risk_level', 'medium').upper()}"),
                "details": incident.get("summary", event.get("file_path", "")),
            }
        )
        await manager.broadcast(
            {
                "type": "new_alert",
                "tenant_id": tenant_id,
                "id": alert,
                "severity": severity,
                "machine_id": req.machine_id,
                "message": incident.get("title", f"DLP {event.get('risk_level', 'medium').upper()}"),
            }
        )
    await manager.broadcast({"type": "dlp_update", "machine_id": req.machine_id, "data": {**event, "id": event_id}})
    if incident:
        await manager.broadcast({"type": "dlp_incident_update", "machine_id": req.machine_id, "data": incident})
    return {"status": "ok", "id": event_id, "incident_id": incident.get("id")}


@router.get("/api/dlp/events")
async def get_dlp_events(
    machine_id: str = "",
    risk_level: str = "",
    destination: str = "",
    destination_type: str = "",
    search: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
    offset: int = 0,
    user=Depends(require_permission("activity.view")),
):
    items = db.get_dlp_events(
        machine_id=machine_id,
        risk_level=risk_level,
        destination=destination,
        destination_type=destination_type,
        date_from=date_from,
        date_to=date_to,
        search=search,
        limit=limit,
        offset=offset,
    )
    total = db.count_dlp_events(
        machine_id=machine_id,
        risk_level=risk_level,
        destination=destination,
        destination_type=destination_type,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )
    return {"events": items, "total": total}


@router.get("/api/dlp/stats")
async def get_dlp_stats(machine_id: str = "", user=Depends(require_permission("activity.view"))):
    return db.get_dlp_stats(machine_id)


@router.put("/api/dlp/events/{event_id}/acknowledge")
async def acknowledge_dlp(event_id: int, user=Depends(require_permission("alerts.manage"))):
    ok = db.acknowledge_dlp_event(event_id)
    return {"status": "ok" if ok else "not_found"}


@router.get("/api/dlp/policy")
async def get_dlp_policy(user=Depends(require_permission("settings.view"))):
    effective = dlp_service.get_effective_policy(int(user.get("tenant_id") or 1))
    return {
        "dlp_enabled": effective.get("dlp_enabled", True),
        "dlp_keywords": effective.get("keywords", []),
        "dlp_custom_patterns": effective.get("custom_patterns", {}),
        "dlp_risk_thresholds": effective.get("risk_thresholds", {"low": 1, "medium": 3, "high": 7}),
        "policy_version": effective.get("policy_version", 1),
        "policy_hash": effective.get("policy_hash", ""),
    }


@router.put("/api/dlp/policy")
async def update_dlp_policy(request: Request, user=Depends(require_permission("settings.edit"))):
    data = await request.json()
    updates = {}
    if "dlp_enabled" in data:
        updates["dlp_enabled"] = bool(data["dlp_enabled"])
    if "dlp_keywords" in data:
        updates["dlp_keywords"] = list(data["dlp_keywords"])
    if "dlp_custom_patterns" in data:
        updates["dlp_custom_patterns"] = dict(data["dlp_custom_patterns"])
    if "dlp_risk_thresholds" in data:
        updates["dlp_risk_thresholds"] = dict(data["dlp_risk_thresholds"])
    if updates:
        db.update_settings(updates)
        effective = dlp_service.get_effective_policy(int(user.get("tenant_id") or 1))
        tenant_policy = next((p for p in db.list_dlp_policies(int(user.get("tenant_id") or 1), scope="tenant_override")), None)
        if tenant_policy:
            db.update_dlp_policy(
                tenant_policy["id"],
                {"config": {"legacy_settings_sync": True}, "status": "published"},
                tenant_id=int(user.get("tenant_id") or 1),
            )
        audit_log(request, user, "dlp_legacy_policy_updated", "settings", "", {"keys": list(updates.keys()), "policy_version": effective.get("policy_version", 1)})
    return {"status": "ok", "updated": list(updates.keys())}
