"""Confidence scoring and calibration.

The score describes evidence quality, never the probability of acceptance. The
model proposes a score; deterministic guardrails cap it when the grounded
evidence is thin, absent, or outdated.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.ai import prompts
from app.ai.client import OllamaClient
from app.utils import clean_text

SECTION = """CONFIDENCE SCORING TASK
Give an integer confidence score from 0 to 100 and a short explanation. The
score measures the strength and quality of the evidence supporting the
classification, not the chance that the professor accepts a student. Direct,
recent, explicit evidence should score higher than an undated inference.
Insufficient evidence should score low even when the category is "potential".
"""


def _parse_score(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        score = int(value)
    else:
        match = re.search(r"\b(\d{1,3})\b", clean_text(value))
        if not match:
            return None
        score = int(match.group(1))
    return max(0, min(100, score))


def fallback_score(category: Optional[int], evidence: List[Dict[str, Any]]) -> int:
    base = {1: 85, 2: 70, 3: 45, 4: 15}.get(category, 0)
    if not evidence:
        return min(base, 20)
    current = [item for item in evidence if item.get("current") is True]
    outdated = [item for item in evidence if item.get("current") is False]
    if current:
        base += 4
    elif outdated:
        base -= 12
    return max(0, min(100, base))


def calibrate_confidence(
    data: Dict[str, Any],
    category: Optional[int],
    evidence: List[Dict[str, Any]],
) -> Dict[str, Any]:
    raw_score = _parse_score(data.get("confidence_score"))
    explanation = clean_text(data.get("confidence_explanation"))
    score = raw_score if raw_score is not None else fallback_score(category, evidence)
    notes: List[str] = []
    grounded = [item for item in evidence if item.get("direction") != "negative"]
    all_evidence = list(evidence)

    if category is None:
        return {
            "score": None,
            "explanation": explanation
            or "Confidence cannot be scored because the opportunity classification failed.",
            "raw_score": raw_score,
            "notes": ["No valid category."],
        }

    original = score
    if not all_evidence:
        score = min(score, 20)
        if score != original:
            notes.append("Capped at 20 because no supporting evidence was grounded.")
    if category in (1, 2):
        if not grounded:
            score = min(score, 45)
            notes.append("Capped at 45 because no positive evidence was grounded.")
        else:
            current_positive = [item for item in grounded if item.get("current") is True]
            outdated_positive = [item for item in grounded if item.get("current") is False]
            if not current_positive and outdated_positive:
                score = min(score, 60)
                notes.append(
                    "Capped at 60 because the supporting evidence appears outdated."
                )
            elif not current_positive and not any(
                item.get("current") is False for item in grounded
            ):
                score = min(score, 80)
                notes.append(
                    "Capped at 80 because the evidence has no verifiable date."
                )
    elif category == 3:
        if not grounded:
            score = min(score, 50)
            notes.append("Capped at 50 because the potential assessment is not evidence-backed.")
        else:
            score = min(score, 75)
    elif category == 4:
        if not all_evidence:
            score = min(score, 20)
        else:
            negative = [item for item in all_evidence if item.get("direction") == "negative"]
            if negative:
                score = min(score, 85)

    score = max(0, min(100, score))
    if raw_score is None:
        notes.append("The model did not provide a usable score; a conservative rubric was applied.")
    if score != original and explanation:
        explanation = (
            explanation
            + " Calibration: "
            + " ".join(notes)
            + f" Final evidence-strength score: {score}/100."
        ).strip()
    elif not explanation:
        explanation = (
            f"Score {score}/100 reflects the quality of the currently available "
            "evidence, not the likelihood of acceptance."
        )
    return {
        "score": score,
        "explanation": explanation,
        "raw_score": raw_score,
        "notes": notes,
    }


def score_confidence(
    client: OllamaClient,
    professor: Dict[str, Any],
    category: Optional[int],
    evidence: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Standalone confidence call."""
    prompt = prompts.build_prompt([SECTION], professor)
    data = client.generate_json(prompt, prompts.SYSTEM_PROMPT)
    return calibrate_confidence(data, category, evidence)
