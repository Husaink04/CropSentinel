"""Enterprise DLP governance and incident APIs."""

from fastapi import APIRouter, Depends, HTTPException, Request

from app.core import audit_log, check_machine_access, get_current_tenant, require_agent_api_key, require_permission, require_platform_admin
from app.services.dlp_file_inventory_service import dlp_file_inventory_service
from app.services.dlp_service import dlp_service
from app.ws_service import manager
from database import db
from models import (
    DlpClassifierRequest,
    DlpExceptionRequest,
    DlpIncidentUpdateRequest,
    DlpPolicyRequest,
    DlpRuleRequest,
    DlpSimulationRequest,
)

router = APIRouter()


@router.get("/api/dlp/policy/effective")
async def get_effective_dlp_policy(tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.view"))):
    return dlp_service.get_effective_policy(int(tenant["id"]))


@router.get("/api/dlp/policies")
async def list_dlp_policies(tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.view"))):
    return {"policies": dlp_service.list_policies_with_rules(int(tenant["id"]))}


@router.post("/api/dlp/policies")
async def create_dlp_policy(request: Request, req: DlpPolicyRequest, tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.edit"))):
    policy_id = db.create_dlp_policy(req.model_dump(), tenant_id=int(tenant["id"]))
    audit_log(request, user, "dlp_policy_created", "dlp_policy", str(policy_id), {"name": req.name})
    return {"id": policy_id}


@router.put("/api/dlp/policies/{policy_id}")
async def update_dlp_policy(request: Request, policy_id: int, req: DlpPolicyRequest, tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.edit"))):
    policy = db.get_dlp_policy(policy_id, tenant_id=int(tenant["id"]))
    if not policy:
        raise HTTPException(status_code=404, detail="Policy not found")
    db.update_dlp_policy(policy_id, req.model_dump(exclude_none=True), tenant_id=int(tenant["id"]))
    audit_log(request, user, "dlp_policy_updated", "dlp_policy", str(policy_id), {"name": req.name})
    return {"status": "ok"}


@router.post("/api/dlp/policies/{policy_id}/publish")
async def publish_dlp_policy(request: Request, policy_id: int, tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.edit"))):
    try:
        effective = dlp_service.publish_policy(int(tenant["id"]), policy_id, user.get("sub", ""))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    audit_log(request, user, "dlp_policy_published", "dlp_policy", str(policy_id), {"policy_version": effective["policy_version"]})
    return effective


@router.get("/api/dlp/rules")
async def list_dlp_rules(policy_id: int = 0, tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.view"))):
    return {"rules": db.list_dlp_rules(policy_id or None, tenant_id=int(tenant["id"]))}


@router.post("/api/dlp/rules")
async def create_dlp_rule(request: Request, req: DlpRuleRequest, tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.edit"))):
    rule_id = db.create_dlp_rule(req.model_dump(), tenant_id=int(tenant["id"]))
    audit_log(request, user, "dlp_rule_created", "dlp_rule", str(rule_id), {"name": req.name})
    return {"id": rule_id}


@router.put("/api/dlp/rules/{rule_id}")
async def update_dlp_rule(request: Request, rule_id: int, req: DlpRuleRequest, tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.edit"))):
    ok = db.update_dlp_rule(rule_id, req.model_dump(exclude_none=True), tenant_id=int(tenant["id"]))
    if not ok:
        raise HTTPException(status_code=404, detail="Rule not found")
    audit_log(request, user, "dlp_rule_updated", "dlp_rule", str(rule_id), {"name": req.name})
    return {"status": "ok"}


@router.get("/api/dlp/classifiers")
async def list_dlp_classifiers(tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.view"))):
    dlp_service.ensure_seeded(int(tenant["id"]))
    return {"classifiers": db.list_dlp_classifiers(tenant_id=int(tenant["id"]))}


@router.post("/api/dlp/classifiers")
async def create_dlp_classifier(request: Request, req: DlpClassifierRequest, tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.edit"))):
    classifier_id = db.create_dlp_classifier(req.model_dump(), tenant_id=int(tenant["id"]))
    audit_log(request, user, "dlp_classifier_created", "dlp_classifier", str(classifier_id), {"name": req.name})
    return {"id": classifier_id}


@router.get("/api/dlp/exceptions")
async def list_dlp_exceptions(status: str = "", tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.view"))):
    return {"exceptions": db.list_dlp_exceptions(tenant_id=int(tenant["id"]), status=status)}


@router.post("/api/dlp/exceptions")
async def create_dlp_exception(request: Request, req: DlpExceptionRequest, tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.edit"))):
    exception_id = db.create_dlp_exception({**req.model_dump(), "created_by": user.get("sub", "")}, tenant_id=int(tenant["id"]))
    audit_log(request, user, "dlp_exception_created", "dlp_exception", str(exception_id), {"scope_type": req.scope_type})
    return {"id": exception_id}


@router.put("/api/dlp/exceptions/{exception_id}")
async def update_dlp_exception(request: Request, exception_id: int, req: DlpExceptionRequest, tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.edit"))):
    ok = db.update_dlp_exception(exception_id, req.model_dump(exclude_none=True), tenant_id=int(tenant["id"]))
    if not ok:
        raise HTTPException(status_code=404, detail="Exception not found")
    audit_log(request, user, "dlp_exception_updated", "dlp_exception", str(exception_id), {"scope_type": req.scope_type})
    return {"status": "ok"}


@router.post("/api/dlp/policies/simulate")
async def simulate_dlp_policy(req: DlpSimulationRequest, tenant=Depends(get_current_tenant), user=Depends(require_permission("settings.view"))):
    return dlp_service.simulate_policy(int(tenant["id"]), req.model_dump())


@router.get("/api/dlp/incidents")
async def list_dlp_incidents(
    state: str = "",
    severity: str = "",
    assignee: str = "",
    actor_username: str = "",
    machine_id: str = "",
    file_hash: str = "",
    content_fingerprint: str = "",
    destination_type: str = "",
    disposition: str = "",
    date_from: str = "",
    date_to: str = "",
    limit: int = 50,
    offset: int = 0,
    tenant=Depends(get_current_tenant),
    user=Depends(require_permission("activity.view")),
):
    payload = dlp_service.list_incidents(
        int(tenant["id"]),
        state=state,
        severity=severity,
        assignee=assignee,
        limit=limit,
        offset=offset,
        actor_username=actor_username,
        machine_id=machine_id,
        file_hash=file_hash,
        content_fingerprint=content_fingerprint,
        destination_type=destination_type,
        disposition=disposition,
        date_from=date_from,
        date_to=date_to,
    )
    payload["stats"] = dlp_service.incident_stats(int(tenant["id"]))
    return payload


@router.get("/api/dlp/incidents/{incident_id}")
async def get_dlp_incident(incident_id: int, tenant=Depends(get_current_tenant), user=Depends(require_permission("activity.view"))):
    item = dlp_service.get_incident_detail(int(tenant["id"]), incident_id)
    if not item:
        raise HTTPException(status_code=404, detail="Incident not found")
    return item


@router.get("/api/dlp/risk/users")
async def list_dlp_user_risk(
    date_from: str = "",
    date_to: str = "",
    window_days: int = 90,
    min_risk_level: str = "",
    trend: str = "",
    machine_id: str = "",
    destination_type: str = "",
    disposition: str = "",
    exclude_disposition: str = "",
    limit: int = 50,
    offset: int = 0,
    tenant=Depends(get_current_tenant),
    user=Depends(require_permission("activity.view")),
):
    return dlp_service.list_user_risk(
        int(tenant["id"]),
        date_from=date_from,
        date_to=date_to,
        window_days=window_days,
        min_risk_level=min_risk_level,
        trend=trend,
        machine_id=machine_id,
        destination_type=destination_type,
        disposition=disposition,
        exclude_disposition=exclude_disposition,
        limit=limit,
        offset=offset,
    )


@router.get("/api/dlp/risk/users/{actor_username}")
async def get_dlp_user_risk_detail(
    actor_username: str,
    date_from: str = "",
    date_to: str = "",
    window_days: int = 90,
    machine_id: str = "",
    destination_type: str = "",
    disposition: str = "",
    exclude_disposition: str = "",
    tenant=Depends(get_current_tenant),
    user=Depends(require_permission("activity.view")),
):
    detail = dlp_service.get_user_risk_detail(
        int(tenant["id"]),
        actor_username,
        date_from=date_from,
        date_to=date_to,
        window_days=window_days,
        machine_id=machine_id,
        destination_type=destination_type,
        disposition=disposition,
        exclude_disposition=exclude_disposition,
    )
    if not detail:
        raise HTTPException(status_code=404, detail="User risk profile not found")
    return detail


@router.put("/api/dlp/incidents/{incident_id}")
async def update_dlp_incident(request: Request, incident_id: int, req: DlpIncidentUpdateRequest, tenant=Depends(get_current_tenant), user=Depends(require_permission("alerts.manage"))):
    incident = db.get_dlp_incident(incident_id, tenant_id=int(tenant["id"]))
    if not incident:
        raise HTTPException(status_code=404, detail="Incident not found")
    payload = req.model_dump(exclude_none=True)
    detail = dlp_service.update_incident_review(int(tenant["id"]), incident_id, payload, user.get("sub", ""))
    audit_log(request, user, "dlp_incident_updated", "dlp_incident", str(incident_id), payload)
    if detail:
        await manager.broadcast({"type": "dlp_incident_update", "tenant_id": int(tenant["id"]), "machine_id": detail.get("machine_id", ""), "data": detail})
    return detail


@router.get("/api/dlp/diagnostics/machines/{machine_id}")
async def get_dlp_diagnostics(machine_id: str, tenant=Depends(get_current_tenant), user=Depends(require_permission("activity.view"))):
    check_machine_access(user, machine_id)
    diag = db.get_latest_dlp_diagnostics_for_machine(machine_id, tenant_id=int(tenant["id"]))
    policy = dlp_service.get_effective_policy(int(tenant["id"]))
    return {
        "machine_id": machine_id,
        "effective_policy_version": policy["policy_version"],
        "effective_policy_hash": policy["policy_hash"],
        "effective_rollout_mode": policy["rollout_mode"],
        "latest_event": diag,
        "unsupported_capabilities": [
            "quarantine",
            "manager_approval",
            "require_justification",
        ],
    }


@router.get("/api/platform/dlp/baseline")
async def get_platform_dlp_baseline(user=Depends(require_platform_admin)):
    return dlp_service.list_platform_baseline()


@router.post("/api/dlp/file-inventory/batch")
async def ingest_dlp_file_inventory_batch(request: Request, _a=Depends(require_agent_api_key)):
    body = await request.json()
    machine_id = str(body.get("machine_id", "") or "")
    if not machine_id:
        raise HTTPException(status_code=400, detail="machine_id_required")
    tenant_id = int(getattr(request.state, "tenant_id", None) or db.get_machine_tenant_id(machine_id) or 1)
    return dlp_file_inventory_service.ingest_batch(tenant_id, machine_id, body)


@router.get("/api/dlp/file-inventory/status/{machine_id}")
async def get_dlp_file_inventory_status(machine_id: str, tenant=Depends(get_current_tenant), user=Depends(require_permission("activity.view"))):
    check_machine_access(user, machine_id)
    return dlp_file_inventory_service.get_status(int(tenant["id"]), machine_id)


@router.post("/api/platform/dlp/classifiers")
async def create_platform_dlp_classifier(request: Request, req: DlpClassifierRequest, user=Depends(require_platform_admin)):
    classifier_id = db.create_dlp_classifier(req.model_dump(), tenant_id=1)
    audit_log(request, user, "platform_dlp_classifier_created", "dlp_classifier", str(classifier_id), {"name": req.name})
    return {"id": classifier_id}


@router.put("/api/platform/dlp/policy")
async def update_platform_dlp_policy(request: Request, req: DlpPolicyRequest, user=Depends(require_platform_admin)):
    policies = dlp_service.list_platform_baseline().get("policies", [])
    policy = next((item for item in policies if item.get("scope") == "platform_baseline"), None)
    if not policy:
        raise HTTPException(status_code=404, detail="Platform baseline not found")
    db.update_dlp_policy(int(policy["id"]), req.model_dump(exclude_none=True), tenant_id=1)
    audit_log(request, user, "platform_dlp_policy_updated", "dlp_policy", str(policy["id"]), {"name": req.name})
    return dlp_service.get_effective_policy(1)
