"""Basic structured logging configuration."""

import logging
import sys

import structlog


def configure_logging(log_level: str) -> None:
    """Configure JSON logs with stable request and service fields."""

    level = getattr(logging, log_level.upper(), logging.INFO)
    logging.basicConfig(format="%(message)s", level=level, stream=sys.stdout, force=True)
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=False,
    )
