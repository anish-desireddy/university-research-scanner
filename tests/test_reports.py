from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from app.reporting.json_report import write_json_report
from app.reporting.pdf_report import write_pdf_report
from tests.helpers import make_professor, make_result


def test_json_report_is_valid_utf8_and_complete(tmp_path):
    result = make_result()
    path = tmp_path / "research_results.json"
    write_json_report(result, path)
    text = path.read_text(encoding="utf-8")
    assert "Jane Doe" in text
    assert '"professors"' in text
    assert '"opportunity"' in text
    assert "Designing accessible data visualizations" in text


def test_pdf_report_includes_every_professor(tmp_path):
    second = make_professor(
        name="John Smith",
        category=4,
        confidence=15,
        summary="John Smith studies distributed systems and cloud computing.",
        evidence=[],
        publications=[],
        email="john.smith@example.edu",
    )
    second["id"] = "prof_002"
    result = make_result([make_professor(), second])
    path = tmp_path / "research_report.pdf"
    write_pdf_report(result, path)

    assert path.exists()
    assert path.stat().st_size > 1000
    assert path.read_bytes().startswith(b"%PDF")

    reader = PdfReader(str(path))
    assert len(reader.pages) >= 3
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    assert "Jane Doe" in text
    assert "John Smith" in text
    assert "Executive Summary" in text
    assert "Professor Directory" in text
    assert "Individual Professor Summaries" in text
    assert "Methodology and Limitations" in text
    assert "No information found" in text


def test_pdf_handles_unanalyzed_professor(tmp_path):
    professor = make_professor(category=4, confidence=12)
    professor["opportunity"]["category"] = None
    professor["opportunity"]["category_label"] = None
    professor["opportunity"]["confidence"] = None
    professor["opportunity"]["status"] = "not_analyzed"
    professor["research"]["summary"] = None
    result = make_result([professor])
    path = tmp_path / "unanalyzed.pdf"
    write_pdf_report(result, path)
    text = "\n".join(page.extract_text() or "" for page in PdfReader(str(path)).pages)
    assert "Not analyzed" in text
    assert "AI analysis was not completed" in text
