from __future__ import annotations

import requests

from app.ai import confidence, opportunity
from app.ai.client import OllamaClient, model_matches, parse_json_object
from tests.helpers import make_professor


def _professor_with_evidence():
    return make_professor(category=3, confidence=55)


def test_grounded_evidence_is_preserved():
    professor = _professor_with_evidence()
    data = {
        "opportunity_category": 2,
        "classification_explanation": "The professor explicitly welcomes undergraduates.",
        "evidence": [
            {
                "id": "E1",
                "quote": "I welcome undergraduate students who are interested in accessibility research.",
                "explanation": "An explicit invitation to undergraduates.",
            }
        ],
    }
    result = opportunity.parse_classification(data, professor)
    assert result["category"] == 2
    assert len(result["evidence"]) == 1
    assert result["evidence"][0]["url"] == professor["profile_url"]


def test_confirmed_opening_without_evidence_is_not_claimed():
    professor = make_professor()
    professor["opportunity"]["evidence"] = []
    data = {
        "opportunity_category": 1,
        "classification_explanation": "There may be an opening.",
        "evidence": [],
    }
    result = opportunity.parse_classification(data, professor)
    assert result["category"] == 4
    assert result["notes"]


def test_ungrounded_citation_is_discarded():
    professor = _professor_with_evidence()
    data = {
        "opportunity_category": 2,
        "classification_explanation": "Recruiting.",
        "evidence": [
            {
                "id": "E1",
                "quote": "This quote was never on the page.",
                "explanation": "Unsupported.",
            }
        ],
    }
    result = opportunity.parse_classification(data, professor)
    assert result["evidence"] == []
    assert result["category"] == 3


def test_confidence_is_capped_without_evidence():
    result = confidence.calibrate_confidence(
        {"confidence_score": 90, "confidence_explanation": "Very strong."},
        category=3,
        evidence=[],
    )
    assert result["score"] <= 20
    assert result["notes"]


def test_confidence_capped_for_outdated_positive_evidence():
    evidence = [
        {
            "url": "https://example.edu/old",
            "quote": "We welcome undergraduates.",
            "current": False,
            "direction": "positive",
        }
    ]
    result = confidence.calibrate_confidence(
        {"confidence_score": 95, "confidence_explanation": "Strong evidence."},
        category=2,
        evidence=evidence,
    )
    assert result["score"] <= 60


def test_confidence_accepts_current_strong_evidence():
    evidence = [
        {
            "url": "https://example.edu/new",
            "quote": "We welcome undergraduates to join the lab.",
            "current": True,
            "direction": "positive",
        }
    ]
    result = confidence.calibrate_confidence(
        {"confidence_score": 88, "confidence_explanation": "Current and explicit."},
        category=2,
        evidence=evidence,
    )
    assert result["score"] == 88


def test_json_parsing_handles_fences_and_noise():
    assert parse_json_object('{"a": 1}') == {"a": 1}
    assert parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert parse_json_object('Here is the result: {"a": 1} thanks') == {"a": 1}
    assert parse_json_object("not json") is None


def test_model_matching():
    assert model_matches("llama3.2:latest", "llama3.2:latest")
    assert model_matches("llama3.2", "llama3.2:latest")
    assert not model_matches("llama3.2", "llama3.2:1b")
    assert not model_matches("llama3.2:latest", "gemma3:270m")


def test_ollama_unavailable_status(monkeypatch):
    def fail(*args, **kwargs):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(requests, "get", fail)
    client = OllamaClient(
        {
            "base_url": "http://127.0.0.1:11434",
            "model": "llama3.2:latest",
            "timeout_seconds": 3,
        }
    )
    status = client.status()
    assert status["available"] is False
    assert status["model_installed"] is False
    assert status["setup_instructions"]
    assert "ollama serve" in " ".join(status["setup_instructions"])
