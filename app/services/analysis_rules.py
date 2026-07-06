"""Typed, versioned configuration for deterministic fit and ranking rules."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


class RankingRules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    freshness_max_bonus: float = Field(ge=0)
    preferred_location_bonus: float = Field(ge=0)
    preferred_domain_bonus: float = Field(ge=0)
    freshness_window_days: int = Field(gt=0)


class AnalysisRules(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    rules_version: str
    analyzer_version: str
    ranking_version: str
    evidence_weights: dict[str, float]
    required_requirement_weight: float = Field(gt=0)
    optional_requirement_weight: float = Field(gt=0)
    target_role_bonus: float = Field(ge=0)
    required_missing_penalty: float = Field(ge=0)
    maximum_missing_penalty: float = Field(ge=0)
    risk_penalties: dict[str, float]
    score_caps: dict[str, float]
    ranking: RankingRules

    @classmethod
    def from_json(cls, path: Path) -> "AnalysisRules":
        return cls.model_validate(json.loads(path.read_text(encoding="utf-8")))
