"""Injectable AI provider contract."""

from typing import Protocol


class AIConfigurationError(ValueError):
    """Raised when live AI was requested but configuration is incomplete."""


class AISafetyNotEnabledError(AIConfigurationError):
    """Raised when live AI was requested without AI_ENABLED=true."""


class AIProviderError(RuntimeError):
    """Raised for provider-side failures with secret-safe messages."""


class AIMalformedResponseError(ValueError):
    """Raised when a provider response cannot be parsed into polished text."""


class AIRateLimitError(AIProviderError):
    """Raised when the provider reports rate limiting."""


class AIProvider(Protocol):
    name: str
    model: str

    def polish(self, prompt: str) -> str: ...
