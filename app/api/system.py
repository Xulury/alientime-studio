"""Dashboard, jobs, activity log, local inbox and health."""
from __future__ import annotations

from datetime import timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.api.views import job_view, watch_summary
from app.core import audit
from app.core.errors import AppError, NotFound
from app.core.lifecycle import MARKET_STATUSES, STATUS_LABELS
from app.core.sku import next_sku
from app.db.base import get_db, iso, utcnow
from app.db.models import Asset, AuditEvent, ChannelCopy, ChannelListing, Job, ManualTask, Watch
from app.ingest.images import ingest_image
from app.ingest.sources import IncomingFile, available_sources
from app.jobs import queue
from app.review.approvals import approval_valid, enabled_channels

import os
import traceback
from sqlalchemy import text
from app.db.models import User

router = APIRouter(prefix="/api", tags=["system"])


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict:
    db_status = "connected"
    try:
        db.execute(text("SELECT 1")).scalar()
    except Exception as exc:
        db_status = f"error: {type(exc).__name__}: {str(exc)}"

    return {
        "status": "ok" if db_status == "connected" else "degraded",
        "database": db_status,
        "environment": {
            "vercel": bool(os.environ.get("VERCEL")),
            "database_url_set": bool(os.environ.get("DATABASE_URL")),
            "supabase_url_set": bool(os.environ.get("SUPABASE_URL")),
        },
    }


@router.get("/debug/db")
def debug_db(db: Session = Depends(get_db)) -> dict:
    try:
        row = db.execute(text("SELECT current_database(), current_user, version()")).fetchone()
        user_count = db.scalar(select(func.count()).select_from(User)) or 0
        return {
            "success": True,
            "database": row[0] if row else None,
            "user": row[1] if row else None,
            "version": row[2][:50] if row else None,
            "user_count": user_count,
        }
    except Exception as exc:
        return {
            "success": False,
            "error_type": type(exc).__name__,
            "error_message": str(exc),
            "traceback": traceback.format_exc(),
        }


@router.get("/dashboard")
def dashboard(db: Session = Depends(get_db), _: Principal = Depends(require("read"))) -> dict:
    active = select(Watch).where(Watch.archived_at.is_(None))
    watches = db.scalars(active).all()
    by_status: dict[str, int] = {s: 0 for s in STATUS_LABELS}
    for w in watches:
        by_status[w.status] = by_status.get(w.status, 0) + 1
    ids_active = [w.id for w in watches if w.status not in ("sold", "withdrawn")]
    awaiting_processing = db.scalar(
        select(func.count(func.distinct(Asset.watch_id))).where(
            Asset.removed_at.is_(None), Asset.pipeline_status.in_(("uploaded", "queued", "processing")),
            Asset.watch_id.in_(ids_active))) or 0
    images_review = db.scalar(select(func.count()).select_from(Asset).where(
        Asset.removed_at.is_(None), Asset.current_render_id.is_not(None),
        Asset.review_status.in_(("pending", "regenerate_requested")), Asset.watch_id.in_(ids_active))) or 0
    privacy = db.scalar(select(func.count()).select_from(Asset).where(
        Asset.removed_at.is_(None), Asset.safety_status.in_(("needs_review", "failed", "ocr_unavailable")),
        Asset.watch_id.in_(ids_active))) or 0
    awaiting_approval = 0
    wmap = {w.id: w for w in watches}
    for c in db.scalars(select(ChannelCopy).where(ChannelCopy.watch_id.in_(ids_active))):
        w = wmap.get(c.watch_id)
        if (w and w.status not in MARKET_STATUSES and c.channel in enabled_channels(db, w)
                and not approval_valid(db, w, "channel", c.channel)):
            awaiting_approval += 1
    published = db.scalar(select(func.count()).select_from(ChannelListing)
                          .where(ChannelListing.status.in_(("live", "manual_posted")))) or 0
    simulated = db.scalar(select(func.count()).select_from(ChannelListing).where(ChannelListing.status == "simulated")) or 0
    since = utcnow() - timedelta(days=14)
    failed_jobs = db.scalars(select(Job).where(Job.status == "failed", Job.finished_at >= since)
                             .order_by(Job.finished_at.desc()).limit(10)).all()
    failed_listings = db.scalar(select(func.count()).select_from(ChannelListing)
                                .where(ChannelListing.status.in_(("failed", "sync_failed")))) or 0
    open_tasks = db.scalar(select(func.count()).select_from(ManualTask).where(ManualTask.status == "open")) or 0
    running = db.scalars(select(Job).where(Job.status.in_(("pending", "running"))).order_by(Job.created_at).limit(10)).all()
    recent = db.scalars(select(AuditEvent).order_by(AuditEvent.at.desc(), AuditEvent.id.desc()).limit(14)).all()
    sku = {w.id: w.sku for w in watches}
    attention = [watch_summary(db, w) for w in sorted(watches, key=lambda x: x.updated_at, reverse=True)
                 if w.status in ("awaiting_review", "processing")][:6]
    inventory_value = sum(float(w.price_sgd or 0) for w in watches if w.status not in ("sold", "withdrawn"))
    return {
        "counts": {
            "total": len(watches),
            "available": sum(1 for w in watches if w.status not in MARKET_STATUSES),
            "reserved": by_status.get("reserved", 0),
            "sold": by_status.get("sold", 0),
            "withdrawn": by_status.get("withdrawn", 0),
            "awaiting_processing": awaiting_processing,
            "images_awaiting_review": images_review,
            "privacy_checks": privacy,
            "listings_awaiting_approval": awaiting_approval,
            "published_listings": published,
            "simulated_listings": simulated,
            "failed": len(failed_jobs) + failed_listings,
            "open_manual_tasks": open_tasks,
        },
        "by_status": by_status,
        "inventory_value_sgd": round(inventory_value, 2),
        "attention": attention,
        "running_jobs": [{**job_view(j), "sku": sku.get(j.watch_id)} for j in running],
        "failed_jobs": [{**job_view(j), "sku": sku.get(j.watch_id)} for j in failed_jobs],
        "recent_activity": [{"id": e.id, "at": iso(e.at), "actor": e.actor, "action": e.action, "summary": e.summary,
                             "watch_id": e.watch_id, "sku": sku.get(e.watch_id)} for e in recent],
    }


# ---- jobs ----------------------------------------------------------------------------------------
@router.get("/jobs")
def list_jobs(status: str | None = None, watch_id: str | None = None, limit: int = Query(default=100, le=500),
              db: Session = Depends(get_db), _: Principal = Depends(require("read"))) -> dict:
    stmt = select(Job).order_by(Job.created_at.desc())
    if status:
        stmt = stmt.where(Job.status.in_(status.split(",")))
    if watch_id:
        stmt = stmt.where(Job.watch_id == watch_id)
    sku = {w.id: w.sku for w in db.scalars(select(Watch))}
    return {"items": [{**job_view(j), "sku": sku.get(j.watch_id)} for j in db.scalars(stmt.limit(limit))]}


@router.get("/jobs/{job_id}")
def get_job(job_id: str, db: Session = Depends(get_db), _: Principal = Depends(require("read"))) -> dict:
    j = db.get(Job, job_id)
    if j is None:
        raise NotFound("Job not found.")
    return job_view(j)


@router.post("/jobs/{job_id}/retry")
def retry_job(job_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require("process"))) -> dict:
    j = db.get(Job, job_id)
    if j is None:
        raise NotFound("Job not found.")
    if j.type in ("publish_channel", "sync_channel") and "publish" not in principal.scopes:
        raise AppError("Retrying a publishing job needs the publish permission.")
    queue.retry(db, j)
    audit.record(db, principal.actor, "job_retried", f"Retried {j.type}", entity_type="job", entity_id=j.id,
                 watch_id=j.watch_id)
    db.commit()
    return job_view(j)


@router.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require("process"))) -> dict:
    j = db.get(Job, job_id)
    if j is None:
        raise NotFound("Job not found.")
    queue.cancel(db, j)
    audit.record(db, principal.actor, "job_cancelled", f"Cancelled {j.type}", entity_type="job", entity_id=j.id,
                 watch_id=j.watch_id)
    db.commit()
    return job_view(j)


# ---- activity ------------------------------------------------------------------------------------
@router.get("/activity")
def activity(q: str | None = Query(default=None, max_length=100), action: str | None = None,
             before_id: int | None = None, limit: int = Query(default=100, le=500), db: Session = Depends(get_db),
             _: Principal = Depends(require("read"))) -> dict:
    stmt = select(AuditEvent).order_by(AuditEvent.id.desc())
    if q:
        stmt = stmt.where(AuditEvent.summary.ilike(f"%{q}%") | AuditEvent.actor.ilike(f"%{q}%"))
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if before_id:
        stmt = stmt.where(AuditEvent.id < before_id)
    rows = db.scalars(stmt.limit(limit)).all()
    sku = {w.id: w.sku for w in db.scalars(select(Watch))}
    return {"items": [{"id": e.id, "at": iso(e.at), "actor": e.actor, "action": e.action, "summary": e.summary,
                       "watch_id": e.watch_id, "sku": sku.get(e.watch_id), "entity_type": e.entity_type,
                       "detail": e.detail} for e in rows]}


# ---- inbox ---------------------------------------------------------------------------------------
class InboxImport(BaseModel):
    source: str = Field(max_length=40)
    refs: list[str] = Field(min_length=1, max_length=200)
    watch_id: str | None = None


@router.get("/inbox")
def inbox(db: Session = Depends(get_db), _: Principal = Depends(require("read"))) -> dict:
    out = []
    skus = {w.sku.upper(): w for w in db.scalars(select(Watch).where(Watch.archived_at.is_(None)))}
    for src in available_sources():
        try:
            items = src.list_pending()
        except Exception as e:  # noqa: BLE001
            out.append({"source": src.name, "error": str(e)[:300], "items": []})
            continue
        out.append({"source": src.name, "items": [
            {"ref": i.ref, "name": i.name, "size": i.size, "group": i.group,
             "matched_watch": ({"id": skus[i.group.upper()].id, "sku": skus[i.group.upper()].sku}
                               if i.group and i.group.upper() in skus else None)} for i in items]})
    from app.config import get_settings

    return {"sources": out, "local_folder": str(get_settings().inbox_dir)}


@router.post("/inbox/import")
def inbox_import(body: InboxImport, db: Session = Depends(get_db), principal: Principal = Depends(require("intake"))) -> dict:
    from app.api.assets import queue_processing
    from app.config import get_settings

    src = next((s for s in available_sources() if s.name == body.source), None)
    if src is None:
        raise AppError("That inbox is not available.")
    pending = {i.ref: i for i in src.list_pending()}
    created: dict[str, Watch] = {}
    results = []
    for ref in body.refs:
        item: IncomingFile | None = pending.get(ref)
        if item is None:
            results.append({"ref": ref, "status": "missing"})
            continue
        watch = db.get(Watch, body.watch_id) if body.watch_id else None
        if watch is None and item.group:
            watch = db.scalar(select(Watch).where(func.upper(Watch.sku) == item.group.upper()))
            if watch is None:
                watch = created.get(item.group)
                if watch is None:
                    watch = Watch(sku=next_sku(db, "Unidentified"), brand="Unidentified", model=item.group[:200],
                                  created_by=principal.actor, internal_notes=f"Created from inbox folder '{item.group}'.")
                    db.add(watch)
                    db.flush()
                    created[item.group] = watch
                    audit.record(db, principal.actor, "watch_created", f"Created {watch.sku} from inbox folder",
                                 entity_type="watch", entity_id=watch.id, watch_id=watch.id)
        if watch is None:
            results.append({"ref": ref, "status": "needs_watch", "message": "Choose which watch this photo belongs to."})
            continue
        res = ingest_image(db, watch, src.fetch(item), item.name, source=src.name, actor=principal.actor)
        if res.status in ("added", "duplicate"):
            src.mark_imported(item)
        if res.status == "added" and get_settings().auto_process_uploads:
            res.asset.pipeline_status = "queued"
            queue_processing(db, res.asset, principal.actor)
        results.append({"ref": ref, "status": res.status, "message": res.message, "watch_id": watch.id})
    db.commit()
    return {"results": results, "created_watches": [{"id": w.id, "sku": w.sku} for w in created.values()]}
