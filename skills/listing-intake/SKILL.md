---
name: listing-intake
description: Start a new Alien Time watch listing from photos sent in Telegram or dropped in the inbox — creates the watch record (SKU assigned automatically) and uploads the photos to the studio.
---

# Listing intake

Use when the owner or staff send watch photos and say what the watch is, or ask to "check the inbox".

## Commands
- New watch with photos: `studio-agent intake --brand "<brand>" --model "<model>" [--reference <ref>] --photos <files or folder>`
- More photos for an existing watch: `studio-agent upload --sku <SKU> --photos <files>`
- Inbox: `studio-agent inbox`, then `studio-agent inbox-import [--sku <SKU>]`

## Check the output
- `ok` must be `true`. Report the new `sku` back to the person.
- For each upload, `status` is `added`, `duplicate` or `rejected`; tell the person about duplicates and rejections
  (the `message` says why, e.g. not an image, too large).
- Photo processing starts automatically (`jobs`). Do not wait for it unless asked; use the listing-images skill.

## Rules
- Never send photos anywhere except the studio. Never post or forward photos yourself.
- Do not guess the brand or model. If the person did not say, ask.
- Papers, invoices and warranty cards may be uploaded; the studio keeps them private automatically.
