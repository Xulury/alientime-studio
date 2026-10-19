"""Phase 3: OpenAI adapter, usage/budget, cloud-eligibility, listing intelligence, copy generation."""
from __future__ import annotations

import base64
import json
from types import SimpleNamespace

import pytest

from app.providers.base import BudgetExceeded, ProviderError
from app.providers.schemas import CopyDraft, ListingIntel, Mismatch, TaggingResult, strict_schema
from tests.conftest import small_watch_jpeg
from tests.fixtures import synthetic as S


# ---- OpenAI adapter (no network: a fake client stands in for the SDK) -----------------------------
class FakeResponses:
    def __init__(self, payload, usage=None):
        self.payload = payload
        self.usage = usage or {"input_tokens": 1200, "output_tokens": 300}
        self.calls = []

    def create(self, **kw):
        self.calls.append(kw)
        text = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return SimpleNamespace(output_text=text, usage=SimpleNamespace(model_dump=lambda: self.usage))


class FakeImages:
    def __init__(self):
        self.calls = []

    def generate(self, **kw):
        self.calls.append(kw)
        from app.providers.mock_provider import MockProvider

        png = MockProvider()._png(256, 256)
        return SimpleNamespace(data=[SimpleNamespace(b64_json=base64.b64encode(png).decode())],
                               usage=SimpleNamespace(model_dump=lambda: {"input_tokens": 50, "output_tokens": 4000,
                                                                         "input_tokens_details": {"text_tokens": 50, "image_tokens": 0}}))


def openai_with_fake(monkeypatch, payload, usage=None):
    from app.config import reset_settings_cache
    from app.providers.openai_provider import OpenAIProvider
    from app.providers.registry import set_provider

    monkeypatch.setenv("OPENAI_API_KEY", "sk-test-000000000000")
    reset_settings_cache()
    p = OpenAIProvider()
    fake = SimpleNamespace(responses=FakeResponses(payload, usage), images=FakeImages(),
                           models=SimpleNamespace(retrieve=lambda m: SimpleNamespace(id=m, owned_by="openai")))
    p._client = fake
    set_provider(p)
    return p, fake


def test_strict_schema_closes_objects():
    sch = strict_schema(ListingIntel)
    assert sch["additionalProperties"] is False and set(sch["required"]) == set(sch["properties"])
    brand = sch["properties"]["brand"]
    assert brand["additionalProperties"] is False and "$ref" not in json.dumps(sch)


def test_openai_structured_call_validates_and_logs_usage(studio, monkeypatch):
    from app.db.base import SessionLocal
    from app.db.models import AIUsage

    payload = {"title": "Richard Mille RM 67-01", "body": "Extra flat.", "caption": None, "hashtags": ["#RM"],
               "condition_line": None, "used_fact_keys": ["brand", "model"]}
    p, fake = openai_with_fake(monkeypatch, payload)
    out = p.structured("text", system="s", text="t", images=None, schema_name="listing_copy",
                       response_model=CopyDraft, operation="copy:test")
    assert out.title == "Richard Mille RM 67-01"
    call = fake.responses.calls[0]
    assert call["model"] == "gpt-6.1-sol" and call["text"]["format"]["strict"] is True and call["store"] is False
    db = SessionLocal()
    u = db.query(AIUsage).filter(AIUsage.operation == "copy:test").one()
    assert u.input_tokens == 1200 and u.cost_usd == pytest.approx((1200 * 2 + 300 * 10) / 1e6)
    db.close()
    st = studio.ok(studio.get("/api/settings/ai"))
    assert st["key_configured"] and "sk-test" not in json.dumps(st)


def test_openai_invalid_output_is_rejected(studio, monkeypatch):
    p, _ = openai_with_fake(monkeypatch, "not json at all")
    with pytest.raises(ProviderError):
        p.structured("text", system="s", text="t", images=None, schema_name="x", response_model=CopyDraft, operation="op")


def test_budget_blocks_calls(studio, monkeypatch):
    from app.config import reset_settings_cache

    monkeypatch.setenv("AI_DAILY_BUDGET_USD", "0.001")
    reset_settings_cache()
    p, _ = openai_with_fake(monkeypatch, {"title": "x", "body": None, "caption": None, "hashtags": [], "condition_line": None,
                                          "used_fact_keys": []}, usage={"input_tokens": 100000, "output_tokens": 100000})
    p.structured("text", system="s", text="t", images=None, schema_name="x", response_model=CopyDraft, operation="op")
    with pytest.raises(BudgetExceeded):
        p.structured("text", system="s", text="t", images=None, schema_name="x", response_model=CopyDraft, operation="op")


def test_openai_image_generation_and_connection_test(studio, monkeypatch):
    p, fake = openai_with_fake(monkeypatch, {})
    png = p.generate_image(prompt="velvet", width=1600, height=2400, operation="background_plate")
    assert png[:4] == b"\x89PNG"
    kw = fake.images.calls[0]
    assert kw["model"] == "gpt-image-2.5-sunburst" and kw["size"] == "1024x1536"
    rep = studio.ok(studio.post("/api/settings/ai/test"))
    assert rep["ok"] and rep["models"]["image"]["model"] == "gpt-image-2.5-sunburst"


# ---- cloud eligibility and AI tagging ------------------------------------------------------------
def _watch_with_photos(studio, files):
    w = studio.complete_watch()
    studio.upload(w["id"], files)
    studio.run_jobs()
    return w, studio.ok(studio.get(f"/api/watches/{w['id']}"))["assets"]


def test_only_checked_non_caseback_frames_reach_cloud_ai(studio, monkeypatch):
    from app.providers.mock_provider import MockProvider
    from app.providers.registry import set_provider

    sent = []

    class Spy(MockProvider):
        def structured(self, role, **kw):
            sent.append(len(kw.get("images") or []))
            return super().structured(role, **kw)

    set_provider(Spy())
    w, assets = _watch_with_photos(studio, [("front.jpg", small_watch_jpeg(seed=21)), S.caseback_with_serial()])
    # nothing checked yet → nothing is sent
    job = studio.ok(studio.post(f"/api/watches/{w['id']}/ai/tag"))
    studio.run_jobs()
    assert sent == [] or sent == [0]
    studio.ok(studio.post(f"/api/watches/{w['id']}/privacy-review", json={"confirm": True}))
    studio.ok(studio.post(f"/api/watches/{w['id']}/ai/tag"))
    jobs = studio.run_jobs()
    assert jobs[-1].status == "completed", jobs[-1].error
    assert sent[-1] == 1, "the caseback is never sent, even after checking"
    facts = studio.ok(studio.get(f"/api/watches/{w['id']}/facts"))
    assert any("Caseback" in k["reason"] for k in facts["ai"]["kept_local"])
    assert job


def test_listing_intel_creates_suggestions_never_applies_them(studio):
    from app.providers.mock_provider import MockProvider

    w, assets = _watch_with_photos(studio, [("front.jpg", small_watch_jpeg(seed=22))])
    studio.ok(studio.post(f"/api/watches/{w['id']}/privacy-review", json={"confirm": True}))
    studio.ok(studio.patch(f"/api/watches/{w['id']}", json={"reference": None}))
    MockProvider.forced_mismatch = Mismatch(field="model", inventory_value="RM 67-01", observed_value="RM 67-02",
                                            explanation="Dial layout looks like the 67-02")
    studio.ok(studio.post(f"/api/watches/{w['id']}/ai/intel"))
    jobs = studio.run_jobs()
    assert jobs[-1].status == "completed", jobs[-1].error
    f = studio.ok(studio.get(f"/api/watches/{w['id']}/facts"))
    assert any(i["code"] == "ai_mismatch" for i in f["issues"])
    assert any(i["code"] == "missing_reference" for i in f["issues"])
    rec = studio.ok(studio.get(f"/api/watches/{w['id']}"))["watch"]
    assert rec["model"] == "RM 67-01", "AI output never changes the record by itself"


def test_accepting_a_suggestion_records_provenance(studio):
    from app.db.base import SessionLocal
    from app.db.models import FactSuggestion

    w = studio.complete_watch()
    db = SessionLocal()
    db.add(FactSuggestion(watch_id=w["id"], field="dial", value="Skeletonised", source="ai_vision"))
    db.commit()
    sid = db.query(FactSuggestion).one().id
    db.close()
    studio.ok(studio.post(f"/api/watches/{w['id']}/suggestions/{sid}", json={"accept": True}))
    f = studio.ok(studio.get(f"/api/watches/{w['id']}/facts"))
    assert f["facts"]["dial"] == {"value": "Skeletonised", "label": "Dial", "source": "ai_vision_confirmed"}


# ---- facts --------------------------------------------------------------------------------------
def test_missing_and_conflicting_facts(studio):
    w = studio.create_watch()
    codes = {i["code"]: i["severity"] for i in studio.ok(studio.get(f"/api/watches/{w['id']}/facts"))["issues"]}
    assert codes["missing_price_sgd"] == "blocker" and codes["missing_condition"] == "blocker"
    assert codes["unknown_box_papers"] == "blocker" and codes["unknown_custody"] == "blocker"
    assert codes["missing_reference"] == "warning" and codes["missing_year"] == "warning"
    studio.ok(studio.put("/api/settings/pricing", json={"fx_sgd_usd": 0.75, "drift_tolerance_pct": 3}))
    studio.ok(studio.patch(f"/api/watches/{w['id']}", json={"price_sgd": 100000, "price_usd": 90000}))
    issues = studio.ok(studio.get(f"/api/watches/{w['id']}/facts"))["issues"]
    drift = next(i for i in issues if i["code"] == "fx_drift")
    assert drift["suggestion"] == "75000"
    studio.ok(studio.patch(f"/api/watches/{w['id']}", json={"is_consignment": True, "consignor_signoff": "pending"}))
    assert any(i["code"] == "consignor_signoff" for i in studio.ok(studio.get(f"/api/watches/{w['id']}/facts"))["issues"])


def test_approved_spec_records_feed_facts(studio):
    w = studio.complete_watch()
    s = studio.ok(studio.post("/api/specs", json={"brand": "Richard Mille", "model": "RM 67-01", "reference": "RM67-01 TI",
                                                   "calibre": "CRMA6", "case_size_mm": "38.7 × 47.5 mm"}), 201)
    assert "calibre" not in studio.ok(studio.get(f"/api/watches/{w['id']}/facts"))["facts"], "drafts are not used"
    studio.ok(studio.post(f"/api/specs/{s['id']}/approve"))
    f = studio.ok(studio.get(f"/api/watches/{w['id']}/facts"))
    assert f["facts"]["calibre"]["value"] == "CRMA6" and f["facts"]["calibre"]["source"].startswith("spec_table")


# ---- copy -----------------------------------------------------------------------------------------
def test_template_copy_for_all_eleven_channels(studio):
    studio.ok(studio.put("/api/settings/fixed_blocks", json={
        "terms": "All sales final. Payment by bank transfer.", "disclaimer": "Brand names are used for identification only.",
        "licence": "Second-Hand Dealer licence SHD-0000", "contact": "", "cta": "Message us to arrange a viewing.",
        "channel_overrides": {"instagram": {"cta": "DM us to arrange a viewing."}}}))
    w = studio.complete_watch(extra_facts={"auction_start_price": "200000"})
    r = studio.ok(studio.post(f"/api/watches/{w['id']}/copy/generate", json={"mode": "template"}))
    chans = {c["key"]: c for c in r["channels"]}
    assert len(chans) == 11
    for key, c in chans.items():
        assert c["copy"]["validation"]["errors"] == [], (key, c["copy"]["validation"])
    shop = chans["shopify"]["copy"]["text"]
    assert "All sales final. Payment by bank transfer." in shop and "SHD-0000" in shop
    assert "DM us to arrange a viewing." in chans["instagram"]["copy"]["text"]
    assert "Price: USD 209,000" in chans["ebay"]["copy"]["text"] or "USD" not in chans["ebay"]["copy"]["text"]
    assert chans["reddit_watchexchange"]["copy"]["sections"]["title"].startswith("[WTS]")
    assert len(chans["ebay"]["copy"]["sections"]["title"]) <= 80
    assert "In hand in Singapore" in chans["whatsapp_groups"]["copy"]["text"]
    assert "Starting bid: SGD 200,000" in chans["moda_auction"]["copy"]["text"]


def test_moda_needs_starting_bid_and_claims_are_enforced(studio):
    from app.providers.mock_provider import MockProvider

    w = studio.complete_watch(custody="consigned_offsite")
    r = studio.ok(studio.post(f"/api/watches/{w['id']}/copy/generate", json={"mode": "template", "channels": ["moda_auction"]}))
    errs = r["channels"][0]["copy"]["validation"]["errors"]
    assert any(e["section"] == "auction" for e in errs)
    MockProvider.forced_copy = {"title": "Richard Mille RM 67-01 — in hand, full set", "body": "Serviced in 2019. Unworn.",
                                "caption": None, "hashtags": ["#RM"], "condition_line": None, "used_fact_keys": []}
    studio.ok(studio.post(f"/api/watches/{w['id']}/copy/generate", json={"mode": "ai", "channels": ["shopify"]}))
    jobs = studio.run_jobs()
    assert jobs[-1].status == "completed", jobs[-1].error
    copy = next(c for c in studio.ok(studio.get(f"/api/watches/{w['id']}/copy"))["channels"] if c["key"] == "shopify")
    msgs = " | ".join(e["message"] for e in copy["copy"]["validation"]["errors"])
    assert "'in hand'" in msgs and "'unworn'" in msgs and "2019" in msgs
    assert copy["copy"]["generator"].startswith("ai:")


def test_edit_regenerate_section_and_revisions(studio):
    w = studio.complete_watch()
    studio.ok(studio.post(f"/api/watches/{w['id']}/copy/generate", json={"mode": "template", "channels": ["carousell"]}))
    c = studio.ok(studio.put(f"/api/watches/{w['id']}/copy/carousell", json={"body": "Collected in 2022 from the boutique."}))
    assert c["copy"]["version"] == 2 and c["copy"]["sources"]["body"] == "user"
    warns = c["copy"]["validation"]["warnings"]
    assert any("2022" in x["message"] for x in warns), "numbers you type are warnings, not errors"
    assert studio.put(f"/api/watches/{w['id']}/copy/carousell", json={"price": "cheap"}).status_code == 422
    r = studio.ok(studio.post(f"/api/watches/{w['id']}/copy/generate",
                              json={"mode": "template", "channels": ["carousell"], "section": "title"}))
    c3 = r["channels"][0]["copy"]
    assert c3["version"] == 3 and c3["sections"]["body"] == "Collected in 2022 from the boutique."
    revs = studio.ok(studio.get(f"/api/watches/{w['id']}/copy/carousell/revisions"))["items"]
    assert [r["version"] for r in revs] == [3, 2, 1]
    c4 = studio.ok(studio.post(f"/api/watches/{w['id']}/copy/carousell/revisions/{revs[-1]['id']}/restore"))
    assert c4["copy"]["version"] == 4 and "2022" not in c4["copy"]["text"]


def test_fixed_block_change_marks_copy_stale(studio):
    w = studio.complete_watch()
    studio.ok(studio.post(f"/api/watches/{w['id']}/copy/generate", json={"mode": "template", "channels": ["shopify"]}))
    studio.ok(studio.put("/api/settings/fixed_blocks", json={"terms": "New terms.", "disclaimer": "", "licence": "",
                                                             "contact": "", "cta": "x", "channel_overrides": {}}))
    copy = next(c for c in studio.ok(studio.get(f"/api/watches/{w['id']}/copy"))["channels"] if c["key"] == "shopify")
    assert any("House terms changed" in s for s in copy["copy"]["stale"])


def test_ai_copy_needs_provider(studio):
    from app.providers.registry import DisabledProvider, set_provider

    set_provider(DisabledProvider())
    w = studio.complete_watch()
    r = studio.post(f"/api/watches/{w['id']}/copy/generate", json={"mode": "ai"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "ai_not_configured"


def test_tagging_schema_roundtrip():
    TaggingResult.model_validate({"frames": [{"index": 0, "photo_type": "dial_front", "confidence": 0.9,
                                              "watch_fully_visible": True, "same_watch_as_others": "yes", "issues": []}],
                                  "different_watch_suspected": False, "notes": ""})
    with pytest.raises(Exception):
        TaggingResult.model_validate({"frames": [{"index": 0, "photo_type": "selfie"}]})
