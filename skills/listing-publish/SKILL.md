---
name: listing-publish
description: Publish an approved Alien Time listing to its channels and hand over draft packs for the channels that must be posted by hand.
---

# Listing publish

## Commands
- Publish: `studio-agent publish --sku <SKU> --channels shopify,instagram,carousell --telegram-user <id>`
- Manual tasks (draft packs to post, links to record): `studio-agent tasks --sku <SKU>`
- Job progress: `studio-agent jobs --sku <SKU>`

## Read the result per channel
- `queued` with `mode: live` → the studio is publishing through the platform's official API.
- `queued` with `mode: simulation` → **nothing will be posted**; the platform is not connected yet. Say so plainly.
- `manual_task` → the channel has no posting API (FB groups, MODA, Marketplace, Carousell, WhatsApp groups,
  Reddit). Tell the owner a draft pack is ready on the review page and that they post it themselves.
- `blocked` → read the blockers back and stop.

## Rules
- Only publish when the owner asked, and pass their Telegram user id.
- Never claim a listing is live unless its listing status is `live` or `manual_posted` with a link.
