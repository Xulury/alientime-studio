"""Watch inventory: list, create, read, update, archive, lifecycle actions, gallery."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.api.schemas import GalleryIn, StatusChange, WatchCreate, WatchUpdate
from app.api.views import asset_view, job_view, watch_record, watch_summary
from app.core import audit
from app.core.errors import AppError, Conflict, NotFound
from app.core.lifecycle import MARKET_STATUSES, TransitionError, apply_market_action, availability, refresh_status
from app.core.sku import next_sku, normalise_sku
from app.db.base import get_db, iso, utcnow
from app.db.models import Asset, AuditEvent, Job, SpecRecord, Watch
from app.review.approvals import invalidate_stale

router = APIRouter(prefix="/api/watches", tags=["watches"])

MATERIAL_FIELDS = {
    "brand", "model", "reference", "year", "condition", "condition_notes", "price_sgd", "price_usd",
    "box_papers", "box_papers_notes", "custody", "description", "extra_facts", "spec_id",
}
SORTS = {
    "updated": Watch.updated_at, "created": Watch.created_at, "sku": Watch.sku, "brand": Watch.brand,
    "price": Watch.price_sgd, "status": Watch.status,
}


def get_watch(db: Session, watch_id: str, include_archived: bool = True) -> Watch:
    w = db.get(Watch, watch_id)
    if w is None or (w.archived_at is not None and not include_archived):
        raise NotFound("Watch not found.")
    return w


@router.get("")
def list_watches(
    q: str | None = Query(default=None, max_length=120),
    status: list[str] | None = Query(default=None),
    availability_: Literal["available", "reserved", "sold", "withdrawn"] | None = Query(default=None, alias="availability"),
    brand: str | None = Query(default=None, max_length=120),
    custody: str | None = None,
    consignment: bool | None = None,
    archived: bool = False,
    sort: Literal["updated", "created", "sku", "brand", "price", "status"] = "updated",
    order: Literal["asc", "desc"] = "desc",
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=48, ge=1, le=200),
    db: Session = Depends(get_db),
    _: Principal = Depends(require("read")),
) -> dict:
    stmt = select(Watch)
    stmt = stmt.where(Watch.archived_at.is_not(None) if archived else Watch.archived_at.is_(None))
    if q:
        like = f"%{q.strip()}%"
        stmt = stmt.where(or_(Watch.sku.ilike(like), Watch.brand.ilike(like), Watch.model.ilike(like),
                              Watch.reference.ilike(like), Watch.consignor_name.ilike(like)))
    if status:
        stmt = stmt.where(Watch.status.in_(status))
    if availability_:
        if availability_ == "available":
            stmt = stmt.where(Watch.status.not_in(MARKET_STATUSES))
        else:
            stmt = stmt.where(Watch.status == availability_)
    if brand:
        stmt = stmt.where(func.lower(Watch.brand) == brand.strip().lower())
    if custody:
        stmt = stmt.where(Watch.custody == custody)
    if consignment is not None:
        stmt = stmt.where(Watch.is_consignment.is_(consignment))
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    col = SORTS[sort]
    stmt = stmt.order_by(col.asc() if order == "asc" else col.desc(), Watch.sku)
    rows = db.scalars(stmt.offset((page - 1) * page_size).limit(page_size)).all()
    brands = db.scalars(select(Watch.brand).where(Watch.archived_at.is_(None)).distinct().order_by(Watch.brand)).all()
    return {"items": [watch_summary(db, w) for w in rows], "total": total, "page": page, "page_size": page_size,
            "brands": brands}


@router.get("/next-sku")
def suggest_sku(brand: str = Query(min_length=1, max_length=120), db: Session = Depends(get_db),
                _: Principal = Depends(require("read"))) -> dict:
    return {"sku": next_sku(db, brand)}


@router.get("/by-sku/{sku}")
def by_sku(sku: str, db: Session = Depends(get_db), _: Principal = Depends(require("read"))) -> dict:
    w = db.scalar(select(Watch).where(func.upper(Watch.sku) == sku.strip().upper()))
    if w is None:
        raise NotFound(f"No watch with SKU {sku}.")
    return {"id": w.id, "sku": w.sku, "status": w.status}


def _apply_fields(w: Watch, data: dict) -> set[str]:
    changed: set[str] = set()
    for k, v in data.items():
        if k == "sku":
            continue
        if k == "extra_facts" and v is not None:
            prov = (w.extra_facts or {}).get("_provenance", {})
            v = {**v, "_provenance": prov}
        if getattr(w, k) != v:
            setattr(w, k, v)
            changed.add(k)
    if "fx_rate_sgd_usd" in changed:
        w.fx_updated_at = utcnow()
    return changed


@router.post("", status_code=201)
def create_watch(body: WatchCreate, db: Session = Depends(get_db),
                 principal: Principal = Depends(require("intake"))) -> dict:
    data = body.model_dump(exclude_unset=True)
    try:
        sku = normalise_sku(data.pop("sku")) if data.get("sku") else next_sku(db, body.brand)
    except ValueError as e:
        raise AppError(str(e), code="invalid_sku")
    if db.scalar(select(Watch.id).where(func.upper(Watch.sku) == sku)):
        raise Conflict(f"SKU {sku} is already used by another watch.")
    if data.get("spec_id") and db.get(SpecRecord, data["spec_id"]) is None:
        raise AppError("The selected spec record does not exist.")
    w = Watch(sku=sku, brand=body.brand, model=body.model, created_by=principal.actor)
    _apply_fields(w, {k: v for k, v in data.items() if k not in ("brand", "model")})
    db.add(w)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise Conflict(f"SKU {sku} is already used by another watch.")
    audit.record(db, principal.actor, "watch_created", f"Created {sku} — {w.brand} {w.model}",
                 entity_type="watch", entity_id=w.id, watch_id=w.id, ip=principal.ip)
    db.commit()
    return watch_record(w)


@router.get("/{watch_id}")
def watch_detail(watch_id: str, db: Session = Depends(get_db), _: Principal = Depends(require("read"))) -> dict:
    from app.review.readiness import watch_readiness

    w = get_watch(db, watch_id)
    assets = db.scalars(select(Asset).where(Asset.watch_id == w.id, Asset.removed_at.is_(None))
                        .order_by(Asset.sort_order)).all()
    jobs = db.scalars(select(Job).where(Job.watch_id == w.id).order_by(Job.created_at.desc()).limit(30)).all()
    return {
        "watch": watch_record(w),
        "summary": watch_summary(db, w),
        "assets": [asset_view(db, a) for a in assets],
        "jobs": [job_view(j) for j in jobs],
        "readiness": watch_readiness(db, w),
    }


@router.patch("/{watch_id}")
def update_watch(watch_id: str, body: WatchUpdate, db: Session = Depends(get_db),
                 principal: Principal = Depends(require("intake"))) -> dict:
    w = get_watch(db, watch_id, include_archived=False)
    data = body.model_dump(exclude_unset=True)
    if "brand" in data and not data["brand"]:
        raise AppError("Brand cannot be empty.")
    if "model" in data and not data["model"]:
        raise AppError("Model cannot be empty.")
    if data.get("sku"):
        try:
            sku = normalise_sku(data["sku"])
        except ValueError as e:
            raise AppError(str(e), code="invalid_sku")
        if sku != w.sku:
            if db.scalar(select(Watch.id).where(func.upper(Watch.sku) == sku, Watch.id != w.id)):
                raise Conflict(f"SKU {sku} is already used by another watch.")
            audit.record(db, principal.actor, "sku_changed", f"SKU {w.sku} → {sku}", entity_type="watch",
                         entity_id=w.id, watch_id=w.id, ip=principal.ip)
            w.sku = sku
    if data.get("spec_id") and db.get(SpecRecord, data["spec_id"]) is None:
        raise AppError("The selected spec record does not exist.")
    before = {k: getattr(w, k) for k in data if k != "sku"}
    changed = _apply_fields(w, data)
    if not changed:
        db.commit()
        return watch_record(w)
    material = sorted(changed & MATERIAL_FIELDS)
    if material:
        w.content_version += 1
    w.updated_at = utcnow()
    db.flush()
    detail = {k: {"from": str(before.get(k)) if before.get(k) is not None else None,
                  "to": str(getattr(w, k)) if getattr(w, k) is not None else None}
              for k in changed if k not in ("internal_notes", "consignor_contact")}
    audit.record(db, principal.actor, "watch_updated", "Edited " + ", ".join(sorted(changed)),
                 entity_type="watch", entity_id=w.id, watch_id=w.id, detail=detail, ip=principal.ip)
    if material:
        invalidate_stale(db, w, "Product facts edited (" + ", ".join(material) + ")", principal.actor)
        refresh_status(db, w, principal.actor)
    db.commit()
    return watch_record(w)


@router.delete("/{watch_id}")
def archive_watch(watch_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require("intake"))) -> dict:
    from app.db.models import ChannelListing

    w = get_watch(db, watch_id, include_archived=False)
    live = db.scalar(select(ChannelListing.id).where(ChannelListing.watch_id == w.id,
                                                     ChannelListing.status.in_(("live", "manual_posted"))).limit(1))
    if live:
        raise AppError("This watch is still listed on at least one channel. Withdraw or mark it sold first.",
                       code="still_listed")
    w.archived_at = utcnow()
    audit.record(db, principal.actor, "watch_archived", f"Archived {w.sku}. Photos and records are kept.",
                 entity_type="watch", entity_id=w.id, watch_id=w.id, ip=principal.ip)
    db.commit()
    return {"ok": True, "archived": True}


@router.post("/{watch_id}/restore")
def restore_watch(watch_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require("intake"))) -> dict:
    w = get_watch(db, watch_id)
    w.archived_at = None
    audit.record(db, principal.actor, "watch_restored", f"Restored {w.sku}", entity_type="watch",
                 entity_id=w.id, watch_id=w.id, ip=principal.ip)
    db.commit()
    return watch_record(w)


@router.post("/{watch_id}/status")
def change_status(watch_id: str, body: StatusChange, db: Session = Depends(get_db),
                  principal: Principal = Depends(require("lifecycle"))) -> dict:
    from app.publish.lifecycle_sync import propagate_market_status

    w = get_watch(db, watch_id, include_archived=False)
    try:
        result = apply_market_action(db, w, body.action, principal.actor, body.note)
    except TransitionError as e:
        raise AppError(str(e), code="invalid_transition")
    db.flush()
    sync = propagate_market_status(db, w, body.action, principal.actor)
    db.commit()
    return {"watch": watch_record(w), "previous": result.previous, "sync": sync,
            "availability": availability(w.status)}


@router.put("/{watch_id}/gallery")
def set_gallery(watch_id: str, body: GalleryIn, db: Session = Depends(get_db),
                principal: Principal = Depends(require("intake"))) -> dict:
    w = get_watch(db, watch_id, include_archived=False)
    valid = {a.id for a in db.scalars(select(Asset).where(Asset.watch_id == w.id, Asset.removed_at.is_(None)))}
    ids = [a for a in dict.fromkeys(body.asset_ids) if a in valid]
    if body.hero_asset_id and body.hero_asset_id not in valid:
        raise AppError("The hero photo must belong to this watch.")
    if ids != (w.gallery or []) or body.hero_asset_id != w.hero_asset_id:
        w.gallery = ids
        w.hero_asset_id = body.hero_asset_id or (ids[0] if ids else None)
        db.flush()
        audit.record(db, principal.actor, "gallery_changed", f"Final image selection set ({len(ids)} photos)",
                     entity_type="watch", entity_id=w.id, watch_id=w.id, ip=principal.ip)
        invalidate_stale(db, w, "Final image selection changed", principal.actor)
    db.commit()
    return {"gallery": w.gallery, "hero_asset_id": w.hero_asset_id}


class ChannelSelection(BaseModel):
    channels: list[str] | None = None


@router.put("/{watch_id}/channels")
def set_channels(watch_id: str, body: ChannelSelection, db: Session = Depends(get_db),
                 principal: Principal = Depends(require("intake"))) -> dict:
    """Choose which channels this watch is listed on (None = all channels enabled in Settings)."""
    from app.copywriter.channels import CHANNELS

    w = get_watch(db, watch_id, include_archived=False)
    chosen = None if body.channels is None else [c for c in dict.fromkeys(body.channels) if c in CHANNELS]
    if chosen != w.channels:
        w.channels = chosen
        db.flush()
        audit.record(db, principal.actor, "channels_changed",
                     "Channels for this watch: " + ("all enabled" if chosen is None else ", ".join(chosen) or "none"),
                     entity_type="watch", entity_id=w.id, watch_id=w.id)
        invalidate_stale(db, w, "Channel selection changed", principal.actor)
        refresh_status(db, w, principal.actor)
    db.commit()
    return {"channels": w.channels}


@router.get("/{watch_id}/activity")
def watch_activity(watch_id: str, limit: int = Query(default=100, le=500), db: Session = Depends(get_db),
                   _: Principal = Depends(require("read"))) -> dict:
    get_watch(db, watch_id)
    rows = db.scalars(select(AuditEvent).where(AuditEvent.watch_id == watch_id)
                      .order_by(AuditEvent.at.desc(), AuditEvent.id.desc()).limit(limit)).all()
    return {"items": [{"id": r.id, "at": iso(r.at), "actor": r.actor, "action": r.action, "summary": r.summary,
                       "detail": r.detail} for r in rows]}
