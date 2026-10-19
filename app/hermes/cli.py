"""Hermes command interface: every command calls the studio's HTTP API and prints one JSON object.

    studio-agent <command> [options]          (or: python -m app.hermes.cli ...)

Environment:
    STUDIO_API_URL      default http://127.0.0.1:8000
    STUDIO_AGENT_TOKEN  an agent token created in Settings → Agent access (never a password)

The agent never touches the database or platform credentials. Sensitive commands (approve, publish,
reserve/sold/withdraw/available) must name the Telegram user who asked (--telegram-user); the studio
only accepts them for users listed in TELEGRAM_ADMIN_USERS and for tokens holding that permission.
Output: {"ok": true, "data": ...} or {"ok": false, "error": "...", "status": 403}. Exit code 0 / 1.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

import httpx

MARKET = {"reserve": "reserved", "sold": "sold", "withdraw": "withdrawn", "available": "available"}
# Facts stored as extra facts rather than inventory columns (kept here so this CLI only needs httpx).
SPEC_OR_EXTRA_FIELDS = {"calibre", "movement_type", "case_size_mm", "case_thickness_mm", "case_material", "dial", "bezel",
                        "crystal", "water_resistance", "power_reserve", "bracelet_strap", "functions", "warranty",
                        "service_history", "auction_start_price", "accessories", "papers_date"}


class CommandError(Exception):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class Api:
    def __init__(self, client: httpx.Client | None = None):
        url = os.environ.get("STUDIO_API_URL", "http://127.0.0.1:8000").rstrip("/")
        token = os.environ.get("STUDIO_AGENT_TOKEN", "")
        if client is None:
            if not token:
                raise CommandError("STUDIO_AGENT_TOKEN is not set.")
            client = httpx.Client(base_url=url, timeout=120)
        self.client = client
        self.headers = {"Authorization": f"Bearer {token}"} if token else {}

    def call(self, method: str, path: str, *, acting: str | None = None, **kw) -> Any:
        headers = {**self.headers, **kw.pop("headers", {})}
        if acting:
            headers["X-Acting-User"] = str(acting)
        r = self.client.request(method, path, headers=headers, **kw)
        if r.headers.get("content-type", "").startswith("application/json"):
            body = r.json()
        else:
            body = {"raw": r.text[:500]}
        if r.status_code >= 400:
            err = body.get("error", {}) if isinstance(body, dict) else {}
            msg = err.get("message") or str(body)[:300]
            details = err.get("details") or {}
            if details.get("blockers"):
                msg += " Blockers: " + "; ".join(details["blockers"][:10])
            raise CommandError(msg, r.status_code)
        return body

    def watch_id(self, sku: str) -> str:
        return self.call("GET", f"/api/watches/by-sku/{sku}")["id"]


def _photos(paths: list[str]) -> list[tuple[str, tuple[str, bytes, str]]]:
    files = []
    for p in paths:
        path = Path(p)
        items = sorted(x for x in path.iterdir() if x.is_file()) if path.is_dir() else [path]
        for f in items:
            if f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".heic"):
                files.append(("files", (f.name, f.read_bytes(), "application/octet-stream")))
    if not files:
        raise CommandError("No photos found at the given path(s).")
    return files


def summarise_review(r: dict) -> dict:
    rd = r["readiness"]
    return {
        "watch": {k: r["watch"][k] for k in ("sku", "brand", "model", "status", "availability")},
        "summary": rd["summary"],
        "fact_issues": [{"field": i["field"], "severity": i["severity"], "message": i["message"],
                         "suggestion": i.get("suggestion")} for i in rd["issues"]],
        "images": [{"file": i["filename"], "approved": i["approved"], "blockers": i["blockers"]} for i in rd["images"]],
        "channels": [{"channel": c["key"], "approved": c["approved"], "mode": c["mode"]["mode"],
                      "listing": c["listing"]["status"] if c["listing"] else None,
                      "blockers": c["publish_blockers"][:6]} for c in rd["channels"]],
        "package": rd["package"],
    }


def run(argv: list[str], client: httpx.Client | None = None) -> tuple[int, dict]:
    p = argparse.ArgumentParser(prog="studio-agent", description="Alien Time Listing Studio agent commands (JSON output)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("status", help="Dashboard counts and running jobs")
    s = sub.add_parser("inventory", help="List watches")
    s.add_argument("--status")
    s.add_argument("--q")
    s = sub.add_parser("intake", help="Create a watch and upload its photos")
    s.add_argument("--brand", required=True)
    s.add_argument("--model", required=True)
    s.add_argument("--sku")
    s.add_argument("--reference")
    s.add_argument("--photos", nargs="*", default=[])
    s = sub.add_parser("upload", help="Add photos to an existing watch")
    s.add_argument("--sku", required=True)
    s.add_argument("--photos", nargs="+", required=True)
    sub.add_parser("inbox", help="List photos waiting in the inbox(es)")
    s = sub.add_parser("inbox-import", help="Import inbox photos (folders named after a SKU attach to it)")
    s.add_argument("--source", default="local_inbox")
    s.add_argument("--sku", help="Attach every listed photo to this watch")
    for name, helptext in (("process", "Run the photo pipeline for unprocessed photos"),
                           ("images", "Photo status: kept/rejected, privacy, fidelity, review"),
                           ("facts", "Facts, missing items and suggestions"),
                           ("ai-tag", "AI photo tagging (only checked, eligible frames are sent)"),
                           ("ai-intel", "AI comparison of photos with the record (suggestions only)"),
                           ("review", "Readiness for approval and publishing"),
                           ("request-approval", "Notify the owner that approval is needed"),
                           ("tasks", "Open manual tasks (draft-pack posting, sold checklists)")):
        s = sub.add_parser(name, help=helptext)
        s.add_argument("--sku", required=name != "tasks")
    s = sub.add_parser("set-fact", help="Set a confirmed fact the owner gave you")
    s.add_argument("--sku", required=True)
    s.add_argument("--field", required=True)
    s.add_argument("--value", required=True)
    s = sub.add_parser("copy", help="Generate listing copy")
    s.add_argument("--sku", required=True)
    s.add_argument("--mode", choices=["template", "ai"], default="template")
    s.add_argument("--channels", help="Comma-separated channel keys (default: all enabled)")
    s = sub.add_parser("approve", help="Approve on behalf of an allow-listed admin")
    s.add_argument("--sku", required=True)
    s.add_argument("--channel")
    s.add_argument("--package", action="store_true")
    s.add_argument("--telegram-user", required=True)
    s.add_argument("--note")
    s = sub.add_parser("publish", help="Publish approved channels")
    s.add_argument("--sku", required=True)
    s.add_argument("--channels", required=True)
    s.add_argument("--simulate", action="store_true")
    s.add_argument("--telegram-user", required=True)
    for name in MARKET:
        s = sub.add_parser(name, help=f"Mark the watch {MARKET[name]} and update every channel")
        s.add_argument("--sku", required=True)
        s.add_argument("--telegram-user", required=True)
        s.add_argument("--note")
    s = sub.add_parser("jobs", help="Recent jobs")
    s.add_argument("--sku")
    s.add_argument("--status")
    s = sub.add_parser("wait", help="Wait for a job to finish")
    s.add_argument("--job", required=True)
    s.add_argument("--timeout", type=int, default=600)

    a = p.parse_args(argv)
    try:
        api = Api(client)
        data = dispatch(api, a)
        return 0, {"ok": True, "command": a.cmd, "data": data}
    except CommandError as e:
        return 1, {"ok": False, "command": a.cmd, "error": str(e), "status": e.status}
    except httpx.HTTPError as e:
        return 1, {"ok": False, "command": a.cmd, "error": f"Could not reach the studio: {e}"}


def dispatch(api: Api, a: argparse.Namespace) -> Any:
    cmd = a.cmd
    if cmd == "status":
        d = api.call("GET", "/api/dashboard")
        return {"counts": d["counts"], "running_jobs": [{"id": j["id"], "label": j["label"], "sku": j.get("sku"),
                                                          "progress": j["progress"]} for j in d["running_jobs"]]}
    if cmd == "inventory":
        params = {"page_size": 200}
        if a.status:
            params["status"] = a.status
        if a.q:
            params["q"] = a.q
        d = api.call("GET", "/api/watches", params=params)
        return [{k: w[k] for k in ("sku", "brand", "model", "reference", "status", "availability", "price_sgd",
                                   "photo_count")} for w in d["items"]]
    if cmd == "intake":
        body = {"brand": a.brand, "model": a.model}
        if a.sku:
            body["sku"] = a.sku
        if a.reference:
            body["reference"] = a.reference
        w = api.call("POST", "/api/watches", json=body)
        out = {"sku": w["sku"], "id": w["id"]}
        if a.photos:
            r = api.call("POST", f"/api/watches/{w['id']}/assets", files=_photos(a.photos))
            out["uploads"] = [{"file": x["filename"], "status": x["status"], "message": x["message"]} for x in r["results"]]
            out["jobs"] = [j["id"] for j in r["jobs"]]
        return out
    if cmd == "upload":
        wid = api.watch_id(a.sku)
        r = api.call("POST", f"/api/watches/{wid}/assets", files=_photos(a.photos))
        return {"uploads": [{"file": x["filename"], "status": x["status"], "message": x["message"]} for x in r["results"]],
                "jobs": [j["id"] for j in r["jobs"]]}
    if cmd == "inbox":
        return api.call("GET", "/api/inbox")
    if cmd == "inbox-import":
        listing = api.call("GET", "/api/inbox")
        src = next((s for s in listing["sources"] if s["source"] == a.source), None)
        if src is None or not src["items"]:
            return {"imported": 0, "message": "Nothing waiting."}
        body = {"source": a.source, "refs": [i["ref"] for i in src["items"]]}
        if a.sku:
            body["watch_id"] = api.watch_id(a.sku)
        return api.call("POST", "/api/inbox/import", json=body)
    if cmd == "tasks":
        params = {"status": "open"}
        if a.sku:
            params["watch_id"] = api.watch_id(a.sku)
        return [{k: t[k] for k in ("id", "sku", "channel_name", "kind", "title", "instructions")}
                for t in api.call("GET", "/api/manual-tasks", params=params)["items"]]
    if cmd == "jobs":
        params = {"limit": 50}
        if a.sku:
            params["watch_id"] = api.watch_id(a.sku)
        if a.status:
            params["status"] = a.status
        return [{k: j[k] for k in ("id", "label", "status", "progress", "message", "error", "sku")}
                for j in api.call("GET", "/api/jobs", params=params)["items"]]
    if cmd == "wait":
        deadline = time.monotonic() + a.timeout
        while True:
            j = api.call("GET", f"/api/jobs/{a.job}")
            if j["status"] in ("completed", "failed", "cancelled") or time.monotonic() > deadline:
                return j
            time.sleep(2)

    wid = api.watch_id(a.sku)
    if cmd == "process":
        return api.call("POST", f"/api/watches/{wid}/process")
    if cmd == "images":
        d = api.call("GET", f"/api/watches/{wid}")
        return [{"file": x["filename"], "pipeline": x["pipeline_status"], "kept": x["selected"],
                 "reasons": x["selection_reasons"], "type": x["photo_type"], "privacy": x["safety_status"],
                 "fidelity_passed": x["fidelity_passed"], "review": x["review_status"], "warnings": x["warnings"]}
                for x in d["assets"]]
    if cmd == "facts":
        d = api.call("GET", f"/api/watches/{wid}/facts")
        return {"facts": {k: v["value"] for k, v in d["facts"].items()}, "issues": d["issues"],
                "suggestions": d["suggestions"]}
    if cmd == "set-fact":
        if a.field in SPEC_OR_EXTRA_FIELDS:
            body = {"extra_facts": {**api.call("GET", f"/api/watches/{wid}")["watch"]["extra_facts"],
                                    a.field: {"value": a.value, "source": "telegram_owner"}}}
        else:
            value: Any = a.value
            if a.field in ("price_sgd", "price_usd"):
                value = float(a.value.replace(",", ""))
            body = {a.field: value}
        return api.call("PATCH", f"/api/watches/{wid}", json=body)
    if cmd == "ai-tag":
        return api.call("POST", f"/api/watches/{wid}/ai/tag")
    if cmd == "ai-intel":
        return api.call("POST", f"/api/watches/{wid}/ai/intel")
    if cmd == "copy":
        body: dict[str, Any] = {"mode": a.mode}
        if a.channels:
            body["channels"] = [c.strip() for c in a.channels.split(",") if c.strip()]
        d = api.call("POST", f"/api/watches/{wid}/copy/generate", json=body)
        if "job" in d:
            return {"job": d["job"]["id"], "message": "AI copy is being written; use `wait --job`."}
        return [{"channel": c["key"], "errors": c["copy"]["validation"]["errors"], "chars": len(c["copy"]["text"])}
                for c in d["channels"]]
    if cmd == "review":
        return summarise_review(api.call("GET", f"/api/watches/{wid}/review"))
    if cmd == "request-approval":
        return api.call("POST", f"/api/watches/{wid}/request-approval")
    if cmd == "approve":
        if not a.package and not a.channel:
            raise CommandError("Use --package or --channel.")
        body = {"scope": "package"} if a.package else {"scope": "channel", "target": a.channel}
        if a.note:
            body["note"] = a.note
        d = api.call("POST", f"/api/watches/{wid}/approvals", json=body, acting=a.telegram_user)
        return {"result": d["result"], "package_approved": d["readiness"]["package"]["approved"]}
    if cmd == "publish":
        body = {"channels": [c.strip() for c in a.channels.split(",") if c.strip()], "simulate": a.simulate}
        return api.call("POST", f"/api/watches/{wid}/publish", json=body, acting=a.telegram_user)
    if cmd in MARKET:
        d = api.call("POST", f"/api/watches/{wid}/status", json={"action": MARKET[cmd], "note": a.note},
                     acting=a.telegram_user)
        return {"status": d["watch"]["status"], "sync": d["sync"]}
    raise CommandError(f"Unknown command {cmd}")


def main() -> None:
    code, out = run(sys.argv[1:])
    print(json.dumps(out, indent=2, default=str))
    sys.exit(code)


if __name__ == "__main__":
    main()
