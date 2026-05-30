"""Tenant-scoped user management router."""

from fastapi import APIRouter, Depends, Request

from app.core import require_permission
from app.services.user_service import create_user, delete_user, get_user, list_users, update_user
from models import CreateUserRequest, UpdateUserRequest

router = APIRouter()


@router.get("/api/users")
async def list_users_endpoint(user=Depends(require_permission("users.view"))):
    return list_users()


@router.post("/api/users")
async def create_user_endpoint(request: Request, req: CreateUserRequest, user=Depends(require_permission("users.manage"))):
    return create_user(request, user, req)


@router.get("/api/users/{user_id}")
async def get_user_endpoint(user_id: int, user=Depends(require_permission("users.view"))):
    return get_user(user_id)


@router.put("/api/users/{user_id}")
async def update_user_endpoint(request: Request, user_id: int, req: UpdateUserRequest, user=Depends(require_permission("users.manage"))):
    return update_user(request, user, user_id, req)


@router.delete("/api/users/{user_id}")
async def delete_user_endpoint(request: Request, user_id: int, user=Depends(require_permission("users.manage"))):
    return delete_user(request, user, user_id)
