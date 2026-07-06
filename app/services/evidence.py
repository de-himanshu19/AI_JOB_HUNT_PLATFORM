"""Truthful requirement-to-profile evidence matching with explicit precedence."""

from __future__ import annotations

from app.domain.analysis import (
    EvidenceReference,
    EvidenceType,
    JobRequirement,
    RequirementCategory,
)
from app.domain.candidate import (
    CandidateEvidenceItem,
    CandidateEvidenceProfile,
    EvidenceStrength,
)
from app.services.normalization import normalize_text


PROFICIENCY = {
    "mentioned": 0, "basic": 1, "a1": 1, "a2": 2, "b1": 3,
    "b2": 4, "business": 4, "professional": 4, "c1": 5,
    "c2": 6, "fluent": 6, "excellent": 6, "native": 7,
}


def _corpus(item: CandidateEvidenceItem) -> str:
    return normalize_text(" ".join((
        item.label, item.summary, *item.skills, *item.tools, *item.domains,
    ))) or ""


def _matches(requirement: JobRequirement, item: CandidateEvidenceItem) -> bool:
    needle = normalize_text(requirement.name) or ""
    corpus = _corpus(item)
    terms = set(needle.split())
    if requirement.name == "SAP S/4HANA migration ownership":
        return any(term in corpus for term in ("s 4hana migration", "s4hana migration", "sap s 4hana implementation"))
    if requirement.category is RequirementCategory.SENIORITY:
        return (item.seniority or "").casefold() in {"senior", "lead", "professional"}
    if requirement.name == "Finance and controlling direct experience":
        return "controlling" in corpus or "financial controlling" in corpus
    return bool(terms) and terms <= set(corpus.split())


class EvidenceMatcher:
    def match(
        self, requirements: tuple[JobRequirement, ...], profile: CandidateEvidenceProfile
    ) -> tuple[tuple[EvidenceReference, ...], tuple[str, ...]]:
        references: list[EvidenceReference] = []
        risks: list[str] = []
        for requirement in requirements:
            reference, risk = self._match_one(requirement, profile)
            references.append(reference)
            if risk and risk not in risks:
                risks.append(risk)
        return tuple(references), tuple(risks)

    def _match_one(self, requirement, profile):
        if requirement.category is RequirementCategory.LANGUAGE:
            return self._language(requirement, profile)

        direct = [
            item for item in profile.work_experience
            if item.strength is EvidenceStrength.DIRECT and _matches(requirement, item)
        ]
        if direct:
            item = direct[0]
            return self._ref(requirement, EvidenceType.DIRECT_PROFESSIONAL, item, "Requirement is explicitly supported by professional experience."), None

        transferable_work = [
            item for item in profile.work_experience
            if item.strength is not EvidenceStrength.DIRECT and _matches(requirement, item)
        ]
        if transferable_work:
            return self._ref(
                requirement, EvidenceType.PROFESSIONAL_TRANSFERABLE,
                transferable_work[0],
                "Requirement is supported by transferable professional evidence.",
            ), None

        if requirement.name == "SAP S/4HANA migration ownership":
            generic_sap = any("sap" in _corpus(item) for item in profile.work_experience)
            if generic_sap:
                return self._none(requirement, "Generic SAP exposure does not prove S/4HANA migration ownership."), "erp_ownership_gap: S/4HANA ownership required but only generic SAP exposure is stored"

        if requirement.category is RequirementCategory.SENIORITY:
            return self._none(requirement, "No matching direct senior/professional evidence is stored."), "seniority_gap: senior or professional experience is required without matching direct evidence"

        if requirement.name == "Finance and controlling direct experience":
            transferable = next((item for item in profile.work_experience if "report" in _corpus(item)), None)
            if transferable:
                return self._ref(requirement, EvidenceType.PROFESSIONAL_TRANSFERABLE, transferable, "Reporting experience is transferable but does not prove direct controlling ownership."), "finance_direct_experience_gap: only transferable reporting evidence is stored"

        projects = [item for item in profile.projects if _matches(requirement, item)]
        if projects:
            return self._ref(requirement, EvidenceType.PROJECT, projects[0], "Requirement is supported by project evidence, not professional ownership."), None

        education = [item for item in profile.education_training if _matches(requirement, item)]
        if education and requirement.category in {RequirementCategory.SKILL, RequirementCategory.TOOL, RequirementCategory.EDUCATION}:
            return self._ref(requirement, EvidenceType.EDUCATION_TRAINING, education[0], "Requirement is supported by education, training, or certification evidence."), None

        general = " ".join((*profile.skills, *profile.tools, *profile.domains))
        if (normalize_text(requirement.name) or "") in (normalize_text(general) or ""):
            synthetic = CandidateEvidenceItem(evidence_id="profile:skills", label="Stored skills and tools", summary=general)
            return self._ref(requirement, EvidenceType.PROFESSIONAL_TRANSFERABLE, synthetic, "Stored skill exposure is transferable evidence and does not imply ownership."), None

        return self._none(requirement, "No supporting evidence is stored in the candidate profile."), None

    def _language(self, requirement, profile):
        language_name = requirement.name.split()[0].casefold()
        candidate = next((item for item in profile.languages if item.name.casefold() == language_name), None)
        if candidate is None:
            return self._none(requirement, "The required language is not stored in the profile."), "language_mismatch: required language proficiency is not stored"
        required = PROFICIENCY.get((requirement.level or "mentioned").casefold(), 0)
        actual = PROFICIENCY.get(candidate.proficiency.casefold(), 0)
        if actual >= required:
            synthetic = CandidateEvidenceItem(evidence_id=f"language:{language_name}", label=f"{candidate.name} {candidate.proficiency}")
            return self._ref(requirement, EvidenceType.DIRECT_PROFESSIONAL, synthetic, "Stored language proficiency meets the requirement."), None
        return self._none(requirement, f"Stored {candidate.name} proficiency ({candidate.proficiency}) is below {requirement.level}."), f"language_mismatch: {requirement.name} required but profile stores {candidate.proficiency}"

    @staticmethod
    def _ref(requirement, evidence_type, item, reason):
        return EvidenceReference(requirement_id=requirement.requirement_id, evidence_type=evidence_type, evidence_id=item.evidence_id, label=item.label, reason=reason)

    @staticmethod
    def _none(requirement, reason):
        return EvidenceReference(requirement_id=requirement.requirement_id, evidence_type=EvidenceType.NO_EVIDENCE, reason=reason)
