"""Lightweight request and trace context shared across next-gen foundations."""

from __future__ import annotations

from contextvars import ContextVar
from uuid import uuid4

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")
_trace_id_var: ContextVar[str] = ContextVar("trace_id", default="")
_client_ip_var: ContextVar[str] = ContextVar("client_ip", default="")
_service_name_var: ContextVar[str] = ContextVar("service_name", default="")


def new_id() -> str:
    return uuid4().hex


def bind_request_context(
    *,
    request_id: str,
    trace_id: str,
    client_ip: str = "",
    service_name: str = "",
) -> None:
    _request_id_var.set(request_id or "")
    _trace_id_var.set(trace_id or request_id or "")
    _client_ip_var.set(client_ip or "")
    _service_name_var.set(service_name or "")


def clear_request_context() -> None:
    bind_request_context(request_id="", trace_id="", client_ip="", service_name="")


def get_request_id() -> str:
    return _request_id_var.get("")


def get_trace_id() -> str:
    return _trace_id_var.get("") or get_request_id()


def get_client_ip() -> str:
    return _client_ip_var.get("")


def get_service_name() -> str:
    return _service_name_var.get("")
