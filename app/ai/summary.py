"""Research summarization for undergraduate readers."""

from __future__ import annotations

from typing import Any, Dict, List

from app.ai import prompts
from app.ai.client import OllamaClient
from app.utils import clean_text, unique_strings

SECTION = """RESEARCH SUMMARY TASK
Write a 2-4 paragraph explanation (120-220 words) for an undergraduate who does
not know this field. Explain: what the professor studies; the problems they are
trying to solve; their main research interests; methods and technologies they
use; notable projects; and recent directions only when the supplied data
supports them. Avoid generic filler such as "conducts important research".
Attribute no facts that are not in the data. If the profile is sparse, state
what is unknown rather than guessing.
"""


def _string_list(value: Any, limit: int = 20) -> List[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return unique_strings(
        [clean_text(item) for item in value if isinstance(item, (str, int, float)) and clean_text(item)]
    )[:limit]


def parse_summary(data: Dict[str, Any]) -> Dict[str, Any]:
    summary = clean_text(data.get("research_summary"))
    if len(summary) > 4000:
        summary = summary[:4000].rsplit(" ", 1)[0]
    return {
        "summary": summary or None,
        "interests": _string_list(data.get("research_interests"), 15),
        "methodologies": _string_list(data.get("methodologies"), 15),
        "technologies": _string_list(data.get("technologies"), 15),
        "current_projects": _string_list(data.get("current_projects"), 12),
    }


def summarize_professor(client: OllamaClient, professor: Dict[str, Any]) -> Dict[str, Any]:
    """Standalone summary call, useful for focused re-analysis and tests."""
    prompt = prompts.build_prompt([SECTION], professor)
    data = client.generate_json(prompt, prompts.SYSTEM_PROMPT)
    return parse_summary(data)
