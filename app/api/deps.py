"""Authentication, CSRF and permission checks shared by all API routes."""
from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import timedelta

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import get_settings
from app.core.errors import Forbidden, Unauthorized
from app.core.security import constant_time_equals, token_digest
from app.db.base import get_db, utcnow
from app.db.models import ApiToken, User, UserSession

SESSION_COOKIE = "at_session"
CSRF_HEADER = "x-csrf-token"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

ALL_SCOPES = {
    "read": "See inventory, photos, copy, jobs and status",
    "intake": "Create watches and upload photos",
    "process": "Run photo processing and AI analysis",
    "copy": "Generate and edit listing copy",
    "request_approval": "Ask for approval (sends a notification)",
    "approve": "Approve images, channels and packages",
    "publish": "Publish approved listings",
    "lifecycle": "Mark watches reserved, sold, withdrawn or available",
    "settings": "Change settings, integrations and tokens",
}
# Actions an agent may only take on behalf of an allow-listed Telegram admin.
ADMIN_SCOPES = {"approve", "publish", "lifecycle", "settings"}
DEFAULT_AGENT_SCOPES = ["read", "intake", "process", "copy", "request_approval"]


@dataclass
class Principal:
    kind: str  # user | token
    name: str
    scopes: set[str] = field(default_factory=set)
    user_id: int | None = None
    token_id: int | None = None
    acting_user: str | None = None
    csrf_token: str | None = None
    ip: str | None = None

    @property
    def actor(self) -> str:
        if self.kind == "user":
            return f"user:{self.name}"
        base = f"agent:{self.name}"
        return f"{base} for telegram:{self.acting_user}" if self.acting_user else base


def client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


def get_principal(request: Request, db: Session = Depends(get_db)) -> Principal:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        raw = auth[7:].strip()
        tok = db.query(ApiToken).filter(ApiToken.token_hash == token_digest(raw)).first()
        if tok is None or tok.revoked_at is not None:
            raise Unauthorized("The API token is not valid.")
        if not tok.last_used_at or utcnow() - tok.last_used_at > timedelta(minutes=1):
            tok.last_used_at = utcnow()
            db.commit()
        acting = (request.headers.get("x-acting-user") or "").strip() or None
        return Principal("token", tok.name, set(tok.scopes or []), token_id=tok.id, acting_user=acting,
                         ip=client_ip(request))

    cookie = request.cookies.get(SESSION_COOKIE)
    if not cookie:
        raise Unauthorized("Please sign in.")
    sess = db.get(UserSession, token_digest(cookie))
    if sess is None or sess.expires_at < utcnow():
        raise Unauthorized("Your session has ended. Please sign in again.")
    if request.method not in SAFE_METHODS:
        sent = request.headers.get(CSRF_HEADER, "")
        if not sent or not constant_time_equals(sent, sess.csrf_token):
            raise Forbidden("Security check failed. Refresh the page and try again.", code="csrf_failed")
    if utcnow() - sess.last_seen_at > timedelta(minutes=5):
        sess.last_seen_at = utcnow()
        db.commit()
    user = db.get(User, sess.user_id)
    if user is None:
        raise Unauthorized("Please sign in.")
    return Principal("user", user.username, set(ALL_SCOPES), user_id=user.id, csrf_token=sess.csrf_token,
                     ip=client_ip(request))


def require(scope: str):
    """Dependency factory: the caller must hold `scope`.

    Agents (API tokens) performing approve/publish/lifecycle/settings actions must also name the
    Telegram user they act for in `X-Acting-User`, and that user must be in TELEGRAM_ADMIN_USERS.
    With no admins configured, agents cannot perform these actions at all (fail closed).
    """

    def dep(principal: Principal = Depends(get_principal)) -> Principal:
        if scope not in principal.scopes:
            raise Forbidden(f"This action needs the '{scope}' permission.")
        if principal.kind == "token" and scope in ADMIN_SCOPES:
            admins = get_settings().telegram_admin_user_ids
            if not admins:
                raise Forbidden("Agents cannot perform this action until TELEGRAM_ADMIN_USERS is configured.")
            if not principal.acting_user or principal.acting_user not in admins:
                raise Forbidden("This action must be requested by an allow-listed admin.")
        return principal

    return dep


def require_person(scope: str):
    """Like `require`, but only a person signed in to the web app may do it — never an agent token.
    Used for the serial-number check and redaction edits: OCR alone is not proof, a human must look."""
    inner = require(scope)

    def dep(principal: Principal = Depends(inner)) -> Principal:
        if principal.kind != "user":
            raise Forbidden("Only a person signed in to the studio can do this; agents cannot.")
        return principal

    return dep


# ---- simple in-memory rate limiter for the login endpoint ----------------------------------------
_attempts: dict[str, deque] = defaultdict(deque)


def login_rate_limited(ip: str | None, limit: int = 12, window_s: int = 300) -> bool:
    key = ip or "unknown"
    q = _attempts[key]
    now = time.monotonic()
    while q and now - q[0] > window_s:
        q.popleft()
    if len(q) >= limit:
        return True
    q.append(now)
    return False


def reset_rate_limits() -> None:
    _attempts.clear()
