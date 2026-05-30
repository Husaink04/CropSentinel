"""Shared authentication, authorization, and request helpers."""

from collections import deque
from time import monotonic
from typing import Optional
from datetime import timedelta
import json
import logging
import os
import secrets

import jwt
from fastapi import Depends, HTTPException, Request, WebSocket
from fastapi.security import OAuth2PasswordBearer
from slowapi import Limiter
from slowapi.util import get_remote_address

from database import db, clear_tenant_context, set_tenant_context, utcnow
from app.db.core import get_tenant_id as _tid
from licensing import has_feature as license_has_feature
from app.monitoring import set_sentry_context, set_sentry_tags
from app.request_context import get_trace_id
from app.repos.audit_repo import audit_repo
from app.repos.settings_repo import settings_repo
from app.repos.tenant_repo import tenant_repo
from app.services.dlp_service import dlp_service
from app.services.phishing_service import phishing_service
from app.event_bus import EventTopics, internal_event_bus

logger = logging.getLogger("cropsentinel")

DEFAULT_TRACK_SCREENSHOTS = os.environ.get("DEFAULT_TRACK_SCREENSHOTS", "0").strip().lower() in {"1", "true", "yes", "on"}
DEFAULT_TRACK_BROWSER = os.environ.get("DEFAULT_TRACK_BROWSER", "1").strip().lower() not in {"0", "false", "no", "off"}
DEFAULT_TRACK_APPLICATIONS = os.environ.get("DEFAULT_TRACK_APPLICATIONS", "1").strip().lower() not in {"0", "false", "no", "off"}
DEFAULT_TRACK_INPUT_ACTIVITY = os.environ.get("DEFAULT_TRACK_INPUT_ACTIVITY", "0").strip().lower() in {"1", "true", "yes", "on"}
DEFAULT_SCREENSHOT_INTERVAL = int(os.environ.get("DEFAULT_SCREENSHOT_INTERVAL", "180"))
DEFAULT_ACTIVITY_SYNC_INTERVAL = int(os.environ.get("DEFAULT_ACTIVITY_SYNC_INTERVAL", "60"))
DEFAULT_HEARTBEAT_INTERVAL_SECONDS = int(os.environ.get("DEFAULT_HEARTBEAT_INTERVAL_SECONDS", "30"))
DEFAULT_APP_TRACKER_INTERVAL_SECONDS = int(os.environ.get("DEFAULT_APP_TRACKER_INTERVAL_SECONDS", "10"))
DEFAULT_NETWORK_INTERVAL_SECONDS = int(os.environ.get("DEFAULT_NETWORK_INTERVAL_SECONDS", "60"))
DEFAULT_USB_INTERVAL_SECONDS = int(os.environ.get("DEFAULT_USB_INTERVAL_SECONDS", "10"))
DEFAULT_PRINT_INTERVAL_SECONDS = int(os.environ.get("DEFAULT_PRINT_INTERVAL_SECONDS", "20"))
DEFAULT_FILE_CACHE_FAST_SWEEP_SECONDS = float(os.environ.get("DEFAULT_FILE_CACHE_FAST_SWEEP_SECONDS", "10"))
DEFAULT_FILE_CACHE_RECURSIVE_SWEEP_SECONDS = float(os.environ.get("DEFAULT_FILE_CACHE_RECURSIVE_SWEEP_SECONDS", "120"))
DEFAULT_FILE_CACHE_SWEEPER_ENABLED = os.environ.get("DEFAULT_FILE_CACHE_SWEEPER_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
DEFAULT_AGENT_SELF_THROTTLE_ENABLED = os.environ.get("DEFAULT_AGENT_SELF_THROTTLE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"}
DEFAULT_AGENT_SELF_THROTTLE_CPU_PERCENT = int(os.environ.get("DEFAULT_AGENT_SELF_THROTTLE_CPU_PERCENT", "85"))
DEFAULT_AGENT_SELF_THROTTLE_MEMORY_PERCENT = int(os.environ.get("DEFAULT_AGENT_SELF_THROTTLE_MEMORY_PERCENT", "80"))
DEFAULT_AGENT_SELF_THROTTLE_QUEUE_DEPTH = int(os.environ.get("DEFAULT_AGENT_SELF_THROTTLE_QUEUE_DEPTH", "500"))
DEFAULT_AGENT_SELF_THROTTLE_MULTIPLIER = float(os.environ.get("DEFAULT_AGENT_SELF_THROTTLE_MULTIPLIER", "2.0"))
DEFAULT_AGENT_SELF_THROTTLE_COOLDOWN_SECONDS = int(os.environ.get("DEFAULT_AGENT_SELF_THROTTLE_COOLDOWN_SECONDS", "300"))
DEFAULT_INPUT_BUCKET_SECONDS = int(os.environ.get("DEFAULT_INPUT_BUCKET_SECONDS", "30"))
DEFAULT_BASELINE_ENABLED = os.environ.get("DEFAULT_BASELINE_INVENTORY_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"}
DEFAULT_BASELINE_WORKER_COUNT = int(os.environ.get("DEFAULT_BASELINE_INVENTORY_WORKER_COUNT", "1"))
DEFAULT_BASELINE_IO_THROTTLE = float(os.environ.get("DEFAULT_BASELINE_INVENTORY_IO_THROTTLE_SECONDS", "0.05"))
DEFAULT_BASELINE_UPLOAD_INTERVAL = int(os.environ.get("DEFAULT_BASELINE_INVENTORY_UPLOAD_INTERVAL_SECONDS", "60"))
DEFAULT_BASELINE_UPLOAD_BATCH = int(os.environ.get("DEFAULT_BASELINE_INVENTORY_UPLOAD_BATCH_SIZE", "100"))
DEFAULT_BASELINE_MAX_HASH_SIZE = int(os.environ.get("DEFAULT_BASELINE_INVENTORY_MAX_HASH_FILE_SIZE", "0"))
DEFAULT_BASELINE_MAX_PARSER_SIZE = int(os.environ.get("DEFAULT_BASELINE_INVENTORY_MAX_PARSER_FILE_SIZE", str(25 * 1024 * 1024)))
DEFAULT_BASELINE_MAX_OCR_SIZE = int(os.environ.get("DEFAULT_BASELINE_INVENTORY_MAX_OCR_FILE_SIZE", str(10 * 1024 * 1024)))
DEFAULT_BASELINE_RESCAN_SECONDS = int(os.environ.get("DEFAULT_BASELINE_INVENTORY_RESCAN_UNCHANGED_AFTER_SECONDS", str(24 * 3600)))
DEFAULT_BASELINE_DISCOVERY_SECONDS = int(os.environ.get("DEFAULT_BASELINE_INVENTORY_MOUNT_DISCOVERY_INTERVAL_SECONDS", "300"))

VALID_ROLES = {"admin", "manager", "viewer", "remote_operator"}

ROLE_PERMISSIONS = {
    "admin": {
        "machines.view", "machines.edit", "machines.delete",
        "teams.view", "teams.manage",
        "activity.view", "screenshots.view",
        "analytics.view", "productivity.view",
        "alerts.view", "alerts.manage",
        "remote.access",
        "reports.generate",
        "settings.view", "settings.edit",
        "users.view", "users.manage",
    },
    "manager": {
        "machines.view",
        "teams.view", "teams.manage",
        "activity.view", "screenshots.view",
        "analytics.view", "productivity.view",
        "alerts.view", "alerts.manage",
        "reports.generate",
    },
    "viewer": {
        "machines.view",
        "teams.view",
        "activity.view", "screenshots.view",
        "analytics.view", "productivity.view",
    },
    "remote_operator": {
        "machines.view",
        "teams.view",
        "activity.view", "screenshots.view",
        "analytics.view",
        "remote.access",
    },
}


def has_permission(user: dict, *perms: str) -> bool:
    role_perms = ROLE_PERMISSIONS.get(user.get("role", ""), set())
    return all(perm in role_perms for perm in perms)


def can_access_machine(user: dict, machine_id: str) -> bool:
    assigned = user.get("assigned_machines") or []
    if not assigned or user.get("role") == "admin":
        return True
    return machine_id in assigned


def cors_middleware_kwargs():
    raw = os.environ.get("CORS_ORIGINS", "").strip()
    if raw == "*":
        logger.warning("CORS_ORIGINS=* is insecure - set specific origins for production")
        return {"allow_origins": ["*"], "allow_credentials": False}
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    if not origins:
        logger.warning("CORS_ORIGINS not set - defaulting to localhost:5173 only")
        origins = ["http://localhost:5173"]
    return {"allow_origins": origins, "allow_credentials": True}


limiter = Limiter(key_func=get_remote_address, default_limits=[])

LOGIN_FAIL_THRESHOLD = int(os.environ.get("LOGIN_FAIL_THRESHOLD", "8"))
LOGIN_FAIL_WINDOW = int(os.environ.get("LOGIN_FAIL_WINDOW", "900"))
LOGIN_LOCKOUT_SECONDS = int(os.environ.get("LOGIN_LOCKOUT_SECONDS", "900"))

_login_fails: dict[str, deque] = {}
_login_lockouts: dict[str, float] = {}

SECRET_KEY = os.environ.get("SECRET_KEY", "")
if not SECRET_KEY or SECRET_KEY == "replace-with-long-random-string":
    SECRET_KEY = secrets.token_urlsafe(48)
    logger.warning(
        "SECRET_KEY not set or still default - generated a random key. "
        "JWTs will not survive server restarts."
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_HOURS = 24
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")


async def tenant_context_middleware(request: Request, call_next):
    request.state.tenant_id = None
    request.state.user_role = None
    request.state.username = None
    try:
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            token = auth[7:]
            try:
                payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
                tenant_id = int(payload.get("tenant_id") or 1)
                set_tenant_context(tenant_id)
                request.state.tenant_id = tenant_id
                request.state.user_role = payload.get("role")
                request.state.username = payload.get("sub")
            except Exception:
                pass
    except Exception:
        pass
    try:
        set_sentry_context(
            tenant_id=request.state.tenant_id,
            user_role=request.state.user_role,
            endpoint=str(request.url.path),
            username=request.state.username,
        )
        response = await call_next(request)
    finally:
        clear_tenant_context()
    return response


def is_locked_out(username: str) -> int:
    if not username:
        return 0
    key = username.lower()
    until = _login_lockouts.get(key, 0)
    remaining = int(until - monotonic())
    if remaining <= 0:
        _login_lockouts.pop(key, None)
        return 0
    return remaining


def record_login_failure(username: str):
    if not username:
        return
    key = username.lower()
    now = monotonic()
    dq = _login_fails.setdefault(key, deque())
    dq.append(now)
    cutoff = now - LOGIN_FAIL_WINDOW
    while dq and dq[0] < cutoff:
        dq.popleft()
    if len(dq) >= LOGIN_FAIL_THRESHOLD:
        _login_lockouts[key] = now + LOGIN_LOCKOUT_SECONDS
        dq.clear()
        logger.warning("Account %s locked out after %d failed attempts", key, LOGIN_FAIL_THRESHOLD)


def clear_login_failures(username: str):
    if not username:
        return
    key = username.lower()
    _login_fails.pop(key, None)
    _login_lockouts.pop(key, None)


def create_access_token(data: dict) -> str:
    expire = utcnow() + timedelta(hours=ACCESS_TOKEN_EXPIRE_HOURS)
    return jwt.encode({**data, "exp": expire}, SECRET_KEY, algorithm=ALGORITHM)


async def get_current_user(token: str = Depends(oauth2_scheme)):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        if not payload.get("sub"):
            raise HTTPException(status_code=401, detail="Invalid token")
        set_tenant_context(int(payload.get("tenant_id") or 1))
        set_sentry_context(
            tenant_id=int(payload.get("tenant_id") or 1),
            user_role=payload.get("role"),
            username=payload.get("sub"),
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid token")


def require_permission(*perms: str):
    async def _check(user=Depends(get_current_user)):
        for perm in perms:
            if not has_permission(user, perm):
                raise HTTPException(status_code=403, detail=f"Permission denied: {perm}")
        return user

    return _check


async def require_platform_admin(user=Depends(get_current_user)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    if int(user.get("tenant_id") or 1) != 1:
        raise HTTPException(status_code=403, detail="Platform admin access required")
    return user


def require_feature(feature_name: str):
    async def _check(request: Request):
        lic = getattr(request.app.state, "license", None)
        if not license_has_feature(lic, feature_name):
            raise HTTPException(
                status_code=402,
                detail=f"Feature '{feature_name}' is not included in your license tier. "
                "Contact HAAK IT Solutions to upgrade.",
            )
        return True

    return _check


async def get_current_tenant(request: Request, user=Depends(get_current_user)) -> dict:
    tenant_id = int(user.get("tenant_id") or 1)
    override_slug = request.headers.get("X-Tenant-Slug", "").strip()
    if override_slug and user.get("role") == "admin":
        tenant = tenant_repo.get_by_slug(override_slug)
        if tenant:
            tenant_id = int(tenant["id"])
    tenant = tenant_repo.get(tenant_id)
    if not tenant or tenant.get("status") != "active":
        raise HTTPException(status_code=401, detail="Tenant is inactive or missing.")
    set_tenant_context(tenant_id)
    return tenant


def filter_machines_for_user(machines: list, user: dict) -> list:
    assigned = user.get("assigned_machines") or []
    if not assigned or user.get("role") == "admin":
        return machines
    assigned_set = set(assigned)
    return [m for m in machines if m.get("machine_id") in assigned_set]


def check_machine_access(user: dict, machine_id: str):
    if not can_access_machine(user, machine_id):
        raise HTTPException(status_code=403, detail="No access to this machine")


def audit_log(
    request: Optional[Request],
    user: Optional[dict],
    action: str,
    resource_type: str = "",
    resource_id: str = "",
    metadata: Optional[dict] = None,
):
    try:
        ip = ""
        if request:
            ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            if not ip:
                ip = getattr(request.client, "host", "") if request.client else ""
        audit_repo.insert(
            {
                "timestamp": utcnow(),
                "user_id": (user or {}).get("user_id", 0),
                "username": (user or {}).get("sub", "system"),
                "role": (user or {}).get("role", ""),
                "action": action,
                "resource_type": resource_type,
                "resource_id": str(resource_id),
                "ip_address": ip,
                "metadata": json.dumps(metadata or {}),
            }
        )
        internal_event_bus.publish(
            topic=EventTopics.AUDIT_EVENTS,
            event_type="audit.logged",
            tenant_id=int((user or {}).get("tenant_id") or (_tid() or 1)),
            machine_id="",
            payload={
                "action": action,
                "resource_type": resource_type,
                "resource_id": str(resource_id),
                "metadata": metadata or {},
                "username": (user or {}).get("sub", "system"),
                "timestamp": utcnow().isoformat(),
            },
        )
    except Exception as exc:
        logging.getLogger("cropsentinel.audit").warning("Audit log failed: %s", exc)


def expected_agent_api_key() -> str:
    return os.environ.get("AGENT_API_KEY", "").strip()


async def require_agent_api_key(request: Request):
    expected = expected_agent_api_key()
    enroll_token = (
        request.headers.get("X-CropSentinel-Enroll-Token")
        or request.headers.get("x-cropsentinel-enroll-token")
        or request.headers.get("X-CropPro-Enroll-Token")
        or request.headers.get("x-croppro-enroll-token")
    )
    resolved_tid: Optional[int] = None
    if enroll_token:
        tenant = tenant_repo.get_by_enrollment_token(enroll_token.strip())
        if not tenant:
            logger.warning(
                "agent_auth_failed reason_code=invalid_enrollment_token endpoint=%s enroll_token_present=true",
                str(request.url.path),
            )
            set_sentry_tags(
                {
                    "registration_status": 401,
                    "registration_error_type": "invalid_enrollment_token",
                    "enroll_token_present": True,
                }
            )
            raise HTTPException(
                status_code=401,
                detail="invalid_enrollment_token: Enrollment token is invalid",
            )
        resolved_tid = int(tenant["id"])
    if expected:
        got = (
            request.headers.get("X-CropSentinel-Agent-Key")
            or request.headers.get("x-cropsentinel-agent-key")
            or request.headers.get("X-CropPro-Agent-Key")
            or request.headers.get("x-croppro-agent-key")
        )
        if got != expected and resolved_tid is None:
            logger.warning(
                "agent_auth_failed reason_code=invalid_agent_api_key endpoint=%s enroll_token_present=%s",
                str(request.url.path),
                bool(enroll_token),
            )
            set_sentry_tags(
                {
                    "registration_status": 401,
                    "registration_error_type": "invalid_agent_api_key",
                    "enroll_token_present": bool(enroll_token),
                }
            )
            raise HTTPException(status_code=401, detail="Invalid or missing agent API key")

    machine_id = ""
    machine_tid: Optional[int] = None

    try:
        body = json.loads(await request.body())
        machine_id = body.get("machine_id", "")
        if machine_id:
            tenant_id = db.get_machine_tenant_id(machine_id)
            if tenant_id:
                machine_tid = int(tenant_id)
                if resolved_tid is not None and machine_tid != resolved_tid:
                    logger.warning(
                        "agent_auth_failed reason_code=tenant_mismatch endpoint=%s machine_id_prefix=%s machine_tid=%s token_tid=%s",
                        str(request.url.path),
                        machine_id[:12],
                        machine_tid,
                        resolved_tid,
                    )
                    set_sentry_tags(
                        {
                            "registration_status": 403,
                            "registration_error_type": "tenant_mismatch",
                            "enroll_token_present": bool(enroll_token),
                        }
                    )
                    raise HTTPException(
                        status_code=403,
                        detail="tenant_mismatch: Machine belongs to a different tenant than supplied enrollment token",
                    )
                if resolved_tid is None:
                    resolved_tid = machine_tid
    except HTTPException:
        raise
    except Exception:
        pass

    if resolved_tid is not None:
        set_tenant_context(resolved_tid)
        request.state.tenant_id = resolved_tid
        set_sentry_context(tenant_id=resolved_tid, endpoint=str(request.url.path))
        set_sentry_tags(
            {
                "registration_status": "ok",
                "registration_error_type": "none",
                "enroll_token_present": True,
            }
        )


def agent_ws_key_ok(websocket: WebSocket) -> bool:
    expected = expected_agent_api_key()
    enroll_token = (
        websocket.headers.get("x-cropsentinel-enroll-token")
        or websocket.headers.get("X-CropSentinel-Enroll-Token")
        or websocket.headers.get("x-croppro-enroll-token")
        or websocket.headers.get("X-CropPro-Enroll-Token")
    )
    if enroll_token:
        tenant = tenant_repo.get_by_enrollment_token(enroll_token.strip())
        if tenant:
            return True
        logger.warning("agent_ws_auth_failed reason_code=invalid_enrollment_token endpoint=%s", str(websocket.url.path))
        return False
    if not expected:
        return True
    got = (
        websocket.headers.get("x-cropsentinel-agent-key")
        or websocket.headers.get("X-CropSentinel-Agent-Key")
        or websocket.headers.get("x-croppro-agent-key")
        or websocket.headers.get("X-CropPro-Agent-Key")
    )
    ok = got == expected
    if not ok:
        logger.warning("agent_ws_auth_failed reason_code=invalid_agent_api_key endpoint=%s", str(websocket.url.path))
    return ok


def agent_public_config() -> dict:
    settings = settings_repo.get()
    tenant_id = _tid() or 1
    effective_policy = dlp_service.get_effective_policy(int(tenant_id))
    phishing_policy = phishing_service.get_effective_policy(int(tenant_id))
    screenshot_interval = int(settings.get("screenshot_interval", DEFAULT_SCREENSHOT_INTERVAL))
    activity_sync_interval = int(settings.get("activity_sync_interval", DEFAULT_ACTIVITY_SYNC_INTERVAL))
    agent_performance = {
        "screenshot_interval_seconds": screenshot_interval,
        "browser_sync_interval_seconds": activity_sync_interval,
        "heartbeat_interval_seconds": int(settings.get("heartbeat_interval_seconds", DEFAULT_HEARTBEAT_INTERVAL_SECONDS)),
        "app_tracker_interval_seconds": int(settings.get("app_tracker_interval_seconds", DEFAULT_APP_TRACKER_INTERVAL_SECONDS)),
        "network_interval_seconds": int(settings.get("network_interval_seconds", DEFAULT_NETWORK_INTERVAL_SECONDS)),
        "usb_interval_seconds": int(settings.get("usb_interval_seconds", DEFAULT_USB_INTERVAL_SECONDS)),
        "print_interval_seconds": int(settings.get("print_interval_seconds", DEFAULT_PRINT_INTERVAL_SECONDS)),
        "file_cache_fast_sweep_seconds": float(settings.get("file_cache_fast_sweep_seconds", DEFAULT_FILE_CACHE_FAST_SWEEP_SECONDS)),
        "file_cache_recursive_sweep_seconds": float(settings.get("file_cache_recursive_sweep_seconds", DEFAULT_FILE_CACHE_RECURSIVE_SWEEP_SECONDS)),
        "file_cache_sweeper_enabled": settings.get("file_cache_sweeper_enabled", DEFAULT_FILE_CACHE_SWEEPER_ENABLED) is not False,
        "self_throttle": {
            "enabled": settings.get("agent_self_throttle_enabled", DEFAULT_AGENT_SELF_THROTTLE_ENABLED) is not False,
            "cpu_percent_threshold": int(settings.get("agent_self_throttle_cpu_percent", DEFAULT_AGENT_SELF_THROTTLE_CPU_PERCENT)),
            "memory_percent_threshold": int(settings.get("agent_self_throttle_memory_percent", DEFAULT_AGENT_SELF_THROTTLE_MEMORY_PERCENT)),
            "queue_depth_threshold": int(settings.get("agent_self_throttle_queue_depth", DEFAULT_AGENT_SELF_THROTTLE_QUEUE_DEPTH)),
            "interval_multiplier": float(settings.get("agent_self_throttle_multiplier", DEFAULT_AGENT_SELF_THROTTLE_MULTIPLIER)),
            "cooldown_seconds": int(settings.get("agent_self_throttle_cooldown_seconds", DEFAULT_AGENT_SELF_THROTTLE_COOLDOWN_SECONDS)),
        },
    }
    return {
        "schema_version": 1,
        "trace_id": get_trace_id(),
        "agent_protocol": {
            "schema_version": 1,
            "event_envelope_version": 1,
            "transport": ["websocket", "http_fallback"],
            "paths": {
                "agent_ws": "/ws/agent/{machine_id}",
                "admin_ws": "/ws/admin",
                "heartbeat": "/api/activity/heartbeat",
            },
            "capabilities": {
                "event_ack": True,
                "config_push": True,
                "baseline_inventory": True,
                "self_throttle": True,
                "dlp_policy": True,
                "phishing_policy": True,
            },
        },
        "track_screenshots": settings.get("track_screenshots", DEFAULT_TRACK_SCREENSHOTS) is True,
        "track_browser": settings.get("track_browser", DEFAULT_TRACK_BROWSER) is not False,
        "track_applications": settings.get("track_applications", DEFAULT_TRACK_APPLICATIONS) is not False,
        "track_input_activity": settings.get("track_input_activity", DEFAULT_TRACK_INPUT_ACTIVITY) is True,
        "screenshot_interval": screenshot_interval,
        "activity_sync_interval": activity_sync_interval,
        "input_bucket_seconds": int(settings.get("input_bucket_seconds", DEFAULT_INPUT_BUCKET_SECONDS)),
        "agent_performance": agent_performance,
        "dlp_enabled": settings.get("dlp_enabled", True) is not False,
        "dlp_keywords": settings.get("dlp_keywords", []),
        "dlp_custom_patterns": settings.get("dlp_custom_patterns", {}),
        "dlp_risk_thresholds": settings.get(
            "dlp_risk_thresholds",
            {"low": 1, "medium": 3, "high": 7},
        ),
        "dlp_policy": effective_policy,
        "dlp_policy_version": effective_policy.get("policy_version", 1),
        "dlp_policy_hash": effective_policy.get("policy_hash", ""),
        "phishing_policy": phishing_policy,
        "phishing_policy_version": phishing_policy.get("policy_version", 1),
        "phishing_policy_hash": phishing_policy.get("policy_hash", ""),
        "baseline_inventory": {
            "enabled": settings.get("baseline_inventory_enabled", DEFAULT_BASELINE_ENABLED) is True,
            "worker_count": int(settings.get("baseline_inventory_worker_count", DEFAULT_BASELINE_WORKER_COUNT)),
            "io_throttle_seconds": float(settings.get("baseline_inventory_io_throttle_seconds", DEFAULT_BASELINE_IO_THROTTLE)),
            "upload_interval_seconds": int(settings.get("baseline_inventory_upload_interval_seconds", DEFAULT_BASELINE_UPLOAD_INTERVAL)),
            "upload_batch_size": int(settings.get("baseline_inventory_upload_batch_size", DEFAULT_BASELINE_UPLOAD_BATCH)),
            "max_hash_file_size": int(settings.get("baseline_inventory_max_hash_file_size", DEFAULT_BASELINE_MAX_HASH_SIZE)),
            "max_parser_file_size": int(settings.get("baseline_inventory_max_parser_file_size", DEFAULT_BASELINE_MAX_PARSER_SIZE)),
            "max_ocr_file_size": int(settings.get("baseline_inventory_max_ocr_file_size", DEFAULT_BASELINE_MAX_OCR_SIZE)),
            "rescan_unchanged_after_seconds": int(settings.get("baseline_inventory_rescan_unchanged_after_seconds", DEFAULT_BASELINE_RESCAN_SECONDS)),
            "mount_discovery_interval_seconds": int(settings.get("baseline_inventory_mount_discovery_interval_seconds", DEFAULT_BASELINE_DISCOVERY_SECONDS)),
        },
    }

