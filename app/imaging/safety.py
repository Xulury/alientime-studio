"""Serial-number protection (runs locally, before any other step).

* `scan()` finds serial-like text with local OCR at four rotations.
* `apply_redaction()` draws visible, solid redaction blocks.
* `recheck()` runs OCR again on each redacted area (four rotations, enlarged) and fails if any digit
  is still readable.

The recognised text is used only in memory to decide whether a box is sensitive. It is never stored
or logged; findings keep a category and a digit count instead.

OCR is not proof that every identifier is gone: frames with findings, dense engraving or no OCR at
all are marked for a person to check before they can go to cloud AI or be published.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import cv2
import numpy as np

from app.imaging.ocr import OCREngine, TextBox, detect_all_rotations

REDACTION_FILL = (38, 38, 38)
REDACTION_EDGE = (78, 78, 78)
DENSE_TEXT_BOXES = 8

_MEASURE = re.compile(r"^\d{1,5}(M|FT|MM|ATM|BAR|K|CT|CTS|HZ|VPH|J|H)$")
_NUMBERED = re.compile(r"(?:\bN[O0Oº°]\.?|#|\bNR\.?|\bSER(?:IAL)?\.?)\s*[:.]?\s*([A-Z0-9]{3,})")
_EDITION = re.compile(r"\b\d{1,4}\s*/\s*\d{2,4}\b")


@dataclass
class Finding:
    x: float
    y: float
    w: float
    h: float
    category: str
    confidence: float
    rotation: int
    digits: int

    def as_dict(self) -> dict:
        return {"x": round(self.x, 1), "y": round(self.y, 1), "w": round(self.w, 1), "h": round(self.h, 1),
                "category": self.category, "confidence": round(self.confidence, 3), "rotation": self.rotation,
                "digits": self.digits}


@dataclass
class ScanResult:
    engine: str | None
    findings: list[Finding] = field(default_factory=list)
    text_boxes: int = 0
    dense_text: bool = False

    @property
    def sensitive(self) -> bool:
        return bool(self.findings)


def classify_text(text: str) -> str | None:
    """Return a sensitivity category for one OCR line, or None if it looks harmless."""
    t = (text or "").upper().strip()
    if not t:
        return None
    digits = sum(c.isdigit() for c in t)
    if digits == 0:
        return None
    if _NUMBERED.search(t):
        return "numbered_marking"
    if _EDITION.search(t):
        return "edition_number"
    tokens = re.findall(r"[A-Z0-9]+", t)
    for tok in tokens:
        if _MEASURE.match(tok):
            continue
        tdig = sum(c.isdigit() for c in tok)
        if len(tok) >= 5 and tdig >= 4:
            return "serial_like"
        if len(tok) >= 6 and tdig >= 3 and any(c.isalpha() for c in tok):
            return "serial_like"
    # digits split by spaces, e.g. "4 827 193"
    compact = re.sub(r"[\s\-.]", "", t)
    runs = re.findall(r"\d{6,}", compact)
    if runs:
        return "long_number"
    return None


def scan(rgb: np.ndarray, engine: OCREngine | None, min_conf: float = 0.35) -> ScanResult:
    if engine is None:
        return ScanResult(engine=None)
    boxes = detect_all_rotations(rgb, engine)
    result = ScanResult(engine=engine.name)
    confident = [b for b in boxes if b.confidence >= 0.5]
    # A frame with lots of text (counted at the most text-rich rotation) is likely a caseback or a document.
    per_rot: dict[int, int] = {}
    for b in confident:
        per_rot[b.rotation] = per_rot.get(b.rotation, 0) + 1
    result.text_boxes = max(per_rot.values()) if per_rot else 0
    result.dense_text = result.text_boxes >= DENSE_TEXT_BOXES
    for b in boxes:
        if b.confidence < min_conf:
            continue
        cat = classify_text(b.text)
        if cat is None:
            continue
        x, y, w, h = b.bbox
        result.findings.append(Finding(x, y, w, h, cat, b.confidence, b.rotation, sum(c.isdigit() for c in b.text)))
    return result


def finding_to_region(f: Finding, img_w: int, img_h: int, pad_ratio: float = 0.35) -> tuple[float, float, float, float]:
    """Pixel box → padded, normalised (x, y, w, h)."""
    pad = max(4.0, pad_ratio * min(f.w, f.h))
    x0 = max(0.0, f.x - pad)
    y0 = max(0.0, f.y - pad)
    x1 = min(float(img_w), f.x + f.w + pad)
    y1 = min(float(img_h), f.y + f.h + pad)
    return x0 / img_w, y0 / img_h, (x1 - x0) / img_w, (y1 - y0) / img_h


def merge_regions(regions: list[tuple[float, float, float, float]], gap: float = 0.004) -> list[tuple[float, float, float, float]]:
    """Merge overlapping or touching normalised rectangles (same text found at several rotations)."""
    rects = [list(r) for r in regions]
    changed = True
    while changed:
        changed = False
        out: list[list[float]] = []
        while rects:
            a = rects.pop()
            ax0, ay0, ax1, ay1 = a[0], a[1], a[0] + a[2], a[1] + a[3]
            i = 0
            while i < len(rects):
                b = rects[i]
                bx0, by0, bx1, by1 = b[0], b[1], b[0] + b[2], b[1] + b[3]
                if ax0 - gap <= bx1 and bx0 - gap <= ax1 and ay0 - gap <= by1 and by0 - gap <= ay1:
                    ax0, ay0, ax1, ay1 = min(ax0, bx0), min(ay0, by0), max(ax1, bx1), max(ay1, by1)
                    rects.pop(i)
                    changed = True
                else:
                    i += 1
            out.append([ax0, ay0, ax1 - ax0, ay1 - ay0])
        rects = out
    return [tuple(r) for r in rects]  # type: ignore[misc]


def region_px(r: tuple[float, float, float, float], w: int, h: int) -> tuple[int, int, int, int]:
    x0 = int(np.floor(r[0] * w))
    y0 = int(np.floor(r[1] * h))
    x1 = int(np.ceil((r[0] + r[2]) * w))
    y1 = int(np.ceil((r[1] + r[3]) * h))
    return max(0, x0), max(0, y0), min(w, x1), min(h, y1)


def apply_redaction(rgb: np.ndarray, regions: list[tuple[float, float, float, float]]) -> np.ndarray:
    out = rgb.copy()
    h, w = out.shape[:2]
    edge = max(1, round(min(w, h) * 0.0015))
    for r in regions:
        x0, y0, x1, y1 = region_px(r, w, h)
        if x1 <= x0 or y1 <= y0:
            continue
        out[y0:y1, x0:x1] = REDACTION_EDGE
        if x1 - x0 > 2 * edge and y1 - y0 > 2 * edge:
            out[y0 + edge:y1 - edge, x0 + edge:x1 - edge] = REDACTION_FILL
    return out


def redaction_mask(shape: tuple[int, int], regions: list[tuple[float, float, float, float]]) -> np.ndarray:
    h, w = shape
    m = np.zeros((h, w), np.uint8)
    for r in regions:
        x0, y0, x1, y1 = region_px(r, w, h)
        m[y0:y1, x0:x1] = 255
    return m


def recheck(redacted: np.ndarray, regions: list[tuple[float, float, float, float]], engine: OCREngine | None) -> dict:
    """Second OCR pass on each redacted area. Fails if any digit is readable there."""
    if engine is None:
        return {"passed": False, "engine": None, "checked": 0, "failures": [],
                "message": "OCR unavailable: redactions need a manual check."}
    h, w = redacted.shape[:2]
    failures: list[int] = []
    for i, r in enumerate(regions):
        x0, y0, x1, y1 = region_px(r, w, h)
        mx = max(6, (x1 - x0) // 6)
        my = max(6, (y1 - y0) // 6)
        crop = redacted[max(0, y0 - my):min(h, y1 + my), max(0, x0 - mx):min(w, x1 + mx)]
        if crop.size == 0:
            continue
        scale = 2.0 if max(crop.shape[:2]) < 800 else 1.0
        if scale != 1.0:
            crop = cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
        boxes = detect_all_rotations(crop, engine, max_edge=max(crop.shape[:2]))
        if any(any(c.isdigit() for c in b.text) and b.confidence >= 0.3 for b in boxes):
            failures.append(i)
    passed = not failures
    return {"passed": passed, "engine": engine.name, "checked": len(regions), "failures": failures,
            "message": "No digits readable inside redacted areas." if passed
            else f"Digits still readable in {len(failures)} redacted area(s). Enlarge the redaction."}
