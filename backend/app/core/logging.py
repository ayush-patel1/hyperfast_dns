from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        payload.update(getattr(record, "ctx", {}))
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level)


class LogEntry(BaseModel):
    ts: datetime = Field(default_factory=lambda: datetime.now(UTC))
    level: str
    stage: str
    message: str
    context: dict[str, Any] = Field(default_factory=dict)


class RunLogger:
    """Collects a run's structured log lines (later served to the agent's log tool) and mirrors them to stdlib logging."""

    def __init__(self, logger_name: str, **base_ctx: Any) -> None:
        self._logger = logging.getLogger(logger_name)
        self._base = base_ctx
        self.entries: list[LogEntry] = []

    def _emit(self, level: int, stage: str, message: str, **ctx: Any) -> None:
        entry = LogEntry(level=logging.getLevelName(level), stage=stage, message=message, context=ctx)
        self.entries.append(entry)
        self._logger.log(level, message, extra={"ctx": {**self._base, "stage": stage, **ctx}})

    def info(self, stage: str, message: str, **ctx: Any) -> None:
        self._emit(logging.INFO, stage, message, **ctx)

    def warning(self, stage: str, message: str, **ctx: Any) -> None:
        self._emit(logging.WARNING, stage, message, **ctx)

    def error(self, stage: str, message: str, **ctx: Any) -> None:
        self._emit(logging.ERROR, stage, message, **ctx)
