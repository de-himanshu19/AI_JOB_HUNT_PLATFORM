"""Absolute-path-safe Streamlit bootstrap for the dashboard."""

from pathlib import Path
import sys


_repository_root = str(Path(__file__).resolve().parents[2])
_original_sys_path = sys.path[:]
try:
    # Streamlit places this script's directory first; bootstrap from the package root.
    sys.path.insert(0, _repository_root)
    from app.dashboard.dashboard_app import main
finally:
    sys.path[:] = _original_sys_path


main()
