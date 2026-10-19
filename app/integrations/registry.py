"""All integrations, for the Settings → Integrations and Publishing → Platforms pages."""
from __future__ import annotations

from app.integrations.base import Integration
from app.integrations.cloudflare_r2 import CloudflareR2
from app.integrations.google import GoogleDrive, GoogleSheets
from app.integrations.messaging import Telegram, WhatsAppCloud


def all_integrations() -> list[Integration]:
    from app.publish.registry import LIVE_ADAPTERS

    return [cls() for cls in LIVE_ADAPTERS.values()] + [CloudflareR2(), GoogleDrive(), GoogleSheets(), Telegram(),
                                                         WhatsAppCloud()]


def get_integration(name: str) -> Integration | None:
    for i in all_integrations():
        if i.name == name:
            return i
    return None
