"""Vercel Serverless Function entrypoint."""
from app.main import app

# Export for ASGI serverless handlers
__all__ = ["app"]
