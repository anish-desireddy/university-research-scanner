"""Optional Playwright fallback for JavaScript-rendered pages.

Playwright is used only for pages the ordinary Scrapy/BeautifulSoup pass marked
as JavaScript-suspect. It is never required for a scan. If it is not installed,
the crawl is preserved and a warning is added to the report.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.crawler.extraction import analyze_page
from app.utils import now_iso, clean_text, truncate, unique_strings

logger = logging.getLogger("urd.crawler")


class PlaywrightUnavailable(RuntimeError):
    pass


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except Exception:
        return False


def render_pages(
    urls: List[str], timeout_ms: int = 25000, max_pages: int = 6
) -> List[Dict[str, Any]]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise PlaywrightUnavailable(
            "Playwright is not installed. Install it with: pip install playwright "
            "and playwright install chromium"
        ) from exc

    results: List[Dict[str, Any]] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 Chrome/120 Safari/537.36"
            )
        )
        try:
            for url in urls[:max_pages]:
                page = context.new_page()
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                    page.wait_for_timeout(1200)
                    results.append({"url": url, "html": page.content()})
                except Exception as exc:
                    results.append({"url": url, "error": str(exc)})
                finally:
                    page.close()
        finally:
            browser.close()
    return results


def _minimal_record(person: Dict[str, Any], university: str, department: str) -> Dict[str, Any]:
    publications = person.get("publications") or []
    evidence = person.get("evidence") or []
    return {
        "id": "",
        "name": person.get("name") or "",
        "title": person.get("title"),
        "department": person.get("department") or department,
        "university": university,
        "email": person.get("email"),
        "profile_url": person.get("profile_url"),
        "personal_website": person.get("personal_website"),
        "research": {
            "interests": person.get("research_interests") or [],
            "methodologies": person.get("methodologies") or [],
            "technologies": person.get("technologies") or [],
            "projects": person.get("projects") or [],
            "lab_name": person.get("lab_name"),
            "lab_links": person.get("lab_links") or [],
            "center_affiliations": [],
            "group_affiliations": person.get("affiliations") or [],
            "text_excerpt": truncate(person.get("text_excerpt") or "", 5000),
            "summary": None,
            "publication_analysis": None,
            "ai_generated": False,
        },
        "publications": publications,
        "links": {
            "faculty_profile": person.get("profile_url"),
            "personal_website": person.get("personal_website"),
            "laboratory": ((person.get("lab_links") or [{}])[0].get("url") if person.get("lab_links") else None),
            "academic_profiles": person.get("academic_profiles") or [],
        },
        "opportunity": {
            "category": None,
            "category_label": None,
            "confidence": None,
            "confidence_explanation": None,
            "explanation": None,
            "evidence": evidence,
            "evidence_found": bool(evidence),
            "status": "not_analyzed",
        },
        "sources": [person.get("profile_url") or person.get("source_url")],
        "provenance": {
            "explicit_fields": [],
            "linked_page_fields": [],
            "ai_generated_fields": [],
        },
        "field_sources": person.get("field_sources") or {},
        "page_types": ["js_rendered"],
    }


def enrich_crawl_data(
    crawl_data: Dict[str, Any],
    options: Dict[str, Any],
    progress_callback: Optional[Any] = None,
) -> Dict[str, Any]:
    candidates = crawl_data.get("js_candidates") or []
    if not candidates:
        return crawl_data
    if not playwright_available():
        warning = (
            "Some pages appeared to require JavaScript rendering, but Playwright "
            "is not installed. Server-rendered content was preserved."
        )
        crawl_data.setdefault("warnings", []).append(warning)
        return crawl_data

    logger.info("Rendering %s JavaScript-suspect pages with Playwright", min(6, len(candidates)))
    try:
        rendered = render_pages(
            candidates,
            timeout_ms=int(options.get("playwright_timeout_ms", 25000)),
        )
    except Exception as exc:
        logger.exception("Playwright rendering failed")
        crawl_data.setdefault("warnings", []).append(
            f"Playwright rendering failed: {type(exc).__name__}: {exc}"
        )
        return crawl_data

    rendered_count = 0
    new_ids = 0
    by_profile = {
        (professor.get("profile_url") or ""): professor
        for professor in crawl_data.get("professors") or []
    }
    by_name = {
        (professor.get("name") or "").casefold(): professor
        for professor in crawl_data.get("professors") or []
    }
    university = crawl_data.get("university") or ""
    department = crawl_data.get("department") or ""
    for result in rendered:
        if result.get("error") or not result.get("html"):
            continue
        url = result["url"]
        try:
            analysis = analyze_page(result["html"], url)
        except Exception:
            logger.exception("Could not analyze Playwright page %s", url)
            continue
        rendered_count += 1
        crawl_data.setdefault("pages", []).append(
            {
                "url": url,
                "title": analysis.get("title") or "",
                "page_type": analysis.get("page_type") or "content",
                "status": 200,
                "depth": 0,
                "professors_found": len(analysis.get("persons") or []),
                "publications_found": analysis.get("publication_count", 0),
                "evidence_found": len(analysis.get("evidence") or []),
                "js_rendered": True,
            }
        )
        for person in analysis.get("persons") or []:
            if person.get("page_type") != "profile":
                continue
            existing = by_profile.get(person.get("profile_url") or "") or by_name.get(
                (person.get("name") or "").casefold()
            )
            if existing:
                research = existing.setdefault("research", {})
                if not research.get("interests") and person.get("research_interests"):
                    research["interests"] = person["research_interests"]
                if not research.get("text_excerpt") and person.get("text_excerpt"):
                    research["text_excerpt"] = truncate(person["text_excerpt"], 5000)
                known = {
                    clean_text(publication.get("title")).casefold()
                    for publication in existing.get("publications") or []
                }
                for publication in person.get("publications") or []:
                    key = clean_text(publication.get("title")).casefold()
                    if key and key not in known:
                        existing.setdefault("publications", []).append(publication)
                        known.add(key)
                if person.get("evidence"):
                    existing.setdefault("opportunity", {})
                    known_evidence = {
                        clean_text(item.get("quote")).casefold()
                        for item in existing["opportunity"].get("evidence") or []
                    }
                    for item in person["evidence"]:
                        key = clean_text(item.get("quote")).casefold()
                        if key and key not in known_evidence:
                            existing["opportunity"].setdefault("evidence", []).append(item)
                            known_evidence.add(key)
                existing.setdefault("sources", [])
                if url not in existing["sources"]:
                    existing["sources"].append(url)
            elif person.get("academic") is True:
                new_ids += 1
                record = _minimal_record(person, university, department)
                record["id"] = f"prof_js_{new_ids:03d}"
                crawl_data.setdefault("professors", []).append(record)

    stats = crawl_data.setdefault("stats", {})
    stats["js_pages_rendered"] = rendered_count
    stats["professors_identified"] = len(crawl_data.get("professors") or [])
    stats["publications_collected"] = sum(
        len(professor.get("publications") or [])
        for professor in crawl_data.get("professors") or []
    )
    if rendered_count:
        crawl_data.setdefault("warnings", []).append(
            f"Playwright rendered {rendered_count} JavaScript-dependent page(s)."
        )
    crawl_data["js_candidates"] = []
    crawl_data["completed_at"] = crawl_data.get("completed_at") or now_iso()
    if progress_callback:
        progress_callback(
            {
                "stage": "publications",
                "pages": int(stats.get("pages_visited") or 0) + rendered_count,
                "professors": len(crawl_data.get("professors") or []),
                "publications": stats.get("publications_collected", 0),
                "warnings": len(crawl_data.get("warnings") or []),
                "errors": len(crawl_data.get("errors") or []),
                "external_domains": len(crawl_data.get("external_domains") or []),
                "max_pages": options.get("max_pages"),
            }
        )
    return crawl_data
