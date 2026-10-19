"""Publishing orchestration: gates, idempotent jobs, manual tasks, failure recording.

Nothing is published unless the channel's approval is valid for the *current* content hash, and the
job re-checks that hash when it runs (content edited after the request → the job refuses).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.copywriter.channels import CHANNELS
from app.core import audit
from app.core.errors import GateFailed
from app.core.lifecycle import MARKET_STATUSES, refresh_status
from app.db.base import utcnow
from app.db.models import ChannelListing, Job, ManualTask, Watch
from app.jobs.queue import enqueue
from app.publish.registry import channel_mode
from app.review.approvals import active_approval, approval_valid

ACTIVE_LISTING = ("live", "simulated", "manual_posted", "reserved")


def get_listing(db: Session, watch: Watch, channel: str, create: bool = True) -> ChannelListing | None:
    listing = db.scalar(select(ChannelListing).where(ChannelListing.watch_id == watch.id, ChannelListing.channel == channel))
    if listing is None and create:
        listing = ChannelListing(watch_id=watch.id, channel=channel, status="not_started",
                                 mode=CHANNELS[channel].route)
        db.add(listing)
        db.flush()
    return listing


def manual_instructions(watch: Watch, channel: str) -> str:
    ch = CHANNELS[channel]
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(ch.manual_steps, 1))
    return (f"Download the {ch.name} draft pack for {watch.sku} (approved images and text).\n\n{steps}\n\n"
            "When it is live, paste the link here and mark the task done.")


def request_publish(db: Session, watch: Watch, channels: list[str], actor: str, *, schedule_at: datetime | None = None,
                    simulate: bool = False) -> list[dict[str, Any]]:
    from app.review.readiness import watch_readiness

    if watch.status in MARKET_STATUSES:
        raise GateFailed(f"This watch is {watch.status}; publishing is not allowed.")
    ready = {c["key"]: c for c in watch_readiness(db, watch)["channels"]}
    results = []
    for ch in channels:
        if ch not in CHANNELS:
            results.append({"channel": ch, "status": "blocked", "message": "Unknown channel."})
            continue
        info = ready.get(ch)
        if info is None:
            results.append({"channel": ch, "status": "blocked", "message": "Channel is switched off in Settings."})
            continue
        if not info["publish_ready"]:
            results.append({"channel": ch, "status": "blocked", "message": "Not ready to publish.",
                            "blockers": info["publish_blockers"]})
            continue
        approval = active_approval(db, watch.id, "channel", ch)
        content_hash = approval.content_hash
        listing = get_listing(db, watch, ch)
        if listing.status in ("live", "simulated", "manual_posted") and listing.published_hash == content_hash:
            results.append({"channel": ch, "status": "already_published", "message": "Already published with this content."})
            continue
        route = CHANNELS[ch].route
        if route == "manual":
            task = db.scalar(select(ManualTask).where(ManualTask.watch_id == watch.id, ManualTask.channel == ch,
                                                      ManualTask.kind == "post", ManualTask.status == "open"))
            if task is None or task.content_hash != content_hash:
                if task is not None:
                    task.status = "dismissed"
                task = ManualTask(watch_id=watch.id, channel=ch, kind="post",
                                  title=f"Post {watch.sku} on {CHANNELS[ch].name}",
                                  instructions=manual_instructions(watch, ch), content_hash=content_hash)
                db.add(task)
                db.flush()
            listing.status = "manual_pending"
            listing.mode = "manual"
            results.append({"channel": ch, "status": "manual_task", "task_id": task.id,
                            "message": "Draft pack ready — post it yourself and record the link."})
            continue
        mode = channel_mode(db, ch).mode
        if simulate and mode == "live":
            mode = "simulation"
        if mode == "unavailable":
            results.append({"channel": ch, "status": "blocked", "message": channel_mode(db, ch).message})
            continue
        action = "update" if listing.external_id and listing.status in ("live", "simulated") else "publish"
        job = enqueue(db, "publish_channel", watch_id=watch.id, channel=ch, created_by=actor,
                      payload={"mode": mode, "content_hash": content_hash, "action": action},
                      idempotency_key=f"publish:{watch.id}:{ch}:{content_hash[:20]}:{mode}",
                      run_after=schedule_at, max_attempts=4)
        if job.status in ("pending", "running"):
            listing.status = "queued" if action == "publish" else "update_pending"
            listing.mode = "simulation" if mode == "simulation" else route
        results.append({"channel": ch, "status": "queued" if job.status in ("pending", "running") else job.status,
                        "job_id": job.id, "mode": mode,
                        "scheduled_for": schedule_at.isoformat() if schedule_at else None,
                        "message": ("Scheduled" if schedule_at else "Queued") + (" (simulation)" if mode == "simulation" else "")})
    audit.record(db, actor, "publish_requested",
                 "Publish requested: " + ", ".join(f"{r['channel']} → {r['status']}" for r in results),
                 entity_type="watch", entity_id=watch.id, watch_id=watch.id, detail={"results": results})
    return results


def complete_manual_task(db: Session, task: ManualTask, actor: str, url: str | None, note: str | None = None) -> ManualTask:
    watch = db.get(Watch, task.watch_id)
    listing = get_listing(db, watch, task.channel)
    if task.status != "open":
        return task
    if task.kind == "post":
        approval = active_approval(db, watch.id, "channel", task.channel)
        if approval is None or not approval_valid(db, watch, "channel", task.channel) or approval.content_hash != task.content_hash:
            raise GateFailed("The content changed after this task was created. Re-approve, then publish again.")
        listing.status = "manual_posted"
        listing.external_url = url
        listing.published_hash = task.content_hash
        listing.published_at = utcnow()
        listing.mode = "manual"
    elif task.kind == "mark_reserved":
        listing.status = "reserved"
    elif task.kind == "mark_sold":
        listing.status = "sold"
    elif task.kind == "remove":
        listing.status = "withdrawn"
    elif task.kind == "mark_available":
        listing.status = "manual_posted" if listing.mode == "manual" else listing.status
    elif task.kind == "manual_update":
        listing.status = {"reserve": "reserved", "sold": "sold", "withdraw": "withdrawn"}.get(
            (listing.details or {}).get("pending_action", ""), listing.status)
    listing.last_synced_at = utcnow()
    task.status = "done"
    task.live_url = url or task.live_url
    task.completed_at = utcnow()
    task.completed_by = actor
    audit.record(db, actor, "manual_task_done", f"{task.title}" + (f" — {url}" if url else "") + (f" ({note})" if note else ""),
                 entity_type="manual_task", entity_id=task.id, watch_id=watch.id,
                 detail={"channel": task.channel, "kind": task.kind})
    refresh_status(db, watch, actor)
    return task


def request_withdraw(db: Session, watch: Watch, channel: str, actor: str) -> dict:
    from app.publish.lifecycle_sync import sync_listing

    listing = get_listing(db, watch, channel, create=False)
    if listing is None or listing.status not in ACTIVE_LISTING + ("manual_pending", "queued", "update_pending", "failed"):
        return {"channel": channel, "status": "not_listed", "message": "Not listed on this channel."}
    res = sync_listing(db, watch, listing, "withdraw", actor)
    audit.record(db, actor, "withdraw_requested", f"Withdraw from {CHANNELS[channel].name}: {res['status']}",
                 entity_type="watch", entity_id=watch.id, watch_id=watch.id)
    return res


def pending_publish_jobs(db: Session, watch: Watch, channel: str | None = None) -> list[Job]:
    stmt = select(Job).where(Job.watch_id == watch.id, Job.type == "publish_channel", Job.status == "pending")
    if channel:
        stmt = stmt.where(Job.channel == channel)
    return list(db.scalars(stmt))
