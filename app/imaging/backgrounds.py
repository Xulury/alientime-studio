"""Stage 4b: studio backgrounds generated locally (no AI), plus fitting of AI background plates.

Styles: studio_white, studio_grey, studio_black, green_velvet (procedural velvet texture),
cleanup (the photo's own background, smoothed), keep_original (handled in compositing).
"""
from __future__ import annotations

import cv2
import numpy as np

LOCAL_STYLES = {
    "studio_white": "Studio white",
    "studio_grey": "Studio grey",
    "studio_black": "Studio black",
    "green_velvet": "Green velvet",
    "cleanup": "Cleaned-up original background",
    "keep_original": "Original background (crop only)",
}
AI_STYLES = {
    "ai_velvet": "Green velvet (AI-generated)",
    "ai_studio": "Studio sweep (AI-generated)",
}
DARK_STYLES = {"studio_black", "green_velvet", "ai_velvet"}


def _radial(w: int, h: int, cx: float = 0.5, cy: float = 0.45, power: float = 1.6) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dx = (xx / max(1, w - 1) - cx) / 0.75
    dy = (yy / max(1, h - 1) - cy) / 0.75
    d = np.sqrt(dx * dx + dy * dy)
    return np.clip(1.0 - d ** power * 0.6, 0.0, 1.0)


def _noise(w: int, h: int, sigma: float, rng: np.random.Generator) -> np.ndarray:
    n = rng.standard_normal((h, w)).astype(np.float32)
    if sigma > 0:
        n = cv2.GaussianBlur(n, (0, 0), sigma)
        n /= max(1e-6, float(n.std()))
    return n


def _gradient_bg(w: int, h: int, center: tuple, edge: tuple, rng: np.random.Generator, grain: float = 1.2) -> np.ndarray:
    r = _radial(w, h)[..., None]
    c = np.array(center, np.float32)
    e = np.array(edge, np.float32)
    img = e + (c - e) * r
    img += _noise(w, h, 0.8, rng)[..., None] * grain  # fine grain prevents banding
    return np.clip(img, 0, 255).astype(np.uint8)


def green_velvet(w: int, h: int, rng: np.random.Generator) -> np.ndarray:
    """Deep green velvet: pile texture, soft sheen bands and a gentle key light from the upper left."""
    base = np.array([22, 64, 44], np.float32)  # RGB deep velvet green
    light = _radial(w, h, cx=0.38, cy=0.32, power=1.3)
    sheen = _noise(w, h, max(w, h) / 9.0, rng)            # broad folds / pile direction changes
    sheen2 = _noise(w, h, max(w, h) / 28.0, rng) * 0.4
    pile = _noise(w, h, 0.9, rng)                          # fine fibres
    fibre = cv2.GaussianBlur(rng.standard_normal((h, w)).astype(np.float32), (0, 0), sigmaX=0.6, sigmaY=2.2)
    fibre /= max(1e-6, float(fibre.std()))
    lum = 0.62 + 0.55 * light + 0.10 * sheen + 0.05 * sheen2
    lum = lum[..., None]
    img = base * lum
    img += (pile * 3.2 + fibre * 2.4)[..., None] * np.array([0.7, 1.0, 0.85], np.float32)
    highlight = np.clip((sheen - 0.9) * 0.6, 0, 1)[..., None] * np.array([10, 22, 16], np.float32)
    img += highlight
    return np.clip(img, 0, 255).astype(np.uint8)


def make_background(style: str, w: int, h: int, seed: int = 7) -> np.ndarray:
    rng = np.random.default_rng(seed)
    if style == "studio_white":
        return _gradient_bg(w, h, (250, 250, 248), (232, 232, 229), rng)
    if style == "studio_grey":
        return _gradient_bg(w, h, (218, 219, 217), (178, 179, 177), rng)
    if style == "studio_black":
        return _gradient_bg(w, h, (40, 41, 43), (10, 10, 11), rng, grain=0.8)
    if style == "green_velvet":
        return green_velvet(w, h, rng)
    raise ValueError(f"Unknown background style: {style}")


def cleanup_background(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """The photo's own background with the watch removed, dust and clutter smoothed away."""
    h, w = rgb.shape[:2]
    scale = min(1.0, 512 / max(h, w))
    small = cv2.resize(rgb, (max(8, int(w * scale)), max(8, int(h * scale))), interpolation=cv2.INTER_AREA)
    m = cv2.resize(mask, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_LINEAR)
    m = cv2.dilate((m > 20).astype(np.uint8) * 255, np.ones((9, 9), np.uint8), iterations=2)
    filled = cv2.inpaint(np.ascontiguousarray(small[:, :, ::-1]), m, 7, cv2.INPAINT_TELEA)[:, :, ::-1]
    filled = cv2.GaussianBlur(filled, (0, 0), max(2.0, min(small.shape[:2]) * 0.03))
    big = cv2.resize(filled, (w, h), interpolation=cv2.INTER_CUBIC).astype(np.float32)
    rng = np.random.default_rng(3)
    big += _noise(w, h, 0.8, rng)[..., None] * 1.0
    return np.clip(big, 0, 255).astype(np.uint8)


def fit_plate(plate: np.ndarray, w: int, h: int) -> np.ndarray:
    """Cover-fit a background plate to the canvas (centre crop)."""
    ph, pw = plate.shape[:2]
    s = max(w / pw, h / ph)
    resized = cv2.resize(plate, (max(w, round(pw * s)), max(h, round(ph * s))),
                         interpolation=cv2.INTER_CUBIC if s > 1 else cv2.INTER_AREA)
    y0 = (resized.shape[0] - h) // 2
    x0 = (resized.shape[1] - w) // 2
    return np.ascontiguousarray(resized[y0:y0 + h, x0:x0 + w])


def contact_shadow(mask_t: np.ndarray, dark_background: bool) -> np.ndarray:
    """Soft shadow under the watch, built from its own outline. Returns 0..1 darkening map."""
    h, w = mask_t.shape
    m = mask_t.astype(np.float32) / 255.0
    d = min(h, w)
    soft = cv2.GaussianBlur(m, (0, 0), d * 0.018)
    soft = np.roll(soft, int(d * 0.012), axis=0)
    tight = cv2.GaussianBlur(m, (0, 0), d * 0.004)
    tight = np.roll(tight, int(d * 0.003), axis=0)
    op_soft, op_tight = (0.45, 0.30) if dark_background else (0.30, 0.22)
    return np.clip(soft * op_soft + tight * op_tight, 0, 0.8)
