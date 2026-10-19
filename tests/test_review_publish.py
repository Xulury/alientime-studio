"""Phase 4: versioned approvals, invalidation, publishing gates, simulation, manual channels, lifecycle sync."""
from __future__ import annotations

import io
import json
import zipfile

import httpx
import pytest

from tests.conftest import small_watch_jpeg

TERMS = {"terms": "All sales final.", "disclaimer": "Brand names are for identification only.", "licence": "",
         "contact": "", "cta": "Message us to arrange a viewing.", "channel_overrides": {}}


def ready_watch(studio, channels=("shopify", "instagram", "carousell", "chrono24"), **facts):
    studio.ok(studio.put("/api/settings/fixed_blocks", json=TERMS))
    studio.ok(studio.put("/api/settings/channels", json={"enabled": list(channels)}))
    w = studio.complete_watch(**facts)
    studio.upload(w["id"], [("front.jpg", small_watch_jpeg(seed=31)), ("side.jpg", small_watch_jpeg(seed=32, scale=0.8))])
    jobs = studio.run_jobs()
    assert all(j.status == "completed" for j in jobs), [j.error for j in jobs]
    studio.ok(studio.post(f"/api/watches/{w['id']}/privacy-review", json={"confirm": True}))
    studio.ok(studio.post(f"/api/watches/{w['id']}/copy/generate", json={"mode": "template"}))
    return w


def approve_all(studio, w):
    return studio.ok(studio.post(f"/api/watches/{w['id']}/approvals", json={"scope": "package"}))


def test_channel_cannot_be_approved_before_images(studio):
    w = ready_watch(studio)
    r = studio.post(f"/api/watches/{w['id']}/approvals", json={"scope": "channel", "target": "shopify"})
    assert r.status_code == 422 and any("Approve the images" in b for b in r.json()["error"]["details"]["blockers"])


def test_package_approval_and_invalidation_on_edits(studio):
    w = ready_watch(studio)
    r = approve_all(studio, w)
    rd = r["readiness"]
    assert rd["package"]["approved"] and all(c["approved"] for c in rd["channels"])
    assert all(i["approved"] for i in rd["images"])
    assert studio.ok(studio.get(f"/api/watches/{w['id']}"))["watch"]["status"] == "approved"
    # non-material edit keeps approvals
    studio.ok(studio.patch(f"/api/watches/{w['id']}", json={"internal_notes": "call client"}))
    assert studio.ok(studio.get(f"/api/watches/{w['id']}/review"))["readiness"]["package"]["approved"]
    # material edit (price) invalidates channel + package approvals, with a reason
    studio.ok(studio.patch(f"/api/watches/{w['id']}", json={"price_sgd": 279000}))
    rd = studio.ok(studio.get(f"/api/watches/{w['id']}/review"))["readiness"]
    assert not rd["package"]["approved"] and not any(c["approved"] for c in rd["channels"])
    assert all(i["approved"] for i in rd["images"]), "image approvals are unaffected by a price change"
    hist = studio.ok(studio.get(f"/api/watches/{w['id']}/approvals"))["items"]
    assert any(a["status"] == "invalidated" and "price_sgd" in (a["invalidated_reason"] or "") for a in hist)
    assert studio.ok(studio.get(f"/api/watches/{w['id']}"))["watch"]["status"] == "awaiting_review"
    # stale copy must be regenerated before it can be approved again
    r = studio.post(f"/api/watches/{w['id']}/approvals", json={"scope": "channel", "target": "shopify"})
    assert r.status_code == 422 and any("Facts changed" in b for b in r.json()["error"]["details"]["blockers"])
    studio.ok(studio.post(f"/api/watches/{w['id']}/copy/generate", json={"mode": "template"}))
    approve_all(studio, w)
    # editing copy invalidates only that channel
    studio.ok(studio.put(f"/api/watches/{w['id']}/copy/carousell", json={"title": "Richard Mille RM 67-01 titanium"}))
    rd = studio.ok(studio.get(f"/api/watches/{w['id']}/review"))["readiness"]
    states = {c["key"]: c["approved"] for c in rd["channels"]}
    assert states == {"shopify": True, "instagram": True, "carousell": False, "chrono24": True}
    # re-rendering a photo invalidates that image and every channel using it
    aid = rd["images"][0]["asset_id"]
    studio.ok(studio.post(f"/api/assets/{aid}/render", json={"background": "studio_grey"}))
    studio.run_jobs()
    rd = studio.ok(studio.get(f"/api/watches/{w['id']}/review"))["readiness"]
    assert not rd["images"][0]["approved"] and not any(c["approved"] for c in rd["channels"])


def test_gallery_change_invalidates(studio):
    w = ready_watch(studio)
    approve_all(studio, w)
    rd = studio.ok(studio.get(f"/api/watches/{w['id']}/review"))["readiness"]
    ids = [i["asset_id"] for i in rd["images"]]
    studio.ok(studio.put(f"/api/watches/{w['id']}/gallery", json={"asset_ids": list(reversed(ids)), "hero_asset_id": ids[-1]}))
    assert not studio.ok(studio.get(f"/api/watches/{w['id']}/review"))["readiness"]["package"]["approved"]


def test_publish_requires_approval(studio):
    w = ready_watch(studio)
    r = studio.ok(studio.post(f"/api/watches/{w['id']}/publish", json={"channels": ["shopify", "carousell"]}))
    assert {x["status"] for x in r["results"]} == {"blocked"}
    assert any("Copy not approved." in b for b in r["results"][0]["blockers"])
    assert studio.post("/api/publish").status_code in (404, 405)


def test_simulated_publish_is_never_counted_as_live(studio):
    w = ready_watch(studio)
    approve_all(studio, w)
    r = studio.ok(studio.post(f"/api/watches/{w['id']}/publish", json={"channels": ["shopify", "instagram", "chrono24"]}))
    assert all(x["status"] == "queued" and x["mode"] == "simulation" for x in r["results"]), r
    again = studio.ok(studio.post(f"/api/watches/{w['id']}/publish", json={"channels": ["shopify"]}))
    assert again["results"][0]["job_id"] == r["results"][0]["job_id"], "same content → same job (idempotent)"
    jobs = studio.run_jobs()
    assert all(j.status == "completed" for j in jobs), [j.error for j in jobs]
    rd = studio.ok(studio.get(f"/api/watches/{w['id']}/review"))["readiness"]
    shop = next(c for c in rd["channels"] if c["key"] == "shopify")
    assert shop["listing"]["status"] == "simulated" and shop["listing"]["external_url"].startswith("https://simulation.invalid/")
    d = studio.ok(studio.get("/api/dashboard"))["counts"]
    assert d["published_listings"] == 0 and d["simulated_listings"] == 3
    assert studio.ok(studio.get(f"/api/watches/{w['id']}"))["watch"]["status"] == "approved"
    ov = studio.ok(studio.get("/api/publishing/overview"))
    assert len(ov["simulated"]) == 3 and ov["published"] == []
    feed = studio.get("/api/publishing/chrono24/feed.csv").text
    assert w["sku"] in feed and "internal_id" in feed.splitlines()[0]


def test_content_changed_after_request_is_refused(studio):
    w = ready_watch(studio)
    approve_all(studio, w)
    studio.ok(studio.post(f"/api/watches/{w['id']}/publish", json={"channels": ["shopify"]}))
    studio.ok(studio.put(f"/api/watches/{w['id']}/copy/shopify", json={"title": "Richard Mille RM 67-01 edited"}))
    jobs = studio.run_jobs()
    assert jobs[0].status == "failed" and "changed after approval" in jobs[0].error
    rd = studio.ok(studio.get(f"/api/watches/{w['id']}/review"))["readiness"]
    shop = next(c for c in rd["channels"] if c["key"] == "shopify")
    assert shop["listing"]["status"] == "failed" and shop["listing"]["last_error"]


def test_failure_is_recorded_and_retryable(studio, monkeypatch):
    from app.config import reset_settings_cache

    monkeypatch.setenv("MOCK_PUBLISH_FAIL_CHANNELS", "instagram")
    reset_settings_cache()
    w = ready_watch(studio)
    approve_all(studio, w)
    studio.ok(studio.post(f"/api/watches/{w['id']}/publish", json={"channels": ["instagram"]}))
    jobs = studio.run_jobs(include_delayed=True)
    assert jobs[-1].status == "failed"
    ov = studio.ok(studio.get("/api/publishing/overview"))
    assert ov["failures"] and "Simulated failure" in ov["failures"][0]["last_error"]
    d = studio.ok(studio.get("/api/dashboard"))["counts"]
    assert d["failed"] >= 1


def test_manual_channel_flow_and_sold_propagation(studio):
    w = ready_watch(studio)
    approve_all(studio, w)
    r = studio.ok(studio.post(f"/api/watches/{w['id']}/publish", json={"channels": ["carousell", "shopify"]}))
    task_id = next(x for x in r["results"] if x["channel"] == "carousell")["task_id"]
    studio.run_jobs()
    tasks = studio.ok(studio.get("/api/manual-tasks"))["items"]
    assert tasks[0]["kind"] == "post" and "Carousell" in tasks[0]["instructions"]
    assert studio.post(f"/api/manual-tasks/{task_id}/complete", json={"url": "javascript:alert(1)"}).status_code == 400
    studio.ok(studio.post(f"/api/manual-tasks/{task_id}/complete", json={"url": "https://www.carousell.sg/p/123"}))
    detail = studio.ok(studio.get(f"/api/watches/{w['id']}"))
    assert detail["watch"]["status"] == "published"
    assert studio.ok(studio.get("/api/dashboard"))["counts"]["published_listings"] == 1
    # cannot archive while listed
    assert studio.delete(f"/api/watches/{w['id']}").status_code == 400
    # sold → internal update now, API channel job queued, manual checklist created, honest message
    r = studio.ok(studio.post(f"/api/watches/{w['id']}/status", json={"action": "sold"}))
    assert r["watch"]["status"] == "sold"
    assert r["sync"]["automatic"] == 1 and r["sync"]["manual"] == 1
    assert "not yet updated everywhere" in r["sync"]["message"]
    studio.run_jobs()
    tasks = studio.ok(studio.get(f"/api/manual-tasks?watch_id={w['id']}"))["items"]
    sold_task = next(t for t in tasks if t["kind"] == "mark_sold")
    rd = studio.ok(studio.get(f"/api/watches/{w['id']}/review"))["readiness"]
    states = {c["key"]: c["listing"]["status"] for c in rd["channels"] if c["listing"]}
    assert states["shopify"] == "sold" and states["carousell"] == "manual_posted"
    studio.ok(studio.post(f"/api/manual-tasks/{sold_task['id']}/complete", json={}))
    rd = studio.ok(studio.get(f"/api/watches/{w['id']}/review"))["readiness"]
    assert {c["key"]: c["listing"]["status"] for c in rd["channels"] if c["listing"]}["carousell"] == "sold"
    # publishing a sold watch is refused
    assert studio.post(f"/api/watches/{w['id']}/publish", json={"channels": ["shopify"]}).status_code == 422


def test_reserve_and_available_cycle(studio):
    w = ready_watch(studio)
    approve_all(studio, w)
    studio.ok(studio.post(f"/api/watches/{w['id']}/publish", json={"channels": ["shopify"]}))
    studio.run_jobs()
    r = studio.ok(studio.post(f"/api/watches/{w['id']}/status", json={"action": "reserved"}))
    assert r["sync"]["automatic"] == 1
    studio.run_jobs()
    r = studio.ok(studio.post(f"/api/watches/{w['id']}/status", json={"action": "available"}))
    studio.run_jobs()
    rd = studio.ok(studio.get(f"/api/watches/{w['id']}/review"))["readiness"]
    assert next(c for c in rd["channels"] if c["key"] == "shopify")["listing"]["status"] == "simulated"


def test_draft_pack_preview_vs_approved(studio):
    w = ready_watch(studio)
    r = studio.get(f"/api/watches/{w['id']}/draft-pack?channels=carousell")
    assert r.status_code == 200 and "PREVIEW" in r.headers["content-disposition"]
    z = zipfile.ZipFile(io.BytesIO(r.content))
    names = z.namelist()
    assert any(n.startswith("carousell_PREVIEW_NOT_APPROVED/images/") for n in names)
    assert z.read("carousell_PREVIEW_NOT_APPROVED/text.txt").decode().startswith("PREVIEW")
    approve_all(studio, w)
    z = zipfile.ZipFile(io.BytesIO(studio.get(f"/api/watches/{w['id']}/draft-pack?channels=carousell").content))
    names = z.namelist()
    assert "carousell/instructions.txt" in names and "product.json" in names
    from PIL import Image

    img = Image.open(io.BytesIO(z.read([n for n in names if n.startswith("carousell/images/")][0])))
    assert img.size == (1080, 1080)
    assert "Status: APPROVED" in z.read("carousell/instructions.txt").decode()


def test_unconfigured_integrations_are_honest(studio):
    items = {i["name"]: i for i in studio.ok(studio.get("/api/integrations"))["items"]}
    for name in ("shopify", "instagram", "facebook_page", "chrono24", "ebay", "cloudflare_r2", "google_drive",
                 "google_sheets", "telegram", "whatsapp"):
        assert items[name]["state"] == "not_configured", name
    r = studio.ok(studio.post("/api/integrations/shopify/test"))
    assert r["state"] == "not_configured"
    assert studio.post("/api/integrations/shopify/live", json={"enabled": True}).status_code == 400
    plats = {p["key"]: p for p in studio.ok(studio.get("/api/publishing/overview"))["platforms"]}
    assert plats["shopify"]["mode"]["mode"] == "simulation" and plats["carousell"]["mode"]["mode"] == "manual"


def test_simulation_can_be_switched_off(studio, monkeypatch):
    from app.config import reset_settings_cache

    monkeypatch.setenv("ENABLE_SIMULATED_PUBLISHING", "false")
    reset_settings_cache()
    w = ready_watch(studio)
    approve_all(studio, w)
    r = studio.ok(studio.post(f"/api/watches/{w['id']}/publish", json={"channels": ["shopify"]}))
    assert r["results"][0]["status"] == "blocked"


# ---- live adapters against a fake HTTP transport -------------------------------------------------
def test_shopify_adapter_flow_with_token_refresh(monkeypatch, tmp_path):
    from app.config import reset_settings_cache
    from app.integrations import base as ib
    from app.publish.base import ListingRef, PublishPackage
    from app.publish.shopify import ShopifyAdapter, _token_cache

    monkeypatch.setenv("SHOPIFY_SHOP", "alientime")
    monkeypatch.setenv("SHOPIFY_CLIENT_ID", "cid")
    monkeypatch.setenv("SHOPIFY_CLIENT_SECRET", "secret")
    monkeypatch.setenv("STUDIO_DATA_DIR", str(tmp_path))
    reset_settings_cache()
    _token_cache.clear()
    seen = []

    def handler(request: httpx.Request):
        seen.append(request)
        if request.url.path == "/admin/oauth/access_token":
            body = dict(x.split("=") for x in request.content.decode().split("&"))
            assert body["grant_type"] == "client_credentials"
            return httpx.Response(200, json={"access_token": "shpat_test", "scope": "write_products", "expires_in": 86399})
        if request.url.host == "upload.example":
            return httpx.Response(201)
        q = json.loads(request.content)["query"]
        assert request.headers["x-shopify-access-token"] == "shpat_test"
        if "stagedUploadsCreate" in q:
            return httpx.Response(200, json={"data": {"stagedUploadsCreate": {"stagedTargets": [
                {"url": "https://upload.example/", "resourceUrl": "https://upload.example/r/1", "parameters": [{"name": "key", "value": "k"}]}],
                "userErrors": []}}})
        if "productSet" in q:
            v = json.loads(request.content)["variables"]
            assert v["input"]["status"] == "DRAFT" and v["input"]["variants"][0]["price"] == "285000.00"
            return httpx.Response(200, json={"data": {"productSet": {"product": {"id": "gid://shopify/Product/1",
                                                                                   "handle": "rm-67-01", "onlineStoreUrl": None,
                                                                                   "status": "DRAFT"}, "userErrors": []}}})
        if "productUpdate" in q:
            st = json.loads(request.content)["variables"]["product"]["status"]
            return httpx.Response(200, json={"data": {"productUpdate": {"product": {"id": "gid://shopify/Product/1", "status": st,
                                                                                     "handle": "rm-67-01", "onlineStoreUrl": None},
                                                                         "userErrors": []}}})
        if "publications" in q:
            return httpx.Response(200, json={"data": {"publications": {"nodes": [{"id": "gid://p/1", "name": "Online Store"}]}}})
        if "publishablePublish" in q:
            return httpx.Response(200, json={"data": {"publishablePublish": {"userErrors": []}}})
        return httpx.Response(400, json={"errors": "unexpected"})

    monkeypatch.setattr(ib, "HTTP_TRANSPORT", httpx.MockTransport(handler))
    img = tmp_path / "a.jpg"
    img.write_bytes(small_watch_jpeg())
    pkg = PublishPackage("w", "AT-RM-0001", "shopify", "Richard Mille RM 67-01", "Intro.\n\n- Reference: RM67-01",
                         {}, {"brand": "Richard Mille", "price_sgd": 285000}, [img], "hash")
    a = ShopifyAdapter()
    res = a.publish_new(pkg)
    assert res.status == "live" and res.external_url == "https://alientime.myshopify.com/products/rm-67-01"
    assert a.withdraw(ListingRef(res.external_id, res.external_url), "sold").status == "sold"
    assert sum(1 for r in seen if r.url.path == "/admin/oauth/access_token") == 1, "token cached"
    reset_settings_cache()


def test_instagram_requires_public_urls_and_cannot_delete(monkeypatch, tmp_path):
    from app.config import reset_settings_cache
    from app.integrations.base import IntegrationError, UnsupportedOperation
    from app.integrations import base as ib
    from app.publish.base import ListingRef, PublishPackage
    from app.publish.meta import InstagramAdapter

    monkeypatch.setenv("META_SYSTEM_USER_TOKEN", "EAAtoken")
    monkeypatch.setenv("IG_USER_ID_ALIENTIME_SG", "1789")
    reset_settings_cache()
    calls = []

    def handler(request: httpx.Request):
        calls.append((request.method, request.url.path))
        p = request.url.path
        if p.endswith("/media") and request.method == "POST":
            return httpx.Response(200, json={"id": f"c{len(calls)}"})
        if p.endswith("/media_publish"):
            return httpx.Response(200, json={"id": "m1"})
        if p.endswith("/m1"):
            return httpx.Response(200, json={"permalink": "https://instagram.com/p/x"})
        return httpx.Response(200, json={"status_code": "FINISHED"})

    monkeypatch.setattr(ib, "HTTP_TRANSPORT", httpx.MockTransport(handler))
    a = InstagramAdapter()
    a.poll_seconds = 0
    pkg = PublishPackage("w", "S", "instagram", "t", "caption", {}, {}, [], "h")
    with pytest.raises(IntegrationError):
        a.publish_new(pkg)
    pkg.public_image_urls = ["https://img.example/1.jpg", "https://img.example/2.jpg"]
    res = a.publish_new(pkg)
    assert res.external_url == "https://instagram.com/p/x"
    assert sum(1 for m, p in calls if m == "POST" and p.endswith("/media")) == 3  # 2 items + carousel
    with pytest.raises(UnsupportedOperation):
        a.withdraw(ListingRef("m1", None), "sold")
    reset_settings_cache()


# ---- permissions for agents ---------------------------------------------------------------------
def test_agent_tokens_are_scoped_and_admin_actions_fail_closed(studio, monkeypatch):
    from app.config import reset_settings_cache

    tok = studio.ok(studio.post("/api/tokens", json={"name": "hermes"}), 201)
    assert tok["token"].startswith("at_") and "token" not in studio.ok(studio.get("/api/tokens"))["items"][0]
    H = {"Authorization": f"Bearer {tok['token']}"}
    c = studio.client
    c.cookies.clear()
    w = c.post("/api/watches", json={"brand": "MB&F", "model": "HM6"}, headers=H)
    assert w.status_code == 201, "agents can create watches without CSRF (bearer token)"
    wid = w.json()["id"]
    assert c.post(f"/api/watches/{wid}/approvals", json={"scope": "package"}, headers=H).status_code == 403
    assert c.post(f"/api/watches/{wid}/status", json={"action": "sold"}, headers=H).status_code == 403
    assert c.put("/api/settings/pricing", json={"fx_sgd_usd": 1}, headers=H).status_code == 403
    assert c.get("/api/watches", headers={"Authorization": "Bearer at_wrong"}).status_code == 401
    # a token with the lifecycle scope still needs an allow-listed Telegram admin
    c.post("/api/auth/login", json={"username": "midas", "password": "correct horse battery staple"})
    st = c.get("/api/auth/state").json()
    tok2 = c.post("/api/tokens", json={"name": "hermes-admin", "scopes": ["read", "lifecycle"]},
                  headers={"x-csrf-token": st["csrf_token"]}).json()
    c.cookies.clear()
    H2 = {"Authorization": f"Bearer {tok2['token']}"}
    assert c.post(f"/api/watches/{wid}/status", json={"action": "reserved"}, headers=H2).status_code == 403
    monkeypatch.setenv("TELEGRAM_ADMIN_USERS", "111,222")
    reset_settings_cache()
    assert c.post(f"/api/watches/{wid}/status", json={"action": "reserved"},
                  headers={**H2, "X-Acting-User": "999"}).status_code == 403
    r = c.post(f"/api/watches/{wid}/status", json={"action": "reserved"}, headers={**H2, "X-Acting-User": "111"})
    assert r.status_code == 200
    acts = c.get(f"/api/watches/{wid}/activity", headers=H2).json()["items"]
    assert any("agent:hermes-admin for telegram:111" == a["actor"] for a in acts)
