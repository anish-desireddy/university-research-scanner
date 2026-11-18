"""Application logging setup."""

from __future__ import annotations

import logging
import logging.handlers
import os
import sys
from pathlib import Path
from typing import Any, Dict


def setup_logging(config: Dict[str, Any]) -> logging.Logger:
    log_dir = Path(config["logging"]["directory"])
    log_dir.mkdir(parents=True, exist_ok=True)
    level_name = str(config["logging"].get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)
    for handler in list(root.handlers):
        root.removeHandler(handler)
        try:
            handler.close()
        except Exception:
            pass

    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(formatter)
    console.setLevel(level)
    root.addHandler(console)

    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "app.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    root.addHandler(file_handler)

    # Keep third-party libraries reasonably quiet; warnings still reach the log.
    for name in ("scrapy", "twisted", "urllib3", "httpx", "httpcore"):
        logging.getLogger(name).setLevel(max(level, logging.WARNING))

    logger = logging.getLogger("urd")
    logger.info("Logging initialized (level=%s, file=%s)", level_name, log_dir / "app.log")
    logger.info("Python executable: %s", sys.executable)
    logger.info("Working directory: %s", os.getcwd())
    return logger
