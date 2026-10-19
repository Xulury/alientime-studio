"""Uploads: validation, original preservation, hashing, duplicates, orientation, inbox ingestion."""
from __future__ import annotations

import hashlib
import io
import os
import stat

from PIL import Image

from app.core.storage import resolve
from tests.conftest import small_watch_jpeg
from tests.fixtures import synthetic as S


def test_upload_preserves_original_bytes_read_only(studio):
    w = studio.create_watch()
    data = small_watch_jpeg()
    r = studio.upload(w["id"], [("front.jpg", data)])
    assert r["added"] == 1 and r["jobs"]  # processing queued automatically
    from app.db.base import SessionLocal
    from app.db.models import Asset

    db = SessionLocal()
    a = db.query(Asset).one()
    original = resolve(a.original_path)
    assert original.read_bytes() == data
    assert a.original_sha256 == hashlib.sha256(data).hexdigest()
    assert not (os.stat(original).st_mode & stat.S_IWUSR), "original must be read-only"
    assert resolve(a.working_path) != original
    # the API serves the exact original bytes, privately
    resp = studio.get(f"/api/assets/{a.id}/image/original")
    assert resp.content == data and "no-store" in resp.headers["cache-control"]
    db.close()


def test_original_never_overwritten():
    import pytest

    from app.core.storage import write_original

    import tempfile
    from pathlib import Path

    p = Path(tempfile.mkdtemp()) / "x.jpg"
    write_original(p, b"one")
    with pytest.raises(FileExistsError):
        write_original(p, b"two")
    assert p.read_bytes() == b"one"


def test_invalid_and_unsupported_uploads(studio):
    w = studio.create_watch()
    gif = io.BytesIO()
    Image.new("RGB", (800, 800), "white").save(gif, "GIF")
    r = studio.upload(w["id"], [("notes.txt", b"hello world, not an image" * 10), ("anim.gif", gif.getvalue()),
                                ("empty.jpg", b"")])
    statuses = [x["status"] for x in r["results"]]
    assert statuses == ["rejected", "rejected", "rejected"] and r["added"] == 0
    assert "GIF" in r["results"][1]["message"]


def test_png_and_webp_supported_and_transparency_becomes_mask(studio):
    w = studio.create_watch()
    webp = io.BytesIO()
    S.draw_watch((900, 1300), seed=3).save(webp, "WEBP", quality=90)
    name, png = S.png_with_transparency()
    r = studio.upload(w["id"], [("a.webp", webp.getvalue()), (name, png)])
    assert r["added"] == 2
    assets = studio.ok(studio.get(f"/api/watches/{w['id']}"))["assets"]
    png_asset = next(a for a in assets if a["filename"] == name)
    assert png_asset["has_mask"]


def test_size_limit(studio, monkeypatch):
    from app.config import reset_settings_cache

    monkeypatch.setenv("MAX_UPLOAD_MB", "1")
    reset_settings_cache()
    w = studio.create_watch()
    big = S._jpeg(S.draw_watch((3000, 4000), background="wood"), 98)
    assert len(big) > 1024 * 1024
    r = studio.upload(w["id"], [("big.jpg", big)])
    assert r["results"][0]["status"] == "rejected" and "MB" in r["results"][0]["message"]


def test_duplicate_detection(studio):
    w = studio.create_watch()
    other = studio.create_watch(model="RM 11-03")
    data = small_watch_jpeg(seed=4)
    studio.upload(w["id"], [("a.jpg", data)])
    r = studio.upload(w["id"], [("again.jpg", data)])
    assert r["results"][0]["status"] == "duplicate"
    # re-encoded copy of the same frame → near-duplicate warning
    im = Image.open(io.BytesIO(data))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=70)
    r = studio.upload(w["id"], [("recompressed.jpg", buf.getvalue())])
    assert r["results"][0]["status"] == "added"
    assert any("almost identical" in x for x in r["results"][0]["warnings"])
    # same file on another watch is allowed but flagged
    r = studio.upload(other["id"], [("a.jpg", data)])
    assert any("also attached" in x for x in r["results"][0]["warnings"])


def test_exif_orientation_applied_to_working_copy(studio):
    w = studio.create_watch()
    img = S.draw_watch((600, 1000), seed=5)
    ex = Image.Exif()
    ex[0x0112] = 6  # rotate 90° CW on display
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=ex.tobytes())
    studio.upload(w["id"], [("rotated.jpg", buf.getvalue())])
    from app.db.base import SessionLocal
    from app.db.models import Asset

    db = SessionLocal()
    a = db.query(Asset).one()
    assert (a.working_width, a.working_height) == (1000, 600)
    assert a.exif_summary.get("Orientation") == "6"
    db.close()


def test_local_inbox_ingestion(studio):
    w = studio.create_watch()
    inbox = studio.data_dir / "inbox"
    (inbox / w["sku"]).mkdir(parents=True)
    (inbox / w["sku"] / "IMG_1.jpg").write_bytes(small_watch_jpeg(seed=7))
    (inbox / "MB&F HM6").mkdir()
    (inbox / "MB&F HM6" / "DSC_1.jpg").write_bytes(small_watch_jpeg(seed=8))
    (inbox / "loose.jpg").write_bytes(small_watch_jpeg(seed=9))
    listing = studio.ok(studio.get("/api/inbox"))
    items = listing["sources"][0]["items"]
    assert len(items) == 3
    matched = next(i for i in items if i["group"] == w["sku"])
    assert matched["matched_watch"]["id"] == w["id"]
    r = studio.ok(studio.post("/api/inbox/import", json={"source": "local_inbox", "refs": [i["ref"] for i in items]}))
    statuses = sorted(x["status"] for x in r["results"])
    assert statuses == ["added", "added", "needs_watch"]
    assert len(r["created_watches"]) == 1
    assert not (inbox / w["sku"] / "IMG_1.jpg").exists()
    assert list((inbox / "_imported").rglob("IMG_1.jpg"))
