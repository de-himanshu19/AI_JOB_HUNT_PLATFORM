"""Deterministic, versioned normalization without altering source values."""

from __future__ import annotations

import html
import json
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


NORMALIZATION_VERSION = "m4-normalization-v1"
TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "referrer",
    "source",
}
LEGAL_SUFFIXES = {
    "ag",
    "eg",
    "gbr",
    "gmbh",
    "kg",
    "kgaa",
    "ltd",
    "se",
    "ug",
}
GERMAN_REGIONS = {
    "bw": "baden-wuerttemberg",
    "baden wurttemberg": "baden-wuerttemberg",
    "baden wuerttemberg": "baden-wuerttemberg",
    "bavaria": "bayern",
    "by": "bayern",
    "nrw": "nordrhein-westfalen",
    "north rhine westphalia": "nordrhein-westfalen",
}
LOCATION_ALIASES = {
    "cologne": "koeln",
    "koln": "koeln",
    "munich": "muenchen",
    "nuremberg": "nuernberg",
}
REMOTE_TOKENS = {"remote", "homeoffice", "home office", "work from home"}


def _ascii_fold(value: str) -> str:
    value = value.replace("ß", "ss").replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
    return "".join(
        character
        for character in unicodedata.normalize("NFKD", value)
        if not unicodedata.combining(character)
    )


def normalize_text(value: str | None) -> str | None:
    if value is None:
        return None
    normalized = unicodedata.normalize("NFKC", html.unescape(value)).casefold()
    normalized = _ascii_fold(normalized)
    normalized = re.sub(r"[^a-z0-9]+", " ", normalized)
    normalized = " ".join(normalized.split())
    return normalized or None


def normalize_title(value: str | None) -> str | None:
    normalized = normalize_text(value)
    if not normalized:
        return None
    tokens = normalized.split()
    gender_markers = {"m", "w", "d", "f", "x", "gn", "div"}
    while tokens and tokens[-1] in gender_markers:
        tokens.pop()
    return " ".join(tokens) or None


@dataclass(frozen=True)
class CompanyAliases:
    aliases: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_json(cls, path: Path | None) -> "CompanyAliases":
        if path is None:
            return cls()
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or not all(
            isinstance(key, str) and isinstance(value, str)
            for key, value in payload.items()
        ):
            raise ValueError("Company alias file must be a JSON object of string pairs")
        return cls(
            {
                normalize_text(key) or "": normalize_text(value) or ""
                for key, value in payload.items()
            }
        )

    def canonical(self, value: str | None) -> str | None:
        normalized = normalize_text(value)
        if not normalized:
            return None
        tokens = normalized.split()
        while tokens and tokens[-1] in LEGAL_SUFFIXES:
            tokens.pop()
        without_suffix = " ".join(tokens) or normalized
        return self.aliases.get(normalized, self.aliases.get(without_suffix, without_suffix))


@dataclass(frozen=True)
class NormalizedLocation:
    city: str | None
    region: str | None
    country: str | None
    remote_mode: str | None


def normalize_location(
    city: str | None,
    region: str | None = None,
    country: str | None = None,
    *,
    raw: str | None = None,
) -> NormalizedLocation:
    normalized_city = normalize_text(city)
    if normalized_city:
        normalized_city = LOCATION_ALIASES.get(normalized_city, normalized_city)
    normalized_region = normalize_text(region)
    if normalized_region:
        normalized_region = GERMAN_REGIONS.get(normalized_region, normalized_region)
    normalized_country = normalize_text(country)
    if normalized_country in {"de", "deutschland", "federal republic of germany"}:
        normalized_country = "germany"
    location_text = normalize_text(" ".join(filter(None, (raw, city, region)))) or ""
    remote_mode = "remote" if any(token in location_text for token in REMOTE_TOKENS) else None
    return NormalizedLocation(normalized_city, normalized_region, normalized_country, remote_mode)


class _HTMLTextParser:
    """Small safe HTML-to-text helper; scripts and styles are removed first."""

    @staticmethod
    def convert(value: str | None) -> str | None:
        if not value:
            return None
        cleaned = re.sub(
            r"<(script|style)\b[^>]*>.*?</\1>", " ", value, flags=re.IGNORECASE | re.DOTALL
        )
        cleaned = re.sub(r"<[^>]+>", " ", cleaned)
        return " ".join(html.unescape(cleaned).split()) or None


def normalize_description(value: str | None) -> str | None:
    return normalize_text(_HTMLTextParser.convert(value))


def normalize_url(value: str | None) -> str | None:
    if not value or not value.strip():
        return None
    parsed = urlsplit(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    host = (parsed.hostname or "").casefold()
    if not host:
        return None
    port = parsed.port
    netloc = host if port is None else f"{host}:{port}"
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    if path != "/":
        path = path.rstrip("/")
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith("utm_")
        and key.casefold() not in TRACKING_QUERY_KEYS
    ]
    query.sort()
    return urlunsplit((parsed.scheme.casefold(), netloc, path, urlencode(query), ""))
