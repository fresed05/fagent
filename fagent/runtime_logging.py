"""Runtime logging bootstrap shared by CLI and server entrypoints."""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger

from fagent.config.paths import get_logs_dir

_RUNTIME_LOGGING_READY = False
_RUNTIME_LOG_PATH: Path | None = None


def setup_runtime_logging(*, verbose: bool = False, console_output: bool = True) -> Path:
    global _RUNTIME_LOGGING_READY, _RUNTIME_LOG_PATH
    if _RUNTIME_LOGGING_READY and _RUNTIME_LOG_PATH is not None:
        return _RUNTIME_LOG_PATH

    logs_dir = get_logs_dir()
    log_path = logs_dir / "runtime.log"
    logger.remove()
    if console_output:
        logger.add(
            sys.stderr,
            level="DEBUG" if verbose else "INFO",
            colorize=True,
            backtrace=False,
            diagnose=False,
        )
    logger.add(
        log_path,
        rotation="10 MB",
        retention=10,
        level="DEBUG" if verbose else "INFO",
        serialize=True,
        enqueue=False,
        backtrace=False,
        diagnose=False,
    )
    _RUNTIME_LOGGING_READY = True
    _RUNTIME_LOG_PATH = log_path
    return log_path
