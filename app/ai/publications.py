"""Publication theme analysis."""

from __future__ import annotations

from typing import Any, Dict, List

from app.ai import prompts
from app.ai.client import OllamaClient
from app.utils import clean_text, unique_strings

SECTION = """PUBLICATION ANALYSIS TASK
Using only the publication titles, years, venues, and topics supplied, write
2-4 sentences describing the main themes and direction of the publication
record. Do not infer publications that are not listed. Do not claim a
comprehensive publication record; these may be selected publications. If there
are no publications, say so. Also return up to 8 short publication topics.
"""


def parse_publication_analysis(data: Dict[str, Any]) -> Dict[str, Any]:
    analysis = clean_text(data.get("publication_analysis"))
    if len(analysis) > 2500:
        analysis = analysis[:2500].rsplit(" ", 1)[0]
    topics = data.get("publication_topics")
    if isinstance(topics, str):
        topics = [topics]
    if not isinstance(topics, list):
        topics = []
    return {
        "analysis": analysis or None,
        "topics": unique_strings(
            [clean_text(topic) for topic in topics if isinstance(topic, str) and clean_text(topic)]
        )[:8],
    }


def analyze_publications(
    client: OllamaClient, professor: Dict[str, Any]
) -> Dict[str, Any]:
    """Standalone publication analysis call."""
    prompt = prompts.build_prompt([SECTION], professor)
    data = client.generate_json(prompt, prompts.SYSTEM_PROMPT)
    return parse_publication_analysis(data)
