"""Stage 4a: deterministic colour and exposure correction.

All corrections are expressed as a small parameter set and applied through per-channel lookup
tables, so the exact same transform can be re-applied when the fidelity gate rebuilds the reference.
"""
from __future__ import annotations

import cv2
import numpy as np


def auto_color_params(rgb: np.ndarray, mask: np.ndarray | None, *, wb_strength: float = 0.6,
                      auto_exposure: bool = True, exposure_ev: float = 0.0, contrast: float = 0.0,
                      warmth: float = 0.0) -> dict:
    small = rgb
    if max(rgb.shape[:2]) > 1024:
        f = 1024 / max(rgb.shape[:2])
        small = cv2.resize(rgb, None, fx=f, fy=f, interpolation=cv2.INTER_AREA)
    if mask is not None:
        m = cv2.resize(mask, (small.shape[1], small.shape[0]), interpolation=cv2.INTER_NEAREST) > 200
    else:
        m = np.ones(small.shape[:2], bool)
    if m.sum() < 200:
        m = np.ones(small.shape[:2], bool)
    x = small.astype(np.float32) / 255.0
    notes: list[str] = []

    gains = np.ones(3, np.float32)
    if wb_strength > 0:
        hsv = cv2.cvtColor(small, cv2.COLOR_RGB2HSV).astype(np.float32)
        sat = hsv[:, :, 1] / 255.0
        val = hsv[:, :, 2] / 255.0
        neutral = m & (sat < 0.22) & (val > 0.18) & (val < 0.96)
        if neutral.sum() >= 400:
            means = x[neutral].mean(axis=0)
            target = float(means.mean())
            raw = np.clip(target / np.maximum(means, 1e-3), 0.85, 1.15)
            gains = 1.0 + wb_strength * (raw - 1.0)
            gains = np.clip(gains, 0.88, 1.12).astype(np.float32)
            notes.append("White balance from neutral areas of the watch.")
        else:
            notes.append("Not enough neutral tones for automatic white balance.")
    if warmth:
        gains = gains * np.array([1 + warmth / 200, 1.0, 1 - warmth / 200], np.float32)

    gain = 1.0
    if auto_exposure:
        y = (x * gains) @ np.array([0.2126, 0.7152, 0.0722], np.float32)
        p995 = float(np.percentile(y[m], 99.5))
        if p995 < 0.86:
            gain = float(np.clip(0.95 / max(p995, 1e-3), 1.0, 1.35))
            notes.append(f"Brightness lifted ×{gain:.2f}.")
        elif p995 > 0.995 and float((y[m] > 0.995).mean()) > 0.03:
            gain = 0.96
            notes.append("Highlights eased slightly.")
    gain *= float(2.0 ** exposure_ev)
    return {
        "wb_gains": [round(float(g), 4) for g in gains],
        "gain": round(gain, 4),
        "contrast": round(float(contrast), 2),
        "notes": notes,
    }


def color_luts(params: dict) -> list[np.ndarray]:
    v = np.arange(256, dtype=np.float32) / 255.0
    c = 1.0 + float(params.get("contrast", 0.0)) / 100.0
    luts = []
    for g in params.get("wb_gains", [1, 1, 1]):
        y = v * float(g) * float(params.get("gain", 1.0))
        y = (y - 0.5) * c + 0.5
        luts.append(np.clip(np.rint(y * 255.0), 0, 255).astype(np.uint8))
    return luts


def apply_color(rgb: np.ndarray, params: dict) -> np.ndarray:
    if not params:
        return rgb
    luts = color_luts(params)
    out = np.empty_like(rgb)
    for i in range(3):
        out[:, :, i] = cv2.LUT(rgb[:, :, i], luts[i])
    return out


def is_identity(params: dict) -> bool:
    return (all(abs(g - 1.0) < 1e-4 for g in params.get("wb_gains", [1, 1, 1]))
            and abs(params.get("gain", 1.0) - 1.0) < 1e-4 and abs(params.get("contrast", 0.0)) < 1e-4)
