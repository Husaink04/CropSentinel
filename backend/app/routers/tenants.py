"""Tenant management routes."""

from pathlib import Path
import os
import io
import json
import re
import zipfile

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse, RedirectResponse

from app.core import audit_log, require_platform_admin
from database import db

router = APIRouter()
VALID_TIERS = ("starter", "professional", "enterprise", "msp")


def _installer_version_key(path: Path) -> tuple[int, int, int]:
    match = re.search(r"cropsentinel-agent-(\d+)\.(\d+)\.(\d+)", path.name)
    if not match:
        return (0, 0, 0)
    return tuple(int(part) for part in match.groups())


def _latest_installer(dist_dir: Path, patterns: list[str]) -> Path | None:
    matches: list[Path] = []
    if not dist_dir.exists():
        return None
    for pattern in patterns:
        matches.extend(dist_dir.glob(pattern))
    if not matches:
        return None
    unique_matches = {path.resolve(): path for path in matches}
    return sorted(
        unique_matches.values(),
        key=lambda p: (_installer_version_key(p), p.stat().st_mtime, p.name.lower()),
        reverse=True,
    )[0]


def _installer_dist_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "dist" / "installers"


def _agent_download_config(platform: str) -> tuple[list[str], str | None, str]:
    normalized = (platform or "windows").strip().lower()
    if normalized == "linux":
        return (
            [
                "cropsentinel-agent-*-linux.tar.gz",
                "cropsentinel-agent-linux-*.tar.gz",
                "cropsentinel-agent-*-linux.zip",
                "cropsentinel-agent-linux-*.zip",
            ],
            os.environ.get("CROPSENTINEL_LINUX_AGENT_URL") or os.environ.get("CROPPRO_LINUX_AGENT_URL"),
            "linux",
        )
    return (
        ["cropsentinel-agent-*.exe"],
        os.environ.get("CROPSENTINEL_WINDOWS_AGENT_URL") or os.environ.get("CROPPRO_WINDOWS_AGENT_URL"),
        "windows",
    )


@router.get("/api/agent-installers/{platform}/latest")
async def download_generic_agent_installer(platform: str):
    patterns, external_url, normalized = _agent_download_config(platform)
    if external_url:
        return RedirectResponse(external_url)

    installer_path = _latest_installer(_installer_dist_dir(), patterns)
    if not installer_path:
        raise HTTPException(
            status_code=503,
            detail=(
                f"No generic {normalized} agent installer is configured. "
                f"Set CROPSENTINEL_{normalized.upper()}_AGENT_URL to a fixed download URL, "
                "or place the generic installer file in backend/dist/installers/."
            ),
        )

    media_type = "application/octet-stream"
    if installer_path.suffix.lower() == ".exe":
        media_type = "application/vnd.microsoft.portable-executable"
    elif installer_path.suffix.lower() == ".zip":
        media_type = "application/zip"
    elif installer_path.name.endswith(".tar.gz"):
        media_type = "application/gzip"

    return FileResponse(
        installer_path,
        media_type=media_type,
        filename=installer_path.name,
    )


@router.get("/api/tenants")
async def list_tenants(request: Request, user=Depends(require_platform_admin)):
    tenants = db.get_all_tenants_with_stats()
    for tenant in tenants:
        if tenant.get("created_at") is not None:
            tenant["created_at"] = str(tenant["created_at"])
    lic = getattr(request.app.state, "license", None)
    return {"tenants": tenants, "max_tenants": lic.max_tenants if lic else None}


@router.get("/api/tenants/{tenant_id}")
async def get_tenant_detail(tenant_id: int, user=Depends(require_platform_admin)):
    tenant = db.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    stats = db.get_tenant_stats(tenant_id)
    license_info = db.get_tenant_license_info(tenant_id)
    for key in ("created_at", "valid_until", "subscription_started", "updated_at"):
        if key in tenant and tenant[key] is not None and not isinstance(tenant[key], str):
            tenant[key] = str(tenant[key])
    return {**tenant, "stats": stats, "license": license_info}


@router.post("/api/tenants")
async def create_tenant(request: Request, user=Depends(require_platform_admin)):
    data = await request.json()
    slug = (data.get("slug") or "").strip().lower().replace(" ", "-")
    name = (data.get("name") or "").strip()
    customer_name = (data.get("customer_name") or "").strip()
    tier = (data.get("tier") or "starter").strip().lower()
    max_seats = int(data.get("max_seats") or 0)
    valid_days_raw = data.get("valid_days")
    valid_days = int(valid_days_raw) if valid_days_raw not in (None, "", 0) else None
    grace_days = int(data.get("grace_days") or 14)

    if not slug:
        raise HTTPException(status_code=400, detail="Slug is required")
    if not all(c.isalnum() or c in "-_" for c in slug):
        raise HTTPException(status_code=400, detail="Slug may only contain letters, numbers, hyphens, underscores")
    if tier not in VALID_TIERS:
        raise HTTPException(status_code=400, detail=f"Invalid tier. Must be one of: {', '.join(VALID_TIERS)}")
    if max_seats < 0:
        raise HTTPException(status_code=400, detail="max_seats must be >= 0 (0 = no cap)")
    if valid_days is not None and valid_days < 1:
        raise HTTPException(status_code=400, detail="valid_days must be >= 1 (or omit for perpetual)")
    if grace_days < 0:
        raise HTTPException(status_code=400, detail="grace_days must be >= 0")

    lic = getattr(request.app.state, "license", None)
    if lic:
        current = db.count_tenants()
        if current >= lic.max_tenants:
            raise HTTPException(
                status_code=403,
                detail=f"Platform license allows max {lic.max_tenants} tenants. Currently at {current}.",
            )

    if db.get_tenant_by_slug(slug):
        raise HTTPException(status_code=409, detail=f"Tenant with slug '{slug}' already exists")

    tenant_id = db.create_tenant(
        slug=slug,
        name=name or slug,
        customer_name=customer_name or (name or slug),
        tier=tier,
        max_seats=max_seats,
        valid_days=valid_days,
        grace_days=grace_days,
    )
    created = db.get_tenant(tenant_id)
    license_info = db.get_tenant_license_info(tenant_id)
    audit_log(
        request,
        user,
        "tenant_created",
        "tenant",
        str(tenant_id),
        {
            "slug": slug,
            "name": name,
            "customer_name": customer_name,
            "tier": tier,
            "max_seats": max_seats,
            "valid_days": valid_days,
            "grace_days": grace_days,
        },
    )
    return {
        "id": tenant_id,
        "slug": slug,
        "name": name or slug,
        "customer_name": customer_name or (name or slug),
        "status": "active",
        "tier": tier,
        "max_seats": max_seats,
        "grace_days": grace_days,
        "enrollment_token": created.get("enrollment_token") if created else None,
        "license": license_info,
    }


@router.post("/api/tenants/{tenant_id}/rotate-token")
async def rotate_tenant_token(tenant_id: int, request: Request, user=Depends(require_platform_admin)):
    tenant = db.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    new_token = db.rotate_enrollment_token(tenant_id)
    if not new_token:
        raise HTTPException(status_code=500, detail="Token rotation failed")
    audit_log(request, user, "tenant_token_rotated", "tenant", str(tenant_id), {"tenant_name": tenant.get("name")})
    return {"tenant_id": tenant_id, "enrollment_token": new_token}


@router.post("/api/tenants/{tenant_id}/download-agent")
async def download_agent_bundle(
    tenant_id: int,
    request: Request,
    platform: str = "windows",
    user=Depends(require_platform_admin),
):
    tenant = db.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    token = tenant.get("enrollment_token")
    if not token:
        token = db.rotate_enrollment_token(tenant_id)
    if not token:
        raise HTTPException(status_code=500, detail="Failed to obtain enrollment token for tenant")

    body = {}
    try:
        raw = await request.body()
        if raw:
            body = json.loads(raw)
            if not isinstance(body, dict):
                body = {}
    except Exception:
        body = {}
    server_url = (
        body.get("server_url")
        or os.environ.get("CROPSENTINEL_SERVER_URL")
        or os.environ.get("CROPSENTINEL_SERVER")
        or os.environ.get("CROPPRO_SERVER_URL")
        or os.environ.get("CROPPRO_SERVER")
        or str(request.base_url)
    ).rstrip("/")

    requested_platform = str(body.get("platform") or platform or "windows").strip().lower()
    dist_dir = _installer_dist_dir()
    if requested_platform == "linux":
        installer_path = _latest_installer(
            dist_dir,
            [
                "cropsentinel-agent-*-linux.tar.gz",
                "cropsentinel-agent-linux-*.tar.gz",
                "cropsentinel-agent-*-linux.zip",
                "cropsentinel-agent-linux-*.zip",
            ],
        )
        missing_detail = (
            "No prebuilt Linux installer is available on this server. "
            "Build one by running installer/build-linux-agent.sh on a Linux dev machine and "
            "copy the resulting cropsentinel-agent-*-linux.tar.gz or cropsentinel-agent-*-linux.zip into backend/dist/installers/."
        )
        output_filename = f"cropsentinel-agent-{tenant.get('slug') or f'tenant-{tenant_id}'}-linux.zip"
    else:
        requested_platform = "windows"
        installer_path = _latest_installer(dist_dir, ["cropsentinel-agent-*.exe"])
        missing_detail = (
            "No prebuilt Windows installer is available on this server. "
            "Build one by running installer/build.ps1 on a Windows dev machine and "
            "copy the resulting cropsentinel-agent-*.exe into backend/dist/installers/."
        )
        output_filename = f"cropsentinel-agent-{tenant.get('slug') or f'tenant-{tenant_id}'}-windows.zip"
    if not installer_path:
        raise HTTPException(status_code=503, detail=missing_detail)

    config_env = (
        f"# CropSentinel Agent configuration for {tenant.get('name')} ({tenant.get('slug')})\n"
        f"CROPSENTINEL_SERVER={server_url}\n"
        f"CROPSENTINEL_ENROLL_TOKEN={token}\n"
        f"CROPPRO_SERVER={server_url}\n"
        f"CROPPRO_ENROLL_TOKEN={token}\n"
    )
    if requested_platform == "linux":
        readme = (
            f"CropSentinel Linux Agent installation for {tenant.get('name')}\r\n"
            f"Server: {server_url}\r\n"
            f"Extract this ZIP, keep config.env next to install-linux-agent.sh, and run:\r\n"
            f"  sudo bash ./install-linux-agent.sh\r\n"
            f"Do not share this ZIP or config.env.\r\n"
        )
    else:
        readme = (
            f"CropSentinel Agent installation for {tenant.get('name')}\r\n"
            f"Server: {server_url}\r\n"
            f"Run the installer EXE and accept the consent screen.\r\n"
            f"Do not share this ZIP or config.env.\r\n"
        )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(installer_path, arcname=installer_path.name)
        zf.writestr("config.env", config_env)
        zf.writestr("README.txt", readme)
    bundle_bytes = buf.getvalue()
    artifact = db.create_generated_artifact(
        category="installer_bundles",
        evidence_classification="agent_bundle",
        content_type="application/zip",
        filename=output_filename,
        raw_bytes=bundle_bytes,
        tenant_id=tenant_id,
        metadata={
            "tenant_slug": tenant.get("slug", ""),
            "server_url": server_url,
            "installer": installer_path.name,
            "platform": requested_platform,
        },
    )

    audit_log(
        request,
        user,
        "agent_bundle_downloaded",
        "tenant",
        str(tenant_id),
        {
            "tenant_name": tenant.get("name"),
            "server_url": server_url,
            "installer": installer_path.name,
            "platform": requested_platform,
            "artifact_id": artifact["id"],
        },
    )
    return Response(
        content=bundle_bytes,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{output_filename}"',
            "Cache-Control": "no-store",
            "X-Artifact-ID": str(artifact["id"]),
        },
    )


@router.put("/api/tenants/{tenant_id}")
async def update_tenant(tenant_id: int, request: Request, user=Depends(require_platform_admin)):
    data = await request.json()
    name = data.get("name")
    status = data.get("status")
    customer_name = data.get("customer_name")
    tier = data.get("tier")
    max_seats = data.get("max_seats")
    grace_days = data.get("grace_days")
    extend_days = data.get("extend_days")
    valid_until = data.get("valid_until")

    if status and status not in ("active", "suspended"):
        raise HTTPException(status_code=400, detail="Status must be 'active' or 'suspended'")
    if tenant_id == 1 and status == "suspended":
        raise HTTPException(status_code=400, detail="Cannot suspend the default tenant")
    if tier is not None and tier not in VALID_TIERS:
        raise HTTPException(status_code=400, detail=f"Invalid tier. Must be one of: {', '.join(VALID_TIERS)}")
    if max_seats is not None and int(max_seats) < 0:
        raise HTTPException(status_code=400, detail="max_seats must be >= 0")
    if grace_days is not None and int(grace_days) < 0:
        raise HTTPException(status_code=400, detail="grace_days must be >= 0")
    if extend_days is not None and int(extend_days) < 0:
        raise HTTPException(status_code=400, detail="extend_days must be >= 0")

    updated = db.update_tenant(
        tenant_id,
        name=name,
        status=status,
        customer_name=customer_name,
        tier=tier,
        max_seats=int(max_seats) if max_seats is not None else None,
        grace_days=int(grace_days) if grace_days is not None else None,
        extend_days=int(extend_days) if extend_days is not None else None,
        valid_until=valid_until,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Tenant not found")
    audit_log(
        request,
        user,
        "tenant_updated",
        "tenant",
        str(tenant_id),
        {"name": name, "status": status, "tier": tier, "max_seats": max_seats, "extend_days": extend_days, "customer_name": customer_name},
    )
    for key in ("created_at", "valid_until", "subscription_started", "updated_at"):
        if key in updated and updated[key] is not None and not isinstance(updated[key], str):
            updated[key] = str(updated[key])
    updated["license"] = db.get_tenant_license_info(tenant_id)
    return updated


@router.delete("/api/tenants/{tenant_id}")
async def delete_tenant_endpoint(tenant_id: int, request: Request, user=Depends(require_platform_admin)):
    tenant = db.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")
    try:
        db.delete_tenant(tenant_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    audit_log(request, user, "tenant_deleted", "tenant", str(tenant_id), {"slug": tenant.get("slug"), "name": tenant.get("name")})
    return {"message": f"Tenant '{tenant.get('slug')}' and all its data deleted."}

