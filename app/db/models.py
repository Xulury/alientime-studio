"""SQLAlchemy models.

Portable column types only (String, Text, Integer, Numeric, Boolean, DateTime, JSON) so the same
schema runs on SQLite for local development and PostgreSQL in production.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, utcnow


def new_id() -> str:
    return uuid.uuid4().hex


# ------------------------------------------------------------------------------------------------
# Identity
# ------------------------------------------------------------------------------------------------
class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), default="")
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(20), default="owner")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime)
    password_changed_at: Mapped[datetime | None] = mapped_column(DateTime)
    failed_login_count: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime)


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256 of the cookie token
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    ip: Mapped[str | None] = mapped_column(String(64))
    user_agent: Mapped[str | None] = mapped_column(String(255))

    user: Mapped[User] = relationship()


class ApiToken(Base):
    """Scoped tokens for agents (Hermes). Only the SHA-256 of the token is stored."""

    __tablename__ = "api_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    token_prefix: Mapped[str] = mapped_column(String(16), nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(80))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime)


# ------------------------------------------------------------------------------------------------
# Inventory
# ------------------------------------------------------------------------------------------------
class SpecRecord(Base):
    """Trusted specification records maintained by the business (not scraped from the web)."""

    __tablename__ = "spec_records"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    brand: Mapped[str] = mapped_column(String(120), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120), index=True)
    calibre: Mapped[str | None] = mapped_column(String(120))
    movement_type: Mapped[str | None] = mapped_column(String(80))
    case_size_mm: Mapped[str | None] = mapped_column(String(40))
    case_thickness_mm: Mapped[str | None] = mapped_column(String(40))
    case_material: Mapped[str | None] = mapped_column(String(120))
    dial: Mapped[str | None] = mapped_column(String(200))
    bezel: Mapped[str | None] = mapped_column(String(200))
    crystal: Mapped[str | None] = mapped_column(String(120))
    water_resistance: Mapped[str | None] = mapped_column(String(80))
    power_reserve: Mapped[str | None] = mapped_column(String(80))
    bracelet_strap: Mapped[str | None] = mapped_column(String(200))
    functions: Mapped[str | None] = mapped_column(String(300))
    extra: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    source_note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="draft")  # draft | approved
    approved_by: Mapped[str | None] = mapped_column(String(80))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Watch(Base):
    __tablename__ = "watches"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    sku: Mapped[str] = mapped_column(String(60), unique=True, nullable=False)
    brand: Mapped[str] = mapped_column(String(120), nullable=False)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    reference: Mapped[str | None] = mapped_column(String(120))
    year: Mapped[str | None] = mapped_column(String(20))
    condition: Mapped[str | None] = mapped_column(String(40))
    condition_notes: Mapped[str | None] = mapped_column(Text)

    price_sgd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    price_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    fx_rate_sgd_usd: Mapped[Decimal | None] = mapped_column(Numeric(12, 6))
    fx_source: Mapped[str | None] = mapped_column(String(40))
    fx_updated_at: Mapped[datetime | None] = mapped_column(DateTime)

    box_papers: Mapped[str] = mapped_column(String(30), default="unknown")
    box_papers_notes: Mapped[str | None] = mapped_column(Text)
    custody: Mapped[str] = mapped_column(String(30), default="unknown")

    is_consignment: Mapped[bool] = mapped_column(Boolean, default=False)
    consignor_name: Mapped[str | None] = mapped_column(String(200))
    consignor_contact: Mapped[str | None] = mapped_column(String(200))
    consignment_ref: Mapped[str | None] = mapped_column(String(120))
    consignment_terms: Mapped[str | None] = mapped_column(Text)
    consignment_payout_sgd: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    consignment_start: Mapped[date | None] = mapped_column(Date)
    consignment_end: Mapped[date | None] = mapped_column(Date)
    consignor_signoff: Mapped[str] = mapped_column(String(20), default="not_required")

    description: Mapped[str | None] = mapped_column(Text)
    internal_notes: Mapped[str | None] = mapped_column(Text)
    extra_facts: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    spec_id: Mapped[str | None] = mapped_column(ForeignKey("spec_records.id", ondelete="SET NULL"))

    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    status_changed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    gallery: Mapped[list[str]] = mapped_column(JSON, default=list)
    channels: Mapped[list[str] | None] = mapped_column(JSON)  # None = every channel enabled in Settings
    hero_asset_id: Mapped[str | None] = mapped_column(String(32))
    content_version: Mapped[int] = mapped_column(Integer, default=1)
    studio_defaults: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_by: Mapped[str | None] = mapped_column(String(120))

    spec: Mapped[SpecRecord | None] = relationship()
    assets: Mapped[list["Asset"]] = relationship(back_populates="watch", order_by="Asset.sort_order")


class Asset(Base):
    """One photograph. The original bytes are stored untouched and read-only."""

    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    watch_id: Mapped[str] = mapped_column(ForeignKey("watches.id", ondelete="CASCADE"), index=True)
    source: Mapped[str] = mapped_column(String(30), default="upload")
    original_filename: Mapped[str] = mapped_column(String(255), default="photo")
    original_path: Mapped[str] = mapped_column(String(500), nullable=False)
    original_sha256: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    original_bytes: Mapped[int] = mapped_column(Integer, default=0)
    original_format: Mapped[str] = mapped_column(String(20), default="JPEG")
    width: Mapped[int] = mapped_column(Integer, default=0)
    height: Mapped[int] = mapped_column(Integer, default=0)
    exif_summary: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    phash: Mapped[str | None] = mapped_column(String(32))
    duplicate_of: Mapped[str | None] = mapped_column(String(32))
    working_path: Mapped[str | None] = mapped_column(String(500))
    working_width: Mapped[int] = mapped_column(Integer, default=0)
    working_height: Mapped[int] = mapped_column(Integer, default=0)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    uploaded_by: Mapped[str | None] = mapped_column(String(120))
    removed_at: Mapped[datetime | None] = mapped_column(DateTime)

    # pipeline
    pipeline_status: Mapped[str] = mapped_column(String(30), default="uploaded")
    pipeline_error: Mapped[str | None] = mapped_column(Text)
    source_profile: Mapped[str | None] = mapped_column(String(20))  # edited | raw | phone
    source_profile_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)

    # stage 1: inspection
    inspection: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    quality_score: Mapped[float | None] = mapped_column(Float)
    selected: Mapped[bool | None] = mapped_column(Boolean)
    selection_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    selection_override: Mapped[bool | None] = mapped_column(Boolean)
    photo_type: Mapped[str | None] = mapped_column(String(30))
    photo_type_source: Mapped[str | None] = mapped_column(String(20))
    photo_type_confidence: Mapped[float | None] = mapped_column(Float)
    ai_tags: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # stage 2: privacy
    safety_status: Mapped[str] = mapped_column(String(30), default="pending")
    safety_engine: Mapped[str | None] = mapped_column(String(60))
    safety_findings: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    safety_recheck: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    safety_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    safety_reviewed_by: Mapped[str | None] = mapped_column(String(120))
    redacted_path: Mapped[str | None] = mapped_column(String(500))
    redaction_version: Mapped[int] = mapped_column(Integer, default=0)

    # stage 3: segmentation
    mask_path: Mapped[str | None] = mapped_column(String(500))
    mask_version: Mapped[int] = mapped_column(Integer, default=0)
    mask_source: Mapped[str | None] = mapped_column(String(60))
    segmentation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    # stage 4/5: studio + review
    studio_settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    current_render_id: Mapped[str | None] = mapped_column(String(32))
    render_stale: Mapped[bool] = mapped_column(Boolean, default=False)
    review_status: Mapped[str] = mapped_column(String(30), default="pending")
    review_note: Mapped[str | None] = mapped_column(Text)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)

    watch: Mapped[Watch] = relationship(back_populates="assets")
    regions: Mapped[list["RedactionRegion"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan", order_by="RedactionRegion.created_at"
    )


class RedactionRegion(Base):
    """A redaction rectangle in normalised coordinates (0..1) of the working image.

    The recognised text itself is never stored: only a category such as "serial-like number".
    """

    __tablename__ = "redaction_regions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    x: Mapped[float] = mapped_column(Float, nullable=False)
    y: Mapped[float] = mapped_column(Float, nullable=False)
    w: Mapped[float] = mapped_column(Float, nullable=False)
    h: Mapped[float] = mapped_column(Float, nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="manual")  # ocr | manual
    category: Mapped[str | None] = mapped_column(String(60))
    confidence: Mapped[float | None] = mapped_column(Float)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(120))

    asset: Mapped[Asset] = relationship(back_populates="regions")


class AssetRender(Base):
    """One studio render of a frame (master + platform variants) with its fidelity result."""

    __tablename__ = "asset_renders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    background_source: Mapped[str | None] = mapped_column(String(80))
    master_path: Mapped[str | None] = mapped_column(String(500))
    master_sha256: Mapped[str | None] = mapped_column(String(64))
    variants: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fidelity: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fidelity_passed: Mapped[bool] = mapped_column(Boolean, default=False)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list)
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="ok")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


# ------------------------------------------------------------------------------------------------
# Listing intelligence + copy
# ------------------------------------------------------------------------------------------------
class AIObservation(Base):
    __tablename__ = "ai_observations"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    watch_id: Mapped[str] = mapped_column(ForeignKey("watches.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(40))  # image_tagging | listing_intel
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80))
    asset_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class FactSuggestion(Base):
    """A value proposed by AI, the specs table or the Sheet. Never applied without confirmation."""

    __tablename__ = "fact_suggestions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    watch_id: Mapped[str] = mapped_column(ForeignKey("watches.id", ondelete="CASCADE"), index=True)
    field: Mapped[str] = mapped_column(String(60))
    value: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(40))
    evidence: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | accepted | dismissed
    observation_id: Mapped[str | None] = mapped_column(String(32))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_by: Mapped[str | None] = mapped_column(String(120))


class ChannelCopy(Base):
    __tablename__ = "channel_copies"
    __table_args__ = (UniqueConstraint("watch_id", "channel", name="uq_channel_copy"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    watch_id: Mapped[str] = mapped_column(ForeignKey("watches.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(40), nullable=False)
    sections: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rendered_text: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    content_hash: Mapped[str] = mapped_column(String(64), default="")
    generator: Mapped[str] = mapped_column(String(80), default="template")
    style: Mapped[str] = mapped_column(String(40), default="house")
    validation: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fixed_blocks_hash: Mapped[str | None] = mapped_column(String(64))
    facts_hash: Mapped[str | None] = mapped_column(String(64))
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(120))


class CopyRevision(Base):
    __tablename__ = "copy_revisions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    watch_id: Mapped[str] = mapped_column(ForeignKey("watches.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(40))
    version: Mapped[int] = mapped_column(Integer)
    sections: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rendered_text: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64))
    generator: Mapped[str] = mapped_column(String(80))
    reason: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_by: Mapped[str | None] = mapped_column(String(120))


# ------------------------------------------------------------------------------------------------
# Approvals + publishing
# ------------------------------------------------------------------------------------------------
class Approval(Base):
    __tablename__ = "approvals"
    __table_args__ = (Index("ix_approval_target", "watch_id", "scope", "target"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    watch_id: Mapped[str] = mapped_column(ForeignKey("watches.id", ondelete="CASCADE"))
    scope: Mapped[str] = mapped_column(String(20))  # image | channel | package
    target: Mapped[str] = mapped_column(String(60))  # asset id | channel key | "package"
    content_hash: Mapped[str] = mapped_column(String(64))
    content_ref: Mapped[str | None] = mapped_column(String(120))
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    approved_by: Mapped[str] = mapped_column(String(160))
    approved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    note: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="active")  # active | invalidated | revoked
    invalidated_at: Mapped[datetime | None] = mapped_column(DateTime)
    invalidated_reason: Mapped[str | None] = mapped_column(Text)


class ChannelListing(Base):
    __tablename__ = "channel_listings"
    __table_args__ = (UniqueConstraint("watch_id", "channel", name="uq_channel_listing"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    watch_id: Mapped[str] = mapped_column(ForeignKey("watches.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30), default="not_started")
    mode: Mapped[str] = mapped_column(String(20), default="manual")  # api | feed | manual | simulation
    external_id: Mapped[str | None] = mapped_column(String(200))
    external_url: Mapped[str | None] = mapped_column(String(500))
    published_hash: Mapped[str | None] = mapped_column(String(64))
    published_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_action: Mapped[str | None] = mapped_column(String(40))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ManualTask(Base):
    __tablename__ = "manual_tasks"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    watch_id: Mapped[str] = mapped_column(ForeignKey("watches.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(30))  # post | update | mark_reserved | mark_sold | remove
    title: Mapped[str] = mapped_column(String(300))
    instructions: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | done | dismissed
    live_url: Mapped[str | None] = mapped_column(String(500))
    content_hash: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_by: Mapped[str | None] = mapped_column(String(120))


# ------------------------------------------------------------------------------------------------
# Jobs, audit, usage, settings
# ------------------------------------------------------------------------------------------------
class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_status_run_after", "status", "run_after"),)

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    type: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    watch_id: Mapped[str | None] = mapped_column(String(32), index=True)
    asset_id: Mapped[str | None] = mapped_column(String(32))
    channel: Mapped[str | None] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    progress: Mapped[float] = mapped_column(Float, default=0.0)
    progress_message: Mapped[str | None] = mapped_column(String(300))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), unique=True)
    run_after: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    locked_by: Mapped[str | None] = mapped_column(String(80))
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[str | None] = mapped_column(String(160))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)


class AuditEvent(Base):
    __tablename__ = "audit_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    actor: Mapped[str] = mapped_column(String(160))
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str | None] = mapped_column(String(40))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    watch_id: Mapped[str | None] = mapped_column(String(32), index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    ip: Mapped[str | None] = mapped_column(String(64))


class AIUsage(Base):
    __tablename__ = "ai_usage"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, index=True)
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(80))
    operation: Mapped[str] = mapped_column(String(60))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    image_input_count: Mapped[int] = mapped_column(Integer, default=0)
    image_output_count: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(30), default="ok")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    watch_id: Mapped[str | None] = mapped_column(String(32))
    job_id: Mapped[str | None] = mapped_column(String(32))
    error: Mapped[str | None] = mapped_column(Text)


class AppSetting(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[Any] = mapped_column(JSON)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)
    updated_by: Mapped[str | None] = mapped_column(String(120))


class IntegrationStatus(Base):
    __tablename__ = "integration_status"

    name: Mapped[str] = mapped_column(String(40), primary_key=True)
    state: Mapped[str] = mapped_column(String(30), default="not_configured")
    checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    message: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    live_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
