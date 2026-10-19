"""Fidelity gate: a number, not a model's opinion.

The reference is rebuilt independently from files on disk: the redacted working photo, the stored
colour parameters and the stored transform. Inside the watch outline (mask eroded a few pixels to skip
the blended edge), the final image must match that reference. Only JPEG compression differences are
expected. Redaction blocks are also checked to still be present in the final.
"""
from __future__ import annotations

import cv2
import numpy as np

from app.imaging.composite import Plan, transform
from app.imaging.enhance import apply_color
from app.imaging.safety import REDACTION_FILL

PSNR_MIN = 34.0
P99_MAX = 32.0


def compare(output: np.ndarray, reference: np.ndarray, mask_t: np.ndarray) -> dict:
    h, w = mask_t.shape
    erode = max(2, int(round(min(h, w) * 0.004)))
    interior = cv2.erode((mask_t >= 250).astype(np.uint8), np.ones((2 * erode + 1, 2 * erode + 1), np.uint8)) > 0
    n = int(interior.sum())
    if n < 500:
        return {"passed": False, "pixels_compared": n, "message": "Watch area too small to verify."}
    diff = np.abs(output[interior].astype(np.int16) - reference[interior].astype(np.int16)).astype(np.float32)
    mse = float((diff ** 2).mean())
    psnr = 99.0 if mse == 0 else float(20 * np.log10(255.0 / np.sqrt(mse)))
    p99 = float(np.percentile(diff.max(axis=1), 99))
    mae = float(diff.mean())
    passed = psnr >= PSNR_MIN and p99 <= P99_MAX
    return {
        "passed": passed, "psnr_db": round(psnr, 2), "mean_abs_error": round(mae, 3), "p99_abs_error": round(p99, 1),
        "pixels_compared": n,
        "message": "Watch pixels match the original photo." if passed
        else "Watch pixels differ from the original photo beyond compression tolerance.",
    }


def redactions_intact(output: np.ndarray, regions: list[tuple[float, float, float, float]], src_size: tuple[int, int],
                      plan: Plan, mask_t: np.ndarray, color_params: dict, bg_keeps_original: bool) -> dict:
    """Check each redaction block that should be visible is still solid in the output.

    Blocks on the watch must survive. Blocks on the background only need to survive when the original
    background is kept; otherwise that area is replaced by the studio background anyway.
    """
    if not regions:
        return {"passed": True, "checked": 0}
    expected = apply_color(np.array([[REDACTION_FILL]], np.uint8), color_params)[0, 0].astype(np.float32)
    sw, sh = src_size
    m = plan.matrix()
    ok = 0
    checked = 0
    for (x, y, w, h) in regions:
        cx = (x + w / 2) * sw * plan.pre_scale
        cy = (y + h / 2) * sh * plan.pre_scale
        px = m[0, 0] * cx + m[0, 1] * cy + m[0, 2]
        py = m[1, 0] * cx + m[1, 1] * cy + m[1, 2]
        half = max(1, int(min(w * sw, h * sh) * plan.total_scale * 0.2))
        x0, y0 = int(px) - half, int(py) - half
        if x0 < 0 or y0 < 0 or x0 + 2 * half >= output.shape[1] or y0 + 2 * half >= output.shape[0]:
            continue
        on_watch = mask_t[int(py), int(px)] >= 128
        if not on_watch and not bg_keeps_original:
            continue
        checked += 1
        patch = output[y0:y0 + 2 * half + 1, x0:x0 + 2 * half + 1].astype(np.float32)
        if np.abs(patch - expected).mean() < 12:
            ok += 1
    return {"passed": ok == checked, "checked": checked, "intact": ok}


def check(output: np.ndarray, redacted_working: np.ndarray, mask: np.ndarray, color_params: dict, plan: Plan,
          regions: list[tuple[float, float, float, float]], bg_keeps_original: bool = False) -> dict:
    reference = transform(apply_color(redacted_working, color_params), plan)
    mask_t = transform(mask, plan, is_mask=True)
    res = compare(output, reference, mask_t)
    red = redactions_intact(output, regions, (redacted_working.shape[1], redacted_working.shape[0]), plan,
                            mask_t, color_params, bg_keeps_original)
    res["redactions"] = red
    if not red["passed"]:
        res["passed"] = False
        res["message"] = "A redaction block is missing from the final image."
    return res
