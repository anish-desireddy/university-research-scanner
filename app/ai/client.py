"""Ollama client.

All inference stays local. The application never substitutes a different model
and never reports a successful analysis when Ollama is unavailable.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger("urd.ai")


class OllamaError(RuntimeError):
    """Raised when local AI inference cannot be completed."""


def _normalize_model_name(name: str) -> str:
    return (name or "").strip().lower()


def model_matches(configured: str, installed: str) -> bool:
    configured_name = _normalize_model_name(configured)
    installed_name = _normalize_model_name(installed)
    if not configured_name or not installed_name:
        return False
    if configured_name == installed_name:
        return True
    # "llama3.2" should match "llama3.2:latest", but not "llama3.2:1b".
    if ":" not in configured_name:
        return installed_name == configured_name + ":latest"
    return False


class OllamaClient:
    def __init__(self, config: Dict[str, Any]):
        self.base_url = str(config["base_url"]).rstrip("/")
        self.model = str(config["model"])
        self.timeout = int(config.get("timeout_seconds", 300))
        self.temperature = float(config.get("temperature", 0.1))
        self.num_ctx = int(config.get("num_ctx", 8192))
        self.num_predict = int(config.get("num_predict", 1100))
        self.keep_alive = str(config.get("keep_alive", "30m"))

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def list_models(self, timeout: float = 3.0) -> List[str]:
        try:
            response = requests.get(f"{self.base_url}/api/tags", timeout=timeout)
            response.raise_for_status()
            data = response.json()
        except requests.RequestException as exc:
            raise OllamaError(
                f"Ollama is not reachable at {self.base_url}: {exc}"
            ) from exc
        except ValueError as exc:
            raise OllamaError("Ollama returned an unreadable model list.") from exc
        models = []
        for item in data.get("models", []) or []:
            name = item.get("name") or item.get("model")
            if name:
                models.append(str(name))
        return models

    def status(self) -> Dict[str, Any]:
        status: Dict[str, Any] = {
            "provider": "ollama",
            "base_url": self.base_url,
            "model": self.model,
            "available": False,
            "model_installed": False,
            "models": [],
            "message": "",
            "setup_instructions": [],
        }
        try:
            models = self.list_models()
        except OllamaError as exc:
            status["message"] = str(exc)
            status["setup_instructions"] = [
                "Install Ollama from https://ollama.com/download (macOS: brew install ollama).",
                f"Start the local server: ollama serve",
                f"Install the configured model: ollama pull {self.model}",
                "Use the Retry AI Analysis button after Ollama is running.",
            ]
            return status
        status["available"] = True
        status["models"] = sorted(models)
        installed = any(model_matches(self.model, name) for name in models)
        status["model_installed"] = installed
        if not installed:
            status["message"] = (
                f"Ollama is running, but the configured model '{self.model}' is not installed."
            )
            status["setup_instructions"] = [
                f"Install the configured model: ollama pull {self.model}",
                "Verify it appears in: ollama list",
                "Then use Retry AI Analysis. The model is never substituted automatically.",
            ]
        else:
            status["message"] = f"Ollama is ready with {self.model}."
        return status

    # ------------------------------------------------------------------
    # Generation
    # ------------------------------------------------------------------

    def generate(self, prompt: str, system: str = "") -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "system": system,
            "stream": False,
            "format": "json",
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": self.temperature,
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
            },
        }
        try:
            response = requests.post(
                f"{self.base_url}/api/generate",
                json=payload,
                timeout=(5, self.timeout),
            )
            response.raise_for_status()
            data = response.json()
        except requests.Timeout as exc:
            raise OllamaError(
                f"Ollama timed out after {self.timeout}s while generating a response."
            ) from exc
        except requests.RequestException as exc:
            raise OllamaError(f"Ollama inference failed: {exc}") from exc
        except ValueError as exc:
            raise OllamaError("Ollama returned an unreadable response.") from exc
        text = data.get("response")
        if not isinstance(text, str) or not text.strip():
            raise OllamaError("Ollama returned an empty response.")
        return text.strip()

    def generate_json(self, prompt: str, system: str = "") -> Dict[str, Any]:
        text = self.generate(prompt, system)
        parsed = parse_json_object(text)
        if parsed is not None:
            return parsed
        logger.warning("Ollama returned invalid JSON; requesting one strict repair.")
        repair_prompt = (
            "The previous response was not valid JSON. Return ONLY a single JSON object, "
            "with no markdown fences, commentary, or trailing text. Ensure every string is "
            "properly quoted and every brace is closed.\n\nPrevious response:\n"
            + text[:6000]
        )
        repaired = self.generate(repair_prompt, system)
        parsed = parse_json_object(repaired)
        if parsed is None:
            raise OllamaError("Ollama did not return valid JSON after a repair attempt.")
        return parsed


def parse_json_object(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    candidate = text.strip()
    candidate = re.sub(r"^```(?:json)?\s*", "", candidate, flags=re.I)
    candidate = re.sub(r"\s*```$", "", candidate)
    try:
        value = json.loads(candidate)
        if isinstance(value, dict):
            return value
    except json.JSONDecodeError:
        pass
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start != -1 and end > start:
        try:
            value = json.loads(candidate[start : end + 1])
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            return None
    return None
