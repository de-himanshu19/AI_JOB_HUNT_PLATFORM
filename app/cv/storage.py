"""Safe atomic storage for private CV artifacts."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path
from uuid import UUID


class ArtifactStore:
    def __init__(self, root: Path):
        self.root = root.resolve(strict=False)

    def write_bundle(self, artifact_id: UUID, cv_text: str, report_text: str) -> tuple[Path, Path]:
        self.root.mkdir(parents=True, exist_ok=True)
        cv_path = self._safe_path(f"{artifact_id}.flowcv.txt")
        report_path = self._safe_path(f"{artifact_id}.evidence.txt")
        if cv_path.exists() or report_path.exists():
            raise FileExistsError("Artifact UUID collision; existing files were not overwritten")
        written: list[Path] = []
        try:
            self._atomic_write(cv_path, cv_text)
            written.append(cv_path)
            self._atomic_write(report_path, report_text)
            written.append(report_path)
        except BaseException:
            self.cleanup(*written)
            raise
        return cv_path, report_path

    def _safe_path(self, filename: str) -> Path:
        path = (self.root / filename).resolve(strict=False)
        if path.parent != self.root:
            raise ValueError("Artifact path escaped the configured root")
        return path

    def write_attempt_report(self, attempt_id: UUID, text: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self._safe_path(f"{attempt_id}.ai-attempt.txt")
        if path.exists():
            raise FileExistsError("AI attempt UUID collision; existing file was not overwritten")
        self._atomic_write(path, text)
        return path

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        fd, temporary = tempfile.mkstemp(prefix=".cv-", suffix=".tmp", dir=path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    @staticmethod
    def cleanup(*paths: Path) -> None:
        for path in paths:
            path.unlink(missing_ok=True)
