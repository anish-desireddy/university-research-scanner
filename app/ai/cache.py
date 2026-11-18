"""Persistent cache for completed Ollama analyses."""

from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("urd.ai")


class AICache:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=15)
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS ai_cache (
                    key TEXT PRIMARY KEY,
                    model TEXT NOT NULL,
                    prompt_version TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    value TEXT NOT NULL
                )
                """
            )

    @staticmethod
    def make_key(model: str, prompt_version: str, prompt: str, system: str) -> str:
        digest = hashlib.sha256()
        for part in (model, prompt_version, system, prompt):
            digest.update(part.encode("utf-8", "ignore"))
            digest.update(b"\0")
        return digest.hexdigest()

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        try:
            with self._connect() as connection:
                row = connection.execute(
                    "SELECT value FROM ai_cache WHERE key = ?", (key,)
                ).fetchone()
        except sqlite3.Error:
            logger.exception("AI cache read failed")
            return None
        if not row:
            return None
        try:
            return json.loads(row[0])
        except (TypeError, json.JSONDecodeError):
            logger.warning("Discarding corrupt AI cache entry %s", key[:12])
            return None

    def set(
        self, key: str, value: Dict[str, Any], model: str, prompt_version: str
    ) -> None:
        try:
            with self._connect() as connection:
                connection.execute(
                    """
                    INSERT OR REPLACE INTO ai_cache
                    (key, model, prompt_version, created_at, value)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        key,
                        model,
                        prompt_version,
                        datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        json.dumps(value, ensure_ascii=False),
                    ),
                )
        except (sqlite3.Error, TypeError):
            logger.exception("AI cache write failed; analysis will not be cached")
