from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.backend.api import create_app
from app.backend.scan_manager import ScanBusyError, ScanManager, ScanNotFoundError
from app.backend.store import ScanStore


def test_invalid_url_rejected(temp_config, fake_unavailable_analyzer):
    manager = ScanManager(
        temp_config, analyzer_factory=lambda cfg: fake_unavailable_analyzer
    )
    with pytest.raises(ValueError):
        manager.start_scan("not a url")


def test_missing_scan_raises(temp_config, fake_unavailable_analyzer):
    manager = ScanManager(
        temp_config, analyzer_factory=lambda cfg: fake_unavailable_analyzer
    )
    with pytest.raises(ScanNotFoundError):
        manager.get_status("does-not-exist")
    with pytest.raises(ScanNotFoundError):
        manager.get_results("does-not-exist")


def test_ai_unavailable_preserves_professors(temp_config, fake_unavailable_analyzer):
    manager = ScanManager(
        temp_config, analyzer_factory=lambda cfg: fake_unavailable_analyzer
    )
    professors = [{"id": "prof_001", "name": "Jane Doe", "opportunity": {}}]
    info = manager._run_ai_stage("scan_test", professors, force_refresh=False)
    assert info["status"] == "unavailable"
    assert professors[0]["opportunity"].get("category") is None
    assert info["setup_instructions"]


def test_download_missing_report_raises(temp_config, fake_unavailable_analyzer):
    manager = ScanManager(
        temp_config, analyzer_factory=lambda cfg: fake_unavailable_analyzer
    )
    record = {
        "id": "scan_missing",
        "url": "https://example.edu/",
        "status": "completed",
        "stage": "completed",
        "progress": 100,
        "message": "done",
        "config": {},
        "output_dir": str(temp_config["output"]["directory"]),
    }
    manager.store.create_scan(record)
    with pytest.raises(FileNotFoundError):
        manager.download_path("scan_missing", "json")


def test_api_health_and_frontend(temp_config, fake_unavailable_analyzer):
    manager = ScanManager(
        temp_config, analyzer_factory=lambda cfg: fake_unavailable_analyzer
    )
    app = create_app(temp_config, manager)
    client = TestClient(app)
    health = client.get("/api/health")
    assert health.status_code == 200
    body = health.json()
    assert body["status"] == "ok"
    assert body["ollama"]["available"] is False
    assert body["defaults"]["max_depth"] == 3
    index = client.get("/")
    assert index.status_code == 200
    assert "University Research Discovery" in index.text
    favicon = client.get("/favicon.ico")
    assert favicon.status_code == 204
    assert favicon.content == b""


def test_api_rejects_invalid_scan_url(temp_config, fake_unavailable_analyzer):
    manager = ScanManager(
        temp_config, analyzer_factory=lambda cfg: fake_unavailable_analyzer
    )
    app = create_app(temp_config, manager)
    client = TestClient(app)
    response = client.post("/api/scans", json={"url": ""})
    assert response.status_code == 400
    assert "URL" in response.json()["detail"]


def test_store_marks_interrupted_scans(tmp_path):
    store = ScanStore(str(tmp_path / "scans.sqlite3"))
    store.create_scan(
        {
            "id": "scan_running",
            "url": "https://example.edu/",
            "status": "running",
            "stage": "accessing",
            "config": {},
            "output_dir": str(tmp_path),
        }
    )
    assert store.mark_interrupted() == 1
    record = store.get_scan("scan_running")
    assert record["status"] == "failed"
    assert "interrupted" in record["error"].lower()
