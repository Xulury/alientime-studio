"""Sign-in, first-run setup, sign-out and password change."""
from __future__ import annotations

import ipaddress
import secrets
from datetime import timedelta

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import SESSION_COOKIE, Principal, client_ip, get_principal, login_rate_limited
from app.config import get_settings
from app.core import audit
from app.core.errors import AppError, Forbidden, Unauthorized
from app.core.security import (
    constant_time_equals,
    hash_password,
    new_secret_token,
    password_problem,
    token_digest,
    verify_password,
)
from app.db.base import get_db, iso, utcnow
from app.db.models import User, UserSession

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginIn(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class SetupIn(BaseModel):
    username: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9_.@-]+$")
    display_name: str = Field(default="", max_length=120)
    password: str = Field(min_length=1, max_length=256)
    setup_token: str | None = None


class RegisterIn(BaseModel):
    username: str = Field(min_length=2, max_length=80, pattern=r"^[A-Za-z0-9_.@-]+$")
    display_name: str = Field(default="", max_length=120)
    password: str = Field(min_length=1, max_length=256)


class PasswordIn(BaseModel):
    current_password: str
    new_password: str = Field(max_length=256)


def _is_loopback(ip: str | None) -> bool:
    if not ip:
        return False
    if ip == "testclient":
        return True
    try:
        return ipaddress.ip_address(ip).is_loopback
    except ValueError:
        return False


def _user_count(db: Session) -> int:
    return db.scalar(select(func.count()).select_from(User)) or 0


def _start_session(db: Session, response: Response, user: User, request: Request) -> UserSession:
    s = get_settings()
    raw = new_secret_token()
    sess = UserSession(
        id=token_digest(raw), user_id=user.id, csrf_token=secrets.token_urlsafe(32),
        expires_at=utcnow() + timedelta(hours=s.studio_session_hours), ip=client_ip(request),
        user_agent=(request.headers.get("user-agent") or "")[:255],
    )
    db.add(sess)
    is_secure = s.studio_cookie_secure or (request.headers.get("x-forwarded-proto") == "https")
    response.set_cookie(
        SESSION_COOKIE, raw, httponly=True, samesite="strict", secure=is_secure,
        max_age=s.studio_session_hours * 3600, path="/",
    )
    return sess


def _user_view(user: User) -> dict:
    return {"username": user.username, "display_name": user.display_name or user.username,
            "last_login_at": iso(user.last_login_at)}


@router.get("/state")
def auth_state(request: Request, db: Session = Depends(get_db)) -> dict:
    setup_required = _user_count(db) == 0
    out = {"authenticated": False, "setup_required": setup_required, "user": None, "csrf_token": None,
           "setup_allowed_here": setup_required and (_is_loopback(client_ip(request))
                                                     or get_settings().studio_allow_remote_setup)}
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        sess = db.get(UserSession, token_digest(cookie))
        if sess and sess.expires_at > utcnow():
            user = db.get(User, sess.user_id)
            if user:
                out.update(authenticated=True, user=_user_view(user), csrf_token=sess.csrf_token)
    return out


@router.post("/setup")
def setup(body: SetupIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    if _user_count(db) > 0:
        raise Forbidden("The studio account already exists. Sign in instead.")
    token_ok = bool(s.studio_setup_token and body.setup_token and
                    constant_time_equals(body.setup_token, s.studio_setup_token.get_secret_value()))
    if not (_is_loopback(client_ip(request)) or s.studio_allow_remote_setup or token_ok):
        raise Forbidden("First-time setup must be done on the computer running the studio.")
    problem = password_problem(body.password)
    if problem:
        raise AppError(problem, code="weak_password")
    user = User(username=body.username.strip(), display_name=body.display_name.strip(),
                password_hash=hash_password(body.password), password_changed_at=utcnow(), last_login_at=utcnow())
    db.add(user)
    db.flush()
    sess = _start_session(db, response, user, request)
    audit.record(db, f"user:{user.username}", "account_created", "Studio account created", ip=client_ip(request))
    db.commit()
    return {"authenticated": True, "user": _user_view(user), "csrf_token": sess.csrf_token}


@router.post("/register")
def register(body: RegisterIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    try:
        existing = db.scalar(select(User).where(func.lower(User.username) == body.username.strip().lower()))
        if existing:
            raise AppError("That username is already taken.", code="username_taken", status_code=400)
        problem = password_problem(body.password)
        if problem:
            raise AppError(problem, code="weak_password")
        user = User(
            username=body.username.strip(),
            display_name=body.display_name.strip(),
            password_hash=hash_password(body.password),
            password_changed_at=utcnow(),
            last_login_at=utcnow(),
            role="owner" if _user_count(db) == 0 else "user",
        )
        db.add(user)
        db.flush()
        sess = _start_session(db, response, user, request)
        audit.record(db, f"user:{user.username}", "account_created", "Studio account created", ip=client_ip(request))
        db.commit()
        return {"authenticated": True, "user": _user_view(user), "csrf_token": sess.csrf_token}
    except AppError:
        raise
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        db.rollback()
        raise AppError(
            f"Registration failed: {type(exc).__name__}: {str(exc)}",
            code="registration_db_error",
            status_code=500,
            details={"type": type(exc).__name__, "message": str(exc), "traceback": tb},
        )


@router.post("/guest")
def guest_login(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    try:
        guest = db.scalar(select(User).where(func.lower(User.username) == "guest"))
        if not guest:
            guest = User(
                username="guest",
                display_name="Guest User",
                password_hash=hash_password(secrets.token_hex(16)),
                role="owner",
                password_changed_at=utcnow(),
                last_login_at=utcnow(),
            )
            db.add(guest)
            db.flush()
        else:
            guest.last_login_at = utcnow()
        sess = _start_session(db, response, guest, request)
        audit.record(db, "user:guest", "guest_sign_in", "Signed in as guest", ip=client_ip(request))
        db.commit()
        return {"authenticated": True, "user": _user_view(guest), "csrf_token": sess.csrf_token}
    except Exception as exc:
        import traceback
        tb = traceback.format_exc()
        db.rollback()
        raise AppError(
            f"Guest login failed: {type(exc).__name__}: {str(exc)}",
            code="guest_login_failed",
            status_code=500,
            details={"type": type(exc).__name__, "message": str(exc), "traceback": tb},
        )


@router.post("/login")
def login(body: LoginIn, request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    s = get_settings()
    ip = client_ip(request)
    if login_rate_limited(ip):
        raise AppError("Too many sign-in attempts. Wait a few minutes and try again.", code="rate_limited",
                       status_code=429)
    user = db.scalar(select(User).where(func.lower(User.username) == body.username.strip().lower()))
    if user and user.locked_until and user.locked_until > utcnow():
        raise AppError("This account is temporarily locked after repeated failed sign-ins. Try again later.",
                       code="locked", status_code=429)
    if user is None or not verify_password(body.password, user.password_hash):
        if user is not None:
            user.failed_login_count += 1
            if user.failed_login_count >= s.studio_login_max_failures:
                user.locked_until = utcnow() + timedelta(minutes=s.studio_login_lock_minutes)
                user.failed_login_count = 0
                audit.record(db, "system", "account_locked", "Account locked after repeated failed sign-ins", ip=ip)
            db.commit()
        raise Unauthorized("The username or password is incorrect.")
    user.failed_login_count = 0
    user.locked_until = None
    user.last_login_at = utcnow()
    sess = _start_session(db, response, user, request)
    audit.record(db, f"user:{user.username}", "signed_in", "Signed in", ip=ip)
    db.commit()
    return {"authenticated": True, "user": _user_view(user), "csrf_token": sess.csrf_token}


@router.post("/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)) -> dict:
    cookie = request.cookies.get(SESSION_COOKIE)
    if cookie:
        sess = db.get(UserSession, token_digest(cookie))
        if sess:
            db.delete(sess)
            db.commit()
    response.delete_cookie(SESSION_COOKIE, path="/")
    return {"authenticated": False}


@router.post("/password")
def change_password(body: PasswordIn, request: Request, principal: Principal = Depends(get_principal),
                    db: Session = Depends(get_db)) -> dict:
    if principal.kind != "user":
        raise Forbidden("Only the account owner can change the password.")
    user = db.get(User, principal.user_id)
    if user is None or not verify_password(body.current_password, user.password_hash):
        raise AppError("The current password is incorrect.", code="wrong_password")
    problem = password_problem(body.new_password)
    if problem:
        raise AppError(problem, code="weak_password")
    user.password_hash = hash_password(body.new_password)
    user.password_changed_at = utcnow()
    # sign out every other session
    current = request.cookies.get(SESSION_COOKIE)
    keep = token_digest(current) if current else None
    for sess in db.scalars(select(UserSession).where(UserSession.user_id == user.id)):
        if sess.id != keep:
            db.delete(sess)
    audit.record(db, principal.actor, "password_changed", "Password changed; other sessions signed out",
                 ip=principal.ip)
    db.commit()
    return {"ok": True}
