"""Schema migrations and safe import of the earlier MVP database.

`upgrade_database()` runs on every start:
1. If the database still has the MVP schema (no `alembic_version`, a `watches` table with a free-text
   `price` column) it is backed up, the old tables are renamed to `legacy_*`, and kept untouched.
2. Alembic upgrades the schema to the latest revision.
3. Rows from the `legacy_*` tables are imported once into the new tables.
"""
from __future__ import annotations

import hashlib
import logging
import re
import shutil
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from app.config import BASE_DIR, get_settings
from app.db.base import get_engine, session_scope, utcnow

log = logging.getLogger(__name__)

LEGACY_TABLES = ("watches", "assets", "channel_drafts", "audit", "publish_jobs")
LEGACY_CHANNEL_MAP = {
    "whatsapp": "whatsapp_groups",
    "facebook_groups": "facebook_groups",
    "reddit": "reddit_watchexchange",
}


def _alembic_config() -> Config:
    cfg = Config(str(BASE_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BASE_DIR / "migrations"))
    cfg.attributes["db_url"] = get_settings().db_url
    return cfg


def _is_legacy_schema() -> bool:
    insp = inspect(get_engine())
    tables = set(insp.get_table_names())
    if "alembic_version" in tables or "watches" not in tables:
        return False
    cols = {c["name"] for c in insp.get_columns("watches")}
    return "price" in cols and "price_sgd" not in cols


def _backup_sqlite() -> Path | None:
    url = get_settings().db_url
    if not url.startswith("sqlite:///"):
        return None
    db_path = Path(url.removeprefix("sqlite:///"))
    if not db_path.exists():
        return None
    try:
        backup = db_path.with_name(f"{db_path.stem}.mvp-backup-{datetime.now():%Y%m%d-%H%M%S}{db_path.suffix}")
        shutil.copy2(db_path, backup)
        return backup
    except OSError:
        return None


def _rename_legacy_tables() -> None:
    engine = get_engine()
    insp = inspect(engine)
    existing = set(insp.get_table_names())
    with engine.begin() as conn:
        for t in LEGACY_TABLES:
            if t in existing and f"legacy_{t}" not in existing:
                conn.execute(text(f'ALTER TABLE "{t}" RENAME TO "legacy_{t}"'))


def _parse_price(raw: str | None) -> Decimal | None:
    if not raw:
        return None
    cleaned = re.sub(r"[^0-9.]", "", raw.replace(",", ""))
    if not cleaned:
        return None
    try:
        return Decimal(cleaned).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


def import_legacy_data() -> dict:
    """Import rows from legacy_* tables once. Returns counts."""
    from app.db.models import Asset, AuditEvent, ChannelCopy, Watch
    from app.core.storage import media_paths, rel

    engine = get_engine()
    tables = set(inspect(engine).get_table_names())
    if "legacy_watches" not in tables:
        return {"imported": 0}
    counts = {"watches": 0, "assets": 0, "copies": 0, "audit": 0}
    with session_scope() as db:
        if db.execute(text("SELECT value FROM app_settings WHERE key='legacy_import_done'")).first():
            return {"imported": 0, "already": True}
        rows = db.execute(text("SELECT * FROM legacy_watches")).mappings().all()
        for r in rows:
            if db.get(Watch, r["id"]):
                continue
            price = _parse_price(r.get("price"))
            currency = (r.get("currency") or "SGD").upper()
            custody = r.get("custody") if r.get("custody") in ("in_hand", "consigned_offsite") else "unknown"
            w = Watch(
                id=r["id"], sku=r["sku"], brand=r["brand"], model=r["model"],
                reference=r.get("reference") or None, year=r.get("year") or None,
                condition_notes=r.get("condition") or None,
                price_sgd=price if currency == "SGD" else None,
                price_usd=price if currency == "USD" else None,
                box_papers_notes=r.get("set_details") or None,
                custody=custody, internal_notes=r.get("notes") or None,
                status="draft",
                created_by="legacy-import",
            )
            if r.get("status") in ("reserved", "sold", "withdrawn"):
                w.status = r["status"]
            db.add(w)
            counts["watches"] += 1
        db.flush()
        if "legacy_assets" in tables:
            for r in db.execute(text("SELECT * FROM legacy_assets")).mappings().all():
                src = Path(r["original"])
                if not src.is_file() or db.get(Asset, r["id"]):
                    continue
                data = src.read_bytes()
                paths = media_paths(r["watch_id"])
                dest = paths.originals / f"{r['id']}.jpg"
                if not dest.exists():
                    dest.write_bytes(data)
                db.add(Asset(
                    id=r["id"], watch_id=r["watch_id"], source="legacy-mvp",
                    original_filename=(r.get("filename") or "photo.jpg")[:255],
                    original_path=rel(dest), original_sha256=hashlib.sha256(data).hexdigest(),
                    original_bytes=len(data), original_format="JPEG",
                    warnings=["Imported from the MVP, which re-encoded originals on upload. The camera original was not kept."],
                ))
                counts["assets"] += 1
        if "legacy_channel_drafts" in tables:
            for r in db.execute(text("SELECT * FROM legacy_channel_drafts")).mappings().all():
                ch = LEGACY_CHANNEL_MAP.get(r["channel"], r["channel"])
                db.add(ChannelCopy(
                    watch_id=r["watch_id"], channel=ch,
                    sections={"body": r["copy"]}, rendered_text=r["copy"],
                    generator="legacy-mvp", version=1, content_hash="",
                ))
                counts["copies"] += 1
        if "legacy_audit" in tables:
            for r in db.execute(text("SELECT * FROM legacy_audit")).mappings().all():
                try:
                    at = datetime.fromisoformat(r["at"]).replace(tzinfo=None)
                except Exception:
                    at = utcnow()
                db.add(AuditEvent(at=at, actor="legacy-mvp", action=r["action"], watch_id=r.get("watch_id"),
                                  summary=r.get("detail") or ""))
                counts["audit"] += 1
        db.execute(text("INSERT INTO app_settings(key, value, updated_at) VALUES ('legacy_import_done', :v, :t)"),
                   {"v": '{"done": true}', "t": utcnow()})
    log.info("legacy import complete: %s", counts)
    return counts


def upgrade_database() -> dict:
    report: dict = {}
    if _is_legacy_schema():
        backup = _backup_sqlite()
        report["backup"] = str(backup) if backup else None
        _rename_legacy_tables()
        report["legacy_detected"] = True
    command.upgrade(_alembic_config(), "head")
    if "legacy_watches" in set(inspect(get_engine()).get_table_names()):
        report["legacy_import"] = import_legacy_data()
    return report
