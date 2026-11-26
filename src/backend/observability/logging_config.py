"""Structured JSON logging with UTC+7 timestamps and request_id ContextVar."""

from __future__ import annotations

import json
import logging
import sys
from contextlib import contextmanager
from contextvars import ContextVar, Token
from datetime import datetime, timedelta, timezone
from typing import Any, Iterator, TextIO

VN_TZ = timezone(timedelta(hours=7))

_REQUEST_ID_CTX: ContextVar[str | None] = ContextVar(
    "datn2_request_id",
    default=None,
)

_STANDARD_RECORD_ATTRS = frozenset(logging.makeLogRecord({}).__dict__.keys()) | {
    "message",
    "asctime",
    "extra_fields",
    "request_id",
}


def get_request_id() -> str | None:
    """Return the current request correlation ID from contextvars."""
    return _REQUEST_ID_CTX.get()


def bind_request_id(req_id: str | None) -> Token[str | None]:
    """Bind request_id into the current execution context and return reset token."""
    return _REQUEST_ID_CTX.set(req_id)


def reset_request_id(token: Token[str | None]) -> None:
    """Restore the previous request_id using a ContextVar token."""
    _REQUEST_ID_CTX.reset(token)


@contextmanager
def request_id_context(req_id: str | None) -> Iterator[str | None]:
    """Scope a request_id to a block and always restore the prior value."""
    token = bind_request_id(req_id)
    try:
        yield req_id
    finally:
        reset_request_id(token)


class JsonFormatter(logging.Formatter):
    """Format LogRecord instances as single-line JSON strings."""

    def format(self, record: logging.LogRecord) -> str:
        timestamp = datetime.fromtimestamp(record.created, tz=VN_TZ).isoformat(
            timespec="milliseconds"
        )
        req_id = getattr(record, "request_id", None)
        if req_id is None:
            req_id = get_request_id()

        payload: dict[str, Any] = {
            "timestamp": timestamp,
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": req_id,
        }

        extra_fields = self._extract_extra_fields(record)
        if extra_fields:
            payload["extra_fields"] = extra_fields

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)

    @staticmethod
    def _extract_extra_fields(record: logging.LogRecord) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        explicit = getattr(record, "extra_fields", None)
        if isinstance(explicit, dict):
            merged.update(explicit)
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRS and not key.startswith("_"):
                merged[key] = value
        return merged


def configure_logging(
    level: str | int = "INFO",
    stream: TextIO | None = None,
    logger_name: str | None = None,
) -> logging.Logger:
    """Configure JSON structured logging cleanly and idempotently."""
    target = logging.getLogger(logger_name)
    resolved_level = (
        getattr(logging, level.upper(), logging.INFO)
        if isinstance(level, str)
        else level
    )
    target.setLevel(resolved_level)

    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setLevel(resolved_level)
    handler.setFormatter(JsonFormatter())
    handler._datn2_json_handler = True  # type: ignore[attr-defined]

    target.handlers = [
        h
        for h in target.handlers
        if not getattr(h, "_datn2_json_handler", False)
    ]
    target.addHandler(handler)

    if logger_name is not None:
        target.propagate = False
    return target
