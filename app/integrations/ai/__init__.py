"""Optional AI provider boundary for CV derivatives."""

from app.config import Settings
from app.integrations.ai.base import AIProvider
from app.integrations.ai.ollama_cloud import OllamaCloudProvider
from app.integrations.ai.openai_compatible import OpenAICompatibleProvider


def build_ai_provider(settings: Settings) -> AIProvider | None:
    if settings.ai_provider == "openai_compatible":
        return OpenAICompatibleProvider(settings)
    if settings.ai_provider == "ollama_cloud":
        return OllamaCloudProvider(settings)
    return None

__all__ = [
    "AIProvider",
    "OllamaCloudProvider",
    "OpenAICompatibleProvider",
    "build_ai_provider",
]
