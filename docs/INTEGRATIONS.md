# Integration setup

Every integration shows one honest state in **Settings → Integrations** and **Publishing → Platforms**:

| State | Meaning |
| --- | --- |
| Not configured | One or more required `.env` values are missing |
| Configured | Values present, connection not yet tested |
| Connected | Last connection test succeeded |
| Error | Last test or call failed (the message says why) |
| Unsupported | The platform has no official API for this; the studio prepares a draft pack instead |

**Live publishing is a separate switch** per platform (Publishing → Platforms) and only becomes available when the
platform is Connected. Until then the channel runs in **simulation**: nothing is posted, results are labelled
"Simulated", links point to `simulation.invalid`, and simulated listings never count as live anywhere in the studio.
Set `ENABLE_SIMULATED_PUBLISHING=false` to remove simulation completely.

After changing `.env`, restart the studio, then press **Test** on the integration.

Optional Python packages for Google and Cloudflare R2: `pip install -r requirements-integrations.txt`.

---

## OpenAI (AI tagging, listing intelligence, copy, AI backgrounds)

1. Create a project at platform.openai.com, set a monthly budget on it, create a project API key.
2. `.env`: `OPENAI_API_KEY=…` (optionally `OPENAI_PROJECT`, `OPENAI_ORGANIZATION`).
3. Image generation may require **API Organization Verification** in the OpenAI dashboard.
4. Settings → AI → **Test connection**.

What is sent: only photos that pass the cloud-eligibility gate (`CLOUD_AI_IMAGE_POLICY`, default `reviewed_only`):
redacted copies of dial/side/clasp frames that you have checked. Casebacks, movements, documents and anything with an
unchecked serial finding are never sent. AI backgrounds default to `AI_BACKGROUND_MODE=plate` (a text-only prompt; no
photo leaves the computer). Every call is logged with tokens and estimated cost; daily/monthly budgets stop further
calls when reached.

## Cloudflare R2 (public image URLs)

Instagram, eBay and the Chrono24 feed need images at public HTTPS URLs. Only **approved final renders** are uploaded,
under `listings/<SKU>/…`; originals never leave the computer.

1. Cloudflare → R2 → create bucket (e.g. `alien-time-listings`), enable a public custom domain (e.g. `img.alientime.sg`).
2. R2 → Manage API tokens → create an *Object Read & Write* token scoped to that bucket.
3. `.env`: `CLOUDFLARE_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`,
   `R2_PUBLIC_BASE_URL=https://img.alientime.sg` (optional `R2_ENDPOINT_URL`).

Withdrawing or selling a watch deletes its uploaded images from R2.

## Shopify (product listing)

Uses the Admin GraphQL API with the **client-credentials grant** (token is refreshed automatically, kept in memory).

1. Shopify Dev Dashboard → create an app for your store, install it, grant scopes `write_products`,
   `read_products`, `write_publications`, `read_publications`, `write_files` (staged uploads).
2. `.env`: `SHOPIFY_SHOP=yourstore.myshopify.com`, `SHOPIFY_CLIENT_ID`, `SHOPIFY_CLIENT_SECRET`,
   `SHOPIFY_API_VERSION` (default `2026-07`).
3. Test, then switch live on.

Behaviour: publishing creates the product as **draft** with approved images (uploaded via staged uploads), then
activates it and publishes it to the Online Store. Reserved sets it back to draft (hidden from the store); available
re-activates it; sold and withdrawn archive it (never deleted). Updates re-send title, description, price and images.
*Not yet run against a live store — test on a development store first.*

## Instagram (carousel post) and Facebook Page

Uses the Meta Graph API (`META_GRAPH_VERSION`, default `v24.0`) with a **system user token** from Meta Business Suite.

1. Business Settings → Users → System users → add a system user, assign the Facebook Page and both Instagram professional
   accounts, generate a token with `instagram_basic`, `instagram_content_publish`, `pages_show_list`,
   `pages_read_engagement`, `pages_manage_posts`, `business_management`.
2. `.env`: `META_APP_ID`, `META_APP_SECRET`, `META_SYSTEM_USER_TOKEN`, `IG_USER_ID_ALIENTIME_SG`,
   `IG_USER_ID_OFFICIAL` (either or both), `FB_PAGE_ID`.
3. Instagram also needs Cloudflare R2 (public JPEG URLs).

Behaviour: Instagram posts a carousel (up to 10 images, 4:5) to each configured account. Published posts cannot be
edited or deleted through the API, so reserved/sold/withdrawn create a manual task (edit the caption or archive the
post yourself). Facebook Page publishes a multi-photo post; reserved and sold put RESERVED / SOLD at the top of the post,
available removes RESERVED, and withdraw deletes the post.

## Chrono24 (dealer feed)

Chrono24 has no public listing API for dealers; listings come from a private feed your Chrono24 integration manager
imports on a schedule.

1. Ask your integration manager for the feed format and an import URL/schedule.
2. Host the feed: publish `data/feeds/chrono24.csv` (or the copy uploaded to R2 at `feeds/chrono24.csv`) at the URL they
   import from, and set `CHRONO24_FEED_URL` to it.
3. Publishing → Chrono24 feed → **Rebuild** / **Download** to check the file.

Columns are a sensible default (`internal_id, brand, model, reference_number, year, condition, scope_of_delivery,
price, currency, price_usd, title, description, location, image_urls`) and **must be confirmed with Chrono24**
before go-live. Sold/reserved/withdrawn watches drop out of the feed, but stay visible until Chrono24's next import —
a manual task reminds you to mark them in the dealer console.

## eBay (optional)

Uses the Sell Inventory API (inventory item → offer → publish).

1. developer.ebay.com → create a production keyset; create a RuName; complete the user consent flow once to get a
   refresh token with `sell.inventory` and `sell.account` scopes.
2. In Seller Hub create business policies (fulfilment, payment, return) and an inventory location.
3. `.env`: `EBAY_CLIENT_ID`, `EBAY_CLIENT_SECRET`, `EBAY_RU_NAME`, `EBAY_REFRESH_TOKEN`,
   `EBAY_MERCHANT_LOCATION_KEY`, `EBAY_FULFILLMENT_POLICY_ID`, `EBAY_PAYMENT_POLICY_ID`, `EBAY_RETURN_POLICY_ID`,
   `EBAY_MARKETPLACE_ID` (default `EBAY_US`), `EBAY_CATEGORY_ID` (default `31387`, Wristwatches).
4. Needs Cloudflare R2.

Reserved has no eBay equivalent: the studio withdraws the offer, and marking the watch available again republishes it.

## Google Drive (photo inbox) and Google Sheets (facts)

Uses a **service account** (read-only scopes).

1. Google Cloud → create a project, enable Drive API and Sheets API, create a service account and download its JSON key.
2. Share your Drive folder (with an `Inbox/` sub-folder) and your facts sheet with the service account's email.
3. `.env`: `GOOGLE_APPLICATION_CREDENTIALS=/path/to/key.json`, `DRIVE_ROOT_FOLDER_ID`, `FACTS_SHEET_ID`
   (optional `FACTS_SHEET_RANGE`).

Drive: files in `Inbox/` appear under **Inbox** in the studio and in `studio-agent inbox`; a sub-folder named after a SKU
attaches its photos to that watch. Sheets: the header row is matched to fact names (`sku`, `brand`, `reference`, `year`,
`price_sgd`…); **Import from Sheet** on a watch creates suggestions you confirm — nothing is overwritten automatically.

## Telegram (notifications; Hermes)

1. Create a bot with @BotFather; get your numeric user ID (e.g. from @userinfobot).
2. `.env`: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_NOTIFY_CHAT_ID` (where approval requests go), `TELEGRAM_ALLOWED_USERS`,
   `TELEGRAM_ADMIN_USERS` (only these IDs may approve/publish/mark sold through Hermes).

The studio only *sends* notifications (approval requests, publish failures, sold checklists). Conversations with the bot
are handled by Hermes — see HERMES.md.

## WhatsApp Cloud API (optional intake)

Lets photos sent to your business number land in the studio inbox. WhatsApp **groups cannot be posted to** through any
official API, so WhatsApp dealer groups stay a manual draft-pack channel.

1. Meta for Developers → WhatsApp → add a phone number; note phone number ID and business account ID; create a permanent
   system-user token.
2. Configure the webhook: callback `https://<your studio>/api/webhooks/whatsapp`, verify token = your
   `WHATSAPP_VERIFY_TOKEN`, subscribe to `messages`.
3. `.env`: `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, `WHATSAPP_BUSINESS_ACCOUNT_ID`, `WHATSAPP_APP_SECRET`,
   `WHATSAPP_VERIFY_TOKEN`.

Every webhook call's `X-Hub-Signature-256` is checked against the app secret; unsigned calls are rejected. This requires the
studio to be reachable over HTTPS (Cloudflare Tunnel — see DEPLOYMENT.md).

## Manual channels (no official posting API)

Facebook Marketplace, Facebook dealer groups, Carousell, WhatsApp dealer groups, Reddit r/WatchExchange and MODA @uction.
Publishing creates a **draft pack** (zip with platform-sized images, copy as text, posting instructions) and a task.
Mark the task done and paste the live link; only then is the channel counted as listed. When the watch is reserved or
sold, a checklist task is created for each of these channels.

## Platform limits used by the copy checks

| Channel | Limits | Source verified? |
| --- | --- | --- |
| Shopify | title 255 | yes · description 20,000 is an internal default |
| Instagram | caption 2,200 | yes |
| Facebook Page | text 5,000 | internal default |
| Chrono24 | title 100, text 5,000 | internal default (confirm with integration manager) |
| eBay | title 80, description 4,000 (studio cap) | yes |
| FB Marketplace / groups | title 100, text 5,000 | internal default |
| Carousell | title 80, text 4,000 | internal default |
| WhatsApp | 4,096 | yes |
| Reddit | title 300, text 40,000 | yes |
| MODA @uction | 5,000 | internal default |

Internal defaults are shown as "unverified" in the copy editor and Settings → Channels; they are defined with their
sources in `app/copywriter/channels.py`.
