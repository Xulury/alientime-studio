"""Request models with validation."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

BoxPapers = Literal["full_set", "set_minus_box", "box_and_papers", "papers_only", "box_only", "watch_only", "unknown"]
Custody = Literal["in_hand", "consigned_offsite", "unknown"]
Condition = Literal["unworn", "excellent", "very_good", "good", "fair"]
Signoff = Literal["not_required", "pending", "approved"]

Price = Decimal


class WatchFields(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    brand: str | None = Field(default=None, max_length=120)
    model: str | None = Field(default=None, max_length=200)
    reference: str | None = Field(default=None, max_length=120)
    year: str | None = Field(default=None, max_length=20)
    condition: Condition | None = None
    condition_notes: str | None = Field(default=None, max_length=2000)
    price_sgd: Price | None = Field(default=None, ge=0, le=Decimal("100000000"))
    price_usd: Price | None = Field(default=None, ge=0, le=Decimal("100000000"))
    fx_rate_sgd_usd: Decimal | None = Field(default=None, gt=0, le=Decimal("100"))
    fx_source: str | None = Field(default=None, max_length=40)
    box_papers: BoxPapers | None = None
    box_papers_notes: str | None = Field(default=None, max_length=1000)
    custody: Custody | None = None
    is_consignment: bool | None = None
    consignor_name: str | None = Field(default=None, max_length=200)
    consignor_contact: str | None = Field(default=None, max_length=200)
    consignment_ref: str | None = Field(default=None, max_length=120)
    consignment_terms: str | None = Field(default=None, max_length=4000)
    consignment_payout_sgd: Price | None = Field(default=None, ge=0, le=Decimal("100000000"))
    consignment_start: date | None = None
    consignment_end: date | None = None
    consignor_signoff: Signoff | None = None
    description: str | None = Field(default=None, max_length=6000)
    internal_notes: str | None = Field(default=None, max_length=6000)
    extra_facts: dict[str, Any] | None = None
    spec_id: str | None = Field(default=None, max_length=32)

    @field_validator("extra_facts")
    @classmethod
    def _check_extra(cls, v):
        if v is None:
            return v
        if len(v) > 40:
            raise ValueError("Too many extra facts.")
        clean: dict[str, Any] = {}
        for k, val in v.items():
            if not isinstance(k, str) or not k.replace("_", "").isalnum() or len(k) > 40 or k.startswith("_"):
                raise ValueError(f"Invalid fact name: {k}")
            if isinstance(val, dict):
                val = {"value": str(val.get("value", ""))[:500], "source": str(val.get("source", "inventory"))[:60]}
            else:
                val = {"value": str(val)[:500], "source": "inventory"}
            clean[k] = val
        return clean


class WatchCreate(WatchFields):
    sku: str | None = Field(default=None, max_length=60)
    brand: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=200)


class WatchUpdate(WatchFields):
    sku: str | None = Field(default=None, max_length=60)


class StatusChange(BaseModel):
    action: Literal["reserved", "sold", "withdrawn", "available", "reopen"]
    note: str | None = Field(default=None, max_length=500)


class GalleryIn(BaseModel):
    asset_ids: list[str] = Field(max_length=60)
    hero_asset_id: str | None = None


class AssetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    photo_type: Literal["dial_front", "side_profile", "crown_side", "clasp", "strap", "caseback", "movement",
                        "box_papers", "document", "detail", "wrist", "unclassified"] | None = None
    selection_override: bool | None = None
    clear_selection_override: bool = False
    sort_order: int | None = None


class RegionIn(BaseModel):
    id: str | None = None
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    w: float = Field(gt=0, le=1)
    h: float = Field(gt=0, le=1)
    enabled: bool = True


class RegionsIn(BaseModel):
    regions: list[RegionIn] = Field(max_length=200)


class SafetyReviewIn(BaseModel):
    confirm: bool
    note: str | None = Field(default=None, max_length=500)


class StudioSettingsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    background: Literal["auto", "keep_original", "cleanup", "studio_white", "studio_grey", "studio_black",
                        "green_velvet", "ai_velvet", "ai_studio"] | None = None
    white_balance_strength: float | None = Field(default=None, ge=0, le=1)
    auto_exposure: bool | None = None
    exposure_ev: float | None = Field(default=None, ge=-1.5, le=1.5)
    contrast: float | None = Field(default=None, ge=-30, le=30)
    warmth: float | None = Field(default=None, ge=-20, le=20)
    shadow: bool | None = None
    fill_ratio: float | None = Field(default=None, ge=0.4, le=0.95)
    rotation_deg: float | None = Field(default=None, ge=-60, le=60)
    hero: bool | None = None


class ReviewDecision(BaseModel):
    decision: Literal["approve", "reject", "regenerate", "reset"]
    note: str | None = Field(default=None, max_length=1000)
