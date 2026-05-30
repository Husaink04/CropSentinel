"""App lifespan and startup initialization."""

import asyncio
import logging
import os
from contextlib import asynccontextmanager

import redis_bus
from database import db
from licensing import LicenseError, SeatEnforcer, load_and_verify_license
from passwords import hash_password
from app.analytics_pipeline import analytics_pipeline
from app.core import expected_agent_api_key
from app.event_bus import internal_event_bus
from app.event_workers import internal_event_workers
from app.repos.settings_repo import settings_repo
from app.repos.user_repo import user_repo
from app.service_roles import (
    enables_analytics_pipeline,
    enables_event_workers,
    enables_redis_fanout,
    owns_schema_management,
    role_name,
    runs_startup_backfill,
    runs_startup_seeding,
)
from app.ws_service import manager

logger = logging.getLogger("croppro")

DEFAULT_SETTINGS = {
    "company_name": "CropSentinel",
    "company_logo": "",
    "screenshot_interval": int(os.environ.get("DEFAULT_SCREENSHOT_INTERVAL", "180")),
    "activity_sync_interval": int(os.environ.get("DEFAULT_ACTIVITY_SYNC_INTERVAL", "60")),
    "heartbeat_interval_seconds": int(os.environ.get("DEFAULT_HEARTBEAT_INTERVAL_SECONDS", "30")),
    "app_tracker_interval_seconds": int(os.environ.get("DEFAULT_APP_TRACKER_INTERVAL_SECONDS", "10")),
    "network_interval_seconds": int(os.environ.get("DEFAULT_NETWORK_INTERVAL_SECONDS", "60")),
    "usb_interval_seconds": int(os.environ.get("DEFAULT_USB_INTERVAL_SECONDS", "10")),
    "print_interval_seconds": int(os.environ.get("DEFAULT_PRINT_INTERVAL_SECONDS", "20")),
    "file_cache_fast_sweep_seconds": float(os.environ.get("DEFAULT_FILE_CACHE_FAST_SWEEP_SECONDS", "10")),
    "file_cache_recursive_sweep_seconds": float(os.environ.get("DEFAULT_FILE_CACHE_RECURSIVE_SWEEP_SECONDS", "120")),
    "file_cache_sweeper_enabled": os.environ.get("DEFAULT_FILE_CACHE_SWEEPER_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"},
    "agent_self_throttle_enabled": os.environ.get("DEFAULT_AGENT_SELF_THROTTLE_ENABLED", "1").strip().lower() not in {"0", "false", "no", "off"},
    "agent_self_throttle_cpu_percent": int(os.environ.get("DEFAULT_AGENT_SELF_THROTTLE_CPU_PERCENT", "85")),
    "agent_self_throttle_memory_percent": int(os.environ.get("DEFAULT_AGENT_SELF_THROTTLE_MEMORY_PERCENT", "80")),
    "agent_self_throttle_queue_depth": int(os.environ.get("DEFAULT_AGENT_SELF_THROTTLE_QUEUE_DEPTH", "500")),
    "agent_self_throttle_multiplier": float(os.environ.get("DEFAULT_AGENT_SELF_THROTTLE_MULTIPLIER", "2.0")),
    "agent_self_throttle_cooldown_seconds": int(os.environ.get("DEFAULT_AGENT_SELF_THROTTLE_COOLDOWN_SECONDS", "300")),
    "productive_apps": ["vscode", "excel", "word", "figma", "terminal"],
    "productive_domains": ["github.com", "stackoverflow.com", "docs.google.com"],
    "unproductive_domains": ["youtube.com", "facebook.com", "twitter.com", "instagram.com", "reddit.com"],
    "productivity_apps": [
        {"match_value": "vscode", "match_type": "contains", "category": "productive", "weight": 1.0, "always_active": False},
        {"match_value": "excel", "match_type": "contains", "category": "productive", "weight": 1.0, "always_active": False},
        {"match_value": "word", "match_type": "contains", "category": "productive", "weight": 1.0, "always_active": False},
        {"match_value": "figma", "match_type": "contains", "category": "productive", "weight": 1.0, "always_active": False},
        {"match_value": "terminal", "match_type": "contains", "category": "productive", "weight": 1.0, "always_active": False},
        {"match_value": "teams", "match_type": "contains", "category": "supportive", "weight": 0.8, "always_active": True},
        {"match_value": "zoom", "match_type": "contains", "category": "supportive", "weight": 0.8, "always_active": True},
        {"match_value": "slack", "match_type": "contains", "category": "supportive", "weight": 0.75, "always_active": True},
        {"match_value": "chatgpt", "match_type": "contains", "category": "supportive", "weight": 0.7, "always_active": False},
        {"match_value": "claude", "match_type": "contains", "category": "supportive", "weight": 0.7, "always_active": False},
    ],
    "productivity_domains": [
        {"match_value": "github.com", "match_type": "contains", "category": "productive", "weight": 1.0, "always_active": False},
        {"match_value": "stackoverflow.com", "match_type": "contains", "category": "productive", "weight": 1.0, "always_active": False},
        {"match_value": "docs.google.com", "match_type": "contains", "category": "supportive", "weight": 0.72, "always_active": False},
        {"match_value": "meet.google.com", "match_type": "contains", "category": "supportive", "weight": 0.8, "always_active": True},
        {"match_value": "youtube.com", "match_type": "contains", "category": "distracting", "weight": 0.0, "always_active": False},
        {"match_value": "facebook.com", "match_type": "contains", "category": "distracting", "weight": 0.0, "always_active": False},
        {"match_value": "reddit.com", "match_type": "contains", "category": "distracting", "weight": 0.0, "always_active": False},
    ],
    "productivity_categories": {"productive": 1.0, "supportive": 0.72, "neutral": 0.35, "distracting": 0.0, "excluded": 0.0},
    "meeting_like_apps": [
        {"match_value": "teams", "match_type": "contains", "category": "supportive", "weight": 0.8, "always_active": True},
        {"match_value": "zoom", "match_type": "contains", "category": "supportive", "weight": 0.8, "always_active": True},
        {"match_value": "meet", "match_type": "contains", "category": "supportive", "weight": 0.8, "always_active": True},
    ],
    "ai_work_assist_apps_or_domains": ["chatgpt", "claude", "gemini", "copilot", "cursor", "perplexity"],
    "productivity_policy_version": 1,
    "track_screenshots": os.environ.get("DEFAULT_TRACK_SCREENSHOTS", "0").strip().lower() in {"1", "true", "yes", "on"},
    "track_browser": os.environ.get("DEFAULT_TRACK_BROWSER", "1").strip().lower() not in {"0", "false", "no", "off"},
    "track_applications": os.environ.get("DEFAULT_TRACK_APPLICATIONS", "1").strip().lower() not in {"0", "false", "no", "off"},
    "track_input_activity": os.environ.get("DEFAULT_TRACK_INPUT_ACTIVITY", "0").strip().lower() in {"1", "true", "yes", "on"},
    "input_bucket_seconds": int(os.environ.get("DEFAULT_INPUT_BUCKET_SECONDS", "30")),
    "baseline_inventory_enabled": os.environ.get("DEFAULT_BASELINE_INVENTORY_ENABLED", "0").strip().lower() in {"1", "true", "yes", "on"},
    "baseline_inventory_worker_count": int(os.environ.get("DEFAULT_BASELINE_INVENTORY_WORKER_COUNT", "1")),
    "baseline_inventory_io_throttle_seconds": float(os.environ.get("DEFAULT_BASELINE_INVENTORY_IO_THROTTLE_SECONDS", "0.05")),
    "baseline_inventory_upload_interval_seconds": int(os.environ.get("DEFAULT_BASELINE_INVENTORY_UPLOAD_INTERVAL_SECONDS", "60")),
    "baseline_inventory_upload_batch_size": int(os.environ.get("DEFAULT_BASELINE_INVENTORY_UPLOAD_BATCH_SIZE", "100")),
    "baseline_inventory_max_hash_file_size": int(os.environ.get("DEFAULT_BASELINE_INVENTORY_MAX_HASH_FILE_SIZE", "0")),
    "baseline_inventory_max_parser_file_size": int(os.environ.get("DEFAULT_BASELINE_INVENTORY_MAX_PARSER_FILE_SIZE", str(25 * 1024 * 1024))),
    "baseline_inventory_max_ocr_file_size": int(os.environ.get("DEFAULT_BASELINE_INVENTORY_MAX_OCR_FILE_SIZE", str(10 * 1024 * 1024))),
    "baseline_inventory_rescan_unchanged_after_seconds": int(os.environ.get("DEFAULT_BASELINE_INVENTORY_RESCAN_UNCHANGED_AFTER_SECONDS", str(24 * 3600))),
    "baseline_inventory_mount_discovery_interval_seconds": int(os.environ.get("DEFAULT_BASELINE_INVENTORY_MOUNT_DISCOVERY_INTERVAL_SECONDS", "300")),
}


def _startup_binary_backfill_limit() -> int:
    try:
        return max(0, int(os.environ.get("STARTUP_BINARY_BACKFILL_LIMIT", "100")))
    except ValueError:
        return 100


@asynccontextmanager
async def lifespan(app):
    service_role = role_name(getattr(app.state, "service_role", None))
    schema_owner = owns_schema_management(service_role)
    app.state.schema_init_enabled = schema_owner
    logger.info(
        "Service startup role=%s schema_init_enabled=%s route_families=%s",
        service_role,
        schema_owner,
        list(getattr(app.state, "route_families", ()) or []),
    )
    enforce = os.environ.get("CROPPRO_LICENSE_ENFORCE", "1") != "0"
    try:
        app.state.license = load_and_verify_license()
        logger.info(
            "License OK: %s (%s) - %d seats, %d days remaining",
            app.state.license.customer,
            app.state.license.tier,
            app.state.license.max_seats,
            app.state.license.days_remaining(),
        )
        if app.state.license.is_in_grace():
            logger.warning("License is in grace period - renew immediately.")
    except LicenseError as exc:
        if enforce:
            logger.error("LICENSE CHECK FAILED: %s", exc)
            raise SystemExit(1)
        logger.warning("CROPPRO_LICENSE_ENFORCE=0 - running without a valid license: %s", exc)
        app.state.license = None

    app.state.seat_enforcer = SeatEnforcer(
        db=db,
        license_info_provider=lambda: getattr(app.state, "license", None),
    )

    if schema_owner:
        db.init_db()
    else:
        db.ping()

    settings = settings_repo.get() if schema_owner else {}
    if runs_startup_seeding(service_role):
        missing_defaults = {key: value for key, value in DEFAULT_SETTINGS.items() if key not in settings}
        if missing_defaults:
            settings_repo.update(missing_defaults)
            settings.update(missing_defaults)

        if not settings.get("agent_stop_password_hash"):
            default_stop_pw = os.environ.get("DEFAULT_AGENT_STOP_PASSWORD", "") or "StopAgent@CropPro"
            settings_repo.update(
                {
                    "agent_stop_password_hash": hash_password(default_stop_pw),
                }
            )

        if user_repo.count_by_role("admin") == 0:
            default_username = os.environ.get("DEFAULT_ADMIN_USERNAME", "").strip() or "admin"
            default_pw = os.environ.get("DEFAULT_ADMIN_PASSWORD", "") or "Admin@CropPro2024"
            user_repo.create(
                {
                    "username": default_username,
                    "password_hash": hash_password(default_pw),
                    "display_name": "Administrator",
                    "role": "admin",
                    "active": True,
                    "created_by": "system",
                }
            )

        if not db.get_alert_rules():
            for rule in [
                {"name": "High CPU Usage", "rule_type": "system", "condition": "cpu_percent_gt", "threshold": "85", "severity": "high", "enabled": True},
                {"name": "Unproductive Site", "rule_type": "browser", "condition": "domain_in_blacklist", "threshold": "", "severity": "medium", "enabled": True},
                {"name": "Long Idle Period", "rule_type": "idle", "condition": "idle_seconds_gt", "threshold": "1800", "severity": "low", "enabled": True},
                {"name": "After-Hours Activity", "rule_type": "schedule", "condition": "outside_hours", "threshold": "09:00-19:00", "severity": "medium", "enabled": False},
                {"name": "Machine Offline", "rule_type": "connectivity", "condition": "machine_offline", "threshold": "", "severity": "high", "enabled": True},
            ]:
                db.create_alert_rule({**rule, "description": "", "machine_id": "all"})

    if not expected_agent_api_key():
        env = os.environ.get("ENV", os.environ.get("ENVIRONMENT", "")).lower()
        if env in ("production", "prod"):
            raise RuntimeError("AGENT_API_KEY is required when ENV=production.")
        logger.warning("AGENT_API_KEY not set - agents can connect without authentication.")

    backfill_limit = _startup_binary_backfill_limit()
    if runs_startup_backfill(service_role) and backfill_limit > 0:
        try:
            migrated = db.backfill_legacy_binary_evidence(limit=backfill_limit)
            if migrated["screenshots"] or migrated["deleted_backups"]:
                logger.info(
                    "Backfilled legacy binary evidence: screenshots=%s deleted_backups=%s",
                    migrated["screenshots"],
                    migrated["deleted_backups"],
                )
        except Exception as exc:
            logger.warning("Legacy binary backfill failed: %s", exc)

    redis_task = None
    if enables_redis_fanout(service_role):
        redis_task = asyncio.create_task(
            redis_bus.subscribe_loop(
                on_broadcast=manager._local_broadcast,
                on_agent_cmd=manager._local_deliver_to_agent,
            )
        )
    if enables_event_workers(service_role):
        await internal_event_workers.start()
    await internal_event_bus.start()
    if enables_analytics_pipeline(service_role):
        await analytics_pipeline.start()
    try:
        yield
    finally:
        if enables_analytics_pipeline(service_role):
            await analytics_pipeline.stop()
        if enables_event_workers(service_role):
            await internal_event_workers.stop()
        await internal_event_bus.stop()
        if redis_task is not None:
            redis_task.cancel()
            try:
                await redis_task
            except asyncio.CancelledError:
                pass
