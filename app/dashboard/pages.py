"""Streamlit page renderers kept intentionally thin."""

from __future__ import annotations

from datetime import UTC, datetime
from dataclasses import asdict

import streamlit as st

from app.dashboard.actions import ConfirmationRequired
from app.dashboard.components import (
    execute_once,
    page_header,
    safe_error,
    table_rows,
)
from app.dashboard.runtime import (
    cached_jobs,
    cached_overview,
    cached_runs,
    runtime,
)
from app.dashboard.view_models import JobFilters
from app.domain.enums import ApplicationStatus, DescriptionCompleteness, JobSource


def _profile_id() -> str | None:
    return st.session_state.get("dashboard_profile_id")


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


def jobs_page() -> None:
    context = runtime()
    page_header(
        "Jobs",
        "Search the representative vacancy by default, or deliberately inspect every source record.",
        eyebrow="Vacancy library",
    )
    with st.expander("Filters and ordering", expanded=True):
        first, second, third, fourth = st.columns(4)
        search = first.text_input("Title, company, or location")
        source = second.selectbox(
            "Source", ["All", *[item.value for item in JobSource]]
        )
        completeness = third.selectbox(
            "Description", ["All", *[item.value for item in DescriptionCompleteness]]
        )
        application_status = fourth.selectbox(
            "Application state", ["All", *[item.value for item in ApplicationStatus]]
        )
        fifth, sixth, seventh, eighth = st.columns(4)
        authority = fifth.selectbox("Fit authority", ["All", "authoritative", "prefilter_only"])
        language = sixth.selectbox("Detected language", ["All", "en", "de", "unknown"])
        logical_only = seventh.toggle("One row per logical vacancy", value=True)
        sort_by = eighth.selectbox(
            "Sort by", ["rank_score", "fit_score", "published_at", "last_seen_at", "title", "company"]
        )
        descending = st.toggle("Descending", value=True)
        score_filter = st.toggle("Apply score ranges", value=False)
        if score_filter:
            fit_range = st.slider("Fit score", 0.0, 100.0, (0.0, 100.0))
            rank_range = st.slider("Rank score", 0.0, 120.0, (0.0, 120.0))
        else:
            fit_range = rank_range = (None, None)

    page = int(st.number_input("Page", min_value=1, value=1, step=1))
    filters = JobFilters(
        search=search, source=None if source == "All" else source,
        completeness=None if completeness == "All" else completeness,
        language=None if language == "All" else language,
        application_status=None if application_status == "All" else application_status,
        authority=None if authority == "All" else authority,
        fit_min=fit_range[0], fit_max=fit_range[1],
        rank_min=rank_range[0], rank_max=rank_range[1],
        logical_only=logical_only, sort_by=sort_by,
        descending=descending, page=page,
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
        row = asdict(item)
        row["application_statuses"] = ", ".join(item.application_statuses)
        display.append(row)
    st.dataframe(display, use_container_width=True, hide_index=True)
    options = [item.job_id for item in result.items]
    selected = st.selectbox(
        "Select a job for Job Detail",
        options,
        format_func=lambda value: next(
            f"{item.title} | {item.company or 'Unknown company'} | {item.source}"
            for item in result.items if item.job_id == value
        ),
    )
    if st.button("Set as selected job", type="primary"):
        st.session_state["selected_job_id"] = selected
        st.success("Selected. Open Job Detail from the navigation.")


def job_detail_page() -> None:
    context = runtime()
    page_header(
        "Job Detail",
        "The complete evidence trail for one vacancy, from source record to application and CV history.",
        eyebrow="Decision record",
    )
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
    ai_requested = st.checkbox("Request optional Ollama polish", value=False)
    live_ai = st.checkbox(
        "I understand this makes an explicit live AI request",
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
                format_func=lambda value: next(
                    f"{item.title} | {item.company or 'Unknown company'}"
                    for item in jobs if item.job_id == value
                ),
            )
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
        "builder_content_version", "validated", "application_status",
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
