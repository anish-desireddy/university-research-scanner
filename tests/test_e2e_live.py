from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from pypdf import PdfReader

from app.backend.scan_manager import ScanManager
from app.config import load_config


@pytest.mark.skipif(
    os.environ.get("RUN_LIVE_E2E") != "1",
    reason="Set RUN_LIVE_E2E=1 to run the live ODU end-to-end scan.",
)
def test_live_odu_scan_produces_consistent_json_and_pdf(tmp_path):
    config = load_config()
    config["output"]["directory"] = str(tmp_path / "outputs")
    config["database"]["path"] = str(tmp_path / "data" / "scans.sqlite3")
    config["ollama"]["cache_path"] = str(tmp_path / "cache" / "ai.sqlite3")
    config["logging"]["directory"] = str(tmp_path / "logs")
    Path(config["output"]["directory"]).mkdir(parents=True, exist_ok=True)
    Path(config["database"]["path"]).parent.mkdir(parents=True, exist_ok=True)
    Path(config["ollama"]["cache_path"]).parent.mkdir(parents=True, exist_ok=True)
    Path(config["logging"]["directory"]).mkdir(parents=True, exist_ok=True)

    manager = ScanManager(config)
    max_pages = int(os.environ.get("URD_E2E_MAX_PAGES", "35"))
    status = manager.start_scan(
        "https://www.cs.odu.edu/",
        {
            "max_pages": max_pages,
            "max_depth": 3,
            "max_external_domains": 4,
            "request_delay": 0.5,
        },
    )
    scan_id = status["id"]
    deadline = time.time() + int(os.environ.get("URD_E2E_TIMEOUT", "1500"))
    while time.time() < deadline:
        status = manager.get_status(scan_id)
        if status["status"] in ("completed", "completed_with_errors", "failed"):
            break
        time.sleep(2)

    assert status["status"] in ("completed", "completed_with_errors"), status.get("error")
    result = manager.get_results(scan_id)
    professors = result.get("professors") or []
    assert professors, "The live crawl should identify at least one professor."
    assert result["scan"]["summary"]["professors_identified"] == len(professors)

    json_path = manager.download_path(scan_id, "json")
    pdf_path = manager.download_path(scan_id, "pdf")
    assert json_path.exists()
    assert pdf_path.exists()
    reader = PdfReader(str(pdf_path))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    for professor in professors:
        assert professor["name"] in text, f"{professor['name']} missing from PDF"
    assert "Executive Summary" in text
    assert "Methodology and Limitations" in text

    # The AI may legitimately be unavailable on a machine without Ollama, but
    # the JSON and PDF must still be produced and consistently list professors.
    assert result["scan"]["ai"]["status"] in (
        "complete",
        "partial",
        "failed",
        "unavailable",
        "model_missing",
        "skipped",
    )
    print("AI status:", result["scan"]["ai"]["status"])
    print("Professors:", len(professors))
    print("JSON:", json_path)
    print("PDF:", pdf_path)
