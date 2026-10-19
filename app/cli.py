"""Administration commands (run on the machine that hosts the studio).

    python -m app.cli migrate                 apply database migrations
    python -m app.cli create-user NAME        create the owner account (prompts for the password)
    python -m app.cli set-password NAME       reset a password (prompts)
    python -m app.cli create-token NAME [--scopes read,intake,...]   agent token for Hermes (printed once)
    python -m app.cli worker                  run the background worker on its own
    python -m app.cli run-jobs                process queued jobs once and exit
    python -m app.cli backup [--out DIR]      zip the database and media into a backup file
    python -m app.cli demo-fixtures [--out DIR]   write the SYNTHETIC reference photo sets
    python -m app.cli status                  OCR, segmentation, AI and integration status
"""
from __future__ import annotations

import argparse
import getpass
import json
import sys
import zipfile
from datetime import datetime
from pathlib import Path


def _db():
    from app.db.base import SessionLocal
    from app.db.migrate import upgrade_database

    upgrade_database()
    return SessionLocal()


def main(argv: list[str] | None = None) -> int:
    from app.config import get_settings
    from app.core.logging import configure_logging

    s = get_settings()
    configure_logging("WARNING", False)
    p = argparse.ArgumentParser(prog="studio")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("migrate")
    c = sub.add_parser("create-user")
    c.add_argument("username")
    c = sub.add_parser("set-password")
    c.add_argument("username")
    c = sub.add_parser("create-token")
    c.add_argument("name")
    c.add_argument("--scopes", default="read,intake,process,copy,request_approval")
    sub.add_parser("worker")
    sub.add_parser("run-jobs")
    c = sub.add_parser("backup")
    c.add_argument("--out", default=str(s.studio_data_dir.parent / "backups"))
    c = sub.add_parser("demo-fixtures")
    c.add_argument("--out", default=str(s.inbox_dir))
    sub.add_parser("status")
    a = p.parse_args(argv)

    if a.cmd == "migrate":
        from app.db.migrate import upgrade_database

        print(json.dumps(upgrade_database(), default=str))
        return 0
    if a.cmd in ("create-user", "set-password"):
        from app.core.security import hash_password, password_problem
        from app.db.base import utcnow
        from app.db.models import User

        db = _db()
        pw = getpass.getpass("Password: ")
        if pw != getpass.getpass("Repeat: "):
            print("Passwords do not match.")
            return 1
        problem = password_problem(pw)
        if problem:
            print(problem)
            return 1
        user = db.query(User).filter(User.username == a.username).first()
        if a.cmd == "create-user":
            if db.query(User).count() and user is None:
                print("An owner account already exists; this version supports one user.")
                return 1
            if user is None:
                user = User(username=a.username, password_hash=hash_password(pw), password_changed_at=utcnow())
                db.add(user)
        else:
            if user is None:
                print("No such user.")
                return 1
            user.password_hash = hash_password(pw)
            user.password_changed_at = utcnow()
            user.locked_until = None
            user.failed_login_count = 0
        db.commit()
        print("Saved.")
        return 0
    if a.cmd == "create-token":
        from app.api.deps import ALL_SCOPES
        from app.core.security import new_secret_token, token_digest
        from app.db.models import ApiToken

        scopes = [x.strip() for x in a.scopes.split(",") if x.strip()]
        bad = [x for x in scopes if x not in ALL_SCOPES]
        if bad:
            print(f"Unknown scopes: {bad}. Available: {', '.join(ALL_SCOPES)}")
            return 1
        db = _db()
        raw = new_secret_token("at_")
        db.add(ApiToken(name=a.name, token_prefix=raw[:9], token_hash=token_digest(raw), scopes=scopes, created_by="cli"))
        db.commit()
        print(f"Token for {a.name} (shown once):\n{raw}")
        return 0
    if a.cmd == "worker":
        from app.jobs.worker import main as worker_main

        worker_main()
        return 0
    if a.cmd == "run-jobs":
        _db().close()
        from app.jobs.queue import run_pending

        done = run_pending()
        print(json.dumps([{"id": j.id, "type": j.type, "status": j.status, "error": j.error} for j in done]))
        return 0
    if a.cmd == "backup":
        out = Path(a.out)
        out.mkdir(parents=True, exist_ok=True)
        target = out / f"studio-backup-{datetime.now():%Y%m%d-%H%M%S}.zip"
        import sqlite3

        db_path = s.studio_data_dir / "studio.db"
        tmp = s.studio_data_dir / "studio.backup.db"
        if db_path.exists():
            src = sqlite3.connect(db_path)
            dst = sqlite3.connect(tmp)
            src.backup(dst)
            dst.close()
            src.close()
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as z:
            if tmp.exists():
                z.write(tmp, "studio.db")
            for f in (s.studio_data_dir / "media").rglob("*"):
                if f.is_file() and "/cache/" not in f.as_posix():
                    z.write(f, f.relative_to(s.studio_data_dir).as_posix())
        tmp.unlink(missing_ok=True)
        print(f"Backup written to {target}")
        return 0
    if a.cmd == "demo-fixtures":
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from tests.fixtures.synthetic import write_reference_sets

        paths = write_reference_sets(Path(a.out))
        print(f"Wrote {len(paths)} SYNTHETIC photos to {a.out}")
        return 0
    if a.cmd == "status":
        from app.api.config_api import system_status
        from app.integrations.registry import all_integrations
        from app.providers.registry import get_provider

        db = _db()
        print(json.dumps({"system": system_status(), "ai": {"provider": get_provider().name,
                                                           "available": get_provider().available,
                                                           "models": get_provider().models()},
                          "integrations": {i.name: i.info(db).state for i in all_integrations()}}, indent=2, default=str))
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
