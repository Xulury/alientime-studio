"""Copy checks run by code after every generation or edit.

* platform limits (title, full text, hashtags)
* required content (title, price where the channel shows one)
* fixed house blocks present word for word
* claim rules ("in hand", "full set", "unworn"…) backed by facts
* every number in written sections traceable to the facts
* no placeholders or banned phrases

Errors block approval. Warnings are shown but do not block.
"""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from app.copywriter.channels import SECTION_LABELS, ChannelDef

if TYPE_CHECKING:  # pragma: no cover
    from app.copywriter.generator import CopyContext

_NUM = re.compile(r"(?<![A-Za-z0-9.,])(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)")
_PLACEHOLDER = re.compile(r"(\[(?!(?:WTS|WTT|WTB)\])[A-Z _]{3,}\]|\bTBD\b|\bTODO\b|\bXXX+\b|lorem ipsum|\{\{|\}\})", re.IGNORECASE)


def _norm_number(s: str) -> str | None:
    try:
        d = Decimal(s.replace(",", ""))
    except InvalidOperation:
        return None
    d = d.normalize()
    return format(d, "f")


def numbers_in(text: str) -> set[str]:
    out = set()
    for m in _NUM.finditer(text or ""):
        n = _norm_number(m.group(1))
        if n is not None:
            out.add(n)
            if "." in n:
                out.add(n.split(".")[0])
    return out


def fact_numbers(facts: dict[str, Any], extra_texts: list[str]) -> set[str]:
    nums: set[str] = set()
    for v in facts.values():
        s = str(v)
        nums |= numbers_in(s)
        # "RM 67-01" → 67, 01, 1, 6701 ; "116610LN" → 116610
        for tok in re.findall(r"\d+", s):
            nums.add(tok)
            nums.add(str(int(tok)))
        joined = re.sub(r"[^0-9]", "", s)
        if joined:
            nums.add(joined)
    for t in extra_texts:
        nums |= numbers_in(t)
    return nums


def _fact_satisfies(requirement: str, facts: dict[str, Any]) -> bool:
    req = requirement.strip()
    if req.startswith("fact:"):
        return bool(facts.get(req[5:]))
    m = re.match(r"(\w+)\s+in\s+(.+)", req)
    if m:
        return str(facts.get(m.group(1), "")) in [x.strip() for x in m.group(2).split(",")]
    m = re.match(r"(\w+)=(.+)", req)
    if m:
        return str(facts.get(m.group(1), "")) == m.group(2).strip()
    return False


def _phrase_in(phrase: str, text: str) -> bool:
    return re.search(r"(?<![A-Za-z])" + re.escape(phrase.lower()) + r"(?![A-Za-z])", text.lower()) is not None


def validate(ch: ChannelDef, sections: dict[str, Any], rendered: str, ctx: "CopyContext") -> dict[str, Any]:
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    sources = sections.get("_sources", {}) if isinstance(sections.get("_sources"), dict) else {}

    def err(section: str, msg: str):
        errors.append({"section": section, "message": msg})

    def warn(section: str, msg: str):
        warnings.append({"section": section, "message": msg})

    title = (sections.get("title") or "").strip()
    counts = {"text": len(rendered), "title": len(title), "hashtags": len(sections.get("hashtags") or [])}

    # limits
    if ch.has_title and not title:
        err("title", "Title is empty.")
    tl = ch.limits.get("title")
    if tl and len(title) > tl.max_chars:
        err("title", f"Title is {len(title)} characters; {ch.name} allows {tl.max_chars}.")
    text_limit = ch.limits.get("text")
    if text_limit and len(rendered) > text_limit.max_chars:
        err("body", f"Text is {len(rendered)} characters; {ch.name} allows {text_limit.max_chars}"
                    + ("" if text_limit.verified else " (internal limit)") + ". Shorten the description.")
    if ch.hashtags_max and counts["hashtags"] > ch.hashtags_max:
        err("hashtags", f"{counts['hashtags']} hashtags; {ch.name} allows {ch.hashtags_max}.")
    if ch.title_prefix and title and not title.startswith(ch.title_prefix.strip()):
        warn("title", f"Title should start with {ch.title_prefix.strip()}.")

    # required facts
    if "price" in ch.text_sections and not (sections.get("price") or "").strip():
        need = "USD" if ch.currency == "USD" else "SGD"
        err("price", f"Price in {need} is missing from the watch facts.")
    if ch.key == "ebay" and ctx.facts.get("price_usd") is None:
        err("price", "eBay needs the price in USD.")
    if ch.key in ("chrono24", "shopify", "carousell", "facebook_marketplace") and ctx.facts.get("price_sgd") is None:
        err("price", "Price in SGD is missing from the watch facts.")
    if ch.key == "moda_auction" and not (sections.get("auction") or "").strip():
        err("auction", "Add the auction starting bid (fact 'auction_start_price') for MODA @uction.")
    brand, model = str(ctx.facts.get("brand", "")), str(ctx.facts.get("model", ""))
    if ch.has_title and title and (brand.lower() not in title.lower() or model.lower() not in title.lower()):
        warn("title", "Title should include the brand and model exactly as recorded.")

    # fixed blocks, word for word
    fixed = ctx.fixed_for(ch.key)
    for key in ch.fixed_blocks:
        expected = fixed.get(key, "")
        if not expected:
            if key in ("terms", "disclaimer"):
                warn(key, f"{SECTION_LABELS[key]} is empty. Add your wording in Settings → House terms.")
            continue
        if (sections.get(key) or "") != expected or expected not in rendered:
            err(key, f"{SECTION_LABELS[key]} must match Settings word for word.")

    # claims, banned phrases, placeholders, numbers — on written (non-fixed) sections
    written = {k: (" ".join(v) if isinstance(v, list) else str(v or "")) for k, v in sections.items()
               if k in ("title", "body", "hashtags")}
    for key, text in written.items():
        if not text:
            continue
        for rule in ctx.claims.get("rules", []):
            if _phrase_in(rule["phrase"], text) and not _fact_satisfies(rule["requires"], ctx.facts):
                err(key, f"'{rule['phrase']}' is not supported by the facts ({rule['requires']}).")
        for phrase in ctx.claims.get("banned", []):
            if _phrase_in(phrase, text):
                err(key, f"'{phrase}' is not allowed in listings.")
        if _PLACEHOLDER.search(text):
            err(key, "Contains placeholder text.")
        allowed = fact_numbers(ctx.facts, [ch.title_prefix])
        unknown = sorted(n for n in numbers_in(text) if n not in allowed)
        if unknown:
            msg = "Numbers not in the confirmed facts: " + ", ".join(unknown[:6])
            if sources.get(key) == "user":
                warn(key, msg + " (written by you — confirm or add them as facts).")
            else:
                err(key, msg + ". Regenerate, edit, or add the fact first.")
        if re.search(r"\bserial\b", text, re.IGNORECASE):
            err(key, "Do not mention serial numbers in listings.")

    return {"errors": errors, "warnings": warnings, "counts": counts, "ok": not errors,
            "limits": {k: {"max": v.max_chars, "verified": v.verified, "source": v.source} for k, v in ch.limits.items()}}
