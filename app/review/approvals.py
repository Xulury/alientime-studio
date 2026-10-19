"""Versioned approvals.

An approval stores the SHA-256 *content hash* of exactly what was approved:
  * image   – the render files (master + every platform size), redaction version and safety state
  * channel – the copy sections and text, the fact values used, and the hashes of the gallery images
  * package – the channel hashes plus the gallery

An approval is valid only while the current content still produces the same hash. Any material edit
(facts, copy, image re-render, redaction change, gallery order) changes the hash, and
`invalidate_stale()` marks the old approval invalidated with a reason, recorded in the audit log.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.settings_store import get_setting
from app.db.base import utcnow
from app.db.models import Approval, Asset, AssetRender, ChannelCopy, Watch

PHOTO_TYPE_ORDER = ["dial_front", "side_profile", "crown_side", "clasp", "strap", "caseback", "movement",
                    "detail", "box_papers", "unclassified"]
SAFE_FOR_PUBLISH = ("clear", "reviewed")


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str, ensure_ascii=False)


def digest(obj: Any) -> str:
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


# ---- gallery -------------------------------------------------------------------------------------
def effective_gallery(db: Session, watch: Watch) -> list[Asset]:
    """Final image selection: explicit order if set, else selected frames with renders."""
    assets = {a.id: a for a in db.scalars(select(Asset).where(Asset.watch_id == watch.id, Asset.removed_at.is_(None)))}
    usable = {aid: a for aid, a in assets.items() if a.current_render_id and a.review_status != "rejected"}
    if watch.gallery:
        ordered = [usable[a] for a in watch.gallery if a in usable]
        if ordered:
            return ordered
    chosen = [a for a in usable.values() if (a.selection_override if a.selection_override is not None else a.selected)]

    def key(a: Asset):
        hero = 0 if a.id == watch.hero_asset_id else 1
        t = PHOTO_TYPE_ORDER.index(a.photo_type) if a.photo_type in PHOTO_TYPE_ORDER else len(PHOTO_TYPE_ORDER)
        return (hero, t, a.sort_order)

    return sorted(chosen, key=key)


# ---- hashes --------------------------------------------------------------------------------------
def image_hash(db: Session, asset: Asset) -> str | None:
    if not asset.current_render_id:
        return None
    render = db.get(AssetRender, asset.current_render_id)
    if render is None:
        return None
    return digest({
        "asset": asset.id,
        "render": render.id,
        "master": render.master_sha256,
        "variants": {k: v.get("sha256") for k, v in sorted((render.variants or {}).items())},
        "redaction_version": asset.redaction_version,
        "safety": asset.safety_status,
    })


def facts_hash(db: Session, watch: Watch) -> str:
    from app.intel.facts import confirmed_facts

    return digest(confirmed_facts(db, watch))


def gallery_signature(db: Session, watch: Watch) -> list[list[str | None]]:
    return [[a.id, image_hash(db, a)] for a in effective_gallery(db, watch)]


def channel_hash(db: Session, watch: Watch, copy: ChannelCopy) -> str:
    return digest({
        "channel": copy.channel,
        "sections": copy.sections,
        "text": copy.rendered_text,
        "facts": facts_hash(db, watch),
        "gallery": gallery_signature(db, watch),
    })


def enabled_channels(db: Session, watch: Watch | None = None) -> list[str]:
    """Channels switched on in Settings, narrowed to the ones chosen for this watch (if any)."""
    enabled = list(get_setting(db, "channels").get("enabled") or [])
    if watch is not None and watch.channels is not None:
        return [c for c in enabled if c in watch.channels]
    return enabled


def package_hash(db: Session, watch: Watch) -> str:
    copies = {c.channel: c for c in db.scalars(select(ChannelCopy).where(ChannelCopy.watch_id == watch.id))}
    chans = {ch: channel_hash(db, watch, copies[ch]) for ch in enabled_channels(db, watch) if ch in copies}
    return digest({"channels": chans, "gallery": gallery_signature(db, watch)})


def current_hash(db: Session, watch: Watch, scope: str, target: str) -> str | None:
    if scope == "image":
        asset = db.get(Asset, target)
        return image_hash(db, asset) if asset and asset.watch_id == watch.id else None
    if scope == "channel":
        copy = db.scalar(select(ChannelCopy).where(ChannelCopy.watch_id == watch.id, ChannelCopy.channel == target))
        return channel_hash(db, watch, copy) if copy else None
    if scope == "package":
        return package_hash(db, watch)
    return None


# ---- lookups -------------------------------------------------------------------------------------
def active_approval(db: Session, watch_id: str, scope: str, target: str) -> Approval | None:
    return db.scalar(select(Approval).where(Approval.watch_id == watch_id, Approval.scope == scope,
                                            Approval.target == target, Approval.status == "active")
                     .order_by(Approval.approved_at.desc()).limit(1))


def approval_valid(db: Session, watch: Watch, scope: str, target: str) -> bool:
    a = active_approval(db, watch.id, scope, target)
    if a is None:
        return False
    return a.content_hash == current_hash(db, watch, scope, target)


def package_approval_valid(db: Session, watch: Watch) -> bool:
    return approval_valid(db, watch, "package", "package")


def latest_approval(db: Session, watch_id: str, scope: str, target: str) -> Approval | None:
    return db.scalar(select(Approval).where(Approval.watch_id == watch_id, Approval.scope == scope,
                                            Approval.target == target)
                     .order_by(Approval.approved_at.desc()).limit(1))


def invalidate_stale(db: Session, watch: Watch, reason: str, actor: str = "system") -> list[Approval]:
    """Mark every active approval whose content changed as invalidated."""
    changed: list[Approval] = []
    for a in db.scalars(select(Approval).where(Approval.watch_id == watch.id, Approval.status == "active")):
        if a.content_hash != current_hash(db, watch, a.scope, a.target):
            a.status = "invalidated"
            a.invalidated_at = utcnow()
            a.invalidated_reason = reason
            changed.append(a)
            label = {"image": "Photo", "channel": f"{a.target} copy", "package": "Full package"}[a.scope]
            audit.record(db, actor, "approval_invalidated", f"{label} approval cleared: {reason}",
                         entity_type="approval", entity_id=a.id, watch_id=watch.id,
                         detail={"scope": a.scope, "target": a.target})
    if changed:
        for asset in db.scalars(select(Asset).where(Asset.watch_id == watch.id, Asset.review_status == "approved")):
            if not approval_valid(db, watch, "image", asset.id):
                asset.review_status = "pending"
    return changed


def record_approval(db: Session, watch: Watch, scope: str, target: str, actor: str, *,
                    snapshot: dict[str, Any], content_ref: str | None = None, note: str | None = None) -> Approval:
    h = current_hash(db, watch, scope, target)
    if h is None:
        raise ValueError("Nothing to approve yet.")
    for old in db.scalars(select(Approval).where(Approval.watch_id == watch.id, Approval.scope == scope,
                                                 Approval.target == target, Approval.status == "active")):
        old.status = "invalidated"
        old.invalidated_at = utcnow()
        old.invalidated_reason = "Replaced by a newer approval"
    a = Approval(watch_id=watch.id, scope=scope, target=target, content_hash=h, content_ref=content_ref,
                 snapshot=snapshot, approved_by=actor, note=note)
    db.add(a)
    db.flush()
    return a


def revoke(db: Session, watch: Watch, scope: str, target: str, actor: str) -> int:
    n = 0
    for a in db.scalars(select(Approval).where(Approval.watch_id == watch.id, Approval.scope == scope,
                                               Approval.target == target, Approval.status == "active")):
        a.status = "revoked"
        a.invalidated_at = utcnow()
        a.invalidated_reason = f"Revoked by {actor}"
        n += 1
    return n
