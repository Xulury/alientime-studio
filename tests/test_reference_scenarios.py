"""The three reference scenarios from the brief, end to end.

SYNTHETIC fixtures stand in for the client's image sets (see tests/fixtures/synthetic.py). They prove the
pipeline handles each source type; final visual acceptance with the real RM 67-01, MB&F and H. Moser sets is
still outstanding (docs/LIMITATIONS.md).
"""
from __future__ import annotations

import pytest

from tests.fixtures import synthetic as S

SCENARIOS = [
    ("Richard Mille", "RM 67-01", S.rm6701_edited, "edited", "keep_original"),
    ("MB&F", "HM6", S.mbf_raw, "raw", "green_velvet"),
    ("H. Moser & Cie.", "Endeavour Centre Seconds", S.moser_whatsapp, "phone", "green_velvet"),
]


@pytest.mark.slow
@pytest.mark.parametrize("brand,model,files,profile,background", SCENARIOS, ids=["rm6701-edited", "mbf-raw", "moser-whatsapp"])
def test_reference_scenario(studio, brand, model, files, profile, background):
    w = studio.complete_watch(brand=brand, model=model, reference=None)
    studio.upload(w["id"], files())
    jobs = studio.run_jobs()
    assert all(j.status == "completed" for j in jobs), [j.error for j in jobs]
    assets = studio.ok(studio.get(f"/api/watches/{w['id']}"))["assets"]
    assert assets
    for a in assets:
        full = studio.ok(studio.get(f"/api/assets/{a['id']}"))
        assert full["source_profile"] == profile, (a["filename"], full["source_profile_reasons"])
        assert full["selected"], (a["filename"], full["selection_reasons"])
        assert full["render"] and full["render"]["fidelity_passed"]
        assert full["render"]["settings"]["background"] == background
        assert set(full["render"]["variants"]) == {"store_2x3", "square", "social_4x5"}
    studio.ok(studio.post(f"/api/watches/{w['id']}/privacy-review", json={"confirm": True}))
    studio.ok(studio.post(f"/api/watches/{w['id']}/copy/generate", json={"mode": "template"}))
    studio.ok(studio.put("/api/settings/fixed_blocks", json={"terms": "Terms.", "disclaimer": "Disclaimer.", "licence": "",
                                                             "contact": "", "cta": "Message us.", "channel_overrides": {}}))
    studio.ok(studio.post(f"/api/watches/{w['id']}/copy/generate", json={"mode": "template"}))
    r = studio.post(f"/api/watches/{w['id']}/approvals", json={"scope": "package"})
    assert r.status_code == 422 and "MODA" in str(r.json()), "MODA needs a starting bid"
    # this piece is not going to auction: leave MODA out for this watch only
    from app.copywriter.channels import CHANNELS

    studio.ok(studio.put(f"/api/watches/{w['id']}/channels", json={"channels": [c for c in CHANNELS if c != "moda_auction"]}))
    r = studio.ok(studio.post(f"/api/watches/{w['id']}/approvals", json={"scope": "package"}))
    assert r["readiness"]["package"]["approved"]
