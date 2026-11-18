from __future__ import annotations

import json
from pathlib import Path

from app.config import default_scan_options, load_config
from app.crawler.spider import UniversityCrawlerSpider


def _spider(tmp_path: Path) -> UniversityCrawlerSpider:
    config = load_config()
    options = default_scan_options(config)
    job = {
        "start_url": "https://example.edu/directory/",
        "config": options,
        "output_path": str(tmp_path / "out.json"),
        "progress_path": str(tmp_path / "progress.jsonl"),
    }
    job_path = tmp_path / "job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    spider = UniversityCrawlerSpider(job_path=str(job_path))
    spider.university = "Example University"
    spider.department = "Computer Science"
    return spider


def _person(name: str, title: str, section: str, page_type: str = "listing"):
    return {
        "name": name,
        "title": title,
        "department": "Computer Science",
        "email": f"{name.lower().replace(' ', '.')}@example.edu",
        "profile_url": "https://example.edu/directory/" + name.lower().replace(" ", "-") + "/",
        "section": section,
        "academic": True if "Professor" in title else False,
        "page_type": page_type,
        "source_url": "https://example.edu/directory/",
        "field_sources": {"name": ["https://example.edu/directory/"]},
    }


def test_duplicate_names_are_merged_and_publications_retained(tmp_path):
    spider = _spider(tmp_path)
    listing = _person("Kurt Maly", "Professor", "Faculty")
    profile = _person("Maly Kurt", "Professor", "Faculty", page_type="profile")
    profile["publications"] = [
        {
            "title": "An example publication",
            "year": 2024,
            "venue": "Example Journal",
            "url": "https://example.edu/pub/1",
            "topic": None,
            "source_url": "https://example.edu/directory/kurt-maly/",
        }
    ]
    spider._merge_person(listing)
    spider._merge_person(profile)
    assert len(spider.professors) == 1
    final = spider._finalize_professors()
    assert len(final) == 1
    assert final[0]["name"] == "Kurt Maly"
    assert len(final[0]["publications"]) == 1


def test_middle_initial_name_variant_is_merged(tmp_path):
    spider = _spider(tmp_path)
    spider._merge_person(_person("Steven J. Zeil", "Professor", "Faculty"))
    spider._merge_person(_person("Steven Zeil", "Professor", "Faculty", page_type="profile"))
    final = spider._finalize_professors()
    assert len(final) == 1
    assert final[0]["name"] == "Steven J. Zeil"


def test_non_academic_staff_is_excluded(tmp_path):
    spider = _spider(tmp_path)
    spider._merge_person(_person("Pat Morgan", "Office Manager", "Staff"))
    final = spider._finalize_professors()
    assert final == []
    assert any(
        record["reason"] == "excluded_non_academic_person"
        for record in spider.manual_review
    )


def test_admin_title_containing_word_faculty_is_excluded(tmp_path):
    spider = _spider(tmp_path)
    listing = _person("Bill Sympson", "Higher Ed Teach Res Asst", "Staff")
    listing["academic"] = True
    profile = _person(
        "Bill Sympson", "Faculty Affairs & Strategic Initiatives", "Faculty", page_type="profile"
    )
    profile["academic"] = True
    spider._merge_person(listing)
    spider._merge_person(profile)
    final = spider._finalize_professors()
    assert final == []
    assert any(
        record["reason"] == "excluded_non_academic_person"
        and record["professor"] == "Bill Sympson"
        for record in spider.manual_review
    )


def test_real_academic_rank_with_faculty_affairs_still_included(tmp_path):
    spider = _spider(tmp_path)
    spider._merge_person(
        _person("Jane Doe", "Professor and Associate Dean for Faculty Affairs", "Faculty")
    )
    final = spider._finalize_professors()
    assert len(final) == 1
    assert final[0]["name"] == "Jane Doe"


def test_faculty_without_research_still_included(tmp_path):
    spider = _spider(tmp_path)
    spider._merge_person(_person("Jane Doe", "Associate Professor", "Faculty"))
    final = spider._finalize_professors()
    assert len(final) == 1
    assert final[0]["name"] == "Jane Doe"
