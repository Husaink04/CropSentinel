"""Shared activity read routes for investigation pages."""

from typing import Optional

from fastapi import APIRouter, Depends

from app.core import check_machine_access as _check_machine_access, require_permission
from app.services.activity_service import activity_service

router = APIRouter()


@router.get("/api/activity/browser-logs")
async def get_browser_logs(
    machine_id: str = "",
    search: str = "",
    date: str = "",
    limit: int = 200,
    offset: int = 0,
    user=Depends(require_permission("activity.view")),
):
    if machine_id:
        _check_machine_access(user, machine_id)
    return activity_service.list_browser_logs(
        machine_id,
        search=search,
        date=date,
        limit=max(1, min(limit, 500)),
        offset=max(0, offset),
    )


@router.get("/api/activity/app-usage")
async def get_app_usage_logs(
    machine_id: str = "",
    search: str = "",
    date: Optional[str] = None,
    category: str = "",
    limit: int = 100,
    offset: int = 0,
    user=Depends(require_permission("activity.view")),
):
    if machine_id:
        _check_machine_access(user, machine_id)
    return activity_service.list_app_usage(
        machine_id,
        search=search,
        date=date,
        category=category,
        limit=max(1, min(limit, 500)),
        offset=max(0, offset),
    )


@router.get("/api/activity/network-logs")
async def get_network_logs(
    machine_id: str = "",
    search: str = "",
    date: str = "",
    limit: int = 50,
    offset: int = 0,
    user=Depends(require_permission("activity.view")),
):
    if machine_id:
        _check_machine_access(user, machine_id)
    return activity_service.list_network_logs(
        machine_id,
        search=search,
        date=date,
        limit=max(1, min(limit, 500)),
        offset=max(0, offset),
    )


@router.get("/api/activity/file-logs")
async def get_file_logs(
    machine_id: str = "",
    action: str = "",
    search: str = "",
    date: str = "",
    limit: int = 100,
    offset: int = 0,
    user=Depends(require_permission("activity.view")),
):
    if machine_id:
        _check_machine_access(user, machine_id)
    return activity_service.list_file_logs(
        machine_id,
        action=action,
        search=search,
        date=date,
        limit=max(1, min(limit, 500)),
        offset=max(0, offset),
    )
