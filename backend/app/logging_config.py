"""Application logging configuration."""

import logging
import sys


def configure_logging(log_level: str = "INFO") -> None:
    """Set up basic logging to stdout. Safe to call multiple times."""
    level = getattr(logging, log_level.upper(), logging.INFO)

    root = logging.getLogger()
    if root.handlers:
        root.setLevel(level)
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    root.addHandler(handler)
    root.setLevel(level)

    # Quiet down noisy libraries
    for name in ("sqlalchemy.engine", "asyncio", "httpx", "uvicorn.error"):
        logging.getLogger(name).setLevel(logging.WARNING)
