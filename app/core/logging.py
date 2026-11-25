import json
import logging
import sys
from pathlib import Path
from types import TracebackType
from typing import Any, Final

from app.core.config import get_settings

LOG_NAME: Final = "counting_down"

settings = get_settings()

# Structured fields that may appear in log output when passed through ``extra``. Anything else is
# dropped, so identifiers and counters are logged but free-form content (prompts, generated text,
# provider response bodies, secrets) can never leak through ``extra`` by accident.
LOG_FIELDS: Final = frozenset(
    {
        "event",
        "job_kind",
        "job_kinds",
        "requested_kinds",
        "outcome",
        "error_type",
        "error_location",
        "duration_ms",
        "processed",
        "failed",
        "timed_out",
        "processed_total",
        "terminal",
        "terminal_total",
        "failed_total",
        "timed_out_total",
        "routine_id",
        "delivery_id",
    }
)
_APP_ROOT = Path(__file__).resolve().parents[1]


def error_fields(exc: BaseException) -> dict[str, str]:
    """Describe an exception without its message.

    Exception messages can carry provider response bodies or user content, so job logs record
    only the type and the innermost application frame where it was raised.
    """
    location = "unknown"
    tb: TracebackType | None = exc.__traceback__
    while tb is not None:
        path = Path(tb.tb_frame.f_code.co_filename)
        if path.is_relative_to(_APP_ROOT):
            location = f"{path.relative_to(_APP_ROOT.parent)}:{tb.tb_lineno}"
        tb = tb.tb_next
    return {"error_type": type(exc).__name__, "error_location": location}


def _structured_fields(record: logging.LogRecord) -> dict[str, Any]:
    return {key: value for key, value in vars(record).items() if key in LOG_FIELDS}


class StructuredFormatter(logging.Formatter):
    """Render allowlisted ``extra`` fields, as text (``key=value``) or one JSON object per line."""

    def __init__(self, *, json_output: bool) -> None:
        super().__init__(
            fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        self._json_output = json_output

    def format(self, record: logging.LogRecord) -> str:
        fields = _structured_fields(record)
        if self._json_output:
            payload: dict[str, Any] = {
                "time": self.formatTime(record, self.datefmt),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
                **fields,
            }
            if record.exc_info:
                payload["exception"] = self.formatException(record.exc_info)
            return json.dumps(payload, default=str, separators=(",", ":"))
        text = super().format(record)
        if fields:
            rendered = " ".join(
                f"{key}={json.dumps(value, default=str, separators=(',', ':'))}"
                for key, value in fields.items()
            )
            text = f"{text} | {rendered}"
        return text


def _get_level_from_env() -> int:
    """Return log level, defaulting to INFO. Uses `app_env` for convenience.

    - `prod`  -> INFO
    - `dev`   -> DEBUG
    - other   -> INFO
    """

    env = settings.app_env.lower()
    if env == "dev":
        return logging.DEBUG
    if env == "prod":
        return logging.INFO
    return logging.INFO


def setup_logging() -> logging.Logger:
    """Configure and return the root application logger.

    Idempotent: safe to call multiple times.
    """

    logger = logging.getLogger(LOG_NAME)

    if getattr(logger, "_configured", False):
        return logger

    logger.setLevel(_get_level_from_env())

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter(json_output=settings.log_format == "json"))

    logger.addHandler(handler)
    logger.propagate = False

    # Mark as configured so we don't duplicate handlers.
    logger._configured = True  # type: ignore[attr-defined]

    return logger


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a child logger of the application logger.

    If `name` is None, returns the main application logger.
    """

    app_logger = logging.getLogger(LOG_NAME)
    if name:
        return app_logger.getChild(name)
    return app_logger
