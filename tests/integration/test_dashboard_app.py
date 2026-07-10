from __future__ import annotations

import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest
import requests

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from app.config import _reset_settings_cache_for_tests, settings_from_mapping
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
from app.db.connection import Database
from app.db.migrations import migrate
from tests.notification_helpers import seed_ranked_vacancies


ROOT = Path(__file__).parents[2]
APP = ROOT / "app" / "dashboard" / "Home.py"


def _unused_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
        listener.bind(("127.0.0.1", 0))
        return listener.getsockname()[1]


def _offline_environment(tmp_path: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update({
        "JOBHUNT_DATABASE_PATH": str(tmp_path / "dashboard.sqlite3"),
        "FIT_RULES_PATH": str(ROOT / "config" / "fit_rules.json"),
        "DEDUP_COMPANY_ALIASES_PATH": str(ROOT / "config" / "company_aliases.json"),
        "TELEGRAM_ENABLED": "false",
        "TELEGRAM_BOT_TOKEN": "",
        "TELEGRAM_CHAT_ID": "",
        "AI_ENABLED": "false",
        "AI_PROVIDER": "rule_based",
        "AI_API_KEY": "",
        "PYTHONUNBUFFERED": "1",
    })
    return environment


def _run(monkeypatch, tmp_path):
    monkeypatch.setenv("JOBHUNT_DATABASE_PATH", str(tmp_path / "dashboard.sqlite3"))
    monkeypatch.setenv("FIT_RULES_PATH", str(ROOT / "config" / "fit_rules.json"))
    monkeypatch.setenv(
        "DEDUP_COMPANY_ALIASES_PATH", str(ROOT / "config" / "company_aliases.json")
    )
    monkeypatch.setenv("TELEGRAM_ENABLED", "false")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "")
    monkeypatch.setenv("AI_ENABLED", "false")
    monkeypatch.setenv("AI_PROVIDER", "rule_based")
    monkeypatch.setenv("AI_API_KEY", "")
    _reset_settings_cache_for_tests()
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    return app


def test_empty_database_starts_without_credentials_or_exceptions(monkeypatch, tmp_path) -> None:
    app = _run(monkeypatch, tmp_path)
    assert not app.exception
    assert app.title[0].value == "Overview"
    assert any("No collection runs" in item.value for item in app.info)
    assert (tmp_path / "dashboard.sqlite3").exists()


def test_absolute_home_path_starts_streamlit_without_import_shadowing(tmp_path) -> None:
    port = _unused_port()
    command = [
        sys.executable,
        "-m",
        "streamlit",
        "run",
        str(APP.resolve()),
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
        "--server.address=127.0.0.1",
        f"--server.port={port}",
    ]
    process = subprocess.Popen(
        command,
        cwd=tmp_path,
        env=_offline_environment(tmp_path),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    logs = ""
    try:
        health_url = f"http://127.0.0.1:{port}/_stcore/health"
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            try:
                response = requests.get(health_url, timeout=0.5)
                if response.status_code == 200:
                    break
            except requests.RequestException:
                time.sleep(0.1)
        else:
            pytest.fail("Streamlit health endpoint did not become ready")

        assert process.poll() is None
        assert response.status_code == 200
        assert requests.get(f"http://127.0.0.1:{port}/", timeout=2).status_code == 200
    finally:
        process.terminate()
        try:
            logs = process.communicate(timeout=10)[0]
        except subprocess.TimeoutExpired:
            process.kill()
            logs = process.communicate(timeout=5)[0]

    assert "'app' is not a package" not in logs
    assert "ModuleNotFoundError" not in logs


def test_startup_and_browsing_make_no_external_request(monkeypatch, tmp_path) -> None:
    def fail_network(*args, **kwargs):
        raise AssertionError("dashboard attempted an external request")

    monkeypatch.setattr(requests.Session, "request", fail_network)
    app = _run(monkeypatch, tmp_path)
    assert not app.exception
    for page in (
        overview_page, analytics_page, jobs_page, job_detail_page, duplicate_review_page,
        review_tray_page, applications_page, cv_builder_page, notifications_page, runs_page,
    ):
        page_app = AppTest.from_string(
            f"from app.dashboard.pages import {page.__name__}\n{page.__name__}()",
            default_timeout=20,
        ).run()
        assert not page_app.exception


def test_populated_database_overview_renders_stored_metrics(monkeypatch, tmp_path) -> None:
    settings = settings_from_mapping({
        "JOBHUNT_DATABASE_PATH": str(tmp_path / "dashboard.sqlite3"),
        "FIT_RULES_PATH": str(ROOT / "config" / "fit_rules.json"),
        "DEDUP_COMPANY_ALIASES_PATH": str(ROOT / "config" / "company_aliases.json"),
    }, root=tmp_path)
    database = Database.from_settings(settings)
    migrate(database)
    seed_ranked_vacancies(database, 2)
    app = _run(monkeypatch, tmp_path)
    assert not app.exception
    metrics = {item.label: item.value for item in app.metric}
    assert metrics["Logical vacancies"] == "2"
    assert metrics["Active source jobs"] == "2"
    assert metrics["Authoritative rankings"] == "2"
    assert metrics["Preliminary rankings"] == "0"


def test_session_action_token_prevents_duplicate_rerun_submission() -> None:
    app = AppTest.from_string(
        """
import streamlit as st
from app.dashboard.components import execute_once
st.session_state.setdefault('calls', 0)
def mutate():
    st.session_state['calls'] += 1
    return True
if st.button('Mutate'):
    execute_once('stable-action', mutate)
st.write(st.session_state['calls'])
""",
        default_timeout=20,
    ).run()
    app.button[0].click().run()
    assert app.markdown[-1].value == "`1`"
    app.button[0].click().run()
    assert app.markdown[-1].value == "`1`"
    assert any("already completed" in item.value for item in app.info)
