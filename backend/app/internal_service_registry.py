"""Internal service boundary catalog for staged service extraction."""

from __future__ import annotations


SERVICE_CATALOG = {
    "agent-control": {
        "display_name": "Agent Control Service",
        "domain": "registration, heartbeat, config delivery, versioning, online state",
        "internal_prefix": "/_internal/services/agent-control",
        "public_contracts": [
            "/api/machines/register",
            "/api/activity/heartbeat",
        ],
        "websocket_contracts": [
            "/ws/agent/{machine_id}",
        ],
        "event_topics": [
            "agent.events",
            "system.events",
        ],
    },
    "monitoring": {
        "display_name": "Monitoring Ingest Service",
        "domain": "browser, app, screenshot, input, file, network, phishing and batch ingest",
        "internal_prefix": "/_internal/services/monitoring",
        "public_contracts": [
            "/api/activity/browser",
            "/api/activity/application",
            "/api/activity/screenshot",
            "/api/activity/input",
            "/api/activity/phishing",
            "/api/activity/batch",
        ],
        "event_topics": [
            "activity.logs",
            "screenshot.events",
            "phishing.events",
            "dlp.events",
        ],
    },
    "realtime": {
        "display_name": "Realtime Session Service",
        "domain": "admin fanout, agent commands, websocket presence, live and remote session signaling",
        "internal_prefix": "/_internal/services/realtime",
        "public_contracts": [
            "/api/sessions/machines/{machine_id}/capabilities",
            "/api/sessions/machines/{machine_id}/start",
            "/ws/admin",
            "/ws/agent/{machine_id}",
        ],
        "event_topics": [
            "system.events",
        ],
    },
}


def service_catalog_snapshot() -> dict[str, dict]:
    return {name: dict(meta) for name, meta in SERVICE_CATALOG.items()}
