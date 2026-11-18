"""Scrapy spider for broad academic discovery."""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlsplit

import scrapy
from scrapy.http import Response

from app.crawler import extraction
from app.crawler.relevance import score_link
from app.utils import (
    atomic_write_json,
    clean_text,
    normalize_url,
    now_iso,
    registrable_domain,
    same_site,
    truncate,
    unique_strings,
)

logger = logging.getLogger("urd.crawler")


def _empty_professor(person: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "name": person.get("name") or "",
        "title": person.get("title"),
        "department": person.get("department"),
        "email": person.get("email"),
        "profile_url": person.get("profile_url"),
        "personal_website": person.get("personal_website"),
        "section": person.get("section"),
        "academic": person.get("academic"),
        "university": None,
        "research_interests": [],
        "research_text": "",
        "methodologies": [],
        "technologies": [],
        "projects": [],
        "publications": [],
        "lab_links": [],
        "center_links": [],
        "academic_profiles": [],
        "lab_name": None,
        "affiliations": [],
        "evidence": [],
        "source_urls": [],
        "explicit_fields": set(),
        "linked_fields": set(),
        "field_sources": {},
        "text_excerpt": "",
        "page_types": set(),
    }


class UniversityCrawlerSpider(scrapy.Spider):
    name = "university"

    def __init__(self, job_path: str, **kwargs: Any):
        super().__init__(**kwargs)
        self.job = json.loads(Path(job_path).read_text(encoding="utf-8"))
        self.start_url = self.job["start_url"]
        self.config = self.job["config"]
        self.output_path = Path(self.job["output_path"])
        self.progress_path = Path(self.job["progress_path"])
        self.max_depth = int(self.config["max_depth"])
        self.max_pages = int(self.config["max_pages"])
        self.max_external_domains = int(self.config["max_external_domains"])
        self.max_pages_per_external_domain = int(
            self.config.get("max_pages_per_external_domain", 6)
        )
        self.use_playwright = bool(self.config.get("use_playwright", True))
        self.start_domain = registrable_domain(self.start_url)
        self.start_path = ""
        self.start_urls = [self.start_url]

        self.pages_visited = 0
        self.pages_requested = 1
        self.professors: Dict[str, Dict[str, Any]] = {}
        self.professor_order: List[str] = []
        self.page_records: List[Dict[str, Any]] = []
        self.errors: List[Dict[str, Any]] = []
        self.manual_review: List[Dict[str, Any]] = []
        self.warnings: List[str] = []
        self.external_domains: List[str] = []
        self.external_domain_pages: Dict[str, int] = {}
        self.seen_urls = {self.start_url}
        self.js_candidates: List[str] = []
        self.university = ""
        self.department = ""
        self.final_start_url = self.start_url
        self.started_at = now_iso()
        self._started_clock = time.time()
        self._last_progress = 0.0
        self._progress_handle = None
        self.fatal_error: Optional[str] = None

    # ------------------------------------------------------------------
    # Requests and page parsing
    # ------------------------------------------------------------------

    def _initial_request(self) -> scrapy.Request:
        self._open_progress()
        return scrapy.Request(
            self.start_url,
            callback=self.parse_page,
            errback=self.handle_error,
            meta={"depth": 0, "associated_professor": None, "parent_url": None},
            priority=1000,
            dont_filter=True,
        )

    async def start(self) -> Any:
        # Scrapy 2.13+ uses the async start() entry point. Keeping
        # start_requests() as well supports older Scrapy releases.
        yield self._initial_request()

    def start_requests(self) -> Iterable[scrapy.Request]:
        yield self._initial_request()

    def _open_progress(self) -> None:
        if self._progress_handle is not None:
            return
        self.progress_path.parent.mkdir(parents=True, exist_ok=True)
        self._progress_handle = self.progress_path.open("a", encoding="utf-8", buffering=1)
        self._write_progress("accessing", "Starting crawl")

    def _write_progress(self, stage: str, message: str = "") -> None:
        if not self._progress_handle:
            return
        payload = {
            "stage": stage,
            "message": message,
            "pages": self.pages_visited,
            "pages_requested": self.pages_requested,
            "max_pages": self.max_pages,
            "professors": len(self.professors),
            "profiles": sum(
                1
                for page in self.page_records
                if page.get("page_type") == "profile"
            ),
            "publications": sum(
                len(prof.get("publications") or []) for prof in self.professors.values()
            ),
            "external_domains": len(self.external_domains),
            "warnings": len(self.warnings),
            "errors": len(self.errors),
            "elapsed_seconds": round(time.time() - self._started_clock, 1),
            "current_url": self.page_records[-1]["url"] if self.page_records else self.start_url,
            "timestamp": now_iso(),
        }
        try:
            self._progress_handle.write(json.dumps(payload, ensure_ascii=False) + "\n")
        except OSError:
            logger.exception("Could not write crawler progress")

    def parse_page(self, response: Response) -> Iterable[scrapy.Request]:
        self.pages_visited += 1
        self.final_start_url = response.url if self.pages_visited == 1 else self.final_start_url
        page_url = normalize_url(response.url) or response.url
        if self.pages_visited == 1:
            raw_path = (urlsplit(page_url).path or "/").rstrip("/")
            segments = [segment for segment in raw_path.split("/") if segment]
            if len(segments) >= 2:
                self.start_path = "/" + "/".join(segments[:2])
            else:
                self.start_path = raw_path or "/"
        associated_key = response.meta.get("associated_professor")
        profile_candidate = bool(response.meta.get("profile_candidate"))
        depth = int(response.meta.get("depth", 0))

        if response.status >= 400:
            self._record_page_error(
                page_url,
                f"HTTP {response.status}",
                response.meta.get("parent_url"),
                response.meta.get("associated_professor"),
            )
            self._write_progress(self._stage(), "Page returned an error status")
            return
        content_type = response.headers.get("Content-Type", b"").decode("latin-1", "ignore")
        if "html" not in content_type.lower() and response.text:
            # Some servers label HTML as text/plain. Only skip clear binaries.
            if content_type and not any(
                value in content_type.lower() for value in ("text", "xml", "xhtml")
            ):
                self.manual_review.append(
                    {
                        "url": page_url,
                        "reason": "non_html_content",
                        "detail": content_type,
                    }
                )
                return
        try:
            analysis = extraction.analyze_page(response.text, page_url)
        except Exception as exc:  # parsing failures are recorded, never hidden
            logger.exception("Extraction failed for %s", page_url)
            self._record_page_error(page_url, f"Extraction error: {exc}", response.meta.get("parent_url"))
            return

        inferred_university = analysis.get("university") or ""
        if inferred_university and (
            not self.university
            or (
                re.search(r"\b(university|college|institute|polytechnic|academy)\b", inferred_university, re.I)
                and not re.search(
                    r"\b(university|college|institute|polytechnic|academy)\b", self.university, re.I
                )
            )
        ):
            self.university = inferred_university
        if not self.department and analysis.get("department"):
            self.department = analysis["department"]

        page_type = analysis["page_type"]
        if page_type == "content" and associated_key:
            page_type = "linked_research"
        page_record = {
            "url": page_url,
            "title": analysis.get("title") or "",
            "page_type": page_type,
            "status": response.status,
            "depth": depth,
            "professors_found": len(analysis.get("persons") or []),
            "publications_found": analysis.get("publication_count", 0),
            "evidence_found": len(analysis.get("evidence") or []),
            "external_domain": registrable_domain(page_url) != self.start_domain,
        }
        self.page_records.append(page_record)

        if analysis.get("js_suspect") and self.use_playwright:
            self.js_candidates.append(page_url)

        if self._accept_persons(analysis, associated_key, profile_candidate):
            persons = analysis.get("persons") or []
            if page_type == "profile":
                # A profile page's sidebar may link to colleagues; only merge
                # the professor described by the profile itself.
                persons = [person for person in persons if person.get("page_type") == "profile"]
            for person in persons:
                self._merge_person(person, linked=False)

        self._associate_linked_page(analysis, associated_key)
        self._associate_page_evidence(analysis, associated_key, page_type)

        links = self._collect_links(page_url, analysis, associated_key, page_type, depth)
        for request in links:
            if self.pages_requested >= self.max_pages:
                self.warnings.append(
                    f"Page cap reached ({self.max_pages}); remaining links were not queued."
                )
                break
            self.pages_requested += 1
            yield request

        if self.pages_visited % 3 == 0 or time.time() - self._last_progress > 2:
            self._last_progress = time.time()
            self._write_progress(self._stage(), f"Processed {self.pages_visited} pages")

    def _within_start_path(self, url: str) -> bool:
        if not self.start_path or self.start_path == "/":
            return True
        path = (urlsplit(url).path or "/").rstrip("/")
        return path == self.start_path or path.startswith(self.start_path + "/")

    def _accept_persons(
        self,
        analysis: Dict[str, Any],
        associated_key: Optional[str],
        profile_candidate: bool = False,
    ) -> bool:
        if analysis.get("page_type") == "profile":
            return (
                self._within_start_path(analysis["url"])
                or bool(associated_key)
                or profile_candidate
            )
        if associated_key:
            # A linked lab or personal page contributes research evidence, not
            # every person named on that page.
            return False
        return self._within_start_path(analysis["url"])

    def _stage(self) -> str:
        profiles = sum(1 for page in self.page_records if page.get("page_type") == "profile")
        publications = sum(
            len(prof.get("publications") or []) for prof in self.professors.values()
        )
        if self.pages_visited <= 1:
            return "accessing"
        if not self.professors:
            return "discovering"
        if profiles == 0:
            return "identifying"
        if publications == 0:
            return "extracting"
        return "publications"

    def _collect_links(
        self,
        page_url: str,
        analysis: Dict[str, Any],
        associated_key: Optional[str],
        page_type: str,
        depth: int,
    ) -> Iterable[scrapy.Request]:
        scored: Dict[str, Dict[str, Any]] = {}
        for anchor in analysis.get("anchors") or []:
            target = anchor.get("url")
            if not target:
                continue
            scored_link = score_link(
                page_url, target, anchor.get("text", ""), anchor.get("context", "")
            )
            if scored_link.get("crawlable") and scored_link.get("internal"):
                target_path = (urlsplit(target).path or "/").rstrip("/")
                if self._within_start_path(target):
                    scored_link["score"] = round(scored_link["score"] + 2.0, 2)
                    scored_link["reason"] += "; within submitted department"
                    if scored_link.get("kind") == "listing" and re.search(
                        r"/(directory|faculty|facultystaff|people|staff)(/|$)",
                        target_path,
                        re.I,
                    ):
                        scored_link["score"] = round(scored_link["score"] + 2.0, 2)
                        scored_link["reason"] += "; primary faculty directory"
                elif self.start_path and self.start_path != "/":
                    # When the user submits a department or profile, unrelated
                    # university-wide sections should not consume the budget.
                    if scored_link.get("kind") in (
                        "listing",
                        "research",
                        "lab",
                        "personal",
                        "same_site",
                    ):
                        continue
            if not scored_link.get("crawlable"):
                if scored_link.get("kind") == "academic_profile":
                    self._note_academic_profile(associated_key, scored_link["url"], anchor.get("text", ""))
                continue
            existing = scored.get(target)
            if existing is None or scored_link["score"] > existing["score"]:
                scored[target] = scored_link

        candidates = sorted(
            scored.values(), key=lambda item: (-item["score"], item["url"])
        )
        selected: List[Dict[str, Any]] = []
        neutral_count = 0
        external_count = 0
        profile_or_listing_count = 0
        for item in candidates:
            target = item["url"]
            if target in self.seen_urls:
                continue
            if depth >= self.max_depth:
                continue
            if page_type == "profile" and item["kind"] in ("listing", "profile"):
                # Global directory/navigation links and colleagues' profile
                # links on a profile page are not part of this professor's
                # research presence.
                continue
            internal = bool(item.get("internal", same_site(page_url, target)))
            domain = registrable_domain(target)
            if not internal:
                if domain in self.external_domain_pages:
                    if self.external_domain_pages[domain] >= self.max_pages_per_external_domain:
                        continue
                    external_count += 1
                else:
                    if len(self.external_domains) >= self.max_external_domains:
                        self._note_skipped_external(target, "external domain limit reached")
                        continue
                    external_count += 1
                if external_count > 6:
                    continue
            else:
                if item["kind"] in ("profile", "listing", "pagination"):
                    profile_or_listing_count += 1
                    if profile_or_listing_count > 60:
                        continue
                elif item["score"] < 1.0:
                    neutral_count += 1
                    if neutral_count > 8:
                        continue
                    if page_type == "content" and depth >= 1 and item["score"] < 1.0:
                        # Neutral same-site navigation is only useful near the
                        # entry point, where the faculty link often lives.
                        continue
            selected.append(item)
            if len(selected) >= 80:
                break

        for item in selected:
            target = item["url"]
            internal = bool(item.get("internal", same_site(page_url, target)))
            domain = registrable_domain(target)
            if not internal:
                if domain not in self.external_domains:
                    self.external_domains.append(domain)
                self.external_domain_pages[domain] = self.external_domain_pages.get(domain, 0) + 1
            self.seen_urls.add(target)
            meta: Dict[str, Any] = {
                "depth": depth + 1,
                "parent_url": page_url,
                "associated_professor": associated_key,
                "profile_candidate": bool(
                    page_type == "listing"
                    and item["kind"] == "profile"
                    and self._within_start_path(page_url)
                ),
            }
            # Links that are likely part of a professor's own academic web
            # presence inherit that professor's association.
            if associated_key and (
                item["kind"] in ("lab", "personal", "research", "same_site", "external_other")
                or (page_type == "profile" and not item.get("internal", True))
            ):
                meta["associated_professor"] = associated_key
            yield scrapy.Request(
                target,
                callback=self.parse_page,
                errback=self.handle_error,
                meta=meta,
                priority=max(0, min(900, int(item["score"] * 10))),
            )

    def _note_academic_profile(
        self, associated_key: Optional[str], url: str, label: str
    ) -> None:
        if not associated_key:
            return
        professor = self.professors.get(associated_key)
        if not professor:
            return
        entry = {"url": url, "label": clean_text(label)}
        if entry not in professor["academic_profiles"]:
            professor["academic_profiles"].append(entry)

    def _note_skipped_external(self, url: str, reason: str) -> None:
        note = {"url": url, "reason": reason, "type": "skipped_link"}
        if note not in self.manual_review and len(self.manual_review) < 200:
            self.manual_review.append(note)

    # ------------------------------------------------------------------
    # Professor merging
    # ------------------------------------------------------------------

    def _find_existing_key(self, person: Dict[str, Any]) -> Optional[str]:
        key = extraction.person_key(person.get("name") or "", person.get("email") or "")
        if key and key in self.professors:
            return key
        email = (person.get("email") or "").casefold()
        profile_url = normalize_url(person.get("profile_url") or "")
        incoming_tokens = extraction.name_token_key(person.get("name") or "")
        incoming_core = extraction.name_core(person.get("name") or "")
        for existing_key, professor in self.professors.items():
            if email and (professor.get("email") or "").casefold() == email:
                return existing_key
            if profile_url and normalize_url(professor.get("profile_url") or "") == profile_url:
                return existing_key
            existing_tokens = extraction.name_token_key(professor.get("name") or "")
            if (
                incoming_tokens
                and len(incoming_tokens) <= 4
                and incoming_tokens == existing_tokens
            ):
                return existing_key
            if (
                incoming_core
                and len(incoming_core) >= 2
                and extraction.name_core(professor.get("name") or "") == incoming_core
            ):
                return existing_key
        return None

    def _merge_person(self, person: Dict[str, Any], linked: bool = False) -> Optional[str]:
        if not person.get("name"):
            return None
        key = self._find_existing_key(person)
        if key is None:
            key = extraction.person_key(person.get("name") or "", person.get("email") or "")
            if not key:
                return None
            professor = _empty_professor(person)
            self.professors[key] = professor
            self.professor_order.append(key)
        professor = self.professors[key]

        # A longer, more specific name wins (e.g. "Mohammad S. Obaidat").
        incoming_name = extraction.normalize_person_name(person.get("name") or "")
        if incoming_name and len(incoming_name) > len(professor.get("name") or ""):
            professor["name"] = incoming_name

        for field in ("department", "email", "personal_website", "lab_name", "section"):
            value = person.get(field)
            if value and not professor.get(field):
                professor[field] = value

        incoming_title = clean_text(person.get("title"))
        if incoming_title:
            current_title = clean_text(professor.get("title"))
            if not current_title:
                professor["title"] = incoming_title
            elif not extraction.ACADEMIC_TITLE_RE.search(current_title) and extraction.ACADEMIC_TITLE_RE.search(
                incoming_title
            ):
                professor["title"] = incoming_title
            elif person.get("page_type") == "profile" and len(incoming_title) < 140:
                professor["title"] = incoming_title

        if person.get("profile_url"):
            current_profile = professor.get("profile_url")
            if not current_profile or person.get("page_type") == "profile":
                professor["profile_url"] = person["profile_url"]

        if person.get("academic") is True:
            professor["academic"] = True
        elif person.get("academic") is False and professor.get("academic") is None:
            professor["academic"] = False

        if not professor.get("university") and self.university:
            professor["university"] = self.university

        for field in (
            "research_interests",
            "methodologies",
            "technologies",
            "projects",
            "lab_links",
            "center_links",
            "academic_profiles",
            "affiliations",
        ):
            incoming = person.get(field) or []
            if incoming:
                existing = professor.setdefault(field, [])
                if field in ("lab_links", "center_links", "academic_profiles"):
                    known_urls = {entry.get("url") for entry in existing if isinstance(entry, dict)}
                    for entry in incoming:
                        if isinstance(entry, dict) and entry.get("url") not in known_urls:
                            existing.append(entry)
                            known_urls.add(entry.get("url"))
                else:
                    professor[field] = unique_strings(list(existing) + list(incoming))

        research_text = person.get("research_text") or ""
        if research_text and len(research_text) > len(professor.get("research_text") or ""):
            professor["research_text"] = research_text
        text_excerpt = person.get("text_excerpt") or ""
        if text_excerpt and len(text_excerpt) > len(professor.get("text_excerpt") or ""):
            professor["text_excerpt"] = text_excerpt

        for publication in person.get("publications") or []:
            title_key = clean_text(publication.get("title")).casefold()
            known = {
                clean_text(item.get("title")).casefold()
                for item in professor.get("publications") or []
            }
            if title_key and title_key not in known:
                professor["publications"].append(publication)

        evidence_known = {
            (item.get("url"), clean_text(item.get("quote")).casefold())
            for item in professor.get("evidence") or []
        }
        for item in person.get("evidence") or []:
            key_tuple = (item.get("url"), clean_text(item.get("quote")).casefold())
            if key_tuple not in evidence_known:
                professor["evidence"].append(item)
                evidence_known.add(key_tuple)

        source_url = person.get("source_url") or person.get("profile_url")
        if source_url and source_url not in professor["source_urls"]:
            professor["source_urls"].append(source_url)
        if person.get("page_type"):
            professor["page_types"].add(person["page_type"])

        for field, sources in (person.get("field_sources") or {}).items():
            if not sources:
                continue
            professor["field_sources"].setdefault(field, [])
            professor["field_sources"][field] = list(
                dict.fromkeys(professor["field_sources"][field] + list(sources))
            )
            if linked or person.get("page_type") not in ("profile", "listing"):
                professor["linked_fields"].add(field)
            else:
                professor["explicit_fields"].add(field)
        return key

    def _associate_linked_page(
        self, analysis: Dict[str, Any], associated_key: Optional[str]
    ) -> None:
        if not associated_key or associated_key not in self.professors:
            return
        professor = self.professors[associated_key]
        page_url = analysis["url"]
        if analysis.get("page_type") == "profile":
            return
        linked_record = {
            "name": professor["name"],
            "page_type": "linked_page",
            "source_url": page_url,
            "research_interests": analysis.get("research_interests") or [],
            "research_text": analysis.get("research_text") or "",
            "methodologies": analysis.get("methodologies") or [],
            "technologies": analysis.get("technologies") or [],
            "projects": analysis.get("projects") or [],
            "publications": analysis.get("publications") or [],
            "field_sources": {
                "research": [page_url] if analysis.get("research_interests") else [],
                "publications": [page_url] if analysis.get("publications") else [],
                "opportunity_evidence": [page_url] if analysis.get("evidence") else [],
            },
        }
        # Only merge a linked page if it actually mentions the professor. This
        # prevents a lab's news pages from attaching unrelated people.
        page_text = (analysis.get("main_text") or "").casefold()
        last_name = (professor.get("name") or "").split()[-1].casefold()
        if last_name and len(last_name) > 2 and last_name not in page_text:
            self.manual_review.append(
                {
                    "url": page_url,
                    "reason": "linked_page_without_professor_name",
                    "professor": professor["name"],
                }
            )
            return
        self._merge_person(linked_record, linked=True)

    def _associate_page_evidence(
        self,
        analysis: Dict[str, Any],
        associated_key: Optional[str],
        page_type: str,
    ) -> None:
        evidence = analysis.get("evidence") or []
        if not evidence:
            return
        if page_type in ("profile", "listing"):
            # Profile evidence was merged with the profile record itself, and
            # directory listings mix many people's text into one page.
            return
        target_key = associated_key
        if not target_key:
            # A listing page may contain a department-wide recruitment note;
            # attach it only to professors whose names appear in the page.
            page_text = (analysis.get("main_text") or "").casefold()
            for key in self.professor_order:
                professor = self.professors[key]
                last_name = (professor.get("name") or "").split()[-1].casefold()
                if last_name and len(last_name) > 2 and last_name in page_text:
                    self._merge_evidence(key, evidence)
            return
        self._merge_evidence(target_key, evidence)

    def _merge_evidence(self, key: str, evidence: List[Dict[str, Any]]) -> None:
        professor = self.professors.get(key)
        if not professor:
            return
        known = {
            (item.get("url"), clean_text(item.get("quote")).casefold())
            for item in professor.get("evidence") or []
        }
        for item in evidence:
            key_tuple = (item.get("url"), clean_text(item.get("quote")).casefold())
            if key_tuple not in known:
                professor["evidence"].append(item)
                known.add(key_tuple)

    # ------------------------------------------------------------------
    # Errors, cleanup, and output
    # ------------------------------------------------------------------

    def _record_page_error(
        self,
        url: str,
        error: str,
        parent_url: Optional[str] = None,
        professor_key: Optional[str] = None,
    ) -> None:
        record = {
            "url": url,
            "error": truncate(str(error), 500),
            "parent_url": parent_url,
            "professor": self.professors.get(professor_key, {}).get("name") if professor_key else None,
            "timestamp": now_iso(),
        }
        self.errors.append(record)
        if len(self.manual_review) < 200:
            self.manual_review.append(
                {
                    "url": url,
                    "reason": "inaccessible_page",
                    "detail": record["error"],
                }
            )

    def handle_error(self, failure: Any) -> None:
        request = getattr(failure, "request", None)
        url = normalize_url(request.url) if request is not None else "unknown"
        self._record_page_error(
            url or "unknown",
            failure.getErrorMessage() if hasattr(failure, "getErrorMessage") else str(failure),
            request.meta.get("parent_url") if request is not None else None,
            request.meta.get("associated_professor") if request is not None else None,
        )
        if self.pages_visited == 0:
            self.fatal_error = failure.getErrorMessage() if hasattr(failure, "getErrorMessage") else str(failure)
        self._write_progress(self._stage(), "A page could not be retrieved")

    def closed(self, reason: str) -> None:
        try:
            output = self.build_output(reason)
            atomic_write_json(self.output_path, output)
            self._write_progress("crawl_complete", "Crawl finished")
            logger.info(
                "Crawl complete: pages=%s professors=%s errors=%s reason=%s",
                self.pages_visited,
                len(output["professors"]),
                len(self.errors),
                reason,
            )
        except Exception:
            logger.exception("Failed to write crawl output")
            raise
        finally:
            if self._progress_handle:
                try:
                    self._progress_handle.close()
                except OSError:
                    pass

    def build_output(self, reason: str = "") -> Dict[str, Any]:
        professors = self._finalize_professors()
        if self.pages_visited > 0:
            self.final_start_url = self.page_records[0]["url"] if self.page_records else self.start_url
        stats = {
            "pages_visited": self.pages_visited,
            "pages_requested": self.pages_requested,
            "professors_identified": len(professors),
            "profile_pages": sum(1 for page in self.page_records if page["page_type"] == "profile"),
            "listing_pages": sum(1 for page in self.page_records if page["page_type"] == "listing"),
            "publications_collected": sum(
                len(prof.get("publications") or []) for prof in professors
            ),
            "evidence_snippets": sum(
                len((prof.get("opportunity") or {}).get("evidence") or [])
                for prof in professors
            ),
            "external_domains": self.external_domains,
            "errors": len(self.errors),
            "manual_review": len(self.manual_review),
            "elapsed_seconds": round(time.time() - self._started_clock, 1),
        }
        return {
            "scan": {
                "start_url": self.start_url,
                "final_start_url": self.final_start_url,
                "started_at": self.started_at,
                "completed_at": now_iso(),
                "config": self.config,
                "reason": reason,
            },
            "university": self.university,
            "department": self.department,
            "professors": professors,
            "pages": self.page_records,
            "errors": self.errors,
            "manual_review": self.manual_review,
            "external_domains": self.external_domains,
            "js_candidates": self.js_candidates[:20],
            "warnings": unique_strings(self.warnings),
            "stats": stats,
            "fatal_error": self.fatal_error,
        }

    def _finalize_professors(self) -> List[Dict[str, Any]]:
        included: List[Dict[str, Any]] = []
        for key in self.professor_order:
            professor = self.professors.get(key)
            if not professor or not professor.get("name"):
                continue
            title = professor.get("title") or ""
            section = professor.get("section") or ""
            has_academic_signal = bool(extraction.ACADEMIC_TITLE_RE.search(title))
            # "Faculty" alone is ambiguous (e.g. "Faculty Affairs"). Require a
            # real academic rank before allowing it to override an admin title.
            strong_academic_signal = bool(extraction.STRONG_ACADEMIC_TITLE_RE.search(title))
            has_faculty_signal = bool(extraction.FACULTY_SECTION_RE.search(section))
            has_research_signal = bool(
                professor.get("publications")
                or len(professor.get("research_interests") or []) >= 2
                or len(clean_text(professor.get("research_text"))) >= 80
            )
            explicitly_non_academic = bool(
                extraction.NON_ACADEMIC_TITLE_RE.search(title)
            ) and not strong_academic_signal
            if explicitly_non_academic or (
                professor.get("academic") is False and not has_academic_signal
            ):
                self.manual_review.append(
                    {
                        "url": professor.get("profile_url") or (professor.get("source_urls") or [None])[0],
                        "reason": "excluded_non_academic_person",
                        "professor": professor.get("name"),
                        "detail": title or section,
                    }
                )
                continue
            if not (has_academic_signal or has_faculty_signal or has_research_signal):
                self.manual_review.append(
                    {
                        "url": professor.get("profile_url") or professor.get("source_urls", [None])[0],
                        "reason": "insufficient_academic_evidence",
                        "professor": professor.get("name"),
                        "detail": title or section,
                    }
                )
                continue

            publications = []
            seen_titles = set()
            for publication in professor.get("publications") or []:
                title_key = clean_text(publication.get("title")).casefold()
                if not title_key or title_key in seen_titles:
                    continue
                seen_titles.add(title_key)
                publications.append(publication)
            publications.sort(key=lambda item: (-(item.get("year") or 0), item.get("title") or ""))

            evidence = sorted(
                professor.get("evidence") or [],
                key=lambda item: (
                    item.get("direction") == "negative",
                    -int(item.get("strength") or 0),
                    item.get("date") or "",
                ),
            )[:8]
            research_interests = unique_strings(professor.get("research_interests") or [])[:20]
            if not professor.get("university") and self.university:
                professor["university"] = self.university
            if not professor.get("department") and self.department:
                professor["department"] = self.department

            record = {
                "id": "",
                "name": professor["name"],
                "title": professor.get("title"),
                "department": professor.get("department"),
                "university": professor.get("university"),
                "email": professor.get("email"),
                "profile_url": professor.get("profile_url"),
                "personal_website": professor.get("personal_website"),
                "research": {
                    "interests": research_interests,
                    "methodologies": professor.get("methodologies") or [],
                    "technologies": professor.get("technologies") or [],
                    "projects": professor.get("projects") or [],
                    "lab_name": professor.get("lab_name"),
                    "lab_links": professor.get("lab_links") or [],
                    "center_affiliations": [
                        entry.get("label")
                        for entry in professor.get("center_links") or []
                        if entry.get("label")
                    ],
                    "group_affiliations": unique_strings(
                        professor.get("affiliations") or []
                    ),
                    "text_excerpt": truncate(professor.get("research_text") or professor.get("text_excerpt") or "", 5000),
                    "summary": None,
                    "publication_analysis": None,
                    "ai_generated": False,
                },
                "publications": publications,
                "links": {
                    "faculty_profile": professor.get("profile_url"),
                    "personal_website": professor.get("personal_website"),
                    "laboratory": (
                        (professor.get("lab_links") or [{}])[0].get("url")
                        if professor.get("lab_links")
                        else None
                    ),
                    "academic_profiles": professor.get("academic_profiles") or [],
                },
                "opportunity": {
                    "category": None,
                    "category_label": None,
                    "confidence": None,
                    "confidence_explanation": None,
                    "explanation": None,
                    "evidence": [
                        {
                            "url": item.get("url"),
                            "quote": item.get("quote"),
                            "page_title": item.get("page_title"),
                            "date": item.get("date"),
                            "current": item.get("current"),
                            "direction": item.get("direction"),
                            "reasons": item.get("reasons") or [],
                        }
                        for item in evidence
                    ],
                    "evidence_found": bool(evidence),
                    "status": "not_analyzed",
                },
                "sources": professor.get("source_urls") or [],
                "provenance": {
                    "explicit_fields": sorted(professor.get("explicit_fields") or []),
                    "linked_page_fields": sorted(professor.get("linked_fields") or []),
                    "ai_generated_fields": [],
                },
                "field_sources": professor.get("field_sources") or {},
                "page_types": sorted(professor.get("page_types") or []),
            }
            included.append(record)

        included.sort(key=lambda item: (item["name"].casefold(), item.get("email") or ""))
        for index, professor in enumerate(included, start=1):
            professor["id"] = f"prof_{index:03d}"
        return included
