"""Which adapter handles each channel, and in which mode (live, simulation, manual)."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.config import get_settings
from app.copywriter.channels import CHANNELS
from app.integrations.base import CONNECTED
from app.integrations.cloudflare_r2 import CloudflareR2
from app.publish.base import ChannelAdapter
from app.publish.chrono24_feed import Chrono24FeedAdapter
from app.publish.ebay import EbayAdapter
from app.publish.meta import FacebookPageAdapter, InstagramAdapter
from app.publish.shopify import ShopifyAdapter
from app.publish.simulation import SimulationAdapter

LIVE_ADAPTERS: dict[str, type[ChannelAdapter]] = {
    "shopify": ShopifyAdapter,
    "instagram": InstagramAdapter,
    "facebook_page": FacebookPageAdapter,
    "chrono24": Chrono24FeedAdapter,
    "ebay": EbayAdapter,
}
NEEDS_PUBLIC_URLS = {"instagram", "ebay", "chrono24"}


@dataclass
class ChannelMode:
    channel: str
    route: str          # api | feed | manual
    mode: str           # live | simulation | manual | unavailable
    state: str          # integration state
    message: str
    live_enabled: bool

    def as_dict(self) -> dict:
        return self.__dict__.copy()


def live_adapter(channel: str) -> ChannelAdapter | None:
    cls = LIVE_ADAPTERS.get(channel)
    return cls() if cls else None


def channel_mode(db: Session, channel: str) -> ChannelMode:
    ch = CHANNELS[channel]
    if ch.route == "manual":
        return ChannelMode(channel, "manual", "manual", "unsupported",
                           "No official posting API: a draft pack is prepared and you post it yourself.", False)
    adapter = live_adapter(channel)
    info = adapter.info(db)
    needs_r2 = channel in NEEDS_PUBLIC_URLS and not CloudflareR2().is_configured()
    if info.state == CONNECTED and info.live_enabled and not needs_r2:
        return ChannelMode(channel, ch.route, "live", info.state, "Connected; live publishing is on.", True)
    reason = info.message or info.state_label
    if info.state == CONNECTED and not info.live_enabled:
        reason = "Connected, but live publishing is switched off in Publishing → Platforms."
    if needs_r2:
        reason = "Needs Cloudflare R2 for public image URLs. " + (reason or "")
    if get_settings().enable_simulated_publishing:
        return ChannelMode(channel, ch.route, "simulation", info.state, f"Simulation only. {reason}".strip(), False)
    return ChannelMode(channel, ch.route, "unavailable", info.state, reason, False)


def adapter_for(db: Session, channel: str, mode: str) -> ChannelAdapter:
    if mode == "simulation":
        return SimulationAdapter(channel, CHANNELS[channel].name, CHANNELS[channel].route)
    if mode == "live":
        m = channel_mode(db, channel)
        if m.mode != "live":
            from app.integrations.base import IntegrationError

            raise IntegrationError(f"{CHANNELS[channel].name} is not connected for live publishing: {m.message}")
        adapter = live_adapter(channel)
        assert adapter is not None
        return adapter
    raise ValueError(f"No adapter for mode {mode}")
