"""Watch lifecycle state machine.

Two kinds of status:
* Work statuses (draft → processing → awaiting_review → approved → published) are derived by the
  system from what has actually happened (photos processed, approvals given, listings live).
* Market statuses (reserved, sold, withdrawn) are set by a person and hold until a person changes them.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.db.base import utcnow
from app.db.models import Asset, ChannelCopy, ChannelListing, Job, Watch

WORK_STATUSES = ("draft", "processing", "awaiting_review", "approved", "published")
MARKET_STATUSES = ("reserved", "sold", "withdrawn")
ALL_STATUSES = WORK_STATUSES + MARKET_STATUSES

STATUS_LABELS = {
    "draft": "Draft",
    "processing": "Processing",
    "awaiting_review": "Awaiting review",
    "approved": "Approved",
    "published": "Published",
    "reserved": "Reserved",
    "sold": "Sold",
    "withdrawn": "Withdrawn",
}

# Which market actions a person may take from each status.
ALLOWED_ACTIONS: dict[str, set[str]] = {
    "draft": {"reserved", "sold", "withdrawn"},
    "processing": {"reserved", "sold", "withdrawn"},
    "awaiting_review": {"reserved", "sold", "withdrawn"},
    "approved": {"reserved", "sold", "withdrawn"},
    "published": {"reserved", "sold", "withdrawn"},
    "reserved": {"available", "sold", "withdrawn"},
    "withdrawn": {"available", "sold"},
    "sold": {"reopen"},
}

LIVE_LISTING_STATUSES = ("live", "manual_posted")


class TransitionError(ValueError):
    pass


@dataclass
class TransitionResult:
    previous: str
    current: str
    changed: bool


def availability(status: str) -> str:
    if status in MARKET_STATUSES:
        return status
    return "available"


def allowed_actions(status: str) -> list[str]:
    return sorted(ALLOWED_ACTIONS.get(status, set()))


def derive_work_status(db: Session, watch: Watch) -> str:
    """Compute the work status from facts in the database."""
    from app.review.approvals import package_approval_valid  # local import: avoids a cycle

    live = db.scalar(
        select(ChannelListing.id).where(
            ChannelListing.watch_id == watch.id, ChannelListing.status.in_(LIVE_LISTING_STATUSES)
        ).limit(1)
    )
    if live:
        return "published"
    if package_approval_valid(db, watch):
        return "approved"
    busy = db.scalar(
        select(Job.id).where(
            Job.watch_id == watch.id,
            Job.status.in_(("pending", "running")),
            Job.type.in_(("process_asset", "render_asset", "safety_scan", "segment_asset", "ai_tag_assets")),
        ).limit(1)
    )
    if busy:
        return "processing"
    has_output = db.scalar(
        select(Asset.id).where(Asset.watch_id == watch.id, Asset.removed_at.is_(None),
                               Asset.current_render_id.is_not(None)).limit(1)
    ) or db.scalar(select(ChannelCopy.id).where(ChannelCopy.watch_id == watch.id).limit(1))
    if has_output:
        return "awaiting_review"
    return "draft"


def refresh_status(db: Session, watch: Watch, actor: str = "system") -> TransitionResult:
    """Re-derive the work status unless a person has put the watch on hold (reserved/sold/withdrawn)."""
    prev = watch.status
    if prev in MARKET_STATUSES:
        return TransitionResult(prev, prev, False)
    new = derive_work_status(db, watch)
    if new != prev:
        watch.status = new
        watch.status_changed_at = utcnow()
        audit.record(db, actor, "status_changed", f"{STATUS_LABELS[prev]} → {STATUS_LABELS[new]}",
                     entity_type="watch", entity_id=watch.id, watch_id=watch.id,
                     detail={"from": prev, "to": new, "automatic": True})
    return TransitionResult(prev, new, new != prev)


def apply_market_action(db: Session, watch: Watch, action: str, actor: str, note: str | None = None) -> TransitionResult:
    """A person reserves, sells, withdraws, makes available again, or reopens a watch."""
    prev = watch.status
    if action not in ALLOWED_ACTIONS.get(prev, set()):
        raise TransitionError(f"A {STATUS_LABELS.get(prev, prev).lower()} watch cannot be changed to '{action}'.")
    if action in MARKET_STATUSES:
        watch.status = action
    else:  # available / reopen → back to the derived work status
        watch.status = "draft"
        watch.status = derive_work_status(db, watch)
    watch.status_changed_at = utcnow()
    audit.record(db, actor, "status_changed",
                 f"{STATUS_LABELS[prev]} → {STATUS_LABELS[watch.status]}" + (f" ({note})" if note else ""),
                 entity_type="watch", entity_id=watch.id, watch_id=watch.id,
                 detail={"from": prev, "to": watch.status, "action": action, "note": note})
    return TransitionResult(prev, watch.status, prev != watch.status)
