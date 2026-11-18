"""Per-professor analysis orchestration."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.ai import confidence as confidence_module
from app.ai import opportunity as opportunity_module
from app.ai import prompts, publications, summary
from app.ai.cache import AICache
from app.ai.client import OllamaClient, OllamaError

logger = logging.getLogger("urd.ai")


class AnalysisError(RuntimeError):
    pass


class ProfessorAnalyzer:
    """Runs one grounded, cached analysis request per professor.

    The four analysis concerns live in separate modules with independent
    prompt sections and parsers. Combining them into one request keeps a
    professor's summary, publications, category, and confidence mutually
    consistent and makes a 50-professor scan practical on a laptop.
    """

    def __init__(self, config: Dict[str, Any], cache: Optional[AICache] = None):
        self.config = config
        self.client = OllamaClient(config)
        self.cache = cache or AICache(config["cache_path"])
        self.model = str(config["model"])

    def analyze(
        self, professor: Dict[str, Any], force_refresh: bool = False
    ) -> Dict[str, Any]:
        prompt = prompts.build_prompt(
            [
                summary.SECTION,
                publications.SECTION,
                opportunity_module.SECTION,
                confidence_module.SECTION,
            ],
            professor,
        )
        key = self.cache.make_key(
            self.model, prompts.PROMPT_VERSION, prompt, prompts.SYSTEM_PROMPT
        )
        cached = None if force_refresh else self.cache.get(key)
        used_cache = cached is not None
        if used_cache:
            data = cached
        else:
            started = time.time()
            logger.info(
                "Ollama analysis for %s (prompt_chars=%s, model=%s)",
                professor.get("name"),
                len(prompt),
                self.model,
            )
            try:
                data = self.client.generate_json(prompt, prompts.SYSTEM_PROMPT)
            except OllamaError:
                raise
            elapsed = round(time.time() - started, 1)
            logger.info(
                "Ollama analysis completed for %s in %ss", professor.get("name"), elapsed
            )
            self.cache.set(key, data, self.model, prompts.PROMPT_VERSION)

        if not isinstance(data, dict) or not data:
            raise AnalysisError("The AI response did not contain an analysis object.")

        summary_data = summary.parse_summary(data)
        publication_data = publications.parse_publication_analysis(data)
        opportunity_data = opportunity_module.parse_classification(data, professor)
        confidence_data = confidence_module.calibrate_confidence(
            data, opportunity_data["category"], opportunity_data["evidence"]
        )

        status = "complete"
        if not summary_data["summary"]:
            status = "partial"
        if opportunity_data["status"] == "failed":
            status = "partial" if summary_data["summary"] else "failed"

        result = {
            "status": status,
            "provider": "ollama",
            "model": self.model,
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "cached": used_cache,
            "research_summary": summary_data["summary"],
            "ai_interests": summary_data["interests"],
            "ai_methodologies": summary_data["methodologies"],
            "ai_technologies": summary_data["technologies"],
            "ai_current_projects": summary_data["current_projects"],
            "publication_analysis": publication_data["analysis"],
            "publication_topics": publication_data["topics"],
            "category": opportunity_data["category"],
            "category_label": opportunity_data["category_label"],
            "classification_explanation": opportunity_data["explanation"],
            "opportunity_evidence": opportunity_data["evidence"],
            "opportunity_status": opportunity_data["status"],
            "opportunity_notes": opportunity_data["notes"],
            "confidence": confidence_data["score"],
            "confidence_explanation": confidence_data["explanation"],
            "raw_confidence": confidence_data["raw_score"],
            "confidence_notes": confidence_data["notes"],
        }
        return result

    def status(self) -> Dict[str, Any]:
        return self.client.status()
