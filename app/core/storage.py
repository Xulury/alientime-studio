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
    if not watch_id or not all(c.isalnum() or c in "_-" for c in watch_id):
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


def stored_to_remote(stored: str | Path | None) -> str | None:
    """Map a local relative storage path like 'media/w123/originals/a1.jpg' 
    to Supabase Storage path '{watch_folder}/originals/a1.jpg'."""
    if not stored:
        return None
    from app.core import supabase_storage

    s = str(stored).replace("\\", "/").strip("/")
    parts = s.split("/")
    if len(parts) >= 3 and parts[0] == "media":
        watch_id = parts[1]
        subpath = "/".join(parts[2:])
        folder = supabase_storage.get_watch_storage_prefix(watch_id)
        return f"{folder}/{subpath}"
    return s


def sync_to_remote(path: Path | str, data: bytes | None = None) -> str | None:
    """Upload file to Supabase Storage if configured."""
    from app.core import supabase_storage

    if not supabase_storage.is_storage_configured():
        return None
    try:
        p = Path(path)
        stored = rel(p)
        remote_path = stored_to_remote(stored)
        if not remote_path:
            return None
        if data is None and p.is_file():
            data = p.read_bytes()
        if not data:
            return None
        ext = p.suffix.lower()
        content_types = {
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".png": "image/png",
            ".webp": "image/webp",
            ".heic": "image/heic",
        }
        content_type = content_types.get(ext, "application/octet-stream")
        return supabase_storage.upload_bytes(remote_path, data, content_type)
    except Exception as e:
        import logging

        logging.getLogger(__name__).warning("Failed to sync file %s to Supabase Storage: %s", path, e)
        return None


def resolve(stored: str | None) -> Path | None:
    """Resolve a stored path and make sure it stays inside the data directory."""
    if not stored:
        return None
    base = get_settings().studio_data_dir.resolve()
    p = Path(stored)
    p = (base / p).resolve() if not p.is_absolute() else p.resolve()
    if base != p and base not in p.parents:
        return None
    if not p.is_file():
        from app.core import supabase_storage

        if supabase_storage.is_storage_configured():
            remote = stored_to_remote(stored)
            if remote:
                data = supabase_storage.download_bytes(remote)
                if data:
                    try:
                        p.parent.mkdir(parents=True, exist_ok=True)
                        with open(p, "wb") as f:
                            f.write(data)
                    except Exception:
                        pass
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
    try:
        os.chmod(path, stat.S_IREAD | stat.S_IRGRP)
    except OSError:
        pass
    sync_to_remote(path, data)


def atomic_write(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, path)
    sync_to_remote(path, data)
