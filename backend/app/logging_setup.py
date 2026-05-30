"""Structured logging configuration for API and worker processes."""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from app.request_context import get_client_ip, get_request_id, get_service_name, get_trace_id

_configured = False


def _log_level() -> int:
    raw = (os.environ.get("LOG_LEVEL", "INFO").strip().upper() or "INFO")
    return getattr(logging, raw, logging.INFO)


def _log_format() -> str:
    return (os.environ.get("LOG_FORMAT", "plain").strip().lower() or "plain")


def _log_file_path() -> str:
    return os.environ.get("LOG_FILE_PATH", "").strip()


def _resolve_log_file_path() -> Path | None:
    raw = _log_file_path()
    if not raw:
        return None
    requested = Path(raw).expanduser()
    candidates = [
        requested,
        Path.home() / ".cropsentinel" / "logs" / requested.name,
        Path("/tmp/cropsentinel/logs") / requested.name,
    ]
    last_error: Exception | None = None
    for candidate in candidates:
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
            with candidate.open("a", encoding="utf-8"):
                pass
            if candidate != requested:
                logging.getLogger("cropsentinel.logging").warning(
                    "Log file fallback activated: requested=%s fallback=%s",
                    requested,
                    candidate,
                )
            return candidate
        except Exception as exc:
            last_error = exc
    logging.getLogger("cropsentinel.logging").warning(
        "Disabling file logging because no writable target is available for %s: %s",
        requested,
        last_error,
    )
    return None


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = get_request_id()
        record.trace_id = get_trace_id()
        record.client_ip = get_client_ip()
        record.service_name = get_service_name()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", ""),
            "trace_id": getattr(record, "trace_id", ""),
            "client_ip": getattr(record, "client_ip", ""),
            "service_name": getattr(record, "service_name", ""),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=True, separators=(",", ":"))


def _make_formatter() -> logging.Formatter:
    if _log_format() == "json":
        return JsonFormatter()
    return logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s "
        "request_id=%(request_id)s trace_id=%(trace_id)s client_ip=%(client_ip)s service=%(service_name)s"
    )


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    level = _log_level()
    formatter = _make_formatter()
    context_filter = RequestContextFilter()
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.addFilter(context_filter)
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    target = _resolve_log_file_path()
    if target is not None:
        file_handler = logging.FileHandler(target, encoding="utf-8")
        file_handler.setLevel(level)
        file_handler.addFilter(context_filter)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)

    _configured = True
