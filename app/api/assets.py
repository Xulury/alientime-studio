"""Photos: upload, pipeline actions, redaction editing, mask editing, review and private image serving."""
from __future__ import annotations

import io
import re

import numpy as np
from fastapi import APIRouter, Depends, File, Query, UploadFile
from fastapi.responses import FileResponse, Response
from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require, require_person
from app.api.schemas import AssetPatch, RegionsIn, ReviewDecision, SafetyReviewIn, StudioSettingsIn
from app.api.views import asset_view, job_view
from app.api.watches import get_watch
from app.config import get_settings
from app.core import audit
from app.core.errors import AppError, NotFound
from app.core.settings_store import get_setting
from app.core.storage import media_paths, resolve
from app.db.base import get_db, utcnow
from app.db.models import Asset, AssetRender, RedactionRegion
from app.imaging import pipeline
from app.imaging.composite import PLATFORM_PRESETS, platform_image
from app.imaging.io import load_rgb, thumbnail_jpeg, to_jpeg_bytes
from app.ingest.images import ingest_image
from app.jobs.queue import enqueue
from app.review.approvals import invalidate_stale

router = APIRouter(prefix="/api", tags=["photos"])

MEDIA_TYPES = {"JPEG": "image/jpeg", "MPO": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp", "HEIF": "image/heic"}


def get_asset(db: Session, asset_id: str) -> Asset:
    a = db.get(Asset, asset_id)
    if a is None or a.removed_at is not None:
        raise NotFound("Photo not found.")
    return a


def queue_processing(db: Session, asset: Asset, actor: str, *, key_suffix: str = "", force_segmentation: bool = False):
    return enqueue(db, "process_asset", watch_id=asset.watch_id, asset_id=asset.id, created_by=actor,
                   payload={"force_segmentation": force_segmentation},
                   idempotency_key=f"process:{asset.id}:{key_suffix or 'initial'}")


# ---- upload -------------------------------------------------------------------------------------
@router.post("/watches/{watch_id}/assets", status_code=201)
async def upload_assets(watch_id: str, files: list[UploadFile] = File(...), db: Session = Depends(get_db),
                        principal: Principal = Depends(require("intake"))) -> dict:
    s = get_settings()
    watch = get_watch(db, watch_id, include_archived=False)
    if len(files) > s.max_files_per_upload:
        raise AppError(f"Upload at most {s.max_files_per_upload} photos at a time.")
    limit = s.max_upload_mb * 1024 * 1024
    results = []
    added_assets = []
    for f in files:
        data = await f.read(limit + 1)
        if len(data) > limit:
            results.append({"filename": f.filename, "status": "rejected",
                            "message": f"{f.filename}: larger than {s.max_upload_mb} MB."})
            continue
        res = ingest_image(db, watch, data, f.filename, source="upload", actor=principal.actor)
        results.append({"filename": f.filename, "status": res.status, "message": res.message,
                        "warnings": res.warnings, "asset_id": res.asset.id if res.asset else None})
        if res.status == "added" and res.asset is not None:
            added_assets.append(res.asset)
    db.flush()
    jobs = []
    if added_assets:
        watch.updated_at = utcnow()
        if s.auto_process_uploads:
            for a in added_assets:
                a.pipeline_status = "queued"
                jobs.append(queue_processing(db, a, principal.actor))
        invalidate_stale(db, watch, "Photos added", principal.actor)
    db.commit()
    return {"results": results, "added": len(added_assets), "jobs": [job_view(j) for j in jobs]}


# ---- read / update ------------------------------------------------------------------------------
@router.get("/assets/{asset_id}")
def asset_detail(asset_id: str, db: Session = Depends(get_db), _: Principal = Depends(require("read"))) -> dict:
    a = get_asset(db, asset_id)
    policy = get_settings().cloud_ai_image_policy
    ok, why = pipeline.cloud_eligible(a, policy)
    v = asset_view(db, a, full=True)
    v["cloud_ai"] = {"eligible": ok, "reason": why, "policy": policy}
    v["studio_resolved"] = {k: val for k, val in pipeline.resolve_studio_settings(db, a, a.watch).items()
                            if k in ("background_resolved", "rotation_resolved", "white_balance_strength", "auto_exposure",
                                     "exposure_ev", "contrast", "warmth", "shadow", "fill_ratio")}
    return v


@router.patch("/assets/{asset_id}")
def update_asset(asset_id: str, body: AssetPatch, db: Session = Depends(get_db),
                 principal: Principal = Depends(require("intake"))) -> dict:
    a = get_asset(db, asset_id)
    changes = []
    if body.photo_type and (body.photo_type != a.photo_type or a.photo_type_source != "user"):
        a.photo_type = body.photo_type
        a.photo_type_source = "user"
        a.photo_type_confidence = 1.0
        changes.append(f"type → {body.photo_type}")
        if body.photo_type in ("caseback", "document", "box_papers") and a.safety_status == "clear":
            a.safety_status = "needs_review"
    if body.clear_selection_override:
        a.selection_override = None
        changes.append("selection → automatic")
    elif body.selection_override is not None and body.selection_override != a.selection_override:
        a.selection_override = body.selection_override
        changes.append("kept" if body.selection_override else "left out")
    if body.sort_order is not None:
        a.sort_order = body.sort_order
    if changes:
        audit.record(db, principal.actor, "photo_updated", f"{a.original_filename}: " + ", ".join(changes),
                     entity_type="asset", entity_id=a.id, watch_id=a.watch_id)
        invalidate_stale(db, a.watch, "Photo selection changed", principal.actor)
    db.commit()
    return asset_view(db, a)


@router.delete("/assets/{asset_id}")
def remove_asset(asset_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require("intake"))) -> dict:
    a = get_asset(db, asset_id)
    a.removed_at = utcnow()
    w = a.watch
    if w.gallery and a.id in w.gallery:
        w.gallery = [x for x in w.gallery if x != a.id]
    if w.hero_asset_id == a.id:
        w.hero_asset_id = None
    audit.record(db, principal.actor, "photo_removed",
                 f"Removed {a.original_filename} from the listing (original file kept in storage)",
                 entity_type="asset", entity_id=a.id, watch_id=a.watch_id)
    invalidate_stale(db, w, "Photo removed", principal.actor)
    db.commit()
    return {"ok": True}


# ---- pipeline actions ---------------------------------------------------------------------------
@router.post("/assets/{asset_id}/process")
def reprocess(asset_id: str, resegment: bool = False, db: Session = Depends(get_db),
              principal: Principal = Depends(require("process"))) -> dict:
    a = get_asset(db, asset_id)
    a.pipeline_status = "queued"
    job = queue_processing(db, a, principal.actor, key_suffix=f"manual-{utcnow().timestamp()}",
                           force_segmentation=resegment)
    db.commit()
    return job_view(job)


@router.post("/watches/{watch_id}/process")
def process_watch(watch_id: str, only_unprocessed: bool = True, db: Session = Depends(get_db),
                  principal: Principal = Depends(require("process"))) -> dict:
    w = get_watch(db, watch_id, include_archived=False)
    jobs = []
    for a in db.scalars(select(Asset).where(Asset.watch_id == w.id, Asset.removed_at.is_(None))):
        if only_unprocessed and a.pipeline_status in ("ready", "queued", "processing"):
            continue
        a.pipeline_status = "queued"
        jobs.append(queue_processing(db, a, principal.actor, key_suffix=f"batch-{utcnow().timestamp()}"))
    db.commit()
    return {"jobs": [job_view(j) for j in jobs], "queued": len(jobs)}


@router.post("/assets/{asset_id}/rescan")
def rescan(asset_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require("process"))) -> dict:
    a = get_asset(db, asset_id)
    job = enqueue(db, "safety_scan", watch_id=a.watch_id, asset_id=a.id, created_by=principal.actor,
                  idempotency_key=f"scan:{a.id}:{utcnow().timestamp()}")
    db.commit()
    return job_view(job)


@router.put("/assets/{asset_id}/regions")
def set_regions(asset_id: str, body: RegionsIn, db: Session = Depends(get_db),
                principal: Principal = Depends(require_person("process"))) -> dict:
    """Replace the redaction regions (add, move, resize, disable or delete)."""
    a = get_asset(db, asset_id)
    if not a.redacted_path:
        raise AppError("Run the privacy check before editing redactions.")
    existing = {r.id: r for r in a.regions}
    keep_ids = set()
    added = removed = 0
    for r in body.regions:
        x, y = min(r.x, 0.999), min(r.y, 0.999)
        w, h = min(r.w, 1 - x), min(r.h, 1 - y)
        if r.id and r.id in existing:
            row = existing[r.id]
            row.x, row.y, row.w, row.h, row.enabled = x, y, w, h, r.enabled
            keep_ids.add(row.id)
        else:
            row = RedactionRegion(x=x, y=y, w=w, h=h, source="manual", category="manual", enabled=r.enabled,
                                  created_by=principal.actor)
            a.regions.append(row)
            added += 1
    for rid, row in existing.items():
        if rid not in keep_ids:
            a.regions.remove(row)
            db.delete(row)
            removed += 1
    db.flush()
    result = pipeline.reapply_redactions(db, a, principal.actor)
    audit.record(db, principal.actor, "redactions_edited",
                 f"{a.original_filename}: {len([r for r in a.regions if r.enabled])} redaction(s) "
                 f"({added} added, {removed} removed); status {a.safety_status}",
                 entity_type="asset", entity_id=a.id, watch_id=a.watch_id)
    invalidate_stale(db, a.watch, "Redactions changed", principal.actor)
    db.commit()
    return {**asset_detail(asset_id, db), "result": result}


@router.post("/assets/{asset_id}/privacy-review")
def privacy_review(asset_id: str, body: SafetyReviewIn, db: Session = Depends(get_db),
                   principal: Principal = Depends(require_person("process"))) -> dict:
    a = get_asset(db, asset_id)
    if not body.confirm:
        raise AppError("Confirm that you have checked the photo for serial numbers and private details.")
    try:
        pipeline.confirm_safety_review(db, a, principal.actor)
    except pipeline.PipelineError as e:
        raise AppError(str(e), code="privacy_check_failed")
    audit.record(db, principal.actor, "privacy_reviewed", f"{a.original_filename}: checked for serials by a person",
                 entity_type="asset", entity_id=a.id, watch_id=a.watch_id, detail={"note": body.note})
    db.commit()
    return asset_detail(asset_id, db)


@router.post("/watches/{watch_id}/privacy-review")
def privacy_review_all(watch_id: str, body: SafetyReviewIn, db: Session = Depends(get_db),
                       principal: Principal = Depends(require_person("process"))) -> dict:
    w = get_watch(db, watch_id, include_archived=False)
    if not body.confirm:
        raise AppError("Confirm that you have checked every photo.")
    done, skipped = 0, []
    for a in db.scalars(select(Asset).where(Asset.watch_id == w.id, Asset.removed_at.is_(None))):
        if a.safety_status in ("needs_review", "clear", "ocr_unavailable"):
            pipeline.confirm_safety_review(db, a, principal.actor)
            done += 1
        elif a.safety_status in ("failed", "pending"):
            skipped.append(a.original_filename)
    audit.record(db, principal.actor, "privacy_reviewed", f"Marked {done} photo(s) as checked for serials",
                 entity_type="watch", entity_id=w.id, watch_id=w.id)
    db.commit()
    return {"checked": done, "skipped": skipped}


@router.put("/assets/{asset_id}/mask")
async def upload_mask(asset_id: str, file: UploadFile = File(...), db: Session = Depends(get_db),
                      principal: Principal = Depends(require("process"))) -> dict:
    a = get_asset(db, asset_id)
    data = await file.read(25 * 1024 * 1024 + 1)
    if len(data) > 25 * 1024 * 1024:
        raise AppError("Mask file is too large.")
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format != "PNG":
                raise AppError("The mask must be a PNG image.")
            if im.width * im.height > 60_000_000:
                raise AppError("Mask is too large.")
            if im.mode in ("RGBA", "LA"):
                arr = np.asarray(im.getchannel("A"))
            else:
                arr = np.asarray(im.convert("L"))
    except AppError:
        raise
    except Exception:
        raise AppError("Could not read the mask image.")
    ratio_src = a.working_width / max(1, a.working_height)
    ratio_new = arr.shape[1] / max(1, arr.shape[0])
    if abs(ratio_src - ratio_new) > 0.02:
        raise AppError("The mask does not match the photo's proportions.")
    pipeline.save_manual_mask(db, a, arr.astype(np.uint8), principal.actor)
    pipeline.run_inspection(db, a)
    invalidate_stale(db, a.watch, "Cutout edited", principal.actor)
    db.commit()
    return asset_detail(asset_id, db)


@router.post("/assets/{asset_id}/mask/reset")
def reset_mask(asset_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require("process"))) -> dict:
    a = get_asset(db, asset_id)
    job = enqueue(db, "segment_asset", watch_id=a.watch_id, asset_id=a.id, created_by=principal.actor,
                  idempotency_key=f"segment:{a.id}:{utcnow().timestamp()}")
    db.commit()
    return job_view(job)


@router.post("/assets/{asset_id}/render")
def render(asset_id: str, body: StudioSettingsIn, db: Session = Depends(get_db),
           principal: Principal = Depends(require("process"))) -> dict:
    a = get_asset(db, asset_id)
    if a.safety_status == "failed":
        raise AppError("Fix the redactions on this photo before rendering it.", code="privacy_check_failed")
    updates = body.model_dump(exclude_unset=True)
    hero = updates.pop("hero", None)
    if updates:
        a.studio_settings = {**(a.studio_settings or {}), **updates}
    if hero:
        a.watch.hero_asset_id = a.id
    if (updates.get("background") or "").startswith("ai_"):
        from app.providers.registry import get_provider

        if not get_provider().available:
            raise AppError("AI backgrounds need an OpenAI API key. Choose a local background, or add the key.",
                           code="ai_not_configured")
    a.pipeline_status = "queued"
    job = enqueue(db, "render_asset", watch_id=a.watch_id, asset_id=a.id, created_by=principal.actor,
                  idempotency_key=f"render:{a.id}:{utcnow().timestamp()}")
    audit.record(db, principal.actor, "render_requested", f"{a.original_filename}: re-render requested",
                 entity_type="asset", entity_id=a.id, watch_id=a.watch_id, detail={"settings": updates})
    db.commit()
    return job_view(job)


@router.post("/assets/{asset_id}/renders/{render_id}/restore")
def restore_render(asset_id: str, render_id: str, db: Session = Depends(get_db),
                   principal: Principal = Depends(require("process"))) -> dict:
    a = get_asset(db, asset_id)
    r = db.get(AssetRender, render_id)
    if r is None or r.asset_id != a.id:
        raise NotFound("Render not found.")
    if r.inputs.get("redaction_version") != a.redaction_version:
        raise AppError("Redactions changed after this render, so it cannot be restored. Render again instead.")
    a.current_render_id = r.id
    a.render_stale = False
    a.review_status = "pending"
    audit.record(db, principal.actor, "render_restored", f"{a.original_filename}: restored render v{r.version}",
                 entity_type="asset", entity_id=a.id, watch_id=a.watch_id)
    invalidate_stale(db, a.watch, "Earlier render restored", principal.actor)
    db.commit()
    return asset_detail(asset_id, db)


@router.post("/assets/{asset_id}/review")
def review_asset(asset_id: str, body: ReviewDecision, db: Session = Depends(get_db),
                 principal: Principal = Depends(require("approve"))) -> dict:
    from app.review.service import decide_image

    a = get_asset(db, asset_id)
    decide_image(db, a, body.decision, principal.actor, body.note)
    db.commit()
    return asset_view(db, a)


# ---- image serving (private) ---------------------------------------------------------------------
def _cache_file(asset: Asset, name: str):
    d = media_paths(asset.watch_id).root / "cache"
    d.mkdir(exist_ok=True)
    return d / name


def _bytes_response(data: bytes, media_type: str, filename: str | None, download: bool) -> Response:
    headers = {"Cache-Control": "private, max-age=300", "X-Content-Type-Options": "nosniff"}
    if download and filename:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return Response(data, media_type=media_type, headers=headers)


def _file_response(path, media_type: str, filename: str | None, download: bool, no_store: bool = False):
    if path is None or not path.is_file():
        raise NotFound("Image not available yet.")
    headers = {"Cache-Control": "private, no-store" if no_store else "private, max-age=300"}
    if download and filename:
        headers["Content-Disposition"] = f'attachment; filename="{filename}"'
    return FileResponse(path, media_type=media_type, headers=headers)


@router.get("/assets/{asset_id}/image/{variant}")
def asset_image(asset_id: str, variant: str, download: bool = False, v: str | None = Query(default=None),
                db: Session = Depends(get_db), _: Principal = Depends(require("read"))):
    a = db.get(Asset, asset_id)
    if a is None:
        raise NotFound("Photo not found.")
    if not re.fullmatch(r"[a-z_0-9:]{2,60}", variant):
        raise NotFound("Unknown image variant.")
    sku = a.watch.sku
    idx = f"{a.sort_order:02d}"
    if variant == "original":
        return _file_response(resolve(a.original_path), MEDIA_TYPES.get(a.original_format, "application/octet-stream"),
                              f"{sku}_{idx}_original_{a.original_filename}", download, no_store=True)
    if variant == "working":
        return _file_response(resolve(a.working_path), "image/jpeg", f"{sku}_{idx}_working.jpg", download)
    if variant == "redacted":
        return _file_response(resolve(a.redacted_path), "image/jpeg", f"{sku}_{idx}_redacted.jpg", download)
    if variant == "mask":
        return _file_response(resolve(a.mask_path), "image/png", f"{sku}_{idx}_mask.png", download)
    if variant == "cutout":
        key = f"{a.id}_cutout_m{a.mask_version}_r{a.redaction_version}.png"
        cache = _cache_file(a, key)
        if not cache.is_file():
            src = resolve(a.redacted_path) or resolve(a.working_path)
            mask = pipeline.current_mask(a)
            if src is None or mask is None:
                raise NotFound("Cutout not available yet.")
            rgb = load_rgb(src)
            rgba = np.dstack([rgb, mask])
            im = Image.fromarray(rgba, "RGBA")
            im.thumbnail((2000, 2000), Image.Resampling.LANCZOS)
            im.save(cache, "PNG")
        return _file_response(cache, "image/png", f"{sku}_{idx}_cutout.png", download)
    render = db.get(AssetRender, a.current_render_id) if a.current_render_id else None
    if variant.startswith("render:"):
        render = db.get(AssetRender, variant.split(":", 1)[1])
        if render is None or render.asset_id != a.id:
            raise NotFound("Render not found.")
        return _file_response(resolve(render.master_path), "image/jpeg", f"{sku}_{idx}_r{render.version}.jpg", download)
    if variant == "final":
        if render is None:
            raise NotFound("No studio image yet.")
        return _file_response(resolve(render.master_path), "image/jpeg", f"{sku}_{idx}_studio.jpg", download)
    if variant.startswith("variant:"):
        key = variant.split(":", 1)[1]
        if render is None or key not in (render.variants or {}):
            raise NotFound("Variant not available.")
        return _file_response(resolve(render.variants[key]["path"]), "image/jpeg", f"{sku}_{idx}_{key}.jpg", download)
    if variant.startswith("aligned:"):
        # The redacted original re-framed exactly like the studio image, for an aligned before/after slider.
        key = variant.split(":", 1)[1]
        if render is None or key not in (render.variants or {}):
            raise NotFound("Comparison image not available.")
        cache = _cache_file(a, f"{a.id}_aligned_{render.id}_{key}.jpg")
        if not cache.is_file():
            from app.imaging.composite import Plan, transform

            src = resolve(a.redacted_path) or resolve(a.working_path)
            plan = Plan.from_dict(render.variants[key]["plan"])
            cache.write_bytes(to_jpeg_bytes(transform(load_rgb(src), plan, replicate=True), quality=90))
        return _file_response(cache, "image/jpeg", f"{sku}_{idx}_{key}_before.jpg", download)
    if variant.startswith("platform:"):
        ch = variant.split(":", 1)[1]
        if render is None or ch not in PLATFORM_PRESETS:
            raise NotFound("Platform image not available.")
        canvas, w, h = PLATFORM_PRESETS[ch]
        src = resolve(render.variants[canvas]["path"])
        data = to_jpeg_bytes(platform_image(load_rgb(src), w, h), quality=90)
        return _bytes_response(data, "image/jpeg", f"{sku}_{idx}_{ch}.jpg", download)
    if variant == "thumb":
        key = f"{a.id}_thumb_{render.id if render else 'none'}_r{a.redaction_version}.jpg"
        cache = _cache_file(a, key)
        if not cache.is_file():
            src = (resolve(render.master_path) if render else None) or resolve(a.redacted_path) or resolve(a.working_path)
            if src is None or not src.is_file():
                raise NotFound("Thumbnail not available.")
            cache.write_bytes(thumbnail_jpeg(load_rgb(src), 520))
        return _file_response(cache, "image/jpeg", None, False)
    raise NotFound("Unknown image variant.")
