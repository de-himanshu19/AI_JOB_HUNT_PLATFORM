"""EnglishJobs.de pagination, safe detail resolution, and common-model conversion."""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from typing import Protocol

from app.config import Settings
from app.domain.enums import DescriptionCompleteness, JobSource
from app.domain.job import Job, JobDescription
from app.sources.base import (
    CollectedJob,
    CollectionError,
    CollectionRequest,
    CollectionResult,
    SourceRunStatus,
)
from app.sources.englishjobs.client import (
    EnglishJobsClientError,
    FetchedDocument,
)
from app.sources.englishjobs.models import RawEnglishJobsDetails, RawEnglishJobsRecord
from app.sources.englishjobs.parser import (
    parse_job_detail,
    parse_published_text,
    parse_search_page,
)
from app.sources.englishjobs.url_builder import (
    build_fingerprint,
    is_clickout_url,
    normalize_identity_url,
)


STATE_DISPLAY_NAMES = {
    "rheinland_pfalz": "Rheinland-Pfalz",
    "bayern": "Bayern",
    "nordrhein_westfalen": "Nordrhein-Westfalen",
    "berlin": "Berlin",
    "baden_wuerttemberg": "Baden-Württemberg",
    "hessen": "Hessen",
    "hamburg": "Hamburg",
    "niedersachsen": "Niedersachsen",
    "sachsen": "Sachsen",
    "sachsen_anhalt": "Sachsen-Anhalt",
    "saarland": "Saarland",
    "brandenburg": "Brandenburg",
    "schleswig_holstein": "Schleswig-Holstein",
    "bremen": "Bremen",
    "thueringen": "Thüringen",
    "mecklenburg_vorpommern": "Mecklenburg-Vorpommern",
}

STATE_URL_SLUGS = {
    "rheinland_pfalz": "rheinland-pfalz",
    "bayern": "bayern",
    "nordrhein_westfalen": "nordrhein-westfalen",
    "berlin": "berlin",
    "baden_wuerttemberg": "baden-wuerttemberg",
    "hessen": "hessen",
    "hamburg": "hamburg",
    "niedersachsen": "niedersachsen",
    "sachsen": "sachsen",
    "sachsen_anhalt": "sachsen-anhalt",
    "saarland": "saarland",
    "brandenburg": "brandenburg",
    "schleswig_holstein": "schleswig-holstein",
    "bremen": "bremen",
    "thueringen": "thueringen",
    "mecklenburg_vorpommern": "mecklenburg-vorpommern",
}


class EnglishJobsClientLike(Protocol):
    def search_state(self, state_slug: str, *, page: int) -> FetchedDocument: ...

    def search_query(
        self,
        query: str,
        *,
        location: str | None,
        page: int,
    ) -> FetchedDocument: ...

    def fetch_document(self, url: str, *, operation: str) -> FetchedDocument: ...


def _normalized(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(value.casefold().split())


class EnglishJobsAdapter:
    def __init__(self, settings: Settings, client: EnglishJobsClientLike):
        self.settings = settings
        self.client = client

    def collect(self, request: CollectionRequest) -> CollectionResult:
        result = CollectionResult()
        records: dict[str, RawEnglishJobsRecord] = {}

        for state in request.states:
            result.states_executed += 1
            state_slug = STATE_URL_SLUGS.get(state)
            if state_slug is None:
                result.errors.append(
                    CollectionError(
                        operation="state_config",
                        state=state,
                        message=f"Unknown EnglishJobs state key: {state}",
                        error_type="UnknownStateError",
                        retriable=False,
                    )
                )
                continue
            self._collect_scope(
                result,
                records,
                request=request,
                page_fetcher=lambda page, slug=state_slug: self.client.search_state(
                    slug, page=page
                ),
                search_query=None,
                search_location=None,
                search_state=state,
                state_display=STATE_DISPLAY_NAMES[state],
            )

        for query in request.queries:
            result.queries_executed += 1
            self._collect_scope(
                result,
                records,
                request=request,
                page_fetcher=lambda page, q=query: self.client.search_query(
                    q,
                    location=request.location,
                    page=page,
                ),
                search_query=query,
                search_location=request.location,
                search_state=None,
                state_display=None,
            )

        for record in records.values():
            details = self._fetch_details(record, result)
            result.jobs.append(self.to_job(record, details))

        if result.search_requests_succeeded == 0 and result.errors:
            result.status = SourceRunStatus.FAILED
        elif not result.jobs and result.errors:
            result.status = SourceRunStatus.FAILED
        elif result.errors:
            result.status = SourceRunStatus.COMPLETED_WITH_ERRORS
        else:
            result.status = SourceRunStatus.COMPLETED
        return result

    def to_job(
        self,
        record: RawEnglishJobsRecord,
        details: RawEnglishJobsDetails | None = None,
    ) -> CollectedJob:
        if details and details.description and len(details.description.strip()) >= 40:
            description_text = details.description
            completeness = DescriptionCompleteness.FULL
        elif record.description_snippet:
            description_text = record.description_snippet
            completeness = DescriptionCompleteness.SNIPPET
        else:
            description_text = None
            completeness = DescriptionCompleteness.MISSING

        canonical_url = (
            details.canonical_url
            if details and details.canonical_url
            else details.final_url if details and details.final_url
            else record.listing_url
            or record.clickout_url
        )
        source_url = record.listing_url or record.clickout_url
        job = Job(
            source=JobSource.ENGLISHJOBS,
            source_job_id=self._source_identity(record),
            source_url=source_url,
            canonical_url=canonical_url,
            title_raw=record.title,
            title_normalized=_normalized(record.title) or "untitled vacancy",
            company_raw=record.company,
            company_normalized=_normalized(record.company),
            location_raw=record.location_raw,
            city=record.city,
            region=record.state_display,
            country="Germany",
            language_detected=None,
            language_confidence=None,
            explicit_german_requirement=None,
            published_at=parse_published_text(record.published_text),
        )
        structured_data = {
            "search_query": record.search_query,
            "search_location": record.search_location,
            "search_state": record.search_state,
            "search_queries": list(record.discovered_queries),
            "search_states": list(record.discovered_states),
            "clickout_url": record.clickout_url,
            "listing_url": record.listing_url,
            "published_text": record.published_text,
            "page_number": record.page_number,
            "state_display": record.state_display,
            "retrieved_at": record.retrieved_at.isoformat(),
            "identity_basis": self._identity_basis(record),
        }
        if details:
            structured_data.update(details.structured_data)
            structured_data["resolved_final_url"] = details.final_url
        content_basis = description_text or (
            f"missing:{job.source_job_id}:{completeness.value}"
        )
        description = JobDescription(
            job_id=job.id,
            raw_text=description_text,
            normalized_text=(
                re.sub(r"\s+", " ", description_text).strip()
                if description_text
                else None
            ),
            completeness=completeness,
            content_hash=hashlib.sha256(content_basis.encode("utf-8")).hexdigest(),
            structured_data=structured_data,
        )
        return CollectedJob(job=job, description=description)

    def _collect_scope(
        self,
        result: CollectionResult,
        records: dict[str, RawEnglishJobsRecord],
        *,
        request: CollectionRequest,
        page_fetcher,
        search_query: str | None,
        search_location: str | None,
        search_state: str | None,
        state_display: str | None,
    ) -> None:
        previous_fingerprint: tuple[str, ...] | None = None
        for page_number in range(1, request.max_pages + 1):
            result.pages_requested += 1
            try:
                document = page_fetcher(page_number)
            except EnglishJobsClientError as error:
                result.search_requests_failed += 1
                result.errors.append(
                    self._error(
                        error,
                        operation="search",
                        query=search_query,
                        state=search_state,
                        page=page_number,
                    )
                )
                continue
            result.search_requests_succeeded += 1
            page = parse_search_page(
                document.text,
                base_url=self.settings.englishjobs_base_url,
                page_number=page_number,
                search_query=search_query,
                search_location=search_location,
                search_state=search_state,
                state_display=state_display,
            )
            result.jobs_parsed += len(page.records)
            result.invalid_cards += page.invalid_cards
            for record_error in page.record_errors:
                result.errors.append(
                    CollectionError(
                        operation="search_parse",
                        query=search_query,
                        state=search_state,
                        page=page_number,
                        message=record_error,
                        error_type="record_validation",
                        retriable=False,
                    )
                )

            if not page.records:
                break
            if previous_fingerprint == page.page_fingerprint:
                result.repeated_pages += 1
                break
            previous_fingerprint = page.page_fingerprint

            for record in page.records:
                key = self._source_identity(record)
                existing = records.get(key)
                if existing:
                    records[key] = self._merge_record(existing, record)
                else:
                    records[key] = record

            if page.has_next_page is False:
                break
            if (
                page.has_next_page is None
                and page.total_jobs is not None
                and page_number * request.page_size >= page.total_jobs
            ):
                break

    def _fetch_details(
        self,
        record: RawEnglishJobsRecord,
        result: CollectionResult,
    ) -> RawEnglishJobsDetails | None:
        if record.listing_url and not is_clickout_url(record.listing_url):
            try:
                document = self.client.fetch_document(
                    record.listing_url,
                    operation="detail",
                )
            except EnglishJobsClientError as error:
                result.detail_requests_failed += 1
                result.errors.append(
                    self._error(
                        error,
                        operation="detail",
                        source_job_id=self._source_identity(record),
                    )
                )
            else:
                result.detail_requests_succeeded += 1
                return parse_job_detail(
                    document.text,
                    source_url=record.listing_url,
                    final_url=document.final_url,
                )
        if record.clickout_url:
            try:
                document = self.client.fetch_document(
                    record.clickout_url,
                    operation="clickout",
                )
            except EnglishJobsClientError as error:
                result.detail_requests_failed += 1
                result.errors.append(
                    self._error(
                        error,
                        operation="clickout",
                        source_job_id=self._source_identity(record),
                    )
                )
            else:
                result.detail_requests_succeeded += 1
                return RawEnglishJobsDetails(
                    description=None,
                    canonical_url=document.final_url,
                    final_url=document.final_url,
                    structured_data={"clickout_resolved": True},
                )
        return None

    @staticmethod
    def _merge_record(
        existing: RawEnglishJobsRecord,
        new: RawEnglishJobsRecord,
    ) -> RawEnglishJobsRecord:
        return existing.model_copy(
            update={
                "search_query": existing.search_query or new.search_query,
                "search_location": existing.search_location or new.search_location,
                "search_state": existing.search_state or new.search_state,
                "discovered_queries": tuple(
                    dict.fromkeys(
                        (*existing.discovered_queries, *new.discovered_queries)
                    )
                ),
                "discovered_states": tuple(
                    dict.fromkeys(
                        (*existing.discovered_states, *new.discovered_states)
                    )
                ),
                "description_snippet": (
                    existing.description_snippet
                    if existing.description_snippet
                    and len(existing.description_snippet) >= len(new.description_snippet or "")
                    else new.description_snippet
                ),
                "listing_url": existing.listing_url or new.listing_url,
                "clickout_url": existing.clickout_url or new.clickout_url,
                "published_text": existing.published_text or new.published_text,
                "location_raw": existing.location_raw or new.location_raw,
                "state_display": existing.state_display or new.state_display,
                "company": existing.company or new.company,
            }
        )

    @staticmethod
    def _identity_basis(record: RawEnglishJobsRecord) -> str:
        if record.listing_id:
            return f"listing_id:{record.listing_id}"
        normalized_listing = normalize_identity_url(record.listing_url)
        if normalized_listing:
            return f"listing_url:{normalized_listing}"
        normalized_clickout = normalize_identity_url(record.clickout_url)
        if normalized_clickout:
            return f"clickout_url:{normalized_clickout}"
        return "fingerprint:" + build_fingerprint(
            record.title,
            record.company,
            record.location_raw,
            record.published_text,
        )

    @classmethod
    def _source_identity(cls, record: RawEnglishJobsRecord) -> str:
        return cls._identity_basis(record)

    @staticmethod
    def _error(
        error: Exception,
        *,
        operation: str,
        query: str | None = None,
        state: str | None = None,
        page: int | None = None,
        source_job_id: str | None = None,
    ) -> CollectionError:
        return CollectionError(
            operation=operation,
            query=query,
            state=state,
            page=page,
            source_job_id=source_job_id,
            message=str(error),
            error_type=type(error).__name__,
            retriable=bool(getattr(error, "retriable", False)),
        )
