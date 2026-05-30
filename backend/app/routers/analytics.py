"""Analytics, screenshots, reports, and license routes."""

from pathlib import Path
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, Response

from app.analytics_pipeline import analytics_pipeline
from app.db.core import get_tenant_id as _tid
from app.core import (
    audit_log,
    check_machine_access as _check_machine_access,
    require_feature,
    require_permission,
)
from app.event_bus import EventTopics, internal_event_bus
from app.services.productivity_service import productivity_service
from database import db, utcnow
from licensing import ACTIVE_WINDOW_MINUTES, LicenseError, SeatEnforcer, load_and_verify_license
from pdf_generator import generate_report

router = APIRouter()
logger = logging.getLogger("croppro")


def _load_productivity_lists() -> tuple:
    settings = db.get_settings()
    return (
        [app.lower() for app in settings.get("productive_apps", [])],
        settings.get("productive_domains", []),
        settings.get("unproductive_domains", []),
    )


def _classify_domain(domain: str, prod_domains: list, unprod_domains: list) -> str:
    value = (domain or "").lower()
    if any(pd.lower() in value for pd in prod_domains):
        return "productive"
    if any(ud.lower() in value for ud in unprod_domains):
        return "unproductive"
    return "neutral"


def _classify_app(app_name: str, prod_apps: list) -> str:
    value = (app_name or "").lower()
    if any(app in value for app in prod_apps):
        return "productive"
    return "neutral"


def _report_filename(hostname: str) -> str:
    safe_hostname = (hostname or "machine").replace(" ", "_")
    return f"CropSentinel_{safe_hostname}_{utcnow().strftime('%Y%m%d')}.pdf"


def _serialize_report_job(job: dict) -> dict:
    payload = dict(job)
    payload["download_url"] = (
        f"/api/reports/jobs/{payload['id']}/download"
        if payload.get("status") == "completed" and (payload.get("storage_key") or payload.get("output_path"))
        else None
    )
    return payload


def _analytics_overview_source() -> dict:
    tenant_id = _tid()
    if analytics_pipeline.read_enabled() and tenant_id:
        try:
            return analytics_pipeline.get_overview_stats(int(tenant_id))
        except Exception as exc:
            logger.warning("ClickHouse overview fallback to postgres: %s", exc)
    return db.get_overview_stats()


def _machine_analytics_source(machine_id: str, start_date: Optional[str], end_date: Optional[str]) -> dict:
    tenant_id = _tid()
    if analytics_pipeline.read_enabled() and tenant_id:
        try:
            return analytics_pipeline.get_machine_analytics(int(tenant_id), machine_id, start_date, end_date)
        except Exception as exc:
            logger.warning("ClickHouse machine analytics fallback to postgres: %s", exc)
    return db.get_machine_analytics(machine_id, start_date, end_date)


@router.get("/api/analytics/overview")
async def get_overview(user=Depends(require_permission("analytics.view"))):
    data = _analytics_overview_source()
    prod_apps, prod_domains, unprod_domains = _load_productivity_lists()
    for app in data.get("top_apps", []):
        app["category"] = _classify_app(app.get("app_name", ""), prod_apps)
    for domain in data.get("top_domains", []):
        domain["category"] = _classify_domain(domain.get("domain", ""), prod_domains, unprod_domains)

    app_prod = sum(a.get("total", 0) for a in data.get("top_apps", []) if a.get("category") == "productive")
    app_neut = sum(a.get("total", 0) for a in data.get("top_apps", []) if a.get("category") == "neutral")
    dom_prod = sum(d.get("visits", 0) for d in data.get("top_domains", []) if d.get("category") == "productive")
    dom_unprod = sum(d.get("visits", 0) for d in data.get("top_domains", []) if d.get("category") == "unproductive")
    dom_neut = sum(d.get("visits", 0) for d in data.get("top_domains", []) if d.get("category") == "neutral")

    data["app_productivity"] = {"productive": app_prod, "neutral": app_neut}
    data["domain_productivity"] = {"productive": dom_prod, "unproductive": dom_unprod, "neutral": dom_neut}
    return data


@router.get("/api/analytics/machine/{machine_id}")
async def get_machine_analytics(
    machine_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user=Depends(require_permission("analytics.view")),
):
    _check_machine_access(user, machine_id)
    return _machine_analytics_source(machine_id, start_date, end_date)


@router.get("/api/analytics/browser/{machine_id}")
async def get_browser_history(
    machine_id: str,
    limit: int = 100,
    search: str = "",
    date: str = "",
    user=Depends(require_permission("activity.view")),
):
    rows = db.get_browser_history(machine_id, limit, search, date)
    _, prod_domains, unprod_domains = _load_productivity_lists()
    for row in rows:
        row["category"] = _classify_domain(row.get("domain", ""), prod_domains, unprod_domains)
    return rows


@router.get("/api/analytics/applications/{machine_id}")
async def get_app_usage(machine_id: str, date: Optional[str] = None, user=Depends(require_permission("activity.view"))):
    rows = db.get_app_usage(machine_id, date)
    prod_apps, _, _ = _load_productivity_lists()
    for row in rows:
        row["category"] = _classify_app(row.get("app_name", ""), prod_apps)
    return rows


@router.get("/api/analytics/productivity/{machine_id}")
async def get_productivity(
    machine_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user=Depends(require_permission("productivity.view")),
):
    _check_machine_access(user, machine_id)
    if start_date or end_date:
        return productivity_service.get_machine_productivity_alias(machine_id, start_date or "", end_date or "")
    return db.get_productivity_score(machine_id)


@router.get("/api/productivity/machines/{machine_id}")
async def get_productivity_machine_detail(
    machine_id: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user=Depends(require_permission("productivity.view")),
):
    _check_machine_access(user, machine_id)
    payload = productivity_service.get_machine_productivity(machine_id, start_date or "", end_date or "")
    if not payload:
        raise HTTPException(status_code=404, detail="Machine not found")
    return payload


@router.get("/api/productivity/machines")
async def list_productivity_machines(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    sort_by: str = "score",
    limit: int = 100,
    user=Depends(require_permission("productivity.view")),
):
    return productivity_service.list_productivity_machines(start_date or "", end_date or "", sort_by=sort_by, limit=limit)


@router.get("/api/productivity/overview")
async def get_productivity_overview(
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    user=Depends(require_permission("productivity.view")),
):
    return productivity_service.get_productivity_overview(start_date or "", end_date or "")


@router.get("/api/analytics/productivity-logs")
async def get_productivity_logs(
    machine_id: str = "",
    date: str = "",
    limit: int = 200,
    user=Depends(require_permission("productivity.view")),
):
    return db.get_productivity_logs(machine_id, date, limit)


@router.get("/api/analytics/input/{machine_id}")
async def get_input_activity_history(
    machine_id: str,
    limit: int = 100,
    date: str = "",
    search: str = "",
    user=Depends(require_permission("activity.view")),
):
    _check_machine_access(user, machine_id)
    return db.get_input_activity(machine_id, limit, date, search)


@router.get("/api/screenshots/{machine_id}")
async def get_screenshots(machine_id: str, limit: int = 20, user=Depends(require_permission("screenshots.view"))):
    _check_machine_access(user, machine_id)
    return db.get_screenshots(machine_id, limit)


@router.get("/api/screenshots/latest/{machine_id}")
async def get_latest_screenshot(machine_id: str, user=Depends(require_permission("screenshots.view"))):
    _check_machine_access(user, machine_id)
    return db.get_latest_screenshot(machine_id)


@router.get("/api/reports/generate/{machine_id}")
async def generate_pdf_report(
    request: Request,
    machine_id: str,
    user=Depends(require_permission("reports.generate")),
    _f=Depends(require_feature("reports")),
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    async_mode: bool = Query(False, alias="async"),
):
    _check_machine_access(user, machine_id)
    machine = db.get_machine(machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    if async_mode:
        job = db.create_report_job(
            {
                "machine_id": machine_id,
                "requested_by": user.get("sub", ""),
                "start_date": start_date,
                "end_date": end_date,
                "filename": _report_filename(machine.get("hostname", machine_id)),
                "metadata": {"hostname": machine.get("hostname", machine_id)},
            }
        )
        internal_event_bus.publish(
            topic=EventTopics.SYSTEM_EVENTS,
            event_type="report.generate.requested",
            tenant_id=int(user.get("tenant_id") or 1),
            machine_id=machine_id,
            payload={
                "job_id": job["id"],
                "tenant_id": int(user.get("tenant_id") or 1),
                "machine_id": machine_id,
                "start_date": start_date,
                "end_date": end_date,
                "requested_by": user.get("sub", ""),
                "report_type": "machine_pdf",
            },
        )
        audit_log(
            request,
            user,
            "report_job_requested",
            "report_job",
            job["id"],
            {"machine_id": machine_id, "start_date": start_date or "", "end_date": end_date or ""},
        )
        return _serialize_report_job(job)
    analytics = db.get_machine_analytics(machine_id, start_date, end_date)
    browser = db.get_browser_history(machine_id, 50)
    apps = db.get_app_usage(machine_id)
    settings = db.get_settings()
    pdf_path = generate_report(machine, analytics, browser, apps, settings, start_date, end_date)
    return FileResponse(
        pdf_path,
        media_type="application/pdf",
        filename=_report_filename(machine["hostname"]),
    )


@router.get("/api/reports/jobs/{job_id}")
async def get_report_job(
    job_id: str,
    user=Depends(require_permission("reports.generate")),
    _f=Depends(require_feature("reports")),
):
    job = db.get_report_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Report job not found")
    _check_machine_access(user, job["machine_id"])
    return _serialize_report_job(job)


@router.get("/api/reports/jobs/{job_id}/download")
async def download_report_job(
    job_id: str,
    user=Depends(require_permission("reports.generate")),
    _f=Depends(require_feature("reports")),
):
    job = db.get_report_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Report job not found")
    _check_machine_access(user, job["machine_id"])
    if job.get("status") != "completed":
        raise HTTPException(status_code=409, detail="Report is not ready yet")
    machine = db.get_machine(job["machine_id"]) or {}
    if job.get("evidence_id"):
        try:
            payload = db.load_evidence_object_bytes(int(job["evidence_id"]))
        except FileNotFoundError:
            raise HTTPException(status_code=404, detail="Generated report artifact is missing")
        return Response(
            content=payload,
            media_type=job.get("content_type") or "application/pdf",
            headers={"Content-Disposition": f'attachment; filename="{job.get("filename") or _report_filename(machine.get("hostname", job["machine_id"]))}"'},
        )
    output_path = Path(job.get("output_path") or "")
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Generated report file is missing")
    return FileResponse(
        str(output_path),
        media_type=job.get("content_type") or "application/pdf",
        filename=job.get("filename") or _report_filename(machine.get("hostname", job["machine_id"])),
    )


@router.get("/api/license/info")
async def get_license_info(request: Request, user=Depends(require_permission("settings.view"))):
    lic = getattr(request.app.state, "license", None)
    bootstrap_mode = getattr(request.app.state, "license_bootstrap", False)
    license_error = getattr(request.app.state, "license_error", "")
    enforcer: Optional[SeatEnforcer] = getattr(request.app.state, "seat_enforcer", None)
    active_seats = 0
    total_seats = 0
    tenant_count = 1
    try:
        if enforcer is not None:
            active_seats = enforcer.active_count()
        total_seats = db.count_total_machines()
        tenant_count = db.count_tenants()
    except Exception as exc:
        logger.warning("License info: failed to compute seat counts: %s", exc)

    if lic is None:
        reason = "No valid license loaded. Running in unlicensed dev mode."
        if bootstrap_mode:
            reason = license_error or "No valid platform license loaded."
        return {
            "licensed": False,
            "bootstrap_mode": bootstrap_mode,
            "reason": reason,
            "usage": {
                "active_seats": active_seats,
                "total_machines": total_seats,
                "max_seats": None,
                "active_tenants": tenant_count,
                "max_tenants": None,
                "active_window_minutes": ACTIVE_WINDOW_MINUTES,
            },
        }

    max_seats = lic.max_seats
    pct_used = round((active_seats / max_seats) * 100, 1) if max_seats else 0.0
    return {
        "licensed": True,
        **lic.to_public_dict(),
        "usage": {
            "active_seats": active_seats,
            "total_machines": total_seats,
            "max_seats": max_seats,
            "seats_remaining": max(0, max_seats - active_seats),
            "percent_used": pct_used,
            "over_limit": active_seats >= max_seats,
            "active_tenants": tenant_count,
            "max_tenants": lic.max_tenants,
            "tenants_remaining": max(0, lic.max_tenants - tenant_count),
            "active_window_minutes": ACTIVE_WINDOW_MINUTES,
        },
    }


@router.post("/api/license/upload")
async def upload_license(
    request: Request,
    file: UploadFile = File(...),
    user=Depends(require_permission("settings.edit")),
):
    raw = await file.read()
    if not raw or len(raw) > 64 * 1024:
        raise HTTPException(status_code=400, detail="License file is empty or too large.")

    target_path = Path(os.environ.get("CROPPRO_LICENSE_PATH", "license.key"))
    os.makedirs(target_path.parent, exist_ok=True)
    tmp_path = Path(f"{target_path}.upload.tmp")
    try:
        try:
            with open(tmp_path, "wb") as handle:
                handle.write(raw)
        except OSError as exc:
            logger.exception("License upload failed while writing temp file")
            raise HTTPException(
                status_code=500,
                detail=f"Could not write uploaded license file to {tmp_path}: {exc}",
            )
        try:
            new_license = load_and_verify_license(license_path=tmp_path)
        except LicenseError as exc:
            audit_log(request, user, "license_upload_rejected", "license", "", {"reason": str(exc)})
            raise HTTPException(status_code=400, detail=f"Invalid license: {exc}")

        try:
            existing_tenants = db.count_tenants()
        except Exception:
            existing_tenants = 1
        if existing_tenants > new_license.max_tenants:
            audit_log(
                request,
                user,
                "license_upload_rejected",
                "license",
                "",
                {
                    "reason": "tenant_count_exceeds_license",
                    "existing": existing_tenants,
                    "max_tenants": new_license.max_tenants,
                },
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    f"This license allows only {new_license.max_tenants} tenant(s), "
                    f"but {existing_tenants} are already active. Delete extra tenants first "
                    "or contact HAAK IT Solutions for an MSP license."
                ),
            )
        try:
            os.replace(tmp_path, target_path)
        except OSError as exc:
            logger.exception("License upload failed while replacing active license")
            raise HTTPException(
                status_code=500,
                detail=f"Could not activate uploaded license at {target_path}: {exc}",
            )
    finally:
        if tmp_path.exists():
            try:
                os.remove(tmp_path)
            except OSError:
                pass

    request.app.state.license = new_license
    request.app.state.license_bootstrap = False
    request.app.state.license_error = ""
    enforcer = getattr(request.app.state, "seat_enforcer", None)
    if enforcer is not None:
        enforcer.invalidate()

    audit_log(
        request,
        user,
        "license_uploaded",
        "license",
        new_license.license_id,
        {
            "customer": new_license.customer,
            "tier": new_license.tier,
            "max_seats": new_license.max_seats,
            "expires_at": new_license.expires_at.isoformat(),
        },
    )
    return {"message": "License installed successfully.", "license": new_license.to_public_dict()}
