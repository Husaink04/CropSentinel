"""Router registration grouped by service domain."""

from __future__ import annotations

from fastapi import FastAPI

from app.routers.activity_logs import router as activity_logs_router
from app.routers.analytics import router as analytics_router
from app.routers.auth import router as auth_router
from app.routers.data_logs import router as data_logs_router
from app.routers.database_admin import router as database_admin_router
from app.routers.dlp_enterprise import router as dlp_enterprise_router
from app.routers.internal import router as internal_router
from app.routers.internal_services import router as internal_services_router
from app.routers.machines_activity import router as machines_activity_router
from app.routers.phishing import router as phishing_router
from app.routers.platform import router as platform_router
from app.routers.sessions import router as sessions_router
from app.routers.settings_alerts import router as settings_alerts_router
from app.routers.teams import router as teams_router
from app.routers.tenants import router as tenants_router
from app.routers.users import router as users_router
from app.routers.websockets import router as websockets_router
from app.service_roles import AGENT_CONTROL_ROLE, FULL_BACKEND_ROLE, MONITORING_ROLE, REALTIME_ROLE

ROUTER_FAMILIES = {
    "auth": auth_router,
    "platform": platform_router,
    "users": users_router,
    "machines_activity": machines_activity_router,
    "analytics": analytics_router,
    "activity_logs": activity_logs_router,
    "tenants": tenants_router,
    "teams": teams_router,
    "settings_alerts": settings_alerts_router,
    "database_admin": database_admin_router,
    "sessions": sessions_router,
    "data_logs": data_logs_router,
    "dlp_enterprise": dlp_enterprise_router,
    "phishing": phishing_router,
    "websockets": websockets_router,
    "internal": internal_router,
    "internal_services": internal_services_router,
}

SERVICE_ROLE_ROUTE_FAMILIES = {
    FULL_BACKEND_ROLE: (
        "auth",
        "platform",
        "users",
        "machines_activity",
        "analytics",
        "activity_logs",
        "tenants",
        "teams",
        "settings_alerts",
        "database_admin",
        "sessions",
        "data_logs",
        "dlp_enterprise",
        "phishing",
        "websockets",
        "internal",
        "internal_services",
    ),
    AGENT_CONTROL_ROLE: (
        "machines_activity",
        "internal",
        "internal_services",
    ),
    MONITORING_ROLE: (
        "machines_activity",
        "data_logs",
        "internal",
        "internal_services",
    ),
    REALTIME_ROLE: (
        "sessions",
        "websockets",
        "internal",
        "internal_services",
    ),
}


def route_family_names_for_role(role: str = FULL_BACKEND_ROLE) -> tuple[str, ...]:
    return SERVICE_ROLE_ROUTE_FAMILIES.get(role, SERVICE_ROLE_ROUTE_FAMILIES[FULL_BACKEND_ROLE])


def route_paths_for_role(role: str = FULL_BACKEND_ROLE) -> list[str]:
    paths: list[str] = []
    for family in route_family_names_for_role(role):
        router = ROUTER_FAMILIES[family]
        for route in router.routes:
            path = getattr(route, "path", "")
            if path:
                paths.append(path)
    return sorted(set(paths))


def register_routers(app: FastAPI, *, role: str = FULL_BACKEND_ROLE) -> None:
    for family in route_family_names_for_role(role):
        app.include_router(ROUTER_FAMILIES[family])
