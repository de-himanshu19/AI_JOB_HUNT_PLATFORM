"""Source adapter contracts and implementations."""

from app.sources.base import (
    CollectedJob,
    CollectionError,
    CollectionRequest,
    CollectionResult,
    SourceRunStatus,
)

__all__ = [
    "CollectedJob",
    "CollectionError",
    "CollectionRequest",
    "CollectionResult",
    "SourceRunStatus",
]

