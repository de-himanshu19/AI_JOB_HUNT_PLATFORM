"""Explicitly opt-in local or cloud Ollama provider."""

from __future__ import annotations

import requests

from app.config import Settings


class OllamaProvider:
    def __init__(self, settings: Settings, session: requests.Session | None = None):
        if settings.ai_provider not in {"local_ollama", "ollama_cloud"}:
            raise ValueError("A configured Ollama provider is required")
        self.name = settings.ai_provider
        self.model = (
            settings.ai_local_model
            if self.name == "local_ollama" else settings.ai_cloud_model
        )
        self.url = (
            "http://localhost:11434/api/generate"
            if self.name == "local_ollama" else "https://ollama.com/api/generate"
        )
        self.api_key = settings.ai_ollama_api_key
        self.timeout = settings.ai_timeout_seconds
        self.session = session or requests.Session()

    def polish(self, prompt: str) -> str:
        headers = {"Content-Type": "application/json"}
        if self.name == "ollama_cloud":
            headers["Authorization"] = f"Bearer {self.api_key.get_secret_value()}"
        response = self.session.post(
            self.url,
            json={
                "model": self.model, "prompt": prompt, "stream": False,
                "options": {"temperature": 0.2},
            },
            headers=headers,
            timeout=self.timeout,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as error:
            raise ValueError("AI provider returned invalid JSON") from error
        text = payload.get("response")
        if not isinstance(text, str) or not text.strip():
            raise ValueError("AI provider returned incomplete response content")
        return text.strip() + "\n"
