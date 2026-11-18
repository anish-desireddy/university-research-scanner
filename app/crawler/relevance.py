"""Link relevance scoring for broad but focused academic discovery.

Same-site links may be followed at a lower threshold. External links are only
followed when they look like an academic lab, research group, or personal
academic site, and are never followed into social networks or scholarly
profile silos (those URLs are retained as linked academic profiles instead).
"""

from __future__ import annotations

import re
from typing import Any, Dict
from urllib.parse import urlsplit

from app.utils import href_is_document  # re-use one definition of document URLs
from app.utils import registrable_domain, same_site

LISTING_RE = re.compile(
    r"\b(faculty|faculties|faculty\s*(and|&)\s*staff|people|directory|staff|"
    r"our\s+people|meet\s+(our|the)\s+faculty|personnel|team|researchers)\b",
    re.I,
)
PROFILE_RE = re.compile(
    r"(/directory/[^/]+|/people/[^/]+|/person/[^/]+|/faculty/[^/]+|"
    r"/profile[s]?/[^/]+|/members?/[^/]+|/bio/[^/]+|/~[a-z0-9_.-]+)",
    re.I,
)
RESEARCH_RE = re.compile(
    r"\b(research|publications?|projects?|scholarship|expertise|publications\s*(and|&)\s*research)\b",
    re.I,
)
LAB_RE = re.compile(r"\b(lab|laboratory|research\s+group|group\s+website|center|centre|institute)\b", re.I)
PERSONAL_RE = re.compile(r"\b(home\s?page|homepage|personal\s+(web)?site|my\s+website|website)\b", re.I)
NEGATIVE_RE = re.compile(
    r"\b(news|events?|calendar|admissions?|apply|application|tuition|financial\s+aid|"
    r"athletics|sports|library|bookstore|dining|housing|parking|maps?|directions|"
    r"give|giving|donate|alumni|foundation|covid|coronavirus|login|sign\s*in|"
    r"register|portal|canvas|blackboard|email|webmail|privacy|accessibility|"
    r"terms|careers?|jobs\s+at|human\s+resources|title\s+ix|emergency|police|"
    r"magazine|podcast|newsletter|social\s+media|instagram|facebook|twitter|"
    r"youtube|tiktok|linkedin|pinterest|flickr)\b",
    re.I,
)
BLOCKED_CRAWL_DOMAINS = {
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "youtube.com",
    "tiktok.com",
    "linkedin.com",
    "pinterest.com",
    "flickr.com",
    "scholar.google.com",
    "scholar.googleusercontent.com",
    "researchgate.net",
    "academia.edu",
    "mendeley.com",
    "scopus.com",
    "webofscience.com",
    "orcid.org",
    "dblp.org",
    "semanticscholar.org",
    "google.com",
    "googletagmanager.com",
    "w3.org",
    "schema.org",
    "creativecommons.org",
    "doi.org",
    "arxiv.org",
    "pubmed.ncbi.nlm.nih.gov",
    "ncbi.nlm.nih.gov",
    "jstor.org",
    "springer.com",
    "sciencedirect.com",
    "ieee.org",
    "acm.org",
    "wikipedia.org",
    "apple.com",
    "microsoft.com",
    "adobe.com",
    "zoom.us",
    "forms.gle",
    "docs.google.com",
    "sharepoint.com",
    "office.com",
    "microsoftonline.com",
    "outlook.com",
}
ACADEMIC_PROFILE_DOMAINS = {
    "scholar.google.com",
    "orcid.org",
    "researchgate.net",
    "dblp.org",
    "semanticscholar.org",
    "linkedin.com",
    "academia.edu",
    "mendeley.com",
    "scopus.com",
    "webofscience.com",
}


def _is_negative(label: str, url: str) -> bool:
    path = urlsplit(url).path or ""
    # Query strings such as ?page=2 are fine; event/news identifiers are not.
    return bool(NEGATIVE_RE.search(label) or NEGATIVE_RE.search(path.replace("-", " ")))


def score_link(page_url: str, target_url: str, label: str, context: str = "") -> Dict[str, Any]:
    label = (label or "").strip()
    context = (context or "").strip()
    if not target_url:
        return {"url": "", "score": -99, "kind": "invalid", "crawlable": False, "reason": "invalid"}
    host = (urlsplit(target_url).hostname or "").lower()
    domain = registrable_domain(target_url)
    internal = same_site(page_url, target_url)
    kind = "content"
    score = 0.0
    reason = "neutral"

    if any(host == blocked or host.endswith("." + blocked) for blocked in BLOCKED_CRAWL_DOMAINS):
        kind = "academic_profile" if any(
            host == blocked or host.endswith("." + blocked)
            for blocked in ACADEMIC_PROFILE_DOMAINS
        ) else "external_resource"
        return {
            "url": target_url,
            "score": -20,
            "kind": kind,
            "crawlable": False,
            "reason": "blocked domain",
        }

    if href_is_document(target_url):
        return {
            "url": target_url,
            "score": -5,
            "kind": "document",
            "crawlable": False,
            "reason": "document",
        }

    if _is_negative(label, target_url):
        return {
            "url": target_url,
            "score": -10,
            "kind": "irrelevant",
            "crawlable": False,
            "reason": "irrelevant navigation",
        }

    path = urlsplit(target_url).path or "/"
    combined = f"{label} {path} {context}".lower()
    is_listing = bool(LISTING_RE.search(label) or LISTING_RE.search(path.replace("-", " ")))
    is_profile = bool(PROFILE_RE.search(path) or PROFILE_RE.search(label))
    is_lab = bool(LAB_RE.search(label) or LAB_RE.search(path.replace("-", " ")))
    is_research = bool(RESEARCH_RE.search(label) or RESEARCH_RE.search(path.replace("-", " ")))
    is_personal = bool(PERSONAL_RE.search(label))

    if is_personal and (not internal or re.search(r"/~[a-z0-9_.-]+", path, re.I)):
        score = 3.2
        kind = "personal"
        reason = "personal academic site"
    elif is_profile:
        score = 5.0 if label and not LISTING_RE.search(label) else 3.0
        kind = "profile"
        reason = "individual profile"
    elif is_listing:
        score = 4.5
        kind = "listing"
        reason = "faculty directory"
    elif is_lab:
        score = 3.4
        kind = "lab"
        reason = "laboratory or research group"
    elif is_research:
        score = 2.8
        kind = "research"
        reason = "research or publications"
    elif is_personal:
        score = 2.5
        kind = "personal"
        reason = "personal academic site"
    elif internal:
        score = 0.2
        kind = "same_site"
        reason = "same-site navigation"
        # Academic subdomains often host faculty pages.
        if re.search(r"(faculty|people|directory|research|cs|eng|sci)\.", host):
            score = 0.8
    else:
        score = -1.0
        kind = "external_other"
        reason = "unrelated external site"

    if not internal and score > 0 and kind not in ("lab", "personal"):
        # External research pages are only valuable when they are clearly
        # academic. A generic external "research" link is not enough.
        if kind == "research" and re.search(r"\b(research|lab|group|publications?)\b", combined):
            score = max(score, 2.6)
        elif kind in ("listing", "profile"):
            score = min(score, 2.0)
        else:
            score = -1.0
            kind = "external_other"
            reason = "external link without academic signal"

    if label.casefold() in {"home", "homepage", "website", "personal website"} and internal:
        score = max(score, 0.5)
    if not label and internal:
        score = min(score, 0.4)
    return {
        "url": target_url,
        "score": round(score, 2),
        "kind": kind,
        "crawlable": score > 0,
        "internal": internal,
        "domain": domain,
        "label": label,
        "reason": reason,
    }
