"""Operational status helpers for backup/restore and disaster recovery metadata."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _bool_env(name: str, default: str = "1") -> bool:
    return (os.environ.get(name, default).strip().lower() or default) in {"1", "true", "yes", "on"}


def _status_file() -> Path:
    raw = os.environ.get("BACKUP_STATUS_FILE", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path(__file__).resolve().parents[1] / "storage" / "ops" / "backup-status.json").resolve()


def _retention_days() -> int:
    try:
        return max(1, int(os.environ.get("BACKUP_RETENTION_DAYS", "14")))
    except ValueError:
        return 14


def _safe_load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _iso_to_epoch(value: str) -> float:
    try:
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized).timestamp()
    except Exception:
        return 0.0


def backup_runtime_status() -> dict[str, Any]:
    path = _status_file()
    raw = _safe_load_json(path)
    targets = {
        "postgres": {"enabled": _bool_env("BACKUP_POSTGRES_ENABLED", "1")},
        "redis": {"enabled": _bool_env("BACKUP_REDIS_ENABLED", "1")},
        "object_storage": {"enabled": _bool_env("BACKUP_OBJECT_STORAGE_ENABLED", "1")},
        "clickhouse": {"enabled": _bool_env("BACKUP_CLICKHOUSE_ENABLED", "1")},
    }
    last_success: dict[str, float] = {}
    latest_targets = raw.get("targets") if isinstance(raw.get("targets"), dict) else {}
    for target, meta in latest_targets.items():
        if isinstance(meta, dict) and meta.get("last_success_at"):
            last_success[target] = _iso_to_epoch(str(meta.get("last_success_at")))
    return {
        "status_file": str(path),
        "retention_days": _retention_days(),
        "dr": {
            "rto_minutes": int(os.environ.get("DR_TARGET_RTO_MINUTES", "30") or 30),
            "rpo_minutes": int(os.environ.get("DR_TARGET_RPO_MINUTES", "5") or 5),
            "cross_region_enabled": _bool_env("DR_CROSS_REGION_ENABLED", "0"),
        },
        "targets": targets,
        "latest_run": raw,
        "last_success": last_success,
    }
