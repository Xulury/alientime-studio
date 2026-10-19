"""Business settings stored in the database (house terms, styles, studio defaults, FX, pricing table).

These are editable in Settings. Secrets never live here; they come from environment variables.
"""
from __future__ import annotations

import copy
from typing import Any

from sqlalchemy.orm import Session

from app.db.base import utcnow
from app.db.models import AppSetting

ALL_CHANNELS = [
    "shopify", "instagram", "facebook_page", "chrono24", "ebay", "facebook_marketplace",
    "facebook_groups", "carousell", "whatsapp_groups", "reddit_watchexchange", "moda_auction",
]

DEFAULTS: dict[str, Any] = {
    "fixed_blocks": {
        # Empty until the business enters its own wording. Readiness checks flag empty blocks.
        "terms": "",
        "disclaimer": "",
        "licence": "",
        "contact": "",
        "cta": "Message us to arrange a viewing or for more photos.",
        "channel_overrides": {},  # {"instagram": {"cta": "DM us for details."}}
    },
    "house_style": {
        "voice": (
            "Write like a knowledgeable Singapore watch dealer: precise, calm and factual. "
            "No hype words, no emojis except where the channel style allows them, no exclamation marks."
        ),
        "styles": {
            "house": "Measured and factual. Short paragraphs. Lead with the model and what makes this piece notable, using only confirmed facts.",
            "concise": "As short as possible. Bullet-style facts, no adjectives beyond what the facts state.",
            "collector": "For collectors: reference-led, mentions calibre and case details from the specs table. No speculation.",
            "social": "Social caption: one strong opening line, then key facts on separate lines. Hashtags at the end.",
        },
        "channel_styles": {
            "instagram": "social", "facebook_page": "social", "whatsapp_groups": "concise",
            "facebook_groups": "concise", "moda_auction": "concise", "carousell": "concise",
            "reddit_watchexchange": "collector", "chrono24": "collector", "shopify": "house",
            "ebay": "house", "facebook_marketplace": "concise",
        },
        "default_hashtags": ["#AlienTime", "#LuxuryWatches", "#WatchesOfSingapore"],
        "brand_hashtags": True,
    },
    "pricing": {
        "fx_sgd_usd": None,       # e.g. 0.77 — entered by the business; never fetched silently
        "fx_updated_at": None,
        "drift_tolerance_pct": 3.0,
        "show_price_on": ALL_CHANNELS,
    },
    "studio": {
        "default_background": "green_velvet",
        "edited_background": "keep_original",
        "white_balance_strength": 0.6,
        "auto_exposure": True,
        "exposure_ev": 0.0,
        "contrast": 0.0,
        "warmth": 0.0,
        "shadow": True,
        "fill_ratio": 0.78,
        "hero_rotation_deg": 0.0,
        "min_sharpness": 35.0,
        "min_resolution": 700,
    },
    "channels": {
        "enabled": ALL_CHANNELS,
        "max_images": {},
    },
    "claims": {
        # Phrases that may only appear when a fact supports them. Checked by code, case-insensitive.
        "rules": [
            {"phrase": "in hand", "requires": "custody=in_hand"},
            {"phrase": "full set", "requires": "box_papers=full_set"},
            {"phrase": "unworn", "requires": "condition=unworn"},
            {"phrase": "brand new", "requires": "condition=unworn"},
            {"phrase": "bnib", "requires": "condition=unworn"},
            {"phrase": "warranty", "requires": "fact:warranty"},
            {"phrase": "service", "requires": "fact:service_history"},
            {"phrase": "box and papers", "requires": "box_papers in full_set,box_and_papers"},
        ],
        "banned": ["investment grade", "guaranteed appreciation", "cheapest"],
    },
    "ai_pricing": {
        # USD per 1M tokens, from developers.openai.com/api/docs/pricing (checked 2026-10-18).
        # Estimates only; your OpenAI invoice is authoritative.
        "gpt-6.1-sol": {"input": 2.00, "output": 10.00},
        "gpt-6-luna": {"input": 0.10, "output": 0.50},
        "gpt-6-astra": {"input": 10.00, "output": 50.00},
        "gpt-5.6-sol": {"input": 4.00, "output": 20.00},
        "gpt-image-2": {"input": 4.00, "output": 15.00, "text_input": 2.50},
        "gpt-image-2.5-sunburst": {"input": 8.00, "output": 30.00, "text_input": 5.00},
        "gpt-image-2.5-flare": {"input": 8.00, "output": 30.00, "text_input": 5.00},
        "_default": {"input": 10.00, "output": 50.00},
    },
}


def _merge(default: Any, stored: Any) -> Any:
    if isinstance(default, dict) and isinstance(stored, dict):
        out = copy.deepcopy(default)
        for k, v in stored.items():
            out[k] = _merge(default.get(k), v) if k in default else v
        return out
    return copy.deepcopy(stored) if stored is not None else copy.deepcopy(default)


def get_setting(db: Session, key: str) -> Any:
    row = db.get(AppSetting, key)
    default = DEFAULTS.get(key)
    if row is None:
        return copy.deepcopy(default)
    return _merge(default, row.value) if default is not None else row.value


def set_setting(db: Session, key: str, value: Any, actor: str | None = None) -> Any:
    row = db.get(AppSetting, key)
    if row is None:
        row = AppSetting(key=key, value=value, updated_by=actor)
        db.add(row)
    else:
        row.value = value
        row.updated_at = utcnow()
        row.updated_by = actor
    return get_setting(db, key)


def all_settings(db: Session) -> dict[str, Any]:
    return {k: get_setting(db, k) for k in DEFAULTS}
