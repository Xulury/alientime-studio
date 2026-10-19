"""Background job handlers for AI analysis and copy generation."""
from __future__ import annotations

from app.copywriter.channels import CHANNELS
from app.copywriter.generator import generate_copy
from app.db.models import Watch
from app.intel import service
from app.jobs.queue import JobContext, PermanentJobError, handler
from app.providers.base import BudgetExceeded, ProviderError, ProviderUnavailable
from app.providers.registry import get_provider


def _watch(ctx: JobContext) -> Watch:
    w = ctx.db.get(Watch, ctx.job.watch_id) if ctx.job.watch_id else None
    if w is None:
        raise PermanentJobError("The watch no longer exists.")
    return w


def _provider():
    p = get_provider()
    if not p.available:
        raise PermanentJobError("AI is not configured. Add OPENAI_API_KEY to .env, or use template copy.")
    return p


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except (BudgetExceeded, ProviderUnavailable) as e:
        raise PermanentJobError(str(e))
    except ProviderError as e:
        if e.retryable:
            raise
        raise PermanentJobError(str(e))


@handler("ai_tag_assets", "AI photo tagging")
def ai_tag_job(ctx: JobContext) -> dict:
    w = _watch(ctx)
    ctx.progress(15, "Sending checked photos for tagging")
    return _call(service.tag_frames, ctx.db, w, _provider(), ctx.job.created_by or "system", ctx.job.id)


@handler("listing_intel", "Listing intelligence")
def listing_intel_job(ctx: JobContext) -> dict:
    w = _watch(ctx)
    ctx.progress(15, "Comparing photos with the record")
    return _call(service.analyse_listing, ctx.db, w, _provider(), ctx.job.created_by or "system", ctx.job.id)


@handler("generate_copy", "Generate listing copy")
def generate_copy_job(ctx: JobContext) -> dict:
    w = _watch(ctx)
    mode = ctx.payload.get("mode", "template")
    channels = [c for c in ctx.payload.get("channels") or list(CHANNELS) if c in CHANNELS]
    section = ctx.payload.get("section")
    style = ctx.payload.get("style")
    provider = _provider() if mode == "ai" else None
    done, errors = 0, 0
    for i, ch in enumerate(channels):
        ctx.progress(5 + 90 * i / max(1, len(channels)), f"Writing {CHANNELS[ch].name}")
        copies = _call(generate_copy, ctx.db, w, [ch], mode=mode, actor=ctx.job.created_by or "system",
                       section=section, style=style, provider=provider, job_id=ctx.job.id)
        ctx.db.commit()
        done += 1
        errors += sum(len(c.validation.get("errors", [])) for c in copies)
    return {"channels": done, "validation_errors": errors,
            "message": f"Copy ready for {done} channel(s)" + (f"; {errors} issue(s) to fix" if errors else "")}
