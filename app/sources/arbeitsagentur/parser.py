"""Structural parsers for Arbeitsagentur v6 search and v4 details."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any, Iterable, Mapping

from app.sources.arbeitsagentur.client import encode_ref_number
from app.sources.arbeitsagentur.models import (
    LanguageSignals,
    RawJobDetails,
    RawJobSummary,
    SearchPage,
)


GERMAN_REQUIREMENT_PHRASES = (
    "verhandlungssichere deutschkenntnisse",
    "verhandlungssicheres deutsch",
    "verhandlungssicher in deutsch",
    "deutsch verhandlungssicher",
    "deutschkenntnisse verhandlungssicher",
    "sehr gute deutschkenntnisse",
    "sehr gutes deutsch",
    "fließende deutschkenntnisse",
    "fliessende deutschkenntnisse",
    "fließend deutsch",
    "fliessend deutsch",
    "deutsch fließend",
    "deutsch fliessend",
    "muttersprachliche deutschkenntnisse",
    "deutsch auf muttersprachlichem niveau",
    "ausgezeichnete deutschkenntnisse",
    "hervorragende deutschkenntnisse",
    "perfekte deutschkenntnisse",
    "fluent german",
    "native german",
)

ENGLISH_SIGNAL_PHRASES = (
    "english",
    "englisch",
    "gute englischkenntnisse",
    "sehr gute englischkenntnisse",
    "very good english",
    "fluent english",
    "international",
    "internationales team",
    "global",
    "multinational",
)

CUSTOMER_FACING_GERMAN_PHRASES = (
    "kundenberatung",
    "telefonische kundenbetreuung",
    "privatkunden",
    "privatkundenberatung",
    "firmenkundenberatung",
    "filialgeschäft",
    "sachbearbeitung",
    "kundenservice",
    "kundenbetreuung",
    "beratungsgespräche",
    "direkter kundenkontakt",
    "persönliche kundenberatung",
    "korrespondenz mit kunden",
    "deutschsprachigen kunden",
)

GERMAN_COMMON_WORDS = {
    "der", "die", "das", "und", "für", "mit", "sie", "wir", "ihre",
    "aufgaben", "anforderungen", "kenntnisse", "erfahrung", "bewerbung",
}
ENGLISH_COMMON_WORDS = {
    "the", "and", "for", "with", "you", "we", "your", "responsibilities",
    "requirements", "skills", "experience", "application",
}


class SourcePayloadError(ValueError):
    pass


def _text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        cleaned = " ".join(value.split())
        return cleaned or None
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, Mapping):
        for key in ("bezeichnung", "name", "wert", "value", "text"):
            if key in value:
                result = _text(value[key])
                if result:
                    return result
    return None


def _date(value: Any) -> date | None:
    text = _text(value)
    if not text:
        return None
    for candidate in (text, text[:10]):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            pass
    for pattern in ("%d.%m.%Y", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            pass
    return None


def _string_items(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        cleaned = _text(value)
        return (cleaned,) if cleaned else ()
    if isinstance(value, Mapping):
        cleaned = _text(value)
        return (cleaned,) if cleaned else ()
    if isinstance(value, Iterable):
        items: list[str] = []
        for child in value:
            cleaned = _text(child)
            if cleaned and cleaned not in items:
                items.append(cleaned)
        return tuple(items)
    return ()


def _first(mapping: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] not in (None, "", [], {}):
            return mapping[key]
    return None


def _description_text(value: Any) -> str | None:
    """Extract text from known scalar or wrapped description representations."""
    direct = _text(value)
    if direct:
        return direct
    if isinstance(value, Mapping):
        for key in (
            "inhalt",
            "text",
            "beschreibung",
            "stellenbeschreibung",
            "stellenangebotsBeschreibung",
        ):
            if key in value:
                nested = _description_text(value[key])
                if nested:
                    return nested
    if isinstance(value, Iterable) and not isinstance(value, (str, bytes, Mapping)):
        parts = tuple(filter(None, (_description_text(item) for item in value)))
        return "\n".join(dict.fromkeys(parts)) or None
    return None


def _address_from_summary(record: Mapping[str, Any]) -> dict[str, str | None]:
    locations = record.get("stellenlokationen")
    if not isinstance(locations, list) or not locations:
        return {"raw": None, "city": None, "region": None, "country": None}
    first_location = locations[0] if isinstance(locations[0], Mapping) else {}
    address = first_location.get("adresse", first_location)
    if not isinstance(address, Mapping):
        address = {}
    city = _text(_first(address, "ort", "stadt"))
    region = _text(_first(address, "region", "bundesland"))
    country = _text(_first(address, "land", "staat"))
    postal_code = _text(_first(address, "plz", "postleitzahl"))
    raw = ", ".join(
        part for part in (" ".join(p for p in (postal_code, city) if p), region, country)
        if part
    ) or None
    return {"raw": raw, "city": city, "region": region, "country": country}


def parse_search_page(
    payload: Mapping[str, Any], *, search_term: str, detail_base_url: str
) -> SearchPage:
    if not isinstance(payload, Mapping):
        raise SourcePayloadError("Search payload root must be an object")
    records = payload.get("ergebnisliste")
    if not isinstance(records, list):
        raise SourcePayloadError("Search payload ergebnisliste must be a list")

    total_value = _first(
        payload, "maxErgebnisse", "gesamtzahl", "totalElements", "total"
    )
    try:
        total_results = int(total_value) if total_value is not None else None
    except (TypeError, ValueError):
        total_results = None

    jobs: list[RawJobSummary] = []
    errors: list[str] = []
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            errors.append(f"Record {index} is not an object")
            continue
        reference = _text(_first(record, "referenznummer", "referenzNummer"))
        if not reference:
            errors.append(f"Record {index} is missing referenznummer")
            continue
        title = _text(_first(record, "stellenangebotsTitel", "titel"))
        profession = _text(_first(record, "hauptberuf", "beruf"))
        if not title:
            title = profession or "Untitled vacancy"
            errors.append(f"Record {index} is missing title")
        address = _address_from_summary(record)
        detail_url = (
            detail_base_url.rstrip("/") + "/" + encode_ref_number(reference)
        )
        jobs.append(
            RawJobSummary(
                source_job_id=reference,
                title=title,
                company=_text(_first(record, "firma", "arbeitgeber")),
                location_raw=address["raw"],
                city=address["city"],
                region=address["region"],
                country=address["country"],
                publication_date=_date(
                    _first(record, "datumErsteVeroeffentlichung", "veroeffentlichtAm")
                ),
                profession=profession,
                external_url=_text(_first(record, "externeURL", "externeUrl")),
                source_detail_url=detail_url,
                search_term=search_term,
                search_terms=(search_term,),
                description_snippet=_text(
                    _first(record, "stellenbeschreibung", "beschreibung", "kurzbeschreibung")
                ),
            )
        )
    return SearchPage(jobs=jobs, total_results=total_results, record_errors=errors)


def detect_language(text: str) -> tuple[str | None, float | None]:
    tokens = re.findall(r"[a-zA-ZäöüÄÖÜß]+", text.casefold())
    if not tokens:
        return None, None
    german = sum(token in GERMAN_COMMON_WORDS for token in tokens)
    english = sum(token in ENGLISH_COMMON_WORDS for token in tokens)
    total = german + english
    if total < 2 or german == english:
        return None, None
    if german > english:
        return "de", round(german / total, 3)
    return "en", round(english / total, 3)


def extract_language_signals(text: str) -> LanguageSignals:
    lowered = " ".join(text.casefold().split())
    german_phrases = tuple(
        phrase for phrase in GERMAN_REQUIREMENT_PHRASES if phrase in lowered
    )
    english_phrases = tuple(
        phrase for phrase in ENGLISH_SIGNAL_PHRASES if phrase in lowered
    )
    customer_phrases = tuple(
        phrase for phrase in CUSTOMER_FACING_GERMAN_PHRASES if phrase in lowered
    )
    level_match = re.search(
        r"(?:deutsch(?:kenntnisse)?|german)\s*(?:auf\s*(?:dem\s*)?niveau\s*)?"
        r"(?:von\s*)?(a1|a2|b1|b2|c1|c2)\b|"
        r"\b(a1|a2|b1|b2|c1|c2)\s*(?:deutsch|german)",
        lowered,
    )
    german_level = next(
        (group.upper() for group in level_match.groups() if group), None
    ) if level_match else None
    requirement = None
    if german_level:
        requirement = f"German {german_level}"
    elif german_phrases:
        requirement = "Explicit high German proficiency requirement"
    detected, confidence = detect_language(text)
    return LanguageSignals(
        detected_language=detected,
        language_confidence=confidence,
        german_requirement=requirement,
        german_level=german_level,
        english_signal=bool(english_phrases),
        customer_facing_german_risk=bool(customer_phrases),
        matched_german_phrases=german_phrases,
        matched_english_phrases=english_phrases,
        matched_customer_facing_phrases=customer_phrases,
    )


def _work_locations(payload: Mapping[str, Any]) -> tuple[dict[str, Any], ...]:
    raw_locations = _first(payload, "arbeitsorte", "stellenlokationen")
    if not isinstance(raw_locations, list):
        return ()
    locations: list[dict[str, Any]] = []
    for raw in raw_locations:
        if not isinstance(raw, Mapping):
            continue
        address = raw.get("adresse", raw)
        if not isinstance(address, Mapping):
            continue
        location = {
            "city": _text(_first(address, "ort", "stadt")),
            "region": _text(_first(address, "region", "bundesland")),
            "country": _text(_first(address, "land", "staat")),
            "postal_code": _text(_first(address, "plz", "postleitzahl")),
        }
        if any(location.values()):
            locations.append(location)
    return tuple(locations)


def parse_job_details(
    payload: Mapping[str, Any], *, source_job_id: str, source_url: str
) -> RawJobDetails:
    if not isinstance(payload, Mapping):
        raise SourcePayloadError("Detail payload root must be an object")
    if not payload:
        return RawJobDetails(source_job_id=source_job_id, source_url=source_url)

    description = _description_text(
        _first(
            payload,
            "stellenangebotsBeschreibung",
            "stellenbeschreibung",
            "beschreibung",
            "jobDescription",
        )
    )
    responsibilities = _string_items(
        _first(payload, "aufgaben", "taetigkeiten", "aufgabenUndTaetigkeiten")
    )
    requirements = _string_items(
        _first(payload, "anforderungen", "voraussetzungen", "bewerberprofil", "profil")
    )
    employer_details = _text(
        _first(payload, "arbeitgeberdarstellung", "arbeitgeberBeschreibung")
    )

    sections: list[tuple[str, tuple[str, ...]]] = []
    if description:
        sections.append(("Job Description", (description,)))
    if responsibilities:
        sections.append(("Responsibilities", responsibilities))
    if requirements:
        sections.append(("Requirements", requirements))
    if employer_details:
        sections.append(("Employer", (employer_details,)))
    combined_parts: list[str] = []
    seen: set[str] = set()
    for heading, values in sections:
        unique_values = []
        for value in values:
            key = value.casefold()
            if key not in seen:
                seen.add(key)
                unique_values.append(value)
        if unique_values:
            combined_parts.append(heading + "\n" + "\n".join(unique_values))
    combined_description = "\n\n".join(combined_parts) or None

    employment_type = _text(
        _first(payload, "arbeitsverhaeltnis", "beschaeftigungsart", "employmentType")
    )
    contract_type = _text(_first(payload, "befristung", "vertragsart", "contractType"))
    working_time = _string_items(
        _first(payload, "arbeitszeitmodelle", "arbeitszeit", "workingTime")
    )
    locations = _work_locations(payload)
    language_text = " ".join(
        part for part in (
            combined_description,
            " ".join(requirements),
        ) if part
    )
    signals = extract_language_signals(language_text)
    original_url = _text(
        _first(
            payload,
            "externeURL",
            "externeUrl",
            "bewerbungUrl",
            "bewerbungsurl",
            "applicationUrl",
        )
    )
    structured_data = {
        "responsibilities": list(responsibilities),
        "requirements": list(requirements),
        "employer_details": employer_details,
        "work_locations": list(locations),
        "employment_type": employment_type,
        "contract_type": contract_type,
        "working_time": list(working_time),
        "start_date": _date(_first(payload, "eintrittsdatum", "startDate")),
        "application_deadline": _date(
            _first(payload, "bewerbungsfrist", "gueltigBis", "applicationDeadline")
        ),
        "original_application_url": original_url,
        "language_signals": signals.model_dump(mode="json"),
    }
    # Dates need JSON-safe strings in persisted structured metadata.
    for date_key in ("start_date", "application_deadline"):
        value = structured_data[date_key]
        structured_data[date_key] = value.isoformat() if value else None

    return RawJobDetails(
        source_job_id=source_job_id,
        description=combined_description,
        responsibilities=responsibilities,
        requirements=requirements,
        employer_details=employer_details,
        work_locations=locations,
        employment_type=employment_type,
        contract_type=contract_type,
        working_time=working_time,
        start_date=_date(_first(payload, "eintrittsdatum", "startDate")),
        application_deadline=_date(
            _first(payload, "bewerbungsfrist", "gueltigBis", "applicationDeadline")
        ),
        original_application_url=original_url,
        source_url=source_url,
        language_signals=signals,
        structured_data=structured_data,
    )
