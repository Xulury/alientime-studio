"""Database engine and session handling (SQLite locally, PostgreSQL-compatible)."""
from __future__ import annotations

import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

_lock = threading.Lock()
_engine: Engine | None = None
_SessionFactory: sessionmaker | None = None


class Base(DeclarativeBase):
    pass


def utcnow() -> datetime:
    """Naive UTC timestamp (stored consistently in SQLite and PostgreSQL)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") + "Z" if dt else None


def _sqlite_pragmas(dbapi_conn, _record) -> None:
    import os

    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    if os.environ.get("VERCEL") or os.environ.get("AWS_LAMBDA_FUNCTION_NAME"):
        cur.execute("PRAGMA journal_mode=MEMORY")
        cur.execute("PRAGMA synchronous=OFF")
    else:
        cur.execute("PRAGMA journal_mode=WAL")
        cur.execute("PRAGMA busy_timeout=15000")
        cur.execute("PRAGMA synchronous=NORMAL")
    cur.close()



def get_engine() -> Engine:
    global _engine, _SessionFactory
    with _lock:
        if _engine is None:
            url = get_settings().db_url
            kwargs: dict = {"future": True, "pool_pre_ping": True}
            if url.startswith("sqlite"):
                kwargs["connect_args"] = {"check_same_thread": False, "timeout": 30}
            elif "postgresql" in url or "postgres" in url:
                from sqlalchemy.pool import NullPool

                kwargs["poolclass"] = NullPool
                kwargs["connect_args"] = {"prepare_threshold": None, "connect_timeout": 5}
                kwargs["execution_options"] = {"compiled_cache": None}
            _engine = create_engine(url, **kwargs)
            if url.startswith("sqlite"):
                event.listen(_engine, "connect", _sqlite_pragmas)
            _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False, autoflush=True)
        return _engine


_tables_initialized = False


def ensure_tables() -> None:
    global _tables_initialized
    if not _tables_initialized:
        with _lock:
            if not _tables_initialized:
                _tables_initialized = True
                try:
                    eng = get_engine()
                    if str(eng.url).startswith("sqlite"):
                        from app.db import models  # noqa: F401

                        Base.metadata.create_all(bind=eng)
                except Exception as exc:
                    import logging

                    logging.getLogger("app.db").warning("Auto-create tables skipped/failed: %s", exc)


def reset_engine() -> None:
    """Dispose the engine (used by tests and after changing settings)."""
    global _engine, _SessionFactory, _tables_initialized
    with _lock:
        if _engine is not None:
            _engine.dispose()
        _engine = None
        _SessionFactory = None
        _tables_initialized = False


def SessionLocal() -> Session:  # noqa: N802 - factory-style name
    ensure_tables()
    get_engine()
    assert _SessionFactory is not None
    return _SessionFactory()


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def get_db() -> Iterator[Session]:
    """FastAPI dependency."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
