# Alien Time Listing Studio

A private studio for Alien Time's watch listings. Photos go in; protected, studio-quality images, verified
listing copy for eleven sales channels, and approved, published listings come out. Nothing posts until you
approve it.

- **Module 1 — Automated studio photography:** quality inspection, serial-number redaction (local OCR, four
  rotations, second-pass check), watch cutout (local model), colour correction, velvet/studio backgrounds
  (local or AI-generated backdrop only), compositing that keeps every watch pixel, a numeric fidelity gate,
  platform crops, before/after comparison.
- **Module 2 — Multi-channel copy & publishing:** fact sheet with provenance and missing-fact checks, specs
  library, AI or template copy for Shopify, Instagram, Facebook Page, Chrono24, eBay, Facebook Marketplace,
  FB dealer groups, Carousell, WhatsApp dealer groups, Reddit r/WatchExchange and MODA @uction, claim and
  limit checks, versioned approvals, publishing adapters, draft packs, reserved/sold propagation.
- **Hermes-ready:** a JSON command interface and skills, using scoped tokens; the web app does not need Hermes.

Progress against the build brief is tracked in [PROGRESS.md](PROGRESS.md). Known gaps are in
[docs/LIMITATIONS.md](docs/LIMITATIONS.md).

---

## 1. Run it on this computer

### One click

| Computer | Do this |
| --- | --- |
| **Windows** | Double-click **`start-studio.bat`** |
| **Mac** | Double-click **`Start Studio.command`** (first time: right-click → Open, because it is not from the App Store) |
| **Linux** | Run `./start-studio.sh` |

The first run sets everything up by itself — it creates a private Python environment (`.venv`), installs the
packages (about 500 MB, a few minutes), creates `.env` from the template, and starts the studio. After that it starts
in a few seconds. Your browser opens at **http://127.0.0.1:8000**; create the owner account there (only possible from
this computer). Keep the window open while you work; close it (or press Ctrl+C) to stop the studio. Double-clicking
again while it is running just opens the browser.

The backend serves the web interface itself, so one window runs everything. Node.js is *not* needed: the interface is
already built into `app/web` (if Node.js is installed and the interface source has changed, the launcher rebuilds it).

You need **Python 3.12 or newer** (tested on 3.13). If Windows has none, the launcher offers to install it with winget,
or tells you where to get it.

Options (add after the file name in a terminal, e.g. `start-studio.bat --port 8001`):

| Option | What it does |
| --- | --- |
| `dev` | Developer mode: live-reloading backend **and** the Vite frontend dev server with hot reload (needs Node.js); opens http://127.0.0.1:5173 |
| `--port 8001` | Use another port (it also moves on automatically if 8000 is taken by another program) |
| `--no-browser` | Do not open the browser (e.g. when started automatically at log-on) |
| `--reinstall` | Reinstall the Python packages |
| `--rebuild` | Rebuild the web interface (needs Node.js) |

### By hand (if you prefer)

**Windows (PowerShell)**

```powershell
cd D:\Alien-Time\alien-time-listing-studio
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt -r requirements-integrations.txt
copy .env.example .env          # only if .env does not exist yet
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**macOS / Linux**

```bash
cd alien-time-listing-studio
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt -r requirements-integrations.txt
cp -n .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

The first photo you process downloads the local cutout model once (~180 MB). If that download is blocked, the
studio falls back to its built-in classical cutout automatically.

### Add your OpenAI key

Open `.env` and set:

```
OPENAI_API_KEY=sk-...
```

Restart the studio, then go to **Settings → AI → Test connection**. Until a key is set, AI tagging, AI copy and AI
backgrounds show as "not configured"; template copy and the local velvet/studio backgrounds work without it.
Model names, budgets and the photo policy are also in `.env` (see comments there). Before using the image model,
OpenAI may require **API Organization Verification** on your account.

### Try it with sample photos

```bash
python -m app.cli demo-fixtures          # writes SYNTHETIC reference photos into data/inbox/
```

Then add a watch and drop the photos in, or use the inbox import (`studio-agent inbox-import`).
These are drawn by code, not real photographs — see docs/LIMITATIONS.md.

---

## 2. Everyday commands

| What | Command |
| --- | --- |
| Start the studio | double-click `start-studio.bat` / `Start Studio.command`, or `uvicorn app.main:app --host 127.0.0.1 --port 8000` |
| Run the worker separately (optional, `WORKER_MODE=external`) | `python -m app.jobs.worker` |
| Apply database migrations (also runs at start) | `python -m app.cli migrate` |
| Reset a forgotten password | `python -m app.cli set-password midas` |
| Create an agent token for Hermes | `python -m app.cli create-token hermes` (or Settings → Agent access) |
| Back up database + photos | `python -m app.cli backup` |
| Health of OCR, cutout, AI, integrations | `python -m app.cli status` |
| Run the tests | `pytest` (add `-m "not slow"` to skip the reference-scenario runs) |
| Rebuild the web interface after changing it | `cd frontend && npm install && npm run build` |
| Backend + frontend live development | `start-studio.bat dev` / `./start-studio.sh dev` (or `cd frontend && npm run dev` with the backend on port 8000) |

---

## 3. How a watch moves through the studio

1. **Add a watch** (SKU assigned automatically, e.g. `AT-RM-0001`) and drop in photos. Originals are stored
   byte-for-byte, read-only, with a SHA-256 hash. Exact and near duplicates are flagged.
2. **Processing** runs in the background: serial scan and visible redaction blocks → cutout → inspection
   (sharpness, exposure, resolution, framing, source type) → studio render in three formats with a fidelity check.
3. **Check the photos** (Photos tab or the studio editor). Photos with serial-like text, dense engraving, or no OCR
   available need your check before they can go to cloud AI or be approved. Casebacks, movements and papers never
   go to cloud AI.
4. **Fill missing facts** (Overview tab). AI and Sheet suggestions wait for your confirmation.
5. **Write copy** for every channel (templates or AI). Code inserts house terms word for word and checks limits,
   claims ("in hand", "full set", "unworn"…) and that every number comes from the facts.
6. **Approve** images, channels or the whole package. Approvals are bound to a content hash: any later edit clears
   the affected approvals automatically, with the reason recorded.
7. **Publish.** Connected API channels publish through official APIs; unconnected ones run in clearly labelled
   simulation; channels without an API get a draft pack and a task to record the live link.
8. **Reserved / sold / withdrawn** updates inventory immediately, queues channel updates and creates a checklist
   for manual channels. The studio never says a watch is off every channel while anything is outstanding.

---

## 4. Project layout

```
app/
  api/            HTTP API (auth, watches, photos, listing, review, publishing, settings, system, webhooks)
  core/           settings store, lifecycle state machine, security, audit, storage, SKU
  db/             SQLAlchemy models, engine, migrations runner + MVP import
  ingest/         upload validation/hashing, local inbox (Drive/Telegram/WhatsApp share the same interface)
  imaging/        OCR, redaction, segmentation, inspection, colour, backgrounds, compositing, fidelity, pipeline
  providers/      AI provider interface, OpenAI adapter, mock provider, usage/cost/budget
  intel/          fact sheet, missing/conflicting facts, AI tagging and listing intelligence
  copywriter/     channel definitions + limits, Jinja templates, generator, validation
  review/         content-hash approvals, readiness, review gates
  publish/        adapters (Shopify, Instagram, Facebook Page, Chrono24 feed, eBay, simulation), draft packs,
                  publish service, lifecycle sync, jobs
  integrations/   connection states, Cloudflare R2, Google Drive/Sheets, Telegram, WhatsApp
  jobs/           persistent job queue and worker
  hermes/         `studio-agent` JSON command interface
  web/            built web interface (from frontend/)
frontend/         React + TypeScript + Tailwind source
migrations/       Alembic migrations
skills/           Hermes skills (SKILL.md per skill)
sop/              house rules the skills cite
tests/            pytest suite + SYNTHETIC reference fixtures
docs/             deployment, integrations, Hermes, limitations
```

## 5. Further reading

- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — running on the shop Mac mini or a VPS, HTTPS, backups, PostgreSQL
- [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) — setting up each platform and what it can and cannot do
- [docs/HERMES.md](docs/HERMES.md) — connecting Hermes and Telegram safely
- [docs/SECURITY.md](docs/SECURITY.md) — what is protected and how
- [docs/LIMITATIONS.md](docs/LIMITATIONS.md) — what still needs credentials or real-world verification
