"""Publishing adapter interface shared by every channel."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from app.integrations.base import Integration, UnsupportedOperation


@dataclass
class PublishPackage:
    watch_id: str
    sku: str
    channel: str
    title: str
    text: str
    sections: dict[str, Any]
    facts: dict[str, Any]
    images: list[Path]
    content_hash: str
    public_image_urls: list[str] = field(default_factory=list)

    @property
    def price_sgd(self):
        return self.facts.get("price_sgd")

    @property
    def price_usd(self):
        return self.facts.get("price_usd")


@dataclass
class ListingRef:
    external_id: str | None
    external_url: str | None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class AdapterResult:
    external_id: str | None
    external_url: str | None
    status: str  # live | draft | withdrawn | reserved | sold | simulated
    message: str
    details: dict[str, Any] = field(default_factory=dict)


class ChannelAdapter(Integration):
    """Every publishing adapter offers the same operations. Unsupported ones raise UnsupportedOperation."""

    kind = "publishing"
    channel = "base"
    route = "api"
    simulated = False

    def create_listing(self, pkg: PublishPackage) -> AdapterResult:
        raise UnsupportedOperation(f"{self.label}: creating listings is not supported.")

    def update_listing(self, ref: ListingRef, pkg: PublishPackage) -> AdapterResult:
        raise UnsupportedOperation(f"{self.label}: updating listings is not supported by its API.")

    def publish(self, ref: ListingRef) -> AdapterResult:
        raise UnsupportedOperation(f"{self.label}: separate publish step is not supported.")

    def withdraw(self, ref: ListingRef, reason: str) -> AdapterResult:
        raise UnsupportedOperation(f"{self.label}: removing listings is not supported by its API.")

    def mark_reserved(self, ref: ListingRef) -> AdapterResult:
        raise UnsupportedOperation(f"{self.label}: marking reserved is not supported by its API.")

    def mark_available(self, ref: ListingRef) -> AdapterResult:
        raise UnsupportedOperation(f"{self.label}: re-listing is not supported by its API.")

    def mark_sold(self, ref: ListingRef) -> AdapterResult:
        return self.withdraw(ref, "sold")

    def check_status(self, ref: ListingRef) -> AdapterResult:
        raise UnsupportedOperation(f"{self.label}: status checks are not supported.")

    def publish_new(self, pkg: PublishPackage) -> AdapterResult:
        """Create then publish (adapters that publish in one step override this)."""
        created = self.create_listing(pkg)
        ref = ListingRef(created.external_id, created.external_url, created.details)
        try:
            published = self.publish(ref)
        except UnsupportedOperation:
            return created
        published.details = {**created.details, **published.details}
        return published
