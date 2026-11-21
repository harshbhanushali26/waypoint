"""
core/logging.py

Single place that configures Python's logging system for the whole app.
This does NOT create any loggers itself — every module (agents, tools,
routers) already does `logger = logging.getLogger(__name__)` and just
emits records. Python's logging hierarchy means those module-level loggers
automatically forward their records up to the root logger, so configuring
handlers/formatters HERE, once, makes every existing logger call in the
codebase start actually producing output — console + file — with zero
changes needed in those files.

Call setup_logging() exactly once, in api/main.py, before the FastAPI app
is constructed.
"""

import os
import logging
import logging.handlers
from pathlib import Path

# Where log files live. Kept outside the repo's tracked files via .gitignore
# (add "logs/" there) since logs are runtime output, not source.
LOG_DIR = Path("logs")
LOG_FILE = LOG_DIR / "waypoint.log"

# Rotation settings: once waypoint.log hits 5MB, it's renamed to
# waypoint.log.1 and a fresh waypoint.log starts. backupCount=3 keeps
# up to 3 old rotated files before the oldest is deleted. Size-based
# (not time-based) because this is a low-traffic personal project —
# rotating by day would leave mostly-empty files most days.
MAX_BYTES = 5 * 1024 * 1024  # 5MB
BACKUP_COUNT = 3


class DefaultTripIdFilter(logging.Filter):
    """
    Ensures every log record has a `trip_id` attribute before it hits the
    formatter, even if the code that logged it never attached one.

    Why this is needed: the format string below references %(trip_id)s.
    Agent/tool nodes will log through a LoggerAdapter that injects the
    real trip_id (see get_trip_logger() below), but plenty of log lines
    happen outside any trip's context entirely — app startup, config
    loading, a router handling a non-trip request. Without this filter,
    those lines would crash the formatter with a KeyError instead of
    just printing something reasonable.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "trip_id"):
            record.trip_id = "-"
        return True  # always let the record through; this filter only enriches it


def setup_logging(level: int | None = None) -> None:
    """
    Configure the root logger with a console handler and a rotating file handler.
    Call once at app startup (api/main.py).

    Level comes from the LOG_LEVEL env var (default INFO). Use LOG_LEVEL=DEBUG
    for local debugging only: DEBUG logs full prompts.
    """
    root_logger = logging.getLogger()
    if getattr(root_logger, "_waypoint_configured", False):
        return   # already configured (reload or repeated call)

    if level is None:
        level = getattr(logging, os.getenv("LOG_LEVEL", "INFO").upper(), logging.INFO)

    LOG_DIR.mkdir(exist_ok=True)

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s [trip:%(trip_id)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    trip_id_filter = DefaultTripIdFilter()

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(trip_id_filter)

    file_handler = logging.handlers.RotatingFileHandler(
        filename=LOG_FILE,
        maxBytes=MAX_BYTES,
        backupCount=BACKUP_COUNT,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(trip_id_filter)

    root_logger.setLevel(level)
    root_logger.addHandler(console_handler)
    root_logger.addHandler(file_handler)
    root_logger._waypoint_configured = True

    # Library loggers log full request URLs (httpx logs API keys in query strings)
    # and full prompts (groq at DEBUG). Keep them quiet whatever the app level is.
    for noisy in ("httpx", "httpcore", "groq", "openai", "urllib3", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_trip_logger(logger: logging.Logger, trip_id: str) -> logging.LoggerAdapter:
    """
    Wrap a module's logger so every log call it makes automatically carries
    the given trip_id, without having to pass trip_id into every log call
    by hand.

    Usage inside a node function (agent or tool):
        logger = logging.getLogger(__name__)          # already exists today
        log = get_trip_logger(logger, state["trip_id"])  # new: one extra line
        log.info("Starting search")                   # trip_id attached automatically
    """
    return logging.LoggerAdapter(logger, {"trip_id": trip_id})