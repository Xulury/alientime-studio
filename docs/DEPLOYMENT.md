# Deployment

The studio is a single Python web process (FastAPI + Uvicorn) with a background worker, a database and a private
data folder. It is built to run on one machine you control. **It is never exposed publicly by default** — it binds to
`127.0.0.1` and you choose how (and whether) to reach it from elsewhere.

## 1. What runs

| Piece | Default | Notes |
| --- | --- | --- |
| Web app + API | `uvicorn app.main:app --host 127.0.0.1 --port 8000` | Serves the built interface from `app/web` |
| Worker | Thread inside the web process (`WORKER_MODE=thread`) | Or `WORKER_MODE=external` + `python -m app.jobs.worker` as a second process |
| Database | SQLite at `data/studio.db` (WAL mode) | PostgreSQL via `DATABASE_URL` |
| Private files | `data/media/` (originals read-only, working copies, masks, renders), `data/exports/`, `data/feeds/`, `data/inbox/` | Never served publicly; images go through authenticated API routes |
| Migrations | Run automatically on start | `python -m app.cli migrate` to run by hand |

Jobs survive restarts: anything that was running when the process stopped is put back in the queue on start.

## 2. Shop Mac mini (recommended)

1. Install Python 3.12+ (`brew install python@3.12`) and clone/copy the project.
2. `python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
3. `cp .env.example .env`, set `STUDIO_ENV=production`, add your OpenAI key and any platform credentials.
4. Start once by hand to create the owner account: `uvicorn app.main:app --host 127.0.0.1 --port 8000`.
5. Keep it running with `launchd` — save as `~/Library/LaunchAgents/sg.alientime.studio.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>sg.alientime.studio</string>
  <key>WorkingDirectory</key><string>/Users/alientime/alien-time-listing-studio</string>
  <key>ProgramArguments</key><array>
    <string>/Users/alientime/alien-time-listing-studio/.venv/bin/uvicorn</string>
    <string>app.main:app</string><string>--host</string><string>127.0.0.1</string><string>--port</string><string>8000</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>/Users/alientime/Library/Logs/alien-time-studio.log</string>
  <key>StandardErrorPath</key><string>/Users/alientime/Library/Logs/alien-time-studio.log</string>
</dict></plist>
```

`launchctl load ~/Library/LaunchAgents/sg.alientime.studio.plist`

## 3. Windows PC

Double-click `start-studio.bat` (see the README). To start the studio automatically when you log on, create a Task
Scheduler task "At log on" that runs `D:\Alien-Time\alien-time-listing-studio\start-studio.bat` with the argument
`--no-browser`, and "Start in" set to the project folder. On a Mac, add `Start Studio.command` to
System Settings → General → Login Items instead.

## 4. Reaching it from your phone (optional)

Do not open a port on your router. Use **Cloudflare Tunnel + Cloudflare Access** so only your Google/email login can
reach the studio:

1. `cloudflared tunnel create alien-time-studio` and route a hostname (e.g. `studio.alientime.sg`) to
   `http://127.0.0.1:8000`.
2. In Cloudflare Zero Trust → Access → Applications, protect that hostname with a policy allowing only your email.
3. In `.env`: `STUDIO_BASE_URL=https://studio.alientime.sg`, `STUDIO_COOKIE_SECURE=true`.

The studio's own login still applies behind Access (two layers).

## 5. VPS / PostgreSQL (later)

- `pip install "psycopg[binary]"` and set `DATABASE_URL=postgresql+psycopg://user:pass@host/studio`.
- Use `WORKER_MODE=external` and run `python -m app.jobs.worker` as its own service (systemd).
- Put Caddy or nginx in front with HTTPS and keep Uvicorn on `127.0.0.1`.
- Store `STUDIO_DATA_DIR` on a disk that is backed up.
- The cutout model needs ~2–3 GB RAM while processing large raw photos; 4 GB minimum, 8 GB recommended.

## 6. Backups

`python -m app.cli backup` writes `backups/studio-<timestamp>.zip` with a consistent copy of the database and the
private media folder. Schedule it daily (launchd/Task Scheduler/cron) and copy the zips off the machine. Originals
are irreplaceable — back up `data/media/` even if you skip everything else.

## 7. Updating

1. `python -m app.cli backup`
2. Replace the code (keep `.env` and `data/`).
3. `pip install -r requirements.txt`
4. Restart. Migrations apply automatically; the old MVP database, if found, is backed up as
   `studio.mvp-backup-<timestamp>.db` and imported once.

## 8. Production checklist

- [ ] `STUDIO_ENV=production`, `STUDIO_COOKIE_SECURE=true` behind HTTPS
- [ ] Uvicorn bound to `127.0.0.1` only
- [ ] `.env` readable only by the studio's user (`chmod 600 .env`)
- [ ] OpenAI project monthly limit set in the OpenAI dashboard as well as `AI_MONTHLY_BUDGET_USD`
- [ ] Daily backups copied off the machine
- [ ] Live publishing switched on per platform only after a successful connection test
- [ ] Agent tokens limited to the scopes Hermes needs; `TELEGRAM_ADMIN_USERS` set to your own Telegram ID
