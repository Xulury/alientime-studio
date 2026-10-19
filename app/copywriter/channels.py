"""Channel definitions: route, sections, limits (with their documentation source), images.

Limits marked `verified=False` are conservative internal defaults because the platform does not
publish a limit; they are shown as such in the interface.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Limit:
    max_chars: int
    source: str
    verified: bool


@dataclass(frozen=True)
class ChannelDef:
    key: str
    name: str
    route: str  # api | feed | manual
    audience: str
    has_title: bool
    text_sections: tuple[str, ...]
    fixed_blocks: tuple[str, ...]
    limits: dict[str, Limit]
    max_images: int
    currency: str  # SGD | USD | SGD+USD | none
    hashtags_max: int = 0
    title_prefix: str = ""
    emoji_ok: bool = False
    manual_steps: tuple[str, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)


SECTION_LABELS = {
    "title": "Title", "body": "Description", "specs": "Specifications", "condition": "Condition",
    "accessories": "Box, papers & accessories", "availability": "Availability", "price": "Price",
    "cta": "Call to action", "terms": "House terms", "disclaimer": "Disclaimer", "licence": "Licence",
    "contact": "Contact", "hashtags": "Hashtags", "auction": "Auction details",
}
# who may write each section: ai (model or template), facts (code from the fact sheet), fixed (settings, verbatim)
SECTION_KIND = {
    "title": "ai", "body": "ai", "hashtags": "ai",
    "specs": "facts", "condition": "facts", "accessories": "facts", "availability": "facts", "price": "facts",
    "auction": "facts",
    "cta": "fixed", "terms": "fixed", "disclaimer": "fixed", "licence": "fixed", "contact": "fixed",
}

_IG = "Meta Instagram Graph API reference, IG User Media (caption ≤ 2,200 characters, ≤ 30 hashtags)"
_EBAY = "eBay Sell Inventory API, Product type (title ≤ 80, description ≤ 4,000)"
_SHOP = "Shopify Admin API product title (≤ 255 characters)"
_REDDIT = "Reddit post limits (title ≤ 300, text post ≤ 40,000 characters)"
_WA = "WhatsApp Cloud API text message body (≤ 4,096 characters)"
_UNVERIFIED = "No published limit found; conservative internal limit"

CHANNELS: dict[str, ChannelDef] = {
    "shopify": ChannelDef(
        "shopify", "Shopify (website)", "api", "Website shoppers who read the full product page.", True,
        ("body", "specs", "condition", "accessories", "availability", "terms", "disclaimer", "licence"),
        ("terms", "disclaimer", "licence"),
        {"title": Limit(255, _SHOP, True), "text": Limit(20000, _UNVERIFIED, False)},
        max_images=20, currency="SGD",
        notes=("Price is set on the product, not in the description.",),
    ),
    "instagram": ChannelDef(
        "instagram", "Instagram", "api", "Followers scrolling a feed; first line must carry the piece.", True,
        ("title", "body", "specs", "condition", "accessories", "price", "cta", "hashtags"),
        ("cta",),
        {"text": Limit(2200, _IG, True)}, max_images=10, currency="SGD", hashtags_max=30,
        notes=("Carousel of up to 10 JPEG images from a public URL (Cloudflare R2).",),
    ),
    "facebook_page": ChannelDef(
        "facebook_page", "Facebook Page", "api", "Page followers; a short post with key facts.", True,
        ("title", "body", "specs", "condition", "accessories", "price", "cta", "disclaimer", "hashtags"),
        ("cta", "disclaimer"),
        {"text": Limit(5000, _UNVERIFIED, False)}, max_images=10, currency="SGD", hashtags_max=5,
    ),
    "chrono24": ChannelDef(
        "chrono24", "Chrono24", "feed", "International collectors comparing listings by reference.", True,
        ("body", "specs", "condition", "accessories", "availability", "terms", "disclaimer"),
        ("terms", "disclaimer"),
        {"title": Limit(100, _UNVERIFIED, False), "text": Limit(5000, _UNVERIFIED, False)},
        max_images=20, currency="SGD+USD",
        notes=("Sent through the dealer product feed; confirm columns with your Chrono24 integration manager.",),
    ),
    "ebay": ChannelDef(
        "ebay", "eBay", "api", "International buyers; precise, searchable title.", True,
        ("body", "specs", "condition", "accessories", "terms", "disclaimer"),
        ("terms", "disclaimer"),
        {"title": Limit(80, _EBAY, True), "text": Limit(4000, _EBAY, True)}, max_images=24, currency="USD",
        notes=("Listings created through the API can then only be edited through the API.",),
    ),
    "facebook_marketplace": ChannelDef(
        "facebook_marketplace", "Facebook Marketplace", "manual", "Local buyers browsing Marketplace.", True,
        ("body", "specs", "condition", "accessories", "availability", "cta"),
        ("cta",),
        {"title": Limit(100, _UNVERIFIED, False), "text": Limit(5000, _UNVERIFIED, False)},
        max_images=10, currency="SGD",
        manual_steps=("Open Facebook → Marketplace → Create new listing → Item for sale.",
                      "Upload the images in order (first image is the cover).",
                      "Paste the title, set the price, choose category 'Jewellery & watches'.",
                      "Paste the description and publish.",
                      "Copy the listing link back into the studio."),
    ),
    "facebook_groups": ChannelDef(
        "facebook_groups", "FB dealer groups", "manual", "Dealers and collectors in trade groups; concise.", True,
        ("title", "body", "specs", "condition", "accessories", "price", "availability", "cta"),
        ("cta",),
        {"text": Limit(5000, _UNVERIFIED, False)}, max_images=10, currency="SGD",
        manual_steps=("Post in each dealer group from your own account (Meta removed API posting to groups in April 2024).",
                      "Follow each group's posting format and price rules.",
                      "Copy each post link back into the studio."),
    ),
    "carousell": ChannelDef(
        "carousell", "Carousell", "manual", "Local Carousell buyers.", True,
        ("body", "specs", "condition", "accessories", "availability", "cta", "terms"),
        ("cta", "terms"),
        {"title": Limit(80, _UNVERIFIED, False), "text": Limit(4000, _UNVERIFIED, False)},
        max_images=10, currency="SGD",
        manual_steps=("Open Carousell → Sell → Luxury → Watches.", "Upload the square images in order.",
                      "Paste title and description, set the price, choose condition and deal method.",
                      "Publish and copy the listing link back into the studio."),
    ),
    "whatsapp_groups": ChannelDef(
        "whatsapp_groups", "WhatsApp dealer groups", "manual", "Dealer broadcast; short and scannable.", True,
        ("title", "specs", "condition", "accessories", "price", "availability", "cta"),
        ("cta",),
        {"text": Limit(4096, _WA, True)}, max_images=10, currency="SGD",
        manual_steps=("Forward the images first, then paste the message text.",
                      "Send to each dealer group from your own WhatsApp (group posting by API is not available)."),
    ),
    "reddit_watchexchange": ChannelDef(
        "reddit_watchexchange", "Reddit r/WatchExchange", "manual", "Enthusiasts; full disclosure expected.", True,
        ("body", "specs", "condition", "accessories", "price", "availability", "terms"),
        ("terms",),
        {"title": Limit(300, _REDDIT, True), "text": Limit(40000, _REDDIT, True)},
        max_images=20, currency="SGD+USD", title_prefix="[WTS] ",
        manual_steps=("Take a timestamp photo (handwritten username + date next to the watch) as the subreddit requires.",
                      "Upload all images plus the timestamp to an album (e.g. Imgur) and add the link to the post.",
                      "Post with the [WTS] title and include the price, as the subreddit rules require.",
                      "Copy the post link back into the studio."),
    ),
    "moda_auction": ChannelDef(
        "moda_auction", "MODA @uction", "manual", "Auction group members; starting bid up front.", True,
        ("title", "auction", "specs", "condition", "accessories", "availability", "terms"),
        ("terms",),
        {"text": Limit(5000, _UNVERIFIED, False)}, max_images=10, currency="SGD",
        manual_steps=("Post in the MODA @uction Facebook group from your own account.",
                      "Set the bid increment and closing time according to the group's current rules.",
                      "Copy the post link back into the studio."),
    ),
}

FIXED_BLOCK_LABELS = {"terms": "House terms", "disclaimer": "Disclaimer", "licence": "Licence", "contact": "Contact",
                      "cta": "Call to action"}


def channel(key: str) -> ChannelDef:
    if key not in CHANNELS:
        raise KeyError(key)
    return CHANNELS[key]


def channel_info(key: str) -> dict:
    c = CHANNELS[key]
    return {
        "key": c.key, "name": c.name, "route": c.route, "audience": c.audience, "has_title": c.has_title,
        "sections": (["title"] if c.has_title and "title" not in c.text_sections else []) + list(c.text_sections),
        "fixed_blocks": list(c.fixed_blocks), "max_images": c.max_images, "currency": c.currency,
        "hashtags_max": c.hashtags_max, "manual_steps": list(c.manual_steps), "notes": list(c.notes),
        "limits": {k: {"max_chars": v.max_chars, "source": v.source, "verified": v.verified} for k, v in c.limits.items()},
    }
