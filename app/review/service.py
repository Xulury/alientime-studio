"""Review decisions with gates. Every approval is bound to a content hash (see approvals.py)."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.copywriter.channels import CHANNELS
from app.core import audit
from app.core.errors import GateFailed
from app.core.lifecycle import refresh_status
from app.db.base import utcnow
from app.db.models import Asset, AssetRender, ChannelCopy, Watch
from app.intel.missing import fact_issues
from app.jobs.queue import enqueue
from app.review.approvals import (
    approval_valid,
    effective_gallery,
    enabled_channels,
    invalidate_stale,
    record_approval,
    revoke,
)
from app.review.readiness import image_blockers


def decide_image(db: Session, asset: Asset, decision: str, actor: str, note: str | None = None) -> None:
    watch = db.get(Watch, asset.watch_id)
    if decision == "approve":
        blockers = image_blockers(db, asset)
        if blockers:
            raise GateFailed("This image cannot be approved yet: " + " ".join(blockers), details={"blockers": blockers})
        if asset.safety_status == "clear":
            # Approving the final image is the human check of the redacted frame.
            asset.safety_status = "reviewed"
            asset.safety_reviewed_at = utcnow()
            asset.safety_reviewed_by = actor
        render = db.get(AssetRender, asset.current_render_id)
        db.flush()
        record_approval(db, watch, "image", asset.id, actor, content_ref=f"render v{render.version}", note=note,
                        snapshot={"filename": asset.original_filename, "render_version": render.version,
                                  "background": render.settings.get("background"),
                                  "fidelity_psnr": (render.fidelity.get("store_2x3") or {}).get("psnr_db")})
        asset.review_status = "approved"
        asset.review_note = note
        audit.record(db, actor, "image_approved", f"Approved {asset.original_filename} (render v{render.version})",
                     entity_type="asset", entity_id=asset.id, watch_id=watch.id)
    elif decision == "reject":
        revoke(db, watch, "image", asset.id, actor)
        asset.review_status = "rejected"
        asset.review_note = note
        audit.record(db, actor, "image_rejected", f"Rejected {asset.original_filename}" + (f": {note}" if note else ""),
                     entity_type="asset", entity_id=asset.id, watch_id=watch.id)
    elif decision == "regenerate":
        revoke(db, watch, "image", asset.id, actor)
        asset.review_status = "regenerate_requested"
        asset.review_note = note
        asset.pipeline_status = "queued"
        enqueue(db, "render_asset", watch_id=watch.id, asset_id=asset.id, created_by=actor,
                idempotency_key=f"render:{asset.id}:{utcnow().timestamp()}")
        audit.record(db, actor, "image_regeneration_requested",
                     f"Requested a new render of {asset.original_filename}" + (f": {note}" if note else ""),
                     entity_type="asset", entity_id=asset.id, watch_id=watch.id)
    elif decision == "reset":
        revoke(db, watch, "image", asset.id, actor)
        asset.review_status = "pending"
    db.flush()
    invalidate_stale(db, watch, "Image selection changed", actor)
    refresh_status(db, watch, actor)


def channel_gate(db: Session, watch: Watch, channel: str) -> list[str]:
    from app.copywriter.generator import copy_is_stale

    blockers = []
    copy = db.scalar(select(ChannelCopy).where(ChannelCopy.watch_id == watch.id, ChannelCopy.channel == channel))
    if copy is None:
        return ["Generate copy for this channel first."]
    blockers += [e["message"] for e in copy.validation.get("errors", [])]
    blockers += copy_is_stale(db, watch, copy)
    blockers += [i.message for i in fact_issues(db, watch) if i.severity == "blocker"]
    gallery = effective_gallery(db, watch)
    if not gallery:
        blockers.append("Select and render at least one studio image.")
    unapproved = [a.original_filename for a in gallery if not approval_valid(db, watch, "image", a.id)]
    if unapproved:
        blockers.append(f"Approve the images first ({len(unapproved)} pending).")
    return blockers


def approve_channel(db: Session, watch: Watch, channel: str, actor: str, note: str | None = None):
    if channel not in CHANNELS:
        raise GateFailed("Unknown channel.")
    blockers = channel_gate(db, watch, channel)
    if blockers:
        raise GateFailed(f"{CHANNELS[channel].name} cannot be approved yet.", details={"blockers": blockers})
    copy = db.scalar(select(ChannelCopy).where(ChannelCopy.watch_id == watch.id, ChannelCopy.channel == channel))
    gallery = effective_gallery(db, watch)
    a = record_approval(db, watch, "channel", channel, actor, content_ref=f"copy v{copy.version}", note=note,
                        snapshot={"version": copy.version, "title": copy.sections.get("title"),
                                  "excerpt": copy.rendered_text[:240], "generator": copy.generator,
                                  "images": [g.id for g in gallery][: CHANNELS[channel].max_images]})
    audit.record(db, actor, "channel_approved", f"Approved {CHANNELS[channel].name} copy v{copy.version}",
                 entity_type="approval", entity_id=a.id, watch_id=watch.id, detail={"channel": channel})
    refresh_status(db, watch, actor)
    return a


def revoke_channel(db: Session, watch: Watch, channel: str, actor: str) -> None:
    if revoke(db, watch, "channel", channel, actor):
        revoke(db, watch, "package", "package", actor)
        audit.record(db, actor, "approval_revoked", f"Approval withdrawn for {CHANNELS[channel].name}",
                     entity_type="watch", entity_id=watch.id, watch_id=watch.id)
        refresh_status(db, watch, actor)


def approve_package(db: Session, watch: Watch, actor: str, note: str | None = None) -> dict:
    """Approve every gallery image and every channel with copy in one action — all gates first, all or nothing."""
    gallery = effective_gallery(db, watch)
    copies = {c.channel: c for c in db.scalars(select(ChannelCopy).where(ChannelCopy.watch_id == watch.id))}
    channels = [c for c in enabled_channels(db, watch) if c in copies]
    problems: list[str] = []
    if not gallery:
        problems.append("Select and render at least one studio image.")
    if not channels:
        problems.append("Generate listing copy first.")
    for a in gallery:
        for b in image_blockers(db, a):
            problems.append(f"{a.original_filename}: {b}")
    from app.copywriter.generator import copy_is_stale

    for ch in channels:
        c = copies[ch]
        for e in c.validation.get("errors", []):
            problems.append(f"{CHANNELS[ch].name}: {e['message']}")
        for r in copy_is_stale(db, watch, c):
            problems.append(f"{CHANNELS[ch].name}: {r}")
    problems += [i.message for i in fact_issues(db, watch) if i.severity == "blocker"]
    if problems:
        raise GateFailed("The package cannot be approved yet.", details={"blockers": list(dict.fromkeys(problems))})
    for a in gallery:
        if not approval_valid(db, watch, "image", a.id):
            decide_image(db, a, "approve", actor, note)
    for ch in channels:
        if not approval_valid(db, watch, "channel", ch):
            approve_channel(db, watch, ch, actor, note)
    db.flush()
    pkg = record_approval(db, watch, "package", "package", actor, note=note, content_ref=f"content v{watch.content_version}",
                          snapshot={"images": [a.id for a in gallery], "channels": channels})
    audit.record(db, actor, "package_approved",
                 f"Approved the full package: {len(gallery)} image(s), {len(channels)} channel(s)",
                 entity_type="approval", entity_id=pkg.id, watch_id=watch.id)
    refresh_status(db, watch, actor)
    return {"images": len(gallery), "channels": channels}
