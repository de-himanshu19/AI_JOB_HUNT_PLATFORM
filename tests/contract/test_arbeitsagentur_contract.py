from __future__ import annotations

from app.config import settings_from_mapping
from app.domain.enums import JobSource
from app.domain.job import Job, JobDescription
from app.sources.arbeitsagentur.adapter import ArbeitsagenturAdapter
from app.sources.base import CollectedJob, CollectionRequest, CollectionResult


class ContractClient:
    def search(self, query, **kwargs):
        return {
            "maxErgebnisse": 1,
            "ergebnisliste": [
                {
                    "referenznummer": "CONTRACT-1",
                    "stellenangebotsTitel": "Data Quality Analyst",
                }
            ],
        }

    def fetch_details(self, source_job_id, url=None):
        return {"stellenbeschreibung": "A complete fixture description " * 3}


def test_adapter_returns_only_source_independent_domain_contract(tmp_path):
    adapter = ArbeitsagenturAdapter(
        settings_from_mapping({}, root=tmp_path), ContractClient()
    )
    result = adapter.collect(CollectionRequest(queries=("Data Quality Analyst",)))
    assert isinstance(result, CollectionResult)
    assert isinstance(result.jobs[0], CollectedJob)
    assert isinstance(result.jobs[0].job, Job)
    assert isinstance(result.jobs[0].description, JobDescription)
    assert result.jobs[0].job.source is JobSource.ARBEITSAGENTUR
    assert not hasattr(result.jobs[0], "dataframe")

