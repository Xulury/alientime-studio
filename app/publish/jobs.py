"""Background job handlers for publishing and channel status updates."""
from __future__ import annotations

import logging

from app.copywriter.channels import CHANNELS
from app.core import audit
from app.core.lifecycle import MARKET_STATUSES, refresh_status
from app.db.base import SessionLocal, utcnow
from app.db.models import ChannelListing, Job, Watch
from app.integrations.base import IntegrationError, UnsupportedOperation
from app.integrations.cloudflare_r2 import CloudflareR2
from app.jobs.queue import JobContext, PermanentJobError, handler
from app.publish.base import ListingRef
from app.publish.chrono24_feed import Chrono24FeedAdapter
from app.publish.package import build_package
from app.publish.registry import NEEDS_PUBLIC_URLS, adapter_for
from app.publish.service import get_listing
from app.review.approvals import active_approval, approval_valid

log = logging.getLogger(__name__)


def _record_failure(job_id: str, listing_id: str, message: str, final: bool, status: str) -> None:
    s = SessionLocal()
    try:
        listing = s.get(ChannelListing, listing_id)
        if listing is not None:
            listing.last_error = message[:1000]
            if final:
                listing.status = status
            s.commit()
    finally:
        s.close()


def _rebuild_feed(ctx: JobContext, mode: str) -> dict:
    return Chrono24FeedAdapter().write_feed(ctx.db, upload=(mode == "live"))


@handler("publish_channel", "Publish listing")
def publish_channel_job(ctx: JobContext) -> dict:
    db = ctx.db
    watch = db.get(Watch, ctx.job.watch_id)
    channel = ctx.job.channel
    if watch is None or channel not in CHANNELS:
        raise PermanentJobError("Watch or channel no longer exists.")
    mode = ctx.payload.get("mode", "simulation")
    expected = ctx.payload.get("content_hash")
    listing = get_listing(db, watch, channel)
    try:
        if watch.status in MARKET_STATUSES:
            raise PermanentJobError(f"Watch is {watch.status}; publishing cancelled.")
        approval = active_approval(db, watch.id, "channel", channel)
        if approval is None or not approval_valid(db, watch, "channel", channel) or approval.content_hash != expected:
            raise PermanentJobError("The content changed after approval. Re-approve and publish again.")
        ctx.progress(10, "Preparing approved images")
        pkg = build_package(db, watch, channel, expected)
        adapter = adapter_for(db, channel, mode)
        if mode == "live" and channel in NEEDS_PUBLIC_URLS:
            ctx.progress(30, "Uploading approved images to public storage")
            urls, keys = CloudflareR2().upload_images(watch.sku, pkg.images)
            pkg.public_image_urls = urls
            listing.details = {**(listing.details or {}), "public_urls": urls, "r2_keys": keys}
        listing.status = "publishing"
        db.commit()
        ctx.progress(55, f"Publishing to {CHANNELS[channel].name}")
        ref = ListingRef(listing.external_id, listing.external_url, listing.details or {})
        if ctx.payload.get("action") == "update" and listing.external_id:
            res = adapter.update_listing(ref, pkg)
        else:
            res = adapter.publish_new(pkg)
        listing.external_id = res.external_id or listing.external_id
        listing.external_url = res.external_url or listing.external_url
        listing.status = "simulated" if mode == "simulation" else ("live" if res.status in ("live", "simulated") else res.status)
        listing.mode = "simulation" if mode == "simulation" else CHANNELS[channel].route
        listing.published_hash = expected
        listing.published_at = utcnow()
        listing.last_error = None
        listing.last_action = ctx.payload.get("action", "publish")
        listing.details = {**(listing.details or {}), **(res.details or {})}
        db.flush()
        if channel == "chrono24":
            feed = _rebuild_feed(ctx, mode)
            listing.details = {**listing.details, "feed": feed}
        audit.record(db, ctx.job.created_by or "system",
                     "listing_simulated" if mode == "simulation" else "listing_published",
                     f"{CHANNELS[channel].name}: {res.message}" + (f" {listing.external_url}" if listing.external_url else ""),
                     entity_type="listing", entity_id=listing.id, watch_id=watch.id,
                     detail={"channel": channel, "mode": mode, "external_id": listing.external_id})
        refresh_status(db, watch)
        return {"status": listing.status, "url": listing.external_url, "message": res.message}
    except PermanentJobError as e:
        db.rollback()
        _record_failure(ctx.job.id, listing.id, str(e), True, "failed")
        raise
    except (IntegrationError, UnsupportedOperation) as e:
        db.rollback()
        retry = isinstance(e, IntegrationError) and e.retryable and ctx.job.attempts < ctx.job.max_attempts
        _record_failure(ctx.job.id, listing.id, str(e), not retry, "failed")
        if retry:
            raise
        raise PermanentJobError(str(e))
    except Exception as e:
        db.rollback()
        final = ctx.job.attempts >= ctx.job.max_attempts
        _record_failure(ctx.job.id, listing.id, f"{type(e).__name__}: {e}", final, "failed")
        raise


@handler("sync_channel", "Update channel status")
def sync_channel_job(ctx: JobContext) -> dict:
    from app.publish.lifecycle_sync import _manual_task

    db = ctx.db
    watch = db.get(Watch, ctx.job.watch_id)
    channel = ctx.job.channel
    listing = get_listing(db, watch, channel, create=False) if watch else None
    if watch is None or listing is None:
        raise PermanentJobError("Listing no longer exists.")
    action = ctx.payload.get("action")
    mode = ctx.payload.get("mode", "live")
    try:
        adapter = adapter_for(db, channel, mode)
        ref = ListingRef(listing.external_id, listing.external_url, listing.details or {})
        ctx.progress(30, f"Updating {CHANNELS[channel].name}")
        try:
            if action == "reserve":
                res = adapter.mark_reserved(ref)
            elif action == "sold":
                res = adapter.mark_sold(ref)
            elif action == "withdraw":
                res = adapter.withdraw(ref, "withdrawn")
            elif action == "available":
                res = adapter.mark_available(ref)
            else:
                raise PermanentJobError(f"Unknown action {action}")
        except UnsupportedOperation as e:
            task = _manual_task(db, watch, listing, action, extra=str(e))
            listing.details = {**(listing.details or {}), "pending_action": action, "manual_task": task.id}
            audit.record(db, ctx.job.created_by or "system", "channel_update_manual",
                         f"{CHANNELS[channel].name}: API cannot do this; added to your checklist",
                         entity_type="listing", entity_id=listing.id, watch_id=watch.id)
            return {"status": "manual_task", "message": f"{CHANNELS[channel].name}: added to your checklist"}
        listing.status = {"simulated": "simulated", "live": "live"}.get(res.status, res.status)
        if mode == "simulation" and listing.status == "live":
            listing.status = "simulated"
        listing.external_url = res.external_url if res.status != "withdrawn" else listing.external_url
        listing.last_synced_at = utcnow()
        listing.last_error = None
        listing.last_action = action
        details = dict(listing.details or {})
        details.pop("pending_action", None)
        listing.details = details
        if channel == "chrono24":
            _rebuild_feed(ctx, mode)
        if action in ("sold", "withdraw") and details.get("r2_keys"):
            try:
                CloudflareR2().delete_keys(details["r2_keys"])
            except Exception as e:  # noqa: BLE001 - cleanup is best effort, but must be visible
                log.warning("R2 cleanup failed for %s: %s", watch.sku, e)
                audit.record(db, "system", "r2_cleanup_failed",
                             f"Could not delete {len(details['r2_keys'])} public image(s) from Cloudflare R2; delete "
                             f"listings/{watch.sku}/ by hand", entity_type="listing", entity_id=listing.id,
                             watch_id=watch.id)
        audit.record(db, ctx.job.created_by or "system", "channel_updated",
                     f"{CHANNELS[channel].name}: {res.message}", entity_type="listing", entity_id=listing.id,
                     watch_id=watch.id, detail={"action": action, "mode": mode})
        return {"status": listing.status, "message": res.message}
    except (IntegrationError, PermanentJobError) as e:
        db.rollback()
        retry = isinstance(e, IntegrationError) and e.retryable and ctx.job.attempts < ctx.job.max_attempts
        _record_failure(ctx.job.id, listing.id, str(e), not retry, "sync_failed")
        if retry:
            raise
        raise PermanentJobError(str(e))
