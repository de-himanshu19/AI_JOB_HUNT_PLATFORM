"""Typed root configuration with one-time .env loading and safe redaction."""

from __future__ import annotations

import os
from pathlib import Path
from threading import Lock
from typing import Mapping

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


SECRET_NAME_MARKERS = ("TOKEN", "KEY", "PASSWORD", "SECRET", "CHAT_ID")
DEFAULT_ARBEITSAGENTUR_QUERIES = tuple(
    dict.fromkeys(
        (
            "Data Analyst",
            "Business Analyst",
            "Reporting Analyst",
            "Operations Analyst",
            "Risk Analyst",
            "Compliance Analyst",
            "KYC Analyst",
            "AML Analyst",
            "Financial Analyst",
            "Data Quality Analyst",
            "Datenanalyst",
            "Data-Analyst",
            "Business-Analyst",
            "Risikoanalyst",
            "Finanzanalyst",
            "Compliance",
            "Geldwäsche",
            "Geldwäscheprävention",
            "KYC",
            "AML",
            "Berichtswesen",
            "Reporting",
            "Controlling",
            "Prozessanalyst",
            "Prozessmanager",
            "Datenqualität",
            "Data Warehouse",
            "Data-Warehouse-Analyst",
            "Bank",
            "Finanzdienstleistungen",
        )
    )
)
DEFAULT_ENGLISHJOBS_STATES = (
    "baden_wuerttemberg",
    "bayern",
    "berlin",
    "brandenburg",
    "bremen",
    "hamburg",
    "hessen",
    "mecklenburg_vorpommern",
    "niedersachsen",
    "nordrhein_westfalen",
    "rheinland_pfalz",
    "saarland",
    "sachsen",
    "sachsen_anhalt",
    "schleswig_holstein",
    "thueringen",
)
_CACHE_LOCK = Lock()
_CACHED_SETTINGS: Settings | None = None
_ENV_FILE_READS = 0


def repository_root() -> Path:
    """Return the repository root based on this module, never the process cwd."""
    return Path(__file__).resolve().parents[1]


def resolve_root_path(root: Path, value: str | Path) -> Path:
    """Resolve relative configuration paths against the repository root."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve(strict=False)


def _parse_env_file(path: Path) -> dict[str, str]:
    """Read a small dotenv-compatible file without interpolation or side effects."""
    global _ENV_FILE_READS
    _ENV_FILE_READS += 1
    if not path.is_file():
        return {}

    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            continue
        key, raw_value = line.split("=", 1)
        key = key.strip()
        value = raw_value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def _first(values: Mapping[str, str], primary: str, *aliases: str, default=None):
    for name in (primary, *aliases):
        value = values.get(name)
        if value is not None and value != "":
            return value
    return default


class Settings(BaseModel):
    """Validated runtime settings for the local application core."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    repo_root: Path
    env_file: Path
    app_env: str = "local"
    log_level: str = "INFO"
    log_json: bool = True
    data_dir: Path
    database_path: Path
    company_aliases_path: Path
    fit_rules_path: Path
    cv_artifact_root: Path
    cv_manual_max_bytes: int = Field(default=1_000_000, ge=1, le=10_000_000)
    sqlite_busy_timeout_ms: int = Field(default=5000, ge=1, le=120_000)

    strict_german_exclusion: bool = False
    language_risk_penalty: int = Field(default=15, ge=0, le=100)
    banking_preference_bonus: int = Field(default=10, ge=0, le=100)

    arbeitsagentur_search_url: str
    arbeitsagentur_detail_url: str
    arbeitsagentur_api_key: SecretStr
    arbeitsagentur_queries: tuple[str, ...] = DEFAULT_ARBEITSAGENTUR_QUERIES
    arbeitsagentur_location: str = "Deutschland"
    arbeitsagentur_published_within_days: int = Field(default=7, ge=0, le=365)
    arbeitsagentur_page_size: int = Field(default=25, ge=1, le=100)
    arbeitsagentur_max_pages: int = Field(default=5, ge=1, le=100)
    arbeitsagentur_connect_timeout_seconds: float = Field(default=5, gt=0, le=120)
    arbeitsagentur_read_timeout_seconds: float = Field(default=20, gt=0, le=300)
    arbeitsagentur_max_retries: int = Field(default=3, ge=0, le=10)
    arbeitsagentur_backoff_seconds: float = Field(default=0.5, ge=0, le=60)

    englishjobs_base_url: str = "https://englishjobs.de"
    englishjobs_states: tuple[str, ...] = DEFAULT_ENGLISHJOBS_STATES
    englishjobs_page_size: int = Field(default=20, ge=1, le=100)
    englishjobs_max_pages: int = Field(default=5, ge=1, le=100)
    englishjobs_connect_timeout_seconds: float = Field(default=5, gt=0, le=120)
    englishjobs_read_timeout_seconds: float = Field(default=20, gt=0, le=300)
    englishjobs_max_retries: int = Field(default=3, ge=0, le=10)
    englishjobs_backoff_seconds: float = Field(default=0.5, ge=0, le=60)
    englishjobs_request_delay_seconds: float = Field(default=1.0, ge=0, le=60)

    telegram_enabled: bool = False
    telegram_bot_token: SecretStr | None = None
    telegram_chat_id: SecretStr | None = None
    telegram_api_base_url: str = "https://api.telegram.org"
    telegram_top_n: int = Field(default=20, ge=1, le=20)
    telegram_min_rank_score: float = Field(default=0, ge=0)
    telegram_message_max_chars: int = Field(default=4000, ge=500, le=4096)
    telegram_connect_timeout_seconds: float = Field(default=5, gt=0, le=120)
    telegram_read_timeout_seconds: float = Field(default=20, gt=0, le=300)
    telegram_max_retries: int = Field(default=3, ge=0, le=10)
    telegram_backoff_seconds: float = Field(default=0.5, ge=0, le=60)

    ai_enabled: bool = False
    ai_provider: str = "rule_based"
    ai_api_key: SecretStr | None = None
    ai_base_url: str = "https://api.openai.com/v1"
    ai_model: str = "gpt-4.1-mini"
    ai_ollama_api_key: SecretStr | None = None
    ai_local_model: str = "llama3.2:3b"
    ai_cloud_model: str = "gpt-oss:20b"
    ai_timeout_seconds: float = Field(default=30, gt=0, le=600)
    ai_max_retries: int = Field(default=2, ge=0, le=5)

    legacy_mysql_enabled: bool = False
    legacy_mysql_host: str | None = None
    legacy_mysql_port: int = Field(default=3306, ge=1, le=65535)
    legacy_mysql_database: str | None = None
    legacy_mysql_user: str | None = None
    legacy_mysql_password: SecretStr | None = None
    legacy_mysql_connect_timeout_seconds: float = Field(default=5, gt=0, le=120)

    @model_validator(mode="after")
    def validate_enabled_features(self) -> "Settings":
        if self.log_level.upper() not in {
            "CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"
        }:
            raise ValueError("APP_LOG_LEVEL must be a standard logging level")
        if self.telegram_enabled and (
            self.telegram_bot_token is None or self.telegram_chat_id is None
        ):
            raise ValueError(
                "Telegram credentials are required only when TELEGRAM_ENABLED=true"
            )
        allowed_ai = {"rule_based", "openai_compatible", "ollama_cloud"}
        if self.ai_provider not in allowed_ai:
            raise ValueError(f"AI_PROVIDER must be one of {sorted(allowed_ai)}")
        if not self.arbeitsagentur_queries:
            raise ValueError("At least one Arbeitsagentur search query is required")
        if self.legacy_mysql_enabled and (
            not self.legacy_mysql_host
            or not self.legacy_mysql_database
            or not self.legacy_mysql_user
            or self.legacy_mysql_password is None
        ):
            raise ValueError(
                "Legacy MySQL credentials are required only when LEGACY_MYSQL_ENABLED=true"
            )
        return self

    def redacted_dict(self) -> dict[str, object]:
        """Return settings safe for diagnostics and structured logs."""
        values = self.model_dump(mode="json")
        for name in list(values):
            if any(marker in name.upper() for marker in SECRET_NAME_MARKERS):
                values[name] = "***REDACTED***"
        return values


def settings_from_mapping(
    values: Mapping[str, str], *, root: Path | None = None
) -> Settings:
    """Build settings from an explicit mapping; environment names override defaults."""
    root = (root or repository_root()).resolve(strict=False)
    data_dir = resolve_root_path(
        root, _first(values, "JOBHUNT_DATA_DIR", "DATA_DIR", default="data")
    )
    database_path = resolve_root_path(
        root,
        _first(
            values,
            "JOBHUNT_DATABASE_PATH",
            "DATABASE_PATH",
            default=data_dir / "job_hunt.sqlite3",
        ),
    )
    company_aliases_path = resolve_root_path(
        root,
        _first(
            values,
            "DEDUP_COMPANY_ALIASES_PATH",
            default="config/company_aliases.json",
        ),
    )
    fit_rules_path = resolve_root_path(
        root,
        _first(values, "FIT_RULES_PATH", default="config/fit_rules.json"),
    )
    cv_artifact_root = resolve_root_path(
        root, _first(values, "CV_ARTIFACT_ROOT", default=data_dir / "cv_artifacts")
    )

    configured_queries = _first(values, "ARBEITSAGENTUR_QUERIES")
    queries = (
        tuple(
            dict.fromkeys(
                item.strip()
                for item in str(configured_queries).split(",")
                if item.strip()
            )
        )
        if configured_queries
        else DEFAULT_ARBEITSAGENTUR_QUERIES
    )
    configured_states = _first(values, "ENGLISHJOBS_STATES")
    englishjobs_states = (
        tuple(
            dict.fromkeys(
                item.strip()
                for item in str(configured_states).split(",")
                if item.strip()
            )
        )
        if configured_states
        else DEFAULT_ENGLISHJOBS_STATES
    )

    return Settings(
        repo_root=root,
        env_file=root / ".env",
        app_env=_first(values, "APP_ENV", default="local"),
        log_level=str(_first(values, "APP_LOG_LEVEL", default="INFO")).upper(),
        log_json=_first(values, "APP_LOG_JSON", default="true"),
        data_dir=data_dir,
        database_path=database_path,
        company_aliases_path=company_aliases_path,
        fit_rules_path=fit_rules_path,
        cv_artifact_root=cv_artifact_root,
        cv_manual_max_bytes=_first(values, "CV_MANUAL_MAX_BYTES", default="1000000"),
        sqlite_busy_timeout_ms=_first(
            values, "SQLITE_BUSY_TIMEOUT_MS", default="5000"
        ),
        strict_german_exclusion=_first(
            values, "STRICT_GERMAN_EXCLUSION", default="false"
        ),
        language_risk_penalty=_first(
            values, "LANGUAGE_RISK_PENALTY", default="15"
        ),
        banking_preference_bonus=_first(
            values, "BANKING_PREFERENCE_BONUS", default="10"
        ),
        arbeitsagentur_search_url=_first(
            values,
            "ARBEITSAGENTUR_SEARCH_URL",
            default=(
                "https://rest.arbeitsagentur.de/jobboerse/"
                "jobsuche-service/pc/v6/jobs"
            ),
        ),
        arbeitsagentur_detail_url=_first(
            values,
            "ARBEITSAGENTUR_DETAIL_URL",
            default=(
                "https://rest.arbeitsagentur.de/jobboerse/"
                "jobsuche-service/pc/v4/jobdetails"
            ),
        ),
        arbeitsagentur_api_key=_first(
            values, "ARBEITSAGENTUR_API_KEY", default="jobboerse-jobsuche"
        ),
        arbeitsagentur_queries=queries,
        arbeitsagentur_location=_first(
            values, "ARBEITSAGENTUR_LOCATION", default="Deutschland"
        ),
        arbeitsagentur_published_within_days=_first(
            values, "ARBEITSAGENTUR_PUBLISHED_WITHIN_DAYS", default="7"
        ),
        arbeitsagentur_page_size=_first(
            values, "ARBEITSAGENTUR_PAGE_SIZE", default="25"
        ),
        arbeitsagentur_max_pages=_first(
            values, "ARBEITSAGENTUR_MAX_PAGES", default="5"
        ),
        arbeitsagentur_connect_timeout_seconds=_first(
            values, "ARBEITSAGENTUR_CONNECT_TIMEOUT_SECONDS", default="5"
        ),
        arbeitsagentur_read_timeout_seconds=_first(
            values, "ARBEITSAGENTUR_READ_TIMEOUT_SECONDS", default="20"
        ),
        arbeitsagentur_max_retries=_first(
            values, "ARBEITSAGENTUR_MAX_RETRIES", default="3"
        ),
        arbeitsagentur_backoff_seconds=_first(
            values, "ARBEITSAGENTUR_BACKOFF_SECONDS", default="0.5"
        ),
        englishjobs_base_url=_first(
            values, "ENGLISHJOBS_BASE_URL", default="https://englishjobs.de"
        ),
        englishjobs_states=englishjobs_states,
        englishjobs_page_size=_first(
            values, "ENGLISHJOBS_PAGE_SIZE", default="20"
        ),
        englishjobs_max_pages=_first(
            values, "ENGLISHJOBS_MAX_PAGES", default="5"
        ),
        englishjobs_connect_timeout_seconds=_first(
            values, "ENGLISHJOBS_CONNECT_TIMEOUT_SECONDS", default="5"
        ),
        englishjobs_read_timeout_seconds=_first(
            values, "ENGLISHJOBS_READ_TIMEOUT_SECONDS", default="20"
        ),
        englishjobs_max_retries=_first(
            values, "ENGLISHJOBS_MAX_RETRIES", default="3"
        ),
        englishjobs_backoff_seconds=_first(
            values, "ENGLISHJOBS_BACKOFF_SECONDS", default="0.5"
        ),
        englishjobs_request_delay_seconds=_first(
            values, "ENGLISHJOBS_REQUEST_DELAY_SECONDS", default="1.0"
        ),
        telegram_enabled=_first(values, "TELEGRAM_ENABLED", default="false"),
        telegram_bot_token=_first(values, "TELEGRAM_BOT_TOKEN"),
        telegram_chat_id=_first(values, "TELEGRAM_CHAT_ID"),
        telegram_api_base_url=_first(
            values, "TELEGRAM_API_BASE_URL", default="https://api.telegram.org"
        ),
        telegram_top_n=_first(values, "TELEGRAM_TOP_N", default="20"),
        telegram_min_rank_score=_first(
            values, "TELEGRAM_MIN_RANK_SCORE", default="0"
        ),
        telegram_message_max_chars=_first(
            values, "TELEGRAM_MESSAGE_MAX_CHARS", default="4000"
        ),
        telegram_connect_timeout_seconds=_first(
            values, "TELEGRAM_CONNECT_TIMEOUT_SECONDS", default="5"
        ),
        telegram_read_timeout_seconds=_first(
            values, "TELEGRAM_READ_TIMEOUT_SECONDS", default="20"
        ),
        telegram_max_retries=_first(
            values, "TELEGRAM_MAX_RETRIES", default="3"
        ),
        telegram_backoff_seconds=_first(
            values, "TELEGRAM_BACKOFF_SECONDS", default="0.5"
        ),
        ai_enabled=_first(values, "AI_ENABLED", default="false"),
        ai_provider=_first(values, "AI_PROVIDER", default="rule_based"),
        ai_api_key=_first(
            values, "AI_API_KEY", "AI_OPENAI_API_KEY", "OPENAI_API_KEY"
        ),
        ai_base_url=_first(
            values, "AI_BASE_URL", default="https://api.openai.com/v1"
        ),
        ai_model=_first(values, "AI_MODEL", default="gpt-4.1-mini"),
        ai_ollama_api_key=_first(
            values, "AI_OLLAMA_API_KEY", "OLLAMA_API_KEY"
        ),
        ai_local_model=_first(values, "AI_LOCAL_MODEL", default="llama3.2:3b"),
        ai_cloud_model=_first(values, "AI_CLOUD_MODEL", default="gpt-oss:20b"),
        ai_timeout_seconds=_first(values, "AI_TIMEOUT_SECONDS", default="30"),
        ai_max_retries=_first(values, "AI_MAX_RETRIES", default="2"),
        legacy_mysql_enabled=_first(
            values, "LEGACY_MYSQL_ENABLED", default="false"
        ),
        legacy_mysql_host=_first(values, "LEGACY_MYSQL_HOST"),
        legacy_mysql_port=_first(values, "LEGACY_MYSQL_PORT", default="3306"),
        legacy_mysql_database=_first(values, "LEGACY_MYSQL_DATABASE"),
        legacy_mysql_user=_first(values, "LEGACY_MYSQL_USER"),
        legacy_mysql_password=_first(values, "LEGACY_MYSQL_PASSWORD"),
        legacy_mysql_connect_timeout_seconds=_first(
            values, "LEGACY_MYSQL_CONNECT_TIMEOUT_SECONDS", default="5"
        ),
    )


def get_settings() -> Settings:
    """Load the root .env once, overlay process environment, and cache settings."""
    global _CACHED_SETTINGS
    if _CACHED_SETTINGS is not None:
        return _CACHED_SETTINGS
    with _CACHE_LOCK:
        if _CACHED_SETTINGS is None:
            root = repository_root()
            merged = _parse_env_file(root / ".env")
            merged.update(os.environ)
            _CACHED_SETTINGS = settings_from_mapping(merged, root=root)
    return _CACHED_SETTINGS


def _reset_settings_cache_for_tests() -> None:
    """Reset singleton state for isolated tests; not part of the public API."""
    global _CACHED_SETTINGS, _ENV_FILE_READS
    with _CACHE_LOCK:
        _CACHED_SETTINGS = None
        _ENV_FILE_READS = 0


def _env_file_read_count_for_tests() -> int:
    return _ENV_FILE_READS
