# Alien Time Listing Studio — development MVP

A functional, local-first web application for Modules 1 and 2 of the Alien Time specification. **No third-party API keys are needed to run this version.** It deliberately performs **no live publishing** and **no calls to external AI providers**.

## Start

Python 3.12+ recommended.

```bash
cd alien-time-listing-studio
python -m venv .venv
# macOS/Linux: source .venv/bin/activate
# Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
# Optional but recommended when not isolated on localhost:
# export STUDIO_PASSWORD='your-long-random-password'
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Open **http://127.0.0.1:8000**. If `STUDIO_PASSWORD` is set, username is `admin`.

## What currently works
- Single-user web dashboard with responsive design
- Create and update watch records (SKU, price, condition, custody and more)
- Upload and privately view source watch photos
- Local-only prepared square previews using Pillow; originals and prepared outputs shown side by side
- Create and edit **template-based** channel drafts for nine channels
- Revisioned internal approval, invalidated automatically by edits or new uploads
- Save local inventory lifecycle states and action history
- Export images, editable drafts and product information in a ZIP for manual posting
- SQLite persistence in `data/studio.db`, with files in `data/media`

## What is NOT yet implemented
- Hermes or Telegram orchestration (integration contract pending)
- Drive / Sheets ingestion and synchronisation
- OCR, serial masking, local segmentation or pixel-fidelity gates
- OpenAI, Claude, Gemini or image generation
- Full publishing integrations (Shopify, Meta, Chrono24 etc.)
- Live posting or external delisting (all intentionally disabled)
- Production-grade identity, encrypted storage, CSRF protection, job queue, backups, monitoring or multi-user access

**Important:** The prepared previews are not verified safe to publish. Do not upload personal documents or send images externally until serial-masking and review checks are implemented. Draft copy is assembled from entered fields, not fact-verified by AI.

## Next development milestones

1. **Image safety:** install local OCR and manual redaction tool, then segmentation and watch-region verification. Add the three reference watch test sets.
2. **AI provider adapters:** interface for OpenAI / Claude / Gemini and background-only image generation (real provider model choices must be verified).
3. **Review workflow:** per-channel approval, revision snapshots, authenticated backend and isolated publish worker.
4. **Integrations:** Google Drive + Sheets, Shopify first, authorised Meta accounts next. Others depend on API availability and client account approval.
5. **Production security:** deploy behind HTTPS and identity-aware access, add CSRF protection, audit and backups. Do not expose the current development server to the public internet.

## Tests

```bash
pytest -q
```

## Privacy
All watch images and inventory records are stored on the machine running the app. The development server uses basic authentication only when a password is set. It is not a production security boundary. Do not put it on a public domain without completing security hardening.

## Integration contracts

`app/integrations/contracts.py` defines small interfaces for photo inboxes, inventory, copy providers, studio background models and publishers. The default `DisabledPublisher` **fails closed** and cannot publish. Later implementations can use Google Drive, Sheets, OpenAI, Anthropic, Gemini, Shopify or Meta after explicit account access is granted.

The web dashboard is the initial interface. Hermes and Telegram can be added as separate controllers that call trusted application services rather than owning publisher credentials.
