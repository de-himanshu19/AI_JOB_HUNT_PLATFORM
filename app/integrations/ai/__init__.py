"""Optional AI provider boundary for CV derivatives."""

from app.integrations.ai.base import AIProvider
from app.integrations.ai.ollama import OllamaProvider

__all__ = ["AIProvider", "OllamaProvider"]
