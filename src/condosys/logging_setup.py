"""Logging configuration: Rich console handler plus a rotating file in ``logs/``.

Never log passwords, certificate contents or session cookies.
"""

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

LOG_FILE_NAME = "condosys.log"
_FILE_FORMAT = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"


def setup_logging(logs_dir: Path, level: str = "INFO", console: Console | None = None) -> Path:
    """Configures the root ``condosys`` logger.

    Args:
        logs_dir: Directory for the rotating log file (created if missing).
        level: Console log level name. The file always records DEBUG and above.
        console: Rich console to log to; a stderr console is created if omitted.

    Returns:
        Path of the log file.
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_file = logs_dir / LOG_FILE_NAME

    logger = logging.getLogger("condosys")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    console_handler = RichHandler(
        console=console or Console(stderr=True),
        show_path=False,
        rich_tracebacks=True,
        markup=False,
    )
    console_handler.setLevel(level.upper())
    logger.addHandler(console_handler)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=2_000_000, backupCount=5, encoding="utf-8"
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(_FILE_FORMAT))
    logger.addHandler(file_handler)

    return log_file
