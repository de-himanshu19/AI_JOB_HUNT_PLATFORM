from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from app.domain.enums import JobSource
from app.domain.job import Job
from app.services.deduplication import DuplicateMatcher
from app.services.normalization import CompanyAliases, normalize_description, normalize_location, normalize_title, normalize_url


def _job(payload: dict) -> Job:
    location = normalize_location(payload.get("city"), country="Germany")
    published = payload.get("published")
    return Job(
        source=JobSource(payload["source"]),
        source_job_id=payload["source_job_id"],
        source_url=payload.get("url"),
        canonical_url=normalize_url(payload.get("url")),
        title_raw=payload["title"],
        title_normalized=normalize_title(payload["title"]),
        company_raw=payload.get("company"),
        company_normalized=CompanyAliases().canonical(payload.get("company")),
        location_raw=payload.get("city"),
        city=location.city,
        country=location.country,
        published_at=(
            datetime.fromisoformat(published).replace(tzinfo=UTC) if published else None
        ),
    )


def test_duplicate_gold_dataset_meets_precision_and_recall_targets() -> None:
    fixture = Path(__file__).parents[1] / "fixtures" / "duplicates" / "gold_pairs.json"
    pairs = json.loads(fixture.read_text(encoding="utf-8"))
    matcher = DuplicateMatcher()
    true_positive = false_positive = false_negative = 0

    for pair in pairs:
        left = _job(pair["left"])
        right = _job(pair["right"])
        decision = matcher.compare(
            left,
            right,
            left_description=normalize_description(pair["left"].get("description")),
            right_description=normalize_description(pair["right"].get("description")),
        )
        expected_match = pair["expected"] == "match"
        true_positive += int(decision.should_cluster and expected_match)
        false_positive += int(decision.should_cluster and not expected_match)
        false_negative += int(not decision.should_cluster and expected_match)
        if pair["expected"] == "review":
            assert decision.needs_review, pair["name"]
        if pair["expected"] == "distinct":
            assert not decision.should_cluster and not decision.needs_review, pair["name"]

    precision = true_positive / (true_positive + false_positive)
    recall = true_positive / (true_positive + false_negative)
    assert precision == 1.0
    assert recall == 1.0


def test_exact_source_identity_is_deterministic() -> None:
    payload = {
        "source": "arbeitsagentur", "source_job_id": "same-id",
        "title": "Data Analyst", "company": "Acme GmbH", "city": "Berlin",
    }
    decision = DuplicateMatcher().compare(_job(payload), _job(payload))
    assert decision.should_cluster
    assert decision.method.value == "exact_source_id"
