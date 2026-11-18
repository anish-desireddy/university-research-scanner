"""SQLite persistence for scan history and live status."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger("urd.backend")

JSON_FIELDS = {"config_json", "summary_json", "ai_json"}
UPDATE_FIELDS = {
    "status",
    "stage",
    "progress",
    "message",
    "updated_at",
    "completed_at",
    "pages",
    "professors_found",
    "publications_found",
    "analyzed_count",
    "warnings_count",
    "errors_count",
    "external_domains",
    "summary_json",
    "ai_json",
    "json_path",
    "pdf_path",
    "error",
    "output_dir",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ScanStore:
    def __init__(self, path: str):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.path), timeout=20)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS scans (
                    id TEXT PRIMARY KEY,
                    url TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stage TEXT NOT NULL,
                    progress INTEGER NOT NULL DEFAULT 0,
                    message TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT,
                    config_json TEXT NOT NULL,
                    pages INTEGER NOT NULL DEFAULT 0,
                    professors_found INTEGER NOT NULL DEFAULT 0,
                    publications_found INTEGER NOT NULL DEFAULT 0,
                    analyzed_count INTEGER NOT NULL DEFAULT 0,
                    warnings_count INTEGER NOT NULL DEFAULT 0,
                    errors_count INTEGER NOT NULL DEFAULT 0,
                    external_domains INTEGER NOT NULL DEFAULT 0,
                    summary_json TEXT,
                    ai_json TEXT,
                    json_path TEXT,
                    pdf_path TEXT,
                    error TEXT,
                    output_dir TEXT NOT NULL
                )
                """
            )

    def create_scan(self, record: Dict[str, Any]) -> Dict[str, Any]:
        now = record.get("created_at") or _now()
        values = {
            "id": record["id"],
            "url": record["url"],
            "status": record.get("status", "queued"),
            "stage": record.get("stage", "initializing"),
            "progress": int(record.get("progress", 0)),
            "message": record.get("message", "Scan queued"),
            "created_at": now,
            "updated_at": now,
            "completed_at": None,
            "config_json": json.dumps(record.get("config") or {}),
            "pages": 0,
            "professors_found": 0,
            "publications_found": 0,
            "analyzed_count": 0,
            "warnings_count": 0,
            "errors_count": 0,
            "external_domains": 0,
            "summary_json": None,
            "ai_json": None,
            "json_path": None,
            "pdf_path": None,
            "error": None,
            "output_dir": record["output_dir"],
        }
        with self._connect() as connection:
            columns = ", ".join(values.keys())
            placeholders = ", ".join(["?"] * len(values))
            connection.execute(
                f"INSERT INTO scans ({columns}) VALUES ({placeholders})",
                tuple(values.values()),
            )
        return self.get_scan(record["id"]) or values

    def update_scan(self, scan_id: str, **fields: Any) -> None:
        updates = {key: value for key, value in fields.items() if key in UPDATE_FIELDS}
        if not updates:
            return
        updates["updated_at"] = updates.get("updated_at") or _now()
        for key in JSON_FIELDS:
            if key in updates and updates[key] is not None and not isinstance(updates[key], str):
                updates[key] = json.dumps(updates[key], ensure_ascii=False)
        assignments = ", ".join(f"{key} = ?" for key in updates)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE scans SET {assignments} WHERE id = ?",
                tuple(updates.values()) + (scan_id,),
            )

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        record = dict(row)
        record["config"] = {}
        record["summary"] = {}
        record["ai"] = {}
        for key, target in (
            ("config_json", "config"),
            ("summary_json", "summary"),
            ("ai_json", "ai"),
        ):
            raw = record.pop(key, None)
            if raw:
                try:
                    record[target] = json.loads(raw)
                except (TypeError, json.JSONDecodeError):
                    record[target] = {}
        return record

    def get_scan(self, scan_id: str) -> Optional[Dict[str, Any]]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM scans WHERE id = ?", (scan_id,)).fetchone()
        return self._row_to_dict(row) if row else None

    def list_scans(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM scans ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row_to_dict(row) for row in rows]

    def mark_interrupted(self) -> int:
        now = _now()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE scans
                SET status = 'failed',
                    stage = 'failed',
                    message = 'The application stopped before this scan finished.',
                    error = 'Scan interrupted by application shutdown.',
                    updated_at = ?
                WHERE status IN ('queued', 'running')
                """,
                (now,),
            )
            return cursor.rowcount
