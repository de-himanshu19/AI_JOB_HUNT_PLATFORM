"""Optional AI provider boundary for CV derivatives."""

from app.config import Settings
from app.integrations.ai.base import AIProvider
from app.integrations.ai.openai_compatible import OpenAICompatibleProvider


def build_ai_provider(settings: Settings) -> AIProvider | None:
    if settings.ai_provider == "openai_compatible":
        return OpenAICompatibleProvider(settings)
    return None

__all__ = [
    "AIProvider",
    "OpenAICompatibleProvider",
    "build_ai_provider",
]
