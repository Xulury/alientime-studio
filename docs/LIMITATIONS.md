# Known limitations and blocked functionality

What is built and tested, but not yet proven against the real world — and what is waiting on you.
Status as of the delivery in October 2026.

## 1. Waiting on credentials (code complete, tested with simulated platform responses)

None of these have been run against the live service, because no credentials were available. Each is covered by
tests that replay the platform's documented requests and responses. Until a connection test passes and you switch live
publishing on, the channel runs in labelled simulation and nothing is posted.

| Integration | What you need to do | First real-world check |
| --- | --- | --- |
| **OpenAI** | Put `OPENAI_API_KEY` in `.env`; complete API Organization Verification for the image model | Settings → AI → Test; tag one checked photo; generate AI copy for one channel |
| **Cloudflare R2** | Bucket + public domain + API token (INTEGRATIONS.md) | Publish one watch in simulation, confirm the image URLs open |
| **Shopify** | App with client credentials and scopes | Run against a development store first; confirm product, images, Online Store publication, draft-on-reserve and archive-on-sold |
| **Instagram / Facebook Page** | System user token, account IDs, R2 | One carousel to a test account; check the RESERVED/SOLD edits on a Page post |
| **Chrono24** | Feed format and import URL from your integration manager | Confirm the column names (current ones are a sensible default, **not** confirmed by Chrono24) |
| **eBay** | Keyset, refresh token, business policies, location | Use the sandbox (`EBAY_ENVIRONMENT=sandbox`) first |
| **Google Drive / Sheets** | Service account shared on the folder and sheet | Inbox listing and one Sheet import |
| **Telegram** | Bot token, chat ID, admin IDs | Approval request message arrives with a working link |
| **WhatsApp Cloud API** | Number, token, app secret, verify token, public HTTPS | Webhook verification and one photo into the inbox |

Shopify, Meta and eBay request formats follow their current API documentation (Shopify Admin GraphQL `2026-07`,
Graph API `v24.0`, Sell Inventory API v1); platforms change these, so re-check the version settings once a year.

## 2. No official API — by design these stay manual

Facebook Marketplace, Facebook dealer groups, Carousell, WhatsApp dealer groups, Reddit r/WatchExchange and MODA
@uction have no official API for posting listings. The studio prepares a draft pack and a checklist task; it never
automates these through browser scripting. Instagram posts cannot be edited or deleted through the API, so
reserved/sold/withdrawn create a manual task there too.

## 3. Real photographs still to be tested

The three reference scenarios (Richard Mille RM 67-01 edited set, MB&F raw camera set, H. Moser WhatsApp photos) run
end-to-end in the tests using **synthetic images drawn by code** (`tests/fixtures/synthetic.py`, every file is labelled
SYNTHETIC), because the real photo sets were not available. They prove the pipeline logic, gates and outputs, not the
visual quality on real watches. Still to do with your own photos:

- Cutout quality on bracelets, skeleton dials, sapphire casebacks, polished cases with strong reflections, and photos
  taken in the box. Use the cutout editor where needed; consider `REMBG_MODEL=birefnet-general` for harder sets.
- Serial detection on real engravings (brushed or curved casebacks, lugs, clasps, warranty cards). OCR can miss
  low-contrast engraving; that is why every photo with possible text needs your check before it can be used.
- Colour correction defaults (white balance strength, warmth) against your own taste — adjust in Settings → Studio
  defaults.
- The local photo-type guess (dial/side/caseback…) is a rough heuristic; AI tagging or your correction replaces it.

## 4. Platform limits not published by the platform

Shopify description, Facebook posts, Chrono24, Facebook Marketplace/groups, Carousell and MODA limits are conservative
internal defaults (marked "unverified" in the copy editor and in Settings → Channels). They are defined, with their
sources, in `app/copywriter/channels.py`; change them there if you learn the real numbers.

## 5. Other limits

- **One role.** Everyone who can sign in can do everything. There are no staff roles with restricted permissions yet.
- **Performance.** Processing runs one photo at a time by default (`WORKER_CONCURRENCY=1`): about 5–10 s per photo
  for OCR, plus the cutout. The local cutout model needs 2–3 GB of memory on large raw images.
- **First-run download.** The cutout model (~180 MB) downloads on first use. If it cannot, the built-in classical
  cutout is used, which is weaker on busy backgrounds.
- **HEIC photos** need `pip install pillow-heif`; otherwise convert iPhone photos to JPEG first.
- **PostgreSQL** is supported by the models and migrations but has only been tested with SQLite.
- **AI background "context_edit" mode** sends a redacted photo to OpenAI; it is off by default (`AI_BACKGROUND_MODE=plate`
  sends no photo). The watch is always composited back from your original pixels either way.
- **Telegram conversations** are handled by Hermes, not by the studio, which only sends notifications.
- **Your computer's Python.** The studio needs Python 3.12+. It was built and tested on Python 3.13 in a Linux
  environment; run `pytest -m "not slow"` once on your own machine after installing to confirm.
