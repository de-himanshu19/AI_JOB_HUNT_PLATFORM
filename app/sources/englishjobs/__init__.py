"""EnglishJobs.de source adapter."""

from app.sources.englishjobs.adapter import EnglishJobsAdapter
from app.sources.englishjobs.client import EnglishJobsClient

__all__ = ["EnglishJobsAdapter", "EnglishJobsClient"]
