"""Settings, alerts, audit logs, and remote command routes."""

import csv
import io
import json
import os

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.core import audit_log, get_current_user, require_feature, require_permission
from app.services.productivity_service import productivity_service
from app.services.session_service import require_session_access, sanitize_remote_command
from app.ws_service import manager
from database import db, utcnow
from models import AlertRuleRequest, SettingsUpdateRequest
from passwords import hash_password

router = APIRouter()


@router.get("/api/settings")
async def get_settings(user=Depends(require_permission("settings.view"))):
    settings = db.get_settings()
    settings.update(productivity_service.get_policy_settings())
    settings.pop("admin_password_hash", None)
    settings.pop("agent_stop_password_hash", None)
    return settings


@router.put("/api/settings")
async def update_settings(request: Request, req: SettingsUpdateRequest, user=Depends(require_permission("settings.edit"))):
    data = req.model_dump(exclude_none=True)
    data = productivity_service.build_settings_patch(data)
    changed_keys = list(data.keys())
    if "agent_stop_password" in data:
        data["agent_stop_password_hash"] = hash_password(data.pop("agent_stop_password"))
        changed_keys = [k if k != "agent_stop_password" else "agent_stop_password_hash" for k in changed_keys]
    db.update_settings(data)
    audit_log(request, user, "settings_updated", "settings", "", {"keys": changed_keys})
    return {"message": "Settings updated"}


@router.get("/api/settings/ice-servers")
async def get_ice_servers(user=Depends(get_current_user)):
    settings = db.get_settings()
    explicit = settings.get("ice_servers")
    if isinstance(explicit, list) and explicit:
        return {"ice_servers": explicit}

    servers = [{"urls": ["stun:stun.l.google.com:19302", "stun:stun1.l.google.com:19302"]}]
    turn_url = (settings.get("webrtc_turn_url") or os.environ.get("WEBRTC_TURN_URL", "")).strip()
    turn_user = (settings.get("webrtc_turn_username") or os.environ.get("WEBRTC_TURN_USER", "")).strip()
    turn_pass = settings.get("webrtc_turn_password") or os.environ.get("WEBRTC_TURN_PASS", "")
    if turn_url:
        entry = {"urls": [turn_url]}
        if turn_user:
            entry["username"] = turn_user
        if turn_pass:
            entry["credential"] = turn_pass
        servers.append(entry)
    return {"ice_servers": servers}


@router.get("/api/alerts/rules")
async def get_alert_rules(user=Depends(require_permission("alerts.view"))):
    return db.get_alert_rules()


@router.post("/api/alerts/rules")
async def create_alert_rule(
    request: Request,
    req: AlertRuleRequest,
    user=Depends(require_permission("alerts.manage")),
    _f=Depends(require_feature("alerts")),
):
    rule_id = db.create_alert_rule(req.model_dump())
    audit_log(request, user, "alert_rule_created", "alert_rule", str(rule_id), {"name": req.name, "rule_type": req.rule_type})
    return {"id": rule_id, "message": "Alert rule created"}


@router.put("/api/alerts/rules/{rule_id}")
async def update_alert_rule(
    request: Request,
    rule_id: int,
    req: AlertRuleRequest,
    user=Depends(require_permission("alerts.manage")),
    _f=Depends(require_feature("alerts")),
):
    if not db.get_alert_rule(rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")
    db.update_alert_rule(rule_id, req.model_dump(exclude_none=True))
    audit_log(request, user, "alert_rule_updated", "alert_rule", str(rule_id), {"name": req.name})
    return {"message": "Rule updated"}


@router.patch("/api/alerts/rules/{rule_id}/toggle")
async def toggle_alert_rule(request: Request, rule_id: int, enabled: bool, user=Depends(require_permission("alerts.manage"))):
    db.toggle_alert_rule(rule_id, enabled)
    audit_log(request, user, "alert_rule_toggled", "alert_rule", str(rule_id), {"enabled": enabled})
    return {"message": "Rule toggled"}


@router.delete("/api/alerts/rules/{rule_id}")
async def delete_alert_rule(
    request: Request,
    rule_id: int,
    user=Depends(require_permission("alerts.manage")),
    _f=Depends(require_feature("alerts")),
):
    rule = db.get_alert_rule(rule_id)
    db.delete_alert_rule(rule_id)
    audit_log(request, user, "alert_rule_deleted", "alert_rule", str(rule_id), {"name": (rule or {}).get("name", "")})
    return {"message": "Rule deleted"}


class RemoteCommandRequest(BaseModel):
    machine_id: str
    action: str
    value: str = ""


@router.post("/api/remote/command")
async def send_remote_command(
    request: Request,
    req: RemoteCommandRequest,
    user=Depends(require_permission("remote.access")),
    _f=Depends(require_feature("remote_access")),
):
    require_session_access(user, req.machine_id, "remote")
    action, value = sanitize_remote_command(req.action, req.value)
    payload = {"type": "remote_command", "action": action, "value": value}
    sent = await manager.send_to_agent(req.machine_id, payload)
    if not sent:
        raise HTTPException(status_code=503, detail="Machine is offline or not connected")
    audit_log(request, user, "remote_command", "machine", req.machine_id, {"action": action})
    return {"message": f"Command '{action}' sent to {req.machine_id}"}


@router.get("/api/alerts/logs")
async def get_alert_logs(
    machine_id: str = "",
    severity: str = "",
    unread_only: bool = False,
    limit: int = 100,
    user=Depends(require_permission("alerts.view")),
):
    ack = False if unread_only else None
    return db.get_alert_logs(machine_id, severity, ack, limit)


@router.get("/api/alerts/stats")
async def get_alert_stats(user=Depends(require_permission("alerts.view"))):
    return db.get_alert_stats()


@router.post("/api/alerts/logs/{log_id}/acknowledge")
async def acknowledge_alert(log_id: int, user=Depends(require_permission("alerts.manage"))):
    db.acknowledge_alert(log_id, user.get("sub", "admin"))
    return {"message": "Alert acknowledged"}


@router.post("/api/alerts/logs/acknowledge-all")
async def acknowledge_all_alerts(user=Depends(require_permission("alerts.manage"))):
    count = db.acknowledge_all_alerts(user.get("sub", "admin"))
    return {"message": f"{count} alerts acknowledged"}


@router.delete("/api/alerts/logs/{log_id}")
async def delete_alert_log(log_id: int, user=Depends(require_permission("alerts.manage"))):
    deleted = db.delete_alert_log(log_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Alert log not found")
    return {"message": "Alert deleted"}


@router.delete("/api/alerts/logs/acknowledged/purge")
async def purge_acknowledged_alerts(user=Depends(require_permission("alerts.manage"))):
    count = db.delete_acknowledged_alerts()
    return {"message": f"{count} acknowledged alerts purged"}


@router.get("/api/audit-logs")
async def get_audit_logs(
    username: str = "",
    action: str = "",
    resource_type: str = "",
    start_date: str = "",
    end_date: str = "",
    search: str = "",
    limit: int = 50,
    offset: int = 0,
    user=Depends(require_permission("settings.view")),
):
    filters = {}
    if username:
        filters["username"] = username
    if action:
        filters["action"] = action
    if resource_type:
        filters["resource_type"] = resource_type
    if start_date:
        filters["start_date"] = start_date
    if end_date:
        filters["end_date"] = end_date
    if search:
        filters["search"] = search
    logs = db.get_audit_logs(filters, limit, offset)
    total = db.count_audit_logs(filters)
    return {"logs": logs, "total": total, "limit": limit, "offset": offset}


@router.get("/api/audit-logs/stats")
async def get_audit_stats(user=Depends(require_permission("settings.view"))):
    return db.get_audit_stats()


@router.get("/api/audit-logs/actions")
async def get_audit_actions(user=Depends(require_permission("settings.view"))):
    return db.get_audit_actions()


# Audit-log export is gated behind the "audit_export" license feature.
# Supports `format=csv` (default) or `format=json`. All filter params
# are optional and combine with AND semantics server-side.
@router.get("/api/audit-logs/export")
async def export_audit_logs(
    format: str = "csv",
    username: str = "",
    action: str = "",
    resource_type: str = "",
    start_date: str = "",
    end_date: str = "",
    search: str = "",
    user=Depends(require_permission("settings.view")),
    _f=Depends(require_feature("audit_export")),
):
    filters = {}
    if username:      filters["username"]      = username
    if action:        filters["action"]        = action
    if resource_type: filters["resource_type"] = resource_type
    if start_date:    filters["start_date"]    = start_date
    if end_date:      filters["end_date"]      = end_date
    if search:        filters["search"]        = search

    rows = db.get_audit_logs(filters, limit=100_000, offset=0)
    stamp = utcnow().strftime("%Y%m%d_%H%M%S")

    if format.lower().strip() == "json":
        filename = f"audit_logs_{stamp}.json"
        payload = json.dumps(rows, default=str, indent=2).encode("utf-8")
        artifact = db.create_generated_artifact(
            category="exports",
            evidence_classification="audit_export",
            content_type="application/json",
            filename=filename,
            raw_bytes=payload,
            metadata={"format": "json", "exported_by": user.get("sub", ""), "filters": filters},
        )
        return Response(
            content=payload,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-Artifact-ID": str(artifact["id"]),
            },
        )

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["Timestamp", "Username", "Role", "Action", "Resource Type", "Resource ID", "IP Address", "Metadata"])
    for log in rows:
        writer.writerow([
            str(log.get("timestamp", "")),
            log.get("username", ""),
            log.get("role", ""),
            log.get("action", ""),
            log.get("resource_type", ""),
            log.get("resource_id", ""),
            log.get("ip_address", ""),
            log.get("metadata", "{}"),
        ])
    filename = f"audit_logs_{stamp}.csv"
    payload = buf.getvalue().encode("utf-8")
    artifact = db.create_generated_artifact(
        category="exports",
        evidence_classification="audit_export",
        content_type="text/csv",
        filename=filename,
        raw_bytes=payload,
        metadata={"format": "csv", "exported_by": user.get("sub", ""), "filters": filters},
    )
    return Response(
        content=payload,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
            "X-Artifact-ID": str(artifact["id"]),
        },
    )
