"""Configuration loading and validation.

Every path in the configuration is resolved relative to the project root so the
application behaves the same regardless of the caller's working directory.
"""

from __future__ import annotations

import copy
import os
from pathlib import Path
from typing import Any, Dict

import yaml

BASE_DIR = Path(__file__).resolve().parent.parent
CONFIG_PATH = BASE_DIR / "config.yaml"

DEFAULTS: Dict[str, Any] = {
    "app": {
        "host": "127.0.0.1",
        "port": 8765,
        "open_browser": True,
        "chrome_path": "",
    },
    "crawl": {
        "max_depth": 3,
        "max_pages": 100,
        "max_external_domains": 20,
        "max_pages_per_external_domain": 6,
        "request_delay": 1.0,
        "download_timeout": 25,
        "concurrent_requests": 4,
        "user_agent": (
            "UniversityResearchDiscoveryBot/1.0 "
            "(local academic research; respectful crawler)"
        ),
        "max_runtime_seconds": 1200,
        "use_playwright": True,
        "playwright_timeout_ms": 25000,
    },
    "ollama": {
        "base_url": "http://127.0.0.1:11434",
        "model": "llama3.2:latest",
        "timeout_seconds": 300,
        "temperature": 0.1,
        "num_ctx": 8192,
        "num_predict": 1100,
        "keep_alive": "30m",
        "max_concurrent_requests": 2,
        "cache_path": "cache/ai_cache.sqlite3",
    },
    "output": {"directory": "outputs"},
    "database": {"path": "data/scans.sqlite3"},
    "logging": {"directory": "logs", "level": "INFO"},
}

_PATH_KEYS = (
    ("output", "directory"),
    ("database", "path"),
    ("logging", "directory"),
    ("ollama", "cache_path"),
)


def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    result = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _resolve_path(value: str) -> str:
    path = Path(os.path.expanduser(str(value)))
    if not path.is_absolute():
        path = BASE_DIR / path
    return str(path.resolve())


def load_config(path: str | Path | None = None) -> Dict[str, Any]:
    """Load config.yaml, apply environment overrides, and resolve paths."""
    config_path = Path(path) if path else CONFIG_PATH
    loaded: Dict[str, Any] = {}
    if config_path.exists():
        with config_path.open("r", encoding="utf-8") as handle:
            loaded = yaml.safe_load(handle) or {}
    config = _deep_merge(DEFAULTS, loaded)

    env_overrides = {
        ("app", "host"): "URD_HOST",
        ("app", "port"): "URD_PORT",
        ("ollama", "base_url"): "OLLAMA_BASE_URL",
        ("ollama", "model"): "OLLAMA_MODEL",
    }
    for (section, key), env_name in env_overrides.items():
        if env_name in os.environ and os.environ[env_name] != "":
            raw = os.environ[env_name]
            if key == "port":
                config[section][key] = int(raw)
            else:
                config[section][key] = raw

    for section, key in _PATH_KEYS:
        config[section][key] = _resolve_path(config[section][key])

    # Numeric guards protect the UI and the crawler from bad config files.
    crawl = config["crawl"]
    crawl["max_depth"] = max(0, min(int(crawl["max_depth"]), 6))
    crawl["max_pages"] = max(1, min(int(crawl["max_pages"]), 500))
    crawl["max_external_domains"] = max(0, min(int(crawl["max_external_domains"]), 100))
    crawl["request_delay"] = max(0.0, float(crawl["request_delay"]))
    ollama = config["ollama"]
    ollama["max_concurrent_requests"] = max(1, int(ollama["max_concurrent_requests"]))
    return config


def ensure_directories(config: Dict[str, Any]) -> None:
    for section, key in _PATH_KEYS:
        value = Path(config[section][key])
        if key in ("path", "cache_path"):
            value.parent.mkdir(parents=True, exist_ok=True)
        else:
            value.mkdir(parents=True, exist_ok=True)


def default_scan_options(config: Dict[str, Any]) -> Dict[str, Any]:
    crawl = config["crawl"]
    return {
        "max_depth": crawl["max_depth"],
        "max_pages": crawl["max_pages"],
        "max_external_domains": crawl["max_external_domains"],
        "max_pages_per_external_domain": crawl["max_pages_per_external_domain"],
        "request_delay": crawl["request_delay"],
        "download_timeout": crawl["download_timeout"],
        "concurrent_requests": crawl["concurrent_requests"],
        "user_agent": crawl["user_agent"],
        "max_runtime_seconds": crawl["max_runtime_seconds"],
        "use_playwright": crawl["use_playwright"],
        "playwright_timeout_ms": crawl["playwright_timeout_ms"],
    }
