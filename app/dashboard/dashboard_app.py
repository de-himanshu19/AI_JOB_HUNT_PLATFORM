"""Streamlit navigation entry point."""

import streamlit as st

from app.dashboard.components import profile_picker
from app.dashboard.pages import (
    analytics_page,
    applications_page,
    cv_builder_page,
    duplicate_review_page,
    job_detail_page,
    jobs_page,
    notifications_page,
    overview_page,
    review_tray_page,
    runs_page,
)
from app.dashboard.runtime import runtime
from app.dashboard.styles import apply_styles


def navigation_labels() -> dict[str, tuple[str, ...]]:
    return {
        "Daily Workflow": (
            "Daily Runs",
            "Review Jobs",
            "Review Tray",
            "Job Detail",
            "CV Workflow",
            "Applications",
            "Analytics",
        ),
        "Advanced / Diagnostics": (
            "Duplicate Review",
            "Notifications",
            "Advanced / Diagnostics",
        ),
    }


def main() -> None:
    st.set_page_config(
        page_title="Job Hunt Operations Desk",
        page_icon=None,
        layout="wide",
        initial_sidebar_state="expanded",
    )
    apply_styles()
    context = runtime()
    profile_picker(context)
    labels = navigation_labels()
    pages = {
        "Daily Workflow": [
            st.Page(
                overview_page,
                title=labels["Daily Workflow"][0],
                url_path="daily-runs",
                default=True,
            ),
            st.Page(
                jobs_page,
                title=labels["Daily Workflow"][1],
                url_path="review-jobs",
            ),
            st.Page(
                review_tray_page,
                title=labels["Daily Workflow"][2],
                url_path="review-tray",
            ),
            st.Page(
                job_detail_page,
                title=labels["Daily Workflow"][3],
                url_path="job-detail",
            ),
            st.Page(
                cv_builder_page,
                title=labels["Daily Workflow"][4],
                url_path="cv-builder",
            ),
            st.Page(
                applications_page,
                title=labels["Daily Workflow"][5],
                url_path="applications",
            ),
            st.Page(
                analytics_page,
                title=labels["Daily Workflow"][6],
                url_path="analytics",
            ),
        ],
        "Advanced / Diagnostics": [
            st.Page(
                duplicate_review_page,
                title=labels["Advanced / Diagnostics"][0],
                url_path="duplicates",
            ),
            st.Page(
                notifications_page,
                title=labels["Advanced / Diagnostics"][1],
                url_path="notifications",
            ),
            st.Page(
                runs_page,
                title=labels["Advanced / Diagnostics"][2],
                url_path="advanced-diagnostics",
            ),
        ],
    }
    st.navigation(pages, position="sidebar").run()
