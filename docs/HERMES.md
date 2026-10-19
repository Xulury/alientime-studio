# Hermes integration

The studio works fully on its own. Hermes (your agent on Telegram) is an optional second way in: it runs studio commands on
your behalf and reports back. It **never** gets the database, the `.env` file, platform credentials or your password —
only a scoped, revocable agent token for the studio's own API.

```
Telegram  ──►  Hermes  ──►  studio-agent (JSON)  ──►  Studio API (scoped token)  ──►  database, photos, adapters
```

## 1. Create an agent token

Settings → **Agent access** → New token (or `python -m app.cli create-token hermes`). The token is shown once; store
it in your password manager. Only its SHA-256 digest is kept in the studio.

| Scope | Allows | Default |
| --- | --- | --- |
| `read` | inventory, photos, copy, jobs, status | ✓ |
| `intake` | create watches, upload photos, import the inbox | ✓ |
| `process` | photo pipeline, AI tagging / comparison (same cloud-AI gate as the web app) | ✓ |
| `copy` | generate and edit listing copy | ✓ |
| `request_approval` | send you an approval request | ✓ |
| `approve` | approve images, channels, packages | admin |
| `publish` | publish approved channels | admin |
| `lifecycle` | reserved / sold / withdrawn / available | admin |
| `settings` | settings, integrations, tokens | admin |

**Admin scopes fail closed.** A token with `approve`, `publish` or `lifecycle` can only use them when the request names
the Telegram user who asked (`--telegram-user <id>`, sent as `X-Acting-User`) **and** that ID is listed in
`TELEGRAM_ADMIN_USERS`. If the list is empty, every admin action by an agent is refused. Every agent action is in the
Activity log as `agent:<token name>` with the acting Telegram user.

Recommended: give Hermes the default scopes plus `lifecycle` (so "sold" from your phone works), and keep `approve` and
`publish` for the web app until you trust the flow.

## 2. Install the command and skills on the Hermes machine

`studio-agent` only needs Python 3.10+ and `httpx`:

```bash
pip install httpx
export STUDIO_API_URL=http://127.0.0.1:8000      # or your Cloudflare Tunnel hostname
export STUDIO_AGENT_TOKEN=at_...                  # inject from the password manager
python -m app.hermes status                       # from the project folder, or install with `pip install -e .`
ln -s /path/to/alien-time-listing-studio/skills ~/.hermes/skills/alientime
```

If Hermes reaches the studio through Cloudflare Access, add an Access **service token** for Hermes and pass its headers
through your tunnel configuration; the studio token is still required.

## 3. Commands

All commands print one JSON object: `{"ok": true, "command": …, "data": …}` or
`{"ok": false, "error": "…", "status": 403}`; exit code 0 or 1.

| Command | What it does |
| --- | --- |
| `status` | Dashboard counts and running jobs |
| `inventory [--status S] [--q TEXT]` | List watches |
| `intake --brand B --model M [--reference R] [--sku S] [--photos files…]` | Create a watch and upload photos |
| `upload --sku S --photos files…` | Add photos |
| `inbox` / `inbox-import [--source local_inbox\|google_drive] [--sku S]` | Photos waiting in the inbox(es) |
| `process --sku S` | Run the photo pipeline for unprocessed photos |
| `images --sku S` | Kept/left out with reasons, privacy check, fidelity, review |
| `facts --sku S` / `set-fact --sku S --field F --value V` | Facts, missing items, suggestions / record a fact you gave |
| `ai-tag --sku S` / `ai-intel --sku S` | AI photo tagging / photo-vs-record check (suggestions only) |
| `copy --sku S [--mode template\|ai] [--channels a,b]` | Generate listing copy |
| `review --sku S` | Readiness: blockers per image and channel |
| `request-approval --sku S` | Send you the approval request |
| `approve --sku S (--channel C \| --package) --telegram-user ID` | Admin: approve |
| `publish --sku S --channels a,b --telegram-user ID [--simulate]` | Admin: publish approved channels |
| `reserve` / `sold` / `withdraw` / `available --sku S --telegram-user ID` | Admin: lifecycle, with the checklist summary |
| `tasks [--sku S]` | Open manual tasks |
| `jobs [--sku S] [--status S]` / `wait --job ID` | Background jobs |

## 4. What Hermes cannot do

- See originals, casebacks or serial findings text (the API never returns OCR text, only that something was found).
- Mark a photo "checked for serials" — that requires a person in the web app.
- Approve or publish anything not approved exactly as it is now (content-hash approvals apply to agents too).
- Claim a watch is off every channel: lifecycle results list manual channels still on your checklist.
- Change settings, integrations or tokens unless you deliberately grant `settings` (not recommended).

## 5. Telegram notifications

With `TELEGRAM_BOT_TOKEN` and `TELEGRAM_NOTIFY_CHAT_ID` set, the studio itself sends approval requests (with a link to
the review page), publish failures and sold/reserved checklists. Hermes can also relay these; both are optional.

## 6. Skills and SOPs

`skills/` holds one `SKILL.md` per workflow (intake, images, copy, review, publish, lifecycle, inventory); `sop/` holds
the house rules they cite (serial safety, velvet backgrounds, lead angle, disclosure wording). Keep both in git and read
the diff before accepting changes Hermes proposes to its own skills.
