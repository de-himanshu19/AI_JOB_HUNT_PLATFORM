"""HTML parsers for EnglishJobs.de search and detail pages."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.sources.englishjobs.models import (
    ParsedEnglishJobsPage,
    RawEnglishJobsDetails,
    RawEnglishJobsRecord,
)
from app.sources.englishjobs.url_builder import absolutize_url, build_fingerprint


class SourcePayloadError(ValueError):
    pass


MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}
FULL_DESCRIPTION_MIN_CHARS = 700
FULL_DESCRIPTION_MIN_KEYWORD_HITS = 2
JOB_BODY_KEYWORDS = {
    "responsibilities",
    "requirements",
    "qualifications",
    "benefits",
    "role",
    "tasks",
    "profile",
    "skills",
    "experience",
    "candidate",
    "team",
    "about the job",
    "what you will do",
    "what we offer",
    "your profile",
    "your tasks",
}
NON_DESCRIPTION_PATTERNS = (
    "apply now",
    "view job",
    "external application",
    "redirect",
    "cookie",
    "privacy policy",
)


def get_text_or_none(element) -> str | None:
    if element is None:
        return None
    text = element.get_text(" ", strip=True)
    return text or None


def extract_total_jobs_count(html: str) -> int | None:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one("h1")
    if heading is None:
        return None
    match = re.search(r"\d+", heading.get_text(" ", strip=True))
    return int(match.group()) if match else None


def parse_published_text(text: str | None) -> datetime | None:
    if not text:
        return None
    normalized = " ".join(text.replace(",", " ").split())
    match = re.search(r"([A-Za-z]+)\s+(\d{1,2})", normalized)
    if not match:
        return None
    month = MONTHS.get(match.group(1).casefold())
    if not month:
        return None
    day = int(match.group(2))
    today = datetime.now(UTC).date()
    year = today.year
    parsed = date(year, month, day)
    if parsed > today:
        parsed = date(year - 1, month, day)
    return datetime(parsed.year, parsed.month, parsed.day, tzinfo=UTC)


def parse_search_page(
    html: str,
    *,
    base_url: str,
    page_number: int,
    search_query: str | None = None,
    search_location: str | None = None,
    search_state: str | None = None,
    state_display: str | None = None,
) -> ParsedEnglishJobsPage:
    soup = BeautifulSoup(html, "html.parser")
    cards = soup.select("div.job.js-job")
    records: list[RawEnglishJobsRecord] = []
    errors: list[str] = []
    invalid_cards = 0

    for index, card in enumerate(cards, start=1):
        try:
            records.append(
                _parse_card(
                    card,
                    base_url=base_url,
                    page_number=page_number,
                    search_query=search_query,
                    search_location=search_location,
                    search_state=search_state,
                    state_display=state_display,
                )
            )
        except SourcePayloadError as error:
            invalid_cards += 1
            errors.append(f"card {index}: {error}")

    total_jobs = extract_total_jobs_count(html)
    if not cards and total_jobs not in (None, 0):
        errors.append("No job cards matched the expected selectors")
    next_link = soup.select_one("a[rel='next'], a.next, li.next a, a.pagination-next")
    page_fingerprint = tuple(
        sorted(
            record.listing_id
            or record.listing_url
            or record.clickout_url
            or build_fingerprint(
                record.title,
                record.company,
                record.location_raw,
                record.published_text,
            )
            for record in records
        )
    )
    return ParsedEnglishJobsPage(
        records=records,
        total_jobs=total_jobs,
        has_next_page=True if next_link is not None else None,
        invalid_cards=invalid_cards,
        record_errors=errors,
        page_fingerprint=page_fingerprint,
    )


def parse_job_detail(
    html: str,
    *,
    source_url: str,
    final_url: str | None = None,
) -> RawEnglishJobsDetails:
    soup = BeautifulSoup(html, "html.parser")
    canonical = soup.select_one("link[rel='canonical']")
    canonical_url = (
        canonical.get("href").strip()
        if canonical and canonical.get("href")
        else final_url or source_url
    )
    _remove_non_body_nodes(soup)
    title = get_text_or_none(
        soup.select_one("h1")
        or soup.select_one("[data-testid='job-title']")
        or soup.select_one(".job-title")
    )
    company = get_text_or_none(
        soup.select_one("[data-testid='company-name']")
        or soup.select_one(".company")
        or soup.select_one(".job-company")
    )
    location_raw = get_text_or_none(
        soup.select_one("[data-testid='job-location']")
        or soup.select_one(".location")
        or soup.select_one(".job-location")
    )
    best_text = None
    for selector in (
        "div.job-description",
        "section.job-description",
        "article.job-description",
        "[data-testid='job-description']",
        ".job-detail .description",
        ".job-posting",
        ".job__description",
        ".job-content",
        "main article",
        "article",
        "main",
    ):
        node = soup.select_one(selector)
        text = _clean_description_text(get_text_or_none(node))
        if text and (best_text is None or len(text) > len(best_text)):
            best_text = text
        if is_full_description_text(text, title=title, company=company, location=location_raw):
            best_text = text
            break
    description = (
        best_text
        if is_full_description_text(
            best_text,
            title=title,
            company=company,
            location=location_raw,
        )
        else None
    )
    keyword_hits = _job_keyword_hits(best_text)
    return RawEnglishJobsDetails(
        title=title,
        company=company,
        location_raw=location_raw,
        description=description,
        canonical_url=canonical_url,
        final_url=final_url or source_url,
        structured_data={
            "detail_description_length": len(best_text or ""),
            "detail_keyword_hits": keyword_hits,
            "detail_description_quality": "full" if description else "not_full",
            "detail_external_final_url": _is_external(source_url, final_url),
        },
    )


def is_full_description_text(
    text: str | None,
    *,
    title: str | None = None,
    company: str | None = None,
    location: str | None = None,
) -> bool:
    if not text:
        return False
    cleaned = _clean_description_text(text)
    if not cleaned or len(cleaned) < FULL_DESCRIPTION_MIN_CHARS:
        return False
    lowered = cleaned.casefold()
    keyword_hits = _job_keyword_hits(cleaned)
    if (
        any(pattern in lowered for pattern in NON_DESCRIPTION_PATTERNS)
        and keyword_hits < FULL_DESCRIPTION_MIN_KEYWORD_HITS
    ):
        return False
    metadata = " ".join(
        value for value in (title, company, location) if value
    ).casefold()
    if metadata and _without_metadata_words(lowered, metadata) < FULL_DESCRIPTION_MIN_CHARS:
        return False
    if _repetition_ratio(cleaned) > 0.45:
        return False
    return keyword_hits >= FULL_DESCRIPTION_MIN_KEYWORD_HITS


def _parse_card(
    card,
    *,
    base_url: str,
    page_number: int,
    search_query: str | None,
    search_location: str | None,
    search_state: str | None,
    state_display: str | None,
) -> RawEnglishJobsRecord:
    title_link = (
        card.select_one("a.js-joblink[href]")
        or card.select_one("a.joblink[href]")
        or card.select_one("h2 a[href]")
        or card.select_one("a[href]")
    )
    clickout_link = card.select_one("a[href*='/clickout/']")

    title = get_text_or_none(title_link)
    if not title:
        raise SourcePayloadError("missing title link")

    title_href = title_link.get("href") if title_link else None
    listing_url = absolutize_url(base_url, title_href)
    if listing_url and "/clickout/" in listing_url and clickout_link is None:
        clickout_link = title_link
        listing_url = None
    if listing_url is None:
        listing_fallback = next(
            (
                link.get("href")
                for link in card.select("a[href]")
                if "/clickout/" not in (link.get("href") or "")
            ),
            None,
        )
        listing_url = absolutize_url(base_url, listing_fallback)
    clickout_url = absolutize_url(
        base_url, clickout_link.get("href") if clickout_link else None
    )

    listing_id = (
        card.get("data-job-id")
        or card.get("data-id")
        or _extract_listing_id(listing_url)
        or _extract_listing_id(clickout_url)
    )

    title_parts = [
        part.strip()
        for part in title_link.get_text(" | ", strip=True).split(" | ")
        if part.strip()
    ]
    text_parts = [
        part.strip()
        for part in card.get_text(" | ", strip=True).split(" | ")
        if part.strip()
    ]
    remaining = text_parts[len(title_parts):]
    company = remaining[0] if len(remaining) > 0 else None
    location_raw = remaining[1] if len(remaining) > 1 else None
    published_text = remaining[2] if len(remaining) > 2 else None
    snippet_parts = [
        part
        for part in remaining[3:]
        if part.casefold() not in {"report problem", "report probem"}
    ]
    description_snippet = " ".join(snippet_parts) if snippet_parts else None
    city = _extract_city(location_raw)
    if not location_raw and state_display:
        location_raw = state_display

    return RawEnglishJobsRecord(
        listing_id=listing_id,
        title=title,
        company=company,
        location_raw=location_raw,
        city=city,
        state_key=search_state,
        state_display=state_display,
        published_text=published_text,
        listing_url=listing_url,
        clickout_url=clickout_url,
        description_snippet=description_snippet,
        search_query=search_query,
        search_location=search_location,
        search_state=search_state,
        discovered_queries=((search_query,) if search_query else ()),
        discovered_states=((search_state,) if search_state else ()),
        page_number=page_number,
    )


def _extract_listing_id(url: str | None) -> str | None:
    if not url:
        return None
    match = re.search(r"/(?:job|jobs|clickout)/([^/?#]+)", url)
    return match.group(1) if match else None


def _extract_city(location_raw: str | None) -> str | None:
    if not location_raw:
        return None
    first = re.split(r",|/|\|", location_raw, maxsplit=1)[0].strip()
    return first or None


def _clean_description_text(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip()
    return cleaned or None


def _remove_non_body_nodes(soup: BeautifulSoup) -> None:
    for node in soup.select(
        "script, style, noscript, nav, footer, header, aside, form, "
        ".cookie, .cookies, .cookie-banner, .footer, .navbar, .navigation"
    ):
        node.decompose()


def _job_keyword_hits(text: str | None) -> int:
    if not text:
        return 0
    lowered = text.casefold()
    return sum(1 for keyword in JOB_BODY_KEYWORDS if keyword in lowered)


def _repetition_ratio(text: str) -> float:
    words = re.findall(r"[A-Za-z]{3,}", text.casefold())
    if not words:
        return 1.0
    unique = len(set(words))
    return 1 - (unique / len(words))


def _without_metadata_words(text: str, metadata: str) -> int:
    metadata_words = {
        word for word in re.findall(r"[A-Za-z0-9+.-]{3,}", metadata)
    }
    body_words = [
        word for word in re.findall(r"[A-Za-z0-9+.-]{3,}", text)
        if word not in metadata_words
    ]
    return len(" ".join(body_words))


def _is_external(source_url: str, final_url: str | None) -> bool:
    if not final_url:
        return False
    source_host = urlparse(source_url).netloc.casefold()
    final_host = urlparse(final_url).netloc.casefold()
    return bool(source_host and final_host and source_host != final_host)
