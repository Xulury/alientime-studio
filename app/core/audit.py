"""Audit trail: every write is recorded with who, what and when."""
from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import redact
from app.db.models import AuditEvent


def record(
    db: Session,
    actor: str,
    action: str,
    summary: str = "",
    *,
    entity_type: str | None = None,
    entity_id: str | None = None,
    watch_id: str | None = None,
    detail: dict[str, Any] | None = None,
    ip: str | None = None,
) -> AuditEvent:
    ev = AuditEvent(
        actor=actor[:160],
        action=action[:80],
        summary=redact(summary)[:2000],
        entity_type=entity_type,
        entity_id=entity_id,
        watch_id=watch_id,
        detail=detail or {},
        ip=ip,
    )
    db.add(ev)
    return ev
