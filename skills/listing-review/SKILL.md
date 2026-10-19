---
name: listing-review
description: Report whether an Alien Time listing is ready, request the owner's approval, and record approvals the owner gives in Telegram.
---

# Listing review and approval

## Commands
- Readiness: `studio-agent review --sku <SKU>`
- Ask for approval (sends the review link): `studio-agent request-approval --sku <SKU>`
- Record an approval the owner gave you:
  `studio-agent approve --sku <SKU> --package --telegram-user <their Telegram user id>`
  or one channel: `studio-agent approve --sku <SKU> --channel shopify --telegram-user <id>`

## Rules
- Only call `approve` when the owner explicitly approves in this conversation. "Looks good" about one channel is
  not approval of the whole package — ask.
- Always pass the Telegram user id of the person who approved. The studio refuses anyone not on the admin list,
  and records who approved what and when.
- If the result contains blockers, read them back to the owner and stop. Do not try to work around them.
- Approval is tied to the exact content. If anything is edited afterwards, the studio clears the approval; run
  `review` again and ask again.
