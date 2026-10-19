"""Small image I/O helpers shared by the pipeline (numpy RGB uint8 arrays)."""
from __future__ import annotations

import io
from pathlib import Path

import cv2
import numpy as np
from PIL import Image


def load_rgb(path: Path | str) -> np.ndarray:
    with Image.open(path) as im:
        return np.asarray(im.convert("RGB")).copy()


def load_mask(path: Path | str, size: tuple[int, int] | None = None) -> np.ndarray:
    with Image.open(path) as im:
        m = im.convert("L")
        if size and m.size != size:
            m = m.resize(size, Image.Resampling.LANCZOS)
        return np.asarray(m).copy()


def save_jpeg(arr: np.ndarray, path: Path, quality: int = 92) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8), "RGB").save(buf, "JPEG", quality=quality, subsampling=0, optimize=True)
    data = buf.getvalue()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    try:
        from app.core.storage import sync_to_remote

        sync_to_remote(path, data)
    except Exception:
        pass
    return data


def save_png(arr: np.ndarray, path: Path, mode: str | None = None) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8), mode).save(buf, "PNG", optimize=False)
    data = buf.getvalue()
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(path)
    try:
        from app.core.storage import sync_to_remote

        sync_to_remote(path, data)
    except Exception:
        pass
    return data


def decode_rgb(data: bytes) -> np.ndarray:
    with Image.open(io.BytesIO(data)) as im:
        return np.asarray(im.convert("RGB")).copy()


def downscale(arr: np.ndarray, max_edge: int) -> tuple[np.ndarray, float]:
    h, w = arr.shape[:2]
    scale = min(1.0, max_edge / max(h, w))
    if scale >= 1.0:
        return arr, 1.0
    out = cv2.resize(arr, (max(1, round(w * scale)), max(1, round(h * scale))), interpolation=cv2.INTER_AREA)
    return out, scale


def thumbnail_jpeg(arr: np.ndarray, max_edge: int = 480, quality: int = 85) -> bytes:
    small, _ = downscale(arr, max_edge)
    buf = io.BytesIO()
    Image.fromarray(small, "RGB").save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def to_jpeg_bytes(arr: np.ndarray, quality: int = 92, max_edge: int | None = None) -> bytes:
    if max_edge:
        arr, _ = downscale(arr, max_edge)
    buf = io.BytesIO()
    Image.fromarray(arr.astype(np.uint8), "RGB").save(buf, "JPEG", quality=quality, subsampling=0)
    return buf.getvalue()
