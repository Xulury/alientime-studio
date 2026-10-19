"""Structured-output schemas for AI calls, validated with Pydantic after every response."""
from __future__ import annotations

import copy
from typing import Literal

from pydantic import BaseModel, Field

PhotoType = Literal["dial_front", "side_profile", "crown_side", "clasp", "strap", "caseback", "movement",
                    "box_papers", "document", "detail", "wrist", "unclassified"]


class FrameTag(BaseModel):
    index: int
    photo_type: PhotoType
    confidence: float = Field(ge=0, le=1)
    watch_fully_visible: bool
    same_watch_as_others: Literal["yes", "no", "uncertain"]
    issues: list[str]


class TaggingResult(BaseModel):
    frames: list[FrameTag]
    different_watch_suspected: bool
    notes: str


class Observed(BaseModel):
    value: str | None
    confidence: float = Field(ge=0, le=1)
    evidence: str


class Mismatch(BaseModel):
    field: Literal["brand", "model", "reference", "dial", "case_material", "bracelet_strap", "bezel", "other"]
    inventory_value: str | None
    observed_value: str | None
    explanation: str


class ListingIntel(BaseModel):
    brand: Observed
    model: Observed
    reference_visible: Observed
    dial: Observed
    case_material: Observed
    bracelet_strap: Observed
    bezel: Observed
    complications: list[str]
    condition_observations: list[str]
    mismatches: list[Mismatch]
    different_watch_suspected: bool
    notes: str


class CopyDraft(BaseModel):
    title: str | None
    body: str | None
    caption: str | None
    hashtags: list[str]
    condition_line: str | None
    used_fact_keys: list[str]


def strict_schema(model: type[BaseModel]) -> dict:
    """Pydantic JSON schema → OpenAI strict structured-output schema.

    Inlines $refs, closes every object (additionalProperties: false), marks every property required
    and drops keywords strict mode does not accept.
    """
    raw = model.model_json_schema()
    defs = raw.pop("$defs", {})

    def walk(node):
        if isinstance(node, dict):
            if "$ref" in node:
                name = node["$ref"].split("/")[-1]
                return walk(copy.deepcopy(defs[name]))
            out = {}
            for k, v in node.items():
                if k in ("title", "default", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
                         "maxLength", "minLength", "maxItems", "minItems", "examples"):
                    continue
                out[k] = walk(v)
            if out.get("type") == "object" and "properties" in out:
                out["additionalProperties"] = False
                out["required"] = list(out["properties"].keys())
            return out
        if isinstance(node, list):
            return [walk(x) for x in node]
        return node

    return walk(raw)
