"""Phase 1: authentication, security controls, inventory CRUD, lifecycle, jobs, migrations."""
from __future__ import annotations

import sqlite3

import pytest

from tests.conftest import PASSWORD


# ---- authentication & security ------------------------------------------------------------------
def test_first_run_setup_then_login_logout(anon):
    st = anon.get("/api/auth/state").json()
    assert st["setup_required"] and not st["authenticated"]
    assert anon.post("/api/auth/setup", json={"username": "midas", "password": "short"}).status_code == 400
    r = anon.post("/api/auth/setup", json={"username": "midas", "password": PASSWORD})
    assert r.status_code == 200
    assert "at_session" in r.cookies or anon.cookies.get("at_session")
    # second setup is refused
    assert anon.post("/api/auth/setup", json={"username": "other", "password": PASSWORD}).status_code == 403
    csrf = r.json()["csrf_token"]
    assert anon.post("/api/auth/logout", headers={"x-csrf-token": csrf}).status_code == 200
    assert anon.get("/api/watches").status_code == 401
    assert anon.post("/api/auth/login", json={"username": "midas", "password": "wrong"}).status_code == 401
    r = anon.post("/api/auth/login", json={"username": "MIDAS", "password": PASSWORD})
    assert r.status_code == 200 and r.json()["authenticated"]
    assert anon.get("/api/watches").status_code == 200


def test_password_hash_is_not_plaintext(studio):
    from app.db.base import SessionLocal
    from app.db.models import User

    db = SessionLocal()
    u = db.query(User).first()
    assert u.password_hash.startswith("scrypt$") and PASSWORD not in u.password_hash
    db.close()


def test_csrf_required_for_cookie_writes(studio):
    r = studio.client.post("/api/watches", json={"brand": "Rolex", "model": "Daytona"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf_failed"
    r = studio.client.post("/api/watches", json={"brand": "Rolex", "model": "Daytona"}, headers={"x-csrf-token": "nope"})
    assert r.status_code == 403
    assert studio.post("/api/watches", json={"brand": "Rolex", "model": "Daytona"}).status_code == 201


def test_lockout_after_repeated_failures(anon, monkeypatch):
    anon.post("/api/auth/setup", json={"username": "midas", "password": PASSWORD})
    anon.cookies.clear()
    codes = [anon.post("/api/auth/login", json={"username": "midas", "password": "bad"}).status_code for _ in range(9)]
    assert 401 in codes and 429 in codes
    # even the right password is refused while locked
    assert anon.post("/api/auth/login", json={"username": "midas", "password": PASSWORD}).status_code == 429


def test_change_password(studio):
    r = studio.post("/api/auth/password", json={"current_password": "wrong", "new_password": "another long pass"})
    assert r.status_code == 400
    r = studio.post("/api/auth/password", json={"current_password": PASSWORD, "new_password": "another long pass 2"})
    assert r.status_code == 200


def test_security_headers_and_safe_errors(studio):
    r = studio.get("/api/dashboard")
    assert r.headers["x-frame-options"] == "DENY"
    assert "default-src 'self'" in r.headers["content-security-policy"]
    assert r.headers["cache-control"] == "no-store"
    r = studio.get("/api/watches/does-not-exist")
    assert r.status_code == 404 and r.json()["error"]["message"] == "Watch not found."
    r = studio.post("/api/watches", json={"brand": "", "model": "x"})
    assert r.status_code == 422 and "error" in r.json()


def test_health_is_public_but_minimal(anon):
    assert anon.get("/api/health").json() == {"status": "ok"}


def test_mvp_disabled_publisher_still_fails_closed():
    from app.integrations.contracts import DisabledPublisher, IntegrationNotConfigured, ListingPackage

    with pytest.raises(IntegrationNotConfigured):
        DisabledPublisher("shopify").publish(ListingPackage("w", 1, "shopify", "text", ()))


# ---- inventory ----------------------------------------------------------------------------------
def test_watch_crud_with_auto_sku(studio):
    a = studio.create_watch()
    b = studio.create_watch(model="RM 11-03")
    assert a["sku"] == "AT-RM-0001" and b["sku"] == "AT-RM-0002"
    c = studio.create_watch(brand="MB&F", model="HM6", sku="custom-1")
    assert c["sku"] == "CUSTOM-1"
    assert studio.post("/api/watches", json={"brand": "X", "model": "Y", "sku": "custom-1"}).status_code == 409
    w = studio.ok(studio.patch(f"/api/watches/{a['id']}", json={"price_sgd": 285000, "price_usd": 210000,
                                                                "box_papers": "full_set", "custody": "in_hand",
                                                                "is_consignment": True, "consignor_name": "Client A"}))
    assert w["price_sgd"] == 285000 and w["is_consignment"] and w["availability"] == "available"
    detail = studio.ok(studio.get(f"/api/watches/{a['id']}"))
    assert detail["watch"]["consignor_name"] == "Client A"
    assert studio.patch(f"/api/watches/{a['id']}", json={"price_sgd": -5}).status_code == 422
    assert studio.patch(f"/api/watches/{a['id']}", json={"custody": "somewhere"}).status_code == 422
    assert studio.ok(studio.delete(f"/api/watches/{b['id']}"))["archived"]
    assert {i["sku"] for i in studio.ok(studio.get("/api/watches"))["items"]} == {"AT-RM-0001", "CUSTOM-1"}
    assert studio.ok(studio.get("/api/watches?archived=true"))["total"] == 1
    studio.ok(studio.post(f"/api/watches/{b['id']}/restore"))
    assert studio.ok(studio.get("/api/watches"))["total"] == 3


def test_search_filter_sort(studio):
    studio.create_watch(price_sgd=100)
    studio.create_watch(brand="MB&F", model="HM6", price_sgd=300, reference="HM6-TI")
    studio.create_watch(brand="H. Moser & Cie.", model="Endeavour", price_sgd=200)
    r = studio.ok(studio.get("/api/watches?q=hm6"))
    assert [i["brand"] for i in r["items"]] == ["MB&F"]
    r = studio.ok(studio.get("/api/watches?sort=price&order=asc"))
    assert [i["price_sgd"] for i in r["items"]] == [100, 200, 300]
    r = studio.ok(studio.get("/api/watches?brand=mb%26f"))
    assert r["total"] == 1
    assert "H. Moser & Cie." in r["brands"]
    assert studio.ok(studio.get("/api/watches/next-sku?brand=H.%20Moser%20%26%20Cie."))["sku"] == "AT-HMC-0002"


def test_lifecycle_transitions_and_audit(studio):
    w = studio.create_watch()
    r = studio.ok(studio.post(f"/api/watches/{w['id']}/status", json={"action": "reserved", "note": "deposit"}))
    assert r["watch"]["status"] == "reserved" and r["availability"] == "reserved"
    assert "not listed on any channel" in r["sync"]["message"]
    assert studio.post(f"/api/watches/{w['id']}/status", json={"action": "reserved"}).status_code == 400
    r = studio.ok(studio.post(f"/api/watches/{w['id']}/status", json={"action": "available"}))
    assert r["watch"]["status"] == "draft"
    studio.ok(studio.post(f"/api/watches/{w['id']}/status", json={"action": "sold"}))
    assert studio.post(f"/api/watches/{w['id']}/status", json={"action": "available"}).status_code == 400
    r = studio.ok(studio.post(f"/api/watches/{w['id']}/status", json={"action": "reopen"}))
    assert r["watch"]["status"] == "draft"
    acts = [e["action"] for e in studio.ok(studio.get(f"/api/watches/{w['id']}/activity"))["items"]]
    assert acts.count("status_changed") == 4 and "watch_created" in acts


def test_dashboard_counts(studio):
    a = studio.create_watch()
    b = studio.create_watch(model="RM 11-03")
    studio.post(f"/api/watches/{b['id']}/status", json={"action": "sold"})
    d = studio.ok(studio.get("/api/dashboard"))
    assert d["counts"]["total"] == 2 and d["counts"]["available"] == 1 and d["counts"]["sold"] == 1
    assert d["recent_activity"]
    assert a


# ---- jobs ---------------------------------------------------------------------------------------
def test_jobs_idempotency_retry_cancel_and_restart_recovery(studio):
    from app.db.base import SessionLocal
    from app.db.models import Job
    from app.jobs import queue

    calls = {"n": 0}

    @queue.handler("test_flaky", "Flaky test job")
    def flaky(ctx):
        calls["n"] += 1
        ctx.progress(50, "half way")
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return {"message": "ok"}

    db = SessionLocal()
    j1 = queue.enqueue(db, "test_flaky", idempotency_key="k1", max_attempts=3)
    j2 = queue.enqueue(db, "test_flaky", idempotency_key="k1")
    assert j1.id == j2.id
    db.commit()
    studio.run_jobs()
    db.expire_all()
    assert db.get(Job, j1.id).status == "pending"  # retry scheduled with back-off
    studio.run_jobs(include_delayed=True)
    db.expire_all()
    j = db.get(Job, j1.id)
    assert j.status == "completed" and j.attempts == 2 and j.progress == 100
    # cancel a pending job
    j3 = queue.enqueue(db, "test_flaky")
    db.commit()
    assert studio.ok(studio.post(f"/api/jobs/{j3.id}/cancel"))["status"] == "cancelled"
    # a job left running by a crash is resumed at start-up
    j4 = queue.enqueue(db, "test_flaky")
    j4.status = "running"
    j4.attempts = 1
    db.commit()
    assert queue.recover_all_running(db) == 1
    db.expire_all()
    assert db.get(Job, j4.id).status == "pending"
    # failed job can be retried from the API
    j5 = queue.enqueue(db, "unknown_type")
    db.commit()
    studio.run_jobs()
    db.expire_all()
    assert db.get(Job, j5.id).status == "failed"
    assert studio.ok(studio.post(f"/api/jobs/{j5.id}/retry"))["status"] == "pending"
    db.close()


# ---- migrations ---------------------------------------------------------------------------------
def test_legacy_mvp_database_is_migrated(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient

    from app.config import reset_settings_cache
    from app.db.base import reset_engine

    data = tmp_path / "legacy"
    media = data / "media" / "abc123"
    media.mkdir(parents=True)
    from tests.conftest import small_watch_jpeg

    img = media / "a1_original.jpg"
    img.write_bytes(small_watch_jpeg())
    con = sqlite3.connect(data / "studio.db")
    con.executescript("""
    CREATE TABLE watches (id TEXT PRIMARY KEY, sku TEXT NOT NULL UNIQUE, brand TEXT NOT NULL, model TEXT NOT NULL,
      reference TEXT, year TEXT, price TEXT, currency TEXT DEFAULT 'SGD', condition TEXT, set_details TEXT, custody TEXT,
      notes TEXT, status TEXT NOT NULL DEFAULT 'draft', revision INTEGER NOT NULL DEFAULT 1, approved_revision INTEGER,
      created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
    CREATE TABLE assets (id TEXT PRIMARY KEY, watch_id TEXT NOT NULL, filename TEXT NOT NULL, original TEXT NOT NULL,
      prepared TEXT, created_at TEXT NOT NULL);
    CREATE TABLE channel_drafts (watch_id TEXT NOT NULL, channel TEXT NOT NULL, copy TEXT NOT NULL, revision INTEGER NOT NULL,
      PRIMARY KEY (watch_id,channel));
    CREATE TABLE audit (id INTEGER PRIMARY KEY AUTOINCREMENT, watch_id TEXT, action TEXT NOT NULL, detail TEXT, at TEXT NOT NULL);
    CREATE TABLE publish_jobs (watch_id TEXT NOT NULL,channel TEXT NOT NULL,status TEXT NOT NULL DEFAULT 'not_connected',
      external_url TEXT,PRIMARY KEY(watch_id,channel));
    """)
    con.execute("INSERT INTO watches VALUES ('abc123','AT001','Richard Mille','RM 67-01','','2021','SGD 285,000','SGD',"
                "'Excellent','Full set','in_hand','note','reserved',3,NULL,'2026-10-01T00:00:00+00:00','2026-10-01T00:00:00+00:00')")
    con.execute("INSERT INTO assets VALUES ('a1','abc123','IMG_1.jpg',?,NULL,'2026-10-01T00:00:00+00:00')", (str(img),))
    con.execute("INSERT INTO channel_drafts VALUES ('abc123','whatsapp','*RM 67-01*',3)")
    con.execute("INSERT INTO audit(watch_id,action,detail,at) VALUES ('abc123','created','Watch created','2026-10-01T00:00:00+00:00')")
    con.commit()
    con.close()
    monkeypatch.setenv("STUDIO_DATA_DIR", str(data))
    reset_settings_cache()
    reset_engine()
    from app.main import app as fastapi_app

    with TestClient(fastapi_app) as c:
        c.post("/api/auth/setup", json={"username": "midas", "password": PASSWORD})
        items = c.get("/api/watches").json()["items"]
        assert len(items) == 1 and items[0]["sku"] == "AT001" and items[0]["price_sgd"] == 285000
        assert items[0]["status"] == "reserved"
        d = c.get(f"/api/watches/{items[0]['id']}").json()
        assert len(d["assets"]) == 1
        copy = c.get(f"/api/watches/{items[0]['id']}/copy").json()
        assert any(ch["key"] == "whatsapp_groups" and ch["copy"] for ch in copy["channels"])
    assert list(data.glob("studio.mvp-backup-*.db")), "a backup of the MVP database is kept"
    con = sqlite3.connect(data / "studio.db")
    assert con.execute("SELECT count(*) FROM legacy_watches").fetchone()[0] == 1
    con.close()
    reset_engine()
    reset_settings_cache()


def test_web_files_have_correct_types_even_with_a_broken_os_mime_table(studio):
    """Windows often maps .js to text/plain in the registry; browsers then refuse to run the interface."""
    import mimetypes

    from app.main import WEB_DIR

    js = next((WEB_DIR / "assets").glob("*.js"), None)
    css = next((WEB_DIR / "assets").glob("*.css"), None)
    if js is None or css is None:
        import pytest

        pytest.skip("web interface not built")
    mimetypes.add_type("text/plain", ".js")  # simulate the broken Windows registry entry
    mimetypes.add_type("text/plain", ".css")
    try:
        r = studio.client.get(f"/assets/{js.name}")
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/javascript")
        assert "immutable" in r.headers["cache-control"]
        again = studio.client.get(f"/assets/{js.name}", headers={"if-none-match": r.headers.get("etag", "x")})
        assert again.status_code == 200 and again.headers["content-type"].startswith("text/javascript"), \
            "a stale cached copy with the wrong type must be replaced, not confirmed with 304"
        r = studio.client.get(f"/assets/{css.name}")
        assert r.headers["content-type"].startswith("text/css")
        r = studio.client.get("/favicon.svg")
        assert r.headers["content-type"].startswith("image/svg+xml")
        r = studio.client.get("/inventory")
        assert r.headers["content-type"].startswith("text/html")
    finally:
        from app.main import register_mime_types

        register_mime_types()
