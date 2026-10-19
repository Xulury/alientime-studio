"""Review centre: queue, approvals (channel, package), revocation, approval requests."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.api.views import watch_summary
from app.api.watches import get_watch
from app.config import get_settings
from app.core import audit
from app.core.errors import AppError
from app.db.base import get_db, iso
from app.db.models import Approval, Watch
from app.review.readiness import watch_readiness
from app.review.service import approve_channel, approve_package, revoke_channel

router = APIRouter(prefix="/api", tags=["review"])


class ApprovalIn(BaseModel):
    scope: Literal["channel", "package"]
    target: str | None = Field(default=None, max_length=40)
    note: str | None = Field(default=None, max_length=1000)


@router.get("/review/queue")
def review_queue(db: Session = Depends(get_db), _: Principal = Depends(require("read"))) -> dict:
    items = []
    for w in db.scalars(select(Watch).where(Watch.archived_at.is_(None),
                                            Watch.status.in_(("draft", "processing", "awaiting_review", "approved",
                                                              "published")))
                        .order_by(Watch.updated_at.desc())):
        r = watch_readiness(db, w)
        s = r["summary"]
        pending_images = s["images_total"] - s["images_approved"]
        pending_channels = s["channels_with_copy"] - s["channels_approved"]
        if w.status == "draft" and not s["images_total"] and not s["channels_with_copy"]:
            continue
        if pending_images == 0 and pending_channels == 0 and r["package"]["approved"]:
            continue
        items.append({**watch_summary(db, w), "pending_images": pending_images, "pending_channels": pending_channels,
                      "fact_blockers": s["fact_blockers"], "package_approved": r["package"]["approved"],
                      "open_suggestions": len(r["suggestions"])})
    return {"items": items}


@router.get("/watches/{watch_id}/review")
def review_detail(watch_id: str, db: Session = Depends(get_db), _: Principal = Depends(require("read"))) -> dict:
    w = get_watch(db, watch_id)
    return {"watch": watch_summary(db, w), "readiness": watch_readiness(db, w)}


@router.post("/watches/{watch_id}/approvals")
def approve(watch_id: str, body: ApprovalIn, db: Session = Depends(get_db),
            principal: Principal = Depends(require("approve"))) -> dict:
    w = get_watch(db, watch_id, include_archived=False)
    if w.status in ("sold", "withdrawn"):
        raise AppError(f"This watch is {w.status}.")
    if body.scope == "channel":
        if not body.target:
            raise AppError("Choose a channel.")
        approve_channel(db, w, body.target, principal.actor, body.note)
        result = {"approved": body.target}
    else:
        result = approve_package(db, w, principal.actor, body.note)
    db.commit()
    return {"result": result, "readiness": watch_readiness(db, w)}


@router.delete("/watches/{watch_id}/approvals/channel/{channel}")
def revoke(watch_id: str, channel: str, db: Session = Depends(get_db),
           principal: Principal = Depends(require("approve"))) -> dict:
    w = get_watch(db, watch_id, include_archived=False)
    revoke_channel(db, w, channel, principal.actor)
    db.commit()
    return {"ok": True}


@router.get("/watches/{watch_id}/approvals")
def approval_history(watch_id: str, db: Session = Depends(get_db), _: Principal = Depends(require("read"))) -> dict:
    w = get_watch(db, watch_id)
    rows = db.scalars(select(Approval).where(Approval.watch_id == w.id).order_by(Approval.approved_at.desc()).limit(200))
    return {"items": [{"id": a.id, "scope": a.scope, "target": a.target, "status": a.status, "approved_by": a.approved_by,
                       "approved_at": iso(a.approved_at), "content_ref": a.content_ref, "hash": a.content_hash[:12],
                       "invalidated_at": iso(a.invalidated_at), "invalidated_reason": a.invalidated_reason,
                       "note": a.note, "snapshot": a.snapshot} for a in rows]}


@router.post("/watches/{watch_id}/request-approval")
def request_approval(watch_id: str, db: Session = Depends(get_db),
                     principal: Principal = Depends(require("request_approval"))) -> dict:
    from app.integrations.messaging import Telegram

    w = get_watch(db, watch_id, include_archived=False)
    r = watch_readiness(db, w)
    s = r["summary"]
    url = f"{get_settings().studio_base_url.rstrip('/')}/watches/{w.id}/review"
    text = (f"Approval needed: {w.sku} {w.brand} {w.model}\n"
            f"Images approved {s['images_approved']}/{s['images_total']}, channels approved "
            f"{s['channels_approved']}/{s['channels_with_copy']}, fact blockers {s['fact_blockers']}.\nReview: {url}")
    sent = False
    try:
        sent = Telegram().notify(text)
    except Exception:  # noqa: BLE001 - notification is best effort
        sent = False
    audit.record(db, principal.actor, "approval_requested", "Approval requested" + (" (Telegram sent)" if sent else ""),
                 entity_type="watch", entity_id=w.id, watch_id=w.id)
    db.commit()
    return {"review_url": url, "notified": sent, "summary": s, "package_blockers": r["package"]["blockers"]}
