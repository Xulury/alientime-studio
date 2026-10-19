"""Photo pipeline orchestration: privacy → cutout → inspection → studio render.

Each stage reads and writes files under the watch's private media folder and records its results on
the Asset row. Stages are idempotent and can be re-run individually from the studio editor.
"""
from __future__ import annotations

import logging
from typing import Callable

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core import audit
from app.core.settings_store import get_setting
from app.core.storage import media_paths, rel, resolve, sha256_bytes
from app.db.base import utcnow
from app.db.models import Asset, AssetRender, RedactionRegion, Watch
from app.imaging import safety as safety_mod
from app.imaging.backgrounds import cleanup_background
from app.imaging.composite import CANVASES, MASTER_CANVAS, render_canvas
from app.imaging.enhance import apply_color, auto_color_params
from app.imaging.fidelity import check as fidelity_check
from app.imaging.inspect import inspect_image
from app.imaging.io import decode_rgb, load_mask, load_rgb, save_jpeg, save_png
from app.imaging.ocr import get_ocr_engine
from app.imaging.segment import mask_stats, segment

log = logging.getLogger(__name__)
Progress = Callable[[float, str], None]

SAFE_FOR_CLOUD_TYPES_BLOCKED = {"caseback", "movement", "document", "box_papers"}


def _noop(_p: float, _m: str) -> None:
    pass


class PipelineError(RuntimeError):
    pass


def working_rgb(asset: Asset) -> np.ndarray:
    p = resolve(asset.working_path)
    if p is None or not p.is_file():
        raise PipelineError("The working copy of this photo is missing.")
    return load_rgb(p)


def redacted_rgb(asset: Asset) -> np.ndarray:
    p = resolve(asset.redacted_path)
    if p is None or not p.is_file():
        raise PipelineError("Run the privacy check before this step.")
    return load_rgb(p)


def current_mask(asset: Asset) -> np.ndarray | None:
    p = resolve(asset.mask_path)
    if p is None or not p.is_file():
        return None
    return load_mask(p, size=(asset.working_width, asset.working_height))


def enabled_regions(asset: Asset) -> list[tuple[float, float, float, float]]:
    return [(r.x, r.y, r.w, r.h) for r in asset.regions if r.enabled]


# ---- stage 2: privacy -----------------------------------------------------------------------------
def _write_redacted(asset: Asset, img: np.ndarray) -> None:
    paths = media_paths(asset.watch_id)
    out = paths.redacted / f"{asset.id}.jpg"
    save_jpeg(img, out, quality=95)
    asset.redacted_path = rel(out)
    asset.redaction_version = (asset.redaction_version or 0) + 1


def run_safety_scan(db: Session, asset: Asset, actor: str = "system") -> dict:
    """OCR at four rotations → automatic redaction regions → visible blocks → second-pass check."""
    rgb = working_rgb(asset)
    h, w = rgb.shape[:2]
    engine = get_ocr_engine()
    result = safety_mod.scan(rgb, engine)
    # replace previous automatic regions, keep manual ones
    for r in list(asset.regions):
        if r.source == "ocr":
            asset.regions.remove(r)
            db.delete(r)
    db.flush()
    auto = safety_mod.merge_regions([safety_mod.finding_to_region(f, w, h) for f in result.findings])
    cats = sorted({f.category for f in result.findings})
    for (x, y, rw, rh) in auto:
        conf = max((f.confidence for f in result.findings), default=None)
        asset.regions.append(RedactionRegion(x=x, y=y, w=rw, h=rh, source="ocr",
                                             category=", ".join(cats) or "text", confidence=conf, created_by=actor))
    db.flush()
    regions = enabled_regions(asset)
    redacted = safety_mod.apply_redaction(rgb, regions)
    _write_redacted(asset, redacted)
    asset.safety_engine = result.engine
    asset.safety_findings = [f.as_dict() for f in result.findings]
    if result.dense_text:
        asset.safety_findings.append({"category": "dense_text", "text_boxes": result.text_boxes})
    asset.safety_reviewed_at = None
    asset.safety_reviewed_by = None
    if engine is None:
        asset.safety_status = "ocr_unavailable"
        asset.safety_recheck = {"passed": False, "message": "Local OCR is not installed; check this photo by eye."}
    elif regions:
        recheck = safety_mod.recheck(redacted, regions, engine)
        asset.safety_recheck = recheck
        asset.safety_status = "needs_review" if recheck["passed"] else "failed"
    elif result.dense_text:
        asset.safety_recheck = {"passed": True, "checked": 0, "message": "Lots of text found (caseback or papers?)."}
        asset.safety_status = "needs_review"
    else:
        asset.safety_recheck = {"passed": True, "checked": 0, "message": "No serial-like text found by OCR."}
        asset.safety_status = "clear"
    audit.record(db, actor, "privacy_scan",
                 f"Privacy scan: {len(regions)} redaction(s), status {asset.safety_status}",
                 entity_type="asset", entity_id=asset.id, watch_id=asset.watch_id,
                 detail={"findings": len(result.findings), "categories": cats, "engine": result.engine})
    _mark_render_stale(asset)
    return {"regions": len(regions), "status": asset.safety_status}


def reapply_redactions(db: Session, asset: Asset, actor: str) -> dict:
    """After manual edits: redraw all enabled regions and re-run the second-pass check."""
    rgb = working_rgb(asset)
    regions = enabled_regions(asset)
    redacted = safety_mod.apply_redaction(rgb, regions)
    _write_redacted(asset, redacted)
    engine = get_ocr_engine()
    asset.safety_reviewed_at = None
    asset.safety_reviewed_by = None
    if regions:
        recheck = safety_mod.recheck(redacted, regions, engine)
        asset.safety_recheck = recheck
        if engine is None:
            asset.safety_status = "ocr_unavailable"
        else:
            asset.safety_status = "needs_review" if recheck["passed"] else "failed"
    else:
        asset.safety_recheck = {"passed": True, "checked": 0, "message": "No redactions on this photo."}
        asset.safety_status = "needs_review" if engine is None or asset.safety_findings else "clear"
    _mark_render_stale(asset)
    return {"regions": len(regions), "status": asset.safety_status}


def confirm_safety_review(db: Session, asset: Asset, actor: str) -> None:
    if asset.safety_status == "failed":
        raise PipelineError("Digits are still readable in a redacted area. Enlarge or add a redaction first.")
    if asset.safety_status == "pending" or not asset.redacted_path:
        raise PipelineError("Run the privacy check first.")
    asset.safety_status = "reviewed"
    asset.safety_reviewed_at = utcnow()
    asset.safety_reviewed_by = actor


def cloud_eligible(asset: Asset, policy: str) -> tuple[bool, str]:
    """May this (redacted) frame be sent to a cloud AI service?"""
    if policy == "never":
        return False, "Cloud AI for photos is turned off."
    if asset.photo_type in SAFE_FOR_CLOUD_TYPES_BLOCKED:
        return False, f"{(asset.photo_type or '').replace('_', ' ').capitalize()} photos never leave this machine."
    if not asset.redacted_path:
        return False, "Privacy check has not run."
    if asset.safety_status == "reviewed":
        return True, "Checked by you."
    if asset.safety_status == "clear" and policy == "safe_auto":
        return True, "No serial-like text found."
    if asset.safety_status == "clear":
        return False, "Mark the photo as checked before it can be sent to AI."
    return False, "Photo needs a privacy check before it can be sent to AI."


# ---- stage 3: segmentation ------------------------------------------------------------------------
def run_segmentation(db: Session, asset: Asset, actor: str = "system", force: bool = False) -> dict:
    if asset.mask_path and not force and asset.mask_source in ("source_transparency", "manual"):
        return {"skipped": True, "reason": f"Kept existing {asset.mask_source} mask"}
    rgb = working_rgb(asset)
    res = segment(rgb)
    paths = media_paths(asset.watch_id)
    asset.mask_version = (asset.mask_version or 0) + 1
    out = paths.masks / f"{asset.id}_v{asset.mask_version}.png"
    save_png(res.mask, out, "L")
    asset.mask_path = rel(out)
    asset.mask_source = res.backend
    stats = mask_stats(res.mask)
    asset.segmentation = {"backend": res.backend, "notes": res.notes, "stats": stats, "at": utcnow().isoformat()}
    _mark_render_stale(asset)
    return {"backend": res.backend, "fg_ratio": stats["fg_ratio"]}


def save_manual_mask(db: Session, asset: Asset, mask: np.ndarray, actor: str) -> None:
    if mask.shape[:2] != (asset.working_height, asset.working_width):
        import cv2

        mask = cv2.resize(mask, (asset.working_width, asset.working_height), interpolation=cv2.INTER_LINEAR)
    paths = media_paths(asset.watch_id)
    asset.mask_version = (asset.mask_version or 0) + 1
    out = paths.masks / f"{asset.id}_v{asset.mask_version}.png"
    save_png(mask, out, "L")
    asset.mask_path = rel(out)
    asset.mask_source = "manual"
    stats = mask_stats(mask)
    asset.segmentation = {**(asset.segmentation or {}), "backend": "manual", "stats": stats,
                          "edited_by": actor, "at": utcnow().isoformat()}
    _mark_render_stale(asset)
    audit.record(db, actor, "mask_edited", f"Cutout corrected by hand ({asset.original_filename})",
                 entity_type="asset", entity_id=asset.id, watch_id=asset.watch_id)


# ---- stage 1: inspection --------------------------------------------------------------------------
def run_inspection(db: Session, asset: Asset) -> dict:
    s = get_setting(db, "studio")
    rgb = working_rgb(asset)
    mask = current_mask(asset)
    dense = any(f.get("category") == "dense_text" for f in (asset.safety_findings or []))
    text_boxes = next((f.get("text_boxes", 0) for f in (asset.safety_findings or []) if f.get("category") == "dense_text"), 0)
    ins = inspect_image(rgb, mask, exif=asset.exif_summary or {}, filename=asset.original_filename,
                        original_size=(asset.width, asset.height), fmt=asset.original_format,
                        had_transparency=asset.mask_source == "source_transparency", text_boxes=text_boxes,
                        dense_text=dense,
                        has_serial=any(f.get("category") != "dense_text" for f in (asset.safety_findings or [])),
                        min_sharpness=float(s.get("min_sharpness", 35)),
                        min_resolution=int(s.get("min_resolution", 700)))
    asset.inspection = ins.as_dict()
    asset.quality_score = ins.score
    asset.source_profile = ins.source_profile
    asset.source_profile_reasons = ins.source_reasons
    if asset.photo_type_source not in ("user", "ai"):
        asset.photo_type = ins.photo_type
        asset.photo_type_source = "local"
        asset.photo_type_confidence = ins.photo_type_confidence
    if asset.photo_type in ("caseback", "document") and asset.safety_status == "clear":
        asset.safety_status = "needs_review"
        asset.safety_recheck = {**(asset.safety_recheck or {}),
                                "message": "Looks like a caseback or papers: check for serial numbers by eye."}
    rejects = list(ins.rejects)
    if asset.photo_type in ("document", "box_papers"):
        rejects.append("Papers or documents are kept private and not used in listings.")
    asset.selected = not rejects
    if rejects:
        asset.selection_reasons = rejects
    else:
        quality = "Sharp and well exposed" if ins.score >= 70 else "Usable"
        asset.selection_reasons = [f"{quality} (score {ins.score:.0f})."]
    asset.warnings = list(dict.fromkeys([w for w in (asset.warnings or []) if "almost identical" in w or "also attached" in w] + ins.warnings))
    return {"score": ins.score, "selected": asset.selected}


def resolve_duplicates(db: Session, watch: Watch) -> int:
    """Among near-duplicates keep the better frame; the other is rejected with a reason."""
    assets = {a.id: a for a in db.scalars(select(Asset).where(Asset.watch_id == watch.id, Asset.removed_at.is_(None)))}
    n = 0
    for a in assets.values():
        other = assets.get(a.duplicate_of or "")
        if other is None or a.quality_score is None or other.quality_score is None:
            continue
        loser, winner = (a, other) if a.quality_score <= other.quality_score else (other, a)
        if loser.selected:
            loser.selected = False
            loser.selection_reasons = [f"Near-duplicate of {winner.original_filename}; the better frame was kept."]
            n += 1
    return n


# ---- stage 4: studio render -----------------------------------------------------------------------
def resolve_studio_settings(db: Session, asset: Asset, watch: Watch) -> dict:
    base = get_setting(db, "studio")
    merged = {**base, **(watch.studio_defaults or {}), **(asset.studio_settings or {})}
    bg = merged.get("background") or "auto"
    if bg == "auto":
        bg = base["edited_background"] if asset.source_profile == "edited" else base["default_background"]
    merged["background_resolved"] = bg
    rot = merged.get("rotation_deg")
    if rot is None:
        rot = base.get("hero_rotation_deg", 0.0) if asset.id == watch.hero_asset_id else 0.0
    merged["rotation_resolved"] = float(rot or 0.0)
    return merged


def _mark_render_stale(asset: Asset) -> None:
    if asset.current_render_id:
        asset.render_stale = True


def render_asset(db: Session, asset: Asset, actor: str = "system", progress: Progress = _noop) -> AssetRender:
    from app.review.approvals import invalidate_stale

    watch = db.get(Watch, asset.watch_id)
    if not asset.redacted_path or asset.safety_status == "pending":
        progress(5, "Privacy check")
        run_safety_scan(db, asset, actor)
    if asset.safety_status == "failed":
        raise PipelineError("The redaction check failed for this photo. Fix the redactions before rendering.")
    if not asset.mask_path:
        progress(15, "Cutting out the watch")
        run_segmentation(db, asset, actor)
    settings = resolve_studio_settings(db, asset, watch)
    bg = settings["background_resolved"]
    red = redacted_rgb(asset)
    mask = current_mask(asset)
    if mask is None:
        raise PipelineError("No cutout mask for this photo.")
    params = auto_color_params(red, mask, wb_strength=float(settings.get("white_balance_strength", 0.6)),
                               auto_exposure=bool(settings.get("auto_exposure", True)),
                               exposure_ev=float(settings.get("exposure_ev", 0.0)),
                               contrast=float(settings.get("contrast", 0.0)), warmth=float(settings.get("warmth", 0.0)))
    colored = apply_color(red, params)
    cleanup = cleanup_background(colored, mask) if bg == "cleanup" else None
    version = (db.scalar(select(func.max(AssetRender.version)).where(AssetRender.asset_id == asset.id)) or 0) + 1
    paths = media_paths(asset.watch_id)
    variants: dict = {}
    warnings: list[str] = []
    all_pass = True
    plate_info: dict = {}
    regions = enabled_regions(asset)
    context_plate = None
    for i, (key, canvas) in enumerate(CANVASES.items()):
        progress(25 + i * 22, f"Rendering {canvas.label}")
        plate = None
        if bg.startswith("ai_"):
            from app.imaging.ai_background import get_plate

            if context_plate is not None:
                plate = context_plate
            else:
                progress(25 + i * 22, "Generating background")
                plate, plate_info = get_plate(db, bg, canvas.width, canvas.height, asset=asset, watch=watch)
                if plate_info.get("mode") == "context_edit":
                    context_plate = plate
        out, plan, warns = render_canvas(colored, mask, canvas, background=bg,
                                         fill=float(settings.get("fill_ratio", canvas.fill)),
                                         angle=settings["rotation_resolved"], shadow=bool(settings.get("shadow", True)),
                                         plate=plate, plate_in_source_frame=context_plate is not None,
                                         cleanup_bg=cleanup)
        path = paths.renders / f"{asset.id}_r{version}_{key}.jpg"
        data = save_jpeg(out, path, quality=92)
        fid = fidelity_check(decode_rgb(data), red, mask, params, plan, regions,
                             bg_keeps_original=bg in ("keep_original",))
        all_pass = all_pass and fid["passed"]
        variants[key] = {"path": rel(path), "sha256": sha256_bytes(data), "width": canvas.width,
                         "height": canvas.height, "label": canvas.label, "plan": plan.as_dict(), "fidelity": fid}
        for w in warns:
            if w not in warnings:
                warnings.append(w)
    master = variants[MASTER_CANVAS]
    if bg in ("keep_original", "cleanup") and asset.source_profile != "edited":
        warnings.append("Original background kept: check it is tidy enough for a listing.")
    render = AssetRender(
        asset_id=asset.id, version=version,
        settings={**{k: settings.get(k) for k in ("white_balance_strength", "auto_exposure", "exposure_ev",
                                                  "contrast", "warmth", "shadow", "fill_ratio")},
                  "background": bg, "rotation_deg": settings["rotation_resolved"], "color": params},
        background_source=plate_info.get("source", f"local:{bg}"),
        master_path=master["path"], master_sha256=master["sha256"], variants=variants,
        fidelity={k: v["fidelity"] for k, v in variants.items()}, fidelity_passed=all_pass, warnings=warnings,
        inputs={"redaction_version": asset.redaction_version, "mask_version": asset.mask_version,
                "mask_source": asset.mask_source, "plate": plate_info or None},
        status="ok",
    )
    db.add(render)
    db.flush()
    asset.current_render_id = render.id
    asset.render_stale = False
    if asset.review_status in ("approved", "regenerate_requested"):
        asset.review_status = "pending"
    audit.record(db, actor, "photo_rendered",
                 f"Studio render v{version} ({bg.replace('_', ' ')}); fidelity {'passed' if all_pass else 'FAILED'}",
                 entity_type="asset", entity_id=asset.id, watch_id=asset.watch_id,
                 detail={"render_id": render.id, "background": bg, "fidelity_passed": all_pass})
    invalidate_stale(db, watch, "Photo re-rendered", actor)
    return render


# ---- full pipeline --------------------------------------------------------------------------------
def process_asset(db: Session, asset: Asset, actor: str = "system", progress: Progress = _noop,
                  force_segmentation: bool = False, render: bool = True) -> dict:
    asset.pipeline_status = "processing"
    asset.pipeline_error = None
    db.flush()
    progress(5, "Checking for serial numbers")
    run_safety_scan(db, asset, actor)
    db.flush()
    progress(30, "Cutting out the watch")
    run_segmentation(db, asset, actor, force=force_segmentation)
    db.flush()
    progress(55, "Inspecting quality")
    run_inspection(db, asset)
    watch = db.get(Watch, asset.watch_id)
    resolve_duplicates(db, watch)
    db.flush()
    rendered = False
    if render and asset.selected and asset.safety_status != "failed":
        render_asset(db, asset, actor, progress=lambda p, m: progress(60 + p * 0.38, m))
        rendered = True
    asset.pipeline_status = "ready"
    return {"selected": asset.selected, "safety": asset.safety_status, "rendered": rendered,
            "message": "Photo processed" if rendered else "Photo inspected"}
