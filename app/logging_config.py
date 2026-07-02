"""Structured logging helpers that omit private CV/JD content and secrets."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from app.config import SECRET_NAME_MARKERS, Settings


PRIVATE_CONTENT_MARKERS = (
    "CV_TEXT",
    "JOB_DESCRIPTION",
    "JD_TEXT",
    "PROFILE_DATA",
    "SOURCE_PAYLOAD",
    "RAW_PAYLOAD",
)


def sanitize_log_context(context: dict[str, Any]) -> dict[str, Any]:
    """Redact secrets and omit full private document payloads."""
    safe: dict[str, Any] = {}
    for name, value in context.items():
        upper_name = name.upper()
        if any(marker in upper_name for marker in SECRET_NAME_MARKERS):
            safe[name] = "***REDACTED***"
        elif any(marker in upper_name for marker in PRIVATE_CONTENT_MARKERS):
            safe[name] = "[OMITTED]"
        elif isinstance(value, (str, int, float, bool)) or value is None:
            safe[name] = value
        else:
            safe[name] = str(value)
    return safe


class StructuredJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        event = getattr(record, "event", None)
        context = getattr(record, "context", None)
        if event:
            payload["event"] = event
        if isinstance(context, dict):
            payload["context"] = sanitize_log_context(context)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(settings: Settings) -> None:
    """Configure the process root logger without logging configuration values."""
    handler = logging.StreamHandler()
    if settings.log_json:
        handler.setFormatter(StructuredJsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(settings.log_level.upper())


def log_event(logger: logging.Logger, event: str, message: str, **context: Any) -> None:
    logger.info(
        message,
        extra={"event": event, "context": sanitize_log_context(context)},
    )

