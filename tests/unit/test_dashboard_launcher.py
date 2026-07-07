from pathlib import Path

from app.dashboard.launcher import command, dashboard_path


def test_windows_safe_launcher_uses_absolute_home_path() -> None:
    path = dashboard_path()
    result = command(["--server.port=8765"])
    assert path.is_absolute()
    assert path.name == "Home.py"
    assert str(path) in result
    assert "--server.headless=true" in result
    assert result[-1] == "--server.port=8765"
    assert Path(result[0]).name.casefold().startswith("python")
