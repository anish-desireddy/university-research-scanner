"""HTML extraction for faculty directories, profiles, and research pages.

The extractors deliberately avoid site-specific selectors as their primary
strategy. They use semantic markup (main/article/headings), schema.org Person
data, person-card heuristics, and link context. Site-specific class names are
used only as additional hints.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from bs4 import BeautifulSoup, Tag

from app.utils import (
    clean_text,
    href_is_document,
    normalize_url,
    normalize_whitespace,
    split_sentences,
    truncate,
    unique_strings,
)

ACADEMIC_TITLE_RE = re.compile(
    r"\b("
    r"professor|lecturer|instructor|faculty|chair|dean|provost|"
    r"research scientist|research associate|research scholar|"
    r"postdoctoral|post-doc|teaching fellow|clinical faculty|"
    r"emeritus|distinguished professor|endowed chair"
    r")\b",
    re.I,
)
STRONG_ACADEMIC_TITLE_RE = re.compile(
    r"\b("
    r"professor|lecturer|instructor|chair|dean|provost|"
    r"research scientist|research associate|research scholar|"
    r"postdoctoral|post-doc|teaching fellow|clinical faculty|"
    r"emeritus|distinguished professor|endowed chair"
    r")\b",
    re.I,
)
NON_ACADEMIC_TITLE_RE = re.compile(
    r"\b("
    r"office manager|administrative assistant|administrator|receptionist|"
    r"business manager|fiscal|accountant|coordinator|advisor|adviser|"
    r"communications|marketing|webmaster|technician|it support|help desk|"
    r"graduate student|undergraduate student|student assistant|"
    r"research assistant|teaching assistant|graduate assistant|"
    r"teach/res|res\.?asst|higher ed\.? teach|"
    r"faculty affairs|strategic initiatives|program manager|"
    r"office of the|advancement officer|development officer|"
    r"alumni|alumnus|alumna|retired staff"
    r")\b",
    re.I,
)
FACULTY_SECTION_RE = re.compile(
    r"\b(faculty|professors?|academic staff|teaching staff|research faculty)\b", re.I
)
STAFF_SECTION_RE = re.compile(r"\b(staff|administration|administrative)\b", re.I)

PERSON_LINK_RE = re.compile(
    r"(/directory/|/people/|/person/|/persons/|/faculty/|/staff/|/profile/|"
    r"/profiles/|/members?/|/team/|/bio/|/~[a-z0-9_.-]+)",
    re.I,
)
PROFILE_URL_RE = re.compile(
    r"(/directory/[^/]+/?$|/people/[^/]+/?$|/person/[^/]+/?$|"
    r"/faculty/[^/]+/?$|/profile[s]?/[^/]+/?$|/~[a-z0-9_.-]+/?$)",
    re.I,
)
GENERIC_NAMES = {
    "faculty",
    "faculty and staff",
    "faculty & staff",
    "faculty directory",
    "staff",
    "staff directory",
    "people",
    "our people",
    "directory",
    "department directory",
    "home",
    "homepage",
    "about",
    "about us",
    "contact",
    "contact us",
    "research",
    "publications",
    "news",
    "events",
    "admissions",
    "academics",
    "graduate",
    "undergraduate",
    "programs",
    "program",
    "courses",
    "alumni",
    "give",
    "login",
    "search",
    "menu",
    "main menu",
    "skip to content",
    "computer science",
    "department of computer science",
    "university",
    "college",
    "school",
    "institute",
    "center",
    "centre",
    "laboratory",
    "lab",
    "research group",
    "meet our faculty",
    "view profile",
    "read more",
    "learn more",
    "website",
    "home page",
    "personal website",
    "google scholar",
    "scholar",
    "linkedin",
    "orcid",
    "researchgate",
    "dblp",
    "curriculum vitae",
    "cv",
    "biography",
    "bio",
}
NAME_SUFFIXES = {
    "jr",
    "jr.",
    "sr",
    "sr.",
    "ii",
    "iii",
    "iv",
    "ph.d",
    "ph.d.",
    "phd",
    "m.d.",
    "md",
}
NAME_PARTICLES = {"van", "von", "de", "del", "der", "da", "di", "la", "le", "bin", "al", "st."}
GENERIC_NAME_TOKENS = {
    "schedule",
    "course",
    "courses",
    "colloquium",
    "seminar",
    "syllabus",
    "calendar",
    "lecture",
    "lectures",
    "notes",
    "slides",
    "teaching",
    "students",
    "admissions",
    "news",
    "events",
    "article",
    "articles",
    "publication",
    "publications",
    "project",
    "projects",
    "contact",
    "directory",
    "faculty",
    "staff",
    "research",
    "lab",
    "labs",
    "group",
    "groups",
    "center",
    "centre",
    "department",
    "university",
    "college",
    "school",
    "institute",
    "homepage",
    "website",
    "bio",
    "biography",
    "cv",
    "vita",
    "profile",
    "people",
    "team",
    "admin",
    "administration",
    "login",
    "apply",
    "alumni",
    "give",
    "president",
    "provost",
    "chancellor",
    "treasurer",
    "manager",
    "workflow",
    "monarch",
    "forms",
    "welcome",
    "assistantship",
    "assistantships",
    "scholarship",
    "scholarships",
    "fellowship",
    "fellowships",
    "funding",
    "tuition",
    "advisory",
    "board",
    "exit",
    "exam",
    "laptop",
    "facilities",
    "internship",
    "internships",
    "organization",
    "organizations",
    "testimonials",
    "assessment",
    "objectives",
    "outcomes",
    "resources",
    "current",
    "future",
    "academics",
    "academic",
    "graduate",
    "undergraduate",
    "syllabi",
    "syllabus",
    "viewer",
    "registration",
}
TECHNOLOGY_TERMS = [
    "Python",
    "Java",
    "JavaScript",
    "TypeScript",
    "C++",
    "C#",
    "C",
    "R",
    "MATLAB",
    "SQL",
    "NoSQL",
    "TensorFlow",
    "PyTorch",
    "Keras",
    "scikit-learn",
    "OpenCV",
    "CUDA",
    "GPU",
    "HPC",
    "MPI",
    "OpenMP",
    "Spark",
    "Hadoop",
    "Kafka",
    "Docker",
    "Kubernetes",
    "AWS",
    "Azure",
    "GCP",
    "Linux",
    "Unity",
    "ROS",
    "FPGA",
    "Verilog",
    "VHDL",
    "Arduino",
    "Raspberry Pi",
    "Tableau",
    "Power BI",
    "SPSS",
    "SAS",
    "Stata",
    "Qualtrics",
    "LaTeX",
]
METHODOLOGY_TERMS = [
    "machine learning",
    "deep learning",
    "reinforcement learning",
    "natural language processing",
    "computer vision",
    "data mining",
    "statistical modeling",
    "simulation",
    "mathematical modeling",
    "optimization",
    "qualitative research",
    "quantitative research",
    "mixed methods",
    "ethnography",
    "interviews",
    "focus groups",
    "survey research",
    "field experiments",
    "randomized controlled trial",
    "case study",
    "design science",
    "usability testing",
    "human-centered design",
    "participatory design",
    "experimental design",
    "computational modeling",
    "network analysis",
    "content analysis",
    "meta-analysis",
    "action research",
    "archival research",
    "longitudinal study",
]
PUBLICATION_SECTION_RE = re.compile(
    r"\b(publications?|selected publications|recent publications|articles|"
    r"journal articles|conference papers|papers|books|book chapters|"
    r"peer[- ]reviewed publications|scholarly works)\b",
    re.I,
)
RESEARCH_SECTION_RE = re.compile(
    r"\b(research interests?|research areas?|areas of interest|areas of expertise|"
    r"research focus|research specialties|specializations?|expertise)\b",
    re.I,
)
GENERIC_RESEARCH_HEADING_RE = re.compile(r"^\s*research\s*$", re.I)
PROJECT_SECTION_RE = re.compile(r"\b(current projects?|research projects?|projects|grants?)\b", re.I)
LAB_SECTION_RE = re.compile(r"\b(labs?|laborator(?:y|ies)|research groups?|centers?|centres?)\b", re.I)

EVIDENCE_PATTERNS: List[Tuple[re.Pattern[str], int, str]] = [
    (
        re.compile(
            r"\b(position|opening|vacanc(?:y|ies))\b.{0,50}\b(available|open)\b|"
            r"\b(available|open)\b.{0,40}\b(position|opening|vacanc(?:y|ies))\b|"
            r"\bwe are (currently )?hiring\b|\baccepting applications\b|"
            r"\bjob posting\b|\bapply (now|today)\b",
            re.I,
        ),
        3,
        "explicit opening",
    ),
    (
        re.compile(
            r"\b(recruiting|recruitment|looking for|seeking)\b.{0,80}"
            r"\b(students?|undergraduates?|research assistants?|interns?)\b|"
            r"\b(students?|undergraduates?)\b.{0,60}\b(join|work with|apply)\b",
            re.I,
        ),
        2,
        "recruitment statement",
    ),
    (
        re.compile(
            r"\bundergraduate(?:s)?\b.{0,100}\b(research|opportunit(?:y|ies)|projects?|thesis|"
            r"independent study|summer)\b|"
            r"\b(research|summer)\b.{0,80}\bundergraduate(?:s)?\b|"
            r"\bREU\b|\bResearch Experiences for Undergraduates\b",
            re.I,
        ),
        2,
        "undergraduate research",
    ),
    (
        re.compile(
            r"\b(join|joining|work in)\b.{0,40}\b(lab|laboratory|research group)\b|"
            r"\bstudents? interested\b|\bwelcome (students|applications)\b|"
            r"\bmentor(?:ing)?\b.{0,50}\b(students|undergraduates)\b|"
            r"\bsupervis(?:e|ing)\b.{0,40}\bundergraduate",
            re.I,
        ),
        2,
        "student invitation",
    ),
    (
        re.compile(
            r"\b(contact|email|reach out to)\b.{0,60}\b(me|dr\.? [A-Z]|professor)\b|"
            r"\bprospective students?\b|\bindependent study\b|\bsenior design\b|"
            r"\bthesis (students?|supervision)\b|\bsummer research\b|\binternships?\b",
            re.I,
        ),
        1,
        "contact invitation",
    ),
]
NEGATIVE_EVIDENCE_RE = re.compile(
    r"\b(no|not|currently not|unfortunately not)\b.{0,40}"
    r"\b(openings?|positions?|vacancies|availability|recruiting|students?)\b|"
    r"\b(lab is full|no undergraduate positions|not accepting)\b",
    re.I,
)


# ---------------------------------------------------------------------------
# Basic page helpers
# ---------------------------------------------------------------------------


def parse_soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html or "", "lxml")


def _meta_content(soup: BeautifulSoup, **attrs: str) -> str:
    tag = soup.find("meta", attrs=attrs)
    return clean_text(tag.get("content")) if tag and tag.get("content") else ""


def page_title(soup: BeautifulSoup) -> str:
    og = _meta_content(soup, property="og:title")
    if og:
        return og
    if soup.title and soup.title.string:
        return clean_text(soup.title.string)
    heading = soup.find("h1")
    return clean_text(heading.get_text(" ")) if heading else ""


def main_content(soup: BeautifulSoup) -> Tag:
    """Return the primary content region with chrome removed."""
    candidates = []
    for selector in ("main", "#main-content", "[role='main']", "article", ".node__content"):
        node = soup.select_one(selector)
        if node is not None:
            text_len = len(clean_text(node.get_text(" ")))
            if text_len >= 120:
                candidates.append((text_len, node))
    node = max(candidates, key=lambda pair: pair[0])[1] if candidates else soup.body or soup
    return node


def clean_main_text(soup: BeautifulSoup) -> str:
    node = main_content(soup)
    # Work on a copy so link extraction still sees the original document.
    copy = BeautifulSoup(str(node), "lxml")
    for unwanted in copy.find_all(
        ["script", "style", "noscript", "nav", "footer", "header", "form", "aside"]
    ):
        unwanted.decompose()
    for unwanted in copy.select(
        "[aria-hidden='true'], .visually-hidden, .sr-only, .skip-link, .breadcrumb, "
        ".pagination, .cookie, .cookie-consent"
    ):
        unwanted.decompose()
    lines = []
    for chunk in copy.get_text("\n").split("\n"):
        value = clean_text(chunk)
        if value and value not in lines[-3:]:
            lines.append(value)
    return "\n".join(lines)


def _looks_like_person_name(text: str) -> bool:
    value = clean_text(text)
    if not value or len(value) > 55 or len(value) < 4:
        return False
    if any(character in value for character in ("@", "|", "/", "&", ";", ":", "(", ")", "<", ">", "=")):
        return False
    if re.search(r"\d", value):
        return False
    value = re.sub(r"^(dr|prof|professor|mr|ms|mrs)\.?\s+", "", value, flags=re.I)
    value = re.sub(r"\s*,?\s*(ph\.?d\.?|m\.?d\.?|m\.?s\.?|b\.?s\.?)$", "", value, flags=re.I)
    value = value.strip(" ,.-")
    if value.casefold() in GENERIC_NAMES:
        return False
    if re.search(
        r"\b(faculty|staff|directory|department|university|college|school|institute|"
        r"center|centre|laboratory|research|program|programs|news|events|admissions|"
        r"alumni|contact|about|home|login|search|menu|profile|website|homepage|"
        r"publications|projects|people|team)\b",
        value,
        re.I,
    ):
        return False
    tokens = [token for token in re.split(r"\s+", value) if token]
    if not (2 <= len(tokens) <= 5):
        return False
    for token in tokens:
        if token.strip(".,").casefold() in GENERIC_NAME_TOKENS:
            return False
    for token in tokens:
        core = token.strip(".,")
        if not core:
            return False
        if core.casefold() in NAME_SUFFIXES or core.casefold() in NAME_PARTICLES:
            continue
        if not re.fullmatch(r"[A-Za-z][A-Za-z'’\-\.]*", core):
            return False
        if not (core[0].isupper() or core.isupper()):
            return False
    return True


def normalize_person_name(text: str) -> str:
    value = clean_text(text)
    value = re.sub(r"^(dr|prof|professor|mr|ms|mrs)\.?\s+", "", value, flags=re.I)
    value = re.sub(r"\s*,?\s*(ph\.?d\.?|m\.?d\.?|m\.?s\.?|b\.?s\.?)$", "", value, flags=re.I)
    value = value.strip(" ,.-")
    if "," in value and _looks_like_person_name(" ".join(reversed(value.split(","))).strip()):
        value = " ".join(reversed(value.split(","))).strip()
    if value.isupper():
        value = " ".join(word.capitalize() for word in value.split())
    return value


def name_core(name: str) -> tuple:
    """First and last name tokens, ignoring middle initials."""
    normalized = normalize_person_name(name).casefold()
    tokens = [
        re.sub(r"[^a-z]", "", token)
        for token in re.split(r"\s+", normalized)
        if re.sub(r"[^a-z]", "", token)
    ]
    if len(tokens) < 2:
        return tuple(tokens)
    return (tokens[0], tokens[-1])


def name_token_key(name: str) -> frozenset:
    normalized = normalize_person_name(name).casefold()
    return frozenset(
        token.strip(".,") for token in re.split(r"\s+", normalized) if token.strip(".,")
    )


def person_key(name: str, email: str = "") -> str:
    normalized = normalize_person_name(name)
    if normalized:
        return re.sub(r"[^a-z0-9]+", "-", normalized.casefold()).strip("-")
    if email:
        return "email-" + re.sub(r"[^a-z0-9]+", "-", email.casefold()).strip("-")
    return ""


def _jsonld_nodes(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    nodes: List[Dict[str, Any]] = []
    for script in soup.find_all("script", attrs={"type": re.compile("ld\\+json", re.I)}):
        raw = script.string or script.get_text()
        if not raw:
            continue
        try:
            data = json.loads(raw.strip())
        except (json.JSONDecodeError, TypeError):
            continue
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, list):
                stack.extend(item)
            elif isinstance(item, dict):
                nodes.append(item)
                stack.extend(item.get("@graph", []) if isinstance(item.get("@graph"), list) else [])
    return nodes


def _jsonld_persons(soup: BeautifulSoup) -> List[Dict[str, Any]]:
    persons = []
    for node in _jsonld_nodes(soup):
        node_type = node.get("@type", "")
        types = node_type if isinstance(node_type, list) else [node_type]
        if any(str(value).casefold() == "person" for value in types):
            persons.append(node)
    return persons


def _jsonld_org_name(soup: BeautifulSoup) -> str:
    for node in _jsonld_nodes(soup):
        node_type = node.get("@type", "")
        types = node_type if isinstance(node_type, list) else [node_type]
        if any(
            str(value).casefold()
            in {"organization", "collegeoruniversity", "educationalorganization", "university"}
            for value in types
        ):
            name = clean_text(node.get("name"))
            if name:
                return name
    return ""


def infer_university(soup: BeautifulSoup, url: str) -> str:
    title_tag = clean_text(soup.title.string) if soup.title and soup.title.string else ""
    for value in (
        _jsonld_org_name(soup),
        title_tag,
        _meta_content(soup, property="og:site_name"),
        page_title(soup),
    ):
        value = clean_text(value)
        if value.startswith(("http://", "https://", "www.")):
            continue
        if value and re.search(
            r"\b(university|college|institute|school of|polytechnic|academy)\b", value, re.I
        ):
            # A page title usually places the institution after a separator.
            parts = re.split(r"\s+[|–—-]\s+", value)
            for part in reversed(parts):
                if re.search(
                    r"\b(university|college|institute|school of|polytechnic|academy)\b",
                    part,
                    re.I,
                ):
                    return part.strip()
            return value
    host = ""
    try:
        from urllib.parse import urlsplit

        host = urlsplit(url).hostname or ""
    except ValueError:
        pass
    return host


def _department_from_text(text: str) -> str:
    for line in text.split("\n")[:30]:
        line = clean_text(line)
        if not line or len(line) > 120:
            continue
        match = re.match(r"(?:department|dept\.?)\s+of\s+(.+)", line, re.I)
        if match:
            return clean_text(match.group(1)).strip(" .,-")
        if re.search(r"\b(department|school of|college of)\b", line, re.I) and len(line) < 90:
            return line
    return ""


def infer_department(soup: BeautifulSoup, text: str = "") -> str:
    for selector in (
        ".department-department",
        "[class*='person-department'] [class*='department']",
        "[class*='field--name-field-department']",
    ):
        node = soup.select_one(selector)
        if node:
            value = clean_text(node.get_text(" "))
            if value and not re.search(
                r"\b(directory|university|college of|office manager|manager|director|dir,)\b",
                value,
                re.I,
            ):
                return value
    meta = _meta_content(soup, name="department") or _meta_content(
        soup, property="article:section"
    )
    if meta and len(meta) < 100:
        return meta
    h1 = soup.find("h1")
    if h1:
        heading = clean_text(h1.get_text(" "))
        if (
            3 < len(heading) < 70
            and not _looks_like_person_name(heading)
            and not re.search(r"\b(welcome|directory|faculty|staff|research)\b", heading, re.I)
        ):
            return heading
    breadcrumb = soup.select_one("[class*='breadcrumb'], nav[aria-label*='readcrumb' i]")
    if breadcrumb:
        labels = [
            clean_text(node.get_text(" "))
            for node in breadcrumb.find_all("a")
            if clean_text(node.get_text(" "))
        ]
        for label in reversed(labels):
            if not re.search(
                r"^(home|directory|people|faculty|staff|profile|research)$", label, re.I
            ) and len(label) < 80:
                return label
    found = _department_from_text(text or clean_main_text(soup))
    if found:
        return re.sub(
            r"^(department|dept\.?)\s+of\s+", "", found, flags=re.I
        ).strip(" .,-")
    return ""


def _page_date(soup: BeautifulSoup) -> Optional[str]:
    candidates = [
        _meta_content(soup, property="article:modified_time"),
        _meta_content(soup, property="og:updated_time"),
        _meta_content(soup, name="date"),
        _meta_content(soup, name="last-modified"),
    ]
    for node in _jsonld_nodes(soup):
        for key in ("dateModified", "datePublished", "dateCreated"):
            if node.get(key):
                candidates.append(clean_text(node.get(key)))
    for node in soup.find_all("time"):
        if node.get("datetime"):
            candidates.append(clean_text(node.get("datetime")))
        elif node.get_text(strip=True):
            candidates.append(clean_text(node.get_text(strip=True)))
    for value in candidates:
        if not value:
            continue
        match = re.search(r"(19|20)\d{2}-\d{2}-\d{2}", value)
        if match:
            return match.group(0)
        match = re.search(r"(19|20)\d{2}", value)
        if match:
            return match.group(0)
    text = clean_text(soup.get_text(" "))
    match = re.search(
        r"(?:last\s+updated|updated|modified|published)\s*(?:on|:)?\s*"
        r"([A-Z][a-z]+\s+\d{1,2},?\s+(?:19|20)\d{2}|(?:19|20)\d{2}-\d{2}-\d{2})",
        text,
        re.I,
    )
    return match.group(1) if match else None


def _is_current(date_value: Optional[str], today: Optional[datetime] = None) -> Optional[bool]:
    if not date_value:
        return None
    today = today or datetime.now(timezone.utc)
    match = re.search(r"((?:19|20)\d{2})", date_value)
    if not match:
        return None
    year = int(match.group(1))
    return (today.year - year) <= 2


# ---------------------------------------------------------------------------
# Section and publication extraction
# ---------------------------------------------------------------------------


def _next_content_container(heading: Tag) -> Optional[Tag]:
    # Bootstrap-style accordions place the body in the parent card.
    card = heading.find_parent(class_=re.compile(r"\bcard\b", re.I))
    if card is not None:
        body = card.select_one(".collapse .card-body, .card-body, .accordion-body")
        if body is not None:
            return body
    parent = heading.parent
    if parent is not None and parent.name in ("div", "section", "li", "dd"):
        # A wrapper that contains substantially more than the heading itself.
        if len(clean_text(parent.get_text(" "))) > len(clean_text(heading.get_text(" "))) + 30:
            if not parent.find(["h1", "h2"], recursive=False):
                return parent
    return None


def _collect_following(heading: Tag, max_chars: int = 12000) -> List[Tag]:
    blocks: List[Tag] = []
    level = int(heading.name[1]) if heading.name and heading.name[0] == "h" else 3
    node = heading
    chars = 0
    while True:
        node = node.find_next_sibling()
        if node is None:
            break
        if isinstance(node, Tag) and re.fullmatch(r"h[1-6]", node.name or ""):
            if int(node.name[1]) <= level:
                break
        if isinstance(node, Tag):
            blocks.append(node)
            chars += len(clean_text(node.get_text(" ")))
            if chars >= max_chars:
                break
    if not blocks and heading.parent is not None:
        node = heading.parent
        while True:
            node = node.find_next_sibling()
            if node is None:
                break
            if isinstance(node, Tag) and re.fullmatch(r"h[1-6]", node.name or ""):
                if int(node.name[1]) <= level:
                    break
            if isinstance(node, Tag):
                blocks.append(node)
                chars += len(clean_text(node.get_text(" ")))
                if chars >= max_chars:
                    break
    return blocks


def _section_items(heading: Tag) -> List[str]:
    container = _next_content_container(heading)
    blocks: Iterable[Tag]
    if container is not None:
        blocks = [container]
    else:
        blocks = _collect_following(heading)
    items: List[str] = []
    for block in blocks:
        candidates = block.find_all(["li", "dd", "p"])
        leaf = [
            item
            for item in candidates
            if not item.find(["li", "dd", "p"])
            and len(clean_text(item.get_text(" "))) >= 3
        ]
        if leaf:
            for item in leaf:
                value = clean_text(item.get_text(" "))
                if value:
                    items.append(value)
        else:
            value = clean_text(block.get_text(" "))
            if value:
                items.append(value)
    seen = set()
    clean_items = []
    for item in items:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        clean_items.append(item)
    return clean_items


def _find_sections(soup: BeautifulSoup, pattern: re.Pattern[str]) -> List[Tuple[str, List[str]]]:
    sections: List[Tuple[str, List[str]]] = []
    seen = set()
    for heading in soup.find_all(["h1", "h2", "h3", "h4", "h5", "dt", "summary"]):
        label = clean_text(heading.get_text(" "))
        if not label or len(label) > 90 or not pattern.search(label):
            continue
        key = (label.casefold(), id(heading.parent))
        if key in seen:
            continue
        seen.add(key)
        items = _section_items(heading)
        if items:
            sections.append((label, items))
    return sections


def extract_publications(soup: BeautifulSoup, page_url: str) -> List[Dict[str, Any]]:
    publications: List[Dict[str, Any]] = []
    seen = set()
    for label, items in _find_sections(soup, PUBLICATION_SECTION_RE):
        for item in items:
            if len(item) < 18 or len(item) > 1200:
                continue
            if re.match(
                r"^(publications?|articles|books?|papers|selected publications)\s*$",
                item,
                re.I,
            ):
                continue
            publication = parse_publication_item(item, page_url)
            if not publication:
                continue
            key = re.sub(r"[^a-z0-9]+", "", publication["title"].casefold())[:160]
            if not key or key in seen:
                continue
            seen.add(key)
            publications.append(publication)
    return publications[:80]


def parse_publication_item(item: str, page_url: str) -> Optional[Dict[str, Any]]:
    text = clean_text(item)
    if len(text) < 18:
        return None
    title = ""
    quote = re.search(r"[\"“”]([^\"“”]{8,350})[\"“”]", text)
    if quote:
        title = clean_text(quote.group(1))
    else:
        after_year = re.search(r"\((?:19|20)\d{2}[a-z]?\)\.?\s*(.+)", text)
        if after_year:
            candidate = after_year.group(1)
            title = clean_text(re.split(r"(?<=[.!?])\s+", candidate)[0])
        else:
            title = clean_text(re.split(r"(?<=[.!?])\s+", text)[0])
    title = title.strip(" .;,\"'“”")
    if len(title) < 8:
        return None
    if re.search(r"\b(copyright|all rights reserved|privacy policy)\b", title, re.I):
        return None
    year_match = re.search(r"\b((?:19|20)\d{2})[a-z]?\b", text)
    year = int(year_match.group(1)) if year_match else None
    if year is not None and (year < 1900 or year > datetime.now(timezone.utc).year + 1):
        year = None
    venue = ""
    if quote:
        remainder = text[quote.end() :].strip(" .;,")
        if remainder:
            venue = clean_text(re.split(r"\.\s", remainder)[0])[:220]
    if not venue:
        # Look for an italic venue in the original markup in a later pass.
        venue = ""
    return {
        "title": truncate(title, 400),
        "year": year,
        "venue": venue or None,
        "url": page_url,
        "topic": None,
        "source_url": page_url,
    }


def _extract_publications_with_links(
    soup: BeautifulSoup, page_url: str
) -> List[Dict[str, Any]]:
    """Attach explicitly linked publication PDFs/DOIs to parsed publications."""
    publications = extract_publications(soup, page_url)
    if not publications:
        return publications
    by_key = {
        re.sub(r"[^a-z0-9]+", "", publication["title"].casefold())[:80]: publication
        for publication in publications
    }
    for anchor in soup.find_all("a", href=True):
        href = normalize_url(anchor.get("href"), page_url)
        if not href:
            continue
        context = clean_text(anchor.find_parent(["li", "p", "dd"]).get_text(" ")) if anchor.find_parent(["li", "p", "dd"]) else ""
        if not context:
            continue
        for key, publication in by_key.items():
            if key and key in re.sub(r"[^a-z0-9]+", "", context.casefold()):
                if href.lower().endswith(".pdf") or "doi.org" in href or "arxiv.org" in href:
                    publication["url"] = href
                break
    return publications


# ---------------------------------------------------------------------------
# Research and opportunity extraction
# ---------------------------------------------------------------------------


def extract_research_interests(soup: BeautifulSoup) -> List[str]:
    interests: List[str] = []
    for label, items in _find_sections(soup, RESEARCH_SECTION_RE):
        for item in items:
            if re.match(
                r"^(contracts?,?\s+grants?|grants?|awards?|publications?|education|"
                r"courses?|teaching|service)\b",
                item,
                re.I,
            ):
                continue
            label_removed = re.sub(
                r"^(research interests?|research areas?|areas of interest|"
                r"areas of expertise|research focus|expertise)\s*[:\-–]?\s*",
                "",
                item,
                flags=re.I,
            )
            if len(label_removed) > 260:
                label_removed = truncate(label_removed, 260)
            parts = [label_removed]
            if len(label_removed) > 90 and (";" in label_removed or "•" in label_removed):
                parts = [part.strip(" •-") for part in re.split(r"[;•]", label_removed)]
            for part in parts:
                part = clean_text(part).strip(" .,-")
                if 3 <= len(part) <= 220:
                    interests.append(part)
    # Generic "Research" heading: only short, prose-like items, never grant lists.
    for label, items in _find_sections(soup, re.compile(r"^research$", re.I)):
        for item in items:
            if len(item) < 20 or len(item) > 900:
                continue
            if re.search(
                r"\$\s?\d|\bgrant(s|ed)?\b|\baward(s|ed)?\b|contracts?,", item, re.I
            ):
                continue
            for sentence in split_sentences(item)[:3]:
                if 25 <= len(sentence) <= 260:
                    interests.append(sentence)
    return unique_strings(interests)[:18]


def extract_projects(soup: BeautifulSoup) -> List[str]:
    projects: List[str] = []
    for label, items in _find_sections(soup, re.compile(r"^(current\s+)?(research\s+)?projects?$", re.I)):
        for item in items:
            if 8 <= len(item) <= 500:
                projects.append(item)
    return unique_strings(projects)[:20]


def extract_technologies(text: str) -> List[str]:
    found = []
    for term in TECHNOLOGY_TERMS:
        if term in ("C", "R"):
            pattern = r"(?<![A-Za-z0-9+#])" + re.escape(term) + r"(?![A-Za-z0-9+#])"
        else:
            pattern = r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])"
        if re.search(pattern, text, re.I if term not in ("C", "R") else 0):
            found.append(term)
    return unique_strings(found)


def extract_methodologies(text: str) -> List[str]:
    found = []
    for term in METHODOLOGY_TERMS:
        if re.search(r"\b" + re.escape(term) + r"s?\b", text, re.I):
            found.append(term)
    return unique_strings(found)


def extract_opportunity_evidence(
    text: str,
    url: str,
    page_title_value: str = "",
    page_date: Optional[str] = None,
) -> List[Dict[str, Any]]:
    evidence: List[Dict[str, Any]] = []
    seen = set()
    page_title_value = clean_text(page_title_value)
    for raw_sentence in split_sentences(text, max_sentences=500):
        sentence = clean_text(raw_sentence).strip(" •-|")
        if len(sentence) < 25 or len(sentence) > 600:
            continue
        if sentence.casefold() in seen:
            continue
        best_strength = 0
        matched_reasons: List[str] = []
        for pattern, strength, reason in EVIDENCE_PATTERNS:
            if pattern.search(sentence):
                best_strength = max(best_strength, strength)
                matched_reasons.append(reason)
        if best_strength == 0:
            continue
        negative = bool(NEGATIVE_EVIDENCE_RE.search(sentence))
        seen.add(sentence.casefold())
        evidence.append(
            {
                "url": url,
                "page_title": page_title_value or None,
                "quote": truncate(sentence, 500),
                "date": page_date,
                "current": _is_current(page_date),
                "reasons": matched_reasons,
                "strength": best_strength,
                "direction": "negative" if negative else "positive",
            }
        )
        if len(evidence) >= 10:
            break
    evidence.sort(key=lambda item: (-item["strength"], item["direction"] == "negative"))
    return evidence[:8]


def _link_inventory(
    soup: BeautifulSoup, page_url: str
) -> Dict[str, List[Dict[str, str]]]:
    inventory = {
        "academic_profiles": [],
        "lab_links": [],
        "personal_links": [],
        "center_links": [],
        "publication_links": [],
    }
    seen = set()
    for anchor in soup.find_all("a", href=True):
        url = normalize_url(anchor.get("href"), page_url)
        if not url or url == page_url:
            continue
        label = clean_text(anchor.get_text(" ")) or clean_text(anchor.get("aria-label"))
        key = (url, label.casefold())
        if key in seen:
            continue
        seen.add(key)
        entry = {"url": url, "label": label}
        host = url.lower()
        label_host = (label + " " + host).lower()
        if any(
            domain in label_host
            for domain in (
                "scholar.google",
                "orcid.org",
                "researchgate.net",
                "dblp.org",
                "semanticscholar.org",
                "linkedin.com/in",
                "academia.edu",
                "mendeley.com",
                "scopus.com",
                "webofscience.com",
            )
        ):
            inventory["academic_profiles"].append(entry)
        elif re.search(r"\b(lab|laboratory|research group|group website)\b", label_host):
            inventory["lab_links"].append(entry)
        elif re.search(
            r"\b(center|centre|institute|consortium|initiative)\b", label_host
        ):
            inventory["center_links"].append(entry)
        elif re.search(r"\b(home\s?page|personal|website|homepage|my site)\b", label_host) or re.search(
            r"/~[a-z0-9_.-]+", host, re.I
        ):
            inventory["personal_links"].append(entry)
        elif href_is_document(url):
            inventory["publication_links"].append(entry)
    for key, values in inventory.items():
        deduped = []
        seen_urls = set()
        for entry in values:
            if entry["url"] in seen_urls:
                continue
            seen_urls.add(entry["url"])
            deduped.append(entry)
        inventory[key] = deduped[:30]
    return inventory


# ---------------------------------------------------------------------------
# Person extraction
# ---------------------------------------------------------------------------


def _card_section(container: Tag) -> str:
    block = container.find_parent(class_=re.compile(r"paragraph--type--person|person-nodes", re.I))
    if block is None:
        block = container.find_parent(class_=re.compile(r"paragraph|person", re.I))
    search_root = block if block is not None else container.parent
    if search_root is None:
        return ""
    # The nearest card-level heading is the section/role label ("Faculty",
    # "Staff", "Director of ..."). Prefer it over global navigation headings.
    for heading in search_root.find_all(["h2", "h3", "h4"], limit=4):
        classes = " ".join(heading.get("class") or [])
        value = clean_text(heading.get_text(" "))
        if value and len(value) < 80 and (
            "section-title" in classes or FACULTY_SECTION_RE.search(value) or STAFF_SECTION_RE.search(value)
        ):
            return value
    for heading in search_root.find_all(["h2", "h3", "h4"], limit=2):
        value = clean_text(heading.get_text(" "))
        if value and len(value) < 80:
            return value
    for heading in search_root.find_all_previous(["h2", "h3", "h4"], limit=1):
        value = clean_text(heading.get_text(" "))
        if value and len(value) < 80:
            return value
    return ""


def _nearby_email(container: Tag) -> str:
    mail = container.find("a", href=re.compile(r"^mailto:", re.I))
    if mail:
        return clean_text(mail.get("href").split(":", 1)[1].split("?")[0]).lower()
    match = re.search(
        r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b",
        clean_text(container.get_text(" ")),
    )
    return match.group(0).lower() if match else ""


def _nearby_title(container: Tag, name: str) -> str:
    for selector in (
        ".department-title",
        ".person-title",
        ".job-title",
        ".position",
        ".rank",
        "[class*='field--name-field-title']",
        "[class*='person-position']",
    ):
        node = container.select_one(selector)
        if node:
            value = clean_text(node.get_text(" "))
            if value and value.casefold() != name.casefold() and len(value) < 120:
                return value
    lines = [
        clean_text(line)
        for line in container.get_text("\n").split("\n")
        if clean_text(line)
    ]
    for line in lines:
        if (
            5 < len(line) < 110
            and line.casefold() != name.casefold()
            and ACADEMIC_TITLE_RE.search(line)
            and not re.search(r"@|\d{3}[-.]\d{3}", line)
        ):
            return line
    return ""


def _nearby_department(container: Tag) -> str:
    for selector in (
        ".department-department",
        "[class*='field--name-field-department']",
        "[class*='person-department']",
    ):
        node = container.select_one(selector)
        if node:
            value = clean_text(node.get_text(" "))
            if value and len(value) < 120:
                return value
    return ""


def _person_from_card(
    container: Tag, page_url: str, chosen_anchor: Optional[Tag] = None
) -> Optional[Dict[str, Any]]:
    links = container.find_all("a", href=True)
    chosen = chosen_anchor
    if chosen is None or not _looks_like_person_name(chosen.get_text(" ")):
        chosen = None
    if chosen is None:
        for anchor in links:
            label = clean_text(anchor.get_text(" "))
            if _looks_like_person_name(label):
                chosen = anchor
                break
    if chosen is None:
        # Some cards use a heading and a separate "Profile" link.
        heading = container.find(["h3", "h4"])
        if heading and _looks_like_person_name(heading.get_text(" ")):
            for anchor in links:
                if re.search(r"profile|directory|people|faculty", anchor.get("href", ""), re.I):
                    chosen = anchor
                    break
            if chosen is None:
                chosen = heading
    if chosen is None:
        return None
    name = normalize_person_name(chosen.get_text(" "))
    if not _looks_like_person_name(name):
        return None
    profile_url = normalize_url(chosen.get("href"), page_url) if chosen.name == "a" else page_url
    if chosen.name == "a" and PROFILE_URL_RE.search(
        normalize_url(chosen.get("href"), page_url) or ""
    ) is None and not PERSON_LINK_RE.search(chosen.get("href", "")):
        # A name in a non-profile link is usually a publication author or a nav item.
        return None
    section = _card_section(container)
    title = _nearby_title(container, name)
    department = _nearby_department(container)
    email = _nearby_email(container)
    homepage = ""
    for anchor in links:
        label = clean_text(anchor.get_text(" "))
        href = normalize_url(anchor.get("href"), page_url)
        if href and re.search(r"home\s?page|personal|website", label, re.I) and href != profile_url:
            homepage = href
            break
    academic: Optional[bool] = None
    if FACULTY_SECTION_RE.search(section or "") and not STAFF_SECTION_RE.search(section or ""):
        academic = True
    elif STAFF_SECTION_RE.search(section or "") and not FACULTY_SECTION_RE.search(section or ""):
        academic = False
    if ACADEMIC_TITLE_RE.search(title or ""):
        academic = True
    elif NON_ACADEMIC_TITLE_RE.search(title or ""):
        academic = False
    return {
        "name": name,
        "title": title or None,
        "department": department or None,
        "email": email or None,
        "profile_url": profile_url or None,
        "personal_website": homepage or None,
        "section": section or None,
        "academic": academic,
        "source_url": page_url,
        "page_type": "listing",
        "field_sources": {
            "name": [page_url],
            "title": [page_url] if title else [],
            "department": [page_url] if department else [],
            "email": [page_url] if email else [],
            "profile_url": [page_url] if profile_url else [],
        },
    }


def extract_listing_persons(soup: BeautifulSoup, page_url: str) -> List[Dict[str, Any]]:
    persons: Dict[str, Dict[str, Any]] = {}
    # Schema.org persons are the most reliable listing source.
    for node in _jsonld_persons(soup):
        name = normalize_person_name(node.get("name") or "")
        if not _looks_like_person_name(name):
            continue
        email = ""
        raw_email = node.get("email")
        if isinstance(raw_email, str):
            email = raw_email.replace("mailto:", "").strip().lower()
        profile_url = normalize_url(node.get("url") or node.get("@id") or "", page_url)
        person = {
            "name": name,
            "title": clean_text(node.get("jobTitle")) or None,
            "department": None,
            "email": email or None,
            "profile_url": profile_url,
            "personal_website": None,
            "section": None,
            "academic": True if ACADEMIC_TITLE_RE.search(clean_text(node.get("jobTitle"))) else None,
            "source_url": page_url,
            "page_type": "listing",
            "field_sources": {"name": [page_url], "profile_url": [page_url] if profile_url else []},
        }
        key = person_key(name, email)
        if key:
            persons[key] = person

    # Anchor-centric card discovery handles both single cards and grid layouts
    # where many profiles share one large "person-content" wrapper.
    containers: List[Any] = []
    seen_cards = set()
    for anchor in soup.find_all("a", href=True):
        label = clean_text(anchor.get_text(" "))
        if not _looks_like_person_name(label):
            continue
        href = normalize_url(anchor.get("href"), page_url)
        if not href or not (
            PROFILE_URL_RE.search(href) or re.search(r"/~[a-z0-9_.-]+", href, re.I)
        ):
            continue
        card = anchor.find_parent(class_=re.compile(r"person-description", re.I))
        if card is None:
            card = anchor.find_parent(["li", "article", "tr"])
        if card is None:
            card = anchor.parent
        if card is None or id(card) in seen_cards:
            continue
        seen_cards.add(id(card))
        containers.append((card, anchor))
    if not containers:
        for node in soup.find_all(["article", "li"], limit=300):
            if node.find("a", href=True):
                containers.append((node, None))

    for container, chosen_anchor in containers:
        person = _person_from_card(container, page_url, chosen_anchor)
        if not person:
            continue
        key = person_key(person["name"], person.get("email") or "")
        if not key:
            continue
        existing = persons.get(key)
        if existing:
            for field, value in person.items():
                if field in ("field_sources", "source_url", "page_type"):
                    continue
                if value and not existing.get(field):
                    existing[field] = value
            for field, sources in person["field_sources"].items():
                existing["field_sources"].setdefault(field, [])
                existing["field_sources"][field] = list(
                    dict.fromkeys(existing["field_sources"][field] + sources)
                )
        else:
            persons[key] = person

    # Fallback: anchors that look like profile links even without person cards.
    if len(persons) < 2:
        for anchor in soup.find_all("a", href=True):
            label = clean_text(anchor.get_text(" "))
            href_raw = anchor.get("href", "")
            if not _looks_like_person_name(label):
                continue
            href = normalize_url(href_raw, page_url)
            if not href:
                continue
            if not (PROFILE_URL_RE.search(href) or re.search(r"/~[a-z0-9_.-]+", href, re.I)):
                continue
            name = normalize_person_name(label)
            key = person_key(name)
            if not key or key in persons:
                continue
            parent = anchor.find_parent(["li", "div", "tr", "article"]) or anchor
            title = _nearby_title(parent, name)
            email = _nearby_email(parent)
            persons[key] = {
                "name": name,
                "title": title or None,
                "department": _nearby_department(parent) or None,
                "email": email or None,
                "profile_url": href,
                "personal_website": None,
                "section": None,
                "academic": bool(ACADEMIC_TITLE_RE.search(title or "")) or None,
                "source_url": page_url,
                "page_type": "listing",
                "field_sources": {
                    "name": [page_url],
                    "profile_url": [page_url],
                    "email": [page_url] if email else [],
                },
            }
    return list(persons.values())


def _detect_profile(soup: BeautifulSoup, page_url: str, text: str) -> bool:
    if PROFILE_URL_RE.search(page_url):
        return True
    if _jsonld_persons(soup):
        return True
    h1 = soup.find("h1")
    heading = clean_text(h1.get_text(" ")) if h1 else ""
    if not _looks_like_person_name(heading):
        return False
    head_text = truncate(text, 1500)
    if ACADEMIC_TITLE_RE.search(head_text):
        return True
    if (soup.find("a", href=re.compile(r"^mailto:", re.I)) or re.search(
        r"\b[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}\b", head_text
    )) and re.search(r"\b(research|publications?|education|biography)\b", head_text, re.I):
        return True
    return False


def extract_profile(
    soup: BeautifulSoup, page_url: str, fallback_name: str = ""
) -> Optional[Dict[str, Any]]:
    text = clean_main_text(soup)
    if not _detect_profile(soup, page_url, text):
        return None
    jsonld_person = (_jsonld_persons(soup) or [{}])[0]
    name = normalize_person_name(jsonld_person.get("name") or "")
    if not name:
        h1 = soup.find("h1")
        candidate = clean_text(h1.get_text(" ")) if h1 else ""
        if _looks_like_person_name(candidate):
            name = normalize_person_name(candidate)
    if not name:
        title_text = page_title(soup)
        candidate = re.split(r"\s+[|–—-]\s+", title_text)[0]
        if _looks_like_person_name(candidate):
            name = normalize_person_name(candidate)
    if not name and fallback_name:
        name = normalize_person_name(fallback_name)
    if not name or not _looks_like_person_name(name):
        return None

    title = clean_text(jsonld_person.get("jobTitle")) or ""
    if not title:
        for selector in (
            "[class*='field--name-field-title']",
            ".person-title",
            ".job-title",
            ".faculty-title",
            ".profile-title",
            ".position",
        ):
            node = soup.select_one(selector)
            if node:
                candidate = clean_text(node.get_text(" "))
                if candidate and candidate.casefold() != name.casefold() and len(candidate) < 130:
                    title = candidate
                    break
    if not title:
        for line in text.split("\n")[:40]:
            line = clean_text(line)
            if (
                5 < len(line) < 120
                and line.casefold() != name.casefold()
                and ACADEMIC_TITLE_RE.search(line)
                and not line.endswith(".")
            ):
                title = line
                break

    email = ""
    mail = soup.find("a", href=re.compile(r"^mailto:", re.I))
    if mail:
        email = clean_text(mail.get("href").split(":", 1)[1].split("?")[0]).lower()
    if not email:
        match = re.search(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b", text)
        email = match.group(0).lower() if match else ""

    interests = extract_research_interests(soup)
    research_text_parts = []
    for label, items in _find_sections(
        soup, re.compile(r"research interests?|research areas?|areas of interest|research", re.I)
    ):
        for item in items[:10]:
            if len(item) < 1500:
                research_text_parts.append(item)
    research_block = truncate(" ".join(research_text_parts), 5000)
    methods = extract_methodologies(research_block or text[:6000])
    technologies = extract_technologies(research_block or text[:6000])
    projects = extract_projects(soup)
    publications = _extract_publications_with_links(soup, page_url)
    profile_scope = main_content(soup)
    inventory = _link_inventory(profile_scope, page_url)
    evidence = extract_opportunity_evidence(text, page_url, page_title(soup), _page_date(soup))

    lab_links = inventory["lab_links"]
    center_links = inventory["center_links"]
    personal_website = inventory["personal_links"][0]["url"] if inventory["personal_links"] else None
    lab_name = None
    for entry in lab_links:
        label = clean_text(entry.get("label"))
        if label and not re.search(r"^(lab|laboratory|research group|website|home)$", label, re.I):
            lab_name = label
            break
    affiliations = []
    for entry in lab_links + center_links:
        label = clean_text(entry.get("label"))
        if label and len(label) < 160:
            affiliations.append(label)

    academic = True
    if title and NON_ACADEMIC_TITLE_RE.search(title) and not ACADEMIC_TITLE_RE.search(title):
        academic = False
    if not title and not interests and not publications and not re.search(
        r"\b(professor|faculty|research|lecturer)\b", text[:1500], re.I
    ):
        academic = False

    field_sources = {
        "name": [page_url],
        "title": [page_url] if title else [],
        "department": [],
        "email": [page_url] if email else [],
        "profile_url": [page_url],
        "research": [page_url] if research_block else [],
        "publications": [page_url] if publications else [],
        "opportunity_evidence": [page_url] if evidence else [],
    }
    department = infer_department(soup, text)
    if department:
        field_sources["department"] = [page_url]
    return {
        "name": name,
        "title": title or None,
        "department": department or None,
        "email": email or None,
        "profile_url": page_url,
        "personal_website": personal_website,
        "section": None,
        "academic": academic,
        "source_url": page_url,
        "page_type": "profile",
        "research_interests": interests,
        "research_text": research_block,
        "methodologies": methods,
        "technologies": technologies,
        "projects": projects,
        "publications": publications,
        "lab_links": lab_links,
        "center_links": center_links,
        "academic_profiles": inventory["academic_profiles"],
        "lab_name": lab_name,
        "affiliations": affiliations,
        "evidence": evidence,
        "page_date": _page_date(soup),
        "text_excerpt": truncate(text, 7000),
        "field_sources": field_sources,
    }


# ---------------------------------------------------------------------------
# Page-level entry point
# ---------------------------------------------------------------------------


def extract_anchors(
    soup: BeautifulSoup, page_url: str, restrict_to_main: bool = False
) -> List[Dict[str, str]]:
    """Return unique anchors with enough surrounding context for relevance."""
    anchors: Dict[str, Dict[str, str]] = {}
    scope = main_content(soup) if restrict_to_main else soup
    for anchor in scope.find_all("a", href=True):
        url = normalize_url(anchor.get("href"), page_url)
        if not url or url == page_url:
            continue
        label = (
            clean_text(anchor.get_text(" "))
            or clean_text(anchor.get("aria-label"))
            or clean_text(anchor.get("title"))
        )
        parent = anchor.find_parent(["li", "p", "div", "td", "article", "section"])
        context = clean_text(parent.get_text(" ")) if parent is not None else ""
        context = truncate(context, 220)
        existing = anchors.get(url)
        if existing is None or len(label) > len(existing.get("text", "")):
            anchors[url] = {"url": url, "text": label, "context": context}
    return list(anchors.values())


def analyze_page(html: str, page_url: str) -> Dict[str, Any]:
    page_url = normalize_url(page_url) or page_url
    soup = parse_soup(html)
    main_text = clean_main_text(soup)
    title = page_title(soup)
    university = infer_university(soup, page_url)
    department = infer_department(soup, main_text)
    page_type = "content"
    persons: List[Dict[str, Any]] = []
    profile = extract_profile(soup, page_url)
    if profile:
        page_type = "profile"
        persons.append(profile)
    listing_persons = extract_listing_persons(soup, page_url)
    if listing_persons:
        if not profile:
            page_type = "listing"
        # Do not duplicate the profile page's own person record.
        profile_key = person_key(profile["name"], profile.get("email") or "") if profile else None
        for person in listing_persons:
            if profile_key and person_key(person["name"], person.get("email") or "") == profile_key:
                continue
            persons.append(person)
    inventory = _link_inventory(soup, page_url)
    research_items = extract_research_interests(soup)
    publications = _extract_publications_with_links(soup, page_url)
    research_parts: List[str] = []
    for label, items in _find_sections(
        soup, re.compile(r"research interests?|research areas?|areas of interest|research", re.I)
    ):
        research_parts.extend(items[:8])
    research_text = truncate(" ".join(research_parts), 5000)
    js_suspect = len(main_text) < 500 and len(soup.find_all("script")) >= 3
    nested_root = soup.select_one("#root, #__next, #app")
    if nested_root is not None and len(clean_text(nested_root.get_text(" "))) < 80:
        js_suspect = True
    return {
        "url": page_url,
        "title": title,
        "university": university,
        "department": department,
        "page_type": page_type,
        "main_text": main_text,
        "text_excerpt": truncate(main_text, 7000),
        "persons": persons,
        "inventory": inventory,
        "anchors": extract_anchors(soup, page_url, restrict_to_main=bool(profile)),
        "research_interests": research_items,
        "research_text": research_text,
        "methodologies": extract_methodologies(research_text or main_text[:6000]),
        "technologies": extract_technologies(research_text or main_text[:6000]),
        "projects": extract_projects(soup),
        "publications": publications,
        "evidence": extract_opportunity_evidence(
            main_text, page_url, title, _page_date(soup)
        ),
        "publication_count": len(publications),
        "js_suspect": js_suspect,
        "page_date": _page_date(soup),
    }
