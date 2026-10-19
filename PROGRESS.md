# Alien Time Listing Studio — Progress Tracker

This file tracks every requirement from the build brief and `Alien Time Listing Studio — Build Spec.md`.
Each item is ticked only when it is implemented **and** exercised by a test or a manual run.

Legend: `[x]` done · `[ ]` not done · `[~]` done locally, needs credentials or real-world verification

_Last updated: 2026-10-19 — all phases implemented; live platform checks wait on credentials (see `[~]`)_

---

## Phase 0 — Audit of the existing MVP

- [x] Inspect directory structure (11 files: `app/main.py`, one-line Jinja template, CSS, contracts, 4 tests)
- [x] Read the complete build spec
- [x] Run existing tests (4 passed on Python 3.13)
- [x] Identify gaps vs spec (see "Audit findings" below)
- [x] Write implementation plan (see "Plan" below)

### Audit findings
| Area | MVP state | Gap |
| --- | --- | --- |
| Backend | Single 218-line FastAPI file, raw `sqlite3` | No ORM, no migrations, no modules |
| Auth | Optional HTTP Basic with one shared password | No password hashing, sessions, CSRF, lockout |
| Inventory | Create/update, one `price` text field | No SGD/USD, consignment, availability, search/filter/sort, delete |
| Uploads | Re-encodes originals (original bytes lost), no hashing | No SHA-256, duplicate detection, read-only originals |
| Imaging | Pillow square canvas only | No inspection, OCR, redaction, segmentation, backgrounds, fidelity |
| AI | None | No provider, usage tracking or budget |
| Copy | f-string templates, 9 channels | No fixed blocks, limits, claims check, revisions per section |
| Approval | One revision counter for the whole watch | No per-image/per-channel approvals, no content hashes |
| Publishing | `DisabledPublisher` only | No adapters, mock mode, draft packs per platform, manual tasks |
| Jobs | Synchronous in request | No background jobs |
| Hermes | Not started | No CLI, skills or scoped tokens |
| UI | Server-rendered single template | No dashboard stats, studio editor, review centre, publishing centre |

### Plan
1. Restructure into modules under `app/` (keep FastAPI + SQLite, add SQLAlchemy + Alembic).
2. Build the photography pipeline as local, testable functions; run them in persistent background jobs.
3. Add the OpenAI adapter, facts engine and channel copy generator with code-enforced fixed blocks and claim checks.
4. Add content-hash approvals, publishing adapters (live structures + clearly labelled simulation), draft packs and lifecycle sync.
5. Replace the Jinja UI with a React + TypeScript + Tailwind single-page app served by FastAPI (pre-built, so Node is not needed to run it).
6. Add the Hermes CLI + skills and the remaining integration adapters.
7. Test end to end, document, and deliver.

---

## Phase 1 — Foundation
- [x] Modular package layout (`app/core`, `app/db`, `app/imaging`, `app/providers`, `app/intel`, `app/copywriter`, `app/review`, `app/publish`, `app/integrations`, `app/jobs`, `app/api`, `app/hermes`)
- [x] Settings from `.env` (pydantic-settings), no hard-coded secrets
- [x] Structured JSON logging with secret redaction
- [x] SQLAlchemy models (SQLite local, PostgreSQL-compatible types)
- [x] Alembic migrations (initial schema) run automatically on start
- [x] Safe migration of legacy MVP data (`watches`, `assets`, `channel_drafts`, `audit`) — old DB backed up first
- [x] Single-user authentication: scrypt password hashing, first-run setup, login, logout, change password
- [x] Server-side sessions (HttpOnly cookie), expiry, lockout after repeated failures
- [x] CSRF protection (per-session token header) for cookie-authenticated writes
- [x] Security headers (CSP, frame-deny, nosniff, referrer policy), safe error messages
- [x] Audit log for every write (who, what, when)
- [x] Watch inventory CRUD (create, read, update, archive/restore with confirmation)
- [x] Watch fields: SKU, brand, model, reference, year, condition, SGD/USD prices, FX metadata, box & papers, availability, custody, consignment, description, timestamps
- [x] Automatic SKU assignment (brand prefix + sequence), manual override with uniqueness check
- [x] Search, filters, sorting, pagination
- [x] Lifecycle state machine (draft → processing → awaiting review → approved → published → reserved/sold/withdrawn)
- [x] Persistent job queue (pending/running/completed/failed/cancelled), progress, retries, restart recovery, idempotency keys
- [x] Worker (in-process thread or separate process)
- [x] Secure uploads: type sniffing (JPEG/PNG/WebP, HEIC optional), size + pixel limits, multiple files
- [x] Original bytes preserved exactly, read-only, SHA-256 recorded
- [x] Exact duplicate detection (hash) and near-duplicate detection (perceptual hash)
- [x] Local ingestion adapter (upload + inbox folder) behind an ingestion interface
- [x] Tests for all of the above (`test_foundation.py`, `test_uploads.py`)

## Phase 2 — Automated Studio Photography (Module 1)
- [x] Stage 1 inspection: sharpness, exposure, blur, resolution, duplicates, watch visibility, composition
- [x] Source profile detection (edited / raw camera / phone-WhatsApp)
- [x] Photo type classification (dial/front, side/profile, crown, clasp, strap, caseback, movement, document) — local heuristic + AI tagging + manual override
- [x] Selected / rejected frames with one-line reasons
- [x] Stage 2 local OCR (RapidOCR) at four rotations; serial-like text detection without storing the text
- [x] Visible redaction blocks; second-pass OCR recheck inside redacted areas
- [x] Manual add / edit / remove of redaction regions; "checked" review step (people only — agents are refused)
- [x] Uncertain frames blocked from cloud AI and publishing until reviewed
- [x] Stage 3 segmentation adapter (rembg ISNet/BiRefNet, OpenCV GrabCut fallback), soft masks, hole filling
- [x] Editable masks (keep/remove brush in the studio editor), mask versioning, reset
- [x] Stage 4 enhancement: white balance, exposure, contrast, warmth (deterministic, recorded)
- [x] Backgrounds: cleanup, keep original (edited sets), studio white/grey/black, green velvet (local), AI background plate (OpenAI)
- [x] AI background is background-only; original watch pixels composited back with the mask; model watch pixels discarded
- [x] Contact shadow from mask
- [x] Crops: 2:3 store frame, 1:1 square, 4:5 social, platform presets
- [x] Hero image option (lead frame, optional rotation)
- [x] Fidelity gate: numeric comparison inside the watch outline vs. the approved transform of the original; redaction-preserved check
- [x] Render history (regenerate individual images, restore an older render), download, approve/reject
- [x] Tests (inspection, OCR/redaction, masks, compositing, fidelity) — `test_imaging.py`
- [~] Visual quality on the real RM 67-01 / MB&F / Moser photo sets (only SYNTHETIC fixtures were available — docs/LIMITATIONS.md §3)

## Phase 3 — OpenAI integration and listing intelligence (Module 2a)
- [x] OpenAI adapter: separate configurable models for vision, listing intelligence, text, image (defaults checked against OpenAI's published model list, Oct 2026)
- [x] Connection test, timeouts, retries, safe error handling
- [x] Usage logging (tokens, image requests), estimated cost, daily + monthly budget enforcement
- [x] Mock provider for tests
- [x] JSON-schema structured outputs validated with Pydantic
- [x] Cloud-eligibility gate: no casebacks/movements/documents/unreviewed frames ever sent
- [x] Vision tagging of eligible (redacted) frames; wrong-watch flag
- [x] Specs library (local, approve before use)
- [x] Facts engine: user facts + inventory + approved specs + AI observations, with provenance
- [x] Missing / conflicting facts (reference, year, prices, condition, set, custody, FX drift, model mismatch)
- [x] AI suggestions shown as editable fields that need confirmation (never auto-applied)
- [x] Google Sheet import creates suggestions only
- [~] Live OpenAI calls — waiting for your `OPENAI_API_KEY` (tested with the mock provider and recorded request shapes)

## Phase 3b — Multi-channel copy (Module 2b)
- [x] 11 channels: Shopify, Instagram, Facebook Page, Chrono24, eBay, Facebook Marketplace, FB dealer groups, Carousell, WhatsApp dealer groups, Reddit r/WatchExchange, MODA @uction
- [x] Sections: title, description, caption, hashtags, price, specifications, condition, accessories, terms, disclaimer, call to action
- [x] Template generation (offline) and AI generation (OpenAI)
- [x] Fixed house blocks inserted by code word for word (per-channel call-to-action overrides)
- [x] Platform limits with documented sources (unverified limits labelled)
- [x] Claims check (numbers must trace to facts; "in hand", "full set", "unworn" rules; serial never mentioned)
- [x] Configurable writing styles (per channel)
- [x] Edit and regenerate individual sections; drafts + revision history + restore
- [x] Per-watch channel selection (e.g. leave MODA @uction out for one watch)
- [x] Tests — `test_ai_copy.py`

## Phase 4 — Review, approval, publishing, lifecycle
- [x] Review centre queue + per-watch review page
- [x] Approve/reject images, request regeneration, edit copy, approve channels, approve full package
- [x] Approvals bound to content hashes; material edits invalidate affected approvals automatically
- [x] Approval records: who, what (hash + snapshot), when, why cleared
- [x] Publishing readiness checks
- [x] Common adapter interface: validate connection, create, update, publish, withdraw, reserve, available, check status
- [~] Shopify (Admin GraphQL `productSet`/`productUpdate`/`publishablePublish`, staged uploads, client-credentials token refresh) — needs store credentials
- [~] Instagram (container → carousel → publish, public JPEG URLs from R2) — needs Meta token + R2
- [~] Facebook Page (multi-photo post, RESERVED/SOLD edits, delete on withdraw) — needs Meta token
- [x] Chrono24 dealer feed file (CSV, rebuilt on every change, downloadable) — [~] column names to confirm with Chrono24
- [~] eBay Inventory API (inventory item → offer → publish; sandbox supported) — needs eBay keys
- [x] Simulation mode clearly labelled (`simulation.invalid` links), never counted as live
- [x] Draft packages (images sized per platform + copy + instructions; PREVIEW watermark if unapproved) for manual channels
- [x] Manual task list with "posted" confirmation and live URL capture
- [x] Idempotent publish jobs, duplicate checks, retries, failure recovery, scheduling
- [x] No unapproved content can be published (enforced in the API and again in the job)
- [x] Reserved / sold / withdrawn: immediate internal update, queued channel updates, failure reporting, manual checklists
- [x] Never claims "removed everywhere" while manual actions remain
- [x] R2 public images deleted on sold/withdrawn (failures recorded in the Activity log)
- [x] Tests — `test_review_publish.py`

## Phase 5 — Hermes and external integrations
- [x] Scoped API tokens for agents (hashed, revocable)
- [x] Admin actions by agent require an allow-listed Telegram user (fail closed)
- [x] Agents cannot sign off the serial-number check or edit redactions
- [x] Hermes CLI returning JSON (intake, process, copy, review status, approval request, approve, publish, inventory, reserve/sold/withdraw, tasks, jobs, wait)
- [x] `skills/` SKILL.md files for each Hermes skill (7)
- [x] `sop/` house rules
- [x] Adapters with honest states (not configured / configured / connected / error / unsupported): Google Drive, Google Sheets, Telegram, WhatsApp Cloud API, Shopify, Instagram, Facebook Page, Chrono24, eBay, Cloudflare R2
- [x] Telegram notifications (optional) — [~] needs bot token
- [x] WhatsApp webhook verification + signature check (optional intake) — [~] needs WhatsApp credentials and public HTTPS
- [x] Tests — `test_hermes.py` (plus integration-state tests in `test_review_publish.py`)

## Web application
- [x] React + TypeScript + Tailwind SPA, pre-built into `app/web` and served by FastAPI (Node not needed to run)
- [x] Login / first-run setup
- [x] Dashboard (counts, live vs simulated, needs-you list, in-progress, recent activity, quick actions)
- [x] Inventory list (search, filters, sort, status indicators)
- [x] New watch + drag-and-drop bulk upload with per-file progress
- [x] Watch detail (facts, photos, listing, review, publishing, activity)
- [x] Studio editor (5 stages, redaction editor, mask editor, background settings, compare slider with zoom)
- [x] Listing copy editor (sections, limits, regenerate, revisions)
- [x] Review centre
- [x] Publishing centre (platform status, queue, failures, manual tasks, scheduled jobs, Chrono24 feed)
- [x] Specs library, Jobs, Activity, Settings (AI, house terms, styles, claims, pricing, studio, channels, integrations, tokens, account, system)
- [x] Empty states, loading, progress, confirmation dialogs, helpful errors, responsive (phone drawer), keyboard focus
- [x] Visual check of every page at desktop and phone width; UI end-to-end run (create watch → upload → process → write copy → reserve) with no console errors

## Phase 6 — Testing, docs, delivery
- [x] Reference scenario fixtures: RM 67-01 (edited), MB&F (raw), H. Moser (WhatsApp) — synthetic, clearly labelled (`test_reference_scenarios.py`)
- [x] End-to-end run through the UI
- [x] README with setup + local commands
- [x] `docs/DEPLOYMENT.md`
- [x] `docs/INTEGRATIONS.md`
- [x] `docs/HERMES.md`
- [x] `docs/SECURITY.md`
- [x] `docs/LIMITATIONS.md` (blocked / incomplete functionality)
- [x] `.env.example` with all variable names, no values; `.env` created with empty secrets
- [x] One-click start: `start-studio.bat` (Windows), `start-studio.sh` (Linux/macOS), `Start Studio.command` (Mac double-click) — first-run setup, backend + web interface, opens the browser; `dev` mode runs backend + Vite together
- [x] Copied to `D:\Alien-Time\alien-time-listing-studio` (checksums match), full test suite (90 tests) passed on the delivered copy; MVP files kept in `legacy_mvp/`

---

## Phase summaries

### Phase 1 — Foundation
**Implemented:** modular FastAPI app; SQLAlchemy 2 models (20 tables) with Alembic migrations applied on start; one-time,
backed-up import of the MVP database; owner account with scrypt, sessions, CSRF, lockout and security headers; audit
log; inventory with automatic SKUs, search/filter/sort/pagination; lifecycle state machine; persistent job queue with
retries, idempotency and restart recovery; secure uploads that keep originals byte-for-byte with SHA-256 and duplicate
detection; local inbox ingestion.
**Main files:** `app/main.py`, `app/config.py`, `app/core/*`, `app/db/*`, `app/jobs/*`, `app/ingest/*`, `app/api/{auth,watches,assets,system}.py`, `migrations/`.
**Tests:** `test_foundation.py`, `test_uploads.py` — passing.
**Needs credentials:** none.

### Phase 2 — Studio photography
**Implemented:** inspection and source profiles; local OCR at four rotations with redaction blocks and a second-pass
check (OCR text never stored); people-only "checked" step; cutout (rembg with GrabCut fallback) with hole filling and a
brush editor; deterministic colour; local velvet/studio backgrounds and AI background plates; compositing that keeps
the original watch pixels; numeric fidelity gate including redaction integrity; three canvases plus platform presets;
render history and restore.
**Main files:** `app/imaging/*`, `app/api/assets.py`, `frontend/src/pages/StudioEditor.tsx`, `frontend/src/components/editors.tsx`.
**Tests:** `test_imaging.py` — passing.
**Needs:** real photo sets for visual acceptance.

### Phase 3 — AI and copy
**Implemented:** OpenAI provider (Responses API with strict JSON schemas, Images API) behind a provider interface,
mock provider, usage/cost logging and budgets; cloud-eligibility gate; facts engine with provenance, missing/conflict
checks and an approved specs library; AI and Sheet suggestions that need confirmation; 11 channels with templates or
AI copy, code-inserted house terms, limits with sources, claims and number checks, revisions and restore.
**Main files:** `app/providers/*`, `app/intel/*`, `app/copywriter/*`, `app/api/listings.py`.
**Tests:** `test_ai_copy.py` — passing.
**Needs credentials:** `OPENAI_API_KEY`.

### Phase 4 — Review, publishing, lifecycle
**Implemented:** content-hash approvals for images, channels and the package, cleared automatically on change;
readiness checks; adapters for Shopify, Instagram, Facebook Page, eBay and the Chrono24 feed; labelled simulation;
draft packs and manual tasks; idempotent, retrying, schedulable publish jobs; reserved/sold/withdrawn propagation with
honest summaries.
**Main files:** `app/review/*`, `app/publish/*`, `app/api/{review,publishing}.py`.
**Tests:** `test_review_publish.py` — passing.
**Needs credentials:** Shopify, Meta, eBay, Cloudflare R2, Chrono24 feed URL.

### Phase 5 — Hermes and integrations
**Implemented:** scoped agent tokens with fail-closed admin allow-list; `studio-agent` JSON CLI; 7 skills and 4 SOPs;
honest integration states and tests for Google Drive/Sheets, Telegram, WhatsApp (signature-checked webhook), R2.
**Main files:** `app/hermes/*`, `app/integrations/*`, `app/api/{config_api,webhooks}.py`, `skills/`, `sop/`.
**Tests:** `test_hermes.py` — passing.
**Needs credentials:** Telegram, Google service account, WhatsApp Cloud API (optional).

### Web application and Phase 6
**Implemented:** React/TypeScript/Tailwind interface (dashboard, inventory, new watch with bulk upload, watch pages,
studio editor, copy editor, review centre, publishing centre, specs, jobs, activity, settings), checked visually at
desktop and phone widths and through a scripted UI run; synthetic reference scenarios; README and docs.
**Next:** add your OpenAI key, connect R2 and one platform at a time (INTEGRATIONS.md), and run your first real watch
through the studio — see LIMITATIONS.md for what to look at closely.
