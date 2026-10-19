"""Watch segmentation (local).

Backends:
* rembg with ISNet / BiRefNet ONNX models (best quality; the model downloads once on first use)
* OpenCV GrabCut seeded from the background colour (no model needed; good on clean backgrounds)

Masks are soft 8-bit alpha mattes at the working-image size, so case edges, hands and crystals keep
their fine detail. Small interior holes (e.g. a semi-transparent crystal) are filled so watch pixels are
never dropped; larger openings (a bracelet loop) are left for the person to decide in the mask editor.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field

import cv2
import numpy as np
from PIL import Image

from app.config import get_settings
from app.imaging.io import downscale

log = logging.getLogger(__name__)


@dataclass
class SegmentationResult:
    mask: np.ndarray
    backend: str
    notes: list[str] = field(default_factory=list)


class GrabCutSegmenter:
    """Classical cutout. Clean studio backgrounds use a colour-difference matte; busy ones use GrabCut."""

    name = "grabcut"

    def segment(self, rgb: np.ndarray) -> SegmentationResult:
        h, w = rgb.shape[:2]
        small, scale = downscale(rgb, 900)
        sh, sw = small.shape[:2]
        lab = cv2.cvtColor(small, cv2.COLOR_RGB2LAB).astype(np.float32)
        b = max(4, min(sh, sw) // 40)
        border = np.concatenate([lab[:b].reshape(-1, 3), lab[-b:].reshape(-1, 3),
                                 lab[:, :b].reshape(-1, 3), lab[:, -b:].reshape(-1, 3)])
        bg = np.median(border, axis=0)
        spread = float(np.percentile(np.linalg.norm(border - bg, axis=1), 65))
        dist = cv2.GaussianBlur(np.linalg.norm(lab - bg, axis=2), (5, 5), 0)
        k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
        notes: list[str] = []
        if spread < 6.0:
            # uniform studio background: a colour-difference matte is more faithful than GrabCut
            thr = max(6.0, spread * 2.5)
            m = (dist > thr).astype(np.uint8)
            m = cv2.morphologyEx(m, cv2.MORPH_OPEN, k, iterations=1)
            m = (m * 255).astype(np.uint8)
            notes.append("Clean background: cut out by colour difference.")
        else:
            dist8 = np.clip(dist / max(1.0, float(dist.max())) * 255, 0, 255).astype(np.uint8)
            otsu, _ = cv2.threshold(dist8, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            thr_abs = max(otsu, (spread * 1.5) / max(1.0, float(dist.max())) * 255)
            init = (dist8 > thr_abs).astype(np.uint8)
            init = cv2.morphologyEx(init, cv2.MORPH_CLOSE, k, iterations=2)
            init = cv2.morphologyEx(init, cv2.MORPH_OPEN, k, iterations=1)
            gc = np.full((sh, sw), cv2.GC_PR_BGD, np.uint8)
            if init.mean() < 0.01 or init.mean() > 0.9:
                notes.append("Busy background; used a centre-weighted starting guess.")
                gc[sh // 8: sh - sh // 8, sw // 8: sw - sw // 8] = cv2.GC_PR_FGD
            else:
                gc[init > 0] = cv2.GC_PR_FGD
                core = cv2.erode(init, k, iterations=4)
                gc[core > 0] = cv2.GC_FGD
            edge = np.zeros((sh, sw), bool)
            edge[:b, :] = edge[-b:, :] = True
            edge[:, :b] = edge[:, -b:] = True
            gc[edge & (init == 0)] = cv2.GC_BGD  # the frame edge is background unless something runs off it
            bgd = np.zeros((1, 65), np.float64)
            fgd = np.zeros((1, 65), np.float64)
            try:
                cv2.grabCut(np.ascontiguousarray(small[:, :, ::-1]), gc, None, bgd, fgd, 5, cv2.GC_INIT_WITH_MASK)
                m = np.where((gc == cv2.GC_FGD) | (gc == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
            except cv2.error:
                notes.append("GrabCut could not converge; using the colour-difference mask.")
                m = init * 255
        m = cv2.resize(m, (w, h), interpolation=cv2.INTER_LINEAR)
        m = cv2.GaussianBlur(m, (0, 0), sigmaX=max(0.8, 0.6 / max(scale, 1e-3)))
        return SegmentationResult(m, self.name, notes)


class RembgSegmenter:
    def __init__(self, model: str):
        from rembg import new_session  # optional dependency

        s = get_settings()
        if s.rembg_model_dir:
            import os

            os.environ.setdefault("U2NET_HOME", str(s.rembg_model_dir))
        self.model = model
        self.name = f"rembg:{model}"
        self._session = new_session(model)
        self._lock = threading.Lock()

    def segment(self, rgb: np.ndarray) -> SegmentationResult:
        from rembg import remove

        with self._lock:
            out = remove(Image.fromarray(rgb), session=self._session, only_mask=True, post_process_mask=False)
        m = np.asarray(out.convert("L")).copy()
        if m.shape[:2] != rgb.shape[:2]:
            m = cv2.resize(m, (rgb.shape[1], rgb.shape[0]), interpolation=cv2.INTER_LINEAR)
        return SegmentationResult(m, self.name)


_lock = threading.Lock()
_segmenter = None
_segmenter_note: str | None = None


def get_segmenter():
    global _segmenter, _segmenter_note
    with _lock:
        if _segmenter is not None:
            return _segmenter
        s = get_settings()
        if s.segmentation_backend in ("auto", "rembg"):
            try:
                _segmenter = RembgSegmenter(s.rembg_model)
                return _segmenter
            except Exception as e:
                _segmenter_note = f"Local AI cutout model unavailable ({type(e).__name__}); using GrabCut."
                log.warning(_segmenter_note)
                if s.segmentation_backend == "rembg":
                    log.warning("SEGMENTATION_BACKEND=rembg but rembg failed; falling back to GrabCut")
        _segmenter = GrabCutSegmenter()
        return _segmenter


def set_segmenter_for_tests(seg) -> None:
    global _segmenter
    with _lock:
        _segmenter = seg


def segmenter_status() -> dict:
    seg = get_segmenter()
    return {"backend": seg.name, "note": _segmenter_note}


def refine_mask(mask: np.ndarray, hole_fill_ratio: float = 0.015) -> tuple[np.ndarray, list[str]]:
    """Remove specks, fill small interior holes. Keeps soft edges."""
    notes: list[str] = []
    h, w = mask.shape
    binary = (mask > 127).astype(np.uint8)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    if n <= 1:
        return mask, ["No watch found in the cutout."]
    areas = stats[1:, cv2.CC_STAT_AREA]
    largest = areas.max()
    keep = np.zeros(n, bool)
    keep[1:] = areas >= max(64, 0.02 * largest)
    removed = int((~keep[1:]).sum())
    out = mask.copy()
    out[(~keep[labels]) & (binary > 0)] = 0
    if removed:
        notes.append(f"Removed {removed} small speck(s) from the cutout.")
    # Fill every hole enclosed by the watch outline: a dial or crystal is never background.
    kept = keep[labels].astype(np.uint8)
    inv = (1 - kept).astype(np.uint8)
    n2, lab2, st2, _ = cv2.connectedComponentsWithStats(inv, connectivity=4)
    filled, large = 0, 0
    for i in range(1, n2):
        x, y, bw, bh, area = st2[i]
        touches = x == 0 or y == 0 or x + bw >= w or y + bh >= h
        if not touches:
            out[lab2 == i] = 255
            filled += 1
            if area > hole_fill_ratio * h * w:
                large += 1
    if filled:
        notes.append(f"Filled {filled} gap(s) inside the watch outline (dial, crystal, reflections).")
    if large:
        notes.append("A large enclosed area was kept as part of the watch. If it is background (for example inside "
                     "a bracelet loop), erase it in the cutout editor.")
    return out, notes


def mask_stats(mask: np.ndarray) -> dict:
    h, w = mask.shape
    fg = mask > 127
    ratio = float(fg.mean())
    if not fg.any():
        return {"fg_ratio": 0.0, "bbox": None, "edge_touch": [], "soft_edge_ratio": 0.0, "mean_alpha": 0.0}
    ys, xs = np.where(fg)
    x0, x1, y0, y1 = int(xs.min()), int(xs.max()), int(ys.min()), int(ys.max())
    edge = []
    band = 3
    for name, strip, length in (("top", fg[:band, :], w), ("bottom", fg[-band:, :], w),
                                ("left", fg[:, :band], h), ("right", fg[:, -band:], h)):
        if strip.any(axis=0 if name in ("top", "bottom") else 1).sum() > 0.02 * length:
            edge.append(name)
    soft = ((mask > 20) & (mask < 235)).sum() / max(1, fg.sum())
    return {
        "fg_ratio": round(ratio, 4),
        "bbox": [x0 / w, y0 / h, (x1 - x0 + 1) / w, (y1 - y0 + 1) / h],
        "edge_touch": edge,
        "soft_edge_ratio": round(float(soft), 4),
        "mean_alpha": round(float(mask[fg].mean() / 255), 4),
    }


def segment(rgb: np.ndarray) -> SegmentationResult:
    seg = get_segmenter()
    try:
        res = seg.segment(rgb)
    except Exception as e:  # model failure at runtime → classical fallback
        log.warning("segmentation backend %s failed: %s", getattr(seg, "name", "?"), e)
        res = GrabCutSegmenter().segment(rgb)
        res.notes.append("The AI cutout model failed on this photo; used GrabCut instead.")
    refined, notes = refine_mask(res.mask)
    res.mask = refined
    res.notes.extend(notes)
    return res
