"""Select the AI provider from settings (openai, mock, or disabled)."""
from __future__ import annotations

import threading

from app.config import get_settings
from app.providers.base import ConnectionReport, ProviderUnavailable


class DisabledProvider:
    name = "disabled"

    @property
    def available(self) -> bool:
        return False

    def models(self) -> dict[str, str]:
        s = get_settings()
        return {"vision": s.openai_model_vision, "intel": s.openai_model_intel, "text": s.openai_model_text,
                "image": s.openai_model_image}

    def test_connection(self) -> ConnectionReport:
        return ConnectionReport(False, self.name, "AI is not configured. Add OPENAI_API_KEY to .env and restart.")

    def _off(self, *a, **k):
        raise ProviderUnavailable("AI is not configured. Add OPENAI_API_KEY to the .env file and restart the studio.")

    structured = _off
    generate_image = _off
    edit_image = _off


_lock = threading.Lock()
_provider = None


def get_provider():
    global _provider
    with _lock:
        if _provider is None:
            kind = get_settings().effective_ai_provider
            if kind == "openai":
                from app.providers.openai_provider import OpenAIProvider

                _provider = OpenAIProvider()
            elif kind == "mock":
                from app.providers.mock_provider import MockProvider

                _provider = MockProvider()
            else:
                _provider = DisabledProvider()
        return _provider


def set_provider(provider) -> None:
    global _provider
    with _lock:
        _provider = provider


def reset_provider() -> None:
    set_provider(None)
