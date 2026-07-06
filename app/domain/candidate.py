"""Versioned candidate profile derived from the ai_cv_tailor master-CV shape."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _profile_hash(profile_data: dict[str, Any]) -> str:
    encoded = json.dumps(
        profile_data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _profile_key(name: str) -> str:
    value = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return value or "candidate"


class CandidateProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    profile_key: str = Field(min_length=1)
    version: int = Field(ge=1)
    display_name: str = Field(min_length=1)
    profile_data: dict[str, Any]
    content_hash: str = Field(min_length=64, max_length=64)
    active: bool = True
    created_at: datetime = Field(default_factory=_utc_now)

    @model_validator(mode="after")
    def validate_master_cv_shape(self) -> "CandidateProfile":
        required = {"personal_info", "work_experience"}
        missing = sorted(required - self.profile_data.keys())
        if not ({"skills_bank", "skills_and_tools"} & self.profile_data.keys()):
            missing.append("skills_bank or skills_and_tools")
        if missing:
            raise ValueError(
                "Candidate profile is missing master-CV sections: " + ", ".join(missing)
            )
        if _profile_hash(self.profile_data) != self.content_hash:
            raise ValueError("Candidate profile content_hash does not match profile_data")
        return self

    @classmethod
    def from_master_cv(
        cls,
        profile_data: dict[str, Any],
        *,
        version: int,
        profile_key: str | None = None,
        active: bool = True,
    ) -> "CandidateProfile":
        personal_info = profile_data.get("personal_info", {})
        display_name = str(personal_info.get("full_name") or "Candidate").strip()
        return cls(
            profile_key=profile_key or _profile_key(display_name),
            version=version,
            display_name=display_name,
            profile_data=profile_data,
            content_hash=_profile_hash(profile_data),
            active=active,
        )


class EvidenceStrength(StrEnum):
    DIRECT = "direct"
    TRANSFERABLE = "transferable"
    SUPPORTING = "supporting"


class CandidateEvidenceItem(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True)

    evidence_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    summary: str = ""
    skills: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    domains: tuple[str, ...] = ()
    metrics: tuple[str, ...] = ()
    seniority: str | None = None
    strength: EvidenceStrength = EvidenceStrength.SUPPORTING


class CandidateLanguage(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(min_length=1)
    proficiency: str = Field(min_length=1)


class CandidatePreferences(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    target_role_families: tuple[str, ...] = ()
    preferred_locations: tuple[str, ...] = ()
    mobility: tuple[str, ...] = ()
    preferred_domains: tuple[str, ...] = ()


class CandidateEvidenceProfile(BaseModel):
    """Generic evidence view derived only from imported profile data."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_id: UUID
    profile_version: int
    content_hash: str
    work_experience: tuple[CandidateEvidenceItem, ...] = ()
    projects: tuple[CandidateEvidenceItem, ...] = ()
    education_training: tuple[CandidateEvidenceItem, ...] = ()
    skills: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    languages: tuple[CandidateLanguage, ...] = ()
    domains: tuple[str, ...] = ()
    verified_metrics: tuple[str, ...] = ()
    preferences: CandidatePreferences = Field(default_factory=CandidatePreferences)

    @classmethod
    def from_candidate_profile(cls, profile: CandidateProfile) -> "CandidateEvidenceProfile":
        data = profile.profile_data
        work = cls._section(data, "work_experience", EvidenceStrength.DIRECT)
        projects = cls._section(data, "projects", EvidenceStrength.SUPPORTING)
        education = tuple(
            item
            for name in ("education", "training_and_courses", "courses", "certifications")
            for item in cls._section(data, name, EvidenceStrength.SUPPORTING)
        )
        skills_payload = data.get("skills_and_tools", data.get("skills_bank", {}))
        skills = cls._strings(skills_payload)
        tools = cls._strings(
            skills_payload.get("tools", []) if isinstance(skills_payload, dict) else []
        )
        languages = cls._languages(data.get("languages", []))
        preferences_data = data.get("preferences", {})
        role_data = data.get("role_families", {})
        target_roles = cls._strings(
            preferences_data.get("target_role_families", role_data)
            if isinstance(preferences_data, dict)
            else role_data
        )
        preferences = CandidatePreferences(
            target_role_families=target_roles,
            preferred_locations=cls._strings(
                preferences_data.get("preferred_locations", [])
                if isinstance(preferences_data, dict) else []
            ),
            mobility=cls._strings(
                preferences_data.get("mobility", [])
                if isinstance(preferences_data, dict) else []
            ),
            preferred_domains=cls._strings(
                preferences_data.get("preferred_domains", [])
                if isinstance(preferences_data, dict) else []
            ),
        )
        return cls(
            profile_id=profile.id,
            profile_version=profile.version,
            content_hash=profile.content_hash,
            work_experience=work,
            projects=projects,
            education_training=education,
            skills=skills,
            tools=tools,
            languages=languages,
            domains=cls._strings(data.get("domains", [])),
            verified_metrics=cls._strings(data.get("verified_metrics", data.get("metrics_and_achievements", []))),
            preferences=preferences,
        )

    @classmethod
    def _section(cls, data: dict[str, Any], name: str, default: EvidenceStrength) -> tuple[CandidateEvidenceItem, ...]:
        payload = data.get(name, [])
        items = payload.get("items", []) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return ()
        results = []
        for index, item in enumerate(items):
            if not isinstance(item, dict):
                continue
            label = str(item.get("role") or item.get("name") or item.get("title") or item.get("degree") or f"{name}-{index + 1}").strip()
            strength_raw = str(item.get("evidence_strength") or item.get("evidence_type") or default.value).casefold()
            strength = (
                EvidenceStrength.DIRECT if "direct" in strength_raw
                else EvidenceStrength.TRANSFERABLE if "transfer" in strength_raw
                else EvidenceStrength.SUPPORTING
            )
            results.append(CandidateEvidenceItem(
                evidence_id=str(item.get("id") or f"{name}:{index + 1}"),
                label=label,
                summary=str(item.get("summary") or item.get("role_summary") or item.get("description") or ""),
                skills=cls._strings(item.get("skills", item.get("keywords", []))),
                tools=cls._strings(item.get("tools", [])),
                domains=cls._strings(item.get("domains", [])),
                metrics=cls._strings(item.get("metrics", [])),
                seniority=(str(item.get("seniority")).strip() or None) if item.get("seniority") is not None else None,
                strength=strength,
            ))
        return tuple(results)

    @classmethod
    def _strings(cls, value: Any) -> tuple[str, ...]:
        if isinstance(value, str):
            return (value.strip(),) if value.strip() else ()
        if isinstance(value, dict):
            return tuple(dict.fromkeys(
                item for nested in value.values() for item in cls._strings(nested)
            ))
        if isinstance(value, list):
            return tuple(dict.fromkeys(
                item for nested in value for item in cls._strings(nested)
            ))
        return ()

    @staticmethod
    def _languages(value: Any) -> tuple[CandidateLanguage, ...]:
        if isinstance(value, dict):
            value = value.get("items", value)
            if isinstance(value, dict):
                return tuple(CandidateLanguage(name=str(name), proficiency=str(level)) for name, level in value.items())
        if not isinstance(value, list):
            return ()
        results = []
        for item in value:
            if isinstance(item, str):
                parts = item.split("-", 1)
                results.append(CandidateLanguage(name=parts[0].strip(), proficiency=parts[1].strip() if len(parts) > 1 else "mentioned"))
            elif isinstance(item, dict) and item.get("name"):
                results.append(CandidateLanguage(name=str(item["name"]), proficiency=str(item.get("proficiency") or item.get("level") or "mentioned")))
        return tuple(results)
