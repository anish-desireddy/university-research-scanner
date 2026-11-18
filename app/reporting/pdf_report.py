"""Concise professional PDF report for a completed scan."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    BaseDocTemplate,
    CondPageBreak,
    Frame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.platypus.flowables import HRFlowable

from app.utils import display_datetime, escape_xml, truncate

logger = logging.getLogger("urd.reporting")

PAGE_WIDTH, PAGE_HEIGHT = A4
NAVY = colors.HexColor("#172b4d")
SLATE = colors.HexColor("#334155")
MUTED = colors.HexColor("#64748b")
TEAL = colors.HexColor("#0f766e")
LIGHT = colors.HexColor("#f1f5f9")
LINE = colors.HexColor("#cbd5e1")
CATEGORY_COLORS = {
    1: (colors.HexColor("#065f46"), colors.HexColor("#d1fae5")),
    2: (colors.HexColor("#1e40af"), colors.HexColor("#dbeafe")),
    3: (colors.HexColor("#92400e"), colors.HexColor("#fef3c7")),
    4: (colors.HexColor("#374151"), colors.HexColor("#e5e7eb")),
}
SHORT_LABELS = {
    1: "Confirmed opening",
    2: "Actively recruiting",
    3: "Potential opportunity",
    4: "No information found",
}


def _link(url: Optional[str], label: Optional[str] = None) -> str:
    if not url:
        return escape_xml(label or "Not listed")
    safe_url = escape_xml(url)
    text = escape_xml(label or url)
    if not str(url).startswith(("http://", "https://")):
        return text
    return f'<link href="{safe_url}" color="#1d4ed8">{text}</link>'


def _paragraph(value: Any, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape_xml(value).replace("\n", "<br/>"), style)


def _category_label(professor: Dict[str, Any]) -> str:
    opportunity = professor.get("opportunity") or {}
    category = opportunity.get("category")
    if category in SHORT_LABELS:
        return SHORT_LABELS[category]
    if opportunity.get("status") == "failed":
        return "AI analysis failed"
    return "Not analyzed"


def _full_category_label(professor: Dict[str, Any]) -> str:
    opportunity = professor.get("opportunity") or {}
    label = opportunity.get("category_label")
    return label or _category_label(professor)


def _confidence(professor: Dict[str, Any]) -> Optional[int]:
    value = (professor.get("opportunity") or {}).get("confidence")
    if isinstance(value, (int, float)):
        return int(value)
    return None


def _research_area(professor: Dict[str, Any], limit: int = 2) -> str:
    research = professor.get("research") or {}
    interests = list(research.get("interests") or [])
    if not interests:
        interests = list(research.get("ai_interests") or [])
    if not interests:
        return "Not listed"
    return "; ".join(truncate(item, 55) for item in interests[:limit])


def _styles() -> Dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "cover_title": ParagraphStyle(
            "CoverTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=30,
            leading=35,
            textColor=NAVY,
            alignment=TA_LEFT,
            spaceAfter=12,
        ),
        "cover_subtitle": ParagraphStyle(
            "CoverSubtitle",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=13,
            leading=19,
            textColor=SLATE,
            spaceAfter=6,
        ),
        "cover_meta": ParagraphStyle(
            "CoverMeta",
            parent=base["Normal"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=15,
            textColor=SLATE,
        ),
        "h1": ParagraphStyle(
            "H1",
            parent=base["Heading1"],
            fontName="Helvetica-Bold",
            fontSize=17,
            leading=21,
            textColor=NAVY,
            spaceBefore=4,
            spaceAfter=9,
            keepWithNext=True,
        ),
        "h2": ParagraphStyle(
            "H2",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12.5,
            leading=16,
            textColor=NAVY,
            spaceBefore=12,
            spaceAfter=6,
            keepWithNext=True,
        ),
        "h3": ParagraphStyle(
            "H3",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=14,
            textColor=SLATE,
            spaceBefore=8,
            spaceAfter=3,
            keepWithNext=True,
        ),
        "body": ParagraphStyle(
            "Body",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.1,
            leading=13.2,
            textColor=colors.HexColor("#1f2937"),
            spaceAfter=5,
        ),
        "small": ParagraphStyle(
            "Small",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=7.4,
            leading=9.6,
            textColor=colors.HexColor("#1f2937"),
        ),
        "small_bold": ParagraphStyle(
            "SmallBold",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.4,
            leading=9.6,
            textColor=colors.white,
        ),
        "meta": ParagraphStyle(
            "Meta",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.4,
            leading=11.6,
            textColor=SLATE,
            spaceAfter=3,
        ),
        "prof_name": ParagraphStyle(
            "ProfName",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=12,
            leading=15,
            textColor=NAVY,
            spaceBefore=0,
            spaceAfter=3,
            keepWithNext=True,
        ),
        "category": ParagraphStyle(
            "Category",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=9,
            leading=12,
            textColor=NAVY,
            spaceAfter=2,
        ),
        "evidence": ParagraphStyle(
            "Evidence",
            parent=base["BodyText"],
            fontName="Helvetica-Oblique",
            fontSize=8.4,
            leading=11.8,
            textColor=colors.HexColor("#334155"),
            leftIndent=8,
            borderPadding=4,
            spaceAfter=4,
        ),
        "note": ParagraphStyle(
            "Note",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=11,
            textColor=MUTED,
            spaceAfter=3,
        ),
        "center": ParagraphStyle(
            "Center",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            alignment=TA_CENTER,
            textColor=SLATE,
        ),
    }


def _cover(story: List[Any], result: Dict[str, Any], styles: Dict[str, ParagraphStyle]) -> None:
    scan = result.get("scan") or {}
    university = result.get("university") or "University not identified"
    department = result.get("department") or "Department not identified"
    story.append(Spacer(1, 2.8 * cm))
    story.append(
        Paragraph(
            '<font color="#0f766e"><b>UNDERGRADUATE RESEARCH</b></font>',
            styles["cover_subtitle"],
        )
    )
    story.append(Paragraph("University Research Discovery Report", styles["cover_title"]))
    story.append(
        HRFlowable(width="38%", thickness=3, color=TEAL, spaceBefore=4, spaceAfter=22, hAlign="LEFT")
    )
    story.append(Paragraph(escape_xml(university), styles["h1"]))
    story.append(Paragraph(escape_xml(department), styles["cover_subtitle"]))
    story.append(Spacer(1, 1.4 * cm))
    ai = scan.get("ai") or {}
    cover_rows = [
        [
            "Scanned URL",
            Paragraph(_link(scan.get("url"), scan.get("url")), styles["cover_meta"]),
        ],
        [
            "Scan date",
            Paragraph(escape_xml(display_datetime(scan.get("created_at"))), styles["cover_meta"]),
        ],
        [
            "Professors identified",
            Paragraph(f"{len(result.get('professors') or [])}", styles["cover_meta"]),
        ],
        [
            "AI provider",
            Paragraph(
                f"Ollama ({escape_xml(ai.get('model') or 'not configured')})",
                styles["cover_meta"],
            ),
        ],
        [
            "AI status",
            Paragraph(escape_xml(str(ai.get("status") or "not run")), styles["cover_meta"]),
        ],
    ]
    table = Table(cover_rows, colWidths=[4.2 * cm, 9.4 * cm])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("TEXTCOLOR", (0, 0), (0, -1), SLATE),
                ("TEXTCOLOR", (1, 0), (1, -1), colors.HexColor("#111827")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 0), (-1, -2), 0.3, LINE),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 2.0 * cm))
    story.append(
        Paragraph(
            "This report summarizes publicly available information and local AI "
            "assessments. An assessment is not a statement from the professor or "
            "the university, and the absence of public opportunity information "
            "does not mean that no opportunities exist.",
            styles["note"],
        )
    )
    story.append(Spacer(1, 0.4 * cm))
    story.append(
        Paragraph(
            f"Generated {escape_xml(display_datetime(scan.get('completed_at')))} · "
            "University Research Discovery",
            styles["note"],
        )
    )
    story.append(NextPageTemplate("body"))
    story.append(PageBreak())


def _executive_summary(
    story: List[Any], result: Dict[str, Any], styles: Dict[str, ParagraphStyle]
) -> None:
    summary = (result.get("scan") or {}).get("summary") or {}
    story.append(Paragraph("Executive Summary", styles["h1"]))
    total = int(summary.get("professors_identified") or len(result.get("professors") or []))
    analyzed = int(summary.get("professors_analyzed") or 0)
    story.append(
        Paragraph(
            f"The crawler identified <b>{total}</b> faculty members and analyzed "
            f"<b>{analyzed}</b> of them. Opportunity classifications reflect only "
            "the public evidence collected during this scan.",
            styles["body"],
        )
    )
    rows = [
        ["Measure", "Count"],
        ["Professors identified", str(total)],
        ["Professors analyzed by AI", str(analyzed)],
        ["Confirmed open positions", str(summary.get("confirmed_open") or 0)],
        ["Actively recruiting / welcoming students", str(summary.get("actively_recruiting") or 0)],
        ["Potential opportunities", str(summary.get("potential_opportunity") or 0)],
        ["No opportunity information found", str(summary.get("no_information") or 0)],
    ]
    if summary.get("not_analyzed"):
        rows.append(["Not analyzed (AI unavailable or failed)", str(summary.get("not_analyzed"))])
    table = Table(rows, colWidths=[11.4 * cm, 3.0 * cm], hAlign="LEFT")
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("ALIGN", (1, 0), (1, -1), "RIGHT"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
            ]
        )
    )
    story.append(Spacer(1, 4))
    story.append(table)
    warnings = (result.get("crawl") or {}).get("warnings") or []
    if warnings:
        story.append(Paragraph("Scan warnings", styles["h3"]))
        for warning in warnings[:5]:
            story.append(Paragraph(f"• {escape_xml(warning)}", styles["meta"]))
    ai = (result.get("scan") or {}).get("ai") or {}
    if ai.get("status") not in ("complete", "partial"):
        story.append(Spacer(1, 6))
        story.append(
            Paragraph(
                f"<b>AI analysis status:</b> {escape_xml(str(ai.get('status') or 'not run'))}. "
                f"{escape_xml(ai.get('message') or '')}",
                styles["note"],
            )
        )


def _directory(
    story: List[Any], professors: List[Dict[str, Any]], styles: Dict[str, ParagraphStyle]
) -> None:
    story.append(Paragraph("Professor Directory", styles["h1"]))
    header = [
        Paragraph("Professor", styles["small_bold"]),
        Paragraph("Department", styles["small_bold"]),
        Paragraph("Position", styles["small_bold"]),
        Paragraph("Research area", styles["small_bold"]),
        Paragraph("Opportunity", styles["small_bold"]),
        Paragraph("Conf.", styles["small_bold"]),
    ]
    rows: List[List[Any]] = [header]
    for professor in professors:
        confidence = _confidence(professor)
        rows.append(
            [
                Paragraph(escape_xml(professor.get("name") or "Unknown"), styles["small"]),
                Paragraph(
                    escape_xml(professor.get("department") or "Not listed"),
                    styles["small"],
                ),
                Paragraph(escape_xml(professor.get("title") or "Faculty"), styles["small"]),
                Paragraph(escape_xml(_research_area(professor)), styles["small"]),
                Paragraph(escape_xml(_category_label(professor)), styles["small"]),
                Paragraph(
                    escape_xml(str(confidence) if confidence is not None else "—"),
                    styles["small"],
                ),
            ]
        )
    table = Table(
        rows,
        colWidths=[3.0 * cm, 2.5 * cm, 2.8 * cm, 3.9 * cm, 3.0 * cm, 1.1 * cm],
        repeatRows=1,
        hAlign="LEFT",
    )
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
                ("GRID", (0, 0), (-1, -1), 0.25, LINE),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 6))
    story.append(
        Paragraph(
            "Confidence measures evidence strength, not the probability that a "
            "professor will accept a student.",
            styles["note"],
        )
    )


def _professor_profile(
    story: List[Any], professor: Dict[str, Any], styles: Dict[str, ParagraphStyle]
) -> None:
    story.append(CondPageBreak(9.0 * cm))
    opportunity = professor.get("opportunity") or {}
    research = professor.get("research") or {}
    story.append(Paragraph(escape_xml(professor.get("name") or "Unknown"), styles["prof_name"]))
    meta_bits = [
        escape_xml(professor.get("title") or "Position not listed"),
        escape_xml(professor.get("department") or "Department not listed"),
    ]
    if professor.get("email"):
        meta_bits.append(_link(f"mailto:{professor.get('email')}", professor.get("email")))
    if professor.get("profile_url"):
        meta_bits.append(_link(professor.get("profile_url"), "Faculty profile"))
    story.append(Paragraph(" · ".join(meta_bits), styles["meta"]))

    summary = research.get("summary")
    if summary:
        story.append(_paragraph(summary, styles["body"]))
    else:
        story.append(
            Paragraph(
                "<b>Research summary:</b> AI analysis was not completed for this "
                "professor. The collected profile information is preserved in the JSON report.",
                styles["note"],
            )
        )
    interests = research.get("interests") or research.get("ai_interests") or []
    if interests:
        story.append(
            Paragraph(
                "<b>Research interests:</b> "
                + escape_xml("; ".join(str(item) for item in interests[:8])),
                styles["meta"],
            )
        )
    lab_links = research.get("lab_links") or []
    if lab_links:
        lab_text = ", ".join(
            _link(entry.get("url"), entry.get("label") or entry.get("url"))
            for entry in lab_links[:3]
            if entry.get("url")
        )
        if lab_text:
            story.append(Paragraph(f"<b>Laboratory / group:</b> {lab_text}", styles["meta"]))
    elif professor.get("personal_website"):
        story.append(
            Paragraph(
                f"<b>Personal website:</b> "
                f"{_link(professor.get('personal_website'), professor.get('personal_website'))}",
                styles["meta"],
            )
        )

    publications = professor.get("publications") or []
    if publications:
        story.append(Paragraph("Selected publications", styles["h3"]))
        for publication in publications[:3]:
            bits = []
            if publication.get("year"):
                bits.append(f"({publication.get('year')})")
            title = escape_xml(publication.get("title") or "Untitled")
            if publication.get("url"):
                title = _link(publication.get("url"), publication.get("title") or "Publication")
            venue = publication.get("venue")
            line = f"• {title} {escape_xml(' '.join(bits))}".strip()
            if venue:
                line += f" — <i>{escape_xml(truncate(venue, 120))}</i>"
            story.append(Paragraph(line, styles["meta"]))
        if len(publications) > 3:
            story.append(
                Paragraph(f"• … and {len(publications) - 3} more in the JSON report.", styles["note"])
            )

    category = opportunity.get("category")
    color, background = CATEGORY_COLORS.get(category, (MUTED, LIGHT))
    confidence = _confidence(professor)
    badge_text = _full_category_label(professor)
    if confidence is not None:
        badge_text += f" · {confidence}/100 confidence"
    badge = Table(
        [[Paragraph(f'<font color="{color.hexval().replace("0x", "#")}"><b>{escape_xml(badge_text)}</b></font>', styles["category"])]],
        colWidths=[14.0 * cm],
    )
    badge.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), background),
                ("BOX", (0, 0), (-1, -1), 0.4, color),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(Spacer(1, 5))
    story.append(badge)

    explanation = opportunity.get("explanation")
    if explanation:
        story.append(Spacer(1, 3))
        story.append(_paragraph(explanation, styles["body"]))
    confidence_explanation = opportunity.get("confidence_explanation")
    if confidence_explanation and confidence is not None:
        story.append(
            Paragraph(
                "<b>Confidence:</b> " + escape_xml(confidence_explanation),
                styles["note"],
            )
        )

    evidence = opportunity.get("evidence") or []
    if evidence:
        story.append(Paragraph("Supporting public evidence", styles["h3"]))
        for item in evidence[:2]:
            date = item.get("date") or "date unknown"
            current = (
                "current"
                if item.get("current") is True
                else ("possibly outdated" if item.get("current") is False else "recency unknown")
            )
            quote = escape_xml(truncate(item.get("quote") or "", 320))
            source = _link(item.get("url"), "source")
            explanation_text = item.get("explanation")
            line = f'“{quote}” — {source} <font color="#64748b">({escape_xml(str(date))}, {current})</font>'
            if explanation_text:
                line += f"<br/><font color='#475569'>{escape_xml(explanation_text)}</font>"
            story.append(Paragraph(line, styles["evidence"]))
    elif opportunity.get("status") == "not_analyzed":
        story.append(
            Paragraph(
                "No AI opportunity assessment was completed. Absence of public "
                "information does not mean that no opportunities exist.",
                styles["note"],
            )
        )
    else:
        story.append(
            Paragraph(
                "No public evidence of an undergraduate research opening or "
                "recruitment statement was found. Absence of information does not "
                "mean absence of opportunities.",
                styles["note"],
            )
        )
    story.append(Spacer(1, 7))
    story.append(HRFlowable(width="100%", thickness=0.4, color=LINE, spaceAfter=7))


def _findings(
    story: List[Any], professors: List[Dict[str, Any]], styles: Dict[str, ParagraphStyle]
) -> None:
    story.append(Paragraph("Consolidated Research Opportunity Findings", styles["h1"]))
    groups = {
        1: "Confirmed open positions",
        2: "Actively recruiting / welcoming students",
        3: "Potential opportunities",
        4: "No opportunity information found",
    }
    for category, heading in groups.items():
        members = [
            professor
            for professor in professors
            if (professor.get("opportunity") or {}).get("category") == category
        ]
        story.append(Paragraph(heading, styles["h2"]))
        if not members:
            story.append(Paragraph("None identified in this scan.", styles["body"]))
            continue
        for professor in members:
            confidence = _confidence(professor)
            confidence_text = f" ({confidence}/100)" if confidence is not None else ""
            story.append(
                Paragraph(
                    f"• <b>{escape_xml(professor.get('name') or 'Unknown')}</b>"
                    f"{confidence_text} — {escape_xml(professor.get('department') or 'Department not listed')}",
                    styles["body"],
                )
            )
    not_analyzed = [
        professor
        for professor in professors
        if (professor.get("opportunity") or {}).get("category") is None
    ]
    story.append(Paragraph("Professors requiring manual investigation", styles["h2"]))
    if not not_analyzed:
        story.append(
            Paragraph(
                "None. Every identified professor received an AI opportunity assessment.",
                styles["body"],
            )
        )
    else:
        story.append(
            Paragraph(
                "These professors could not be classified from the available evidence "
                "or were not analyzed. Review their profile pages and contact them directly.",
                styles["body"],
            )
        )
        for professor in not_analyzed:
            story.append(
                Paragraph(
                    f"• {escape_xml(professor.get('name') or 'Unknown')} — "
                    f"{_link(professor.get('profile_url'), 'profile')}",
                    styles["body"],
                )
            )


def _methodology(
    story: List[Any], result: Dict[str, Any], styles: Dict[str, ParagraphStyle]
) -> None:
    story.append(PageBreak())
    story.append(Paragraph("Methodology and Limitations", styles["h1"]))
    scan = result.get("scan") or {}
    ai = scan.get("ai") or {}
    paragraphs = [
        "<b>Discovery.</b> The crawler starts at the submitted URL and follows "
        "relevance-scored links within the university site and, when they clearly "
        "represent academic work, to external laboratory, research-group, and "
        "personal academic websites. It respects robots.txt, applies a request delay, "
        "deduplicates URLs, and enforces page and external-domain limits. "
        "Directory and profile pages are parsed for names, titles, departments, "
        "emails, research interests, laboratories, and publication lists. Every "
        "professor is deduplicated across pages.",
        "<b>Evidence.</b> Statements about undergraduate research, openings, "
        "recruitment, and student participation are extracted verbatim with their "
        "source URL and page date when available. The assessment distinguishes "
        "current, outdated, and undated evidence.",
        "<b>AI analysis.</b> Each professor's collected information and evidence "
        "candidates are sent to the locally hosted model configured in config.yaml "
        f"(currently {escape_xml(str(ai.get('model') or 'not configured'))}). The model "
        "produces a research summary, publication themes, one of four opportunity "
        "categories, and a confidence score. Model citations are grounded against "
        "the supplied quotations; unsupported citations are discarded. A category "
        "that claims an opening without grounded positive evidence is downgraded.",
        "<b>Interpretation.</b> Confidence measures the strength and quality of the "
        "public evidence, not the probability of acceptance. A high confidence score "
        "does not imply an open position. A laboratory or research group does not "
        "automatically mean the professor is recruiting.",
        "<b>Limitations.</b> Public pages may be incomplete, outdated, or behind a "
        "login. JavaScript-rendered content may not be captured unless Playwright is "
        "installed. The crawler cannot see private openings, unadvertised mentoring "
        "capacity, or departmental policies. The AI can make mistakes; verify every "
        "opportunity with the professor or department before applying. Absence of "
        "information does not mean absence of opportunities.",
    ]
    for text in paragraphs:
        story.append(Paragraph(text, styles["body"]))
    story.append(Spacer(1, 8))
    stats = (scan.get("stats") or {})
    story.append(Paragraph("Scan details", styles["h2"]))
    details = [
        ["Original URL", _link(scan.get("url"), scan.get("url"))],
        ["Final URL", _link(scan.get("final_url"), scan.get("final_url"))],
        ["Pages visited", str(stats.get("pages_visited") or 0)],
        ["External domains", str(len(stats.get("external_domains") or []))],
        ["Publications collected", str(stats.get("publications_collected") or 0)],
        ["Evidence snippets", str(stats.get("evidence_snippets") or 0)],
        ["Crawl errors recorded", str(stats.get("errors") or 0)],
        ["Manual-review records", str(stats.get("manual_review") or 0)],
    ]
    table = Table(details, colWidths=[4.6 * cm, 9.4 * cm])
    table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica"),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("TEXTCOLOR", (0, 0), (0, -1), SLATE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LINEBELOW", (0, 0), (-1, -1), 0.25, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 4),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 10))
    story.append(Paragraph("Data source and attribution", styles["h2"]))
    story.append(
        Paragraph(
            "All source URLs are retained in the accompanying JSON report. "
            "Publication and profile information belongs to the respective "
            "institutions and authors. This report is an informational tool, not "
            "an official university publication.",
            styles["note"],
        )
    )


def _header_footer(canvas: Any, doc: Any, university: str) -> None:
    canvas.saveState()
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.5)
    canvas.line(1.8 * cm, PAGE_HEIGHT - 1.45 * cm, PAGE_WIDTH - 1.8 * cm, PAGE_HEIGHT - 1.45 * cm)
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(MUTED)
    canvas.drawString(1.8 * cm, PAGE_HEIGHT - 1.25 * cm, "University Research Discovery")
    canvas.drawRightString(
        PAGE_WIDTH - 1.8 * cm,
        PAGE_HEIGHT - 1.25 * cm,
        truncate(university, 62),
    )
    canvas.line(1.8 * cm, 1.5 * cm, PAGE_WIDTH - 1.8 * cm, 1.5 * cm)
    canvas.drawString(
        1.8 * cm,
        1.1 * cm,
        f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}",
    )
    canvas.drawRightString(PAGE_WIDTH - 1.8 * cm, 1.1 * cm, f"Page {doc.page}")
    canvas.restoreState()


def write_pdf_report(result: Dict[str, Any], path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    styles = _styles()
    university = result.get("university") or "University not identified"
    professors = result.get("professors") or []

    doc = BaseDocTemplate(
        str(target),
        pagesize=A4,
        leftMargin=1.8 * cm,
        rightMargin=1.8 * cm,
        topMargin=1.8 * cm,
        bottomMargin=1.7 * cm,
        title="University Research Discovery Report",
        author="University Research Discovery",
        subject="Undergraduate research opportunity scan",
    )
    cover_frame = Frame(
        1.9 * cm,
        1.7 * cm,
        PAGE_WIDTH - 3.8 * cm,
        PAGE_HEIGHT - 3.4 * cm,
        id="cover",
    )
    body_frame = Frame(
        1.8 * cm,
        1.8 * cm,
        PAGE_WIDTH - 3.6 * cm,
        PAGE_HEIGHT - 3.6 * cm,
        id="body",
    )
    doc.addPageTemplates(
        [
            PageTemplate(id="cover", frames=[cover_frame]),
            PageTemplate(
                id="body",
                frames=[body_frame],
                onPage=lambda canvas, document: _header_footer(canvas, document, university),
            ),
        ]
    )
    story: List[Any] = []
    _cover(story, result, styles)
    _executive_summary(story, result, styles)
    _directory(story, professors, styles)
    story.append(PageBreak())
    story.append(Paragraph("Individual Professor Summaries", styles["h1"]))
    if not professors:
        story.append(
            Paragraph(
                "No professors were identified during this scan. See the scan details "
                "and the accompanying JSON report for crawl errors and pages that "
                "require manual review.",
                styles["body"],
            )
        )
    for professor in professors:
        _professor_profile(story, professor, styles)
    story.append(PageBreak())
    _findings(story, professors, styles)
    _methodology(story, result, styles)

    doc.build(story)
    logger.info("PDF report written: %s (%s professors)", target, len(professors))
    return target
