"""Versioned candidate profile derived from the ai_cv_tailor master-CV shape."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
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
        required = {"personal_info", "work_experience", "skills_bank"}
        missing = sorted(required - self.profile_data.keys())
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

