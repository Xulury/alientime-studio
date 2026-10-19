"""Build the exact package that is published: approved copy + approved images at platform size."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.copywriter.channels import CHANNELS
from app.core.storage import resolve
from app.db.models import AssetRender, ChannelCopy, Watch
from app.imaging.composite import PLATFORM_PRESETS, platform_image
from app.imaging.io import load_rgb, save_jpeg
from app.intel.facts import confirmed_facts
from app.publish.base import PublishPackage
from app.review.approvals import effective_gallery


def export_images(db: Session, watch: Watch, channel: str, dest: Path | None = None) -> list[Path]:
    ch = CHANNELS[channel]
    canvas, w, h = PLATFORM_PRESETS[channel]
    dest = dest or (get_settings().exports_dir / watch.id / channel)
    dest.mkdir(parents=True, exist_ok=True)
    for old in dest.glob("*.jpg"):
        old.unlink()
    out = []
    for i, a in enumerate(effective_gallery(db, watch)[: ch.max_images], 1):
        render = db.get(AssetRender, a.current_render_id)
        src = resolve(render.variants[canvas]["path"])
        img = platform_image(load_rgb(src), w, h)
        p = dest / f"{watch.sku}_{channel}_{i:02d}.jpg"
        save_jpeg(img, p, quality=90)
        out.append(p)
    return out


def build_package(db: Session, watch: Watch, channel: str, content_hash: str) -> PublishPackage:
    copy = db.scalar(select(ChannelCopy).where(ChannelCopy.watch_id == watch.id, ChannelCopy.channel == channel))
    if copy is None:
        raise ValueError("No copy for this channel.")
    return PublishPackage(
        watch_id=watch.id, sku=watch.sku, channel=channel,
        title=(copy.sections.get("title") or f"{watch.brand} {watch.model}").strip(),
        text=copy.rendered_text, sections={k: v for k, v in copy.sections.items() if not k.startswith("_")},
        facts=confirmed_facts(db, watch), images=export_images(db, watch, channel), content_hash=content_hash,
    )
