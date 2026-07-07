from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.cli as cli
from app.config import settings_from_mapping
from app.db.connection import Database
from app.db.migrations import migrate
from tests.notification_helpers import seed_ranked_vacancies
from app.integrations.telegram import TelegramSendResult


def _settings(tmp_path, root, **updates):
    values = {
        "JOBHUNT_DATABASE_PATH": "notification-cli.sqlite3",
        "FIT_RULES_PATH": str(root / "config" / "fit_rules.json"),
        "DEDUP_COMPANY_ALIASES_PATH": str(root / "config" / "company_aliases.json"),
    }
    values.update(updates)
    return settings_from_mapping(values, root=tmp_path)


def test_preview_is_offline_and_does_not_write_notification_state(
    monkeypatch, tmp_path, capsys,
) -> None:
    root = Path(__file__).parents[2]
    settings = _settings(tmp_path, root)
    database = Database.from_settings(settings)
    migrate(database)
    profile, _ = seed_ranked_vacancies(database, 2)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    assert cli.main([
        "notify", "telegram", "preview", "--profile-id", str(profile.id)
    ]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["network_requested"] is False
    assert output["database_modified"] is False
    assert output["selected_count"] == 2
    with database.read_connection() as connection:
        assert connection.execute("SELECT COUNT(*) FROM notification_batches").fetchone()[0] == 0


def test_send_is_blocked_without_explicit_enabled_configuration(
    monkeypatch, tmp_path,
) -> None:
    root = Path(__file__).parents[2]
    settings = _settings(tmp_path, root)
    database = Database.from_settings(settings)
    migrate(database)
    profile, _ = seed_ranked_vacancies(database, 1)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    with pytest.raises(ValueError, match="TELEGRAM_ENABLED"):
        cli.main([
            "notify", "telegram", "send", "--profile-id", str(profile.id),
            "--live",
        ])


def test_list_and_show_are_offline(monkeypatch, tmp_path, capsys) -> None:
    root = Path(__file__).parents[2]
    settings = _settings(tmp_path, root)
    database = Database.from_settings(settings)
    migrate(database)
    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    assert cli.main(["notify", "list"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_live_cli_send_uses_injected_client_and_audit_commands(
    monkeypatch, tmp_path, capsys,
) -> None:
    root = Path(__file__).parents[2]
    settings = _settings(
        tmp_path, root,
        TELEGRAM_ENABLED="true",
        TELEGRAM_BOT_TOKEN="fixture-token",
        TELEGRAM_CHAT_ID="fixture-chat",
    )
    database = Database.from_settings(settings)
    migrate(database)
    profile, _ = seed_ranked_vacancies(database, 1)
    messages = []

    class InjectedClient:
        def send_message(self, text):
            messages.append(text)
            return TelegramSendResult(True, "fixture-message")

    monkeypatch.setattr(cli, "get_settings", lambda: settings)
    monkeypatch.setattr(cli, "TelegramClient", lambda _: InjectedClient())
    assert cli.main([
        "notify", "telegram", "send", "--profile-id", str(profile.id), "--live"
    ]) == 0
    sent = json.loads(capsys.readouterr().out)
    batch_id = sent["batch"]["id"]
    assert sent["batch"]["status"] == "completed"
    assert len(messages) == 1
    assert cli.main(["notify", "show", batch_id]) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["items"][0]["status"] == "sent"
