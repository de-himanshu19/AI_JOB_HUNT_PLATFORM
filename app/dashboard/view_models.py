"""Typed read models used by dashboard controllers and Streamlit pages."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Generic, TypeVar


T = TypeVar("T")


@dataclass(frozen=True)
class PageResult(Generic[T]):
    items: tuple[T, ...]
    total: int
    page: int
    page_size: int

    @property
    def pages(self) -> int:
        return max(1, (self.total + self.page_size - 1) // self.page_size)


@dataclass(frozen=True)
class ProfileSummary:
    id: str
    profile_key: str
    version: int
    display_name: str
    active: bool
    content_hash: str


@dataclass(frozen=True)
class JobFilters:
    search: str = ""
    location_search: str = ""
    source: str | None = None
    completeness: str | None = None
    language: str | None = None
    application_status: str | None = None
    authority: str | None = None
    date_from: str | None = None
    include_prefilter_only: bool = True
    fit_min: float | None = None
    fit_max: float | None = None
    rank_min: float | None = None
    rank_max: float | None = None
    logical_only: bool = True
    active_only: bool = True
    sort_by: str = "posted_or_first_seen"
    descending: bool = True
    page: int = 1
    page_size: int = 25


@dataclass(frozen=True)
class JobListItem:
    job_id: str
    logical_id: str
    cluster_id: str | None
    representative: bool
    title: str
    company: str | None
    location: str | None
    source: str
    completeness: str
    language: str | None
    german_requirement: str | None
    authority: str | None
    fit_score: float | None
    rank_score: float | None
    application_statuses: tuple[str, ...] = ()
    published_at: str | None = None
    first_seen_at: str | None = None
    last_seen_at: str | None = None
    created_at: str | None = None


@dataclass(frozen=True)
class OverviewView:
    active_source_jobs: int
    logical_vacancies: int
    authoritative_analyses: int
    ranked_vacancies: int
    preliminary_analyses: int
    preliminary_rankings: int
    pending_duplicate_reviews: int
    application_counts: dict[str, int] = field(default_factory=dict)
    recent_runs: tuple[dict[str, object], ...] = ()
    recent_notification_batches: tuple[dict[str, object], ...] = ()
    recent_cv_artifacts: tuple[dict[str, object], ...] = ()


@dataclass(frozen=True)
class JobDetailView:
    job: dict[str, object]
    description: dict[str, object] | None
    cluster: dict[str, object] | None
    cluster_members: tuple[dict[str, object], ...]
    analysis: dict[str, object] | None
    ranking: dict[str, object] | None
    applications: tuple[dict[str, object], ...]
    application_history: tuple[dict[str, object], ...]
    notifications: tuple[dict[str, object], ...]
    cv_artifacts: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class DuplicateReviewView:
    candidate: dict[str, object]
    left_job: dict[str, object]
    right_job: dict[str, object]
