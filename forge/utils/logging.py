"""Structured logging setup."""

from __future__ import annotations

import logging
import sys

import structlog


def configure_logging(verbose: bool = False) -> None:
    """Configure application logging once for CLI execution."""
    # Non-verbose mode uses WARNING to suppress model telemetry (INFO-level) from stderr.
    level = logging.DEBUG if verbose else logging.WARNING
    logging.basicConfig(format="%(message)s", level=level, stream=sys.stderr)
    logging.getLogger().setLevel(level)
    structlog.configure(
        processors=[
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.add_log_level,
            structlog.processors.EventRenamer("message"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """Return a structured logger bound to a module name."""
    return structlog.get_logger(name)
