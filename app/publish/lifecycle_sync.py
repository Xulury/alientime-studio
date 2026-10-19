"""Reserved / sold / withdrawn / available: propagate to every channel the watch is on.

The watch record changes immediately. API channels get queued update jobs; manual channels and API
operations the platform does not support become checklist tasks. The summary never claims the watch is
off every channel while any task or update is still outstanding.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.copywriter.channels import CHANNELS
from app.db.base import utcnow
from app.db.models import ChannelListing, ManualTask, Watch
from app.jobs.queue import cancel, enqueue
from app.publish.service import pending_publish_jobs

ACTION_FOR_STATUS = {"reserved": "reserve", "sold": "sold", "withdrawn": "withdraw", "available": "available",
                     "reopen": "available"}
MANUAL_TASK = {
    "reserve": ("mark_reserved", "Mark {sku} as RESERVED on {name}",
                "Edit the {name} post or listing so buyers can see it is reserved (or hide it)."),
    "sold": ("mark_sold", "Mark {sku} as SOLD on {name}",
             "Mark the {name} listing as sold, or delete the post. Reply to open enquiries."),
    "withdraw": ("remove", "Remove {sku} from {name}", "Delete or hide the {name} post or listing."),
    "available": ("mark_available", "Make {sku} available again on {name}",
                  "Remove the RESERVED note from the {name} post or listing, or post it again."),
}


def _manual_task(db: Session, watch: Watch, listing: ChannelListing, action: str, extra: str = "") -> ManualTask:
    kind, title, instr = MANUAL_TASK[action]
    name = CHANNELS[listing.channel].name
    for t in db.scalars(select(ManualTask).where(ManualTask.watch_id == watch.id, ManualTask.channel == listing.channel,
                                                 ManualTask.status == "open", ManualTask.kind != "post")):
        t.status = "dismissed"
    task = ManualTask(watch_id=watch.id, channel=listing.channel, kind=kind, title=title.format(sku=watch.sku, name=name),
                      instructions=instr.format(name=name) + (f"\n\n{extra}" if extra else "")
                      + (f"\n\nListing: {listing.external_url}" if listing.external_url else ""))
    db.add(task)
    db.flush()
    return task


def sync_listing(db: Session, watch: Watch, listing: ChannelListing, action: str, actor: str) -> dict:
    ch = CHANNELS[listing.channel]
    # cancel anything still waiting to publish on this channel
    for job in pending_publish_jobs(db, watch, listing.channel):
        cancel(db, job)
    if listing.status in ("queued", "update_pending") and not listing.external_id:
        listing.status = "not_started"
        return {"channel": listing.channel, "status": "cancelled", "message": "Queued publish cancelled."}
    if ch.route == "manual":
        if listing.status == "manual_pending":
            for t in db.scalars(select(ManualTask).where(ManualTask.watch_id == watch.id, ManualTask.channel == listing.channel,
                                                         ManualTask.kind == "post", ManualTask.status == "open")):
                t.status = "dismissed"
            listing.status = "not_started"
            return {"channel": listing.channel, "status": "cancelled", "message": "Posting task cancelled (it was not posted yet)."}
        if listing.status in ("manual_posted", "reserved", "live"):
            task = _manual_task(db, watch, listing, action)
            return {"channel": listing.channel, "status": "manual_task", "task_id": task.id, "message": task.title}
        return {"channel": listing.channel, "status": "not_listed", "message": "Not posted on this channel."}
    if listing.status not in ("live", "simulated", "reserved", "sync_failed"):
        return {"channel": listing.channel, "status": "not_listed", "message": "Not live on this channel."}
    mode = "simulation" if listing.mode == "simulation" else "live"
    job = enqueue(db, "sync_channel", watch_id=watch.id, channel=listing.channel, created_by=actor,
                  payload={"action": action, "mode": mode},
                  idempotency_key=f"sync:{listing.id}:{action}:{utcnow().timestamp()}", max_attempts=4)
    listing.details = {**(listing.details or {}), "pending_action": action}
    return {"channel": listing.channel, "status": "queued", "job_id": job.id,
            "message": f"{ch.name}: update queued" + (" (simulation)" if mode == "simulation" else "")}


def propagate_market_status(db: Session, watch: Watch, status_action: str, actor: str) -> dict:
    action = ACTION_FOR_STATUS[status_action]
    listings = db.scalars(select(ChannelListing).where(ChannelListing.watch_id == watch.id)).all()
    results = [sync_listing(db, watch, l, action, actor) for l in listings
               if l.status not in ("not_started", "withdrawn", "failed")]
    auto = sum(1 for r in results if r["status"] == "queued")
    manual = sum(1 for r in results if r["status"] == "manual_task")
    if not results:
        message = "Inventory updated. The watch was not listed on any channel."
    else:
        parts = []
        if auto:
            parts.append(f"{auto} channel update(s) queued")
        if manual:
            parts.append(f"{manual} manual action(s) on your checklist")
        message = "Inventory updated. " + ", ".join(parts) + "." if parts else "Inventory updated."
        if action in ("sold", "withdraw", "reserve") and (auto or manual):
            message += " The watch is not yet updated everywhere until these are done."
    return {"action": action, "results": results, "automatic": auto, "manual": manual, "message": message}


def removal_summary(db: Session, watch: Watch) -> dict:
    """For sold/withdrawn watches: is it really off every channel?"""
    listings = db.scalars(select(ChannelListing).where(ChannelListing.watch_id == watch.id)).all()
    still = [l.channel for l in listings if l.status in ("live", "simulated", "manual_posted", "update_pending",
                                                          "sync_failed", "queued", "manual_pending")]
    tasks = db.scalars(select(ManualTask).where(ManualTask.watch_id == watch.id, ManualTask.status == "open")).all()
    return {"channels_outstanding": still, "open_tasks": len(tasks), "complete": not still and not tasks}
