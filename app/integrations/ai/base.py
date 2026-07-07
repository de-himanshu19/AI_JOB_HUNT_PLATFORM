"""Injectable AI provider contract."""

from typing import Protocol


class AIProvider(Protocol):
    name: str
    model: str

    def polish(self, prompt: str) -> str: ...
