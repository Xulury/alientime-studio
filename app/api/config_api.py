"""Settings, AI configuration, integrations, agent tokens and the specifications library."""
from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.api.deps import ALL_SCOPES, DEFAULT_AGENT_SCOPES, Principal, require
from app.config import get_settings
from app.copywriter.channels import CHANNELS, channel_info
from app.core import audit
from app.core.errors import AppError, Forbidden, NotFound
from app.core.security import new_secret_token, token_digest
from app.core.settings_store import ALL_CHANNELS, DEFAULTS, all_settings, get_setting, set_setting
from app.db.base import get_db, iso, utcnow
from app.db.models import ApiToken, SpecRecord
from app.imaging.ocr import ocr_status
from app.integrations.base import CONNECTED, set_live_enabled
from app.integrations.registry import all_integrations, get_integration
from app.providers.registry import get_provider

router = APIRouter(prefix="/api", tags=["settings"])


# ---- business settings ---------------------------------------------------------------------------
class FixedBlocksIn(BaseModel):
    terms: str = Field(default="", max_length=4000)
    disclaimer: str = Field(default="", max_length=4000)
    licence: str = Field(default="", max_length=1000)
    contact: str = Field(default="", max_length=1000)
    cta: str = Field(default="", max_length=500)
    channel_overrides: dict[str, dict[str, str]] = Field(default_factory=dict)

    @field_validator("channel_overrides")
    @classmethod
    def _chk(cls, v):
        for ch, d in v.items():
            if ch not in CHANNELS:
                raise ValueError(f"Unknown channel {ch}")
            for k, val in d.items():
                if k not in ("cta", "terms", "disclaimer", "licence", "contact") or len(val) > 4000:
                    raise ValueError(f"Invalid override {ch}.{k}")
        return v


class HouseStyleIn(BaseModel):
    voice: str = Field(max_length=2000)
    styles: dict[str, str]
    channel_styles: dict[str, str]
    default_hashtags: list[str] = Field(max_length=30)
    brand_hashtags: bool = True

    @field_validator("styles")
    @classmethod
    def _styles(cls, v):
        if not v or len(v) > 12 or any(len(k) > 40 or len(t) > 1500 for k, t in v.items()):
            raise ValueError("Provide 1–12 styles with short names.")
        return v


class PricingIn(BaseModel):
    fx_sgd_usd: float | None = Field(default=None, gt=0, le=10)
    drift_tolerance_pct: float = Field(default=3.0, ge=0, le=50)
    show_price_on: list[str] = Field(default_factory=lambda: list(ALL_CHANNELS))


class StudioIn(BaseModel):
    default_background: Literal["studio_white", "studio_grey", "studio_black", "green_velvet", "cleanup", "keep_original",
                                "ai_velvet", "ai_studio"]
    edited_background: Literal["keep_original", "cleanup", "studio_white", "studio_grey", "studio_black", "green_velvet"]
    white_balance_strength: float = Field(ge=0, le=1)
    auto_exposure: bool
    exposure_ev: float = Field(ge=-1.5, le=1.5)
    contrast: float = Field(ge=-30, le=30)
    warmth: float = Field(ge=-20, le=20)
    shadow: bool
    fill_ratio: float = Field(ge=0.4, le=0.95)
    hero_rotation_deg: float = Field(ge=-60, le=60)
    min_sharpness: float = Field(ge=0, le=100)
    min_resolution: int = Field(ge=200, le=4000)


class ChannelsIn(BaseModel):
    enabled: list[str]

    @field_validator("enabled")
    @classmethod
    def _en(cls, v):
        bad = [c for c in v if c not in CHANNELS]
        if bad:
            raise ValueError(f"Unknown channel(s): {bad}")
        return v


class ClaimsIn(BaseModel):
    rules: list[dict[str, str]] = Field(max_length=60)
    banned: list[str] = Field(max_length=100)


SECTION_MODELS = {"fixed_blocks": FixedBlocksIn, "house_style": HouseStyleIn, "pricing": PricingIn,
                  "studio": StudioIn, "channels": ChannelsIn, "claims": ClaimsIn}


def system_status() -> dict:
    from app.imaging.segment import segmenter_status

    s = get_settings()
    try:
        seg = segmenter_status()
    except Exception as e:  # noqa: BLE001
        seg = {"backend": "unavailable", "note": str(e)[:200]}
    return {
        "environment": s.studio_env, "data_dir": str(s.studio_data_dir), "base_url": s.studio_base_url,
        "worker_mode": s.worker_mode, "ocr": ocr_status(), "segmentation": seg,
        "cloud_ai_image_policy": s.cloud_ai_image_policy, "ai_background_mode": s.ai_background_mode,
        "simulated_publishing": s.enable_simulated_publishing, "max_upload_mb": s.max_upload_mb,
        "cookie_secure": s.studio_cookie_secure,
    }


@router.get("/settings")
def get_all(db: Session = Depends(get_db), _: Principal = Depends(require("read"))) -> dict:
    data = all_settings(db)
    data.pop("ai_pricing", None)
    return {"settings": data, "system": system_status(), "channels": [channel_info(k) for k in CHANNELS]}


@router.put("/settings/{section}")
def put_section(section: str, body: dict[str, Any], db: Session = Depends(get_db),
                principal: Principal = Depends(require("settings"))) -> dict:
    model = SECTION_MODELS.get(section)
    if model is None:
        raise NotFound("Unknown settings section.")
    try:
        value = model.model_validate(body).model_dump()
    except Exception as e:  # pydantic validation error → friendly message
        raise AppError(f"Invalid settings: {str(e)[:300]}")
    if section == "claims":
        for r in value["rules"]:
            if not r.get("phrase") or not r.get("requires"):
                raise AppError("Each claim rule needs a phrase and a requirement.")
    if section == "pricing" and value.get("fx_sgd_usd"):
        value["fx_updated_at"] = utcnow().isoformat()
    set_setting(db, section, value, principal.actor)
    audit.record(db, principal.actor, "settings_changed", f"Settings updated: {section.replace('_', ' ')}",
                 detail={"section": section})
    db.commit()
    return {"section": section, "value": get_setting(db, section)}


@router.post("/settings/{section}/reset")
def reset_section(section: str, db: Session = Depends(get_db), principal: Principal = Depends(require("settings"))) -> dict:
    if section not in DEFAULTS or section == "ai_pricing":
        raise NotFound("Unknown settings section.")
    set_setting(db, section, DEFAULTS[section], principal.actor)
    audit.record(db, principal.actor, "settings_reset", f"Settings reset to defaults: {section}")
    db.commit()
    return {"section": section, "value": get_setting(db, section)}


# ---- AI ------------------------------------------------------------------------------------------
@router.get("/settings/ai")
def ai_settings(db: Session = Depends(get_db), _: Principal = Depends(require("read"))) -> dict:
    from app.providers.usage import usage_summary

    s = get_settings()
    p = get_provider()
    return {
        "provider": p.name, "available": p.available, "mode": s.effective_ai_provider,
        "key_configured": bool(s.openai_api_key and s.openai_api_key.get_secret_value()),
        "models": p.models(), "timeout_seconds": s.openai_timeout_seconds, "max_retries": s.openai_max_retries,
        "image_quality": s.openai_image_quality, "image_policy": s.cloud_ai_image_policy,
        "background_mode": s.ai_background_mode, "usage": usage_summary(),
        "pricing": get_setting(db, "ai_pricing"),
    }


@router.post("/settings/ai/test")
def ai_test(db: Session = Depends(get_db), principal: Principal = Depends(require("settings"))) -> dict:
    rep = get_provider().test_connection()
    audit.record(db, principal.actor, "ai_connection_test", f"AI connection test: {'ok' if rep.ok else 'failed'}")
    db.commit()
    return {"ok": rep.ok, "provider": rep.provider, "message": rep.message, "models": rep.models}


# ---- integrations --------------------------------------------------------------------------------
@router.get("/integrations")
def integrations(db: Session = Depends(get_db), _: Principal = Depends(require("read"))) -> dict:
    return {"items": [i.info(db).as_dict() for i in all_integrations()]}


@router.post("/integrations/{name}/test")
def test_integration(name: str, db: Session = Depends(get_db), principal: Principal = Depends(require("settings"))) -> dict:
    integ = get_integration(name)
    if integ is None:
        raise NotFound("Unknown integration.")
    info = integ.run_test(db)
    audit.record(db, principal.actor, "integration_tested", f"{integ.label}: {info.state_label}",
                 detail={"name": name, "state": info.state})
    db.commit()
    return info.as_dict()


class LiveToggle(BaseModel):
    enabled: bool


@router.post("/integrations/{name}/live")
def toggle_live(name: str, body: LiveToggle, db: Session = Depends(get_db),
                principal: Principal = Depends(require("settings"))) -> dict:
    integ = get_integration(name)
    if integ is None:
        raise NotFound("Unknown integration.")
    if body.enabled and integ.info(db).state != CONNECTED:
        raise AppError("Run a successful connection test before switching on live publishing.")
    set_live_enabled(db, name, body.enabled)
    audit.record(db, principal.actor, "live_publishing_toggled",
                 f"Live publishing {'ON' if body.enabled else 'OFF'} for {integ.label}")
    db.commit()
    return integ.info(db).as_dict()


# ---- agent tokens --------------------------------------------------------------------------------
class TokenIn(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    scopes: list[str] = Field(default_factory=lambda: list(DEFAULT_AGENT_SCOPES))


def _token_view(t: ApiToken) -> dict:
    return {"id": t.id, "name": t.name, "prefix": t.token_prefix, "scopes": t.scopes, "created_at": iso(t.created_at),
            "last_used_at": iso(t.last_used_at), "revoked": t.revoked_at is not None, "created_by": t.created_by}


@router.get("/tokens")
def list_tokens(db: Session = Depends(get_db), _: Principal = Depends(require("settings"))) -> dict:
    return {"items": [_token_view(t) for t in db.scalars(select(ApiToken).order_by(ApiToken.created_at.desc()))],
            "scopes": ALL_SCOPES, "default_scopes": DEFAULT_AGENT_SCOPES,
            "admin_users_configured": bool(get_settings().telegram_admin_user_ids)}


@router.post("/tokens", status_code=201)
def create_token(body: TokenIn, db: Session = Depends(get_db), principal: Principal = Depends(require("settings"))) -> dict:
    if principal.kind != "user":
        raise Forbidden("Only the account owner can create agent tokens.")
    bad = [s for s in body.scopes if s not in ALL_SCOPES]
    if bad:
        raise AppError(f"Unknown permission(s): {', '.join(bad)}")
    raw = new_secret_token("at_")
    t = ApiToken(name=body.name.strip(), token_prefix=raw[:9], token_hash=token_digest(raw), scopes=sorted(set(body.scopes)),
                 created_by=principal.actor)
    db.add(t)
    audit.record(db, principal.actor, "token_created", f"Agent token '{t.name}' created ({', '.join(t.scopes)})")
    db.commit()
    return {**_token_view(t), "token": raw, "note": "Copy this token now. It will not be shown again."}


@router.delete("/tokens/{token_id}")
def revoke_token(token_id: int, db: Session = Depends(get_db), principal: Principal = Depends(require("settings"))) -> dict:
    if principal.kind != "user":
        raise Forbidden("Only the account owner can revoke agent tokens.")
    t = db.get(ApiToken, token_id)
    if t is None:
        raise NotFound("Token not found.")
    t.revoked_at = utcnow()
    audit.record(db, principal.actor, "token_revoked", f"Agent token '{t.name}' revoked")
    db.commit()
    return _token_view(t)


# ---- specifications library ----------------------------------------------------------------------
class SpecIn(BaseModel):
    brand: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=200)
    reference: str | None = Field(default=None, max_length=120)
    calibre: str | None = Field(default=None, max_length=120)
    movement_type: str | None = Field(default=None, max_length=80)
    case_size_mm: str | None = Field(default=None, max_length=40)
    case_thickness_mm: str | None = Field(default=None, max_length=40)
    case_material: str | None = Field(default=None, max_length=120)
    dial: str | None = Field(default=None, max_length=200)
    bezel: str | None = Field(default=None, max_length=200)
    crystal: str | None = Field(default=None, max_length=120)
    water_resistance: str | None = Field(default=None, max_length=80)
    power_reserve: str | None = Field(default=None, max_length=80)
    bracelet_strap: str | None = Field(default=None, max_length=200)
    functions: str | None = Field(default=None, max_length=300)
    source_note: str | None = Field(default=None, max_length=2000)


def _spec_view(s: SpecRecord) -> dict:
    d = {c: getattr(s, c) for c in SpecIn.model_fields}
    return {"id": s.id, **d, "status": s.status, "approved_by": s.approved_by, "approved_at": iso(s.approved_at),
            "updated_at": iso(s.updated_at)}


@router.get("/specs")
def list_specs(q: str | None = None, db: Session = Depends(get_db), _: Principal = Depends(require("read"))) -> dict:
    stmt = select(SpecRecord).order_by(SpecRecord.brand, SpecRecord.model)
    if q:
        like = f"%{q}%"
        stmt = stmt.where(or_(SpecRecord.brand.ilike(like), SpecRecord.model.ilike(like), SpecRecord.reference.ilike(like)))
    return {"items": [_spec_view(s) for s in db.scalars(stmt.limit(500))]}


@router.post("/specs", status_code=201)
def create_spec(body: SpecIn, db: Session = Depends(get_db), principal: Principal = Depends(require("intake"))) -> dict:
    s = SpecRecord(**body.model_dump(), status="draft")
    db.add(s)
    db.flush()
    audit.record(db, principal.actor, "spec_created", f"Spec record {s.brand} {s.model} {s.reference or ''} added (draft)",
                 entity_type="spec", entity_id=s.id)
    db.commit()
    return _spec_view(s)


@router.put("/specs/{spec_id}")
def update_spec(spec_id: str, body: SpecIn, db: Session = Depends(get_db), principal: Principal = Depends(require("intake"))) -> dict:
    s = db.get(SpecRecord, spec_id)
    if s is None:
        raise NotFound("Spec record not found.")
    for k, v in body.model_dump().items():
        setattr(s, k, v)
    s.status = "draft"
    s.approved_at = None
    s.approved_by = None
    audit.record(db, principal.actor, "spec_updated", f"Spec record {s.brand} {s.model} edited (needs re-approval)",
                 entity_type="spec", entity_id=s.id)
    _invalidate_watches_for_spec(db, s, principal.actor)
    db.commit()
    return _spec_view(s)


def _invalidate_watches_for_spec(db: Session, s: SpecRecord, actor: str) -> None:
    from app.db.models import Watch
    from app.review.approvals import invalidate_stale

    for w in db.scalars(select(Watch).where(Watch.archived_at.is_(None))):
        invalidate_stale(db, w, f"Spec record {s.brand} {s.model} changed", actor)


@router.post("/specs/{spec_id}/approve")
def approve_spec(spec_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require("approve"))) -> dict:
    s = db.get(SpecRecord, spec_id)
    if s is None:
        raise NotFound("Spec record not found.")
    s.status = "approved"
    s.approved_by = principal.actor
    s.approved_at = utcnow()
    audit.record(db, principal.actor, "spec_approved", f"Spec record {s.brand} {s.model} {s.reference or ''} approved",
                 entity_type="spec", entity_id=s.id)
    _invalidate_watches_for_spec(db, s, principal.actor)
    db.commit()
    return _spec_view(s)


@router.delete("/specs/{spec_id}")
def delete_spec(spec_id: str, db: Session = Depends(get_db), principal: Principal = Depends(require("intake"))) -> dict:
    from app.db.models import Watch

    s = db.get(SpecRecord, spec_id)
    if s is None:
        raise NotFound("Spec record not found.")
    linked = db.scalar(select(Watch.id).where(Watch.spec_id == s.id).limit(1))
    if linked:
        raise AppError("This spec record is linked to a watch. Unlink it first.")
    audit.record(db, principal.actor, "spec_deleted", f"Spec record {s.brand} {s.model} deleted", entity_type="spec",
                 entity_id=s.id)
    db.delete(s)
    _invalidate_watches_for_spec(db, s, principal.actor)
    db.commit()
    return {"ok": True}
