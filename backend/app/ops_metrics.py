"""Lightweight Prometheus-style metrics for runtime operations."""

from __future__ import annotations

import threading
import time
from collections import defaultdict
from typing import Any

from app.analytics_pipeline import analytics_pipeline
from app.event_bus import internal_event_bus


def _escape_label(value: Any) -> str:
    text = str(value if value is not None else "")
    return text.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _format_labels(labels: dict[str, Any]) -> str:
    if not labels:
        return ""
    rendered = ",".join(f'{key}="{_escape_label(value)}"' for key, value in sorted(labels.items()))
    return "{" + rendered + "}"


class OpsMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._http_request_counts: dict[tuple[str, str, str], int] = defaultdict(int)
        self._http_request_duration_sum: dict[tuple[str, str], float] = defaultdict(float)
        self._http_request_duration_count: dict[tuple[str, str], int] = defaultdict(int)
        self._realtime_agents = 0
        self._realtime_admins = 0
        self._startup_time = time.time()

    def record_http_request(self, *, method: str, path: str, status_code: int, duration_seconds: float) -> None:
        method_name = (method or "GET").upper()
        route = path or "/"
        status = str(int(status_code or 0))
        with self._lock:
            self._http_request_counts[(method_name, route, status)] += 1
            self._http_request_duration_sum[(method_name, route)] += max(0.0, float(duration_seconds))
            self._http_request_duration_count[(method_name, route)] += 1

    def set_realtime_counts(self, *, agents: int, admins: int) -> None:
        with self._lock:
            self._realtime_agents = max(0, int(agents))
            self._realtime_admins = max(0, int(admins))

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "uptime_seconds": max(0.0, time.time() - self._startup_time),
                "http_request_counts": dict(self._http_request_counts),
                "http_request_duration_sum": dict(self._http_request_duration_sum),
                "http_request_duration_count": dict(self._http_request_duration_count),
                "realtime_agents": self._realtime_agents,
                "realtime_admins": self._realtime_admins,
            }

    def reset(self) -> None:
        with self._lock:
            self._http_request_counts.clear()
            self._http_request_duration_sum.clear()
            self._http_request_duration_count.clear()
            self._realtime_agents = 0
            self._realtime_admins = 0
            self._startup_time = time.time()

    def render_prometheus_text(self, *, backup_status: dict[str, Any] | None = None) -> str:
        snapshot = self.snapshot()
        event_bus_status = internal_event_bus.status()
        analytics_status = analytics_pipeline.status()
        lines: list[str] = [
            "# HELP cropsentinel_process_uptime_seconds Process uptime in seconds.",
            "# TYPE cropsentinel_process_uptime_seconds gauge",
            f"cropsentinel_process_uptime_seconds {snapshot['uptime_seconds']:.3f}",
            "# HELP cropsentinel_http_requests_total Total HTTP requests seen by edge middleware.",
            "# TYPE cropsentinel_http_requests_total counter",
        ]
        for (method, path, status), value in sorted(snapshot["http_request_counts"].items()):
            lines.append(
                f"cropsentinel_http_requests_total{_format_labels({'method': method, 'path': path, 'status': status})} {value}"
            )
        lines.extend(
            [
                "# HELP cropsentinel_http_request_duration_seconds_sum Total request duration by method and path.",
                "# TYPE cropsentinel_http_request_duration_seconds_sum counter",
            ]
        )
        for (method, path), value in sorted(snapshot["http_request_duration_sum"].items()):
            lines.append(
                f"cropsentinel_http_request_duration_seconds_sum{_format_labels({'method': method, 'path': path})} {value:.6f}"
            )
        lines.extend(
            [
                "# HELP cropsentinel_http_request_duration_seconds_count Request samples by method and path.",
                "# TYPE cropsentinel_http_request_duration_seconds_count counter",
            ]
        )
        for (method, path), value in sorted(snapshot["http_request_duration_count"].items()):
            lines.append(
                f"cropsentinel_http_request_duration_seconds_count{_format_labels({'method': method, 'path': path})} {value}"
            )
        lines.extend(
            [
                "# HELP cropsentinel_realtime_online_agents Connected agent WebSockets.",
                "# TYPE cropsentinel_realtime_online_agents gauge",
                f"cropsentinel_realtime_online_agents {int(snapshot['realtime_agents'])}",
                "# HELP cropsentinel_realtime_online_admins Connected admin WebSockets.",
                "# TYPE cropsentinel_realtime_online_admins gauge",
                f"cropsentinel_realtime_online_admins {int(snapshot['realtime_admins'])}",
                "# HELP cropsentinel_event_bus_queue_depth Pending internal event queue depth.",
                "# TYPE cropsentinel_event_bus_queue_depth gauge",
                f"cropsentinel_event_bus_queue_depth {int(event_bus_status.get('queue_depth', 0) or 0)}",
                "# HELP cropsentinel_event_bus_published_total Internal events published.",
                "# TYPE cropsentinel_event_bus_published_total counter",
                f"cropsentinel_event_bus_published_total {int(event_bus_status.get('published_count', 0) or 0)}",
                "# HELP cropsentinel_event_bus_failed_total Internal event publish failures.",
                "# TYPE cropsentinel_event_bus_failed_total counter",
                f"cropsentinel_event_bus_failed_total {int(event_bus_status.get('failed_count', 0) or 0)}",
                "# HELP cropsentinel_event_bus_subscriber_delivery_total Local subscriber deliveries.",
                "# TYPE cropsentinel_event_bus_subscriber_delivery_total counter",
                f"cropsentinel_event_bus_subscriber_delivery_total {int(event_bus_status.get('subscriber_delivery_count', 0) or 0)}",
                "# HELP cropsentinel_analytics_queue_depth Pending analytics rows waiting for ClickHouse flush.",
                "# TYPE cropsentinel_analytics_queue_depth gauge",
                f"cropsentinel_analytics_queue_depth {int(analytics_status.get('queue_depth', 0) or 0)}",
                "# HELP cropsentinel_analytics_published_total Analytics rows flushed successfully.",
                "# TYPE cropsentinel_analytics_published_total counter",
                f"cropsentinel_analytics_published_total {int(analytics_status.get('published', 0) or 0)}",
                "# HELP cropsentinel_analytics_failed_total Analytics rows that failed to flush.",
                "# TYPE cropsentinel_analytics_failed_total counter",
                f"cropsentinel_analytics_failed_total {int(analytics_status.get('failed', 0) or 0)}",
                "# HELP cropsentinel_analytics_read_enabled Whether ClickHouse-powered analytics reads are enabled.",
                "# TYPE cropsentinel_analytics_read_enabled gauge",
                f"cropsentinel_analytics_read_enabled {1 if analytics_status.get('read_enabled') else 0}",
            ]
        )
        if backup_status:
            lines.extend(
                [
                    "# HELP cropsentinel_backup_target_enabled Whether backups are configured for a target.",
                    "# TYPE cropsentinel_backup_target_enabled gauge",
                ]
            )
            for target, payload in sorted((backup_status.get("targets") or {}).items()):
                lines.append(
                    f"cropsentinel_backup_target_enabled{_format_labels({'target': target})} {1 if payload.get('enabled') else 0}"
                )
            last_success = backup_status.get("last_success") or {}
            if last_success:
                lines.extend(
                    [
                        "# HELP cropsentinel_backup_last_success_timestamp_seconds Last successful backup timestamp per target.",
                        "# TYPE cropsentinel_backup_last_success_timestamp_seconds gauge",
                    ]
                )
                for target, value in sorted(last_success.items()):
                    lines.append(
                        f"cropsentinel_backup_last_success_timestamp_seconds{_format_labels({'target': target})} {float(value):.3f}"
                    )
        return "\n".join(lines) + "\n"


ops_metrics = OpsMetrics()
