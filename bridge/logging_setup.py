"""Structured JSON logging for the bridge.

- All bridge logs are JSON, emitted both to stderr (visible in `make logs`
  and uvicorn output) and to `logs/bridge.log` (immutable history).
- The audit log is a separate JSONL stream (`logs/audit.jsonl`) — append-only,
  one event per line, no log levels, no formatting. cameleon and ops both
  consume it.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

import structlog

from .config import get_settings


def setup_logging() -> structlog.stdlib.BoundLogger:
    settings = get_settings()
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    settings.bridge_log_path.parent.mkdir(parents=True, exist_ok=True)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]

    structlog.configure(
        processors=shared_processors + [structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            structlog.processors.JSONRenderer(),
        ],
    )

    file_handler = logging.FileHandler(settings.bridge_log_path, mode="a", encoding="utf-8")
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(file_handler)
    # In foreground dev (TTY attached) also mirror to stderr for live visibility.
    # In daemon mode (stderr piped to uvicorn.log) skip this to avoid duplication.
    if sys.stderr.isatty():
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)
    root.setLevel(log_level)

    # uvicorn's access log duplicates our middleware log — silence it.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.error").setLevel(log_level)

    return structlog.get_logger("bridge")


def write_audit(record: dict[str, Any]) -> None:
    """Append one JSON event to audit.jsonl (immutable, append-only)."""
    settings = get_settings()
    settings.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(settings.audit_log_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n")
