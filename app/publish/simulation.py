"""Simulation adapter: exercises the full publishing flow without contacting any platform.

Every result is labelled `simulated`, uses the reserved `.invalid` domain for its URL, and is never
counted as a live publication anywhere in the studio.
"""
from __future__ import annotations

import hashlib

from app.config import get_settings
from app.integrations.base import IntegrationError, TestResult
from app.publish.base import AdapterResult, ChannelAdapter, ListingRef, PublishPackage


class SimulationAdapter(ChannelAdapter):
    simulated = True
    required_env = ()

    def __init__(self, channel: str, label: str, route: str = "api"):
        self.channel = channel
        self.name = f"simulation:{channel}"
        self.label = f"{label} (simulation)"
        self.route = route

    def _maybe_fail(self, op: str) -> None:
        if self.channel in get_settings().mock_fail_channels:
            raise IntegrationError(f"Simulated failure while trying to {op} on {self.channel}.")

    def test(self) -> TestResult:
        return TestResult(True, "Simulation mode: no external platform is contacted.")

    def publish_new(self, pkg: PublishPackage) -> AdapterResult:
        self._maybe_fail("publish")
        h = hashlib.sha256(f"{pkg.watch_id}:{self.channel}".encode()).hexdigest()[:10]
        ext = f"sim-{self.channel}-{h}"
        return AdapterResult(ext, f"https://simulation.invalid/{self.channel}/{ext}", "simulated",
                             "Simulated publish — nothing was posted.",
                             {"images": len(pkg.images), "chars": len(pkg.text), "content_hash": pkg.content_hash})

    def update_listing(self, ref: ListingRef, pkg: PublishPackage) -> AdapterResult:
        self._maybe_fail("update")
        return AdapterResult(ref.external_id, ref.external_url, "simulated", "Simulated update — nothing was posted.")

    def withdraw(self, ref: ListingRef, reason: str) -> AdapterResult:
        self._maybe_fail("withdraw")
        return AdapterResult(ref.external_id, ref.external_url, "sold" if reason == "sold" else "withdrawn",
                             "Simulated removal — nothing was changed on the platform.")

    def mark_reserved(self, ref: ListingRef) -> AdapterResult:
        self._maybe_fail("mark reserved")
        return AdapterResult(ref.external_id, ref.external_url, "reserved", "Simulated reserve — nothing was changed.")

    def mark_available(self, ref: ListingRef) -> AdapterResult:
        self._maybe_fail("re-list")
        return AdapterResult(ref.external_id, ref.external_url, "simulated", "Simulated re-list — nothing was changed.")

    def check_status(self, ref: ListingRef) -> AdapterResult:
        return AdapterResult(ref.external_id, ref.external_url, "simulated", "Simulation.")
