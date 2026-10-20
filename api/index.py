"""Vercel Serverless Function entrypoint."""
from __future__ import annotations

import json
import os
import sys
import traceback
from pathlib import Path

# Ensure the root project directory is at the beginning of sys.path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# Pre-import and initialize app with error capture
startup_error = None
fastapi_app = None

try:
    from app.main import app as fastapi_app
except Exception:
    startup_error = traceback.format_exc()


async def app(scope, receive, send):
    """ASGI entrypoint with diagnostic error capture and route normalization."""
    if startup_error or fastapi_app is None:
        safe_env = {
            k: v
            for k, v in os.environ.items()
            if not any(s in k.lower() for s in ("key", "secret", "token", "password", "auth"))
        }
        body = json.dumps(
            {
                "error": {
                    "code": "startup_failed",
                    "message": "FastAPI application failed to start on Vercel.",
                    "details": {
                        "traceback": startup_error,
                        "python_version": sys.version,
                        "sys_path": sys.path[:10],
                        "cwd": os.getcwd(),
                        "environment": safe_env,
                    },
                }
            },
            indent=2,
        ).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": 500,
            "headers": [
                [b"content-type", b"application/json"],
                [b"content-length", str(len(body)).encode("ascii")],
            ],
        })
        await send({"type": "http.response.body", "body": body})
        return

    # Normalize incoming path for ASGI:
    # If Vercel rewrites stripped the `/api` prefix, ensure `/api` is restored so routers match.
    if scope.get("type") == "http":
        path = scope.get("path", "")
        if not path.startswith("/api"):
            scope["path"] = f"/api{path}" if path.startswith("/") else f"/api/{path}"

    return await fastapi_app(scope, receive, send)


__all__ = ["app"]
