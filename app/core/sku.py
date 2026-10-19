"""Automatic SKU assignment: AT-<brand code>-<4-digit sequence>, e.g. AT-RM-0007."""
from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Watch

SKU_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,59}$")

KNOWN_CODES = {
    "richard mille": "RM",
    "mb&f": "MBF",
    "h. moser & cie.": "HMC",
    "h. moser & cie": "HMC",
    "audemars piguet": "AP",
    "patek philippe": "PP",
    "vacheron constantin": "VC",
    "a. lange & söhne": "ALS",
    "a. lange & sohne": "ALS",
    "f.p. journe": "FPJ",
    "rolex": "ROL",
    "omega": "OME",
}


def brand_code(brand: str) -> str:
    key = brand.strip().lower()
    if key in KNOWN_CODES:
        return KNOWN_CODES[key]
    words = [w for w in re.split(r"[^A-Za-z0-9]+", brand) if w and w.lower() not in {"and", "cie", "co"}]
    if not words:
        return "GEN"
    if len(words) == 1:
        return words[0][:3].upper()
    return "".join(w[0] for w in words[:4]).upper()


def normalise_sku(value: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", value.strip()).strip("-").upper()
    if not SKU_RE.match(s):
        raise ValueError("SKU must be 2–60 letters, numbers, dashes or underscores.")
    return s


def next_sku(db: Session, brand: str) -> str:
    code = brand_code(brand)
    prefix = f"AT-{code}-"
    existing = db.scalars(select(Watch.sku).where(Watch.sku.like(f"{prefix}%"))).all()
    seq = 0
    for sku in existing:
        m = re.match(rf"^{re.escape(prefix)}(\d+)$", sku)
        if m:
            seq = max(seq, int(m.group(1)))
    return f"{prefix}{seq + 1:04d}"
