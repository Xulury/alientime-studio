---
name: listing-lifecycle
description: Mark an Alien Time watch reserved, sold, withdrawn or available again, update every channel, and give the owner the checklist for channels that need manual action.
---

# Listing lifecycle

## Commands
- `studio-agent reserve --sku <SKU> --telegram-user <id> [--note "deposit received"]`
- `studio-agent sold --sku <SKU> --telegram-user <id>`
- `studio-agent withdraw --sku <SKU> --telegram-user <id>`
- `studio-agent available --sku <SKU> --telegram-user <id>`
- Then: `studio-agent tasks --sku <SKU>` for the manual checklist.

## Read the result
- `sync.automatic` = channel updates queued through APIs; `sync.manual` = checklist items for the owner.
- Repeat `sync.message` to the owner. If any manual items remain, list them — **never say the watch is off every
  channel while manual items or failed updates remain.**
- Chrono24 drops the piece only at the next feed import: remind the owner to mark it sold in the dealer console.

## Rules
- Only the owner (or a named admin) may mark sold, reserved or withdrawn. Always pass their Telegram user id.
