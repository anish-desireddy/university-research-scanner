"""Prompt construction shared by the four analysis modules."""

from __future__ import annotations

import json
from typing import Any, Dict, List

from app.utils import clean_text, truncate

PROMPT_VERSION = "2026-11-01.1"

SYSTEM_PROMPT = """You are a careful academic research analyst working only from
publicly available web information supplied to you. You help undergraduate
students understand what a professor studies and whether that professor appears
to have undergraduate research opportunities.

Hard rules:
- Use only the supplied professor data and evidence candidates.
- Never invent a publication, project, quotation, date, email, or opportunity.
- If information is missing, say that it is not available.
- General research interests are not a job opening.
- A laboratory website does not by itself prove that the professor is recruiting.
- Absence of public information does not mean absence of opportunities.
- Return only valid JSON. Do not wrap it in markdown fences or add commentary.
"""

SCHEMA = """Return ONE JSON object with exactly these keys:
{
  "research_summary": "2-4 plain-language paragraphs for an undergraduate (120-220 words)",
  "research_interests": ["concise interest", "..."],
  "methodologies": ["research method", "..."],
  "technologies": ["tool or technology", "..."],
  "current_projects": ["project explicitly supported by the data", "..."],
  "publication_analysis": "2-4 sentences about themes in the listed publications, or a statement that no publications were available",
  "publication_topics": ["topic", "..."],
  "opportunity_category": 1,
  "classification_explanation": "2-4 sentences explaining the category from the evidence",
  "evidence": [
    {"id": "E1", "quote": "exact quotation from that evidence candidate", "explanation": "how it supports the classification"}
  ],
  "confidence_score": 75,
  "confidence_explanation": "2-3 sentences explaining the strength and limits of the evidence"
}

All array values must be arrays of strings. Use [] when nothing is supported.
Use null only where explicitly allowed; otherwise omit speculation.
"""

CATEGORY_DEFINITIONS = """Opportunity categories:
1 = CONFIRMED OPEN POSITION. Explicit public evidence of an available
    undergraduate research position (for example a dated opening or "position
    available" announcement).
2 = ACTIVELY RECRUITING / WELCOMING STUDENTS. The professor or laboratory
    explicitly invites students to participate, but a specific vacant position
    is not confirmed (for example "undergraduates are welcome in our lab").
3 = POTENTIAL OPPORTUNITY. No confirmed opening or explicit recruitment
    statement, but the professor's research activity makes a respectful inquiry
    worthwhile.
4 = NO OPPORTUNITY INFORMATION FOUND. Insufficient public evidence to determine
    whether positions are available.

Do not present speculation as a confirmed position. Do not choose category 1
or 2 unless a supplied evidence candidate explicitly supports it.
"""

CONFIDENCE_DEFINITIONS = """Confidence score (0-100) measures the strength and
quality of the evidence behind the assessment, NOT the probability that the
professor will accept a student:
90-100 = strong, direct, recent evidence
70-89  = good supporting evidence
40-69  = limited or potentially outdated evidence
0-39   = insufficient evidence
A high score does not imply an open position.
"""

EVIDENCE_RULES = """Evidence rules:
- Use only the evidence candidates listed below, which were extracted verbatim
  from crawled pages. Refer to them by id and repeat their exact quotation.
- For category 1 or 2, cite at least one positive candidate.
- If no candidate supports an opening or recruitment, do not choose category 1
  or 2. Prefer category 3 when research activity is documented, or category 4
  when the available information is insufficient.
- If there are no evidence candidates, use category 4, return an empty evidence
  array, and keep the confidence score at or below 25.
"""


def build_professor_payload(professor: Dict[str, Any]) -> Dict[str, Any]:
    research = professor.get("research") or {}
    links = professor.get("links") or {}
    publications = []
    for publication in (professor.get("publications") or [])[:20]:
        publications.append(
            {
                "title": truncate(publication.get("title") or "", 300),
                "year": publication.get("year"),
                "venue": truncate(publication.get("venue") or "", 160) or None,
                "url": publication.get("url"),
            }
        )
    return {
        "name": professor.get("name"),
        "title": professor.get("title"),
        "department": professor.get("department"),
        "university": professor.get("university"),
        "email": professor.get("email"),
        "faculty_profile": professor.get("profile_url"),
        "research_interests_from_page": research.get("interests") or [],
        "research_methodologies_from_page": research.get("methodologies") or [],
        "technologies_from_page": research.get("technologies") or [],
        "current_projects_from_page": research.get("projects") or [],
        "laboratory": research.get("lab_name"),
        "laboratory_links": [
            entry.get("url") for entry in (research.get("lab_links") or []) if entry.get("url")
        ],
        "group_affiliations": research.get("group_affiliations") or [],
        "center_affiliations": research.get("center_affiliations") or [],
        "academic_profile_links": [
            entry.get("url") for entry in (links.get("academic_profiles") or []) if entry.get("url")
        ],
        "publications": publications,
        "profile_text_excerpt": truncate(
            research.get("text_excerpt") or "", 5200
        ),
        "source_urls": (professor.get("sources") or [])[:20],
    }


def evidence_candidates(professor: Dict[str, Any]) -> List[Dict[str, Any]]:
    evidence = (professor.get("opportunity") or {}).get("evidence") or []
    candidates = []
    for index, item in enumerate(evidence[:8], start=1):
        candidates.append(
            {
                "id": f"E{index}",
                "url": item.get("url"),
                "quote": truncate(item.get("quote") or "", 500),
                "date": item.get("date"),
                "current": item.get("current"),
                "direction": item.get("direction") or "positive",
                "reasons": item.get("reasons") or [],
            }
        )
    return candidates


def format_evidence_block(candidates: List[Dict[str, Any]]) -> str:
    if not candidates:
        return "EVIDENCE CANDIDATES: none.\n"
    lines = ["EVIDENCE CANDIDATES (verbatim from crawled pages):"]
    for item in candidates:
        date = item.get("date") or "date unknown"
        current = (
            "current"
            if item.get("current") is True
            else ("possibly outdated" if item.get("current") is False else "recency unknown")
        )
        lines.append(
            f"[{item['id']}] {item.get('direction', 'positive')} evidence | "
            f"{date} | {current} | {item.get('url')}\n"
            f"    QUOTE: {item.get('quote')}"
        )
    return "\n".join(lines) + "\n"


def format_publications(professor: Dict[str, Any]) -> str:
    publications = professor.get("publications") or []
    if not publications:
        return "PUBLICATIONS: none collected.\n"
    lines = ["PUBLICATIONS (explicitly listed on crawled pages):"]
    for publication in publications[:20]:
        year = publication.get("year") or "year unknown"
        venue = publication.get("venue") or "venue not listed"
        lines.append(f"- {publication.get('title')} ({year}). {venue}.")
    return "\n".join(lines) + "\n"


def build_prompt(sections: List[str], professor: Dict[str, Any]) -> str:
    payload = build_professor_payload(professor)
    candidates = evidence_candidates(professor)
    parts = [
        SCHEMA,
        "\n".join(sections),
        CATEGORY_DEFINITIONS,
        CONFIDENCE_DEFINITIONS,
        EVIDENCE_RULES,
        "PROFESSOR DATA (JSON):\n"
        + json.dumps(payload, indent=2, ensure_ascii=False),
        format_publications(professor),
        format_evidence_block(candidates),
        (
            "Reminder: base every claim on the data above. If the evidence is "
            "insufficient, say so plainly. Return ONLY the JSON object."
        ),
    ]
    return "\n\n".join(part for part in parts if part)
