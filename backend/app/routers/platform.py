"""Platform admin router."""

from typing import Optional

from fastapi import APIRouter, Depends, Request

from app.core import require_platform_admin
from app.repos.tenant_repo import tenant_repo
from app.services.user_service import create_platform_user, delete_platform_user, list_platform_users
from database import clear_tenant_context, set_tenant_context
from models import CreateUserRequest

router = APIRouter()


@router.get("/api/platform/stats")
async def platform_stats(request: Request, user=Depends(require_platform_admin)):
    tenants = tenant_repo.list_with_stats()
    active_tenants = [t for t in tenants if t.get("status") == "active"]
    total_machines = sum(t.get("machine_count", 0) for t in tenants)
    total_users = sum(t.get("user_count", 0) for t in tenants)
    lic = getattr(request.app.state, "license", None)
    enforcer = getattr(request.app.state, "seat_enforcer", None)
    active_seats = enforcer.active_count() if enforcer else 0
    return {
        "tenants": len(tenants),
        "active_tenants": len(active_tenants),
        "total_machines": total_machines,
        "active_seats": active_seats,
        "total_users": total_users,
        "max_tenants": lic.max_tenants if lic else None,
        "max_seats": lic.max_seats if lic else None,
        "license_tier": lic.tier if lic else "unlicensed",
        "license_customer": lic.customer if lic else None,
        "license_expires": lic.expires_at.isoformat() if lic else None,
        "tenant_list": [
            {
                "id": t["id"],
                "name": t.get("name"),
                "slug": t.get("slug"),
                "status": t.get("status"),
                "machine_count": t.get("machine_count", 0),
                "user_count": t.get("user_count", 0),
                "created_at": str(t["created_at"]) if t.get("created_at") else None,
            }
            for t in tenants
        ],
    }


@router.get("/api/platform/users")
async def platform_list_users(tenant_id: Optional[int] = None, user=Depends(require_platform_admin)):
    return list_platform_users(tenant_id)


@router.post("/api/platform/users")
async def platform_create_user(request: Request, req: CreateUserRequest, user=Depends(require_platform_admin)):
    return create_platform_user(request, user, req)


@router.delete("/api/platform/users/{user_id}")
async def platform_delete_user(request: Request, user_id: int, user=Depends(require_platform_admin)):
    return delete_platform_user(request, user, user_id, set_tenant_context, clear_tenant_context)
