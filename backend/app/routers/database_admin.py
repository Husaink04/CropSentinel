"""Database operations and long-term storage visibility routes."""

from fastapi import APIRouter, Depends, Query, Request

from app.core import audit_log, require_permission
from database import db

router = APIRouter()


@router.get("/api/admin/database/overview")
async def get_database_overview(user=Depends(require_permission("settings.view"))):
    return db.get_database_overview()


@router.get("/api/admin/database/retention")
async def get_database_retention(user=Depends(require_permission("settings.view"))):
    return {
        "retention": db.get_retention_settings(),
        "storage": db.get_storage_settings(),
    }


@router.get("/api/admin/database/partitions")
async def get_database_partitions(user=Depends(require_permission("settings.view"))):
    return {"partitions": db.get_partition_health()}


@router.post("/api/admin/database/retention/run")
async def run_database_retention(
    request: Request,
    dry_run: bool = Query(True),
    user=Depends(require_permission("settings.edit")),
):
    result = db.run_retention_cleanup(dry_run=dry_run)
    audit_log(
        request,
        user,
        "database_retention_run",
        "database",
        "",
        {"dry_run": dry_run, "deleted": result.get("deleted", {})},
    )
    return result
