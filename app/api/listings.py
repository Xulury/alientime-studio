"""Listing intelligence (facts, suggestions, AI analysis) and channel copy."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import Principal, require
from app.api.views import job_view
from app.api.watches import get_watch
from app.copywriter.channels import CHANNELS, SECTION_KIND, SECTION_LABELS, channel_info
from app.copywriter.generator import build_context, copy_is_stale, edit_copy, generate_copy, restore_revision
from app.core import audit
from app.core.errors import AppError, NotFound
from app.core.settings_store import get_setting
from app.db.base import get_db, iso, utcnow
from app.db.models import ChannelCopy, CopyRevision, FactSuggestion, SpecRecord
from app.intel.facts import ALL_FACT_LABELS, fact_sheet, find_spec
from app.intel.missing import fact_issues
from app.intel.service import eligible_frames, resolve_suggestion
from app.jobs.queue import enqueue
from app.providers.registry import get_provider
from app.review.approvals import approval_valid, latest_approval

router = APIRouter(prefix="/api/watches", tags=["listing"])


class SuggestionDecision(BaseModel):
    accept: bool
    value: str | None = Field(default=None, max_length=500)


class GenerateIn(BaseModel):
    channels: list[str] | None = None
    mode: Literal["template", "ai"] = "template"
    section: Literal["title", "body", "hashtags"] | None = None
    style: str | None = Field(default=None, max_length=40)


class CopyEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(default=None, max_length=500)
    body: str | None = Field(default=None, max_length=20000)
    hashtags: list[str] | str | None = None


@router.get("/{watch_id}/facts")
def facts(watch_id: str, db: Session = Depends(get_db), _: Principal = Depends(require("read"))) -> dict:
    w = get_watch(db, watch_id)
    spec = find_spec(db, w)
    frames, skipped = eligible_frames(db, w)
    return {
        "facts": fact_sheet(db, w),
        "issues": [i.as_dict() for i in fact_issues(db, w)],
        "suggestions": [{"id": s.id, "field": s.field, "label": ALL_FACT_LABELS.get(s.field, s.field), "value": s.value,
                         "source": s.source, "evidence": s.evidence, "confidence": s.confidence,
                         "created_at": iso(s.created_at)}
                        for s in db.scalars(select(FactSuggestion).where(FactSuggestion.watch_id == w.id,
                                                                         FactSuggestion.status == "open"))],
        "spec": {"id": spec.id, "brand": spec.brand, "model": spec.model, "reference": spec.reference} if spec else None,
        "ai": {"available": get_provider().available, "provider": get_provider().name,
               "eligible_frames": len(frames), "kept_local": skipped},
        "labels": ALL_FACT_LABELS,
    }


@router.post("/{watch_id}/suggestions/{suggestion_id}")
def decide_suggestion(watch_id: str, suggestion_id: str, body: SuggestionDecision, db: Session = Depends(get_db),
                      principal: Principal = Depends(require("intake"))) -> dict:
    w = get_watch(db, watch_id, include_archived=False)
    sug = db.get(FactSuggestion, suggestion_id)
    if sug is None or sug.watch_id != w.id:
        raise NotFound("Suggestion not found.")
    resolve_suggestion(db, w, sug, body.accept, principal.actor, body.value)
    db.commit()
    return {"ok": True, "status": sug.status}


@router.post("/{watch_id}/ai/tag")
def ai_tag(watch_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require("process"))) -> dict:
    w = get_watch(db, watch_id, include_archived=False)
    if not get_provider().available:
        raise AppError("AI is not configured. Add OPENAI_API_KEY to the .env file.", code="ai_not_configured")
    job = enqueue(db, "ai_tag_assets", watch_id=w.id, created_by=principal.actor,
                  idempotency_key=f"tag:{w.id}:{utcnow().timestamp()}", max_attempts=2)
    db.commit()
    return job_view(job)


@router.post("/{watch_id}/ai/intel")
def ai_intel(watch_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require("process"))) -> dict:
    w = get_watch(db, watch_id, include_archived=False)
    if not get_provider().available:
        raise AppError("AI is not configured. Add OPENAI_API_KEY to the .env file.", code="ai_not_configured")
    job = enqueue(db, "listing_intel", watch_id=w.id, created_by=principal.actor,
                  idempotency_key=f"intel:{w.id}:{utcnow().timestamp()}", max_attempts=2)
    db.commit()
    return job_view(job)


@router.post("/{watch_id}/sheet-import")
def sheet_import(watch_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require("intake"))) -> dict:
    from app.integrations.google import GoogleSheets

    w = get_watch(db, watch_id, include_archived=False)
    sheets = GoogleSheets()
    if not sheets.is_configured():
        raise AppError("Google Sheets is not configured (see Settings → Integrations).", code="not_configured")
    row = sheets.row_for(w.sku)
    if row is None:
        raise NotFound(f"No row for {w.sku} in the facts Sheet.")
    created = 0
    for field, value in row.items():
        if field == "sku":
            continue
        current = getattr(w, field, None)
        if current not in (None, "", "unknown") and str(current).strip() == value:
            continue
        db.add(FactSuggestion(watch_id=w.id, field=field, value=value, source="google_sheet", evidence="Facts Sheet row"))
        created += 1
    audit.record(db, principal.actor, "sheet_import", f"{created} suggestion(s) from the facts Sheet",
                 entity_type="watch", entity_id=w.id, watch_id=w.id)
    db.commit()
    return {"suggestions": created}


# ---- copy ----------------------------------------------------------------------------------------
def copy_view(db: Session, w, c: ChannelCopy | None, key: str, ctx=None) -> dict[str, Any]:
    info = channel_info(key)
    out = {**info, "copy": None, "approved": False, "approval": None}
    if c is None:
        return out
    sections = {k: v for k, v in c.sections.items() if not k.startswith("_")}
    a = latest_approval(db, w.id, "channel", key)
    out.update({
        "copy": {
            "id": c.id, "version": c.version, "sections": sections, "sources": c.sections.get("_sources", {}),
            "text": c.rendered_text, "generator": c.generator, "style": c.style, "validation": c.validation,
            "updated_at": iso(c.updated_at), "updated_by": c.updated_by, "stale": copy_is_stale(db, w, c, ctx),
            "hash": c.content_hash[:12],
        },
        "approved": approval_valid(db, w, "channel", key),
        "approval": {"status": a.status, "approved_by": a.approved_by, "approved_at": iso(a.approved_at),
                     "invalidated_reason": a.invalidated_reason} if a else None,
    })
    return out


@router.get("/{watch_id}/copy")
def get_copy(watch_id: str, db: Session = Depends(get_db), _: Principal = Depends(require("read"))) -> dict:
    w = get_watch(db, watch_id)
    copies = {c.channel: c for c in db.scalars(select(ChannelCopy).where(ChannelCopy.watch_id == w.id))}
    enabled = get_setting(db, "channels").get("enabled") or list(CHANNELS)
    ctx = build_context(db, w)
    styles = list((get_setting(db, "house_style").get("styles") or {}).keys())
    chosen = w.channels
    views = []
    for k in CHANNELS:
        if k in enabled:
            v = copy_view(db, w, copies.get(k), k, ctx)
            v["included"] = chosen is None or k in chosen
            views.append(v)
    return {"channels": views, "watch_channels": chosen,
            "section_labels": SECTION_LABELS, "section_kinds": SECTION_KIND, "styles": styles,
            "ai": {"available": get_provider().available, "provider": get_provider().name}}


@router.post("/{watch_id}/copy/generate")
def generate(watch_id: str, body: GenerateIn, db: Session = Depends(get_db),
             principal: Principal = Depends(require("copy"))) -> dict:
    w = get_watch(db, watch_id, include_archived=False)
    from app.review.approvals import enabled_channels

    channels = [c for c in (body.channels or enabled_channels(db, w)) if c in CHANNELS]
    if not channels:
        raise AppError("Choose at least one channel.")
    if body.mode == "ai":
        if not get_provider().available:
            raise AppError("AI is not configured. Use template copy, or add OPENAI_API_KEY to .env.",
                           code="ai_not_configured")
        job = enqueue(db, "generate_copy", watch_id=w.id, created_by=principal.actor,
                      payload={"mode": "ai", "channels": channels, "section": body.section, "style": body.style},
                      idempotency_key=f"copy:{w.id}:{utcnow().timestamp()}", max_attempts=2)
        db.commit()
        return {"job": job_view(job)}
    try:
        copies = generate_copy(db, w, channels, mode="template", actor=principal.actor, section=body.section,
                               style=body.style)
    except ValueError as e:
        raise AppError(str(e))
    db.commit()
    ctx = build_context(db, w)
    return {"channels": [copy_view(db, w, c, c.channel, ctx) for c in copies]}


@router.put("/{watch_id}/copy/{channel}")
def update_copy(watch_id: str, channel: str, body: CopyEdit, db: Session = Depends(get_db),
                principal: Principal = Depends(require("copy"))) -> dict:
    w = get_watch(db, watch_id, include_archived=False)
    if channel not in CHANNELS:
        raise NotFound("Unknown channel.")
    edits = body.model_dump(exclude_unset=True)
    try:
        c = edit_copy(db, w, channel, edits, principal.actor)
    except ValueError as e:
        raise AppError(str(e))
    db.commit()
    return copy_view(db, w, c, channel)


@router.get("/{watch_id}/copy/{channel}/revisions")
def revisions(watch_id: str, channel: str, db: Session = Depends(get_db), _: Principal = Depends(require("read"))) -> dict:
    w = get_watch(db, watch_id)
    rows = db.scalars(select(CopyRevision).where(CopyRevision.watch_id == w.id, CopyRevision.channel == channel)
                      .order_by(CopyRevision.version.desc()).limit(50)).all()
    return {"items": [{"id": r.id, "version": r.version, "reason": r.reason, "generator": r.generator,
                       "created_at": iso(r.created_at), "created_by": r.created_by, "text": r.rendered_text,
                       "title": r.sections.get("title"), "hash": r.content_hash[:12]} for r in rows]}


@router.post("/{watch_id}/copy/{channel}/revisions/{revision_id}/restore")
def restore(watch_id: str, channel: str, revision_id: str, db: Session = Depends(get_db),
            principal: Principal = Depends(require("copy"))) -> dict:
    w = get_watch(db, watch_id, include_archived=False)
    rev = db.get(CopyRevision, revision_id)
    if rev is None or rev.watch_id != w.id or rev.channel != channel:
        raise NotFound("Revision not found.")
    c = restore_revision(db, w, rev, principal.actor)
    db.commit()
    return copy_view(db, w, c, channel)


@router.post("/{watch_id}/spec/{spec_id}")
def link_spec(watch_id: str, spec_id: str, db: Session = Depends(get_db),
              principal: Principal = Depends(require("intake"))) -> dict:
    from app.review.approvals import invalidate_stale

    w = get_watch(db, watch_id, include_archived=False)
    spec = db.get(SpecRecord, spec_id)
    if spec is None:
        raise NotFound("Spec record not found.")
    if spec.status != "approved":
        raise AppError("Approve the spec record before linking it.")
    w.spec_id = spec.id
    w.content_version += 1
    audit.record(db, principal.actor, "spec_linked", f"Linked spec record {spec.brand} {spec.model} {spec.reference or ''}",
                 entity_type="watch", entity_id=w.id, watch_id=w.id)
    invalidate_stale(db, w, "Specification record linked", principal.actor)
    db.commit()
    return {"ok": True}
