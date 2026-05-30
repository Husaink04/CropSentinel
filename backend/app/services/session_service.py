"""Session capability, authorization, and remote-command validation."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from app.core import can_access_machine, has_permission
from database import db

SESSION_KIND_PERMISSIONS = {
    "live": "screenshots.view",
    "remote": "remote.access",
}

ALLOWED_REMOTE_COMMANDS: dict[str, dict[str, Any]] = {
    "lock_screen": {"needs_value": False, "max_length": 0},
    "show_message": {"needs_value": True, "max_length": 500},
    "open_url": {"needs_value": True, "max_length": 2048},
    "mute_audio": {"needs_value": False, "max_length": 0},
    "unmute_audio": {"needs_value": False, "max_length": 0},
    "sleep": {"needs_value": False, "max_length": 0},
    "logout_user": {"needs_value": False, "max_length": 0},
    "ctrl_alt_del": {"needs_value": False, "max_length": 0},
}


def normalize_session_kind(kind: str) -> str:
    value = str(kind or "live").strip().lower()
    return value if value in SESSION_KIND_PERMISSIONS else "live"


def require_session_access(user: dict, machine_id: str, session_kind: str) -> str:
    kind = normalize_session_kind(session_kind)
    if not can_access_machine(user, machine_id):
        raise HTTPException(status_code=403, detail="No access to this machine")
    perm = SESSION_KIND_PERMISSIONS[kind]
    if not has_permission(user, perm):
        raise HTTPException(status_code=403, detail=f"Permission denied: {perm}")
    return kind


def sanitize_remote_command(action: str, value: str) -> tuple[str, str]:
    normalized_action = str(action or "").strip().lower()
    spec = ALLOWED_REMOTE_COMMANDS.get(normalized_action)
    if not spec:
        raise HTTPException(status_code=400, detail="Unsupported remote command")
    normalized_value = str(value or "").strip()
    if spec["needs_value"] and not normalized_value:
        raise HTTPException(status_code=400, detail="Command value is required")
    if spec["max_length"] and len(normalized_value) > int(spec["max_length"]):
        raise HTTPException(status_code=400, detail="Command value is too long")
    if normalized_action == "open_url":
        lowered = normalized_value.lower()
        if not (lowered.startswith("http://") or lowered.startswith("https://")):
            raise HTTPException(status_code=400, detail="URL must start with http:// or https://")
    return normalized_action, normalized_value


def session_capabilities(user: dict, machine_id: str, *, remote_access_licensed: bool) -> dict:
    machine = db.get_machine(machine_id)
    if not machine:
        raise HTTPException(status_code=404, detail="Machine not found")
    if not can_access_machine(user, machine_id):
        raise HTTPException(status_code=403, detail="No access to this machine")
    can_live = has_permission(user, "screenshots.view")
    can_remote = has_permission(user, "remote.access") and remote_access_licensed
    return {
        "machine_id": machine_id,
        "hostname": machine.get("hostname", machine_id),
        "online": bool(machine.get("online")),
        "supports": {
            "live_webrtc": can_live,
            "live_jpeg_fallback": can_live,
            "remote_control": can_remote,
            "remote_audio": can_remote,
            "file_transfer": can_remote,
        },
        "permissions": {
            "can_view_screenshots": can_live,
            "can_start_live_session": can_live,
            "can_start_remote_session": can_remote,
            "can_send_remote_command": can_remote,
        },
        "remote_commands": sorted(ALLOWED_REMOTE_COMMANDS.keys()) if can_remote else [],
        "session_kinds": [kind for kind, perm in SESSION_KIND_PERMISSIONS.items() if has_permission(user, perm)],
    }
