"""User-facing dashboard presentation helpers."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import re
from typing import Any


_POSTCODE_PREFIX = re.compile(r"^\d{4,6}\s+(.+)$")


def parse_city(location: str | None) -> str:
    if not location:
        return ""
    raw = location.strip()
    if not raw:
        return ""
    first = raw.split(",", 1)[0].strip()
    postcode_match = _POSTCODE_PREFIX.match(first)
    if postcode_match:
        candidate = postcode_match.group(1).strip()
        return candidate or raw
    return first or raw


def match_type_label(authority: str | None) -> str:
    if authority == "authoritative":
        return "Full analysis"
    if authority == "prefilter_only":
        return "Quick match only"
    return "Not analyzed"


def fit_score_label(authority: str | None, fit_score: float | None) -> str:
    if authority == "prefilter_only" or fit_score is None:
        return "Quick match only"
    return f"{fit_score:.2f}"


def posted_or_first_seen(
    published_at: str | None,
    first_seen_at: str | None,
    created_at: str | None = None,
) -> tuple[str, str]:
    value = published_at or first_seen_at or created_at
    if not value:
        return ("Unknown", "Unknown")
    if published_at:
        return (_display_date(published_at), "Posted")
    if first_seen_at:
        return (_display_date(first_seen_at), "First seen")
    return (_display_date(created_at or value), "Created")


def posted_or_first_seen_display(
    published_at: str | None,
    first_seen_at: str | None,
    created_at: str | None = None,
) -> str:
    value, source = posted_or_first_seen(published_at, first_seen_at, created_at)
    if source == "Unknown":
        return value
    return f"{value} ({source})"


def default_follow_up_date(today: date | None = None) -> date:
    base = today or datetime.now(UTC).date()
    return base + timedelta(days=7)


def date_range_start(range_label: str, *, today: date | None = None) -> str | None:
    anchor = today or datetime.now(UTC).date()
    mapping = {
        "Today": 0,
        "Last 3 days": 2,
        "Last 7 days": 6,
        "All": None,
    }
    days = mapping.get(range_label)
    if days is None:
        return None
    return (anchor - timedelta(days=days)).isoformat()


def _display_date(value: str) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return value
    return parsed.date().isoformat()


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    candidate = value.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(candidate)
    except ValueError:
        return None


def job_row(item: Any) -> dict[str, object]:
    title = getattr(item, "title", "") or ""
    company = getattr(item, "company", None) or ""
    location = getattr(item, "location", None)
    authority = getattr(item, "authority", None)
    return {
        "Select": False,
        "Posted / First Seen": posted_or_first_seen_display(
            getattr(item, "published_at", None),
            getattr(item, "first_seen_at", None),
            getattr(item, "created_at", None),
        ),
        "Title": title,
        "Company": company,
        "City": parse_city(location),
        "Source": getattr(item, "source", ""),
        "Match Type": match_type_label(authority),
        "Rank Score": getattr(item, "rank_score", None),
        "Fit Score": fit_score_label(authority, getattr(item, "fit_score", None)),
        "Application Status": ", ".join(getattr(item, "application_statuses", ()) or ()),
    }


def tray_row(item: dict[str, object]) -> dict[str, object]:
    authority = item.get("authority")
    return {
        "Title": item.get("title_raw") or "",
        "Company": item.get("company_raw") or "",
        "City": parse_city(item.get("location_raw")),
        "Source": item.get("source") or "",
        "Match Type": match_type_label(str(authority) if authority else None),
        "Rank Score": item.get("rank_score"),
        "Fit Score": fit_score_label(str(authority) if authority else None, item.get("fit_score")),
        "Status": item.get("current_status") or item.get("status") or "",
        "Follow-up Date": item.get("follow_up_date") or "",
    }
