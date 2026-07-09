"""Arbeitsagentur pagination, detail enrichment, and common-model conversion."""

from __future__ import annotations

import hashlib
import math
import re
from datetime import UTC, datetime
from typing import Protocol

from app.config import Settings
from app.domain.enums import DescriptionCompleteness, JobSource
from app.domain.job import Job, JobDescription
from app.sources.arbeitsagentur.client import (
    ArbeitsagenturClientError,
    encode_ref_number,
)
from app.sources.arbeitsagentur.models import RawJobDetails, RawJobSummary
from app.sources.arbeitsagentur.parser import (
    SourcePayloadError,
    detect_language,
    extract_language_signals,
    parse_job_details,
    parse_search_page,
)
from app.sources.base import (
    CollectedJob,
    CollectionError,
    CollectionRequest,
    CollectionResult,
    SourceRunStatus,
)


class ArbeitsagenturClientLike(Protocol):
    def search(
        self,
        query: str,
        *,
        location: str,
        page: int,
        page_size: int,
        published_within_days: int,
    ) -> dict: ...

    def fetch_details(self, source_job_id: str, url: str | None = None) -> dict: ...


def _normalized(value: str | None) -> str | None:
    if not value:
        return None
    return " ".join(value.casefold().split())


class ArbeitsagenturAdapter:
    def __init__(self, settings: Settings, client: ArbeitsagenturClientLike):
        self.settings = settings
        self.client = client

    def collect(self, request: CollectionRequest) -> CollectionResult:
        result = CollectionResult()
        summaries: dict[str, RawJobSummary] = {}

        for query in request.queries:
            result.queries_executed += 1
            previous_page_ids: tuple[str, ...] | None = None
            for page_number in range(1, request.max_pages + 1):
                result.pages_requested += 1
                try:
                    payload = self.client.search(
                        query,
                        location=request.location,
                        page=page_number,
                        page_size=request.page_size,
                        published_within_days=request.published_within_days,
                    )
                except ArbeitsagenturClientError as error:
                    result.search_requests_failed += 1
                    result.errors.append(
                        self._error(
                            error,
                            operation="search",
                            query=query,
                            page=page_number,
                        )
                    )
                    continue
                result.search_requests_succeeded += 1
                try:
                    page = parse_search_page(
                        payload,
                        search_term=query,
                        detail_base_url=self.settings.arbeitsagentur_detail_url,
                    )
                except (SourcePayloadError, ValueError) as error:
                    result.errors.append(
                        self._error(
                            error,
                            operation="search_parse",
                            query=query,
                            page=page_number,
                        )
                    )
                    continue

                for record_error in page.record_errors:
                    result.errors.append(
                        CollectionError(
                            operation="search_parse",
                            query=query,
                            page=page_number,
                            message=record_error,
                            error_type="record_validation",
                            retriable=False,
                        )
                    )

                if not page.jobs:
                    break
                page_ids = tuple(job.source_job_id for job in page.jobs)
                if previous_page_ids == page_ids:
                    break
                previous_page_ids = page_ids

                for summary in page.jobs:
                    existing = summaries.get(summary.source_job_id)
                    if existing:
                        terms = tuple(
                            dict.fromkeys((*existing.search_terms, *summary.search_terms))
                        )
                        summaries[summary.source_job_id] = existing.model_copy(
                            update={"search_terms": terms}
                        )
                    else:
                        summaries[summary.source_job_id] = summary

                if page.total_results is not None:
                    total_pages = max(1, math.ceil(page.total_results / request.page_size))
                    if page_number >= total_pages:
                        break

        for summary in summaries.values():
            details: RawJobDetails | None = None
            try:
                result.detail_requests_attempted += 1
                detail_payload = self.client.fetch_details(
                    summary.source_job_id, summary.source_detail_url
                )
            except ArbeitsagenturClientError as error:
                result.detail_requests_failed += 1
                result.errors.append(
                    self._error(
                        error,
                        operation="detail",
                        source_job_id=summary.source_job_id,
                    )
                )
            else:
                result.detail_requests_succeeded += 1
                try:
                    details = parse_job_details(
                        detail_payload,
                        source_job_id=summary.source_job_id,
                        source_url=summary.source_detail_url,
                    )
                except (SourcePayloadError, ValueError) as error:
                    result.parsing_errors += 1
                    result.errors.append(
                        self._error(
                            error,
                            operation="detail_parse",
                            source_job_id=summary.source_job_id,
                        )
                    )
            result.jobs.append(self.to_job(summary, details))

        if result.search_requests_succeeded == 0:
            result.status = SourceRunStatus.FAILED
        elif not result.jobs and result.errors:
            result.status = SourceRunStatus.FAILED
        elif result.errors:
            result.status = SourceRunStatus.COMPLETED_WITH_ERRORS
        else:
            result.status = SourceRunStatus.COMPLETED
        return result

    def fetch_details(
        self, source_job_id: str, url: str | None = None
    ) -> RawJobDetails:
        payload = self.client.fetch_details(source_job_id, url)
        source_url = url or (
            self.settings.arbeitsagentur_detail_url.rstrip("/")
            + "/"
            + encode_ref_number(source_job_id)
        )
        return parse_job_details(
            payload, source_job_id=source_job_id, source_url=source_url
        )

    def to_job(
        self, raw_summary: RawJobSummary, raw_details: RawJobDetails | None = None
    ) -> CollectedJob:
        detail_text = raw_details.description if raw_details else None
        if detail_text and len(detail_text.strip()) >= 40:
            description_text = detail_text
            completeness = DescriptionCompleteness.FULL
        elif raw_summary.description_snippet:
            description_text = raw_summary.description_snippet
            completeness = DescriptionCompleteness.SNIPPET
        else:
            description_text = None
            completeness = DescriptionCompleteness.MISSING

        if raw_details:
            signals = raw_details.language_signals
            first_location = raw_details.work_locations[0] if raw_details.work_locations else {}
        else:
            signals = extract_language_signals(description_text or "")
            first_location = {}
        detected_language = signals.detected_language
        language_confidence = signals.language_confidence
        if description_text and not detected_language:
            detected_language, language_confidence = detect_language(description_text)

        publication = (
            datetime.combine(raw_summary.publication_date, datetime.min.time(), UTC)
            if raw_summary.publication_date else None
        )
        expiry = (
            datetime.combine(raw_details.application_deadline, datetime.min.time(), UTC)
            if raw_details and raw_details.application_deadline else None
        )
        job = Job(
            source=JobSource.ARBEITSAGENTUR,
            source_job_id=raw_summary.source_job_id,
            source_url=raw_summary.source_detail_url,
            canonical_url=(
                raw_details.original_application_url
                if raw_details and raw_details.original_application_url
                else raw_summary.external_url or raw_summary.source_detail_url
            ),
            title_raw=raw_summary.title,
            title_normalized=_normalized(raw_summary.title) or "untitled vacancy",
            company_raw=raw_summary.company,
            company_normalized=_normalized(raw_summary.company),
            location_raw=raw_summary.location_raw,
            city=first_location.get("city") or raw_summary.city,
            region=first_location.get("region") or raw_summary.region,
            country=first_location.get("country") or raw_summary.country,
            language_detected=detected_language,
            language_confidence=language_confidence,
            explicit_german_requirement=signals.german_requirement,
            published_at=publication,
            expires_at=expiry,
            employment_type=(
                raw_details.employment_type if raw_details else None
            ),
        )
        structured_data = {
            "profession": raw_summary.profession,
            "search_term": raw_summary.search_term,
            "search_terms": list(raw_summary.search_terms),
            "external_url": raw_summary.external_url,
        }
        if raw_details:
            structured_data.update(raw_details.structured_data)
        content_basis = description_text or (
            f"missing:{raw_summary.source_job_id}:{completeness.value}"
        )
        description = JobDescription(
            job_id=job.id,
            raw_text=description_text,
            normalized_text=(
                re.sub(r"\s+", " ", description_text).strip()
                if description_text else None
            ),
            completeness=completeness,
            content_hash=hashlib.sha256(content_basis.encode("utf-8")).hexdigest(),
            structured_data=structured_data,
        )
        return CollectedJob(job=job, description=description)

    @staticmethod
    def _error(
        error: Exception,
        *,
        operation: str,
        query: str | None = None,
        page: int | None = None,
        source_job_id: str | None = None,
    ) -> CollectionError:
        return CollectionError(
            operation=operation,
            query=query,
            page=page,
            source_job_id=source_job_id,
            message=str(error),
            error_type=type(error).__name__,
            retriable=bool(getattr(error, "retriable", False)),
        )
