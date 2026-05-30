"""User management service layer."""

import json

from fastapi import HTTPException, Request

from passwords import hash_password
from app.core import VALID_ROLES, audit_log
from app.repos.tenant_repo import tenant_repo
from app.repos.user_repo import user_repo


def list_users():
    users = user_repo.list_current_tenant()
    for item in users:
        item.pop("password_hash", None)
    return users


def get_user(user_id: int):
    user = user_repo.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.pop("password_hash", None)
    return user


def create_user(request: Request, actor: dict, payload) -> dict:
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role: {payload.role}")
    if user_repo.get_by_username(payload.username):
        raise HTTPException(status_code=409, detail="Username already exists")

    target_tenant = None
    if payload.tenant_id is not None:
        caller_tenant = int(actor.get("tenant_id") or 1)
        if caller_tenant != 1:
            raise HTTPException(status_code=403, detail="Only platform admin can assign users to other tenants")
        tenant = tenant_repo.get(payload.tenant_id)
        if not tenant:
            raise HTTPException(status_code=400, detail=f"Tenant {payload.tenant_id} not found")
        target_tenant = payload.tenant_id

    user_id = user_repo.create(
        {
            "username": payload.username,
            "password_hash": hash_password(payload.password),
            "display_name": payload.display_name or payload.username,
            "role": payload.role,
            "assigned_machines": json.dumps(payload.assigned_machines or []),
            "active": True,
            "created_by": actor.get("sub", "admin"),
            **({"tenant_id": target_tenant} if target_tenant else {}),
        }
    )
    audit_log(
        request,
        actor,
        "user_created",
        "user",
        str(user_id),
        {"target_username": payload.username, "role": payload.role, "tenant_id": target_tenant},
    )
    return {"id": user_id, "message": "User created"}


def update_user(request: Request, actor: dict, user_id: int, payload) -> dict:
    target = user_repo.get_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    data = payload.model_dump(exclude_none=True)
    if "role" in data and data["role"] not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role: {data['role']}")

    changes = {}
    if "role" in data and data["role"] != target.get("role"):
        changes["role_change"] = f"{target.get('role')} -> {data['role']}"
    if "active" in data and data["active"] != target.get("active"):
        changes["active_change"] = f"{target.get('active')} -> {data['active']}"
    if "password" in data:
        data["password_hash"] = hash_password(data.pop("password"))
        changes["password_reset"] = True
    if "assigned_machines" in data:
        data["assigned_machines"] = json.dumps(data["assigned_machines"])
        changes["machines_updated"] = True

    user_repo.update(user_id, data)
    audit_log(request, actor, "user_updated", "user", str(user_id), {"target_username": target["username"], **changes})
    return {"message": "User updated"}


def delete_user(request: Request, actor: dict, user_id: int) -> dict:
    target = user_repo.get_by_id(user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    if target["username"] == actor.get("sub"):
        raise HTTPException(status_code=400, detail="Cannot delete yourself")
    user_repo.delete(user_id)
    audit_log(
        request,
        actor,
        "user_deleted",
        "user",
        str(user_id),
        {"target_username": target["username"], "role": target["role"]},
    )
    return {"message": "User deleted"}


def list_platform_users(tenant_id=None):
    users = user_repo.list_cross_tenant(tenant_id)
    for item in users:
        item.pop("password_hash", None)
    return users


def create_platform_user(request: Request, actor: dict, payload) -> dict:
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=400, detail=f"Invalid role: {payload.role}")
    if payload.tenant_id is None:
        raise HTTPException(status_code=400, detail="tenant_id is required")
    tenant = tenant_repo.get(payload.tenant_id)
    if not tenant:
        raise HTTPException(status_code=400, detail=f"Tenant {payload.tenant_id} not found")
    if user_repo.get_by_username(payload.username):
        raise HTTPException(status_code=409, detail="Username already exists")

    user_id = user_repo.create(
        {
            "username": payload.username,
            "password_hash": hash_password(payload.password),
            "display_name": payload.display_name or payload.username,
            "role": payload.role,
            "assigned_machines": json.dumps(payload.assigned_machines or []),
            "active": True,
            "created_by": actor.get("sub", "platform_admin"),
            "tenant_id": payload.tenant_id,
        }
    )
    audit_log(
        request,
        actor,
        "platform_user_created",
        "user",
        str(user_id),
        {"target_username": payload.username, "role": payload.role, "tenant_id": payload.tenant_id},
    )
    return {"id": user_id, "message": "User created", "tenant_id": payload.tenant_id}


def delete_platform_user(request: Request, actor: dict, user_id: int, set_tenant_context, clear_tenant_context):
    rows = user_repo.list_cross_tenant(None)
    target = next((row for row in rows if row["id"] == user_id), None)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    set_tenant_context(int(target["tenant_id"]))
    try:
        user_repo.delete(user_id)
    finally:
        clear_tenant_context()
    audit_log(
        request,
        actor,
        "platform_user_deleted",
        "user",
        str(user_id),
        {"target_username": target.get("username"), "tenant_id": target.get("tenant_id")},
    )
    return {"message": "User deleted"}
