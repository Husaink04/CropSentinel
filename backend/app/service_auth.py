"""Internal service-to-service auth helpers for future service extraction."""

from __future__ import annotations

import os
from collections.abc import Callable

from fastapi import HTTPException, Request

INTERNAL_SERVICE_NAME_HEADER = "X-Internal-Service"
INTERNAL_SERVICE_TOKEN_HEADER = "X-Internal-Service-Token"


def internal_service_token() -> str:
    return os.environ.get("INTERNAL_SERVICE_TOKEN", "").strip()


def metrics_observer_token() -> str:
    return os.environ.get("PROMETHEUS_METRICS_TOKEN", "").strip()


def service_identity_from_request(request: Request) -> str:
    return request.headers.get(INTERNAL_SERVICE_NAME_HEADER, "").strip()


async def require_internal_service(request: Request) -> str:
    expected = internal_service_token()
    token = request.headers.get(INTERNAL_SERVICE_TOKEN_HEADER, "").strip()
    service_name = service_identity_from_request(request) or "unknown"
    if not expected:
        raise HTTPException(status_code=503, detail="Internal service token is not configured")
    if token != expected:
        raise HTTPException(status_code=401, detail="Invalid internal service token")
    request.state.internal_service_name = service_name
    return service_name


async def require_internal_observer(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "").strip()
    expected_metrics_token = metrics_observer_token()
    if expected_metrics_token and auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if token == expected_metrics_token:
            request.state.internal_service_name = "prometheus"
            return "prometheus"
    return await require_internal_service(request)


def require_internal_service_scope(*allowed_services: str) -> Callable:
    allowed = {value.strip() for value in allowed_services if value and value.strip()}

    async def _check(request: Request) -> str:
        service_name = await require_internal_service(request)
        if allowed and service_name not in allowed:
            raise HTTPException(status_code=403, detail="Internal service is not allowed for this route")
        return service_name

    return _check
