"""AI provider interface. The pipeline only talks to this interface, so providers can be swapped."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel


class ProviderError(RuntimeError):
    """A provider call failed. `retryable` tells the job system whether to try again."""

    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


class ProviderUnavailable(ProviderError):
    pass


class BudgetExceeded(ProviderError):
    pass


@dataclass
class ImagePart:
    jpeg: bytes
    label: str = ""


@dataclass
class ConnectionReport:
    ok: bool
    provider: str
    message: str
    models: dict[str, Any] = field(default_factory=dict)


class AIProvider(Protocol):
    name: str

    @property
    def available(self) -> bool: ...

    def models(self) -> dict[str, str]: ...

    def test_connection(self) -> ConnectionReport: ...

    def structured(self, role: str, *, system: str, text: str, images: list[ImagePart] | None,
                   schema_name: str, response_model: type[BaseModel], operation: str,
                   watch_id: str | None = None, job_id: str | None = None) -> BaseModel: ...

    def generate_image(self, *, prompt: str, width: int, height: int, operation: str,
                       watch_id: str | None = None, job_id: str | None = None) -> bytes: ...

    def edit_image(self, *, image_png: bytes, mask_png: bytes, prompt: str, width: int, height: int,
                   operation: str, watch_id: str | None = None, job_id: str | None = None) -> bytes: ...
