"""Shared utility helpers."""

from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit, urlunsplit

import tldextract

_TLD_EXTRACT = tldextract.TLDExtract(suffix_list_urls=())

_PRIVATE_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "ip6-localhost",
    "ip6-loopback",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def now_iso() -> str:
    return utc_now().isoformat(timespec="seconds")


def scan_timestamp() -> str:
    return utc_now().astimezone().strftime("%Y-%m-%d_%H%M%S")


def display_datetime(value: str | None = None) -> str:
    if not value:
        return utc_now().astimezone().strftime("%B %d, %Y at %H:%M")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone().strftime("%B %d, %Y at %H:%M")
    except ValueError:
        return value


def normalize_whitespace(text: Any) -> str:
    if text is None:
        return ""
    return re.sub(r"\s+", " ", str(text)).strip()


def clean_text(text: Any) -> str:
    """Collapse whitespace and strip common invisible separators."""
    value = normalize_whitespace(text)
    return value.replace("\u200b", "").replace("\xa0", " ").strip()


def truncate(text: str, length: int, suffix: str = "…") -> str:
    text = normalize_whitespace(text)
    if len(text) <= length:
        return text
    return text[: max(0, length - len(suffix))].rstrip() + suffix


def dedupe(items: Iterable[Any]) -> List[Any]:
    seen = set()
    result = []
    for item in items:
        key = item.lower() if isinstance(item, str) else item
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def unique_strings(items: Iterable[Any]) -> List[str]:
    seen = set()
    result: List[str] = []
    for item in items:
        value = normalize_whitespace(item)
        if not value:
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def atomic_write_json(path: str | Path, data: Any) -> None:
    """Write UTF-8 JSON atomically so a crash cannot leave a half file."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(
        prefix=target.name + ".", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def read_json(path: str | Path, default: Any = None) -> Any:
    try:
        with Path(path).open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        return default


def normalize_url(url: str, base: Optional[str] = None) -> Optional[str]:
    """Return a canonical absolute http(s) URL without a fragment."""
    from urllib.parse import urljoin

    if not url:
        return None
    url = url.strip()
    if url.startswith(("mailto:", "tel:", "javascript:", "data:")):
        return None
    if base:
        url = urljoin(base, url)
    parts = urlsplit(url)
    if parts.scheme.lower() not in ("http", "https") or not parts.hostname:
        return None
    host = parts.hostname.lower().rstrip(".")
    port = parts.port
    netloc = host
    if port and not (
        (parts.scheme.lower() == "http" and port == 80)
        or (parts.scheme.lower() == "https" and port == 443)
    ):
        netloc = f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parts.path or "/")
    # Directory index pages are canonically represented with a trailing slash.
    if not path.endswith("/") and "." not in path.rsplit("/", 1)[-1]:
        path += "/"
    return urlunsplit((parts.scheme.lower(), netloc, path, parts.query, ""))


def href_is_document(url: str) -> bool:
    return bool(re.search(r"\.(pdf|docx?|bib|ris)(?:$|\?)", url or "", re.I))


def registrable_domain(url_or_host: str) -> str:
    host = url_or_host
    if "://" in host:
        host = urlsplit(host).hostname or ""
    host = host.split(":")[0].lower().strip(".")
    if not host:
        return ""
    if host in _PRIVATE_HOSTNAMES:
        return host
    try:
        ipaddress.ip_address(host)
        return host
    except ValueError:
        pass
    extracted = _TLD_EXTRACT(host)
    if extracted.domain and extracted.suffix:
        return f"{extracted.domain}.{extracted.suffix}"
    return host


def same_site(url_a: str, url_b: str) -> bool:
    return registrable_domain(url_a) == registrable_domain(url_b)


def _is_private_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    return (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_reserved
        or address.is_multicast
        or address.is_unspecified
    )


def is_private_host(hostname: str) -> bool:
    host = (hostname or "").lower().strip(".")
    if not host:
        return True
    if host in _PRIVATE_HOSTNAMES or host.endswith(".local"):
        return True
    if _is_private_ip(host):
        return True
    return False


def validate_start_url(raw_url: str, allow_private: bool = False) -> str:
    """Validate and normalize a user-supplied scan URL.

    Raises ValueError with a user-facing message. DNS is only consulted for
    private-network protection; unreachable hosts are reported by the crawler.
    """
    raw = (raw_url or "").strip()
    if not raw:
        raise ValueError("Enter a university webpage URL.")
    if "://" not in raw:
        raw = "https://" + raw
    parts = urlsplit(raw)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError("Only http:// and https:// URLs are supported.")
    if not parts.hostname:
        raise ValueError("The URL does not contain a valid hostname.")
    if parts.username or parts.password:
        raise ValueError("URLs containing credentials are not supported.")
    host = parts.hostname.lower()
    if "." not in host and not host.startswith("localhost"):
        raise ValueError("Enter a complete web address, for example https://www.example.edu/.")
    if not allow_private:
        if is_private_host(host):
            raise ValueError("Private and local network addresses cannot be scanned.")
        try:
            infos = socket.getaddrinfo(host, None)
            for info in infos:
                address = info[4][0]
                if _is_private_ip(address):
                    raise ValueError(
                        "This hostname resolves to a private network address and cannot be scanned."
                    )
        except socket.gaierror:
            # The crawler will produce a clear connection error if it is offline.
            pass
    normalized = normalize_url(raw)
    if not normalized:
        raise ValueError("The URL could not be normalized.")
    return normalized


def slugify(value: str, fallback: str = "item") -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "-", value or "").strip("-").lower()
    return text or fallback


def safe_filename(value: str, fallback: str = "file") -> str:
    text = re.sub(r"[^a-zA-Z0-9._-]+", "_", value or "").strip("._")
    return text or fallback


def split_sentences(text: str, max_sentences: int = 400) -> List[str]:
    text = normalize_whitespace(text)
    if not text:
        return []
    # Protect common abbreviations from being split.
    protected = text
    for abbreviation in ("Dr.", "Prof.", "Mr.", "Ms.", "Mrs.", "St.", "vs.", "e.g.", "i.e."):
        protected = protected.replace(abbreviation, abbreviation.replace(".", "§"))
    chunks = re.split(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(])", protected)
    sentences = []
    for chunk in chunks:
        sentence = chunk.replace("§", ".").strip()
        if sentence:
            sentences.append(sentence)
        if len(sentences) >= max_sentences:
            break
    return sentences


def domain_counts(urls: Iterable[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for url in urls:
        domain = registrable_domain(url)
        counts[domain] = counts.get(domain, 0) + 1
    return counts


def escape_xml(value: Any) -> str:
    from xml.sax.saxutils import escape

    return escape("" if value is None else str(value), {'"': "&quot;"})


def shorten_url(url: str, limit: int = 70) -> str:
    if len(url) <= limit:
        return url
    return url[: limit - 1] + "…"
