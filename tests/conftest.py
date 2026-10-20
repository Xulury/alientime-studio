"""Shared test fixtures.

Every test gets a fresh data folder and database, the mock AI provider, GrabCut segmentation (no model
download) and the real local OCR engine when it is installed.
"""
from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

os.environ.update({
    "STUDIO_ENV": "test",
    "WORKER_MODE": "off",
    "AI_PROVIDER": "mock",
    "SEGMENTATION_BACKEND": "grabcut",
    "STUDIO_LOG_LEVEL": "WARNING",
    "STUDIO_LOG_JSON": "false",
    "ENABLE_SIMULATED_PUBLISHING": "true",
    "OCR_MAX_EDGE": "1600",
})
for k in list(os.environ):
    if k.startswith(("OPENAI_", "SHOPIFY_", "META_", "IG_", "FB_", "EBAY_", "R2_", "TELEGRAM_", "WHATSAPP_",
                     "GOOGLE_", "DRIVE_", "FACTS_", "CHRONO24_", "CLOUDFLARE_")) or k in ("DATABASE_URL", "SUPABASE_URL", "SUPABASE_KEY"):
        del os.environ[k]


import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

import app.jobs.handlers  # noqa: E402,F401  (register job handlers)
from app.config import Settings, reset_settings_cache  # noqa: E402
from app.db.base import reset_engine  # noqa: E402
from app.providers.registry import reset_provider  # noqa: E402

# Tests must not reload production credentials from the developer's .env after the environment
# above has been cleared. In particular, no fixture may contact the real database or photo bucket.
Settings.model_config["env_file"] = None

PASSWORD = "correct horse battery staple"


class Studio:
    def __init__(self, client: TestClient, csrf: str, data_dir: Path):
        self.client = client
        self.csrf = csrf
        self.data_dir = data_dir

    def _h(self, headers=None):
        return {"x-csrf-token": self.csrf, **(headers or {})}

    def get(self, url, **kw):
        return self.client.get(url, **kw)

    def post(self, url, **kw):
        kw["headers"] = self._h(kw.get("headers"))
        return self.client.post(url, **kw)

    def put(self, url, **kw):
        kw["headers"] = self._h(kw.get("headers"))
        return self.client.put(url, **kw)

    def patch(self, url, **kw):
        kw["headers"] = self._h(kw.get("headers"))
        return self.client.patch(url, **kw)

    def delete(self, url, **kw):
        kw["headers"] = self._h(kw.get("headers"))
        return self.client.delete(url, **kw)

    def ok(self, resp, code=200):
        assert resp.status_code == code, resp.text
        return resp.json()

    def run_jobs(self, include_delayed=False):
        from app.jobs.queue import run_pending

        return run_pending(include_delayed=include_delayed)

    def create_watch(self, **fields):
        body = {"brand": "Richard Mille", "model": "RM 67-01", **fields}
        return self.ok(self.post("/api/watches", json=body), 201)

    def complete_watch(self, **extra):
        """A watch with every fact needed for approval."""
        base = dict(reference="RM67-01 TI", year="2021", condition="excellent",
                    condition_notes="Light hairlines on the case", price_sgd=285000, price_usd=209000,
                    box_papers="full_set", custody="in_hand")
        return self.create_watch(**{**base, **extra})

    def upload(self, watch_id, files):
        r = self.post(f"/api/watches/{watch_id}/assets",
                      files=[("files", (name, data, "application/octet-stream")) for name, data in files])
        return self.ok(r, 201)


@pytest.fixture
def studio(monkeypatch, tmp_path):
    data = tmp_path / "data"
    monkeypatch.setenv("STUDIO_DATA_DIR", str(data))
    reset_settings_cache()
    reset_engine()
    reset_provider()
    from app.api.deps import reset_rate_limits
    from app.integrations import base as integ_base
    from app.providers.mock_provider import MockProvider

    reset_rate_limits()
    MockProvider.forced_mismatch = None
    MockProvider.forced_copy = None
    integ_base.HTTP_TRANSPORT = None
    from app.main import app as fastapi_app

    with TestClient(fastapi_app) as client:
        r = client.post("/api/auth/setup", json={"username": "midas", "password": PASSWORD})
        assert r.status_code == 200, r.text
        yield Studio(client, r.json()["csrf_token"], data)
    reset_engine()
    reset_settings_cache()
    reset_provider()


@pytest.fixture
def anon(monkeypatch, tmp_path):
    """A fresh studio with no account yet."""
    monkeypatch.setenv("STUDIO_DATA_DIR", str(tmp_path / "data"))
    reset_settings_cache()
    reset_engine()
    reset_provider()
    from app.api.deps import reset_rate_limits

    reset_rate_limits()
    from app.main import app as fastapi_app

    with TestClient(fastapi_app) as client:
        yield client
    reset_engine()
    reset_settings_cache()


def small_watch_jpeg(seed=1, size=(900, 1350), **kw) -> bytes:
    from tests.fixtures.synthetic import _jpeg, draw_watch

    return _jpeg(draw_watch(size, seed=seed, **kw), 93)


def jpeg_bytes(img) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=92)
    return buf.getvalue()


def ocr_available() -> bool:
    try:
        import rapidocr_onnxruntime  # noqa: F401
        return True
    except Exception:
        return False


needs_ocr = pytest.mark.skipif(not ocr_available(), reason="local OCR engine not installed")
_ = tempfile
