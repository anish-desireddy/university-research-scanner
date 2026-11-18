from __future__ import annotations

from pathlib import Path

from app.crawler.extraction import (
    _looks_like_person_name,
    analyze_page,
    normalize_person_name,
)

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _html(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_listing_extracts_faculty_and_staff():
    analysis = analyze_page(_html("directory.html"), "https://example.edu/directory/")

    assert analysis["page_type"] == "listing"
    assert analysis["university"] == "Example University"
    names = {person["name"]: person for person in analysis["persons"]}
    assert {"Jane Doe", "John Smith", "Pat Morgan"}.issubset(names)

    jane = names["Jane Doe"]
    assert jane["title"] == "Associate Professor"
    assert jane["department"] == "Computer Science"
    assert jane["email"] == "jane.doe@example.edu"
    assert jane["academic"] is True
    assert jane["profile_url"].endswith("/directory/jane-doe/")

    pat = names["Pat Morgan"]
    assert pat["section"] == "Staff"
    assert pat["academic"] is False
    assert pat["title"] == "Office Manager"


def test_profile_extracts_research_publications_and_evidence():
    analysis = analyze_page(_html("profile.html"), "https://example.edu/directory/jane-doe/")
    assert analysis["page_type"] == "profile"
    professor = [person for person in analysis["persons"] if person["page_type"] == "profile"][0]

    assert professor["name"] == "Jane Doe"
    assert professor["title"] == "Associate Professor"
    assert professor["department"] == "Computer Science"
    assert professor["email"] == "jane.doe@example.edu"
    assert "Human-computer interaction" in professor["research_interests"]
    assert "Accessible computing" in professor["research_interests"]
    assert "qualitative research" in professor["methodologies"]
    assert "Python" in professor["technologies"]

    assert len(professor["publications"]) == 2
    assert professor["publications"][0]["year"] == 2024
    assert "accessible data visualizations" in professor["publications"][0]["title"].lower()

    assert professor["lab_links"]
    assert professor["lab_links"][0]["url"] == "https://doe-lab.example.org/"
    assert professor["academic_profiles"]
    assert any("scholar.google" in profile["url"] for profile in professor["academic_profiles"])

    assert professor["evidence"]
    quote = professor["evidence"][0]["quote"].lower()
    assert "undergraduate" in quote
    assert professor["evidence"][0]["url"] == "https://example.edu/directory/jane-doe/"


def test_profile_without_opportunity_evidence():
    analysis = analyze_page(
        _html("profile_no_evidence.html"), "https://example.edu/directory/john-smith/"
    )
    professor = [person for person in analysis["persons"] if person["page_type"] == "profile"][0]
    assert professor["name"] == "John Smith"
    assert professor["evidence"] == []
    assert len(professor["publications"]) == 1


def test_name_helpers_reject_navigation_and_accept_real_names():
    assert _looks_like_person_name("Jane Doe")
    assert _looks_like_person_name("Mohammad S. Obaidat")
    assert not _looks_like_person_name("Course Schedule")
    assert not _looks_like_person_name("Faculty & Staff")
    assert not _looks_like_person_name("Monarch Workflow Manager")
    assert normalize_person_name("Doe, Jane") == "Jane Doe"


def test_publication_without_quotes_is_not_fabricated():
    analysis = analyze_page(_html("profile_no_evidence.html"), "https://example.edu/directory/john-smith/")
    publication = analysis["publications"][0]
    assert publication["title"].startswith("Scheduling in heterogeneous clouds")
    assert publication["year"] == 2023
