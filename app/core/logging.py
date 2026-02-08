import logging
import sys
from typing import Final

from app.core.config import get_settings

LOG_NAME: Final = "counting_down"

settings = get_settings()


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

    if getattr(logger, "_configured", False):  # type: ignore[attr-defined]
        return logger

    logger.setLevel(_get_level_from_env())

    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(formatter)

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
