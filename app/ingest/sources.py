"""Ingestion sources.

Every source (local inbox folder, Google Drive Inbox/, Telegram, WhatsApp) implements the same small
interface so the rest of the pipeline does not care where photos came from.

Local inbox layout (inside the data folder):

    inbox/
      AT-RM-0001/          ← folder named after an existing SKU: photos attach to that watch
        IMG_0001.jpg
      Richard Mille RM 67-01/   ← any other folder name: a new draft watch is created for review
        DSC_1234.jpg
      loose-photo.jpg      ← loose files are listed but need a watch chosen in the UI
"""
from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from app.config import get_settings

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".heic"}


@dataclass
class IncomingFile:
    ref: str            # source-specific reference (relative path, Drive file id…)
    name: str
    size: int
    group: str | None   # folder / SKU hint, if any
    source: str


class IngestSource(Protocol):
    name: str

    def is_available(self) -> bool: ...
    def list_pending(self) -> list[IncomingFile]: ...
    def fetch(self, item: IncomingFile) -> bytes: ...
    def mark_imported(self, item: IncomingFile) -> None: ...


class LocalInbox:
    """A folder on this machine. Imported files are moved to inbox/_imported/<date>/."""

    name = "local_inbox"

    def __init__(self, root: Path | None = None):
        self.root = root or get_settings().inbox_dir
        self.root.mkdir(parents=True, exist_ok=True)

    def is_available(self) -> bool:
        return self.root.is_dir()

    def _safe(self, ref: str) -> Path:
        p = (self.root / ref).resolve()
        if self.root.resolve() not in p.parents:
            raise ValueError("path outside inbox")
        return p

    def list_pending(self) -> list[IncomingFile]:
        out: list[IncomingFile] = []
        for p in sorted(self.root.rglob("*")):
            if not p.is_file() or p.suffix.lower() not in IMAGE_EXT:
                continue
            relp = p.relative_to(self.root)
            if relp.parts and relp.parts[0].startswith("_"):
                continue
            group = relp.parts[0] if len(relp.parts) > 1 else None
            out.append(IncomingFile(ref=relp.as_posix(), name=p.name, size=p.stat().st_size, group=group,
                                    source=self.name))
        return out

    def fetch(self, item: IncomingFile) -> bytes:
        return self._safe(item.ref).read_bytes()

    def mark_imported(self, item: IncomingFile) -> None:
        src = self._safe(item.ref)
        dest_dir = self.root / "_imported" / datetime.now().strftime("%Y-%m-%d")
        dest = dest_dir / item.ref
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            dest = dest.with_name(f"{dest.stem}-{datetime.now():%H%M%S%f}{dest.suffix}")
        shutil.move(str(src), str(dest))
        parent = src.parent
        if parent != self.root and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()


def available_sources() -> list[IngestSource]:
    sources: list[IngestSource] = [LocalInbox()]
    try:
        from app.integrations.google import DriveInbox

        drive = DriveInbox()
        if drive.is_available():
            sources.append(drive)
    except Exception:
        pass
    return sources
