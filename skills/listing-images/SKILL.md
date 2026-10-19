---
name: listing-images
description: Run and report on Alien Time's studio photography pipeline (privacy check, cutout, quality check, studio render) for a watch SKU.
---

# Listing images

## Commands
- Start processing anything not yet processed: `studio-agent process --sku <SKU>`
- Status per photo: `studio-agent images --sku <SKU>`
- Wait for a job: `studio-agent wait --job <id>`
- Optional AI photo tagging (only frames the owner has checked are sent): `studio-agent ai-tag --sku <SKU>`

## Check the output of `images`
For each photo report: `kept` (true/false and `reasons`), `privacy`, `fidelity_passed`.
- `privacy` = `needs_review`, `ocr_unavailable` or `failed` → tell the owner to open the review page and check the
  redactions. **You cannot confirm a privacy check for them.**
- `fidelity_passed` = false → the studio image must not be used; tell the owner.
- Rejected photos: pass on the one-line reason (blur, too small, duplicate, documents kept private).

## Rules
- Stop and report if any job fails. Do not retry more than once.
- Never describe or repeat serial numbers, even if the owner sends them.
