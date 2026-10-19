"""Image intake: validation, hashing, duplicate detection and original preservation.

The original bytes are written exactly as received (read-only) and never modified. All processing
uses a separate *working copy*: orientation applied, metadata stripped, RGB, long edge capped.
"""
from __future__ import annotations

import io
import logging
import re
import unicodedata
import warnings
from dataclasses import dataclass, field

import numpy as np
from PIL import ExifTags, Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core import audit
from app.core.storage import media_paths, rel, sha256_bytes, write_original
from app.db.models import Asset, Watch

log = logging.getLogger(__name__)

ALLOWED_FORMATS = {"JPEG": "jpg", "MPO": "jpg", "PNG": "png", "WEBP": "webp"}
ALLOWED_MIME = {"image/jpeg", "image/png", "image/webp", "image/jpg", "application/octet-stream", ""}

try:  # optional HEIC support if pillow-heif is installed
    import pillow_heif  # type: ignore

    pillow_heif.register_heif_opener()
    ALLOWED_FORMATS["HEIF"] = "heic"
except Exception:  # pragma: no cover - optional
    pass


class UploadRejected(ValueError):
    pass


@dataclass
class IngestResult:
    status: str  # added | duplicate | rejected
    message: str
    asset: Asset | None = None
    warnings: list[str] = field(default_factory=list)


def safe_filename(name: str | None) -> str:
    name = (name or "photo").replace("\\", "/").split("/")[-1]
    name = unicodedata.normalize("NFKC", name)
    name = re.sub(r"[\x00-\x1f\x7f<>:\"|?*]", "", name).strip(" .")
    return (name or "photo")[:120]


def dhash(img: Image.Image, size: int = 8) -> str:
    g = img.convert("L").resize((size + 1, size), Image.Resampling.LANCZOS)
    a = np.asarray(g, dtype=np.int16)
    bits = (a[:, 1:] > a[:, :-1]).flatten()
    value = 0
    for b in bits:
        value = (value << 1) | int(b)
    return f"{value:016x}"


def hamming(a: str | None, b: str | None) -> int:
    if not a or not b:
        return 64
    return bin(int(a, 16) ^ int(b, 16)).count("1")


_EXIF_KEEP = {"Make", "Model", "Software", "DateTimeOriginal", "DateTime", "LensModel", "Orientation"}


def exif_summary(img: Image.Image) -> dict:
    """Camera facts useful for source detection. GPS and serial-number tags are never kept."""
    out: dict = {}
    try:
        exif = img.getexif()
    except Exception:
        return out
    if not exif:
        return out
    tags = {ExifTags.TAGS.get(k, str(k)): v for k, v in exif.items()}
    try:
        tags.update({ExifTags.TAGS.get(k, str(k)): v for k, v in exif.get_ifd(0x8769).items()})
    except Exception:
        pass
    for k in _EXIF_KEEP:
        if k in tags:
            v = tags[k]
            out[k] = v.decode("utf-8", "ignore") if isinstance(v, bytes) else str(v)[:80]
    return out


def decode_image(data: bytes) -> tuple[Image.Image, str]:
    s = get_settings()
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise UploadRejected(f"File is larger than {s.max_upload_mb} MB.")
    if len(data) < 100:
        raise UploadRejected("File is empty or too small to be a photo.")
    Image.MAX_IMAGE_PIXELS = s.max_image_pixels
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            probe = Image.open(io.BytesIO(data))
            fmt = probe.format or ""
            probe.verify()
            img = Image.open(io.BytesIO(data))
            img.load()
    except (Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise UploadRejected("Image has too many pixels to process safely.")
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError):
        raise UploadRejected("This file is not a readable JPEG, PNG or WebP image.")
    if fmt not in ALLOWED_FORMATS:
        raise UploadRejected(f"{fmt or 'This'} format is not supported. Use JPEG, PNG or WebP.")
    return img, fmt


def make_working_copy(img: Image.Image) -> tuple[Image.Image, Image.Image | None]:
    """Apply EXIF orientation, drop metadata, convert to RGB, cap size. Returns (rgb, alpha-or-None)."""
    s = get_settings()
    img = ImageOps.exif_transpose(img)
    alpha = None
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        a = rgba.getchannel("A")
        lo, hi = a.getextrema()
        if lo < 250:  # real transparency: keep it as a ready-made mask
            alpha = a
        bg = Image.new("RGB", rgba.size, (255, 255, 255))
        bg.paste(rgba, mask=a)
        rgb = bg
    else:
        rgb = img.convert("RGB")
    if max(rgb.size) > s.working_max_edge:
        scale = s.working_max_edge / max(rgb.size)
        new_size = (max(1, round(rgb.width * scale)), max(1, round(rgb.height * scale)))
        rgb = rgb.resize(new_size, Image.Resampling.LANCZOS)
        if alpha is not None:
            alpha = alpha.resize(new_size, Image.Resampling.LANCZOS)
    return rgb, alpha


def ingest_image(
    db: Session,
    watch: Watch,
    data: bytes,
    filename: str | None,
    *,
    source: str = "upload",
    actor: str = "system",
) -> IngestResult:
    name = safe_filename(filename)
    try:
        img, fmt = decode_image(data)
    except UploadRejected as e:
        return IngestResult("rejected", f"{name}: {e}")

    digest = sha256_bytes(data)
    same = db.scalar(select(Asset).where(Asset.watch_id == watch.id, Asset.original_sha256 == digest,
                                         Asset.removed_at.is_(None)))
    if same is not None:
        return IngestResult("duplicate", f"{name}: already uploaded for this watch ({same.original_filename}).",
                            asset=same)
    warns: list[str] = []
    elsewhere = db.execute(
        select(Watch.sku).join(Asset, Asset.watch_id == Watch.id)
        .where(Asset.original_sha256 == digest, Watch.id != watch.id).limit(1)
    ).scalar()
    if elsewhere:
        warns.append(f"The same file is also attached to {elsewhere}.")

    paths = media_paths(watch.id)
    asset = Asset(watch_id=watch.id, source=source, original_filename=name, original_sha256=digest,
                  original_bytes=len(data), original_format=fmt, width=img.width, height=img.height,
                  exif_summary=exif_summary(img), uploaded_by=actor, original_path="")
    db.add(asset)
    db.flush()
    original = paths.originals / f"{asset.id}.{ALLOWED_FORMATS[fmt]}"
    write_original(original, data)
    asset.original_path = rel(original)

    rgb, alpha = make_working_copy(img)
    working = paths.working / f"{asset.id}.jpg"
    rgb.save(working, "JPEG", quality=95, subsampling=0, optimize=True)
    asset.working_path = rel(working)
    asset.working_width, asset.working_height = rgb.size
    asset.phash = dhash(rgb)
    if alpha is not None:
        mask_file = paths.masks / f"{asset.id}_v1.png"
        alpha.save(mask_file, "PNG")
        asset.mask_path = rel(mask_file)
        asset.mask_version = 1
        asset.mask_source = "source_transparency"
        asset.segmentation = {"backend": "source_transparency", "note": "Mask taken from the PNG's transparency."}

    near = None
    for other in db.scalars(select(Asset).where(Asset.watch_id == watch.id, Asset.id != asset.id,
                                                Asset.removed_at.is_(None))):
        if hamming(asset.phash, other.phash) <= 5:
            near = other
            break
    if near is not None:
        asset.duplicate_of = near.id
        warns.append(f"Looks almost identical to {near.original_filename}.")
    asset.warnings = warns
    max_order = db.scalar(select(func.max(Asset.sort_order)).where(Asset.watch_id == watch.id)) or 0
    asset.sort_order = max_order + 1
    audit.record(db, actor, "photo_uploaded", f"Uploaded {name}", entity_type="asset", entity_id=asset.id,
                 watch_id=watch.id, detail={"sha256": digest, "bytes": len(data), "source": source})
    return IngestResult("added", f"{name}: uploaded.", asset=asset, warnings=warns)
