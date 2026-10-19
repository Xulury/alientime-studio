"""AI-assisted photo tagging and listing intelligence.

Only cloud-eligible frames are ever sent (redacted, never casebacks/movements/papers, checked by a
person unless the policy says otherwise). Whatever the model reports becomes an *observation* or a
*suggestion*; nothing changes the watch record until a person accepts it.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit
from app.db.base import utcnow
from app.db.models import AIObservation, Asset, FactSuggestion, Watch
from app.imaging.io import to_jpeg_bytes
from app.imaging.pipeline import cloud_eligible, redacted_rgb
from app.intel.facts import EXTRA_FIELDS, INVENTORY_FIELDS, SPEC_FIELDS, confirmed_facts, fact_sheet
from app.intel.missing import _same
from app.providers.base import ImagePart
from app.providers.mock_provider import FACTS_MARKER
from app.providers.schemas import ListingIntel, TaggingResult
from app.review.approvals import invalidate_stale

MAX_FRAMES = 10
INTEL_FRAMES = 4


def eligible_frames(db: Session, watch: Watch) -> tuple[list[Asset], list[dict]]:
    policy = get_settings().cloud_ai_image_policy
    ok, skipped = [], []
    for a in db.scalars(select(Asset).where(Asset.watch_id == watch.id, Asset.removed_at.is_(None))
                        .order_by(Asset.sort_order)):
        allowed, why = cloud_eligible(a, policy)
        if allowed:
            ok.append(a)
        else:
            skipped.append({"asset_id": a.id, "filename": a.original_filename, "reason": why})
    return ok, skipped


def _image_parts(frames: list[Asset]) -> list[ImagePart]:
    parts = []
    for a in frames:
        parts.append(ImagePart(to_jpeg_bytes(redacted_rgb(a), quality=88, max_edge=1280),
                               label=f"frame {a.sort_order}; local guess: {a.photo_type or 'unclassified'}"))
    return parts


def tag_frames(db: Session, watch: Watch, provider, actor: str, job_id: str | None = None) -> dict:
    frames, skipped = eligible_frames(db, watch)
    frames = frames[:MAX_FRAMES]
    if not frames:
        return {"tagged": 0, "skipped": skipped,
                "message": "No photos are cleared for AI yet. Check them on the Privacy step first."}
    system = ("You classify luxury watch photographs. For each image give the photo type and whether the whole "
              "watch is visible, and say whether every frame shows the same watch. Do not read or repeat any "
              "numbers, engravings or text from the photos.")
    text = f"There are {len(frames)} photos of one watch listed as {watch.brand} {watch.model}."
    result: TaggingResult = provider.structured("vision", system=system, text=text, images=_image_parts(frames),
                                                schema_name="photo_tags", response_model=TaggingResult,
                                                operation="photo_tagging", watch_id=watch.id, job_id=job_id)
    tagged = 0
    for tag in result.frames:
        if not (0 <= tag.index < len(frames)):
            continue
        a = frames[tag.index]
        a.ai_tags = {"photo_type": tag.photo_type, "confidence": tag.confidence, "fully_visible": tag.watch_fully_visible,
                     "same_watch": tag.same_watch_as_others, "issues": tag.issues[:6], "at": utcnow().isoformat()}
        if a.photo_type_source != "user":
            a.photo_type = tag.photo_type
            a.photo_type_source = "ai"
            a.photo_type_confidence = tag.confidence
        if tag.same_watch_as_others == "no":
            a.warnings = list(dict.fromkeys((a.warnings or []) + ["AI check: this frame may show a different watch."]))
        if tag.photo_type in ("caseback", "movement", "document", "box_papers") and a.safety_status == "clear":
            a.safety_status = "needs_review"
        tagged += 1
    obs = AIObservation(watch_id=watch.id, kind="image_tagging", provider=provider.name,
                        model=provider.models().get("vision", ""), asset_ids=[a.id for a in frames],
                        payload=result.model_dump())
    db.add(obs)
    audit.record(db, actor, "ai_photo_tagging", f"AI tagged {tagged} photo(s); {len(skipped)} kept local",
                 entity_type="watch", entity_id=watch.id, watch_id=watch.id,
                 detail={"different_watch": result.different_watch_suspected})
    return {"tagged": tagged, "skipped": skipped, "different_watch_suspected": result.different_watch_suspected,
            "message": f"Tagged {tagged} photo(s)"}


SUGGESTABLE = {"brand": "brand", "model": "model", "reference_visible": "reference", "dial": "dial",
               "case_material": "case_material", "bracelet_strap": "bracelet_strap", "bezel": "bezel"}


def analyse_listing(db: Session, watch: Watch, provider, actor: str, job_id: str | None = None) -> dict:
    frames, skipped = eligible_frames(db, watch)
    priority = {"dial_front": 0, "side_profile": 1, "crown_side": 2, "clasp": 3, "strap": 4}
    frames = sorted(frames, key=lambda a: priority.get(a.photo_type or "", 9))[:INTEL_FRAMES]
    facts = confirmed_facts(db, watch)
    public = {k: v for k, v in facts.items() if k not in ("price_sgd", "price_usd", "custody")}
    system = ("You compare photographs of a watch with its inventory record. Report what the photos show, with "
              "confidence and the visual evidence. Only report a reference number if it is printed on the dial "
              "or case exterior. Never report serial numbers. Never guess: use null when something is not visible. "
              "List mismatches between the photos and the record.")
    text = (f"Inventory record for this watch.\n{FACTS_MARKER} {json.dumps(public, default=str, ensure_ascii=False)}\n\n"
            f"There are {len(frames)} photos.")
    result: ListingIntel = provider.structured("intel", system=system, text=text, images=_image_parts(frames),
                                               schema_name="listing_intel", response_model=ListingIntel,
                                               operation="listing_intel", watch_id=watch.id, job_id=job_id)
    obs = AIObservation(watch_id=watch.id, kind="listing_intel", provider=provider.name,
                        model=provider.models().get("intel", ""), asset_ids=[a.id for a in frames],
                        payload=result.model_dump())
    db.add(obs)
    db.flush()
    sheet = fact_sheet(db, watch)
    created = 0
    for attr, field in SUGGESTABLE.items():
        o = getattr(result, attr)
        if not o.value or o.confidence < 0.5:
            continue
        current = sheet.get(field, {}).get("value")
        if current and _same(str(current), o.value):
            continue
        exists = db.scalar(select(FactSuggestion).where(FactSuggestion.watch_id == watch.id, FactSuggestion.field == field,
                                                        FactSuggestion.value == o.value))
        if exists:
            continue
        db.add(FactSuggestion(watch_id=watch.id, field=field, value=o.value[:500], source="ai_vision",
                              evidence=o.evidence[:500], confidence=o.confidence, observation_id=obs.id))
        created += 1
    if result.complications and not sheet.get("functions"):
        db.add(FactSuggestion(watch_id=watch.id, field="functions", value=", ".join(result.complications)[:300],
                              source="ai_vision", evidence="Visible on the dial", confidence=0.5, observation_id=obs.id))
        created += 1
    audit.record(db, actor, "ai_listing_intel",
                 f"AI compared {len(frames)} photo(s) with the record: {len(result.mismatches)} mismatch(es), "
                 f"{created} suggestion(s)", entity_type="watch", entity_id=watch.id, watch_id=watch.id)
    return {"frames": len(frames), "skipped": skipped, "mismatches": len(result.mismatches), "suggestions": created,
            "message": f"{created} suggestion(s), {len(result.mismatches)} possible mismatch(es)"}


def resolve_suggestion(db: Session, watch: Watch, sug: FactSuggestion, accept: bool, actor: str,
                       value: str | None = None) -> None:
    if sug.status != "open":
        return
    sug.status = "accepted" if accept else "dismissed"
    sug.resolved_at = utcnow()
    sug.resolved_by = actor
    if not accept:
        audit.record(db, actor, "suggestion_dismissed", f"Dismissed suggested {sug.field}: {sug.value}",
                     entity_type="watch", entity_id=watch.id, watch_id=watch.id)
        return
    final = (value if value is not None else sug.value).strip()
    prov_tag = f"{sug.source}_confirmed"
    extra = dict(watch.extra_facts or {})
    prov = dict(extra.get("_provenance", {}))
    if sug.field in INVENTORY_FIELDS and sug.field not in ("price_sgd", "price_usd"):
        setattr(watch, sug.field, final)
        prov[sug.field] = prov_tag
    else:
        extra[sug.field] = {"value": final, "source": prov_tag}
    extra["_provenance"] = prov
    watch.extra_facts = extra
    watch.content_version += 1
    audit.record(db, actor, "suggestion_accepted", f"Confirmed {sug.field}: {final} (suggested by {sug.source})",
                 entity_type="watch", entity_id=watch.id, watch_id=watch.id)
    invalidate_stale(db, watch, f"Fact confirmed ({sug.field})", actor)


ALL_FACT_FIELDS = {**INVENTORY_FIELDS, **SPEC_FIELDS, **EXTRA_FIELDS}
