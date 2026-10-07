"""Logging adapter for identifier-only runtime outcomes."""

import logging

from packages.domain.observability import RuntimeObservation


def observe_runtime(logger: logging.Logger, observation: RuntimeObservation) -> None:
    """Emit structured identifiers only; learner content never enters the log."""

    logger.info("runtime_operation", extra={"runtime": observation.identifiers()})
