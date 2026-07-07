"""Shared presentational helpers and mutation rerun protection."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Callable, TypeVar

import streamlit as st

from app.dashboard.runtime import DashboardRuntime, cached_profiles, clear_read_caches


T = TypeVar("T")


def page_header(title: str, lede: str, *, eyebrow: str = "Operations desk") -> None:
    st.markdown(f'<div class="eyebrow">{eyebrow}</div>', unsafe_allow_html=True)
    st.title(title)
    st.markdown(f'<p class="page-lede">{lede}</p>', unsafe_allow_html=True)


def profile_picker(context: DashboardRuntime) -> str | None:
    profiles = cached_profiles(
        str(context.database.path), context.database.busy_timeout_ms
    )
    with st.sidebar:
        st.markdown("### Candidate context")
        if not profiles:
            st.info("Import a candidate profile with the CLI to enable analysis views.")
            st.session_state.pop("dashboard_profile_id", None)
            return None
        ids = [item.id for item in profiles]
        active = next((item.id for item in profiles if item.active), ids[0])
        current = st.session_state.get("dashboard_profile_id", active)
        if current not in ids:
            current = active
        selected = st.selectbox(
            "Candidate profile",
            ids,
            index=ids.index(current),
            format_func=lambda value: next(
                f"{item.display_name} | v{item.version}"
                for item in profiles if item.id == value
            ),
            key="dashboard_profile_select",
        )
        st.session_state["dashboard_profile_id"] = selected
        selected_profile = next(item for item in profiles if item.id == selected)
        st.caption(f"Profile key: {selected_profile.profile_key}")
        return selected


def execute_once(token: str, action: Callable[[], T]) -> T | None:
    completed = st.session_state.setdefault("completed_dashboard_actions", set())
    if token in completed:
        st.info("This action was already completed in the current session.")
        return None
    in_flight = st.session_state.get("dashboard_action_in_flight")
    if in_flight:
        st.warning("Another action is already in progress.")
        return None
    st.session_state["dashboard_action_in_flight"] = token
    try:
        result = action()
        completed.add(token)
        clear_read_caches()
        return result
    finally:
        st.session_state.pop("dashboard_action_in_flight", None)


def table_rows(items):
    return [asdict(item) if is_dataclass(item) else dict(item) for item in items]


def safe_error(error: Exception) -> None:
    if isinstance(error, (KeyError, ValueError, RuntimeError)):
        st.error(str(error).strip("'"))
    else:
        st.error("The action could not be completed. Review safe diagnostics.")
