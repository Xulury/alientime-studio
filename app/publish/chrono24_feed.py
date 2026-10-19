"""Chrono24 dealer feed.

Chrono24 imports dealer listings from a private product feed that your integration manager connects.
Publishing adds the watch to the feed file; sold/reserved/withdrawn remove it. A sold piece stays visible
on Chrono24 until the next import, so the lifecycle checklist also asks you to mark it sold in the dealer
console. Column names below are a sensible default — confirm them with your integration manager.
"""
from __future__ import annotations

import csv
import io
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.integrations.base import IntegrationError, TestResult
from app.integrations.cloudflare_r2 import CloudflareR2
from app.publish.base import AdapterResult, ChannelAdapter, ListingRef, PublishPackage

COLUMNS = ["internal_id", "brand", "model", "reference_number", "year", "condition", "scope_of_delivery",
           "price", "currency", "price_usd", "title", "description", "location", "image_urls"]
SCOPE = {"full_set": "Original box, original papers", "box_and_papers": "Original box, original papers",
         "set_minus_box": "Original papers, no original box", "papers_only": "Original papers, no original box",
         "box_only": "Original box, no original papers", "watch_only": "No original box, no original papers"}


def feed_path() -> Path:
    return get_settings().feeds_dir / "chrono24.csv"


class Chrono24FeedAdapter(ChannelAdapter):
    name = "chrono24"
    channel = "chrono24"
    route = "feed"
    label = "Chrono24 dealer feed"
    required_env = ("CHRONO24_FEED_URL",)
    capabilities = ("add to feed", "remove from feed")
    notes = ("Feed onboarding runs on Chrono24's schedule.",
             "Also mark sold pieces in the dealer console; the feed only updates at the next import.")

    def test(self) -> TestResult:
        r2 = CloudflareR2()
        if not r2.is_configured():
            return TestResult(False, "CHRONO24_FEED_URL is set, but Cloudflare R2 is not configured to host the feed.")
        return TestResult(True, f"Feed will be published to {self._feed_key()} in R2.")

    def _feed_key(self) -> str:
        url = self.settings.chrono24_feed_url or ""
        return urlparse(url).path.lstrip("/") or "feeds/chrono24.csv"

    @staticmethod
    def build_feed(db: Session) -> str:
        from app.db.models import ChannelCopy, ChannelListing, Watch

        rows = db.execute(select(ChannelListing, Watch).join(Watch, Watch.id == ChannelListing.watch_id)
                          .where(ChannelListing.channel == "chrono24",
                                 ChannelListing.status.in_(("live", "simulated")))).all()
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=COLUMNS)
        w.writeheader()
        for listing, watch in rows:
            if watch.status in ("reserved", "sold", "withdrawn"):
                continue
            copy = db.scalar(select(ChannelCopy).where(ChannelCopy.watch_id == watch.id, ChannelCopy.channel == "chrono24"))
            w.writerow({
                "internal_id": watch.sku, "brand": watch.brand, "model": watch.model,
                "reference_number": watch.reference or "", "year": watch.year or "",
                "condition": watch.condition or "", "scope_of_delivery": SCOPE.get(watch.box_papers, ""),
                "price": f"{float(watch.price_sgd):.0f}" if watch.price_sgd is not None else "", "currency": "SGD",
                "price_usd": f"{float(watch.price_usd):.0f}" if watch.price_usd is not None else "",
                "title": (copy.sections.get("title") if copy else "") or f"{watch.brand} {watch.model}",
                "description": copy.rendered_text if copy else "", "location": "Singapore",
                "image_urls": "|".join((listing.details or {}).get("public_urls", [])),
            })
        return buf.getvalue()

    def write_feed(self, db: Session, upload: bool) -> dict:
        data = self.build_feed(db)
        p = feed_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(data, encoding="utf-8")
        out = {"local_path": str(p), "rows": max(0, data.count("\n") - 1)}
        if upload:
            r2 = CloudflareR2()
            if not r2.is_configured():
                raise IntegrationError("Cloudflare R2 is not configured; cannot publish the Chrono24 feed.")
            out["url"] = r2.upload_file(p, self._feed_key(), content_type="text/csv", cache_seconds=300)
        return out

    # The feed is rebuilt by the publish service after the listing row changes; these return the intent.
    def publish_new(self, pkg: PublishPackage) -> AdapterResult:
        return AdapterResult(f"feed:{pkg.sku}", None, "live", "Added to the Chrono24 feed.")

    def update_listing(self, ref: ListingRef, pkg: PublishPackage) -> AdapterResult:
        return AdapterResult(ref.external_id, ref.external_url, "live", "Chrono24 feed entry updated.")

    def withdraw(self, ref: ListingRef, reason: str) -> AdapterResult:
        return AdapterResult(ref.external_id, ref.external_url, "sold" if reason == "sold" else "withdrawn",
                             "Removed from the Chrono24 feed (also mark it in the dealer console).")

    def mark_reserved(self, ref: ListingRef) -> AdapterResult:
        return AdapterResult(ref.external_id, ref.external_url, "reserved", "Removed from the feed while reserved.")

    def mark_available(self, ref: ListingRef) -> AdapterResult:
        return AdapterResult(ref.external_id, ref.external_url, "live", "Back in the Chrono24 feed.")
