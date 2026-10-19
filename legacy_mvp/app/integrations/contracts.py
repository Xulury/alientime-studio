"""Explicit integration contracts. No external network calls in the MVP.

Implementations added later must not bypass review/version/fidelity safety checks.
"""
from dataclasses import dataclass
from typing import Protocol

@dataclass(frozen=True)
class ListingPackage:
    watch_id: str
    revision: int
    channel: str
    text: str
    approved_image_paths: tuple[str, ...]

@dataclass(frozen=True)
class PublishResult:
    channel: str
    external_id: str
    external_url: str | None
    status: str

class InventorySource(Protocol):
    def fetch_watch(self, sku: str) -> dict: ...

class PhotoInbox(Protocol):
    def pull_new_files(self) -> list[str]: ...

class CopyProvider(Protocol):
    def generate_copy(self, verified_facts: dict, channel: str) -> str: ...

class StudioBackgroundProvider(Protocol):
    def generate_background(self, reference_image_path: str, style: dict) -> str: ...

class Publisher(Protocol):
    def publish(self, package: ListingPackage) -> PublishResult: ...
    def update_status(self, external_id: str, status: str) -> PublishResult: ...

class IntegrationNotConfigured(RuntimeError):
    pass

class DisabledPublisher:
    """Fail closed until client grants scopes and production safety gates pass."""
    def __init__(self, channel: str): self.channel=channel
    def publish(self, package: ListingPackage) -> PublishResult:
        raise IntegrationNotConfigured(f'{self.channel}: publishing disabled until authenticated integration is configured')
    def update_status(self, external_id: str, status: str) -> PublishResult:
        raise IntegrationNotConfigured(f'{self.channel}: status synchronization disabled')
