"""Publishing centre: platforms, queue, failures, manual tasks, draft packs, withdrawals."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.api.views import job_view
from app.api.watches import get_watch
from app.copywriter.channels import CHANNELS
from app.core import audit
from app.core.errors import AppError, NotFound
from app.core.settings_store import get_setting
from app.db.base import get_db, iso
from app.db.models import ChannelListing, Job, ManualTask, Watch
from app.publish.chrono24_feed import Chrono24FeedAdapter, feed_path
from app.publish.draft_pack import build_draft_pack
from app.publish.registry import channel_mode
from app.publish.service import complete_manual_task, request_publish, request_withdraw
from app.review.readiness import LISTING_LABELS

router = APIRouter(prefix="/api", tags=["publishing"])


class PublishIn(BaseModel):
    channels: list[str] = Field(min_length=1, max_length=20)
    schedule_at: datetime | None = None
    simulate: bool = False


class TaskDone(BaseModel):
    url: str | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=500)


def task_view(db: Session, t: ManualTask) -> dict:
    w = db.get(Watch, t.watch_id)
    return {"id": t.id, "watch_id": t.watch_id, "sku": w.sku if w else None,
            "watch": f"{w.brand} {w.model}" if w else None, "channel": t.channel,
            "channel_name": CHANNELS[t.channel].name if t.channel in CHANNELS else t.channel, "kind": t.kind,
            "title": t.title, "instructions": t.instructions, "status": t.status, "live_url": t.live_url,
            "created_at": iso(t.created_at), "completed_at": iso(t.completed_at), "completed_by": t.completed_by}


@router.get("/publishing/overview")
def overview(db: Session = Depends(get_db), _: Principal = Depends(require("read"))) -> dict:
    from app.publish.registry import live_adapter

    enabled = get_setting(db, "channels").get("enabled") or list(CHANNELS)
    platforms = []
    for key, ch in CHANNELS.items():
        m = channel_mode(db, key)
        adapter = live_adapter(key)
        info = adapter.info(db).as_dict() if adapter else None
        platforms.append({"key": key, "name": ch.name, "route": ch.route, "enabled": key in enabled,
                          "mode": m.as_dict(), "integration": info})
    jobs = db.scalars(select(Job).where(Job.type.in_(("publish_channel", "sync_channel")))
                      .order_by(Job.created_at.desc()).limit(80)).all()
    listings = db.execute(select(ChannelListing, Watch).join(Watch, Watch.id == ChannelListing.watch_id)
                          .order_by(ChannelListing.updated_at.desc()).limit(200)).all()

    def lv(l: ChannelListing, w: Watch) -> dict:
        return {"id": l.id, "watch_id": w.id, "sku": w.sku, "watch": f"{w.brand} {w.model}", "channel": l.channel,
                "channel_name": CHANNELS[l.channel].name if l.channel in CHANNELS else l.channel,
                "status": l.status, "label": LISTING_LABELS.get(l.status, l.status), "mode": l.mode,
                "external_url": l.external_url, "published_at": iso(l.published_at), "last_error": l.last_error,
                "updated_at": iso(l.updated_at)}

    tasks = db.scalars(select(ManualTask).where(ManualTask.status == "open").order_by(ManualTask.created_at)).all()
    sku_for = {w.id: w.sku for w in db.scalars(select(Watch))}
    return {
        "platforms": platforms,
        "queue": [{**job_view(j), "sku": sku_for.get(j.watch_id)} for j in jobs if j.status in ("pending", "running")],
        "scheduled": [{**job_view(j), "sku": sku_for.get(j.watch_id)} for j in jobs
                      if j.status == "pending" and j.run_after and j.run_after > datetime.now(timezone.utc).replace(tzinfo=None)],
        "recent_jobs": [{**job_view(j), "sku": sku_for.get(j.watch_id)} for j in jobs[:30]],
        "failures": [lv(l, w) for l, w in listings if l.status in ("failed", "sync_failed")],
        "published": [lv(l, w) for l, w in listings if l.status in ("live", "manual_posted")],
        "simulated": [lv(l, w) for l, w in listings if l.status == "simulated"],
        "listings": [lv(l, w) for l, w in listings],
        "manual_tasks": [task_view(db, t) for t in tasks],
    }


@router.post("/watches/{watch_id}/publish")
def publish(watch_id: str, body: PublishIn, db: Session = Depends(get_db),
            principal: Principal = Depends(require("publish"))) -> dict:
    w = get_watch(db, watch_id, include_archived=False)
    sched = body.schedule_at
    if sched is not None and sched.tzinfo is not None:
        sched = sched.astimezone(timezone.utc).replace(tzinfo=None)
    results = request_publish(db, w, body.channels, principal.actor, schedule_at=sched, simulate=body.simulate)
    db.commit()
    return {"results": results}


@router.post("/watches/{watch_id}/channels/{channel}/withdraw")
def withdraw(watch_id: str, channel: str, db: Session = Depends(get_db),
             principal: Principal = Depends(require("publish"))) -> dict:
    w = get_watch(db, watch_id, include_archived=False)
    if channel not in CHANNELS:
        raise NotFound("Unknown channel.")
    res = request_withdraw(db, w, channel, principal.actor)
    db.commit()
    return res


@router.get("/watches/{watch_id}/draft-pack")
def draft_pack(watch_id: str, channels: str | None = Query(default=None, max_length=400), db: Session = Depends(get_db),
               principal: Principal = Depends(require("read"))):
    w = get_watch(db, watch_id)
    chosen = [c for c in channels.split(",") if c] if channels else None
    data, status = build_draft_pack(db, w, chosen)
    if not status:
        raise AppError("Generate listing copy before downloading a draft pack.")
    suffix = "" if all(v == "approved" for v in status.values()) else "_PREVIEW"
    audit.record(db, principal.actor, "draft_pack_downloaded", f"Draft pack: {', '.join(f'{k} ({v})' for k, v in status.items())}",
                 entity_type="watch", entity_id=w.id, watch_id=w.id)
    db.commit()
    return Response(data, media_type="application/zip",
                    headers={"Content-Disposition": f'attachment; filename="{w.sku}_draft_pack{suffix}.zip"',
                             "Cache-Control": "no-store"})


@router.get("/manual-tasks")
def manual_tasks(status: str = "open", watch_id: str | None = None, db: Session = Depends(get_db),
                 _: Principal = Depends(require("read"))) -> dict:
    stmt = select(ManualTask).order_by(ManualTask.created_at.desc())
    if status != "all":
        stmt = stmt.where(ManualTask.status == status)
    if watch_id:
        stmt = stmt.where(ManualTask.watch_id == watch_id)
    return {"items": [task_view(db, t) for t in db.scalars(stmt.limit(300))]}


@router.post("/manual-tasks/{task_id}/complete")
def complete_task(task_id: str, body: TaskDone, db: Session = Depends(get_db),
                  principal: Principal = Depends(require("publish"))) -> dict:
    t = db.get(ManualTask, task_id)
    if t is None:
        raise NotFound("Task not found.")
    if body.url and not body.url.startswith(("https://", "http://")):
        raise AppError("The link must start with https://")
    complete_manual_task(db, t, principal.actor, body.url, body.note)
    db.commit()
    return task_view(db, t)


@router.post("/manual-tasks/{task_id}/dismiss")
def dismiss_task(task_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require("publish"))) -> dict:
    t = db.get(ManualTask, task_id)
    if t is None:
        raise NotFound("Task not found.")
    if t.status == "open":
        t.status = "dismissed"
        audit.record(db, principal.actor, "manual_task_dismissed", f"Dismissed: {t.title}", entity_type="manual_task",
                     entity_id=t.id, watch_id=t.watch_id)
        if t.kind == "post":
            listing = db.scalar(select(ChannelListing).where(ChannelListing.watch_id == t.watch_id,
                                                             ChannelListing.channel == t.channel))
            if listing is not None and listing.status == "manual_pending":
                listing.status = "not_started"
    db.commit()
    return task_view(db, t)


@router.post("/publishing/chrono24/feed")
def rebuild_feed(db: Session = Depends(get_db), principal: Principal = Depends(require("publish"))) -> dict:
    m = channel_mode(db, "chrono24")
    res = Chrono24FeedAdapter().write_feed(db, upload=m.mode == "live")
    audit.record(db, principal.actor, "chrono24_feed_built", f"Chrono24 feed rebuilt ({res['rows']} row(s))")
    db.commit()
    return res


@router.get("/publishing/chrono24/feed.csv")
def download_feed(_: Principal = Depends(require("read"))):
    p = feed_path()
    if not p.is_file():
        raise NotFound("The feed has not been built yet.")
    return FileResponse(p, media_type="text/csv", filename="chrono24.csv", headers={"Cache-Control": "no-store"})
