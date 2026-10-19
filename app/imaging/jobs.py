"""Background job handlers for the photo pipeline."""
from __future__ import annotations

from app.db.models import Asset
from app.imaging import pipeline
from app.jobs.queue import JobContext, PermanentJobError, handler


def _asset(ctx: JobContext) -> Asset:
    asset = ctx.db.get(Asset, ctx.job.asset_id) if ctx.job.asset_id else None
    if asset is None or asset.removed_at is not None:
        raise PermanentJobError("The photo no longer exists.")
    return asset


def _run(ctx: JobContext, fn, *args, **kwargs):
    asset = _asset(ctx)
    try:
        return asset, fn(ctx.db, asset, *args, **kwargs)
    except pipeline.PipelineError as e:
        ctx.db.rollback()
        a = ctx.db.get(Asset, ctx.job.asset_id)
        if a is not None:
            a.pipeline_status = "needs_attention"
            a.pipeline_error = str(e)
            ctx.db.commit()
        raise PermanentJobError(str(e))
    except Exception as e:
        ctx.db.rollback()
        a = ctx.db.get(Asset, ctx.job.asset_id)
        if a is not None:
            a.pipeline_status = "failed"
            a.pipeline_error = f"{type(e).__name__}: {e}"[:500]
            ctx.db.commit()
        raise


@handler("process_asset", "Process photo")
def process_asset_job(ctx: JobContext) -> dict:
    actor = ctx.job.created_by or "system"
    _, result = _run(ctx, pipeline.process_asset, actor, progress=ctx.progress,
                     force_segmentation=bool(ctx.payload.get("force_segmentation")),
                     render=ctx.payload.get("render", True))
    return result


@handler("render_asset", "Render studio image")
def render_asset_job(ctx: JobContext) -> dict:
    actor = ctx.job.created_by or "system"
    asset, render = _run(ctx, pipeline.render_asset, actor, progress=ctx.progress)
    asset.pipeline_status = "ready"
    return {"render_id": render.id, "fidelity_passed": render.fidelity_passed,
            "message": "Studio image ready" if render.fidelity_passed else "Rendered, but the fidelity check failed"}


@handler("safety_scan", "Privacy check")
def safety_scan_job(ctx: JobContext) -> dict:
    actor = ctx.job.created_by or "system"
    ctx.progress(10, "Reading text in the photo")
    _, result = _run(ctx, pipeline.run_safety_scan, actor)
    return {**result, "message": f"Privacy check: {result['status'].replace('_', ' ')}"}


@handler("segment_asset", "Cut out watch")
def segment_asset_job(ctx: JobContext) -> dict:
    actor = ctx.job.created_by or "system"
    ctx.progress(10, "Cutting out the watch")
    _, result = _run(ctx, pipeline.run_segmentation, actor, force=True)
    asset = _asset(ctx)
    pipeline.run_inspection(ctx.db, asset)
    return {**result, "message": "Cutout updated"}
