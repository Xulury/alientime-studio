"""Common integration interface and honest connection states.

States:
  not_configured – required environment variables are missing
  configured     – credentials present but not yet verified with a live call
  connected      – the last live test call succeeded
  error          – the last live test call failed (message says why)
  unsupported    – the requested operation is not offered by the platform's official API
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import httpx
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.base import iso, utcnow
from app.db.models import IntegrationStatus

NOT_CONFIGURED, CONFIGURED, CONNECTED, ERROR, UNSUPPORTED = "not_configured", "configured", "connected", "error", "unsupported"
STATE_LABELS = {NOT_CONFIGURED: "Not configured", CONFIGURED: "Configured (not tested)", CONNECTED: "Connected",
                ERROR: "Error", UNSUPPORTED: "Unsupported"}

# Tests inject an httpx.MockTransport here; production uses the network.
HTTP_TRANSPORT: httpx.BaseTransport | None = None


def http_client(timeout: float = 30.0, **kw) -> httpx.Client:
    return httpx.Client(timeout=timeout, transport=HTTP_TRANSPORT, follow_redirects=False, **kw)


class UnsupportedOperation(RuntimeError):
    pass


class IntegrationError(RuntimeError):
    def __init__(self, message: str, *, retryable: bool = False):
        super().__init__(message)
        self.retryable = retryable


@dataclass
class TestResult:
    ok: bool
    message: str
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class IntegrationInfo:
    name: str
    label: str
    kind: str
    state: str
    state_label: str
    message: str | None
    checked_at: str | None
    live_enabled: bool
    required_env: list[str]
    missing_env: list[str]
    capabilities: list[str]
    notes: list[str]

    def as_dict(self) -> dict:
        return asdict(self)


class Integration:
    name = "base"
    label = "Integration"
    kind = "other"
    required_env: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @property
    def settings(self):
        return get_settings()

    def _env_value(self, env: str):
        v = getattr(self.settings, env.lower(), None)
        if v is not None and hasattr(v, "get_secret_value"):
            v = v.get_secret_value()
        return v

    def missing_env(self) -> list[str]:
        return [e for e in self.required_env if not self._env_value(e)]

    def is_configured(self) -> bool:
        return not self.missing_env()

    def test(self) -> TestResult:  # pragma: no cover - overridden
        raise NotImplementedError

    def info(self, db: Session) -> IntegrationInfo:
        row = db.get(IntegrationStatus, self.name)
        missing = self.missing_env()
        if missing:
            state, msg = NOT_CONFIGURED, f"Missing: {', '.join(missing)}"
        elif row is None or row.state in (NOT_CONFIGURED,):
            state, msg = CONFIGURED, "Credentials present. Run a connection test."
        else:
            state, msg = row.state, row.message
        return IntegrationInfo(self.name, self.label, self.kind, state, STATE_LABELS[state], msg,
                               iso(row.checked_at) if row else None, bool(row.live_enabled) if row and not missing else False,
                               list(self.required_env), missing, list(self.capabilities), list(self.notes))

    def run_test(self, db: Session) -> IntegrationInfo:
        if not self.is_configured():
            record(db, self.name, NOT_CONFIGURED, f"Missing: {', '.join(self.missing_env())}")
            return self.info(db)
        try:
            res = self.test()
            record(db, self.name, CONNECTED if res.ok else ERROR, res.message, res.details)
        except Exception as e:  # noqa: BLE001
            from app.core.logging import redact

            record(db, self.name, ERROR, redact(f"{type(e).__name__}: {e}")[:500])
        return self.info(db)

    def is_connected(self, db: Session) -> bool:
        return self.info(db).state == CONNECTED


def record(db: Session, name: str, state: str, message: str | None, details: dict | None = None) -> IntegrationStatus:
    row = db.get(IntegrationStatus, name)
    if row is None:
        row = IntegrationStatus(name=name)
        db.add(row)
    row.state = state
    row.message = (message or "")[:1000]
    row.details = details or {}
    row.checked_at = utcnow()
    if state != CONNECTED:
        row.live_enabled = False
    return row


def set_live_enabled(db: Session, name: str, enabled: bool) -> IntegrationStatus:
    row = db.get(IntegrationStatus, name)
    if row is None:
        row = IntegrationStatus(name=name, state=NOT_CONFIGURED)
        db.add(row)
    row.live_enabled = enabled
    return row
