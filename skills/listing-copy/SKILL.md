---
name: listing-copy
description: Collect missing facts from the owner and generate Alien Time listing copy for every sales channel, using only confirmed facts.
---

# Listing copy

## Commands
- What is known and missing: `studio-agent facts --sku <SKU>`
- Record a fact the owner just told you: `studio-agent set-fact --sku <SKU> --field <field> --value "<value>"`
  Fields: year, condition (unworn | excellent | very_good | good | fair), condition_notes, price_sgd, price_usd,
  box_papers (full_set | set_minus_box | box_and_papers | papers_only | box_only | watch_only), box_papers_notes,
  custody (in_hand | consigned_offsite), reference, plus spec facts such as calibre, case_size_mm, dial,
  warranty, service_history, auction_start_price.
- Optional AI check of photos against the record (creates suggestions only): `studio-agent ai-intel --sku <SKU>`
- Generate copy: `studio-agent copy --sku <SKU> [--mode ai|template] [--channels shopify,instagram]`

## Workflow
1. Run `facts`. For every issue with `severity: blocker`, ask the owner one short question at a time.
2. Only record values the owner actually gave you. Never invent or estimate a fact, price or year.
3. Suggestions from AI or the Sheet are **not** facts: ask the owner to confirm before `set-fact`.
4. Generate copy. Report channels with `errors` (the message says what to fix).

## Rules
- House terms, disclaimers and licence text are inserted by the studio word for word; never rewrite them.
- "In hand" is only allowed when custody is in_hand; the studio enforces this.
