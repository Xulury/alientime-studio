# Security and privacy

What the studio protects, and how. If you change any of this, update this file and the tests.

## Secrets

- All credentials come from `.env` (or are injected by your password manager). Nothing is hard-coded; `.env.example`
  holds names only. `.env`, `.env.*` (except the example), `data/` and `backups/` are git-ignored.
- Secrets are read as pydantic `SecretStr` and never returned by the API: the Settings pages show only whether a value
  is set and which variable names are missing.
- Logs pass through a redaction filter that masks API keys, bearer tokens, `sk-…`/`at_…` strings and known secret
  values before anything is written.
- The browser never sees platform or OpenAI credentials; all calls to outside services are made by the server.

## Sign-in and access

- One owner account (more can be added with `python -m app.cli create-user`). Passwords are hashed with scrypt;
  minimum 10 characters. First-account setup only from this computer unless `STUDIO_SETUP_TOKEN` is set.
- Server-side sessions in an HttpOnly, SameSite=Strict cookie (`Secure` when `STUDIO_COOKIE_SECURE=true`); expiry
  `STUDIO_SESSION_HOURS`. Sign-in is rate-limited per address and an account locks for 15 minutes after 8 failed
  attempts.
- Every write from the web app needs the per-session CSRF token header.
- Security headers on every response: Content-Security-Policy (self only), `X-Frame-Options: DENY`,
  `X-Content-Type-Options: nosniff`, strict referrer policy, permissions policy.
- Errors returned to the browser are plain messages; stack traces stay in the server log.
- The server binds to `127.0.0.1` by default. It is not exposed publicly unless you set that up (see DEPLOYMENT.md).

## Agent tokens (Hermes)

- Random 256-bit tokens, shown once, stored as SHA-256 digests, revocable, with `last used` tracking.
- Scoped (read, intake, process, copy, request_approval, approve, publish, lifecycle, settings).
- Approve/publish/lifecycle/settings by an agent require an allow-listed Telegram admin (`TELEGRAM_ADMIN_USERS`);
  with no list configured they are refused (fail closed).
- Agents can never mark a photo as checked for serials or change its redactions — only a signed-in person can.
- Agents have no access to the database, files or `.env`; they use the same API and gates as the web app.

## Photos and serial numbers

- Originals are stored byte-for-byte, read-only, outside any public folder, with a SHA-256 hash. They are only served
  to a signed-in user through authenticated routes and are never uploaded anywhere.
- Every photo is scanned locally (RapidOCR, four rotations). Serial-like text is covered with solid redaction blocks;
  a second OCR pass checks inside the blocks. The OCR text itself is never stored — only position, rotation, category
  and confidence.
- Photos with findings, dense engraving or no OCR available stay "needs check" until a person looks and confirms.
  OCR alone is never treated as proof.
- Cloud AI gate (`CLOUD_AI_IMAGE_POLICY=reviewed_only`): only redacted working copies of checked dial/side/clasp frames
  can be sent. Casebacks, movements, documents and any unchecked frame are blocked in code, whatever the caller asks.
  AI backgrounds default to a text-only prompt, so no photo is sent at all.
- The fidelity gate re-checks that redaction blocks are still present in every render.
- Only approved final renders are ever uploaded to public storage (Cloudflare R2), under the listing's SKU. When the
  watch is sold or withdrawn the studio deletes them again (if a delete fails, the Activity log says so and names the
  folder to remove by hand).
- GPS/location EXIF is never copied into the database, working copies, renders, draft packs or uploads. (The untouched
  original keeps whatever the camera wrote, which is why originals never leave the computer.)

## Publishing safeguards

- Approvals are bound to a hash of the exact images, facts, house terms and copy. Any change clears the affected
  approvals automatically (with the reason recorded). The publish endpoint and the publish job both re-check the
  approval hash before anything is sent.
- Live publishing is a separate per-platform switch that is only available after a successful connection test.
- Simulated results are labelled, use `simulation.invalid` links, and are never counted as live.
- The studio never reports a watch as removed everywhere while a manual action is still open.

## Records

- Every write is in the Activity log with who (user, or agent + Telegram user), what, when and the affected watch.
- Approval records keep the content hash and a snapshot of what was approved.
- AI usage is logged with model, tokens, image count and estimated cost.

## Reporting a problem

If you find something that bypasses these rules, stop publishing (switch live publishing off in Publishing →
Platforms), rotate the affected credentials, and fix it with a test before switching back on.
