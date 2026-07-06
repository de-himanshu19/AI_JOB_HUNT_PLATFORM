"""Cheap, profile-driven relevance score kept separate from verified fit."""

from __future__ import annotations

from app.domain.analysis import ScoreComponent
from app.domain.candidate import CandidateEvidenceProfile
from app.domain.job import Job, JobDescription
from app.services.normalization import normalize_text


class PrefilterService:
    def score(
        self, job: Job, description: JobDescription | None,
        profile: CandidateEvidenceProfile,
    ) -> tuple[float, tuple[ScoreComponent, ...]]:
        text = normalize_text(" ".join(filter(None, (
            job.title_raw, job.company_raw, job.location_raw,
            description.raw_text if description else None,
        )))) or ""
        components: list[ScoreComponent] = []
        role_hits = [role for role in profile.preferences.target_role_families if (normalize_text(role) or "") in text]
        if role_hits:
            components.append(ScoreComponent(name="target_role_overlap", points=min(40, 20 + 5 * len(role_hits)), reason="Matched target role families: " + ", ".join(role_hits)))
        skill_hits = [skill for skill in (*profile.skills, *profile.tools) if (normalize_text(skill) or "") in text]
        if skill_hits:
            components.append(ScoreComponent(name="profile_term_overlap", points=min(30, 3 * len(skill_hits)), reason="Matched stored profile terms: " + ", ".join(skill_hits[:10])))
        location_hits = [item for item in profile.preferences.preferred_locations if (normalize_text(item) or "") in text]
        if location_hits:
            components.append(ScoreComponent(name="preferred_location", points=15, reason="Matched preferred location: " + location_hits[0]))
        domain_hits = [item for item in profile.preferences.preferred_domains if (normalize_text(item) or "") in text]
        if domain_hits:
            components.append(ScoreComponent(name="preferred_domain", points=15, reason="Matched preferred domain: " + domain_hits[0]))
        return min(100.0, sum(item.points for item in components)), tuple(components)
