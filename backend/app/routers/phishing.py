"""Phishing protection policy, incidents, and diagnostics APIs."""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core import audit_log, check_machine_access, get_current_tenant, require_agent_api_key, require_permission, require_platform_admin
from app.services.phishing_service import phishing_service
from database import db
from models import (
    PhishingAllowlistRequest,
    PhishingBlocklistRequest,
    PhishingCheckRequest,
    PhishingIncidentUpdateRequest,
    PhishingPolicyRequest,
    PhishingReportRequest,
)

router = APIRouter()


@router.get("/api/phishing/policy/effective")
async def get_effective_phishing_policy(tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.view"))):
    return phishing_service.get_effective_policy(int(tenant["id"]))


@router.get("/api/phishing/policies")
async def list_phishing_policies(tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.view"))):
    return {"policies": phishing_service.list_policies(int(tenant["id"]))}


@router.post("/api/phishing/policies")
async def create_phishing_policy(request: Request, req: PhishingPolicyRequest, tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.edit"))):
    policy_id = db.create_phishing_policy(req.model_dump(), tenant_id=int(tenant["id"]))
    audit_log(request, user, "phishing_policy_created", "phishing_policy", str(policy_id), {"name": req.name})
    return {"id": policy_id}


@router.put("/api/phishing/policy")
async def update_default_phishing_policy(request: Request, req: PhishingPolicyRequest, tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.edit"))):
    policies = phishing_service.list_policies(int(tenant["id"]))
    policy = next((item for item in policies if item.get("scope") == "tenant_override"), None)
    if not policy:
        raise HTTPException(status_code=404, detail="Tenant phishing policy not found")
    db.update_phishing_policy(int(policy["id"]), req.model_dump(exclude_none=True), tenant_id=int(tenant["id"]))
    audit_log(request, user, "phishing_policy_updated", "phishing_policy", str(policy["id"]), {"name": req.name})
    return phishing_service.get_effective_policy(int(tenant["id"]))


@router.post("/api/phishing/policies/{policy_id}/publish")
async def publish_phishing_policy(request: Request, policy_id: int, tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.edit"))):
    try:
        effective = phishing_service.publish_policy(int(tenant["id"]), policy_id, user.get("sub", ""))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit_log(request, user, "phishing_policy_published", "phishing_policy", str(policy_id), {"policy_version": effective["policy_version"]})
    return effective


@router.get("/api/phishing/events")
async def list_phishing_events(limit: int = 50, offset: int = 0, tenant=Depends(get_current_tenant), user=Depends(require_permission("activity.view"))):
    return {
        "events": db.list_phishing_events(tenant_id=int(tenant["id"]), limit=max(1, min(limit, 200)), offset=max(0, offset)),
        "total": db.count_phishing_events(tenant_id=int(tenant["id"])),
    }


@router.get("/api/phishing/incidents")
async def list_phishing_incidents(state: str = "", severity: str = "", assignee: str = "", limit: int = 50, offset: int = 0, tenant=Depends(get_current_tenant), user=Depends(require_permission("activity.view"))):
    payload = phishing_service.list_incidents(int(tenant["id"]), state=state, severity=severity, assignee=assignee, limit=limit, offset=offset)
    payload["stats"] = phishing_service.incident_stats(int(tenant["id"]))
    return payload


@router.get("/api/phishing/incidents/{incident_id}")
async def get_phishing_incident(incident_id: int, tenant=Depends(get_current_tenant), user=Depends(require_permission("activity.view"))):
    item = phishing_service.get_incident_detail(int(tenant["id"]), incident_id)
    if not item:
        raise HTTPException(status_code=404, detail="Incident not found")
    return item


@router.put("/api/phishing/incidents/{incident_id}")
async def update_phishing_incident(request: Request, incident_id: int, req: PhishingIncidentUpdateRequest, tenant=Depends(get_current_tenant), user=Depends(require_permission("alerts.manage"))):
    incident = db.get_phishing_incident(incident_id, tenant_id=int(tenant["id"]))
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    payload = req.model_dump(exclude_none=True)
    note = payload.pop("note", None)
    db.update_phishing_incident(incident_id, payload, tenant_id=int(tenant["id"]))
    db.add_phishing_incident_timeline(incident_id, "incident_updated", user.get("sub", ""), payload, tenant_id=int(tenant["id"]))
    if note:
        db.add_phishing_incident_note(incident_id, note, user.get("sub", ""), tenant_id=int(tenant["id"]))
    audit_log(request, user, "phishing_incident_updated", "phishing_incident", str(incident_id), payload)
    return phishing_service.get_incident_detail(int(tenant["id"]), incident_id)


@router.get("/api/phishing/allowlists")
async def list_phishing_allowlists(tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.view"))):
    return {"items": db.list_phishing_allowlist_exceptions(tenant_id=int(tenant["id"]))}


@router.post("/api/phishing/allowlists")
async def create_phishing_allowlist(request: Request, req: PhishingAllowlistRequest, tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.edit"))):
    allowlist_id = phishing_service.create_allowlist_exception(
        int(tenant["id"]),
        {**req.model_dump(), "created_by": user.get("sub", "")},
    )
    audit_log(request, user, "phishing_allowlist_created", "phishing_allowlist", str(allowlist_id), req.model_dump())
    return {"id": allowlist_id}


@router.get("/api/phishing/whitelists")
async def list_phishing_whitelists(tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.view"))):
    return {"items": db.list_phishing_allowlist_exceptions(tenant_id=int(tenant["id"]))}


@router.post("/api/phishing/whitelists")
async def create_phishing_whitelist(request: Request, req: PhishingAllowlistRequest, tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.edit"))):
    allowlist_id = phishing_service.create_allowlist_exception(
        int(tenant["id"]),
        {**req.model_dump(), "created_by": user.get("sub", "")},
    )
    audit_log(request, user, "phishing_whitelist_created", "phishing_whitelist", str(allowlist_id), req.model_dump())
    return {"id": allowlist_id}


@router.delete("/api/phishing/allowlists/{allowlist_id}")
async def delete_phishing_allowlist(request: Request, allowlist_id: int, tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.edit"))):
    ok = db.delete_phishing_allowlist_exception(allowlist_id, tenant_id=int(tenant["id"]))
    if not ok:
        raise HTTPException(status_code=404, detail="Allowlist not found")
    audit_log(request, user, "phishing_allowlist_deleted", "phishing_allowlist", str(allowlist_id), {})
    return {"status": "ok"}


@router.delete("/api/phishing/whitelists/{allowlist_id}")
async def delete_phishing_whitelist(request: Request, allowlist_id: int, tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.edit"))):
    ok = db.delete_phishing_allowlist_exception(allowlist_id, tenant_id=int(tenant["id"]))
    if not ok:
        raise HTTPException(status_code=404, detail="Whitelist not found")
    audit_log(request, user, "phishing_whitelist_deleted", "phishing_whitelist", str(allowlist_id), {})
    return {"status": "ok"}


@router.get("/api/phishing/blacklists")
async def list_phishing_blacklists(tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.view"))):
    return {"items": db.list_phishing_blocklist_exceptions(tenant_id=int(tenant["id"]))}


@router.post("/api/phishing/blacklists")
async def create_phishing_blacklist(request: Request, req: PhishingBlocklistRequest, tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.edit"))):
    blocklist_id = phishing_service.create_blocklist_exception(
        int(tenant["id"]),
        {**req.model_dump(), "created_by": user.get("sub", "")},
    )
    audit_log(request, user, "phishing_blacklist_created", "phishing_blacklist", str(blocklist_id), req.model_dump())
    return {"id": blocklist_id}


@router.delete("/api/phishing/blacklists/{blocklist_id}")
async def delete_phishing_blacklist(request: Request, blocklist_id: int, tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.edit"))):
    ok = db.delete_phishing_blocklist_exception(blocklist_id, tenant_id=int(tenant["id"]))
    if not ok:
        raise HTTPException(status_code=404, detail="Blacklist not found")
    audit_log(request, user, "phishing_blacklist_deleted", "phishing_blacklist", str(blocklist_id), {})
    return {"status": "ok"}


@router.get("/api/phishing/diagnostics/machines/{machine_id}")
async def get_phishing_diagnostics(machine_id: str, tenant=Depends(get_current_tenant), user=Depends(require_permission("activity.view"))):
    check_machine_access(user, machine_id)
    return phishing_service.get_machine_diagnostics(int(tenant["id"]), machine_id)


@router.get("/api/platform/phishing/baseline")
async def get_platform_phishing_baseline(user=Depends(require_platform_admin)):
    return phishing_service.platform_baseline()


@router.put("/api/platform/phishing/policy")
async def update_platform_phishing_policy(request: Request, req: PhishingPolicyRequest, user=Depends(require_platform_admin)):
    policies = phishing_service.platform_baseline().get("policies", [])
    policy = next((item for item in policies if item.get("scope") == "platform_baseline"), None)
    if not policy:
        raise HTTPException(status_code=404, detail="Platform phishing baseline not found")
    db.update_phishing_policy(int(policy["id"]), req.model_dump(exclude_none=True), tenant_id=1)
    audit_log(request, user, "platform_phishing_policy_updated", "phishing_policy", str(policy["id"]), {"name": req.name})
    return phishing_service.get_effective_policy(1)


@router.post("/api/phishing/check")
async def check_phishing_url(req: PhishingCheckRequest, request: Request, _a=Depends(require_agent_api_key)):
    tenant_id = int(getattr(request.state, "tenant_id", None) or db.get_machine_tenant_id(req.machine_id) or 1)
    return phishing_service.check_url(tenant_id, req.model_dump())


@router.post("/api/phishing/report")
async def report_phishing_feedback(req: PhishingReportRequest, request: Request, _a=Depends(require_agent_api_key)):
    tenant_id = int(getattr(request.state, "tenant_id", None) or db.get_machine_tenant_id(req.machine_id) or 1)
    return phishing_service.report_feedback(tenant_id, req.model_dump())
