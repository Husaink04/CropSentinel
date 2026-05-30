"""Authentication router."""

from fastapi import APIRouter, Depends, Request
from fastapi.security import OAuth2PasswordRequestForm

from app.core import get_current_user, limiter
from app.services.auth_service import (
    build_profile,
    change_password,
    get_tenant_license,
    login_user,
    platform_login,
    verify_agent_password,
)
from models import AgentPasswordRequest, ChangePasswordRequest

router = APIRouter()


@router.post("/api/auth/login")
@limiter.limit("10/15minute")
async def login(request: Request, form: OAuth2PasswordRequestForm = Depends()):
    return login_user(request, form.username, form.password)


@router.get("/api/auth/me")
async def get_me(user=Depends(get_current_user)):
    return build_profile(user)


@router.get("/api/my-tenant/license")
async def get_my_tenant_license(user=Depends(get_current_user)):
    return get_tenant_license(user)


@router.post("/api/auth/change-password")
async def change_password_endpoint(request: Request, req: ChangePasswordRequest, user=Depends(get_current_user)):
    return change_password(request, user, req.old_password, req.new_password)


@router.post("/api/auth/verify-agent-password")
@limiter.limit("5/minute")
async def verify_agent_password_endpoint(request: Request, req: AgentPasswordRequest):
    return verify_agent_password(req.password)


@router.post("/api/platform/login")
@limiter.limit("10/15minute")
async def platform_login_endpoint(request: Request, form: OAuth2PasswordRequestForm = Depends()):
    return platform_login(request, form.username, form.password)
