"""Windows-safe local Streamlit launcher."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def dashboard_path() -> Path:
    return Path(__file__).resolve().with_name("Home.py")


def command(extra_args: list[str] | None = None) -> list[str]:
    return [
        sys.executable, "-m", "streamlit", "run", str(dashboard_path()),
        "--server.headless=true", "--browser.gatherUsageStats=false",
        *(extra_args or []),
    ]


def main() -> int:
    return subprocess.call(command(sys.argv[1:]))


if __name__ == "__main__":
    raise SystemExit(main())

