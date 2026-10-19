"""Phase 5: Hermes command interface against the real API (scoped token, admin allow-list)."""
from __future__ import annotations

import json

from app.hermes.cli import run
from tests.conftest import small_watch_jpeg


def agent(studio, scopes=None):
    body = {"name": "hermes"} if scopes is None else {"name": "hermes", "scopes": scopes}
    tok = studio.ok(studio.post("/api/tokens", json=body), 201)["token"]
    return tok


def cli(studio, token, *argv):
    import os

    os.environ["STUDIO_AGENT_TOKEN"] = token
    try:
        code, out = run(list(argv), client=studio.client)
    finally:
        os.environ.pop("STUDIO_AGENT_TOKEN", None)
    json.dumps(out, default=str)  # output must always be JSON-serialisable
    return code, out


def test_cli_intake_process_facts_copy_review(studio, tmp_path, monkeypatch):
    token = agent(studio)
    studio.client.cookies.clear()
    photos = tmp_path / "photos"
    photos.mkdir()
    (photos / "a.jpg").write_bytes(small_watch_jpeg(seed=41))
    code, out = cli(studio, token, "intake", "--brand", "MB&F", "--model", "HM6", "--photos", str(photos))
    assert code == 0 and out["data"]["sku"] == "AT-MBF-0001" and out["data"]["uploads"][0]["status"] == "added"
    studio.run_jobs()
    code, out = cli(studio, token, "images", "--sku", "AT-MBF-0001")
    assert code == 0 and out["data"][0]["pipeline"] == "ready"
    code, out = cli(studio, token, "facts", "--sku", "AT-MBF-0001")
    assert any(i["severity"] == "blocker" for i in out["data"]["issues"])
    for field, value in (("price_sgd", "350,000"), ("condition", "excellent"), ("box_papers", "full_set"),
                         ("custody", "in_hand"), ("year", "2018"), ("calibre", "HM6 engine")):
        code, out = cli(studio, token, "set-fact", "--sku", "AT-MBF-0001", "--field", field, "--value", value)
        assert code == 0, out
    code, out = cli(studio, token, "copy", "--sku", "AT-MBF-0001", "--channels", "shopify,whatsapp_groups")
    assert code == 0 and all(c["errors"] == [] or c["channel"] for c in out["data"])
    code, out = cli(studio, token, "review", "--sku", "AT-MBF-0001")
    assert code == 0 and "channels" in out["data"]
    code, out = cli(studio, token, "request-approval", "--sku", "AT-MBF-0001")
    assert code == 0 and out["data"]["review_url"].endswith("/review")
    code, out = cli(studio, token, "status")
    assert code == 0 and out["data"]["counts"]["total"] == 1


def test_cli_cannot_approve_publish_or_sell_without_admin(studio, monkeypatch):
    from app.config import reset_settings_cache

    token = agent(studio, ["read", "intake", "approve", "publish", "lifecycle"])
    studio.client.cookies.clear()
    code, out = cli(studio, token, "intake", "--brand", "Rolex", "--model", "Daytona")
    sku = out["data"]["sku"]
    code, out = cli(studio, token, "sold", "--sku", sku, "--telegram-user", "123")
    assert code == 1 and out["status"] == 403 and "TELEGRAM_ADMIN_USERS" in out["error"]
    monkeypatch.setenv("TELEGRAM_ADMIN_USERS", "123")
    reset_settings_cache()
    code, out = cli(studio, token, "approve", "--sku", sku, "--package", "--telegram-user", "999")
    assert code == 1 and out["status"] == 403
    code, out = cli(studio, token, "approve", "--sku", sku, "--package", "--telegram-user", "123")
    assert code == 1 and out["status"] == 422 and "Blockers" in out["error"], "gates still apply to admins"
    code, out = cli(studio, token, "reserve", "--sku", sku, "--telegram-user", "123", "--note", "deposit")
    assert code == 0 and out["data"]["status"] == "reserved"


def test_cli_without_token_or_scope(studio):
    code, out = run(["status"])
    assert code == 1 and "STUDIO_AGENT_TOKEN" in out["error"]
    token = agent(studio, ["read"])
    studio.client.cookies.clear()
    code, out = cli(studio, token, "intake", "--brand", "Rolex", "--model", "Daytona")
    assert code == 1 and out["status"] == 403


def test_agent_cannot_mark_photos_checked_or_edit_redactions(studio):
    """The serial-number check is a human step: OCR alone is not proof, so agents may not sign it off."""
    w = studio.ok(studio.post("/api/watches", json={"brand": "MB&F", "model": "HM6"}), 201)
    up = studio.ok(studio.post(f"/api/watches/{w['id']}/assets",
                               files=[("files", ("a.jpg", small_watch_jpeg(seed=43), "image/jpeg"))]), 201)
    aid = up["results"][0]["asset_id"]
    studio.run_jobs()
    token = agent(studio, ["read", "intake", "process"])
    studio.client.cookies.clear()
    h = {"authorization": f"Bearer {token}"}
    r = studio.client.post(f"/api/assets/{aid}/privacy-review", json={"confirm": True}, headers=h)
    assert r.status_code == 403 and "person" in r.json()["error"]["message"]
    r = studio.client.post(f"/api/watches/{w['id']}/privacy-review", json={"confirm": True}, headers=h)
    assert r.status_code == 403
    r = studio.client.put(f"/api/assets/{aid}/regions", json={"regions": []}, headers=h)
    assert r.status_code == 403
    assert studio.client.get(f"/api/assets/{aid}", headers=h).json()["safety_reviewed_by"] is None
