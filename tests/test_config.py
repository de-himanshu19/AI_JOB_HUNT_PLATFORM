from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

import app.config as config
from app.logging_config import sanitize_log_context


def test_settings_defaults_and_approved_product_policy(tmp_path: Path) -> None:
    settings = config.settings_from_mapping({}, root=tmp_path)

    assert settings.database_path == (tmp_path / "data/job_hunt.sqlite3").resolve()
    assert settings.data_dir == (tmp_path / "data").resolve()
    assert settings.telegram_enabled is False
    assert settings.ai_provider == "rule_based"
    assert settings.strict_german_exclusion is False
    assert settings.language_risk_penalty == 15
    assert settings.banking_preference_bonus == 10
    assert settings.arbeitsagentur_location == "Deutschland"
    assert settings.arbeitsagentur_page_size == 25
    assert settings.arbeitsagentur_max_pages == 5
    assert len(settings.arbeitsagentur_queries) == len(set(settings.arbeitsagentur_queries))


def test_windows_safe_relative_path_resolution(tmp_path: Path) -> None:
    settings = config.settings_from_mapping(
        {"JOBHUNT_DATABASE_PATH": r"data\nested folder\jobs.sqlite3"},
        root=tmp_path,
    )
    assert settings.database_path == (
        tmp_path / "data" / "nested folder" / "jobs.sqlite3"
    ).resolve()
    assert "nested folder" in str(settings.database_path)


def test_primary_names_and_temporary_aliases(tmp_path: Path) -> None:
    aliased = config.settings_from_mapping(
        {
            "DATABASE_PATH": "legacy.sqlite3",
            "OLLAMA_API_KEY": "legacy-key",
        },
        root=tmp_path,
    )
    assert aliased.database_path == (tmp_path / "legacy.sqlite3").resolve()
    assert aliased.ai_ollama_api_key.get_secret_value() == "legacy-key"

    primary = config.settings_from_mapping(
        {
            "JOBHUNT_DATABASE_PATH": "primary.sqlite3",
            "DATABASE_PATH": "legacy.sqlite3",
            "AI_OLLAMA_API_KEY": "primary-key",
            "OLLAMA_API_KEY": "legacy-key",
        },
        root=tmp_path,
    )
    assert primary.database_path == (tmp_path / "primary.sqlite3").resolve()
    assert primary.ai_ollama_api_key.get_secret_value() == "primary-key"


def test_arbeitsagentur_query_override_is_typed_and_deduplicated(tmp_path: Path) -> None:
    settings = config.settings_from_mapping(
        {"ARBEITSAGENTUR_QUERIES": "Data Analyst, Reporting Analyst, Data Analyst"},
        root=tmp_path,
    )
    assert settings.arbeitsagentur_queries == (
        "Data Analyst",
        "Reporting Analyst",
    )


def test_feature_specific_validation_is_deferred_until_enabled(tmp_path: Path) -> None:
    config.settings_from_mapping({}, root=tmp_path)

    with pytest.raises(ValidationError, match="Telegram credentials"):
        config.settings_from_mapping(
            {"TELEGRAM_ENABLED": "true"}, root=tmp_path
        )

    with pytest.raises(ValidationError, match="AI_OLLAMA_API_KEY"):
        config.settings_from_mapping(
            {"AI_PROVIDER": "ollama_cloud"}, root=tmp_path
        )


def test_secret_redaction_covers_required_name_markers(tmp_path: Path) -> None:
    settings = config.settings_from_mapping(
        {
            "TELEGRAM_BOT_TOKEN": "do-not-log",
            "TELEGRAM_CHAT_ID": "do-not-log",
            "AI_OLLAMA_API_KEY": "do-not-log",
        },
        root=tmp_path,
    )
    redacted = settings.redacted_dict()

    assert redacted["telegram_bot_token"] == "***REDACTED***"
    assert redacted["telegram_chat_id"] == "***REDACTED***"
    assert redacted["ai_ollama_api_key"] == "***REDACTED***"
    assert redacted["arbeitsagentur_api_key"] == "***REDACTED***"
    assert "do-not-log" not in repr(redacted)


def test_structured_log_context_redacts_secrets_and_private_documents() -> None:
    safe = sanitize_log_context(
        {
            "job_id": "job-1",
            "telegram_token": "secret",
            "job_description": "private JD body",
            "cv_text": "private CV body",
        }
    )
    assert safe == {
        "job_id": "job-1",
        "telegram_token": "***REDACTED***",
        "job_description": "[OMITTED]",
        "cv_text": "[OMITTED]",
    }


def test_root_env_is_read_exactly_once(monkeypatch, tmp_path: Path) -> None:
    (tmp_path / ".env").write_text(
        "APP_LOG_LEVEL=WARNING\nSTRICT_GERMAN_EXCLUSION=true\n",
        encoding="utf-8",
    )
    config._reset_settings_cache_for_tests()
    monkeypatch.setattr(config, "repository_root", lambda: tmp_path)

    first = config.get_settings()
    second = config.get_settings()

    assert first is second
    assert first.log_level == "WARNING"
    assert first.strict_german_exclusion is True
    assert config._env_file_read_count_for_tests() == 1
    config._reset_settings_cache_for_tests()
