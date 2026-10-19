"""Stage 1: image inspection and selection.

Scores sharpness, exposure, resolution, watch visibility and composition, detects the source type
(edited / raw camera / phone or WhatsApp), guesses the photo type, and decides whether a frame is
kept, with a one-line reason for every rejection.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.imaging.io import downscale

PHONE_MAKES = ("apple", "samsung", "google", "huawei", "xiaomi", "oppo", "vivo", "oneplus", "honor", "realme", "motorola")
CAMERA_MAKES = ("canon", "nikon", "sony", "fujifilm", "leica", "hasselblad", "panasonic", "olympus", "om digital", "pentax", "ricoh", "sigma")
EDIT_SOFTWARE = ("photoshop", "lightroom", "capture one", "affinity", "gimp", "pixelmator", "luminar", "snapseed")
WHATSAPP_NAME = re.compile(r"(IMG-\d{8}-WA\d+|WhatsApp Image)", re.IGNORECASE)


@dataclass
class Inspection:
    metrics: dict = field(default_factory=dict)
    rejects: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    score: float = 0.0
    source_profile: str = "raw"
    source_reasons: list[str] = field(default_factory=list)
    photo_type: str = "unclassified"
    photo_type_confidence: float = 0.0

    def as_dict(self) -> dict:
        return {"metrics": self.metrics, "rejects": self.rejects, "warnings": self.warnings,
                "score": self.score, "source_profile": self.source_profile, "source_reasons": self.source_reasons,
                "photo_type": self.photo_type, "photo_type_confidence": self.photo_type_confidence}


def detect_source_profile(rgb: np.ndarray, exif: dict, filename: str, original_size: tuple[int, int],
                          fmt: str, had_transparency: bool) -> tuple[str, list[str]]:
    make = (exif.get("Make") or "").lower()
    software = (exif.get("Software") or "").lower()
    reasons: list[str] = []
    if had_transparency:
        return "edited", ["PNG with a transparent background"]
    if any(s in software for s in EDIT_SOFTWARE):
        reasons.append(f"Edited in {exif.get('Software')}")
    small, _ = downscale(rgb, 512)
    b = max(3, min(small.shape[:2]) // 40)
    border = np.concatenate([small[:b].reshape(-1, 3), small[-b:].reshape(-1, 3),
                             small[:, :b].reshape(-1, 3), small[:, -b:].reshape(-1, 3)]).astype(np.float32)
    bmean, bstd = float(border.mean()), float(border.std())
    if bstd < 7 and (bmean > 232 or bmean < 22):
        reasons.append("Clean, uniform studio background")
    if reasons:
        return "edited", reasons
    if WHATSAPP_NAME.search(filename or ""):
        return "phone", ["WhatsApp file name"]
    if any(m in make for m in PHONE_MAKES):
        return "phone", [f"Phone camera ({exif.get('Make')} {exif.get('Model', '')})".strip()]
    if not exif and fmt in ("JPEG", "MPO") and max(original_size) <= 1600:
        return "phone", ["No camera data and at most 1600 px — typical of WhatsApp or messaging apps"]
    if any(m in make for m in CAMERA_MAKES):
        return "raw", [f"Camera original ({exif.get('Make')} {exif.get('Model', '')})".strip()]
    return "raw", ["Unedited photo"]


def _subject_region(mask: np.ndarray | None, shape: tuple[int, int]) -> np.ndarray:
    h, w = shape
    if mask is not None and (mask > 127).mean() > 0.01:
        m = cv2.resize(mask, (w, h), interpolation=cv2.INTER_NEAREST) > 127
        return cv2.erode(m.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    region = np.zeros((h, w), bool)
    region[h // 5: h - h // 5, w // 5: w - w // 5] = True
    return region


def sharpness(gray: np.ndarray, region: np.ndarray) -> tuple[float, float]:
    lap = cv2.Laplacian(gray, cv2.CV_64F, ksize=3)
    vals = lap[region]
    if vals.size < 50:
        vals = lap.ravel()
    var = float(vals.var())
    # Use the sharpest part of the subject too: a dial in focus with a soft strap is fine.
    h, w = gray.shape
    tiles = []
    th, tw = max(16, h // 6), max(16, w // 6)
    for y in range(0, h - th + 1, th):
        for x in range(0, w - tw + 1, tw):
            r = region[y:y + th, x:x + tw]
            if r.mean() > 0.5:
                tiles.append(float(lap[y:y + th, x:x + tw][r].var()))
    peak = float(np.percentile(tiles, 90)) if tiles else var
    return var, peak


def sharpness_score(var: float) -> float:
    return round(max(0.0, min(100.0, 100 * math.log10(1 + var) / math.log10(1 + 1500))), 1)


def _front_case_shape(fg: np.ndarray) -> bool:
    """True when the silhouette looks like a watch seen from the front: a roughly square case section that is
    clearly wider than the strap. Seen from the side, the case section is long and thin instead."""
    ys, xs = np.nonzero(fg)
    if len(xs) < 500:
        return False
    pts = np.stack([xs, ys], 1).astype(np.float32)
    pts -= pts.mean(0)
    _, vecs = np.linalg.eigh(np.cov(pts.T))
    u, v = pts @ vecs[:, 1], pts @ vecs[:, 0]
    edges = np.linspace(u.min(), u.max() + 1e-3, 61)
    step = edges[1] - edges[0]
    idx = np.clip(np.digitize(u, edges) - 1, 0, 59)
    widths = np.zeros(60)
    for i in range(60):
        sel = v[idx == i]
        if len(sel) > 3:
            widths[i] = np.percentile(sel, 98) - np.percentile(sel, 2)
    w_max = float(np.percentile(widths[widths > 0], 95)) if (widths > 0).any() else 0.0
    if w_max <= 0:
        return False
    case = widths >= 0.8 * w_max
    case_len = float(case.sum() * step)
    rest = widths[(~case) & (widths > 0)]
    strap = float(np.median(rest)) if len(rest) >= 6 else 0.0
    squareish = 0.6 <= case_len / w_max <= 1.7
    return squareish and (strap == 0.0 or w_max / max(strap, 1.0) >= 1.12)


def classify_local(rgb: np.ndarray, mask: np.ndarray | None, text_boxes: int, dense_text: bool,
                   has_serial: bool = False) -> tuple[str, float]:
    """Cheap, low-confidence photo-type guess. AI tagging or the user can override it."""
    if mask is None or (mask > 127).mean() < 0.01:
        return ("document", 0.4) if dense_text else ("unclassified", 0.0)
    small_mask, s = downscale(mask, 640)
    fg = (small_mask > 127).astype(np.uint8)
    cnts, _ = cv2.findContours(fg, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not cnts:
        return "unclassified", 0.0
    c = max(cnts, key=cv2.contourArea)
    area = cv2.contourArea(c)
    x, y, bw, bh = cv2.boundingRect(c)
    aspect = max(bw, bh) / max(1, min(bw, bh))
    rect_fill = area / max(1, bw * bh)
    if dense_text and rect_fill > 0.85:
        return "document", 0.5
    small_rgb, _ = downscale(rgb, 640)
    gray = cv2.cvtColor(small_rgb, cv2.COLOR_RGB2GRAY)
    roi = cv2.GaussianBlur(gray[y:y + bh, x:x + bw], (5, 5), 1.5)
    circles = None
    if min(bw, bh) > 40:
        circles = cv2.HoughCircles(roi, cv2.HOUGH_GRADIENT, dp=1.2, minDist=min(bw, bh),
                                   param1=120, param2=40, minRadius=int(min(bw, bh) * 0.28),
                                   maxRadius=int(min(bw, bh) * 0.55))
    if circles is not None and len(circles[0]):
        if dense_text or has_serial:
            return "caseback", 0.5
        return "dial_front", 0.45
    if _front_case_shape(fg):
        if dense_text or has_serial:
            return "caseback", 0.35
        return "dial_front", 0.35
    if aspect >= 2.4:
        return "strap", 0.3
    if aspect >= 1.6:
        return "side_profile", 0.25
    if dense_text or has_serial:
        return "caseback", 0.3
    return "unclassified", 0.0


def inspect_image(
    rgb: np.ndarray,
    mask: np.ndarray | None,
    *,
    exif: dict,
    filename: str,
    original_size: tuple[int, int],
    fmt: str,
    had_transparency: bool = False,
    text_boxes: int = 0,
    dense_text: bool = False,
    has_serial: bool = False,
    min_sharpness: float = 35.0,
    min_resolution: int = 700,
) -> Inspection:
    ins = Inspection()
    small, _ = downscale(rgb, 1024)
    gray = cv2.cvtColor(small, cv2.COLOR_RGB2GRAY)
    region = _subject_region(mask, gray.shape)

    # sharpness / blur
    var, peak = sharpness(gray, region)
    s_score = sharpness_score(max(var, peak * 0.6))
    ins.metrics["sharpness"] = s_score
    ins.metrics["laplacian_var"] = round(var, 1)
    if s_score < min_sharpness:
        ins.rejects.append("Out of focus or motion-blurred.")
    elif s_score < min_sharpness + 12:
        ins.warnings.append("Slightly soft focus.")

    # exposure (on the watch, not the background)
    lum = cv2.cvtColor(small, cv2.COLOR_RGB2LAB)[:, :, 0].astype(np.float32) * (100 / 255)
    sub = lum[region] if region.any() else lum.ravel()
    mean = float(sub.mean())
    p5, p95 = float(np.percentile(sub, 5)), float(np.percentile(sub, 95))
    clipped = float((small[region] >= 252).all(axis=-1).mean()) if region.any() else 0.0
    crushed = float((small[region] <= 4).all(axis=-1).mean()) if region.any() else 0.0
    ins.metrics.update({"exposure_mean": round(mean, 1), "exposure_p5": round(p5, 1),
                        "exposure_p95": round(p95, 1), "clipped": round(clipped, 4), "crushed": round(crushed, 4)})
    if mean < 12 and p95 < 35:
        ins.rejects.append("Far too dark to use.")
    elif mean < 22 and p95 < 55:
        ins.warnings.append("Underexposed; brightness will be lifted.")
    if clipped > 0.25:
        ins.rejects.append("Large blown-out highlights on the watch.")
    elif clipped > 0.08:
        ins.warnings.append("Some highlights on the watch are blown out.")
    if crushed > 0.3:
        ins.warnings.append("Deep shadows hide detail.")
    exp_score = 100.0 - min(100.0, abs(mean - 50) * 1.2 + clipped * 200 + crushed * 80)

    # resolution
    ow, oh = original_size
    ins.metrics["resolution"] = [ow, oh]
    short = min(ow, oh)
    if short < min_resolution:
        ins.rejects.append(f"Too small ({ow}×{oh} px).")
    elif short < 1200:
        ins.warnings.append(f"Low resolution ({ow}×{oh} px): fine for social, limited zoom on the website.")
    res_score = max(0.0, min(100.0, (short - 500) / 15))

    # watch visibility and composition
    vis_score = 50.0
    if mask is not None:
        from app.imaging.segment import mask_stats

        ms = mask_stats(mask)
        ins.metrics["subject"] = ms
        if ms["fg_ratio"] < 0.015:
            ins.rejects.append("Watch not found in the frame.")
            vis_score = 0.0
        else:
            bx, by, bw, bh = ms["bbox"]
            fill = bw * bh
            ins.metrics["subject_fill"] = round(fill, 3)
            off = math.hypot(bx + bw / 2 - 0.5, by + bh / 2 - 0.5)
            ins.metrics["subject_offset"] = round(off, 3)
            vis_score = 100.0
            if len(ms["edge_touch"]) >= 2:
                ins.warnings.append("The watch runs off the frame edge (" + ", ".join(ms["edge_touch"]) + ").")
                vis_score -= 35
            elif ms["edge_touch"]:
                ins.warnings.append(f"The watch touches the {ms['edge_touch'][0]} edge.")
                vis_score -= 15
            if fill < 0.04:
                ins.warnings.append("The watch is small in the frame; enlarging it may soften detail.")
                vis_score -= 25
            if off > 0.25:
                ins.warnings.append("Off-centre composition (the studio crop re-centres it).")
                vis_score -= 5
    ins.metrics["visibility"] = round(vis_score, 1)

    ins.score = round(0.4 * s_score + 0.25 * exp_score + 0.15 * res_score + 0.2 * vis_score, 1)
    ins.source_profile, ins.source_reasons = detect_source_profile(rgb, exif, filename, original_size, fmt,
                                                                    had_transparency)
    ins.photo_type, ins.photo_type_confidence = classify_local(rgb, mask, text_boxes, dense_text, has_serial)
    return ins
