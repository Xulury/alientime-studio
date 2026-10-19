"""Private file storage for originals and derived images.

Paths are stored in the database relative to the data directory so the data folder can be moved.
Originals are written once, with the exact uploaded bytes, and made read-only.
"""
from __future__ import annotations

import hashlib
import os
import stat
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings


@dataclass(frozen=True)
class WatchMedia:
    root: Path
    originals: Path
    working: Path
    redacted: Path
    masks: Path
    renders: Path
    ai: Path


def media_paths(watch_id: str) -> WatchMedia:
    if not watch_id or not all(c.isalnum() for c in watch_id):
        raise ValueError("invalid watch id")
    root = get_settings().media_dir / watch_id
    wm = WatchMedia(root, root / "originals", root / "working", root / "redacted", root / "masks",
                    root / "renders", root / "ai")
    for p in (wm.originals, wm.working, wm.redacted, wm.masks, wm.renders, wm.ai):
        p.mkdir(parents=True, exist_ok=True)
    return wm


def rel(path: Path | str) -> str:
    """Path relative to the data dir (posix separators) for storage in the database."""
    p = Path(path).resolve()
    base = get_settings().studio_data_dir.resolve()
    try:
        return p.relative_to(base).as_posix()
    except ValueError:
        return str(p)


def resolve(stored: str | None) -> Path | None:
    """Resolve a stored path and make sure it stays inside the data directory."""
    if not stored:
        return None
    base = get_settings().studio_data_dir.resolve()
    p = Path(stored)
    p = (base / p).resolve() if not p.is_absolute() else p.resolve()
    if base != p and base not in p.parents:
        return None
    return p


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_original(path: Path, data: bytes) -> None:
    """Write the original once and mark it read-only. Never overwrites an existing original."""
    if path.exists():
        raise FileExistsError(f"original already exists: {path.name}")
    with open(path, "xb") as f:
        f.write(data)
    os.chmod(path, stat.S_IREAD | stat.S_IRGRP)


def atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
