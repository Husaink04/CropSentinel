"""Edge gateway and request-tracing middleware."""

from __future__ import annotations

import logging
import time

from fastapi import Request

from app.ops_metrics import ops_metrics
from app.request_context import bind_request_context, clear_request_context, new_id
from app.service_auth import service_identity_from_request

logger = logging.getLogger("cropsentinel.edge")


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return getattr(request.client, "host", "") if request.client else ""


async def edge_middleware(request: Request, call_next):
    request_id = request.headers.get("x-request-id", "").strip() or new_id()
    trace_id = request.headers.get("x-trace-id", "").strip() or request_id
    started = time.perf_counter()
    bind_request_context(
        request_id=request_id,
        trace_id=trace_id,
        client_ip=_client_ip(request),
        service_name=service_identity_from_request(request),
    )
    try:
        response = await call_next(request)
    except Exception:
        duration_ms = round((time.perf_counter() - started) * 1000, 2)
        ops_metrics.record_http_request(
            method=request.method,
            path=request.url.path,
            status_code=500,
            duration_seconds=duration_ms / 1000,
        )
        logger.info(
            "edge_request method=%s path=%s status=%s duration_ms=%s request_id=%s trace_id=%s internal_service=%s",
            request.method,
            request.url.path,
            500,
            duration_ms,
            request_id,
            trace_id,
            service_identity_from_request(request) or "-",
        )
        clear_request_context()
        raise
    duration_ms = round((time.perf_counter() - started) * 1000, 2)
    ops_metrics.record_http_request(
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_seconds=duration_ms / 1000,
    )
    logger.info(
        "edge_request method=%s path=%s status=%s duration_ms=%s request_id=%s trace_id=%s internal_service=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
        request_id,
        trace_id,
        service_identity_from_request(request) or "-",
    )
    clear_request_context()
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Trace-ID"] = trace_id
    return response
