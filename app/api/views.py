"""JSON views of database rows for the web app and agents."""
from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.lifecycle import STATUS_LABELS, allowed_actions, availability
from app.db.base import iso
from app.db.models import Asset, AssetRender, Job, ManualTask, RedactionRegion, Watch
from app.jobs.queue import JOB_LABELS

PHOTO_TYPE_LABELS = {
    "dial_front": "Dial / front", "side_profile": "Side / profile", "crown_side": "Crown side",
    "clasp": "Clasp", "strap": "Strap / bracelet", "caseback": "Caseback", "movement": "Movement",
    "box_papers": "Box / papers", "document": "Document", "detail": "Detail", "wrist": "On the wrist",
    "unclassified": "Unclassified",
}
SAFETY_LABELS = {
    "pending": "Not checked yet",
    "clear": "No serial-like text found",
    "needs_review": "Check redactions",
    "reviewed": "Checked by you",
    "failed": "Redaction check failed",
    "ocr_unavailable": "Manual check needed",
}
PIPELINE_LABELS = {
    "uploaded": "Uploaded", "queued": "Queued", "processing": "Processing", "ready": "Ready",
    "failed": "Failed", "needs_attention": "Needs attention",
}


def money(v) -> float | None:
    return float(v) if v is not None else None


def image_url(asset_id: str, variant: str, version: str | int | None = None) -> str:
    v = f"?v={version}" if version is not None else ""
    return f"/api/assets/{asset_id}/image/{variant}{v}"


def asset_view(db: Session, a: Asset, *, full: bool = False) -> dict[str, Any]:
    render = db.get(AssetRender, a.current_render_id) if a.current_render_id else None
    selected = a.selection_override if a.selection_override is not None else a.selected
    v = {
        "id": a.id,
        "watch_id": a.watch_id,
        "filename": a.original_filename,
        "source": a.source,
        "width": a.width,
        "height": a.height,
        "bytes": a.original_bytes,
        "format": a.original_format,
        "sha256": a.original_sha256,
        "uploaded_at": iso(a.uploaded_at),
        "sort_order": a.sort_order,
        "duplicate_of": a.duplicate_of,
        "pipeline_status": a.pipeline_status,
        "pipeline_label": PIPELINE_LABELS.get(a.pipeline_status, a.pipeline_status),
        "pipeline_error": a.pipeline_error,
        "source_profile": a.source_profile,
        "quality_score": a.quality_score,
        "selected": selected,
        "selection_auto": a.selected,
        "selection_override": a.selection_override,
        "selection_reasons": a.selection_reasons or [],
        "photo_type": a.photo_type,
        "photo_type_label": PHOTO_TYPE_LABELS.get(a.photo_type or "", "Not classified"),
        "photo_type_source": a.photo_type_source,
        "safety_status": a.safety_status,
        "safety_label": SAFETY_LABELS.get(a.safety_status, a.safety_status),
        "review_status": a.review_status,
        "review_note": a.review_note,
        "render_stale": a.render_stale,
        "warnings": a.warnings or [],
        "has_mask": bool(a.mask_path),
        "has_render": render is not None,
        "fidelity_passed": render.fidelity_passed if render else None,
        "urls": {
            "thumb": image_url(a.id, "thumb", f"{a.redaction_version}-{a.current_render_id or 0}"),
            "working": image_url(a.id, "working"),
            "redacted": image_url(a.id, "redacted", a.redaction_version) if a.redacted_path else None,
            "mask": image_url(a.id, "mask", a.mask_version) if a.mask_path else None,
            "cutout": image_url(a.id, "cutout", f"{a.mask_version}-{a.redaction_version}") if a.mask_path else None,
            "final": image_url(a.id, "final", render.id) if render else None,
            "original": image_url(a.id, "original"),
        },
    }
    if full:
        v.update({
            "inspection": a.inspection or {},
            "source_profile_reasons": a.source_profile_reasons or [],
            "photo_type_confidence": a.photo_type_confidence,
            "ai_tags": a.ai_tags or {},
            "exif": a.exif_summary or {},
            "safety_engine": a.safety_engine,
            "safety_findings": a.safety_findings or [],
            "safety_recheck": a.safety_recheck or {},
            "safety_reviewed_at": iso(a.safety_reviewed_at),
            "safety_reviewed_by": a.safety_reviewed_by,
            "regions": [region_view(r) for r in a.regions],
            "segmentation": a.segmentation or {},
            "mask_source": a.mask_source,
            "studio_settings": a.studio_settings or {},
            "working_size": [a.working_width, a.working_height],
            "render": render_view(render) if render else None,
            "renders": [render_view(r, brief=True) for r in db.scalars(
                select(AssetRender).where(AssetRender.asset_id == a.id).order_by(AssetRender.version.desc()).limit(12))],
        })
    return v


def region_view(r: RedactionRegion) -> dict[str, Any]:
    return {"id": r.id, "x": r.x, "y": r.y, "w": r.w, "h": r.h, "source": r.source, "category": r.category,
            "confidence": r.confidence, "enabled": r.enabled}


def render_view(r: AssetRender, brief: bool = False) -> dict[str, Any]:
    v = {
        "id": r.id, "version": r.version, "created_at": iso(r.created_at), "status": r.status,
        "background_source": r.background_source, "fidelity_passed": r.fidelity_passed,
        "url": image_url(r.asset_id, f"render:{r.id}"),
    }
    if not brief:
        v.update({
            "settings": r.settings, "fidelity": r.fidelity, "warnings": r.warnings or [],
            "variants": {k: {"width": x.get("width"), "height": x.get("height"), "label": x.get("label"),
                             "url": image_url(r.asset_id, f"variant:{k}", r.id)}
                         for k, x in (r.variants or {}).items()},
        })
    return v


def watch_summary(db: Session, w: Watch) -> dict[str, Any]:
    photo_count = db.scalar(select(func.count()).select_from(Asset)
                            .where(Asset.watch_id == w.id, Asset.removed_at.is_(None))) or 0
    thumb = None
    hero = db.get(Asset, w.hero_asset_id) if w.hero_asset_id else None
    if hero is None or hero.removed_at is not None:
        hero = db.scalar(select(Asset).where(Asset.watch_id == w.id, Asset.removed_at.is_(None))
                         .order_by(Asset.current_render_id.is_(None), Asset.sort_order).limit(1))
    if hero is not None:
        thumb = image_url(hero.id, "thumb", f"{hero.redaction_version}-{hero.current_render_id or 0}")
    open_tasks = db.scalar(select(func.count()).select_from(ManualTask)
                           .where(ManualTask.watch_id == w.id, ManualTask.status == "open")) or 0
    return {
        "id": w.id,
        "sku": w.sku,
        "brand": w.brand,
        "model": w.model,
        "reference": w.reference,
        "year": w.year,
        "condition": w.condition,
        "price_sgd": money(w.price_sgd),
        "price_usd": money(w.price_usd),
        "custody": w.custody,
        "box_papers": w.box_papers,
        "is_consignment": w.is_consignment,
        "status": w.status,
        "status_label": STATUS_LABELS.get(w.status, w.status),
        "availability": availability(w.status),
        "photo_count": photo_count,
        "open_manual_tasks": open_tasks,
        "thumb": thumb,
        "created_at": iso(w.created_at),
        "updated_at": iso(w.updated_at),
        "archived": w.archived_at is not None,
    }


def watch_record(w: Watch) -> dict[str, Any]:
    return {
        "id": w.id, "sku": w.sku, "brand": w.brand, "model": w.model, "reference": w.reference, "year": w.year,
        "condition": w.condition, "condition_notes": w.condition_notes,
        "price_sgd": money(w.price_sgd), "price_usd": money(w.price_usd),
        "fx_rate_sgd_usd": float(w.fx_rate_sgd_usd) if w.fx_rate_sgd_usd is not None else None,
        "fx_source": w.fx_source, "fx_updated_at": iso(w.fx_updated_at),
        "box_papers": w.box_papers, "box_papers_notes": w.box_papers_notes, "custody": w.custody,
        "is_consignment": w.is_consignment, "consignor_name": w.consignor_name,
        "consignor_contact": w.consignor_contact, "consignment_ref": w.consignment_ref,
        "consignment_terms": w.consignment_terms, "consignment_payout_sgd": money(w.consignment_payout_sgd),
        "consignment_start": w.consignment_start.isoformat() if w.consignment_start else None,
        "consignment_end": w.consignment_end.isoformat() if w.consignment_end else None,
        "consignor_signoff": w.consignor_signoff,
        "description": w.description, "internal_notes": w.internal_notes,
        "extra_facts": {k: v for k, v in (w.extra_facts or {}).items() if not k.startswith("_")},
        "spec_id": w.spec_id,
        "status": w.status, "status_label": STATUS_LABELS.get(w.status, w.status),
        "status_changed_at": iso(w.status_changed_at),
        "availability": availability(w.status), "allowed_actions": allowed_actions(w.status),
        "gallery": w.gallery or [], "hero_asset_id": w.hero_asset_id, "channels": w.channels,
        "content_version": w.content_version,
        "created_at": iso(w.created_at), "updated_at": iso(w.updated_at),
        "archived": w.archived_at is not None,
    }


def job_view(j: Job) -> dict[str, Any]:
    return {
        "id": j.id, "type": j.type, "label": JOB_LABELS.get(j.type, j.type.replace("_", " ").capitalize()),
        "status": j.status, "watch_id": j.watch_id, "asset_id": j.asset_id, "channel": j.channel,
        "progress": round(j.progress or 0, 1), "message": j.progress_message, "error": j.error,
        "attempts": j.attempts, "max_attempts": j.max_attempts, "result": j.result or {},
        "run_after": iso(j.run_after), "created_at": iso(j.created_at), "started_at": iso(j.started_at),
        "finished_at": iso(j.finished_at), "created_by": j.created_by,
    }
