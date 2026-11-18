"""Comprehensive JSON report output."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict

from app.utils import atomic_write_json, read_json

logger = logging.getLogger("urd.reporting")


def write_json_report(result: Dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    atomic_write_json(target, result)
    # Verify that the file is valid UTF-8 JSON before declaring success.
    verified = read_json(target)
    if not isinstance(verified, dict):
        raise RuntimeError(f"JSON report at {target} could not be verified.")
    logger.info(
        "JSON report written: %s (%s professors)",
        target,
        len(result.get("professors") or []),
    )
    return target
