"""Shared test helpers."""

from __future__ import annotations

from typing import Any, Dict, List


def make_professor(
    name: str = "Jane Doe",
    category: int = 3,
    confidence: int = 55,
    summary: str = "Jane Doe studies accessible computing and human-computer interaction. She works with students on accessible data visualization projects.",
    evidence: List[Dict[str, Any]] | None = None,
    publications: List[Dict[str, Any]] | None = None,
    email: str = "jane.doe@example.edu",
) -> Dict[str, Any]:
    evidence = evidence if evidence is not None else [
        {
            "url": "https://example.edu/directory/jane-doe",
            "quote": "I welcome undergraduate students who are interested in accessibility research.",
            "page_title": "Jane Doe",
            "date": "2026-01-10",
            "current": True,
            "direction": "positive",
            "reasons": ["student invitation"],
            "explanation": "The professor explicitly invites undergraduates to participate in research.",
        }
    ]
    publications = publications if publications is not None else [
        {
            "title": "Designing accessible data visualizations for blind students",
            "year": 2024,
            "venue": "ACM Transactions on Accessible Computing",
            "url": "https://example.edu/pub/1",
            "topic": None,
            "source_url": "https://example.edu/directory/jane-doe",
        }
    ]
    return {
        "id": "prof_001",
        "name": name,
        "title": "Associate Professor",
        "department": "Computer Science",
        "university": "Example University",
        "email": email,
        "profile_url": "https://example.edu/directory/jane-doe",
        "personal_website": "https://janedoe.example.org/",
        "research": {
            "interests": ["Human-computer interaction", "Accessible computing"],
            "methodologies": ["qualitative research", "usability testing"],
            "technologies": ["Python"],
            "projects": ["Accessible data visualization for blind students"],
            "lab_name": "Doe Accessibility Lab",
            "lab_links": [
                {"url": "https://doe-lab.example.org/", "label": "Doe Accessibility Lab"}
            ],
            "center_affiliations": [],
            "group_affiliations": ["Doe Accessibility Lab"],
            "text_excerpt": "Research interests: accessible computing.",
            "summary": summary,
            "publication_analysis": "The publications focus on accessible data visualization and usability testing.",
            "publication_topics": ["accessible visualization", "usability testing"],
            "ai_generated": True,
            "ai_interests": ["accessibility", "human-centered design"],
            "ai_methodologies": ["usability testing"],
            "ai_technologies": ["Python"],
            "ai_current_projects": ["Accessible data visualization for blind students"],
        },
        "publications": publications,
        "links": {
            "faculty_profile": "https://example.edu/directory/jane-doe",
            "personal_website": "https://janedoe.example.org/",
            "laboratory": "https://doe-lab.example.org/",
            "academic_profiles": [
                {
                    "url": "https://scholar.google.com/citations?user=example",
                    "label": "Google Scholar",
                }
            ],
        },
        "opportunity": {
            "category": category,
            "category_label": {
                1: "Confirmed open position",
                2: "Actively recruiting / welcoming students",
                3: "Potential opportunity",
                4: "No opportunity information found",
            }.get(category),
            "confidence": confidence,
            "confidence_explanation": "The evidence is current and directly relevant, although it does not describe a specific vacancy.",
            "explanation": "The professor explicitly welcomes undergraduate students to participate in accessibility research.",
            "evidence": evidence,
            "evidence_found": bool(evidence),
            "status": "analyzed",
            "assessment_status": "complete",
        },
        "sources": [
            "https://example.edu/directory/jane-doe",
            "https://example.edu/directory/",
        ],
        "provenance": {
            "explicit_fields": ["name", "title", "email", "research", "publications"],
            "linked_page_fields": ["research_interests", "opportunity_evidence"],
            "ai_generated_fields": [
                "research.summary",
                "research.ai_interests",
                "research.publication_analysis",
                "opportunity.category",
                "opportunity.confidence",
                "opportunity.explanation",
            ],
        },
        "field_sources": {
            "name": ["https://example.edu/directory/jane-doe"],
            "publications": ["https://example.edu/directory/jane-doe"],
        },
        "page_types": ["listing", "profile"],
        "analysis": {
            "status": "complete",
            "provider": "ollama",
            "model": "llama3.2:latest",
            "generated_at": "2026-11-18T12:00:00+00:00",
            "cached": False,
        },
    }


def make_result(professors: List[Dict[str, Any]] | None = None) -> Dict[str, Any]:
    professors = professors if professors is not None else [make_professor()]
    categories = {1: 0, 2: 0, 3: 0, 4: 0}
    for professor in professors:
        category = (professor.get("opportunity") or {}).get("category")
        if category in categories:
            categories[category] += 1
    summary = {
        "professors_identified": len(professors),
        "professors_analyzed": sum(
            1 for professor in professors if (professor.get("opportunity") or {}).get("category")
        ),
        "confirmed_open": categories[1],
        "actively_recruiting": categories[2],
        "potential_opportunity": categories[3],
        "no_information": categories[4],
        "not_analyzed": sum(
            1 for professor in professors if (professor.get("opportunity") or {}).get("category") is None
        ),
        "pages_visited": 12,
        "publications_collected": sum(len(professor.get("publications") or []) for professor in professors),
        "evidence_snippets": sum(
            len((professor.get("opportunity") or {}).get("evidence") or []) for professor in professors
        ),
        "errors": 0,
        "manual_review": 0,
    }
    return {
        "schema_version": "1.0",
        "application": {"name": "University Research Discovery", "version": "1.0.0"},
        "scan": {
            "id": "scan_2026-11-18_120000",
            "url": "https://www.cs.odu.edu/",
            "final_url": "https://www.odu.edu/computer-science",
            "created_at": "2026-11-18T12:00:00+00:00",
            "completed_at": "2026-11-18T12:01:00+00:00",
            "status": "completed",
            "config": {"max_depth": 3, "max_pages": 100},
            "university": "Example University",
            "department": "Computer Science",
            "summary": summary,
            "ai": {
                "provider": "ollama",
                "model": "llama3.2:latest",
                "status": "complete",
                "message": "AI analysis completed for all professors.",
                "setup_instructions": [],
                "analyses_completed": summary["professors_analyzed"],
                "analyses_failed": 0,
                "errors": [],
            },
            "stats": summary,
            "warnings": [],
        },
        "university": "Example University",
        "department": "Computer Science",
        "professors": professors,
        "crawl": {
            "stats": summary,
            "pages": [
                {
                    "url": "https://example.edu/directory/",
                    "title": "Directory",
                    "page_type": "listing",
                    "status": 200,
                    "depth": 1,
                    "professors_found": len(professors),
                    "publications_found": 0,
                    "evidence_found": 0,
                }
            ],
            "errors": [],
            "manual_review": [],
            "external_domains": ["doe-lab.example.org"],
            "warnings": [],
            "js_candidates": [],
        },
        "methodology": {
            "discovery": "Relevance-scored crawl.",
            "extraction": "Semantic HTML extraction.",
            "ai_provider": "Ollama",
            "ai_model": "llama3.2:latest",
            "confidence_meaning": "Evidence strength, not probability of acceptance.",
        },
    }
