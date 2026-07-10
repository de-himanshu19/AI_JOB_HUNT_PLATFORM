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
    pages = {
        "Daily Workflow": [
            st.Page(overview_page, title="Daily Runs", url_path="overview", default=True),
            st.Page(jobs_page, title="Review Jobs", url_path="jobs"),
            st.Page(review_tray_page, title="Review Tray", url_path="review-tray"),
            st.Page(job_detail_page, title="Job Detail", url_path="job-detail"),
            st.Page(cv_builder_page, title="CV Workflow", url_path="cv-builder"),
            st.Page(applications_page, title="Applications", url_path="applications"),
            st.Page(
                analytics_page,
                title="Analytics",
                url_path="applications-analytics",
            ),
        ],
        "Advanced / Diagnostics": [
            st.Page(duplicate_review_page, title="Duplicate Review", url_path="duplicates"),
            st.Page(notifications_page, title="Notifications", url_path="notifications"),
            st.Page(runs_page, title="Advanced / Diagnostics", url_path="runs"),
        ],
    }
    st.navigation(pages, position="sidebar").run()
