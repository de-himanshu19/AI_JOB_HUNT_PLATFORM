"""URL construction and identity helpers for EnglishJobs.de."""

from __future__ import annotations

import hashlib
from urllib.parse import parse_qsl, quote, urlencode, urljoin, urlparse, urlunparse


TRACKING_QUERY_KEYS = {
    "e",
    "prev",
    "ql",
    "sig",
}


def _normalize_component(value: str, *, separator: str) -> str:
    collapsed = " ".join(value.strip().split()).lower().replace(" ", separator)
    return quote(collapsed, safe="-_")


def build_state_url(base_url: str, state_slug: str, page: int = 1) -> str:
    url = base_url.rstrip("/") + f"/in/{quote(state_slug.strip(), safe='-_')}"
    if page > 1:
        url += "?" + urlencode({"page": page})
    return url


def build_keyword_url(
    base_url: str,
    query: str,
    location: str | None = None,
    page: int = 1,
) -> str:
    keyword = _normalize_component(query, separator="_")
    if location:
        path = f"/in/{_normalize_component(location, separator='-')}/{keyword}"
    else:
        path = f"/jobs/{keyword}"
    url = base_url.rstrip("/") + path
    if page > 1:
        url += "?" + urlencode({"page": page})
    return url


def absolutize_url(base_url: str, href: str | None) -> str | None:
    if not href:
        return None
    return urljoin(base_url.rstrip("/") + "/", href)


def normalize_identity_url(url: str | None) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    filtered_query = [
        (key, value)
        for key, value in sorted(parse_qsl(parsed.query, keep_blank_values=True))
        if key and key not in TRACKING_QUERY_KEYS and not key.startswith("utm_")
    ]
    query = urlencode(filtered_query)
    normalized = parsed._replace(
        scheme=parsed.scheme.lower() or "https",
        netloc=parsed.netloc.lower(),
        query=query,
        fragment="",
    )
    return urlunparse(normalized)


def is_clickout_url(url: str | None) -> bool:
    return bool(url and "/clickout/" in urlparse(url).path)


def build_fingerprint(*values: str | None) -> str:
    basis = "||".join((value or "").strip().casefold() for value in values)
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()
