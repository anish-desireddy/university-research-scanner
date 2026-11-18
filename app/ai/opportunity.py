"""Undergraduate research opportunity classification with evidence grounding."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

from app.ai import prompts
from app.ai.client import OllamaClient
from app.utils import clean_text

CATEGORY_LABELS = {
    1: "Confirmed open position",
    2: "Actively recruiting / welcoming students",
    3: "Potential opportunity",
    4: "No opportunity information found",
}

SECTION = """OPPORTUNITY CLASSIFICATION TASK
Choose exactly one category from 1-4 using the definitions and the supplied
evidence candidates. Explain the decision. Cite only supplied evidence by id and
repeat its quotation exactly. Explicit statements about undergraduate research,
joining a lab, openings, or recruitment matter. General descriptions of research
do not. Never upgrade absence of information into a confirmed opening.
"""

_WORD_CATEGORIES = {
    1: re.compile(r"\bconfirmed\b|\bopen position\b|\bopening\b", re.I),
    2: re.compile(r"\brecruit|\bwelcome|\bwelcoming\b|\binvit", re.I),
    3: re.compile(r"\bpotential\b", re.I),
    4: re.compile(r"\bno opportunity\b|\binsufficient\b|\bnot (?:available|found)\b", re.I),
}


def normalize_category(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and int(value) in CATEGORY_LABELS:
        return int(value)
    text = clean_text(value)
    if not text:
        return None
    match = re.search(r"\b([1-4])\b", text)
    if match:
        return int(match.group(1))
    for category, pattern in _WORD_CATEGORIES.items():
        if pattern.search(text):
            return category
    return None


def _match_candidate(
    item: Dict[str, Any], candidates: List[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    evidence_id = clean_text(item.get("id")).upper()
    quote = clean_text(item.get("quote")).casefold()
    if evidence_id:
        for candidate in candidates:
            if candidate["id"] != evidence_id:
                continue
            candidate_quote = clean_text(candidate.get("quote")).casefold()
            if quote and candidate_quote and not (
                quote == candidate_quote
                or quote in candidate_quote
                or candidate_quote in quote
            ):
                # A valid id with a fabricated quotation is not grounded.
                return None
            return candidate
    for candidate in candidates:
        candidate_quote = clean_text(candidate.get("quote")).casefold()
        if not candidate_quote:
            continue
        if quote == candidate_quote or quote in candidate_quote or candidate_quote in quote:
            return candidate
    return None


def parse_classification(
    data: Dict[str, Any], professor: Dict[str, Any]
) -> Dict[str, Any]:
    candidates = prompts.evidence_candidates(professor)
    category = normalize_category(data.get("opportunity_category"))
    explanation = clean_text(data.get("classification_explanation"))
    raw_evidence = data.get("evidence")
    if not isinstance(raw_evidence, list):
        raw_evidence = []

    grounded: List[Dict[str, Any]] = []
    seen = set()
    for item in raw_evidence[:8]:
        if not isinstance(item, dict):
            continue
        candidate = _match_candidate(item, candidates)
        if candidate is None:
            # A model citation that cannot be matched to a supplied page is
            # discarded rather than trusted.
            continue
        key = (candidate["id"], candidate["url"])
        if key in seen:
            continue
        seen.add(key)
        grounded.append(
            {
                "url": candidate["url"],
                "quote": candidate["quote"],
                "page_title": None,
                "date": candidate.get("date"),
                "current": candidate.get("current"),
                "direction": candidate.get("direction", "positive"),
                "reasons": candidate.get("reasons") or [],
                "explanation": clean_text(item.get("explanation")) or None,
                "evidence_id": candidate["id"],
            }
        )

    notes: List[str] = []
    positive = [item for item in grounded if item.get("direction") != "negative"]
    negative = [item for item in grounded if item.get("direction") == "negative"]

    if category is None:
        notes.append("The local model did not return a valid category.")
        status = "failed"
    else:
        status = "complete"
        if category in (1, 2) and not positive:
            if not candidates:
                category = 4
                notes.append(
                    "No public evidence of an opening or recruitment statement was "
                    "found, so the assessment was downgraded to category 4."
                )
            else:
                category = 3
                notes.append(
                    "The model selected an opening/recruitment category without a "
                    "grounded positive quotation, so the assessment was downgraded "
                    "to a potential opportunity."
                )
            status = "adjusted"
        if category == 1 and not any(
            item["direction"] != "negative" and item.get("current") is not False
            for item in grounded
        ):
            category = 2 if grounded else 4
            notes.append(
                "No current, date-supported evidence of a specific opening was "
                "grounded; a confirmed opening was not claimed."
            )
            status = "adjusted"
        if category == 4 and negative:
            notes.append("Negative evidence was found and is recorded below.")
        if not grounded:
            notes.append("No supporting evidence quotation was available.")

    if notes:
        explanation = (explanation + " " + " ".join(notes)).strip()

    return {
        "category": category,
        "category_label": CATEGORY_LABELS.get(category),
        "explanation": explanation or None,
        "evidence": grounded,
        "evidence_found": bool(grounded),
        "status": status,
        "notes": notes,
        "raw_category": data.get("opportunity_category"),
    }


def classify_opportunity(
    client: OllamaClient, professor: Dict[str, Any]
) -> Dict[str, Any]:
    """Standalone classification call."""
    prompt = prompts.build_prompt([SECTION], professor)
    data = client.generate_json(prompt, prompts.SYSTEM_PROMPT)
    return parse_classification(data, professor)
