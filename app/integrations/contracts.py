"""Compatibility shim for the MVP's integration contracts.

The MVP's `DisabledPublisher` is kept and still fails closed. New code uses the richer interfaces in
`app.publish.base` (ChannelAdapter), `app.ingest.sources` (IngestSource) and `app.providers.base`
(AIProvider).
"""
from dataclasses import dataclass


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


class IntegrationNotConfigured(RuntimeError):
    pass


class DisabledPublisher:
    """Fail closed: this publisher can never publish anything."""

    def __init__(self, channel: str):
        self.channel = channel

    def publish(self, package: ListingPackage) -> PublishResult:
        raise IntegrationNotConfigured(f"{self.channel}: publishing disabled until an authenticated integration is configured")

    def update_status(self, external_id: str, status: str) -> PublishResult:
        raise IntegrationNotConfigured(f"{self.channel}: status synchronization disabled")
