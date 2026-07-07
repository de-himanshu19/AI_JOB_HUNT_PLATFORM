"""Dashboard dependency construction and safe read-only Streamlit caches."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from app.config import Settings, get_settings
from app.dashboard.actions import DashboardActions
from app.dashboard.query_service import DashboardQueryService
from app.dashboard.view_models import JobFilters
from app.db.connection import Database
from app.db.migrations import migrate


@dataclass(frozen=True)
class DashboardRuntime:
    settings: Settings
    database: Database
    queries: DashboardQueryService
    actions: DashboardActions


def runtime() -> DashboardRuntime:
    settings = get_settings()
    database = Database.from_settings(settings)
    migrate(database)
    return DashboardRuntime(
        settings=settings,
        database=database,
        queries=DashboardQueryService(database),
        actions=DashboardActions(database, settings),
    )


@st.cache_data(ttl=20, show_spinner=False)
def cached_profiles(database_path: str, busy_timeout_ms: int):
    return DashboardQueryService(
        Database(Path(database_path), busy_timeout_ms)
    ).profiles()


@st.cache_data(ttl=20, show_spinner=False)
def cached_overview(database_path: str, busy_timeout_ms: int, profile_id: str):
    return DashboardQueryService(
        Database(Path(database_path), busy_timeout_ms)
    ).overview(profile_id or None)


@st.cache_data(ttl=20, show_spinner=False)
def cached_jobs(
    database_path: str,
    busy_timeout_ms: int,
    profile_id: str,
    filters: JobFilters,
):
    return DashboardQueryService(
        Database(Path(database_path), busy_timeout_ms)
    ).jobs(filters, profile_id or None)


@st.cache_data(ttl=20, show_spinner=False)
def cached_runs(database_path: str, busy_timeout_ms: int, limit: int):
    return DashboardQueryService(
        Database(Path(database_path), busy_timeout_ms)
    ).runs(limit)


def clear_read_caches() -> None:
    cached_profiles.clear()
    cached_overview.clear()
    cached_jobs.clear()
    cached_runs.clear()

