"""AI background plates.

Default mode ("plate"): the image model is asked for an *empty* backdrop from a text prompt only — no
photo of the watch is sent at all. One plate per style and aspect ratio is generated, cached and reused
across watches (consistent look, lower cost). "New background" generates a fresh variation.

Optional mode ("context_edit", AI_BACKGROUND_MODE=context_edit): the redacted, cloud-eligible frame and a
mask are sent so the model can match lighting. OpenAI documents that GPT Image treats a mask as guidance,
so the model's version of the watch is discarded: the watch area of its output is filled from the
surrounding generated background before our own watch pixels are composited on top.
"""
from __future__ import annotations

import hashlib
import io

import cv2
import numpy as np
from PIL import Image
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.settings_store import get_setting, set_setting
from app.core.storage import rel, resolve
from app.db.base import utcnow
from app.db.models import Asset, Watch
from app.imaging.io import decode_rgb, load_rgb

PROMPTS = {
    "ai_velvet": (
        "Product photography backdrop only: an empty, smooth deep green velvet surface filling the entire frame, "
        "soft diffused key light from the upper left with gentle falloff into darker edges, subtle natural velvet "
        "pile texture. No objects, no watch, no jewellery, no props, no text, no logos, no people. Photorealistic, "
        "neutral colour accuracy."
    ),
    "ai_studio": (
        "Product photography backdrop only: an empty seamless light grey studio sweep, soft even lighting with a "
        "gentle gradient toward the edges. No objects, no text, no logos, no people. Photorealistic."
    ),
}
ASPECT_SIZES = {"2x3": (1024, 1536), "1x1": (1024, 1024), "4x5": (1024, 1280)}


def aspect_key(w: int, h: int) -> str:
    r = w / h
    return min(ASPECT_SIZES, key=lambda k: abs(ASPECT_SIZES[k][0] / ASPECT_SIZES[k][1] - r))


def plates_dir():
    d = get_settings().media_dir / "_plates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def get_plate(db: Session, style: str, width: int, height: int, *, asset: Asset | None = None,
              watch: Watch | None = None, regenerate: bool = False) -> tuple[np.ndarray, dict]:
    from app.imaging.pipeline import cloud_eligible
    from app.providers.registry import get_provider

    if style not in PROMPTS:
        raise ValueError(f"Unknown AI background style: {style}")
    s = get_settings()
    provider = get_provider()
    if s.ai_background_mode == "context_edit" and asset is not None:
        ok, why = cloud_eligible(asset, s.cloud_ai_image_policy)
        if ok:
            return _context_plate(db, style, asset, provider)
    key = aspect_key(width, height)
    registry = get_setting(db, "ai_plates") or {}
    entry = (registry.get(style) or {}).get(key)
    if entry and not regenerate:
        p = resolve(entry.get("path"))
        if p and p.is_file():
            return load_rgb(p), {"source": f"ai:{entry.get('model')}:plate", "plate": entry}
    if not provider.available:
        from app.providers.base import ProviderUnavailable

        raise ProviderUnavailable("AI backgrounds need OpenAI. Add OPENAI_API_KEY or choose a local background.")
    pw, ph = ASPECT_SIZES[key]
    png = provider.generate_image(prompt=PROMPTS[style], width=pw, height=ph, operation="background_plate",
                                  watch_id=watch.id if watch else None)
    rgb = decode_rgb(png)
    digest = hashlib.sha256(png).hexdigest()[:16]
    path = plates_dir() / f"{style}_{key}_{digest}.png"
    Image.fromarray(rgb).save(path, "PNG")
    model = provider.models().get("image", "unknown")
    entry = {"path": rel(path), "model": model, "created_at": utcnow().isoformat(), "sha": digest,
             "prompt": PROMPTS[style]}
    registry.setdefault(style, {})[key] = entry
    set_setting(db, "ai_plates", registry, actor="system")
    db.flush()
    return rgb, {"source": f"ai:{model}:plate", "plate": entry}


def _context_plate(db: Session, style: str, asset: Asset, provider) -> tuple[np.ndarray, dict]:
    """Background generated around this frame; the model's watch pixels are removed afterwards."""
    from app.imaging.pipeline import current_mask, redacted_rgb

    red = redacted_rgb(asset)
    mask = current_mask(asset)
    h, w = red.shape[:2]
    scale = min(1.0, 1536 / max(h, w))
    sw, sh = int(w * scale) // 16 * 16, int(h * scale) // 16 * 16
    small = cv2.resize(red, (sw, sh), interpolation=cv2.INTER_AREA)
    m = cv2.resize(mask, (sw, sh), interpolation=cv2.INTER_LINEAR)
    keep = cv2.dilate((m > 20).astype(np.uint8) * 255, np.ones((15, 15), np.uint8))
    rgba_mask = np.dstack([np.zeros((sh, sw, 3), np.uint8), keep])  # transparent = area to generate
    buf_img, buf_mask = io.BytesIO(), io.BytesIO()
    Image.fromarray(small).save(buf_img, "PNG")
    Image.fromarray(rgba_mask, "RGBA").save(buf_mask, "PNG")
    png = provider.edit_image(image_png=buf_img.getvalue(), mask_png=buf_mask.getvalue(), prompt=PROMPTS[style],
                              width=sw, height=sh, operation="background_context_edit", watch_id=asset.watch_id)
    out = decode_rgb(png)
    out = cv2.resize(out, (w, h), interpolation=cv2.INTER_CUBIC)
    full_keep = cv2.resize(keep, (w, h), interpolation=cv2.INTER_NEAREST)
    # discard every generated pixel in and around the watch area
    small_out = cv2.resize(out, (max(8, w // 4), max(8, h // 4)), interpolation=cv2.INTER_AREA)
    small_keep = cv2.resize(full_keep, (small_out.shape[1], small_out.shape[0]), interpolation=cv2.INTER_NEAREST)
    filled = cv2.inpaint(np.ascontiguousarray(small_out[:, :, ::-1]), small_keep, 9, cv2.INPAINT_TELEA)[:, :, ::-1]
    filled = cv2.resize(filled, (w, h), interpolation=cv2.INTER_CUBIC)
    out[full_keep > 0] = filled[full_keep > 0]
    return out, {"source": f"ai:{provider.models().get('image')}:context_edit", "mode": "context_edit"}
