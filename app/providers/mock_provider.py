"""Deterministic mock provider for tests and offline demos.

It never contacts a network service and is labelled "Test mode" everywhere it appears. Outputs are
built only from the facts passed in, so they exercise the same validation as real responses.
"""
from __future__ import annotations

import io
import json
import re

from PIL import Image
from pydantic import BaseModel

from app.providers import usage as usage_mod
from app.providers.base import ConnectionReport, ImagePart
from app.providers.schemas import CopyDraft, FrameTag, ListingIntel, Mismatch, Observed, TaggingResult

FACTS_MARKER = "FACTS_JSON:"


def extract_facts(text: str) -> dict:
    m = re.search(re.escape(FACTS_MARKER) + r"\s*(\{.*?\})\s*(?:\n\n|$)", text, re.S)
    if not m:
        return {}
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return {}


class MockProvider:
    name = "mock"
    # Tests can set these to simulate the model noticing a mismatch.
    forced_mismatch: Mismatch | None = None
    forced_copy: dict | None = None

    @property
    def available(self) -> bool:
        return True

    def models(self) -> dict[str, str]:
        return {"vision": "mock-vision", "intel": "mock-intel", "text": "mock-text", "image": "mock-image"}

    def test_connection(self) -> ConnectionReport:
        return ConnectionReport(True, self.name, "Test mode: mock AI provider, no external calls.",
                                {r: {"model": m, "ok": True} for r, m in self.models().items()})

    def structured(self, role, *, system, text, images, schema_name, response_model: type[BaseModel], operation,
                   watch_id=None, job_id=None):
        facts = extract_facts(text)
        if response_model is TaggingResult:
            frames = []
            for i, img in enumerate(images or []):
                hint = re.search(r"local guess: ([a-z_]+)", img.label or "")
                t = hint.group(1) if hint and hint.group(1) != "unclassified" else "dial_front"
                frames.append(FrameTag(index=i, photo_type=t, confidence=0.7, watch_fully_visible=True,
                                       same_watch_as_others="yes", issues=[]))
            out = TaggingResult(frames=frames, different_watch_suspected=False, notes="Mock tagging.")
        elif response_model is ListingIntel:
            def ob(v):
                return Observed(value=v, confidence=0.6 if v else 0.0, evidence="mock" if v else "not visible")
            out = ListingIntel(
                brand=ob(facts.get("brand")), model=ob(facts.get("model")), reference_visible=ob(None),
                dial=ob(None), case_material=ob(None), bracelet_strap=ob(None), bezel=ob(None),
                complications=[], condition_observations=["No visible damage in the supplied photos (mock)."],
                mismatches=[self.forced_mismatch] if self.forced_mismatch else [],
                different_watch_suspected=False, notes="Mock analysis.")
        elif response_model is CopyDraft:
            if self.forced_copy is not None:
                out = CopyDraft(**self.forced_copy)
            else:
                name = " ".join(str(facts[k]) for k in ("brand", "model") if facts.get(k))
                ref = f" Ref. {facts['reference']}" if facts.get("reference") else ""
                bits = [f"{name}{ref}."]
                if facts.get("year"):
                    bits.append(f"Year {facts['year']}.")
                if facts.get("condition_notes"):
                    bits.append(str(facts["condition_notes"]).rstrip(".") + ".")
                out = CopyDraft(title=f"{name}{ref}".strip(), body=" ".join(bits), caption=" ".join(bits),
                                hashtags=["#" + re.sub(r"[^A-Za-z0-9]", "", facts.get("brand", "Watch"))],
                                condition_line=facts.get("condition_notes"), used_fact_keys=sorted(facts.keys()))
        else:  # pragma: no cover - unknown schema
            raise ValueError(f"mock provider cannot produce {response_model.__name__}")
        usage_mod.log_usage(self.name, self.models().get(role, "mock"), operation, cost=0.0,
                            image_in=len(images or []), watch_id=watch_id, job_id=job_id)
        return out

    def _png(self, width: int, height: int) -> bytes:
        from app.imaging.backgrounds import make_background

        arr = make_background("green_velvet", min(width, 768), min(height, 1152), seed=11)
        buf = io.BytesIO()
        Image.fromarray(arr).save(buf, "PNG")
        return buf.getvalue()

    def generate_image(self, *, prompt, width, height, operation, watch_id=None, job_id=None) -> bytes:
        usage_mod.log_usage(self.name, "mock-image", operation, cost=0.0, image_out=1, watch_id=watch_id, job_id=job_id)
        return self._png(width, height)

    def edit_image(self, *, image_png, mask_png, prompt, width, height, operation, watch_id=None, job_id=None) -> bytes:
        usage_mod.log_usage(self.name, "mock-image", operation, cost=0.0, image_in=1, image_out=1,
                            watch_id=watch_id, job_id=job_id)
        return self._png(width, height)


__all__ = ["MockProvider", "ImagePart", "FACTS_MARKER"]
