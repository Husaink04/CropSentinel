"""Authentication and profile-related business logic."""

from typing import Optional
import json

from fastapi import HTTPException, Request

from passwords import hash_password, upgrade_hash_if_legacy, verify_password
from app.core import (
    audit_log,
    clear_login_failures,
    create_access_token,
    is_locked_out,
    record_login_failure,
)
from app.repos.settings_repo import settings_repo
from app.repos.tenant_repo import tenant_repo
from app.repos.user_repo import user_repo


def login_user(request: Request, username: str, password: str) -> dict:
    locked = is_locked_out(username)
    if locked:
        audit_log(
            request,
            {"sub": username, "user_id": 0, "role": ""},
            "login_locked",
            "auth",
            username,
            {"remaining_seconds": locked},
        )
        raise HTTPException(
            status_code=429,
            detail=f"Account temporarily locked due to repeated failures. Try again in {locked // 60 + 1} min.",
        )

    user = user_repo.get_by_username(username)
    if not user or not user.get("active", True):
        record_login_failure(username)
        audit_log(
            request,
            {"sub": username, "user_id": 0, "role": ""},
            "login_failed",
            "auth",
            username,
            {"reason": "invalid_credentials"},
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    stored = user.get("password_hash", "")
    if not verify_password(password, stored):
        record_login_failure(username)
        audit_log(
            request,
            {"sub": username, "user_id": user["id"], "role": user["role"]},
            "login_failed",
            "auth",
            username,
            {"reason": "wrong_password"},
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")

    clear_login_failures(username)
    tenant_id = int(user.get("tenant_id") or 1)
    tenant = tenant_repo.get(tenant_id)
    if not tenant:
        raise HTTPException(status_code=403, detail="Tenant not found")
    if tenant.get("status") == "suspended":
        audit_log(
            request,
            {"sub": username, "user_id": user["id"], "role": user["role"]},
            "login_blocked",
            "auth",
            username,
            {"reason": "tenant_suspended"},
        )
        raise HTTPException(status_code=403, detail="Your account has been suspended. Please contact support.")

    tenant_license = tenant_repo.get_license_info(tenant_id)
    if tenant_license and tenant_license.get("is_past_grace"):
        audit_log(
            request,
            {"sub": username, "user_id": user["id"], "role": user["role"]},
            "login_blocked",
            "auth",
            username,
            {"reason": "subscription_expired"},
        )
        raise HTTPException(status_code=403, detail="Your subscription has expired. Please renew to continue.")

    upgraded = upgrade_hash_if_legacy(password, stored)
    if upgraded:
        user_repo.update(user["id"], {"password_hash": upgraded})

    assigned = user.get("assigned_machines", "[]")
    if isinstance(assigned, str):
        try:
            assigned = json.loads(assigned)
        except Exception:
            assigned = []

    jwt_payload = {
        "sub": user["username"],
        "role": user["role"],
        "user_id": user["id"],
        "tenant_id": tenant_id,
        "display_name": user.get("display_name", ""),
        "assigned_machines": assigned,
    }
    token = create_access_token(jwt_payload)
    audit_log(request, jwt_payload, "login_success", "auth", user["username"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": user["role"],
        "display_name": user.get("display_name", ""),
        "username": user["username"],
        "tenant_id": tenant_id,
    }


def platform_login(request: Request, username: str, password: str) -> dict:
    locked = is_locked_out(username)
    if locked:
        raise HTTPException(
            status_code=429,
            detail=f"Account temporarily locked. Try again in {locked // 60 + 1} min.",
        )
    user = user_repo.get_by_username(username)
    if not user or not user.get("active", True):
        record_login_failure(username)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    stored = user.get("password_hash", "")
    if not verify_password(password, stored):
        record_login_failure(username)
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if user.get("role") != "admin" or int(user.get("tenant_id", 1)) != 1:
        raise HTTPException(status_code=403, detail="Platform admin access required")

    clear_login_failures(username)
    upgraded = upgrade_hash_if_legacy(password, stored)
    if upgraded:
        user_repo.update(user["id"], {"password_hash": upgraded})
    jwt_payload = {
        "sub": user["username"],
        "role": user["role"],
        "user_id": user["id"],
        "tenant_id": 1,
        "display_name": user.get("display_name", ""),
        "assigned_machines": [],
        "platform_admin": True,
    }
    token = create_access_token(jwt_payload)
    audit_log(request, jwt_payload, "platform_login", "auth", user["username"])
    return {
        "access_token": token,
        "token_type": "bearer",
        "role": "platform_admin",
        "display_name": user.get("display_name", ""),
        "username": user["username"],
        "tenant_id": 1,
    }


def build_profile(user: dict) -> dict:
    return {
        "username": user.get("sub"),
        "role": user.get("role"),
        "user_id": user.get("user_id"),
        "display_name": user.get("display_name", ""),
        "assigned_machines": user.get("assigned_machines", []),
        "tenant_id": user.get("tenant_id", 1),
    }


def get_tenant_license(user: dict) -> dict:
    tenant_id = int(user.get("tenant_id") or 1)
    info = tenant_repo.get_license_info(tenant_id)
    if not info:
        raise HTTPException(status_code=404, detail="Tenant not found")
    tenant = tenant_repo.get(tenant_id) or {}
    return {
        **info,
        "tenant_id": tenant_id,
        "tenant_name": tenant.get("name", ""),
        "tenant_slug": tenant.get("slug", ""),
    }


def change_password(request: Request, user: dict, old_password: str, new_password: str):
    db_user = user_repo.get_by_username(user.get("sub"))
    if not db_user:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_password(old_password, db_user["password_hash"]):
        audit_log(request, user, "password_change_failed", "user", user.get("sub"))
        raise HTTPException(status_code=400, detail="Current password incorrect")
    user_repo.update(db_user["id"], {"password_hash": hash_password(new_password)})
    audit_log(request, user, "password_changed", "user", user.get("sub"))
    return {"message": "Password updated"}


def verify_agent_password(password: str) -> dict:
    settings = settings_repo.get()
    stored = settings.get("agent_stop_password_hash")
    ok = verify_password(password, stored)
    if ok:
        upgraded = upgrade_hash_if_legacy(password, stored)
        if upgraded:
            settings_repo.update({"agent_stop_password_hash": upgraded})
    return {"valid": ok}
