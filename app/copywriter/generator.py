"""Channel copy generation.

Sections come from three places, and only one of them may be written by a model:
  * creative sections (title, description, hashtags): Jinja template or the AI text model
  * fact sections (specifications, condition, set, availability, price, auction): code, from confirmed facts
  * fixed sections (terms, disclaimer, licence, call to action): inserted by code, word for word

Every result is validated (limits, claims, numbers, fixed blocks) and saved as a new revision.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.copywriter.channels import CHANNELS, SECTION_KIND, ChannelDef
from app.copywriter.validation import validate
from app.core import audit
from app.core.settings_store import get_setting
from app.db.base import utcnow
from app.db.models import ChannelCopy, CopyRevision, Watch
from app.intel.facts import BOX_PAPERS_LABELS, CONDITION_LABELS, confirmed_facts, display_value
from app.review.approvals import digest, invalidate_stale

TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)), autoescape=False, trim_blocks=True,
                   lstrip_blocks=True, undefined=StrictUndefined)
EDITABLE_SECTIONS = {"title", "body", "hashtags"}


@dataclass
class CopyContext:
    facts: dict[str, Any]
    display: dict[str, str]
    fixed: dict[str, str]
    channel_fixed: dict[str, dict[str, str]]
    style: dict[str, Any]
    pricing: dict[str, Any]
    claims: dict[str, Any]
    watch: Watch

    def fixed_for(self, channel: str) -> dict[str, str]:
        out = {k: (self.fixed.get(k) or "").strip() for k in ("terms", "disclaimer", "licence", "contact", "cta")}
        for k, v in (self.channel_fixed.get(channel) or {}).items():
            if k in out and v is not None:
                out[k] = str(v).strip()
        return out


def build_context(db: Session, watch: Watch) -> CopyContext:
    facts = confirmed_facts(db, watch)
    display = {k: display_value(k, v) for k, v in facts.items()}
    fb = get_setting(db, "fixed_blocks")
    return CopyContext(facts=facts, display=display, fixed=fb, channel_fixed=fb.get("channel_overrides") or {},
                       style=get_setting(db, "house_style"), pricing=get_setting(db, "pricing"),
                       claims=get_setting(db, "claims"), watch=watch)


def fixed_blocks_hash(ctx: CopyContext, ch: ChannelDef) -> str:
    fx = ctx.fixed_for(ch.key)
    return digest({k: fx.get(k, "") for k in ch.fixed_blocks})


# ---- fact sections --------------------------------------------------------------------------------
def _money(v) -> str:
    return display_value("price_sgd", v)


def price_line(ch: ChannelDef, ctx: CopyContext) -> str:
    sgd, usd = ctx.facts.get("price_sgd"), ctx.facts.get("price_usd")
    if ch.currency == "USD":
        return f"Price: USD {_money(usd)}" if usd is not None else ""
    if ch.currency == "SGD+USD":
        if sgd is not None and usd is not None:
            return f"Price: SGD {_money(sgd)} (USD {_money(usd)})"
        return f"Price: SGD {_money(sgd)}" if sgd is not None else ""
    return f"Price: SGD {_money(sgd)}" if sgd is not None else ""


def fact_sections(ch: ChannelDef, ctx: CopyContext) -> dict[str, str]:
    f, d = ctx.facts, ctx.display
    specs = []
    for key, label in (("reference", "Reference"), ("year", "Year"), ("calibre", "Calibre"),
                       ("movement_type", "Movement"), ("functions", "Functions")):
        if f.get(key):
            specs.append(f"{label}: {d[key]}")
    case_bits = [x for x in (d.get("case_size_mm"), d.get("case_material")) if x]
    if case_bits:
        specs.append("Case: " + ", ".join(case_bits))
    for key, label in (("case_thickness_mm", "Thickness"), ("dial", "Dial"), ("bezel", "Bezel"),
                       ("crystal", "Crystal"), ("water_resistance", "Water resistance"),
                       ("power_reserve", "Power reserve"), ("bracelet_strap", "Bracelet / strap")):
        if f.get(key):
            specs.append(f"{label}: {d[key]}")
    bullet = "• " if ch.key in ("instagram", "facebook_page", "whatsapp_groups", "facebook_groups",
                                "moda_auction", "carousell", "facebook_marketplace") else "- "
    out: dict[str, str] = {"specs": "\n".join(bullet + s for s in specs)}
    cond = []
    if f.get("condition"):
        cond.append(f"Condition: {CONDITION_LABELS.get(f['condition'], d['condition'])}.")
    if f.get("condition_notes"):
        cond.append(str(f["condition_notes"]).strip().rstrip(".") + ".")
    out["condition"] = " ".join(cond)
    acc = []
    if f.get("box_papers"):
        acc.append(f"Set: {BOX_PAPERS_LABELS.get(f['box_papers'], d['box_papers'])}.")
    if f.get("box_papers_notes"):
        acc.append(str(f["box_papers_notes"]).strip().rstrip(".") + ".")
    if f.get("accessories"):
        acc.append(f"Also included: {str(f['accessories']).strip().rstrip('.')}.")
    if f.get("papers_date"):
        acc.append(f"Papers dated {f['papers_date']}.")
    if f.get("warranty"):
        acc.append(f"Warranty: {str(f['warranty']).strip().rstrip('.')}.")
    if f.get("service_history"):
        acc.append(f"Service history: {str(f['service_history']).strip().rstrip('.')}.")
    out["accessories"] = " ".join(acc)
    custody = f.get("custody")
    if custody == "in_hand":
        out["availability"] = "In hand in Singapore; viewing by appointment."
    elif custody == "consigned_offsite":
        out["availability"] = "Held by our consignment partner; viewing by appointment."
    else:
        out["availability"] = ""
    out["price"] = price_line(ch, ctx)
    if ch.key == "moda_auction":
        start = f.get("auction_start_price")
        out["auction"] = f"Starting bid: SGD {_money(start)}" if start not in (None, "") else ""
    return out


def fixed_sections(ch: ChannelDef, ctx: CopyContext) -> dict[str, str]:
    fx = ctx.fixed_for(ch.key)
    return {k: fx.get(k, "") for k in ch.fixed_blocks}


# ---- creative sections ----------------------------------------------------------------------------
def _hashtag(text: str) -> str:
    return "#" + re.sub(r"[^A-Za-z0-9]", "", text)


def template_hashtags(ch: ChannelDef, ctx: CopyContext) -> list[str]:
    if not ch.hashtags_max:
        return []
    tags = list(ctx.style.get("default_hashtags") or [])
    if ctx.style.get("brand_hashtags", True):
        tags.append(_hashtag(ctx.facts.get("brand", "")))
        tags.append(_hashtag(ctx.facts.get("model", "")))
    seen, out = set(), []
    for t in tags:
        if len(t) > 1 and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[: ch.hashtags_max]


def style_for(ch: ChannelDef, ctx: CopyContext, override: str | None = None) -> tuple[str, str]:
    name = override or (ctx.style.get("channel_styles") or {}).get(ch.key, "house")
    text = (ctx.style.get("styles") or {}).get(name) or (ctx.style.get("styles") or {}).get("house", "")
    return name, text


def _alnum(text: str) -> str:
    return re.sub(r"[^0-9a-z]", "", (text or "").lower())


def name_with_reference(f: dict[str, Any]) -> str:
    """Brand + model + reference, without repeating the model when the reference already contains it
    (model "RM 67-01", reference "RM67-01 TI" -> "Richard Mille RM67-01 TI")."""
    brand, model, ref = (str(f.get(k) or "").strip() for k in ("brand", "model", "reference"))
    if ref and len(_alnum(model)) >= 3 and _alnum(ref).startswith(_alnum(model)):
        return re.sub(r"\s+", " ", f"{brand} {ref}").strip()
    return re.sub(r"\s+", " ", f"{brand} {model} {ref}").strip()


def template_creative(ch: ChannelDef, ctx: CopyContext) -> dict[str, Any]:
    tmpl = _env.get_template(f"{ch.key}.j2")
    f = {**{k: "" for k in ("brand", "model", "reference", "year", "description", "calibre", "movement_type",
                             "case_size_mm", "case_material", "dial", "functions")}, **ctx.display}
    f["name_ref"] = name_with_reference(f)
    mod = tmpl.make_module({"f": f, "prefix": ch.title_prefix})
    title = re.sub(r"\s+", " ", str(mod.title()).strip()) if ch.has_title else ""
    body = re.sub(r"\n{3,}", "\n\n", str(mod.body()).strip())
    title_limit = ch.limits.get("title")
    if title and title_limit and len(title) > title_limit.max_chars:
        title = _fit_title(ch, ctx, title_limit.max_chars)
    return {"title": title, "body": body, "hashtags": template_hashtags(ch, ctx)}


def _fit_title(ch: ChannelDef, ctx: CopyContext, max_chars: int) -> str:
    f = ctx.display
    candidates = [
        f"{ch.title_prefix}{name_with_reference(f)}",
        f"{ch.title_prefix}{f.get('brand', '')} {f.get('model', '')}",
    ]
    for c in candidates:
        c = re.sub(r"\s+", " ", c).strip()
        if len(c) <= max_chars:
            return c
    return candidates[-1][:max_chars].rstrip()


def ai_creative(ch: ChannelDef, ctx: CopyContext, provider, *, rest_length: int, style: str | None,
                watch_id: str, job_id: str | None) -> dict[str, Any]:
    from app.providers.mock_provider import FACTS_MARKER
    from app.providers.schemas import CopyDraft

    style_name, style_text = style_for(ch, ctx, style)
    text_limit = ch.limits.get("text")
    title_limit = ch.limits.get("title")
    body_budget = (text_limit.max_chars - rest_length - 40) if text_limit else 1500
    body_budget = max(150, min(body_budget, 1800))
    claim_rules = "; ".join(f"'{r['phrase']}' only if {r['requires']}" for r in ctx.claims.get("rules", []))
    banned = ", ".join(ctx.claims.get("banned", []))
    system = (
        "You write listing copy for Alien Time, a luxury watch dealer in Singapore. "
        "Use ONLY the facts in FACTS_JSON. Never add specifications, history, provenance, condition details, "
        "accessories, prices, dates, measurements or any other number that is not in the facts. "
        "Never mention serial numbers. Do not write prices, terms, disclaimers, contact details or calls to "
        "action: the system adds those separately. If a fact is missing, leave it out rather than guess. "
        "List in used_fact_keys every fact key you relied on."
    )
    user = (
        f"Channel: {ch.name}. Audience: {ch.audience}\n"
        f"House voice: {ctx.style.get('voice', '')}\n"
        f"Style '{style_name}': {style_text}\n"
        f"Title: {'required' if ch.has_title else 'not used (return null)'}"
        + (f", at most {title_limit.max_chars} characters" if title_limit else ", one line")
        + (f", must start with '{ch.title_prefix.strip()}'" if ch.title_prefix else "") + ".\n"
        f"Body: at most {body_budget} characters, plain text, no bullet lists of specs (the system adds them).\n"
        f"Caption: same as body for social channels, else null.\n"
        f"Hashtags: {('up to ' + str(min(ch.hashtags_max, 12))) if ch.hashtags_max else 'none (return [])'}.\n"
        f"Wording rules: {claim_rules}. Never use: {banned}.\n"
        f"{'Emojis are acceptable sparingly.' if ch.emoji_ok else 'No emojis.'}\n\n"
        f"{FACTS_MARKER} {json.dumps(ctx.facts, default=str, ensure_ascii=False)}\n\n"
    )
    draft = provider.structured("text", system=system, text=user, images=None, schema_name="listing_copy",
                                response_model=CopyDraft, operation=f"copy:{ch.key}", watch_id=watch_id,
                                job_id=job_id)
    title = (draft.title or "").strip()
    if ch.title_prefix and title and not title.startswith(ch.title_prefix.strip()):
        title = ch.title_prefix + title
    body = (draft.body or draft.caption or "").strip()
    tags = [t if t.startswith("#") else "#" + t for t in (draft.hashtags or []) if t.strip()]
    tags = [_hashtag(t) for t in tags][: ch.hashtags_max] if ch.hashtags_max else []
    return {"title": title if ch.has_title else "", "body": body, "hashtags": tags}


# ---- assembly -------------------------------------------------------------------------------------
def assemble(ch: ChannelDef, sections: dict[str, Any]) -> str:
    parts: list[str] = []
    for key in ch.text_sections:
        v = sections.get(key)
        if key == "hashtags":
            v = " ".join(v or [])
        if v and str(v).strip():
            parts.append(str(v).strip())
    return "\n\n".join(parts)


def _rest_length(ch: ChannelDef, sections: dict[str, Any]) -> int:
    rest = {k: v for k, v in sections.items() if k not in ("body",)}
    return len(assemble(ch, rest))


def save_copy(db: Session, watch: Watch, ch: ChannelDef, sections: dict[str, Any], *, generator: str, style: str,
              actor: str, reason: str, ctx: CopyContext | None = None) -> ChannelCopy:
    ctx = ctx or build_context(db, watch)
    rendered = assemble(ch, sections)
    report = validate(ch, sections, rendered, ctx)
    copy = db.scalar(select(ChannelCopy).where(ChannelCopy.watch_id == watch.id, ChannelCopy.channel == ch.key))
    content_hash = digest({"sections": sections, "text": rendered})
    if copy is None:
        copy = ChannelCopy(watch_id=watch.id, channel=ch.key, version=0)
        db.add(copy)
    copy.sections = sections
    copy.rendered_text = rendered
    copy.version = (copy.version or 0) + 1
    copy.content_hash = content_hash
    copy.generator = generator
    copy.style = style
    copy.validation = report
    copy.fixed_blocks_hash = fixed_blocks_hash(ctx, ch)
    copy.facts_hash = digest(ctx.facts)
    copy.updated_at = utcnow()
    copy.updated_by = actor
    db.flush()
    db.add(CopyRevision(watch_id=watch.id, channel=ch.key, version=copy.version, sections=sections,
                        rendered_text=rendered, content_hash=content_hash, generator=generator, reason=reason,
                        created_by=actor))
    return copy


def generate_copy(db: Session, watch: Watch, channel_keys: list[str], *, mode: str, actor: str,
                  section: str | None = None, style: str | None = None, provider=None,
                  job_id: str | None = None) -> list[ChannelCopy]:
    """mode: 'template' (offline, deterministic) or 'ai'. `section` regenerates one creative section only."""
    if section and section not in EDITABLE_SECTIONS:
        raise ValueError("Only the title, description and hashtags can be regenerated.")
    ctx = build_context(db, watch)
    results = []
    for key in channel_keys:
        ch = CHANNELS[key]
        existing = db.scalar(select(ChannelCopy).where(ChannelCopy.watch_id == watch.id, ChannelCopy.channel == key))
        base = {**fact_sections(ch, ctx), **fixed_sections(ch, ctx)}
        sources = dict((existing.sections or {}).get("_sources", {})) if existing else {}
        if section and existing:
            sections = {k: v for k, v in existing.sections.items()}
            sections.update(base)  # always refresh facts and fixed blocks from the source of truth
        else:
            sections = dict(base)
        if mode == "ai":
            if provider is None:
                from app.providers.registry import get_provider

                provider = get_provider()
            creative = ai_creative(ch, ctx, provider, rest_length=_rest_length(ch, {**sections, "title": "x" * 40}),
                                   style=style, watch_id=watch.id, job_id=job_id)
            gen = f"ai:{provider.models().get('text', provider.name)}"
        else:
            creative = template_creative(ch, ctx)
            gen = "template"
        targets = [section] if section else ["title", "body", "hashtags"]
        for t in targets:
            sections[t] = creative.get(t, "" if t != "hashtags" else [])
            sources[t] = "ai" if mode == "ai" else "template"
        for k in base:
            sources[k] = SECTION_KIND.get(k, "facts")
        sections["_sources"] = sources
        style_name, _ = style_for(ch, ctx, style)
        reason = f"regenerated {section}" if section else ("generated with AI" if mode == "ai" else "generated from template")
        copy = save_copy(db, watch, ch, sections, generator=gen, style=style_name, actor=actor, reason=reason, ctx=ctx)
        audit.record(db, actor, "copy_generated", f"{ch.name}: {reason} (v{copy.version})",
                     entity_type="copy", entity_id=copy.id, watch_id=watch.id,
                     detail={"channel": key, "mode": mode, "section": section,
                             "errors": len(copy.validation.get("errors", []))})
        results.append(copy)
    invalidate_stale(db, watch, "Listing copy regenerated", actor)
    return results


def edit_copy(db: Session, watch: Watch, channel_key: str, edits: dict[str, Any], actor: str) -> ChannelCopy:
    ch = CHANNELS[channel_key]
    existing = db.scalar(select(ChannelCopy).where(ChannelCopy.watch_id == watch.id, ChannelCopy.channel == channel_key))
    if existing is None:
        raise ValueError("Generate copy for this channel first.")
    bad = set(edits) - EDITABLE_SECTIONS
    if bad:
        raise ValueError("Facts, prices and house terms are not edited here: change the watch facts or Settings instead.")
    ctx = build_context(db, watch)
    sections = {k: v for k, v in existing.sections.items()}
    sources = dict(sections.get("_sources", {}))
    changed = []
    for k, v in edits.items():
        if k == "hashtags":
            if isinstance(v, str):
                v = [t for t in re.split(r"[\s,]+", v) if t]
            v = [t if t.startswith("#") else "#" + t for t in v][:60]
        else:
            v = str(v or "").strip()[:20000]
        if sections.get(k) != v:
            sections[k] = v
            sources[k] = "user"
            changed.append(k)
    if not changed:
        return existing
    sections.update({**fact_sections(ch, ctx), **fixed_sections(ch, ctx)})
    sections["_sources"] = sources
    copy = save_copy(db, watch, ch, sections, generator=existing.generator, style=existing.style, actor=actor,
                     reason="edited " + ", ".join(changed), ctx=ctx)
    audit.record(db, actor, "copy_edited", f"{ch.name}: edited {', '.join(changed)} (v{copy.version})",
                 entity_type="copy", entity_id=copy.id, watch_id=watch.id, detail={"channel": channel_key})
    invalidate_stale(db, watch, f"{ch.name} copy edited", actor)
    return copy


def restore_revision(db: Session, watch: Watch, revision: CopyRevision, actor: str) -> ChannelCopy:
    ch = CHANNELS[revision.channel]
    ctx = build_context(db, watch)
    sections = dict(revision.sections)
    sections.update({**fact_sections(ch, ctx), **fixed_sections(ch, ctx)})
    copy = save_copy(db, watch, ch, sections, generator=revision.generator, style="restored", actor=actor,
                     reason=f"restored v{revision.version}", ctx=ctx)
    audit.record(db, actor, "copy_restored", f"{ch.name}: restored v{revision.version} as v{copy.version}",
                 entity_type="copy", entity_id=copy.id, watch_id=watch.id)
    invalidate_stale(db, watch, f"{ch.name} copy restored", actor)
    return copy


def copy_is_stale(db: Session, watch: Watch, copy: ChannelCopy, ctx: CopyContext | None = None) -> list[str]:
    """Reasons the saved copy no longer reflects current facts or house terms."""
    ctx = ctx or build_context(db, watch)
    ch = CHANNELS[copy.channel]
    reasons = []
    if copy.facts_hash and copy.facts_hash != digest(ctx.facts):
        reasons.append("Facts changed after this copy was written.")
    if copy.fixed_blocks_hash and copy.fixed_blocks_hash != fixed_blocks_hash(ctx, ch):
        reasons.append("House terms changed in Settings after this copy was written.")
    return reasons
