"""Publishing readiness: everything a person needs to see before approving and publishing."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.copywriter.channels import CHANNELS, SECTION_LABELS, channel_info
from app.db.base import iso
from app.db.models import Asset, AssetRender, ChannelCopy, ChannelListing, FactSuggestion, ManualTask, Watch
from app.intel.facts import fact_sheet
from app.intel.missing import fact_issues
from app.review.approvals import (
    SAFE_FOR_PUBLISH,
    approval_valid,
    effective_gallery,
    enabled_channels,
    latest_approval,
)

LISTING_LABELS = {
    "not_started": "Not published", "queued": "Queued", "publishing": "Publishing…", "live": "Live",
    "simulated": "Simulated (not live)", "manual_pending": "Waiting for you to post", "manual_posted": "Posted by you",
    "reserved": "Marked reserved", "sold": "Marked sold", "withdrawn": "Withdrawn", "failed": "Failed",
    "sync_failed": "Update failed", "update_pending": "Update queued",
}


def approval_view(a) -> dict | None:
    if a is None:
        return None
    return {"id": a.id, "status": a.status, "approved_by": a.approved_by, "approved_at": iso(a.approved_at),
            "invalidated_at": iso(a.invalidated_at), "invalidated_reason": a.invalidated_reason,
            "content_hash": a.content_hash[:12], "snapshot": a.snapshot}


def image_blockers(db: Session, a: Asset) -> list[str]:
    out = []
    render = db.get(AssetRender, a.current_render_id) if a.current_render_id else None
    if render is None:
        out.append("No studio image yet.")
    else:
        if not render.fidelity_passed:
            out.append("Fidelity check failed.")
        if a.render_stale:
            out.append("Edited since the last render; render again.")
    if a.safety_status not in SAFE_FOR_PUBLISH:
        out.append({"needs_review": "Check the redactions first.", "failed": "Redaction check failed.",
                    "ocr_unavailable": "Check this photo for serial numbers by eye first.",
                    "pending": "Privacy check has not run."}.get(a.safety_status, "Privacy check incomplete."))
    return out


def watch_readiness(db: Session, watch: Watch) -> dict[str, Any]:
    from app.copywriter.generator import build_context, copy_is_stale
    from app.publish.registry import channel_mode

    issues = fact_issues(db, watch)
    fact_blockers = [i for i in issues if i.severity == "blocker"]
    sheet = fact_sheet(db, watch)
    gallery = effective_gallery(db, watch)

    images = []
    for a in gallery:
        valid = approval_valid(db, watch, "image", a.id)
        images.append({
            "asset_id": a.id, "filename": a.original_filename, "photo_type": a.photo_type,
            "review_status": a.review_status, "approved": valid, "blockers": image_blockers(db, a),
            "approval": approval_view(latest_approval(db, watch.id, "image", a.id)),
            "thumb": f"/api/assets/{a.id}/image/thumb?v={a.current_render_id}",
        })
    img_problems = []
    if not gallery:
        img_problems.append("No studio images selected yet.")
    pending_imgs = [i for i in images if not i["approved"]]
    if pending_imgs:
        img_problems.append(f"{len(pending_imgs)} of {len(images)} image(s) not approved.")

    ctx = build_context(db, watch)
    copies = {c.channel: c for c in db.scalars(select(ChannelCopy).where(ChannelCopy.watch_id == watch.id))}
    listings = {l.channel: l for l in db.scalars(select(ChannelListing).where(ChannelListing.watch_id == watch.id))}
    open_tasks = db.scalars(select(ManualTask).where(ManualTask.watch_id == watch.id, ManualTask.status == "open")).all()
    channels = []
    on_hold = watch.status in ("reserved", "sold", "withdrawn")
    for key in enabled_channels(db, watch):
        ch = CHANNELS[key]
        copy = copies.get(key)
        mode = channel_mode(db, key)
        listing = listings.get(key)
        blockers: list[str] = []
        stale = copy_is_stale(db, watch, copy, ctx) if copy else []
        if copy is None:
            blockers.append("No copy yet.")
        else:
            blockers += [f"{SECTION_LABELS.get(e['section'], e['section'])}: {e['message']}"
                         for e in copy.validation.get("errors", [])]
            blockers += stale
        approved = approval_valid(db, watch, "channel", key) if copy else False
        publish_blockers = list(blockers)
        publish_blockers += [b.message for b in fact_blockers]
        publish_blockers += img_problems
        if not approved:
            publish_blockers.append("Copy not approved.")
        if mode.mode == "unavailable":
            publish_blockers.append(mode.message)
        if on_hold:
            publish_blockers.append(f"Watch is {watch.status}.")
        channels.append({
            **channel_info(key),
            "copy": {"version": copy.version, "title": copy.sections.get("title"), "generator": copy.generator,
                     "updated_at": iso(copy.updated_at), "chars": len(copy.rendered_text),
                     "errors": copy.validation.get("errors", []), "warnings": copy.validation.get("warnings", []),
                     "stale": stale} if copy else None,
            "approved": approved,
            "approval": approval_view(latest_approval(db, watch.id, "channel", key)),
            "approval_blockers": list(dict.fromkeys(blockers + [b.message for b in fact_blockers] + img_problems)),
            "mode": mode.as_dict(),
            "listing": {"status": listing.status, "label": LISTING_LABELS.get(listing.status, listing.status),
                        "mode": listing.mode, "external_url": listing.external_url, "external_id": listing.external_id,
                        "published_at": iso(listing.published_at), "last_error": listing.last_error,
                        "up_to_date": listing.published_hash is None or not approved
                        or listing.published_hash == (latest_approval(db, watch.id, 'channel', key).content_hash
                                                      if latest_approval(db, watch.id, 'channel', key) else None)}
            if listing else None,
            "publish_ready": not publish_blockers,
            "publish_blockers": list(dict.fromkeys(publish_blockers)),
        })
    package_ok = approval_valid(db, watch, "package", "package")
    copies_needed = [c for c in channels if c["copy"] is not None]
    package_blockers = list(dict.fromkeys(
        [b.message for b in fact_blockers] + img_problems
        + [f"{c['name']}: {b}" for c in channels if c["copy"] for b in c["approval_blockers"]
           if not b.endswith("not approved.")]
        + ([] if copies_needed else ["Generate listing copy first."])))
    live = [c for c in channels if c["listing"] and c["listing"]["status"] in ("live", "manual_posted")]
    suggestions = db.scalars(select(FactSuggestion).where(FactSuggestion.watch_id == watch.id,
                                                          FactSuggestion.status == "open")).all()
    return {
        "facts": sheet,
        "issues": [i.as_dict() for i in issues],
        "suggestions": [{"id": s.id, "field": s.field, "value": s.value, "source": s.source, "evidence": s.evidence,
                         "confidence": s.confidence} for s in suggestions],
        "images": images,
        "image_problems": img_problems,
        "channels": channels,
        "package": {"approved": package_ok, "approval": approval_view(latest_approval(db, watch.id, "package", "package")),
                    "blockers": package_blockers},
        "open_manual_tasks": len(open_tasks),
        "summary": {
            "images_total": len(images), "images_approved": sum(1 for i in images if i["approved"]),
            "channels_with_copy": len(copies_needed), "channels_approved": sum(1 for c in channels if c["approved"]),
            "channels_live": len(live), "fact_blockers": len(fact_blockers),
            "ready_to_publish": sum(1 for c in channels if c["publish_ready"]),
        },
    }
