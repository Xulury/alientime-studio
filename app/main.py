"""Alien Time Listing Studio — FastAPI application.

Run locally:  uvicorn app.main:app --host 127.0.0.1 --port 8000
"""
from __future__ import annotations

import logging
import mimetypes
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.staticfiles import StaticFiles

from app.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging

log = logging.getLogger("app")
WEB_DIR = Path(__file__).resolve().parent / "web"

# Python guesses file types from the operating system. On many Windows PCs the registry maps .js to
# "text/plain", and browsers then refuse to run the web interface (blank page). Set the types ourselves.
WEB_MIME_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".html": "text/html",
    ".json": "application/json",
    ".svg": "image/svg+xml",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".map": "application/json",
}


def register_mime_types() -> None:
    for ext, mime in WEB_MIME_TYPES.items():
        mimetypes.add_type(mime, ext)


register_mime_types()


def web_media_type(path: str | Path) -> str | None:
    mime = WEB_MIME_TYPES.get(Path(path).suffix.lower())
    if mime and (mime.startswith("text/") or mime == "application/json"):
        mime += "; charset=utf-8"
    return mime


class WebStaticFiles(StaticFiles):
    """The built interface's assets, with fixed content types whatever the operating system's file-type table says.

    File names contain a content hash, so they can be cached for good. We always send the full file instead of
    "304 Not Modified": a browser that cached a file with a wrong type earlier then picks up the right one.
    """

    def file_response(self, full_path, stat_result, scope, status_code: int = 200):
        response = FileResponse(full_path, status_code=status_code, stat_result=stat_result,
                                media_type=web_media_type(full_path))
        response.headers["cache-control"] = "public, max-age=31536000, immutable"
        return response

CSP = ("default-src 'self'; img-src 'self' data: blob:; style-src 'self' 'unsafe-inline'; font-src 'self' data:; "
       "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; object-src 'none'; base-uri 'self'; "
       "form-action 'self'")


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        h = response.headers
        h.setdefault("Content-Security-Policy", CSP)
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("Referrer-Policy", "same-origin")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()")
        h.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        if request.url.path.startswith("/api/") and "cache-control" not in h:
            h["Cache-Control"] = "no-store"
        if get_settings().studio_cookie_secure:
            h.setdefault("Strict-Transport-Security", "max-age=31536000")
        return response


def _error(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "details": details or {}}}, status_code=status)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    configure_logging(s.studio_log_level, s.studio_log_json)
    s.ensure_dirs()
    from app.db.migrate import upgrade_database

    report = upgrade_database()
    if report.get("legacy_detected"):
        log.info("Imported data from the earlier MVP: %s", report)
    worker = None
    if s.worker_mode == "thread" and not s.is_test:
        from app.jobs.worker import Worker

        worker = Worker(concurrency=s.worker_concurrency)
        worker.start()
    app.state.worker = worker
    log.info("Alien Time Listing Studio started (data: %s)", s.studio_data_dir)
    yield
    if worker is not None:
        worker.stop()


def create_app() -> FastAPI:
    register_mime_types()
    app = FastAPI(title="Alien Time Listing Studio", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(SecurityHeaders)

    @app.exception_handler(AppError)
    async def _app_error(_request: Request, exc: AppError):
        return _error(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(HTTPException)
    async def _http_error(_request: Request, exc: HTTPException):
        msg = exc.detail if isinstance(exc.detail, str) else "Request failed."
        return _error(exc.status_code, "http_error", msg)

    @app.exception_handler(RequestValidationError)
    async def _validation(_request: Request, exc: RequestValidationError):
        errs = exc.errors()
        first = errs[0] if errs else {}
        loc = ".".join(str(x) for x in first.get("loc", []) if x not in ("body", "query", "path"))
        msg = f"{loc}: {first.get('msg', 'invalid value')}" if loc else first.get("msg", "Invalid request.")
        return _error(422, "validation_error", msg, {"errors": [{"loc": e.get("loc"), "msg": e.get("msg")} for e in errs[:10]]})

    @app.exception_handler(Exception)
    async def _unhandled(_request: Request, exc: Exception):
        ref = uuid.uuid4().hex[:8]
        log.exception("unhandled error %s", ref)
        return _error(500, "server_error", f"Something went wrong on the server (reference {ref}). It has been logged.")

    from app.api import assets, auth, config_api, listings, publishing, review, system, watches, webhooks

    for r in (auth.router, system.router, watches.router, assets.router, listings.router, review.router,
              publishing.router, config_api.router, webhooks.router):
        app.include_router(r)

    if (WEB_DIR / "assets").is_dir():
        app.mount("/assets", WebStaticFiles(directory=str(WEB_DIR / "assets")), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str):
        if full_path.startswith("api/"):
            return _error(404, "not_found", "Not found.")
        candidate = (WEB_DIR / full_path).resolve()
        if full_path and WEB_DIR in candidate.parents and candidate.is_file():
            return FileResponse(candidate, media_type=web_media_type(candidate))
        index = WEB_DIR / "index.html"
        if index.is_file():
            return FileResponse(index, media_type="text/html; charset=utf-8", headers={"Cache-Control": "no-cache"})
        return HTMLResponse("<h1>Alien Time Listing Studio</h1><p>The web interface has not been built. "
                            "Run <code>npm install && npm run build</code> in <code>frontend/</code>.</p>")

    return app


app = create_app()
