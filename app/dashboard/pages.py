"""Streamlit page renderers kept intentionally thin."""

from __future__ import annotations

from datetime import UTC, datetime

import streamlit as st

from app.dashboard.components import (
    execute_once,
    page_header,
    safe_error,
    table_rows,
)
from app.dashboard.runtime import (
    cached_application_analytics,
    cached_daily_runs,
    cached_jobs,
    cached_overview,
    cached_runs,
    runtime,
)
from app.dashboard.presentation import (
    date_range_start,
    default_follow_up_date,
    fit_score_label,
    job_row,
    match_type_label,
    parse_city,
    posted_or_first_seen_display,
    tray_row,
)
from app.dashboard.view_models import JobFilters
from app.domain.enums import ApplicationStatus, JobSource


def _profile_id() -> str | None:
    return st.session_state.get("dashboard_profile_id")


def _selected_job_id() -> str | None:
    return st.session_state.get("selected_job_id")


def _set_selected_job(job_id: str) -> None:
    st.session_state["selected_job_id"] = job_id


def _selected_cv_artifact_id(detail) -> str | None:
    if detail.applications and detail.applications[0].get("cv_artifact_id"):
        return str(detail.applications[0]["cv_artifact_id"])
    if detail.cv_artifacts:
        return str(detail.cv_artifacts[0].get("id"))
    return None


def _job_option_label(items, value: str) -> str:
    item = next(entry for entry in items if entry.job_id == value)
    return f"{item.title} | {item.company or 'Unknown company'} | {parse_city(item.location)}"


def overview_page() -> None:
    context = runtime()
    profile_id = _profile_id()
    page_header(
        "Overview",
        "A quiet control room for the job hunt: what arrived, what deserves review, and what is ready for action.",
    )
    view = cached_overview(
        str(context.database.path), context.database.busy_timeout_ms, profile_id or ""
    )
    columns = st.columns(7)
    metrics = (
        ("Logical vacancies", view.logical_vacancies),
        ("Active source jobs", view.active_source_jobs),
        ("Authoritative analyses", view.authoritative_analyses),
        ("Preliminary analyses", view.preliminary_analyses),
        ("Authoritative rankings", view.ranked_vacancies),
        ("Preliminary rankings", view.preliminary_rankings),
        ("Duplicate reviews", view.pending_duplicate_reviews),
    )
    for column, (label, value) in zip(columns, metrics):
        column.metric(label, value)

    st.subheader("Application pipeline")
    status_columns = st.columns(4)
    for index, status in enumerate(ApplicationStatus):
        status_columns[index % 4].metric(
            status.value.replace("_", " ").title(),
            view.application_counts.get(status.value, 0),
        )

    left, right = st.columns(2)
    with left:
        st.subheader("Recent collection runs")
        if view.recent_runs:
            st.dataframe(view.recent_runs, use_container_width=True, hide_index=True)
        else:
            st.info("No collection runs yet. The dashboard never starts one automatically.")
        st.subheader("Recent CV artifacts")
        if view.recent_cv_artifacts:
            st.dataframe(view.recent_cv_artifacts, use_container_width=True, hide_index=True)
        else:
            st.info("No CV artifacts have been generated.")
    with right:
        st.subheader("Recent notification batches")
        if view.recent_notification_batches:
            st.dataframe(
                view.recent_notification_batches,
                use_container_width=True,
                hide_index=True,
            )
        else:
            st.info("No notification batches. Preview remains an explicit offline action.")


def analytics_page() -> None:
    context = runtime()
    profile_id = _profile_id()
    page_header(
        "Applications Analytics",
        "Read-only funnel, source quality, follow-up, and daily activity signals for the job search.",
        eyebrow="Progress dashboard",
    )
    summary = cached_application_analytics(
        str(context.database.path),
        context.database.busy_timeout_ms,
        profile_id or "",
        str(context.settings.repo_root / "data" / "daily_runs"),
    )
    metrics = summary["metrics"]
    top = st.columns(6)
    for column, (label, key) in zip(
        top,
        (
            ("Jobs stored", "total_jobs_stored"),
            ("Logical vacancies", "total_logical_vacancies"),
            ("CV-ready", "cv_ready_count"),
            ("Applied", "applied_count"),
            ("Interview", "interview_count"),
            ("Rejected", "rejected_count"),
        ),
    ):
        column.metric(label, metrics[key])
    follow = st.columns(4)
    for column, (label, key) in zip(
        follow,
        (
            ("Due follow-ups", "due_followups"),
            ("Overdue follow-ups", "overdue_followups"),
            ("Jobs seen 7d", "jobs_collected_last_7_days"),
            ("Applications 7d", "applications_created_last_7_days"),
        ),
    ):
        column.metric(label, metrics[key])

    funnel_tab, source_tab, follow_tab, daily_tab = st.tabs(
        ["Funnel", "Source Quality", "Follow-ups", "Daily Runs"]
    )
    with funnel_tab:
        st.subheader("Application funnel")
        funnel = list(summary["funnel"])
        if funnel:
            st.bar_chart(funnel, x="stage", y="count")
            st.dataframe(funnel, use_container_width=True, hide_index=True)
        else:
            st.info("No funnel data yet.")
        st.subheader("Applications by status")
        status_rows = [
            {"status": key, "count": value}
            for key, value in summary["applications_by_status"].items()
        ]
        if status_rows:
            st.bar_chart(status_rows, x="status", y="count")
            st.dataframe(status_rows, use_container_width=True, hide_index=True)
        st.subheader("Applications by priority")
        priority_rows = [
            {"priority": key, "count": value}
            for key, value in summary["applications_by_priority"].items()
        ]
        if priority_rows:
            st.dataframe(priority_rows, use_container_width=True, hide_index=True)

    with source_tab:
        st.subheader("Jobs by source")
        source_rows = [
            {"source": key, "jobs": value}
            for key, value in summary["jobs_by_source"].items()
        ]
        if source_rows:
            st.bar_chart(source_rows, x="source", y="jobs")
            st.dataframe(source_rows, use_container_width=True, hide_index=True)
        else:
            st.info("No jobs are stored yet.")
        st.subheader("Description completeness by source")
        completeness = list(summary["description_completeness_by_source"])
        if completeness:
            st.dataframe(completeness, use_container_width=True, hide_index=True)
        st.subheader("Source quality")
        quality = list(summary["source_quality"])
        if quality:
            st.dataframe(quality, use_container_width=True, hide_index=True)

    with follow_tab:
        st.subheader("Follow-ups due now")
        due = list(summary["followups"]["due"])
        if due:
            st.dataframe(due, use_container_width=True, hide_index=True)
        else:
            st.info("No follow-ups are due today.")
        st.subheader("Overdue follow-ups")
        overdue = list(summary["followups"]["overdue"])
        if overdue:
            st.dataframe(overdue, use_container_width=True, hide_index=True)
        else:
            st.info("No overdue follow-ups.")
        st.subheader("Next 7 days")
        upcoming = list(summary["followups"]["next_7_days"])
        if upcoming:
            st.dataframe(upcoming, use_container_width=True, hide_index=True)
        else:
            st.info("No follow-ups scheduled for the next 7 days.")

    with daily_tab:
        daily = summary["daily_runs"]
        st.subheader("Latest daily run")
        if daily["latest"]:
            st.json(daily["latest"])
        else:
            st.info("No saved daily-run summaries found under data/daily_runs.")
        columns = st.columns(5)
        for column, (label, key) in zip(
            columns,
            (
                ("Searches", "total_searches"),
                ("Succeeded", "successful_searches"),
                ("Failed", "failed_searches"),
                ("Jobs collected", "jobs_collected"),
                ("Errors", "errors"),
            ),
        ):
            column.metric(label, daily[key])
        rows = list(daily["last_7"])
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)


def jobs_page() -> None:
    context = runtime()
    page_header(
        "Review Jobs",
        "Review fresh vacancies deliberately. Filters update only when you click Apply Filters.",
        eyebrow="Daily review",
    )
    if "review_jobs_filters" not in st.session_state:
        st.session_state["review_jobs_filters"] = {
            "source": "All",
            "date_range": "Last 7 days",
            "location_search": "",
            "search": "",
            "application_status": "All",
            "rank_min": 0.0,
            "fit_min": 0.0,
            "authority": "All",
            "include_prefilter_only": True,
            "page": 1,
        }
    stored = st.session_state["review_jobs_filters"]
    with st.form("review_jobs_filters_form"):
        first, second, third, fourth = st.columns(4)
        source = first.selectbox(
            "Source",
            ["All", *[item.value for item in JobSource]],
            index=["All", *[item.value for item in JobSource]].index(stored["source"]),
        )
        date_range = second.selectbox(
            "Posted / First Seen",
            ["Today", "Last 3 days", "Last 7 days", "All"],
            index=["Today", "Last 3 days", "Last 7 days", "All"].index(stored["date_range"]),
        )
        location_search = third.text_input("City / location", value=stored["location_search"])
        search = fourth.text_input("Title / company keyword", value=stored["search"])
        fifth, sixth, seventh, eighth = st.columns(4)
        application_status = fifth.selectbox(
            "Application status",
            ["All", *[item.value for item in ApplicationStatus]],
            index=["All", *[item.value for item in ApplicationStatus]].index(
                stored["application_status"]
            ),
        )
        rank_min = sixth.number_input(
            "Minimum rank score", min_value=0.0, max_value=120.0,
            value=float(stored["rank_min"]), step=1.0,
        )
        fit_min = seventh.number_input(
            "Minimum fit score", min_value=0.0, max_value=100.0,
            value=float(stored["fit_min"]), step=1.0,
        )
        authority = eighth.selectbox(
            "Match type",
            ["All", "Full analysis", "Quick match only"],
            index=["All", "Full analysis", "Quick match only"].index(stored["authority"]),
        )
        include_prefilter_only = st.checkbox(
            "Include quick-match-only jobs",
            value=bool(stored["include_prefilter_only"]),
        )
        submitted = st.form_submit_button("Apply Filters", type="primary")
    if submitted:
        stored = {
            "source": source,
            "date_range": date_range,
            "location_search": location_search,
            "search": search,
            "application_status": application_status,
            "rank_min": rank_min,
            "fit_min": fit_min,
            "authority": authority,
            "include_prefilter_only": include_prefilter_only,
            "page": 1,
        }
        st.session_state["review_jobs_filters"] = stored
    page = int(st.number_input(
        "Page", min_value=1, value=int(stored.get("page", 1)), step=1,
        key="review_jobs_page",
    ))
    if page != stored.get("page", 1):
        stored = {**stored, "page": page}
        st.session_state["review_jobs_filters"] = stored
    authority_filter = {
        "Full analysis": "authoritative",
        "Quick match only": "prefilter_only",
    }.get(stored["authority"])
    filters = JobFilters(
        search=stored["search"],
        location_search=stored["location_search"],
        source=None if stored["source"] == "All" else stored["source"],
        application_status=(
            None if stored["application_status"] == "All"
            else stored["application_status"]
        ),
        authority=authority_filter,
        date_from=date_range_start(stored["date_range"]),
        include_prefilter_only=bool(stored["include_prefilter_only"]),
        fit_min=float(stored["fit_min"]) if float(stored["fit_min"]) > 0 else None,
        rank_min=float(stored["rank_min"]) if float(stored["rank_min"]) > 0 else None,
        logical_only=True,
        sort_by="posted_or_first_seen",
        descending=True,
        page=page,
    )
    try:
        result = cached_jobs(
            str(context.database.path), context.database.busy_timeout_ms,
            _profile_id() or "", filters,
        )
    except Exception as error:
        safe_error(error)
        return
    st.caption(f"{result.total} matching rows | page {result.page} of {result.pages}")
    if not result.items:
        st.info("No jobs match these filters. Try source-record view or remove a filter.")
        return
    display = []
    for item in result.items:
        row = job_row(item)
        row["job_id"] = item.job_id
        display.append(row)
    edited = st.data_editor(
        display,
        use_container_width=True,
        hide_index=True,
        disabled=[
            "Posted / First Seen", "Title", "Company", "City", "Source",
            "Match Type", "Rank Score", "Fit Score", "Application Status",
        ],
        column_config={
            "Select": st.column_config.CheckboxColumn(required=True),
            "job_id": None,
        },
        key="review_jobs_table",
    )
    options = [item.job_id for item in result.items]
    selected = st.selectbox(
        "Selected job",
        options,
        index=options.index(_selected_job_id()) if _selected_job_id() in options else 0,
        format_func=lambda value: _job_option_label(result.items, value),
    )
    action_columns = st.columns(3)
    if action_columns[0].button("Open Job Detail", type="primary"):
        _set_selected_job(selected)
        st.success("Selected. Open Job Detail from the navigation.")
    selected_rows = [row["job_id"] for row in edited if row.get("Select")]
    if action_columns[1].button("Add selected to Review Tray"):
        if not _profile_id():
            st.warning("Select a candidate profile before adding jobs to the Review Tray.")
        elif not selected_rows:
            st.warning("Tick one or more jobs first.")
        else:
            try:
                result_rows = execute_once(
                    f"review-tray:{_profile_id()}:{','.join(selected_rows)}",
                    lambda: context.actions.add_to_review_tray(selected_rows, _profile_id()),
                )
                if result_rows is not None:
                    st.success(f"Added {len(result_rows)} job(s) to the Review Tray.")
            except Exception as error:
                safe_error(error)
    if action_columns[2].button("Set selected job"):
        _set_selected_job(selected)
        st.success("Selected job is shared with Job Detail and CV Workflow.")


def review_tray_page() -> None:
    context = runtime()
    page_header(
        "Review Tray",
        "Your working list for jobs worth a closer look before CV generation and manual application.",
        eyebrow="Next actions",
    )
    profile_id = _profile_id()
    if not profile_id:
        st.info("Select a candidate profile before using the Review Tray.")
        return
    tray = context.queries.applications(profile_id, ApplicationStatus.SHORTLISTED.value)
    if not tray:
        st.info("Your Review Tray is empty. Add jobs from Review Jobs.")
        return
    st.dataframe([tray_row(item) for item in tray], use_container_width=True, hide_index=True)
    selected_application_id = st.selectbox(
        "Tray job",
        [str(item["id"]) for item in tray],
        format_func=lambda value: next(
            f"{item['title_raw']} | {item.get('company_raw') or 'Unknown company'} | "
            f"{parse_city(item.get('location_raw'))}"
            for item in tray if str(item["id"]) == value
        ),
    )
    selected_application = next(
        item for item in tray if str(item["id"]) == selected_application_id
    )
    selected_job = str(selected_application["job_id"])
    _set_selected_job(selected_job)
    st.caption("Selected job is shared with Job Detail, CV Workflow, and command sections.")
    commands = {
        "Generate CV": (
            f"python -m app.cli cv generate --job-id {selected_job} "
            f"--profile-id {profile_id}"
        ),
        "Create Prep Pack": context.queries.prep_pack_command(profile_id, selected_job),
        "Create Application Pack": context.queries.application_pack_command(
            profile_id,
            selected_job,
            selected_application.get("cv_artifact_id")
            or selected_application.get("latest_cv_artifact_id"),
        ),
    }
    command_tab, action_tab = st.tabs(["Commands", "Application Actions"])
    with command_tab:
        for label, command in commands.items():
            st.markdown(f"**{label}**")
            st.code(command, language="powershell")
        st.caption("Commands are local-only. The dashboard does not apply, send, or call AI automatically.")
    with action_tab:
        note = st.text_input("Action note", key="review-tray-action-note")
        follow_up = st.date_input(
            "Follow-up date",
            value=default_follow_up_date(),
            key="review-tray-follow-up",
        )
        confirmed = st.checkbox("Confirm selected Review Tray action")
        columns = st.columns(4)
        if columns[0].button("Open Job Detail", type="primary"):
            _set_selected_job(selected_job)
            st.success("Selected. Open Job Detail from the navigation.")
        if columns[1].button("Remove from Tray / Skip"):
            if not confirmed:
                st.warning("Confirm before removing this job from the Review Tray.")
            else:
                try:
                    result = execute_once(
                        f"review-tray-skip:{selected_application_id}",
                        lambda: context.actions.set_application_status(
                            selected_job,
                            profile_id,
                            ApplicationStatus.SKIPPED.value,
                            note=note or "Removed from Review Tray",
                        ),
                    )
                    if result:
                        st.success("Job removed from the Review Tray.")
                except Exception as error:
                    safe_error(error)
        if columns[2].button("Mark Applied"):
            if not confirmed:
                st.warning("Confirm after you have manually applied on the external website.")
            else:
                try:
                    result = execute_once(
                        f"review-tray-applied:{selected_job}:{follow_up.isoformat()}",
                        lambda: context.actions.submit_manual_application(
                            selected_job,
                            profile_id,
                            note=note or "Marked applied from Review Tray",
                            follow_up_date=follow_up.isoformat(),
                        ),
                    )
                    if result:
                        st.success("Application marked applied and follow-up saved.")
                except Exception as error:
                    safe_error(error)
        if columns[3].button("Set Follow-up"):
            if not confirmed:
                st.warning("Confirm before changing the follow-up date.")
            else:
                try:
                    result = execute_once(
                        f"review-tray-follow-up:{selected_application_id}:{follow_up.isoformat()}",
                        lambda: context.actions.set_application_follow_up(
                            selected_application_id,
                            follow_up.isoformat(),
                            note=note or None,
                        ),
                    )
                    if result:
                        st.success("Follow-up saved.")
                except Exception as error:
                    safe_error(error)


def _render_job_detail_action_center(context) -> None:
    candidates = context.queries.jobs(
        JobFilters(logical_only=False, page_size=100), _profile_id()
    ).items
    if not candidates:
        st.info("No stored jobs are available.")
        return
    options = [item.job_id for item in candidates]
    current = _selected_job_id()
    selected = st.selectbox(
        "Job",
        options,
        index=options.index(current) if current in options else 0,
        format_func=lambda value: _job_option_label(candidates, value),
        key="job_detail_selector",
    )
    _set_selected_job(selected)
    try:
        detail = context.queries.job_detail(selected, _profile_id())
    except Exception as error:
        safe_error(error)
        return
    job = detail.job
    analysis = detail.analysis or {}
    ranking = detail.ranking or {}
    applications = detail.applications
    current_status = str(applications[0]["current_status"]) if applications else ""
    title = str(job.get("title_raw") or "Untitled job")
    company = str(job.get("company_raw") or "Unknown company")
    city = parse_city(job.get("location_raw"))
    st.subheader(title)
    st.caption(f"{company} | {city or 'Location not supplied'} | {job['source']}")
    top = st.columns(6)
    top[0].metric(
        "Posted / First Seen",
        posted_or_first_seen_display(
            job.get("published_at"), job.get("first_seen_at"), job.get("created_at")
        ),
    )
    top[1].metric("Match Type", match_type_label(analysis.get("authority")))
    top[2].metric("Rank Score", ranking.get("rank_score") or "")
    top[3].metric(
        "Fit Score",
        fit_score_label(analysis.get("authority"), analysis.get("fit_score")),
    )
    top[4].metric("Application Status", current_status or "Not tracked")
    top[5].metric("Source", str(job["source"]))
    link = job.get("canonical_url") or job.get("source_url")
    if link:
        st.link_button("Open original vacancy", str(link))
    compatibility, description_tab, cv_tab, application_tab, advanced = st.tabs([
        "Compatibility / Why this job",
        "Job Description",
        "CV Actions",
        "Application Actions",
        "Advanced Details",
    ])
    with compatibility:
        if analysis:
            st.json({
                "authority": analysis.get("authority"),
                "fit_score": analysis.get("fit_score"),
                "prefilter_score": analysis.get("prefilter_score"),
                "requirements": analysis.get("requirements"),
                "evidence": analysis.get("evidence"),
                "missing_skills": analysis.get("missing_skills"),
                "risk_flags": analysis.get("risk_flags"),
            })
        else:
            st.info("No analysis exists for the selected profile and job.")
            if _profile_id() and st.button("Run deterministic analysis"):
                try:
                    result = execute_once(
                        f"analysis:{selected}:{_profile_id()}",
                        lambda: context.actions.analyze_job(selected, _profile_id()),
                    )
                    if result:
                        st.success("Analysis complete. Refresh the page to inspect it.")
                except Exception as error:
                    safe_error(error)
        if ranking:
            st.markdown("**Latest ranking**")
            st.json(ranking)
    with description_tab:
        if detail.description:
            st.caption(f"Completeness: {detail.description['completeness']}")
            st.text_area(
                "Stored description",
                detail.description.get("raw_text") or "No description text stored.",
                height=360,
                disabled=True,
            )
        else:
            st.info("No description version is stored. Use manual JD in CV Workflow.")
    with cv_tab:
        profile_id = _profile_id()
        if not profile_id:
            st.info("Select a candidate profile to generate CV commands.")
        else:
            st.markdown("**Generate CV**")
            st.code(
                f"python -m app.cli cv generate --job-id {selected} --profile-id {profile_id}",
                language="powershell",
            )
            st.markdown("**Optional AI polish, explicit live AI only**")
            st.code(
                "python -m app.cli cv generate "
                f"--job-id {selected} --profile-id {profile_id} "
                "--force-regenerate --ai-polish --live-ai",
                language="powershell",
            )
            if st.button("Generate local rule-based CV"):
                try:
                    result = execute_once(
                        f"job-detail-cv:{selected}:{profile_id}",
                        lambda: context.actions.generate_cv(selected, profile_id),
                    )
                    if result:
                        st.session_state["last_cv_result"] = _cv_result(result)
                        st.success("Rule-based CV generated locally.")
                except Exception as error:
                    safe_error(error)
        if detail.cv_artifacts:
            st.markdown("**Latest CV artifacts**")
            st.dataframe(detail.cv_artifacts, use_container_width=True, hide_index=True)
        else:
            st.info("No CV artifacts are linked to this vacancy.")
    with application_tab:
        profile_id = _profile_id()
        if not profile_id:
            st.info("Select a candidate profile before application actions.")
        else:
            selected_cv = _selected_cv_artifact_id(detail)
            st.markdown("**Local preparation commands**")
            st.code(context.queries.prep_pack_command(profile_id, selected, selected_cv), language="powershell")
            st.code(context.queries.application_pack_command(profile_id, selected, selected_cv), language="powershell")
            for row in context.queries.communication_draft_commands(profile_id, selected):
                st.code(row["command"], language="powershell")
            st.caption("These commands create local files only. They do not apply, upload, send, or call AI.")
            note = st.text_input("Application action note", key="job-detail-action-note")
            follow_up = st.date_input(
                "Follow-up date",
                value=default_follow_up_date(),
                key="job-detail-follow-up",
            )
            confirmed = st.checkbox("Confirm selected application action")
            actions = st.columns(4)
            if actions[0].button("Add to Review Tray", type="primary"):
                try:
                    result = execute_once(
                        f"job-detail-review-tray:{selected}:{profile_id}",
                        lambda: context.actions.add_to_review_tray([selected], profile_id),
                    )
                    if result:
                        st.success("Added to Review Tray.")
                except Exception as error:
                    safe_error(error)
            if actions[1].button("Create Prep Pack"):
                if not confirmed:
                    st.warning("Confirm before creating a local prep pack.")
                else:
                    try:
                        result = execute_once(
                            f"job-detail-prep:{selected}:{profile_id}:{selected_cv}",
                            lambda: context.actions.create_prep_pack(
                                selected, profile_id, cv_artifact_id=selected_cv
                            ),
                        )
                        if result:
                            st.success("Prep pack created locally.")
                    except Exception as error:
                        safe_error(error)
            if actions[2].button("Create Application Pack"):
                if not confirmed:
                    st.warning("Confirm before creating a local application pack.")
                else:
                    try:
                        result = execute_once(
                            f"job-detail-application-pack:{selected}:{profile_id}:{selected_cv}",
                            lambda: context.actions.create_application_pack(
                                selected, profile_id, cv_artifact_id=selected_cv
                            ),
                        )
                        if result:
                            st.success("Application pack created locally.")
                    except Exception as error:
                        safe_error(error)
            if actions[3].button("Mark Applied"):
                if not confirmed:
                    st.warning("Confirm only after you manually applied externally.")
                else:
                    try:
                        result = execute_once(
                            f"job-detail-applied:{selected}:{profile_id}:{follow_up.isoformat()}",
                            lambda: context.actions.submit_manual_application(
                                selected,
                                profile_id,
                                note=note or "Marked applied from dashboard",
                                follow_up_date=follow_up.isoformat(),
                            ),
                        )
                        if result:
                            st.success("Marked applied and follow-up saved.")
                    except Exception as error:
                        safe_error(error)
            if detail.applications:
                st.markdown("**Application record**")
                st.dataframe(detail.applications, use_container_width=True, hide_index=True)
                st.markdown("**Immutable history**")
                st.dataframe(detail.application_history, use_container_width=True, hide_index=True)
    with advanced:
        safe_fields = {
            key: job.get(key) for key in (
                "id", "source", "source_job_id", "published_at", "expires_at",
                "employment_type", "language_detected", "language_confidence",
                "explicit_german_requirement", "first_seen_at", "last_seen_at",
                "created_at", "active",
            )
        }
        st.markdown("**Source metadata and technical IDs**")
        st.json(safe_fields)
        if detail.cluster:
            st.markdown("**Duplicate provenance**")
            st.json(detail.cluster)
            st.dataframe(detail.cluster_members, use_container_width=True, hide_index=True)
        if detail.notifications:
            st.markdown("**Notification history**")
            st.dataframe(detail.notifications, use_container_width=True, hide_index=True)


def job_detail_page() -> None:
    context = runtime()
    page_header(
        "Job Detail",
        "A practical action center for one selected vacancy.",
        eyebrow="Decision record",
    )
    _render_job_detail_action_center(context)
    return
    candidates = context.queries.jobs(
        JobFilters(logical_only=False, page_size=100), _profile_id()
    ).items
    if not candidates:
        st.info("No stored jobs are available.")
        return
    options = [item.job_id for item in candidates]
    current = st.session_state.get("selected_job_id")
    index = options.index(current) if current in options else 0
    selected = st.selectbox(
        "Job", options, index=index,
        format_func=lambda value: next(
            f"{item.title} | {item.company or 'Unknown company'} | {item.source}"
            for item in candidates if item.job_id == value
        ),
        key="job_detail_selector",
    )
    st.session_state["selected_job_id"] = selected
    try:
        detail = context.queries.job_detail(selected, _profile_id())
    except Exception as error:
        safe_error(error)
        return
    job = detail.job
    st.subheader(str(job["title_raw"]))
    st.caption(
        f"{job.get('company_raw') or 'Unknown company'} | "
        f"{job.get('location_raw') or 'Location not supplied'} | {job['source']}"
    )
    link = job.get("canonical_url") or job.get("source_url")
    if link:
        st.link_button("Open original vacancy", str(link))
    else:
        st.info("This source record has no stored external link.")
    metadata, description_tab, cluster_tab, analysis_tab = st.tabs(
        ["Source metadata", "Description", "Duplicate provenance", "Fit and ranking"]
    )
    with metadata:
        safe_fields = {
            key: job.get(key) for key in (
                "id", "source", "source_job_id", "published_at", "expires_at",
                "employment_type", "language_detected", "language_confidence",
                "explicit_german_requirement", "first_seen_at", "last_seen_at", "active",
            )
        }
        st.json(safe_fields)
    with description_tab:
        if detail.description:
            st.caption(f"Completeness: {detail.description['completeness']}")
            st.text_area(
                "Stored description",
                detail.description.get("raw_text") or "No description text stored.",
                height=360, disabled=True,
            )
        else:
            st.info("No description version is stored. Use manual JD in CV Builder.")
    with cluster_tab:
        if detail.cluster:
            st.caption(f"Cluster: {detail.cluster['cluster_id']}")
            st.dataframe(detail.cluster_members, use_container_width=True, hide_index=True)
            if len(detail.cluster_members) > 1:
                with st.expander("Split one source record"):
                    split_id = st.selectbox(
                        "Source record", [str(item["id"]) for item in detail.cluster_members]
                    )
                    confirmation = st.text_input("Type the exact job ID to confirm")
                    if st.button("Split source record"):
                        try:
                            result = execute_once(
                                f"split:{split_id}:{confirmation}",
                                lambda: context.actions.split_duplicate(
                                    split_id, confirmation=confirmation
                                ),
                            )
                            if result:
                                st.success(f"Created cluster {result}")
                        except Exception as error:
                            safe_error(error)
        else:
            st.info("This job has no current duplicate-cluster link.")
    with analysis_tab:
        if detail.analysis:
            a, b, c = st.columns(3)
            a.metric("Authority", detail.analysis.get("authority"))
            b.metric("Fit score", detail.analysis.get("fit_score") or "Not authoritative")
            c.metric("Prefilter", detail.analysis.get("prefilter_score") or "None")
            st.markdown("**Evidence and requirements**")
            st.json({
                "requirements": detail.analysis.get("requirements"),
                "evidence": detail.analysis.get("evidence"),
                "missing_skills": detail.analysis.get("missing_skills"),
                "risk_flags": detail.analysis.get("risk_flags"),
                "penalties": detail.analysis.get("penalties"),
                "score_caps": detail.analysis.get("score_caps"),
            })
        else:
            st.info("No analysis exists for the selected profile and cluster.")
            if _profile_id() and st.button("Run deterministic analysis"):
                try:
                    execute_once(
                        f"analysis:{selected}:{_profile_id()}",
                        lambda: context.actions.analyze_job(selected, _profile_id()),
                    )
                    st.success("Analysis complete. Refresh the page to inspect it.")
                except Exception as error:
                    safe_error(error)
        if detail.ranking:
            st.markdown("**Latest ranking**")
            st.json(detail.ranking)

    st.subheader("Application lifecycle")
    if not _profile_id():
        st.info("Select a candidate profile to track this application.")
    elif not detail.applications:
        if st.button("Start tracking this vacancy"):
            try:
                result = execute_once(
                    f"track:{selected}:{_profile_id()}",
                    lambda: context.actions.start_tracking(selected, _profile_id()),
                )
                if result:
                    st.success("Application tracking created.")
            except Exception as error:
                safe_error(error)
    else:
        if len(detail.applications) > 1:
            st.warning("Multiple cluster-member application records exist; no history was merged.")
        st.dataframe(detail.applications, use_container_width=True, hide_index=True)
        st.markdown("**Immutable history**")
        st.dataframe(detail.application_history, use_container_width=True, hide_index=True)
        application = detail.applications[0]
        allowed = context.actions.allowed_transitions(str(application["id"]))
        if allowed:
            with st.form("application_transition"):
                next_status = st.selectbox("Next valid state", allowed)
                reason = st.text_input("Reason or note")
                confirmed = st.checkbox("Confirm this status change")
                submitted = st.form_submit_button("Update application status")
            if submitted:
                if not confirmed:
                    st.warning("Confirm the status change first.")
                else:
                    try:
                        result = execute_once(
                            f"transition:{application['id']}:{next_status}",
                            lambda: context.actions.transition_application(
                                str(application["id"]), next_status, reason=reason or None
                            ),
                        )
                        if result:
                            st.success("Status updated and history appended.")
                    except Exception as error:
                        safe_error(error)
        else:
            st.caption("This application state has no allowed outgoing transition.")

    st.subheader("Notification history")
    if detail.notifications:
        st.dataframe(detail.notifications, use_container_width=True, hide_index=True)
    else:
        st.info("No notification item references this logical vacancy.")
    st.subheader("CV artifact history")
    if detail.cv_artifacts:
        st.dataframe(detail.cv_artifacts, use_container_width=True, hide_index=True)
    else:
        st.info("No CV artifacts are linked to this vacancy.")

    st.subheader("Application prep pack")
    if not _profile_id():
        st.info("Select a candidate profile to see the prep-pack command.")
    else:
        selected_cv = None
        if detail.applications:
            selected_cv = detail.applications[0].get("cv_artifact_id")
        if not selected_cv and detail.cv_artifacts:
            selected_cv = detail.cv_artifacts[0].get("id")
        command = context.queries.prep_pack_command(
            _profile_id(),
            selected,
            selected_cv,
        )
        st.code(command, language="powershell")
        st.caption(
            "Prep packs are local markdown drafts only. The dashboard does not "
            "auto-apply, send messages, or call AI when showing this command."
        )
        packs = context.queries.latest_prep_packs(
            context.settings.data_dir / "prep_packs",
            job_id=selected,
        )
        if packs:
            st.markdown("**Latest local prep packs**")
            st.dataframe(packs, use_container_width=True, hide_index=True)

        st.subheader("Manual application package")
        package_command = context.queries.application_pack_command(
            _profile_id(),
            selected,
            selected_cv,
        )
        st.code(package_command, language="powershell")
        submit_command = context.queries.manual_submit_command(
            _profile_id(),
            selected,
        )
        st.code(submit_command, language="powershell")
        st.caption(
            "Application packages are local files only. Marking an application "
            "as submitted requires running the explicit submit-manual command "
            "after you apply yourself."
        )
        application_packs = context.queries.latest_application_packs(
            context.settings.data_dir / "application_packs",
            job_id=selected,
        )
        if application_packs:
            st.markdown("**Latest local application packages**")
            st.dataframe(application_packs, use_container_width=True, hide_index=True)

        st.subheader("Communication drafts")
        draft_commands = context.queries.communication_draft_commands(
            _profile_id(),
            selected,
        )
        st.dataframe(draft_commands, use_container_width=True, hide_index=True)
        st.caption(
            "Communication drafts are local markdown only. The dashboard does "
            "not send email, Telegram messages, or recruiter communications."
        )
        drafts = context.queries.latest_communication_drafts(
            context.settings.data_dir / "communication_drafts",
            job_id=selected,
        )
        if drafts:
            st.markdown("**Latest local communication drafts**")
            st.dataframe(drafts, use_container_width=True, hide_index=True)


def duplicate_review_page() -> None:
    context = runtime()
    page_header(
        "Duplicate Review",
        "Resolve uncertain cross-source matches without deleting either source record.",
        eyebrow="Human review",
    )
    status = st.selectbox("Review status", ["pending", "approved", "rejected"])
    reviews = context.queries.duplicate_reviews(status)
    if not reviews:
        st.info(f"No {status} duplicate candidates.")
        return
    for review in reviews:
        candidate = review.candidate
        with st.expander(
            f"{review.left_job['title_raw']} <-> {review.right_job['title_raw']} | "
            f"{float(candidate['confidence']):.0%}",
            expanded=status == "pending",
        ):
            left, right = st.columns(2)
            left.markdown("**Left source record**")
            left.json({key: review.left_job.get(key) for key in (
                "id", "source", "title_raw", "company_raw", "location_raw", "published_at"
            )})
            right.markdown("**Right source record**")
            right.json({key: review.right_job.get(key) for key in (
                "id", "source", "title_raw", "company_raw", "location_raw", "published_at"
            )})
            st.markdown("**Matcher reasons**")
            st.write(candidate["reasons"])
            if status == "pending":
                confirmed = st.checkbox(
                    "I reviewed both source records",
                    key=f"confirm-review-{candidate['id']}",
                )
                approve, reject = st.columns(2)
                for column, decision, label in (
                    (approve, "approved", "Approve merge"),
                    (reject, "rejected", "Keep separate"),
                ):
                    if column.button(label, key=f"{decision}-{candidate['id']}"):
                        try:
                            result = execute_once(
                                f"duplicate:{candidate['id']}:{decision}",
                                lambda d=decision: context.actions.review_duplicate(
                                    str(candidate["id"]), d, confirmed=confirmed
                                ),
                            )
                            if result is not None:
                                st.success("Review decision saved transactionally.")
                        except Exception as error:
                            safe_error(error)


def applications_page() -> None:
    context = runtime()
    page_header(
        "Applications",
        "A deliberate lifecycle board. Nothing here submits an application or changes state without confirmation.",
        eyebrow="Pipeline",
    )
    profile_id = _profile_id()
    status = st.selectbox("Status", ["All", *[item.value for item in ApplicationStatus]])
    all_applications = context.queries.applications(profile_id)
    applications = context.queries.applications(
        profile_id, None if status == "All" else status
    )
    counts = {item.value: 0 for item in ApplicationStatus}
    due_followups = 0
    today = datetime.now(UTC).date().isoformat()
    for item in all_applications:
        counts[str(item["status"])] = counts.get(str(item["status"]), 0) + 1
        follow_up = item.get("follow_up_date")
        if (
            follow_up
            and str(follow_up) <= today
            and item["status"] not in {"rejected", "withdrawn", "skipped"}
        ):
            due_followups += 1
    metric_columns = st.columns(4)
    metric_columns[0].metric("Tracked", len(all_applications))
    metric_columns[1].metric("Shortlisted", counts.get("shortlisted", 0))
    metric_columns[2].metric("Applied", counts.get("applied", 0))
    metric_columns[3].metric("Due follow-ups", due_followups)
    if not applications:
        st.info("No tracked applications match this view.")
        return
    table_columns = [
        "current_status", "priority", "title_raw", "company_raw", "location_raw",
        "rank_score", "fit_score", "follow_up_date", "updated_at",
        "notes_preview",
    ]
    st.dataframe(
        [{key: item.get(key) for key in table_columns} for item in applications],
        use_container_width=True,
        hide_index=True,
    )
    selected = st.selectbox(
        "Application",
        [str(item["id"]) for item in applications],
        format_func=lambda value: next(
            f"{item['title_raw']} | {item.get('company_raw') or 'Unknown company'} | {item['status']}"
            for item in applications if str(item["id"]) == value
        ),
    )
    application = next(item for item in applications if str(item["id"]) == selected)
    history = context.queries.job_detail(
        str(application["job_id"]), _profile_id()
    ).application_history
    st.markdown("**Immutable history**")
    st.dataframe(history, use_container_width=True, hide_index=True)
    allowed = context.actions.allowed_transitions(selected)
    if allowed:
        target = st.selectbox("Next valid state", allowed)
        reason = st.text_input("Reason", key="applications-reason")
        confirmed = st.checkbox("Confirm lifecycle change", key="applications-confirm")
        if st.button("Apply valid transition", type="primary"):
            if not confirmed:
                st.warning("Confirm the lifecycle change first.")
            else:
                try:
                    result = execute_once(
                        f"application-board:{selected}:{target}",
                        lambda: context.actions.transition_application(
                            selected, target, reason=reason or None
                        ),
                    )
                    if result:
                        st.success("Application status updated.")
                except Exception as error:
                    safe_error(error)
    st.markdown("**Quick CRM actions**")
    priority = st.selectbox(
        "Priority", ["", "high", "medium", "low"], key="applications-priority"
    )
    quick_note = st.text_input("Action note", key="applications-note")
    follow_up = st.date_input("Follow-up date", key="applications-follow-up")
    action_confirmed = st.checkbox(
        "Confirm application action", key="applications-action-confirm"
    )
    action_columns = st.columns(5)
    quick_actions = (
        ("Shortlist", "shortlisted"),
        ("Skip", "skipped"),
        ("Applied", "applied"),
        ("Rejected", "rejected"),
    )
    for column, (label, next_status) in zip(action_columns[:4], quick_actions):
        if column.button(label):
            if not action_confirmed:
                st.warning("Confirm the application action first.")
            else:
                try:
                    if next_status == "shortlisted":
                        result = execute_once(
                            f"application-shortlist:{selected}",
                            lambda: context.actions.shortlist_application(
                                str(application["job_id"]),
                                profile_id,
                                priority=priority or None,
                                note=quick_note or None,
                            ),
                        )
                    else:
                        result = execute_once(
                            f"application-status:{selected}:{next_status}",
                            lambda s=next_status: context.actions.set_application_status(
                                str(application["job_id"]),
                                profile_id,
                                s,
                                note=quick_note or None,
                            ),
                        )
                    if result:
                        st.success("Application updated.")
                except Exception as error:
                    safe_error(error)
    if action_columns[4].button("Set follow-up"):
        if not action_confirmed:
            st.warning("Confirm the application action first.")
        else:
            try:
                result = execute_once(
                    f"application-follow-up:{selected}:{follow_up.isoformat()}",
                    lambda: context.actions.set_application_follow_up(
                        selected,
                        follow_up.isoformat(),
                        note=quick_note or None,
                    ),
                )
                if result:
                    st.success("Follow-up saved.")
            except Exception as error:
                safe_error(error)
    if st.button("Add note"):
        if not action_confirmed:
            st.warning("Confirm the application action first.")
        else:
            try:
                result = execute_once(
                    f"application-note:{selected}:{quick_note}",
                    lambda: context.actions.add_application_note(selected, quick_note),
                )
                if result:
                    st.success("Note saved.")
            except Exception as error:
                safe_error(error)


def cv_builder_page() -> None:
    context = runtime()
    page_header(
        "CV Workflow",
        "Generate, review, copy, and attach deterministic FlowCV artifacts without automatic submission.",
        eyebrow="Application preparation",
    )
    profile_id = _profile_id()
    if not profile_id:
        st.info("Import and select a candidate profile before generating a CV.")
        return
    profile = context.queries.profile_detail(profile_id)
    with st.expander("Inspect selected candidate profile"):
        st.json({
            "id": profile["id"], "profile_key": profile["profile_key"],
            "version": profile["version"], "display_name": profile["display_name"],
            "active": profile["active"], "profile_data": profile["profile_data"],
        })
    ai_requested = st.checkbox("Request optional API AI polish", value=False)
    live_ai = st.checkbox(
        "I understand this sends CV text to an external AI API",
        value=False, disabled=not ai_requested,
    )
    if context.settings.ai_provider == "rule_based":
        st.caption("AI_PROVIDER=rule_based. Rule-based generation remains fully available.")
    stored_tab, manual_tab = st.tabs(["Stored full-description job", "Manual JD fallback"])
    with stored_tab:
        jobs = context.queries.jobs(
            JobFilters(completeness="full", logical_only=True, page_size=100),
            profile_id,
        ).items
        if not jobs:
            st.info("No logical vacancy currently has a full stored description.")
        else:
            selected = st.selectbox(
                "Stored job",
                [item.job_id for item in jobs],
                index=(
                    [item.job_id for item in jobs].index(_selected_job_id())
                    if _selected_job_id() in [item.job_id for item in jobs]
                    else 0
                ),
                format_func=lambda value: next(
                    f"{item.title} | {item.company or 'Unknown company'}"
                    for item in jobs if item.job_id == value
                ),
            )
            _set_selected_job(selected)
            if st.button("Generate authoritative CV", type="primary"):
                try:
                    result = execute_once(
                        f"cv:{selected}:{profile_id}:{ai_requested}:{live_ai}",
                        lambda: context.actions.generate_cv(
                            selected, profile_id,
                            ai_polish=ai_requested,
                            live_ai_confirmed=live_ai,
                        ),
                    )
                    if result:
                        st.session_state["last_cv_result"] = _cv_result(result)
                except Exception as error:
                    safe_error(error)
    with manual_tab:
        upload = st.file_uploader("Upload UTF-8 job description", type=["txt", "md"])
        if upload is not None:
            if upload.size > context.settings.cv_manual_max_bytes:
                st.error("The file exceeds CV_MANUAL_MAX_BYTES.")
            elif st.button("Generate from manual JD"):
                try:
                    text = upload.getvalue().decode("utf-8-sig")
                    result = execute_once(
                        f"manual-cv:{profile_id}:{hash(text)}:{ai_requested}:{live_ai}",
                        lambda: context.actions.generate_manual_cv(
                            text, profile_id,
                            ai_polish=ai_requested,
                            live_ai_confirmed=live_ai,
                        ),
                    )
                    if result:
                        st.session_state["last_cv_result"] = _cv_result(result)
                except UnicodeDecodeError:
                    st.error("Manual JD must use UTF-8 text encoding.")
                except Exception as error:
                    safe_error(error)
    result = st.session_state.get("last_cv_result")
    if result:
        st.subheader("Latest generation result")
        st.json(result)
        if result.get("job_id"):
            st.markdown("**Suggested next steps**")
            st.code(
                f"python -m app.cli prep pack --job-id {result['job_id']} "
                f"--profile-id {result['profile_id']} --cv-artifact-id {result['artifact_id']}",
                language="powershell",
            )
            st.code(
                f"python -m app.cli application-pack create --job-id {result['job_id']} "
                f"--profile-id {result['profile_id']} --cv-artifact-id {result['artifact_id']}",
                language="powershell",
            )
        st.markdown(
            '<div class="status-note"><strong>Private evidence report:</strong> '
            "Use it for verification only; it is not recruiter-facing content.</div>",
            unsafe_allow_html=True,
        )
    st.subheader("Generated CV artifacts")
    artifacts = context.queries.list_cv_artifacts(profile_id)
    if not artifacts:
        st.info("No CV artifacts are stored for the selected profile yet.")
        return
    artifact_columns = [
        "artifact_id", "title_raw", "company_raw", "location_raw",
        "generation_mode", "source", "formatter_version",
        "builder_content_version", "validated", "parent_rule_based_artifact_id",
        "provider", "model", "ai_status", "application_status",
        "attached_cv_artifact_id", "created_at",
    ]
    st.dataframe(
        [{key: item.get(key) for key in artifact_columns} for item in artifacts],
        use_container_width=True,
        hide_index=True,
    )
    selected_artifact = st.selectbox(
        "CV artifact",
        [str(item["artifact_id"]) for item in artifacts],
        format_func=lambda value: next(
            f"{item.get('title_raw') or 'Manual JD'} | {item['source']} | {value}"
            for item in artifacts if str(item["artifact_id"]) == value
        ),
    )
    artifact = context.queries.get_cv_artifact_detail(selected_artifact)
    with st.expander("Artifact metadata", expanded=True):
        st.json(artifact)
    show_text = st.checkbox("Show FlowCV TXT content", key="cv-workflow-show-text")
    if show_text:
        payload = context.queries.read_cv_artifact_text(selected_artifact)
        if payload["found"]:
            st.text_area(
                "FlowCV TXT",
                payload["text"],
                height=420,
                key=f"cv-text-{selected_artifact}",
            )
        else:
            st.warning(payload["message"])
            st.caption(payload["path"])
    show_evidence = st.checkbox(
        "Show private evidence report",
        key="cv-workflow-show-evidence",
        help="Evidence reports are for verification only, not recruiter-facing copy.",
    )
    if show_evidence:
        payload = context.queries.read_evidence_report_text(selected_artifact)
        if payload["found"]:
            st.text_area(
                "Private evidence report",
                payload["text"],
                height=420,
                key=f"cv-evidence-{selected_artifact}",
            )
        else:
            st.warning(payload["message"])
            st.caption(payload["path"])
    if artifact.get("job_id"):
        st.markdown("**Attach to application**")
        applications = [
            item for item in context.queries.list_applications_with_cv_context(profile_id)
            if str(item.get("job_id")) == str(artifact["job_id"])
            or (
                item.get("logical_cluster_id")
                and item.get("logical_cluster_id") == artifact.get("logical_cluster_id")
            )
        ]
        if not applications:
            st.info("Track this job as an application before attaching a CV.")
        else:
            selected_application = st.selectbox(
                "Tracked application",
                [str(item["id"]) for item in applications],
                format_func=lambda value: next(
                    f"{item['title_raw']} | {item['current_status']} | {value}"
                    for item in applications if str(item["id"]) == value
                ),
                key="cv-workflow-application",
            )
            application = next(
                item for item in applications if str(item["id"]) == selected_application
            )
            note = st.text_input(
                "Attach note",
                value="CV reviewed in dashboard",
                key="cv-workflow-attach-note",
            )
            confirmed = st.checkbox(
                "Confirm Attach CV / Mark CV Ready",
                key="cv-workflow-attach-confirm",
            )
            if st.button("Attach CV / Mark CV Ready", type="primary"):
                if not confirmed:
                    st.warning("Confirm the CV attachment first.")
                else:
                    try:
                        result = execute_once(
                            f"cv-attach:{selected_application}:{selected_artifact}",
                            lambda: context.actions.attach_cv_artifact(
                                str(application["job_id"]),
                                profile_id,
                                selected_artifact,
                                note=note or None,
                            ),
                        )
                        if result:
                            st.success("CV attached and application marked cv_ready.")
                    except Exception as error:
                        safe_error(error)
    else:
        st.info("Manual-JD artifacts are not linked to a stored job application.")


def _cv_result(result):
    artifact = result.rule_based_artifact
    return {
        "artifact_id": str(artifact.id),
        "authoritative_artifact_path": str(artifact.artifact_path),
        "private_evidence_report_path": str(artifact.evidence_report_path),
        "validated": artifact.validated,
        "cache_reused": result.cache_hit,
        "job_id": str(artifact.job_id) if artifact.job_id else None,
        "profile_id": str(artifact.profile_id),
        "profile_version": artifact.profile_version,
        "analysis_id": str(artifact.analysis_id) if artifact.analysis_id else None,
        "ai_status": result.ai_status,
        "ai_failure_category": result.ai_failure_category,
    }


def notifications_page() -> None:
    context = runtime()
    page_header(
        "Notifications",
        "Preview is offline. Delivery is isolated behind configuration, typed confirmation, and an explicit click.",
        eyebrow="Telegram audit",
    )
    profile_id = _profile_id()
    if not profile_id:
        st.info("Select a candidate profile to preview ranked vacancies.")
        return
    if st.button("Build offline Telegram preview", type="primary"):
        try:
            preview = context.actions.notification_preview(profile_id)
            st.session_state["notification_preview"] = {
                "selected_count": preview.selected_count,
                "chunks": [
                    {"index": chunk.index, "characters": len(chunk.text), "text": chunk.text}
                    for chunk in preview.chunks
                ],
            }
        except Exception as error:
            safe_error(error)
    preview = st.session_state.get("notification_preview")
    if preview:
        st.metric("Selected logical vacancies", preview["selected_count"])
        for chunk in preview["chunks"]:
            with st.expander(
                f"Preview chunk {chunk['index']} | {chunk['characters']} characters"
            ):
                st.text(chunk["text"])

    batches = context.actions.notification_batches(profile_id)
    st.subheader("Notification history")
    if batches:
        st.dataframe(
            [item.model_dump(mode="json") for item in batches],
            use_container_width=True, hide_index=True,
        )
        selected_batch = st.selectbox("Batch details", [str(item.id) for item in batches])
        batch, items, deliveries = context.actions.notification_batch_details(selected_batch)
        st.json({
            "batch": batch.model_dump(mode="json"),
            "items": [item.model_dump(mode="json") for item in items],
            "deliveries": [item.model_dump(mode="json") for item in deliveries],
        })
    else:
        st.info("No Telegram batches have been created.")

    with st.expander("Live Telegram controls"):
        if not context.settings.telegram_enabled:
            st.warning("Disabled: TELEGRAM_ENABLED=false. No client has been created.")
        else:
            confirmation = st.text_input("Type SEND TELEGRAM to enable delivery")
            acknowledged = st.checkbox("I understand this sends a real Telegram message")
            if st.button("Send ranked vacancies live", disabled=not acknowledged):
                try:
                    result = execute_once(
                        f"telegram-send:{profile_id}:{confirmation}",
                        lambda: context.actions.send_notifications(
                            profile_id, confirmation=confirmation
                        ),
                    )
                    if result:
                        st.success("Live delivery attempt completed; inspect batch history.")
                except Exception as error:
                    safe_error(error)
            if batches and st.button("Retry failed chunks", disabled=not acknowledged):
                try:
                    result = execute_once(
                        f"telegram-retry:{selected_batch}:{confirmation}",
                        lambda: context.actions.retry_notifications(
                            selected_batch, confirmation=confirmation
                        ),
                    )
                    if result:
                        st.success("Retry completed; successful chunks were not resent.")
                except Exception as error:
                    safe_error(error)


def runs_page() -> None:
    context = runtime()
    page_header(
        "Runs & Diagnostics",
        "Operational facts without raw payloads, document text, provider responses, or credentials.",
        eyebrow="Safe diagnostics",
    )
    runs = cached_runs(
        str(context.database.path), context.database.busy_timeout_ms, 100
    )
    st.subheader("Collection runs")
    if runs:
        st.dataframe(runs, use_container_width=True, hide_index=True)
    else:
        st.info("No collection runs are stored. Browsing this page never starts one.")
    st.subheader("Daily Runs")
    daily_runs = cached_daily_runs(
        str(context.settings.repo_root / "data" / "daily_runs"),
        20,
    )
    if daily_runs:
        st.dataframe(daily_runs, use_container_width=True, hide_index=True)
    else:
        st.info("No daily-run summaries are stored. Browsing this page never starts one.")
    st.subheader("Database status")
    diagnostics = context.queries.diagnostics()
    a, b = st.columns(2)
    a.metric("Applied migration", max(
        (item["version"] for item in diagnostics["migrations"]), default=0
    ))
    b.metric("Foreign-key issues", diagnostics["foreign_key_issues"])
    st.caption(f"Database file: {diagnostics['database_name']}")
    st.dataframe(diagnostics["migrations"], use_container_width=True, hide_index=True)
    st.json(diagnostics["counts"])
