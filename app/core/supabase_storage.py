"""Supabase Storage integration for watch photos.

Bucket: 'watch-photos' (public)
Folder structure: '{watch_name}_{session_id}/{variant}/{filename}'
"""
from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any

from app.config import get_settings

log = logging.getLogger(__name__)

# In-memory mapping from watch_id to sanitized folder prefix
_FOLDER_CACHE: dict[str, str] = {}


def sanitize_slug(text: str) -> str:
    """Sanitize text to be safe in URL paths and storage folders."""
    text = (text or "").strip()
    text = re.sub(r"[^a-zA-Z0-9_\-]+", "_", text)
    return text.strip("_")


def get_watch_storage_prefix(
    watch_id: str,
    brand: str | None = None,
    model: str | None = None,
    reference: str | None = None,
    sku: str | None = None,
) -> str:
    """Generate the folder name for a watch: '{watch_name}_{session_or_watch_id}'."""
    if watch_id in _FOLDER_CACHE and not (brand or model):
        return _FOLDER_CACHE[watch_id]

    if not (brand or model or reference or sku):
        try:
            from app.db.base import session_scope
            from app.db.models import Watch

            with session_scope() as session:
                w = session.get(Watch, watch_id)
                if w is not None:
                    brand = w.brand
                    model = w.model
                    reference = w.reference
                    sku = w.sku
        except Exception:
            pass

    parts: list[str] = []
    if brand:
        parts.append(sanitize_slug(brand))
    if model:
        parts.append(sanitize_slug(model))
    if reference:
        parts.append(sanitize_slug(reference))

    if parts:
        watch_name = "_".join(parts)
    elif sku:
        watch_name = sanitize_slug(sku)
    else:
        watch_name = "Watch"

    session_id = watch_id.strip()
    folder = f"{watch_name}_{session_id}"
    _FOLDER_CACHE[watch_id] = folder
    return folder


def register_watch_folder(watch_id: str, folder: str) -> None:
    _FOLDER_CACHE[watch_id] = folder


@lru_cache(maxsize=1)
def get_supabase_client() -> Any:
    s = get_settings()
    url = s.supabase_url
    key = s.supabase_key.get_secret_value() if s.supabase_key else None
    if not url or not key:
        return None
    try:
        from supabase import create_client
        return create_client(url, key)
    except Exception as e:
        log.warning("Could not initialize Supabase client: %s", e)
        return None


def is_storage_configured() -> bool:
    s = get_settings()
    return bool(s.supabase_url and s.supabase_key)


def get_bucket_name() -> str:
    return getattr(get_settings(), "supabase_storage_bucket", "watch-photos") or "watch-photos"


def get_public_url(remote_path: str) -> str:
    """Return the direct public CDN URL for a file in watch-photos."""
    s = get_settings()
    base = (s.supabase_url or "").rstrip("/")
    bucket = get_bucket_name()
    path = remote_path.lstrip("/")
    return f"{base}/storage/v1/object/public/{bucket}/{path}"


def upload_bytes(remote_path: str, data: bytes, content_type: str = "image/jpeg") -> str | None:
    """Upload binary data to the Supabase Storage bucket. Returns public URL or None on failure."""
    client = get_supabase_client()
    if client is None:
        return None
    bucket_name = get_bucket_name()
    clean_path = remote_path.lstrip("/")
    try:
        bucket = client.storage.from_(bucket_name)
        bucket.upload(
            clean_path,
            data,
            file_options={"content-type": content_type, "upsert": "true"},
        )
        return get_public_url(clean_path)
    except Exception as e:
        log.warning("Supabase Storage upload failed for %s: %s", clean_path, e)
        return None


def download_bytes(remote_path: str) -> bytes | None:
    """Download binary data from the Supabase Storage bucket. Returns bytes or None."""
    client = get_supabase_client()
    if client is None:
        return None
    bucket_name = get_bucket_name()
    clean_path = remote_path.lstrip("/")
    try:
        bucket = client.storage.from_(bucket_name)
        res = bucket.download(clean_path)
        return res
    except Exception as e:
        log.warning("Supabase Storage download failed for %s: %s", clean_path, e)
        return None


def delete_file(remote_path: str) -> bool:
    """Delete a file from Supabase Storage."""
    client = get_supabase_client()
    if client is None:
        return False
    bucket_name = get_bucket_name()
    clean_path = remote_path.lstrip("/")
    try:
        bucket = client.storage.from_(bucket_name)
        bucket.remove([clean_path])
        return True
    except Exception as e:
        log.warning("Supabase Storage delete failed for %s: %s", clean_path, e)
        return False
