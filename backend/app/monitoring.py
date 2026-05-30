"""Sentry initialization and payload scrubbing helpers."""

from __future__ import annotations

import copy
import logging
import os
from typing import Any

try:
    import sentry_sdk
    from sentry_sdk.integrations.fastapi import FastApiIntegration
except Exception:  # pragma: no cover - optional dependency
    sentry_sdk = None
    FastApiIntegration = None


logger = logging.getLogger("croppro.monitoring")

_REDACTED = "[Filtered]"
_SENSITIVE_KEYS = {
    "password",
    "password_hash",
    "authorization",
    "access_token",
    "refresh_token",
    "token",
    "jwt",
    "license",
    "license_key",
    "licensefile",
    "secret",
    "credential",
    "webrtc_turn_password",
}


def _scrub_value(value: Any) -> Any:
    if isinstance(value, dict):
        cleaned = {}
        for key, item in value.items():
            if str(key).lower() in _SENSITIVE_KEYS:
                cleaned[key] = _REDACTED
            else:
                cleaned[key] = _scrub_value(item)
        return cleaned
    if isinstance(value, list):
        return [_scrub_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_scrub_value(item) for item in value)
    return value


def before_send(event: dict, hint: dict | None):
    if not event:
        return event
    return _scrub_value(copy.deepcopy(event))


def init_sentry() -> bool:
    if sentry_sdk is None or FastApiIntegration is None:
        logger.info("sentry-sdk not installed; monitoring disabled")
        return False

    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        logger.info("SENTRY_DSN not set; monitoring disabled")
        return False

    traces_sample_rate = float(os.environ.get("SENTRY_TRACES_SAMPLE_RATE", "0.1"))
    environment = os.environ.get("SENTRY_ENVIRONMENT", os.environ.get("ENV", "development"))
    release = os.environ.get("SENTRY_RELEASE", "").strip() or None

    sentry_sdk.init(
        dsn=dsn,
        integrations=[FastApiIntegration()],
        send_default_pii=False,
        traces_sample_rate=traces_sample_rate,
        before_send=before_send,
        environment=environment,
        release=release,
    )
    logger.info("Sentry monitoring enabled for environment=%s", environment)
    return True


def set_sentry_context(
    *,
    tenant_id: int | None = None,
    user_role: str | None = None,
    endpoint: str | None = None,
    username: str | None = None,
) -> None:
    if sentry_sdk is None or getattr(sentry_sdk.Hub.current, "client", None) is None:
        return

    with sentry_sdk.configure_scope() as scope:
        if tenant_id is not None:
            scope.set_tag("tenant_id", str(tenant_id))
        if user_role:
            scope.set_tag("user_role", user_role)
        if endpoint:
            scope.set_tag("endpoint", endpoint)
        if username:
            scope.user = {"username": username, "id": username}


def set_sentry_tags(tags: dict[str, Any] | None = None) -> None:
    if not tags:
        return
    if sentry_sdk is None or getattr(sentry_sdk.Hub.current, "client", None) is None:
        return
    with sentry_sdk.configure_scope() as scope:
        for key, value in tags.items():
            if value is None:
                continue
            scope.set_tag(str(key), str(value))
