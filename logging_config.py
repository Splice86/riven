"""Riven logging setup — file-based error/debug logging to ~/.riven/logs/."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path


def setup_logging(
    log_file: str | None = None,
    level: int = logging.DEBUG,
    include_stdout: bool = True,
) -> logging.Logger:
    """Configure riven's root logger with a file handler.

    All riven modules use `logging.getLogger(__name__)` which makes them
    children of 'riven'. Setting up the 'riven' logger once here is enough.

    Args:
        log_file: Path to log file. Default: ~/.riven/logs/riven.log
        level: Minimum log level. DEBUG captures everything.
        include_stdout: Also print to stdout (useful for dev/debugging).
                       Set False in production to keep logs clean.
    """
    log_path = log_file or os.path.expanduser("~/.riven/logs/riven.log")

    # Ensure log directory exists
    log_dir = os.path.dirname(log_path)
    if log_dir:
        Path(log_dir).mkdir(parents=True, exist_ok=True)

    # Configure the 'riven' root logger (all modules are children of this)
    root = logging.getLogger("riven")
    root.setLevel(level)

    # Avoid duplicate handlers on re-runs (e.g. uvicorn reload)
    if root.handlers:
        return root

    formatter = logging.Formatter(
        fmt="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # File handler — always the primary log sink
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    # Optional stdout handler for dev (uvicorn already captures this, but
    # having it here means the log file is the source of truth)
    if include_stdout:
        stdout_handler = logging.StreamHandler(sys.stdout)
        stdout_handler.setLevel(level)
        stdout_handler.setFormatter(formatter)
        root.addHandler(stdout_handler)

    root.info("Logging initialised → %s", log_path)
    return root


def get_logger(name: str) -> logging.Logger:
    """Convenience: get a logger for a module.

    Usage:
        logger = get_logger(__name__)
        logger.info("Starting up")
        logger.error("Something went wrong: %s", e)
    """
    return logging.getLogger(f"riven.{name}")
