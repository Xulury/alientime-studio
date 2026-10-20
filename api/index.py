"""Vercel Serverless Function entrypoint."""
from __future__ import annotations

import sys
from pathlib import Path

# Add project root to sys.path so 'app' and its modules resolve
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.main import app as fastapi_app


async def app(scope, receive, send):
    """Normalize incoming path so routes match with or without `/api` prefix."""
    if scope.get("type") == "http":
        path = scope.get("path", "")
        if not path.startswith("/api"):
            scope["path"] = f"/api{path}" if path.startswith("/") else f"/api/{path}"
    return await fastapi_app(scope, receive, send)


__all__ = ["app"]
