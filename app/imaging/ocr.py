"""Local OCR adapter (RapidOCR / PaddleOCR models via ONNX Runtime). Nothing leaves the machine.

`detect_all_rotations` runs the engine at 0°, 90°, 180° and 270° and maps every box back to the
coordinates of the unrotated image, so engravings at any angle are found.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from app.config import get_settings
from app.imaging.io import downscale

log = logging.getLogger(__name__)


@dataclass
class TextBox:
    points: list[tuple[float, float]]  # four corners in original image pixel coordinates
    text: str
    confidence: float
    rotation: int = 0

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        xs = [p[0] for p in self.points]
        ys = [p[1] for p in self.points]
        return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


class OCREngine(Protocol):
    name: str

    def detect(self, rgb: np.ndarray) -> list[TextBox]: ...


class RapidOCREngine:
    name = "rapidocr-onnx"

    def __init__(self) -> None:
        from rapidocr_onnxruntime import RapidOCR  # imported lazily: optional dependency

        self._engine = RapidOCR()
        self._lock = threading.Lock()

    def detect(self, rgb: np.ndarray) -> list[TextBox]:
        bgr = np.ascontiguousarray(rgb[:, :, ::-1])
        with self._lock:
            result, _ = self._engine(bgr)
        boxes: list[TextBox] = []
        for item in result or []:
            pts, text, conf = item[0], item[1], item[2]
            try:
                c = float(conf)
            except (TypeError, ValueError):
                c = 0.0
            boxes.append(TextBox([(float(p[0]), float(p[1])) for p in pts], str(text), c))
        return boxes


_engine_lock = threading.Lock()
_engine: OCREngine | None = None
_engine_error: str | None = None
_engine_loaded = False


def get_ocr_engine() -> OCREngine | None:
    """Returns the configured engine, or None when OCR is unavailable (frames then need a manual check)."""
    global _engine, _engine_error, _engine_loaded
    backend = get_settings().ocr_backend
    if backend == "none":
        return None
    with _engine_lock:
        if not _engine_loaded:
            _engine_loaded = True
            try:
                _engine = RapidOCREngine()
            except Exception as e:  # missing package or model problem
                _engine_error = f"{type(e).__name__}: {e}"
                log.warning("OCR engine unavailable: %s", _engine_error)
                _engine = None
        return _engine


def ocr_status() -> dict:
    eng = get_ocr_engine()
    return {"available": eng is not None, "engine": eng.name if eng else None, "error": _engine_error}


def set_engine_for_tests(engine: OCREngine | None) -> None:
    global _engine, _engine_loaded
    with _engine_lock:
        _engine = engine
        _engine_loaded = True


def _unrotate(x: float, y: float, k: int, w: int, h: int) -> tuple[float, float]:
    """Map a point from np.rot90(img, k) back to the original image (w, h = original size)."""
    if k == 0:
        return x, y
    if k == 1:
        return w - 1 - y, x
    if k == 2:
        return w - 1 - x, h - 1 - y
    return y, h - 1 - x


def detect_all_rotations(rgb: np.ndarray, engine: OCREngine, rotations=(0, 1, 2, 3),
                         max_edge: int | None = None) -> list[TextBox]:
    max_edge = max_edge or get_settings().ocr_max_edge
    small, scale = downscale(rgb, max_edge)
    h, w = small.shape[:2]
    found: list[TextBox] = []
    for k in rotations:
        img = np.ascontiguousarray(np.rot90(small, k)) if k else small
        for box in engine.detect(img):
            pts = [_unrotate(px, py, k, w, h) for px, py in box.points]
            pts = [(px / scale, py / scale) for px, py in pts]
            found.append(TextBox(pts, box.text, box.confidence, rotation=k * 90))
    return found
