from __future__ import annotations

import pytest

from app.utils import (
    normalize_url,
    registrable_domain,
    same_site,
    validate_start_url,
)


def test_normalizes_missing_scheme():
    assert validate_start_url("www.example.edu", allow_private=True) == "https://www.example.edu/"


def test_keeps_query_and_removes_fragment():
    normalized = validate_start_url(
        "https://example.edu/people?department=cs#faculty", allow_private=True
    )
    assert normalized == "https://example.edu/people/?department=cs"


def test_rejects_empty_url():
    with pytest.raises(ValueError):
        validate_start_url("")


def test_rejects_unsupported_scheme():
    with pytest.raises(ValueError):
        validate_start_url("ftp://example.edu/")


def test_rejects_private_network_literal():
    with pytest.raises(ValueError):
        validate_start_url("http://127.0.0.1/")


def test_rejects_localhost():
    with pytest.raises(ValueError):
        validate_start_url("http://localhost:8000/")


def test_rejects_credentials():
    with pytest.raises(ValueError):
        validate_start_url("https://user:pass@example.edu/")


def test_normalize_url_canonicalizes_directory_path():
    assert normalize_url("https://EXAMPLE.edu/people") == "https://example.edu/people/"
    assert normalize_url("https://example.edu/file.pdf") == "https://example.edu/file.pdf"


def test_domain_comparison_handles_subdomains():
    assert registrable_domain("https://www.cs.odu.edu/directory/") == "odu.edu"
    assert same_site("https://cs.odu.edu/", "https://www.odu.edu/computer-science/")
    assert not same_site("https://odu.edu/", "https://example.edu/")
