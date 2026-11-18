from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import pytest

from app.config import load_config

FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def temp_config(tmp_path: Path) -> Dict[str, Any]:
    config = load_config()
    config["output"]["directory"] = str(tmp_path / "outputs")
    config["database"]["path"] = str(tmp_path / "data" / "scans.sqlite3")
    config["ollama"]["cache_path"] = str(tmp_path / "cache" / "ai.sqlite3")
    config["logging"]["directory"] = str(tmp_path / "logs")
    Path(config["output"]["directory"]).mkdir(parents=True, exist_ok=True)
    Path(config["database"]["path"]).parent.mkdir(parents=True, exist_ok=True)
    Path(config["ollama"]["cache_path"]).parent.mkdir(parents=True, exist_ok=True)
    Path(config["logging"]["directory"]).mkdir(parents=True, exist_ok=True)
    return config


class FakeUnavailableAnalyzer:
    def status(self) -> Dict[str, Any]:
        return {
            "provider": "ollama",
            "base_url": "http://127.0.0.1:11434",
            "model": "llama3.2:latest",
            "available": False,
            "model_installed": False,
            "models": [],
            "message": "Ollama is not reachable at http://127.0.0.1:11434.",
            "setup_instructions": ["Start the local server: ollama serve"],
        }

    def analyze(self, professor: Dict[str, Any], force_refresh: bool = False) -> Dict[str, Any]:
        raise RuntimeError("AI unavailable in this test")


@pytest.fixture
def fake_unavailable_analyzer():
    return FakeUnavailableAnalyzer()
