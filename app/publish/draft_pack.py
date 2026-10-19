"""Draft packs: images at platform size + copy + step-by-step instructions, as a ZIP.

Approved channels get a clean pack. Channels without a valid approval get a PREVIEW pack: images carry a
visible "PREVIEW — NOT APPROVED" watermark and the text files say so, so unapproved content cannot be
posted by accident.
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.copywriter.channels import CHANNELS
from app.db.models import ChannelCopy, Watch
from app.imaging.io import load_rgb, save_jpeg
from app.intel.facts import confirmed_facts
from app.publish.package import export_images
from app.review.approvals import active_approval, approval_valid


def watermark(path: Path) -> None:
    img = load_rgb(path)
    h, w = img.shape[:2]
    overlay = img.copy()
    text = "PREVIEW - NOT APPROVED"
    scale = w / 900
    thickness = max(2, int(scale * 3))
    (tw, th), _ = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, thickness)
    for y in range(th + 40, h, max(th * 6, 200)):
        cv2.putText(overlay, text, ((w - tw) // 2, y), cv2.FONT_HERSHEY_SIMPLEX, scale, (255, 255, 255), thickness,
                    cv2.LINE_AA)
    out = cv2.addWeighted(overlay, 0.55, img, 0.45, 0)
    save_jpeg(np.ascontiguousarray(out), path, quality=85)


def build_draft_pack(db: Session, watch: Watch, channels: list[str] | None = None) -> tuple[bytes, dict]:
    copies = {c.channel: c for c in db.scalars(select(ChannelCopy).where(ChannelCopy.watch_id == watch.id))}
    channels = [c for c in (channels or list(copies)) if c in copies and c in CHANNELS]
    buf = io.BytesIO()
    status: dict[str, str] = {}
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z, TemporaryDirectory() as tmp:
        facts = {k: (float(v) if hasattr(v, "is_integer") else v) for k, v in confirmed_facts(db, watch).items()}
        z.writestr("product.json", json.dumps({"sku": watch.sku, "facts": facts}, indent=2, default=str))
        for ch in channels:
            ch_def = CHANNELS[ch]
            copy = copies[ch]
            approved = approval_valid(db, watch, "channel", ch)
            status[ch] = "approved" if approved else "preview"
            folder = ch if approved else f"{ch}_PREVIEW_NOT_APPROVED"
            imgs = export_images(db, watch, ch, dest=Path(tmp) / ch)
            for p in imgs:
                if not approved:
                    watermark(p)
                z.write(p, f"{folder}/images/{p.name}")
            header = "" if approved else "PREVIEW — NOT APPROVED. Do not post this text.\n\n"
            if ch_def.has_title:
                z.writestr(f"{folder}/title.txt", header + (copy.sections.get("title") or ""))
            z.writestr(f"{folder}/text.txt", header + copy.rendered_text)
            appr = active_approval(db, watch.id, "channel", ch)
            steps = "\n".join(f"{i}. {s}" for i, s in enumerate(ch_def.manual_steps, 1)) or "Publish through the studio."
            z.writestr(f"{folder}/instructions.txt", "\n".join([
                f"{ch_def.name} — {watch.sku} {watch.brand} {watch.model}",
                f"Status: {'APPROVED' if approved else 'NOT APPROVED (preview only)'}",
                f"Approved by: {appr.approved_by} at {appr.approved_at:%Y-%m-%d %H:%M} UTC" if approved and appr else "",
                f"Content version: {copy.version} · hash {copy.content_hash[:12]}",
                f"Images: {len(imgs)} (first image is the cover)", "", "Steps:", steps, "",
                *(f"Note: {n}" for n in ch_def.notes),
            ]))
        z.writestr("README.txt", (
            f"Alien Time draft pack for {watch.sku} — generated {datetime.now():%Y-%m-%d %H:%M}\n"
            "Each folder holds the images (in posting order), the text and step-by-step instructions for one channel.\n"
            "Folders marked PREVIEW_NOT_APPROVED are for review only: their images are watermarked.\n"
            "Serial numbers have been redacted by the studio; still check every image before posting.\n"))
    return buf.getvalue(), status
