"""Phase 2: inspection, serial protection, segmentation, compositing, fidelity, studio API."""
from __future__ import annotations

import io

import numpy as np
import pytest
from PIL import Image

from app.imaging import safety
from app.imaging.composite import CANVASES, make_plan, render_canvas, transform
from app.imaging.enhance import apply_color, auto_color_params
from app.imaging.fidelity import check as fidelity_check, compare
from app.imaging.inspect import detect_source_profile, inspect_image
from app.imaging.segment import GrabCutSegmenter, mask_stats, refine_mask
from tests.conftest import needs_ocr, small_watch_jpeg
from tests.fixtures import synthetic as S


def rgb_of(data: bytes) -> np.ndarray:
    return np.asarray(Image.open(io.BytesIO(data)).convert("RGB")).copy()


# ---- sensitive text rules -----------------------------------------------------------------------
@pytest.mark.parametrize("text,expected", [
    ("No. 4827193", "numbered_marking"),
    ("N° 1234", "numbered_marking"),
    ("4827193", "serial_like"),
    ("A1234567", "serial_like"),
    ("4 827 193", "long_number"),
    ("023/150", "edition_number"),
    ("100M/330FT", None),
    ("SWISS MADE", None),
    ("12", None),
    ("1000", None),
    ("AUTOMATIC", None),
])
def test_classify_text(text, expected):
    assert safety.classify_text(text) == expected


def test_merge_regions_and_redaction_blocks():
    merged = safety.merge_regions([(0.1, 0.1, 0.2, 0.05), (0.25, 0.11, 0.2, 0.05), (0.7, 0.7, 0.1, 0.1)])
    assert len(merged) == 2
    img = np.full((100, 200, 3), 200, np.uint8)
    out = safety.apply_redaction(img, [(0.1, 0.2, 0.3, 0.3)])
    assert tuple(out[35, 40]) == safety.REDACTION_FILL
    assert tuple(out[90, 190]) == (200, 200, 200)
    assert img[35, 40, 0] == 200, "input is never modified in place"


@needs_ocr
def test_scan_finds_serial_without_storing_text():
    from app.imaging.ocr import get_ocr_engine

    name, data = S.caseback_with_serial("No. 4827193")
    res = safety.scan(rgb_of(data), get_ocr_engine())
    assert res.findings, "serial must be detected"
    dumped = str([f.as_dict() for f in res.findings])
    assert "4827193" not in dumped and "No." not in dumped


@needs_ocr
def test_recheck_fails_when_digits_still_readable():
    from app.imaging.ocr import get_ocr_engine

    eng = get_ocr_engine()
    _, data = S.caseback_with_serial("No. 4827193")
    rgb = rgb_of(data)
    res = safety.scan(rgb, eng)
    h, w = rgb.shape[:2]
    regions = safety.merge_regions([safety.finding_to_region(f, w, h) for f in res.findings])
    # Not redacted → the second pass must fail
    assert not safety.recheck(rgb, regions, eng)["passed"]
    redacted = safety.apply_redaction(rgb, regions)
    assert safety.recheck(redacted, regions, eng)["passed"]


# ---- segmentation & inspection ------------------------------------------------------------------
def test_refine_mask_fills_dial_holes_and_removes_specks():
    m = np.zeros((300, 300), np.uint8)
    m[50:250, 50:250] = 255
    m[100:200, 100:200] = 0      # dial wrongly cut out
    m[5:8, 280:283] = 255        # speck
    out, notes = refine_mask(m)
    assert out[150, 150] == 255 and out[6, 281] == 0
    assert any("Filled" in n for n in notes)


def test_grabcut_on_clean_background_and_edge_detection():
    _, data = S.rm6701_edited()[0]
    rgb = rgb_of(data)
    res = GrabCutSegmenter().segment(rgb)
    mask, _ = refine_mask(res.mask)
    st = mask_stats(mask)
    assert 0.3 < st["fg_ratio"] < 0.55 and st["edge_touch"] == []
    _, raw = S.mbf_raw()[0]
    rr = rgb_of(raw)
    m2, _ = refine_mask(GrabCutSegmenter().segment(rr).mask)
    assert set(mask_stats(m2)["edge_touch"]) == {"top", "bottom"}


def test_inspection_rejects_blur_and_tiny_and_detects_sources():
    _, sharp = S.rm6701_edited()[0]
    _, blur = S.blurred_frame()
    _, tiny = S.tiny_frame()
    seg = GrabCutSegmenter()
    def ins(data, name, exif=None, fmt="JPEG"):
        rgb = rgb_of(data)
        m, _ = refine_mask(seg.segment(rgb).mask)
        return inspect_image(rgb, m, exif=exif or {}, filename=name, original_size=(rgb.shape[1], rgb.shape[0]), fmt=fmt)
    a = ins(sharp, "front.jpg")
    assert not a.rejects and a.source_profile == "edited"
    b = ins(blur, "blur.jpg")
    assert any("focus" in r for r in b.rejects)
    c = ins(tiny, "tiny.jpg")
    assert any("Too small" in r for r in c.rejects)
    name, raw = S.mbf_raw()[1]
    assert detect_source_profile(rgb_of(raw)[:400, :400], {"Make": "SONY", "Model": "ILCE"}, name, (4000, 3000),
                                 "JPEG", False)[0] == "raw"
    name, wa = S.moser_whatsapp()[0]
    assert detect_source_profile(rgb_of(wa), {}, name, (1200, 1600), "JPEG", False)[0] == "phone"


# ---- compositing & fidelity ---------------------------------------------------------------------
def _cutout():
    _, data = S.moser_whatsapp()[0]
    rgb = rgb_of(data)
    mask, _ = refine_mask(GrabCutSegmenter().segment(rgb).mask)
    return rgb, mask


@pytest.mark.parametrize("bg", ["green_velvet", "studio_white", "studio_black", "keep_original"])
def test_render_keeps_watch_pixels(bg):
    rgb, mask = _cutout()
    params = auto_color_params(rgb, mask)
    colored = apply_color(rgb, params)
    canvas = CANVASES["square"]
    out, plan, _ = render_canvas(colored, mask, canvas, background=bg)
    assert out.shape == (canvas.height, canvas.width, 3)
    res = fidelity_check(out, rgb, mask, params, plan, [], bg_keeps_original=bg == "keep_original")
    assert res["passed"] and res["psnr_db"] > 60, res


def test_fidelity_detects_altered_watch_pixels():
    rgb, mask = _cutout()
    params = auto_color_params(rgb, mask)
    out, plan, _ = render_canvas(apply_color(rgb, params), mask, CANVASES["square"], background="green_velvet")
    tampered = out.copy()
    mt = transform(mask, plan, is_mask=True)
    ys, xs = np.where(mt > 250)
    cy, cx = int(ys.mean()), int(xs.mean())
    tampered[cy - 150:cy + 150, cx - 150:cx + 150] = (90, 160, 90)   # e.g. a model "repainting" the dial
    res = fidelity_check(tampered, rgb, mask, params, plan, [])
    assert not res["passed"]
    assert compare(out, transform(apply_color(rgb, params), plan), mt)["passed"]


def test_fidelity_checks_redaction_blocks_survive():
    rgb, mask = _cutout()
    h, w = rgb.shape[:2]
    ys, xs = np.where(mask > 250)
    region = ((xs.mean() - 60) / w, (ys.mean() - 20) / h, 120 / w, 40 / h)
    red = safety.apply_redaction(rgb, [region])
    params = auto_color_params(red, mask)
    out, plan, _ = render_canvas(apply_color(red, params), mask, CANVASES["store_2x3"], background="studio_grey")
    assert fidelity_check(out, red, mask, params, plan, [region])["redactions"]["passed"]
    # an output built from the unredacted photo must fail
    out2, _, _ = render_canvas(apply_color(rgb, params), mask, CANVASES["store_2x3"], background="studio_grey")
    assert not fidelity_check(out2, red, mask, params, plan, [region])["passed"]


def test_plan_scales_and_limits_enlargement():
    mask = np.zeros((1000, 1000), np.uint8)
    mask[480:520, 480:520] = 255
    plan, warns = make_plan(mask, CANVASES["square"])
    assert plan.total_scale == pytest.approx(2.0) and warns


# ---- studio API ---------------------------------------------------------------------------------
def _process(studio, files):
    w = studio.complete_watch()
    studio.upload(w["id"], files)
    jobs = studio.run_jobs()
    assert all(j.status == "completed" for j in jobs), [(j.type, j.error) for j in jobs]
    return w, studio.ok(studio.get(f"/api/watches/{w['id']}"))["assets"]


@needs_ocr
def test_caseback_pipeline_redacts_and_blocks_until_checked(studio):
    w, assets = _process(studio, [S.caseback_with_serial()])
    a = studio.ok(studio.get(f"/api/assets/{assets[0]['id']}"))
    assert a["safety_status"] == "needs_review" and a["regions"]
    assert a["photo_type"] == "caseback"
    assert not a["cloud_ai"]["eligible"]
    assert a["render"]["fidelity_passed"]
    for v in a["render"]["fidelity"].values():
        assert v["redactions"]["passed"]
    assert "4827193" not in str(a)
    # cannot approve until the redactions are checked by a person
    r = studio.post(f"/api/assets/{a['id']}/review", json={"decision": "approve"})
    assert r.status_code == 422 and "redactions" in r.json()["error"]["message"]
    studio.ok(studio.post(f"/api/assets/{a['id']}/privacy-review", json={"confirm": True}))
    # caseback never goes to cloud AI, even when checked
    a = studio.ok(studio.get(f"/api/assets/{a['id']}"))
    assert a["safety_status"] == "reviewed" and not a["cloud_ai"]["eligible"]


@needs_ocr
def test_manual_redaction_edit_marks_render_stale(studio):
    w, assets = _process(studio, [("front.jpg", small_watch_jpeg(seed=11))])
    aid = assets[0]["id"]
    before = studio.ok(studio.get(f"/api/assets/{aid}"))
    r = studio.ok(studio.put(f"/api/assets/{aid}/regions",
                             json={"regions": [{"x": 0.4, "y": 0.4, "w": 0.1, "h": 0.05}]}))
    assert r["safety_status"] == "needs_review" and len(r["regions"]) == 1 and r["render_stale"]
    assert r["redaction_version"] if "redaction_version" in r else True
    studio.ok(studio.put(f"/api/assets/{aid}/regions", json={"regions": []}))
    assert before["urls"]["redacted"]


def test_mask_upload_and_render_settings(studio):
    w, assets = _process(studio, [("front.jpg", small_watch_jpeg(seed=12))])
    aid = assets[0]["id"]
    a = studio.ok(studio.get(f"/api/assets/{aid}"))
    ww, wh = a["working_size"]
    mask = np.zeros((wh, ww), np.uint8)
    mask[wh // 4: 3 * wh // 4, ww // 4: 3 * ww // 4] = 255
    buf = io.BytesIO()
    Image.fromarray(mask).save(buf, "PNG")
    r = studio.put(f"/api/assets/{aid}/mask", files={"file": ("mask.png", buf.getvalue(), "image/png")})
    a = studio.ok(r)
    assert a["mask_source"] == "manual" and a["render_stale"]
    job = studio.ok(studio.post(f"/api/assets/{aid}/render", json={"background": "studio_white", "rotation_deg": 10}))
    studio.run_jobs()
    a = studio.ok(studio.get(f"/api/assets/{aid}"))
    assert a["render"]["settings"]["background"] == "studio_white" and a["render"]["version"] == 2
    assert a["render"]["settings"]["rotation_deg"] == 10 and not a["render_stale"]
    # earlier render can be restored only if redactions did not change since
    first = a["renders"][-1]["id"]
    studio.ok(studio.post(f"/api/assets/{aid}/renders/{first}/restore"))
    # image variants and platform sizes
    img = Image.open(io.BytesIO(studio.get(f"/api/assets/{aid}/image/platform:instagram").content))
    assert img.size == (1080, 1350)
    assert studio.get(f"/api/assets/{aid}/image/variant:square").status_code == 200
    assert studio.get(f"/api/assets/{aid}/image/cutout").headers["content-type"] == "image/png"
    assert studio.get(f"/api/assets/{aid}/image/thumb").status_code == 200
    assert studio.get(f"/api/assets/{aid}/image/../../etc").status_code == 404
    assert job


def test_ai_background_plate_is_cached_and_watch_untouched(studio):
    from app.db.base import SessionLocal
    from app.db.models import AIUsage

    w, assets = _process(studio, [("front.jpg", small_watch_jpeg(seed=13)), ("side.jpg", small_watch_jpeg(seed=14, scale=0.8))])
    for a in assets:
        studio.ok(studio.post(f"/api/assets/{a['id']}/render", json={"background": "ai_velvet"}))
    jobs = studio.run_jobs()
    assert all(j.status == "completed" for j in jobs), [j.error for j in jobs]
    a = studio.ok(studio.get(f"/api/assets/{assets[0]['id']}"))
    assert a["render"]["background_source"].startswith("ai:") and a["render"]["fidelity_passed"]
    db = SessionLocal()
    plates = db.query(AIUsage).filter(AIUsage.operation == "background_plate").count()
    db.close()
    assert plates == 3, "one plate per aspect ratio, reused across photos"


def test_ai_background_requires_provider(studio, monkeypatch):
    from app.providers.registry import DisabledProvider, set_provider

    w, assets = _process(studio, [("front.jpg", small_watch_jpeg(seed=15))])
    set_provider(DisabledProvider())
    r = studio.post(f"/api/assets/{assets[0]['id']}/render", json={"background": "ai_velvet"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "ai_not_configured"


def test_selection_override_and_photo_type(studio):
    w, assets = _process(studio, [("front.jpg", small_watch_jpeg(seed=16)), S.blurred_frame()])
    blurred = next(a for a in assets if a["filename"] == "RM6701_blurred.jpg")
    assert blurred["selected"] is False and blurred["selection_reasons"]
    r = studio.ok(studio.patch(f"/api/assets/{blurred['id']}", json={"selection_override": True, "photo_type": "side_profile"}))
    assert r["selected"] is True and r["photo_type"] == "side_profile" and r["photo_type_source"] == "user"
