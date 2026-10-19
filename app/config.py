"""Application settings.

Every value is read from environment variables (or a local `.env` file). Secrets are never
hard-coded and never returned to the browser. `public_view()` gives the safe subset the UI may show.
"""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        env_ignore_empty=True,
    )

    # ---- application -------------------------------------------------------------------------
    studio_env: Literal["development", "production", "test"] = "development"
    studio_data_dir: Path = BASE_DIR / "data"
    database_url: str | None = None
    supabase_url: str | None = None
    supabase_key: SecretStr | None = None
    supabase_storage_bucket: str = "watch-photos"
    studio_base_url: str = "http://127.0.0.1:8000"
    studio_cookie_secure: bool = False
    studio_session_hours: int = 12
    studio_allow_remote_setup: bool = False
    studio_setup_token: SecretStr | None = None
    studio_login_max_failures: int = 8
    studio_login_lock_minutes: int = 15
    studio_log_level: str = "INFO"
    studio_log_json: bool = True

    # ---- uploads -----------------------------------------------------------------------------
    max_upload_mb: int = 30
    max_files_per_upload: int = 40
    max_image_pixels: int = 80_000_000
    working_max_edge: int = 4000

    # ---- background jobs ---------------------------------------------------------------------
    worker_mode: Literal["thread", "external", "off"] = "thread"
    worker_concurrency: int = 1
    job_max_attempts: int = 3
    job_stale_minutes: int = 15
    auto_process_uploads: bool = True

    # ---- local image models ------------------------------------------------------------------
    ocr_backend: Literal["auto", "rapidocr", "none"] = "auto"
    ocr_max_edge: int = 2560
    segmentation_backend: Literal["auto", "rembg", "grabcut"] = "auto"
    rembg_model: str = "isnet-general-use"
    rembg_model_dir: Path | None = None

    # ---- AI provider -------------------------------------------------------------------------
    ai_provider: Literal["auto", "openai", "mock", "disabled"] = "auto"
    openai_api_key: SecretStr | None = None
    openai_base_url: str | None = None
    openai_organization: str | None = None
    openai_project: str | None = None
    # Model identifiers verified against the OpenAI models + changelog pages on 2026-10-18.
    openai_model_vision: str = "gpt-6.1-sol"
    openai_model_intel: str = "gpt-6.1-sol"
    openai_model_text: str = "gpt-6.1-sol"
    openai_model_image: str = "gpt-image-2.5-sunburst"
    openai_image_quality: Literal["low", "medium", "high", "xhigh", "max", "auto"] = "high"
    openai_timeout_seconds: float = 120.0
    openai_max_retries: int = 3
    ai_daily_budget_usd: float = 10.0
    ai_monthly_budget_usd: float = 100.0
    # reviewed_only: a photo goes to cloud AI only after a person marks it checked.
    # safe_auto: photos whose OCR scan found nothing may go without a manual check.
    # never: no photo ever leaves the machine.
    cloud_ai_image_policy: Literal["reviewed_only", "safe_auto", "never"] = "reviewed_only"
    ai_background_mode: Literal["plate", "context_edit"] = "plate"

    # ---- publishing --------------------------------------------------------------------------
    enable_simulated_publishing: bool = True
    mock_publish_fail_channels: str = ""

    # ---- Hermes / agent ----------------------------------------------------------------------
    telegram_bot_token: SecretStr | None = None
    telegram_allowed_users: str = ""
    telegram_admin_users: str = ""
    telegram_notify_chat_id: str | None = None

    # ---- Google ------------------------------------------------------------------------------
    google_application_credentials: Path | None = None
    drive_root_folder_id: str | None = None
    facts_sheet_id: str | None = None
    facts_sheet_range: str = "A1:Z1000"

    # ---- Cloudflare --------------------------------------------------------------------------
    cloudflare_api_token: SecretStr | None = None
    cloudflare_account_id: str | None = None
    cf_pages_project: str | None = None
    r2_access_key_id: str | None = None
    r2_secret_access_key: SecretStr | None = None
    r2_bucket: str | None = None
    r2_public_base_url: str | None = None
    r2_endpoint_url: str | None = None

    # ---- Shopify -----------------------------------------------------------------------------
    shopify_shop: str | None = None
    shopify_client_id: str | None = None
    shopify_client_secret: SecretStr | None = None
    shopify_api_version: str = "2026-07"

    # ---- Meta --------------------------------------------------------------------------------
    meta_app_id: str | None = None
    meta_app_secret: SecretStr | None = None
    meta_system_user_token: SecretStr | None = None
    meta_graph_version: str = "v24.0"
    ig_user_id_alientime_sg: str | None = None
    ig_user_id_official: str | None = None
    fb_page_id: str | None = None

    # ---- Chrono24 ----------------------------------------------------------------------------
    chrono24_feed_url: str | None = None

    # ---- eBay --------------------------------------------------------------------------------
    ebay_client_id: str | None = None
    ebay_client_secret: SecretStr | None = None
    ebay_ru_name: str | None = None
    ebay_refresh_token: SecretStr | None = None
    ebay_merchant_location_key: str | None = None
    ebay_fulfillment_policy_id: str | None = None
    ebay_payment_policy_id: str | None = None
    ebay_return_policy_id: str | None = None
    ebay_marketplace_id: str = "EBAY_US"
    ebay_category_id: str = "31387"
    ebay_environment: Literal["production", "sandbox"] = "production"

    # ---- WhatsApp Cloud API ------------------------------------------------------------------
    whatsapp_access_token: SecretStr | None = None
    whatsapp_phone_number_id: str | None = None
    whatsapp_business_account_id: str | None = None
    whatsapp_app_secret: SecretStr | None = None
    whatsapp_verify_token: SecretStr | None = None

    @field_validator("studio_data_dir", mode="before")
    @classmethod
    def _resolve_data_dir(cls, v):
        if v:
            p = Path(v)
            if not p.is_absolute():
                p = BASE_DIR / p
            return p
        if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
            return Path("/tmp/data")
        return BASE_DIR / "data"

    @field_validator("worker_mode", mode="before")
    @classmethod
    def _resolve_worker_mode(cls, v):
        if v:
            return v
        if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
            return "off"
        return "thread"

    # ---- derived -----------------------------------------------------------------------------
    @property
    def db_url(self) -> str:
        if self.database_url:
            url = self.database_url
            if url.startswith("postgres://"):
                url = "postgresql+psycopg://" + url.removeprefix("postgres://")
            elif url.startswith("postgresql://"):
                url = "postgresql+psycopg://" + url.removeprefix("postgresql://")
            return url
        return f"sqlite:///{(self.studio_data_dir / 'studio.db').as_posix()}"

    @property
    def media_dir(self) -> Path:
        return self.studio_data_dir / "media"

    @property
    def exports_dir(self) -> Path:
        return self.studio_data_dir / "exports"

    @property
    def feeds_dir(self) -> Path:
        return self.studio_data_dir / "feeds"

    @property
    def inbox_dir(self) -> Path:
        return self.studio_data_dir / "inbox"

    @property
    def is_test(self) -> bool:
        return self.studio_env == "test"

    @property
    def effective_ai_provider(self) -> str:
        if self.ai_provider == "auto":
            return "openai" if self.openai_api_key and self.openai_api_key.get_secret_value() else "disabled"
        return self.ai_provider

    @staticmethod
    def _split(v: str) -> list[str]:
        return [x.strip() for x in (v or "").split(",") if x.strip()]

    @property
    def telegram_allowed_user_ids(self) -> list[str]:
        return self._split(self.telegram_allowed_users)

    @property
    def telegram_admin_user_ids(self) -> list[str]:
        return self._split(self.telegram_admin_users)

    @property
    def mock_fail_channels(self) -> set[str]:
        return set(self._split(self.mock_publish_fail_channels))

    def ensure_dirs(self) -> None:
        for d in (self.studio_data_dir, self.media_dir, self.exports_dir, self.feeds_dir, self.inbox_dir):
            try:
                d.mkdir(parents=True, exist_ok=True)
            except OSError:
                pass


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.ensure_dirs()
    return s


def reset_settings_cache() -> None:
    get_settings.cache_clear()
