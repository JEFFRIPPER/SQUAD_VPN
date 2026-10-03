"""Logging for the server process: rotating file, optional console."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .config import LoggingConfig


FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_configured: set[Path] = set()


def setup_logging(root: Path, config: LoggingConfig, *, name: str = "squad") -> Path:
    """Send ``squad_vpn.*`` logs to ``data/logs/<name>.log`` (rotated).

    The console gets them too only when it is a real terminal: under the
    agent, stdout is already redirected to a file, and writing the same
    lines twice into two files (one of them rotating) breaks on Windows.
    """
    logs = root / "data" / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    path = logs / f"{name}.log"
    logger = logging.getLogger("squad_vpn")
    logger.setLevel(config.level)
    if path in _configured:
        return path
    handler = RotatingFileHandler(
        path,
        maxBytes=int(config.max_mb * 1_000_000),
        backupCount=max(1, config.keep),
        encoding="utf-8",
        delay=True,
    )
    handler.setFormatter(logging.Formatter(FORMAT))
    logger.addHandler(handler)
    if sys.stdout is not None and sys.stdout.isatty():
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
        logger.addHandler(console)
    _configured.add(path)
    return path
