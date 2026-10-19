"""Fact sheet assembly with provenance.

Facts come from (in order of trust):
  1. the inventory record entered by a person,
  2. approved records in the local specifications table,
  3. AI or Sheet suggestions that a person has explicitly accepted.

Nothing reaches listing copy unless it is in this fact sheet.
"""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import SpecRecord, Watch

BOX_PAPERS_LABELS = {
    "full_set": "Full set (box and papers)",
    "set_minus_box": "Papers and accessories, no box",
    "box_and_papers": "Box and papers",
    "papers_only": "Papers only",
    "box_only": "Box only",
    "watch_only": "Watch only",
    "unknown": "Unknown",
}
CUSTODY_LABELS = {"in_hand": "In hand", "consigned_offsite": "Consigned (held off-site)", "unknown": "Unknown"}
CONDITION_LABELS = {
    "unworn": "Unworn", "excellent": "Excellent", "very_good": "Very good", "good": "Good", "fair": "Fair",
}

INVENTORY_FIELDS = {
    "brand": "Brand", "model": "Model", "reference": "Reference", "year": "Year",
    "condition": "Condition", "condition_notes": "Condition notes", "price_sgd": "Price (SGD)",
    "price_usd": "Price (USD)", "box_papers": "Box and papers", "box_papers_notes": "Set details",
    "custody": "Custody", "description": "Description",
}
SPEC_FIELDS = {
    "calibre": "Calibre", "movement_type": "Movement", "case_size_mm": "Case size",
    "case_thickness_mm": "Case thickness", "case_material": "Case material", "dial": "Dial",
    "bezel": "Bezel", "crystal": "Crystal", "water_resistance": "Water resistance",
    "power_reserve": "Power reserve", "bracelet_strap": "Bracelet / strap", "functions": "Functions",
}
EXTRA_FIELDS = {
    "warranty": "Warranty", "service_history": "Service history", "auction_start_price": "Auction starting bid (SGD)",
    "accessories": "Accessories", "papers_date": "Papers dated",
}
ALL_FACT_LABELS = {**INVENTORY_FIELDS, **SPEC_FIELDS, **EXTRA_FIELDS}


def norm_ref(ref: str | None) -> str:
    return re.sub(r"[\s\-./]", "", (ref or "")).upper()


def find_spec(db: Session, watch: Watch) -> SpecRecord | None:
    """Linked approved spec, else an approved spec with the same brand and reference."""
    if watch.spec_id:
        spec = db.get(SpecRecord, watch.spec_id)
        if spec is not None and spec.status == "approved":
            return spec
    if not watch.reference:
        return None
    target = norm_ref(watch.reference)
    for spec in db.scalars(select(SpecRecord).where(SpecRecord.status == "approved")):
        if norm_ref(spec.reference) == target and spec.brand.strip().lower() == watch.brand.strip().lower():
            return spec
    return None


def _fmt(v: Any) -> Any:
    if isinstance(v, Decimal):
        return float(v)
    return v


def fact_sheet(db: Session, watch: Watch) -> dict[str, dict[str, Any]]:
    """field -> {value, label, source}. Only non-empty values are included."""
    out: dict[str, dict[str, Any]] = {}
    provenance = (watch.extra_facts or {}).get("_provenance", {})
    for f, label in INVENTORY_FIELDS.items():
        v = _fmt(getattr(watch, f))
        if v in (None, "") or (f in ("box_papers", "custody") and v == "unknown"):
            continue
        out[f] = {"value": v, "label": label, "source": provenance.get(f, "inventory")}
    spec = find_spec(db, watch)
    if spec is not None:
        for f, label in SPEC_FIELDS.items():
            v = getattr(spec, f)
            if v:
                out[f] = {"value": v, "label": label, "source": f"spec_table:{spec.id}"}
    for f, entry in (watch.extra_facts or {}).items():
        if f.startswith("_"):
            continue
        v = entry.get("value") if isinstance(entry, dict) else entry
        if v in (None, ""):
            continue
        src = entry.get("source", "inventory") if isinstance(entry, dict) else "inventory"
        out[f] = {"value": v, "label": ALL_FACT_LABELS.get(f, f.replace("_", " ").capitalize()), "source": src}
    return out


def confirmed_facts(db: Session, watch: Watch) -> dict[str, Any]:
    return {k: v["value"] for k, v in fact_sheet(db, watch).items()}


def display_value(field: str, value: Any) -> str:
    if field == "box_papers":
        return BOX_PAPERS_LABELS.get(value, str(value))
    if field == "custody":
        return CUSTODY_LABELS.get(value, str(value))
    if field == "condition":
        return CONDITION_LABELS.get(value, str(value))
    if field in ("price_sgd", "price_usd", "auction_start_price"):
        try:
            return f"{float(value):,.0f}" if float(value) == int(float(value)) else f"{float(value):,.2f}"
        except (TypeError, ValueError):
            return str(value)
    return str(value)
