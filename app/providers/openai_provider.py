"""OpenAI provider adapter (Responses API for text/vision, Images API for backgrounds).

* Model identifiers come from settings (one per role), never from code paths elsewhere.
* Timeouts and retries are handled by the official SDK (`OPENAI_TIMEOUT_SECONDS`, `OPENAI_MAX_RETRIES`).
* Every call is checked against the daily/monthly budget first and logged with token counts and an
  estimated cost afterwards.
* Responses are parsed as JSON and validated with Pydantic; invalid output is an error, not a guess.
* The API key is read from the environment on the server and never logged or sent to the browser.
"""
from __future__ import annotations

import base64
import json
import time
from typing import Any

from pydantic import BaseModel, ValidationError

from app.config import get_settings
from app.core.logging import redact
from app.providers import usage as usage_mod
from app.providers.base import ConnectionReport, ImagePart, ProviderError, ProviderUnavailable
from app.providers.schemas import strict_schema

ROLE_SETTINGS = {
    "vision": "openai_model_vision",
    "intel": "openai_model_intel",
    "text": "openai_model_text",
    "image": "openai_model_image",
}


def _usage_dict(u: Any) -> dict:
    if u is None:
        return {}
    if hasattr(u, "model_dump"):
        return u.model_dump()
    if isinstance(u, dict):
        return u
    return {}


class OpenAIProvider:
    name = "openai"

    def __init__(self) -> None:
        s = get_settings()
        self._key = s.openai_api_key.get_secret_value() if s.openai_api_key else ""
        self._client = None

    @property
    def available(self) -> bool:
        return bool(self._key)

    def models(self) -> dict[str, str]:
        s = get_settings()
        return {role: getattr(s, attr) for role, attr in ROLE_SETTINGS.items()}

    def _model(self, role: str) -> str:
        return self.models()[role]

    @property
    def client(self):
        if not self.available:
            raise ProviderUnavailable("OpenAI is not configured. Add OPENAI_API_KEY to the .env file.")
        if self._client is None:
            from openai import OpenAI

            s = get_settings()
            self._client = OpenAI(api_key=self._key, base_url=s.openai_base_url or None,
                                  organization=s.openai_organization or None, project=s.openai_project or None,
                                  timeout=s.openai_timeout_seconds, max_retries=s.openai_max_retries)
        return self._client

    # ---- errors ----------------------------------------------------------------------------------
    @staticmethod
    def _translate(e: Exception) -> ProviderError:
        import openai

        msg = redact(str(e))[:400]
        if isinstance(e, openai.AuthenticationError):
            return ProviderError("OpenAI rejected the API key. Check OPENAI_API_KEY.")
        if isinstance(e, openai.PermissionDeniedError):
            if "verif" in msg.lower():
                return ProviderError("Your OpenAI organization must complete API Organization Verification "
                                     "before it can use this image model.")
            return ProviderError(f"OpenAI refused the request: {msg}")
        if isinstance(e, openai.NotFoundError):
            return ProviderError(f"The configured model is not available to this API key: {msg}")
        if isinstance(e, openai.RateLimitError):
            if "quota" in msg.lower() or "billing" in msg.lower():
                return ProviderError("The OpenAI account has run out of credit or hit its spending limit.")
            return ProviderError("OpenAI rate limit reached; will retry.", retryable=True)
        if isinstance(e, (openai.APITimeoutError, openai.APIConnectionError, openai.InternalServerError)):
            return ProviderError("OpenAI did not respond in time; will retry.", retryable=True)
        if isinstance(e, openai.BadRequestError):
            return ProviderError(f"OpenAI could not process the request: {msg}")
        return ProviderError(f"OpenAI error: {type(e).__name__}: {msg}", retryable=True)

    # ---- connection test -------------------------------------------------------------------------
    def test_connection(self) -> ConnectionReport:
        if not self.available:
            return ConnectionReport(False, self.name, "OPENAI_API_KEY is not set.")
        results: dict[str, Any] = {}
        ok = True
        for role, model in self.models().items():
            try:
                m = self.client.models.retrieve(model)
                results[role] = {"model": model, "ok": True, "owned_by": getattr(m, "owned_by", None)}
            except Exception as e:  # noqa: BLE001
                err = self._translate(e)
                results[role] = {"model": model, "ok": False, "error": str(err)}
                ok = False
        usage_mod.log_usage(self.name, "models.retrieve", "connection_test", status="ok" if ok else "error")
        msg = "Connected. All configured models are available." if ok else "Connected, but some models are not available."
        if all(not r.get("ok") for r in results.values()):
            first = next(iter(results.values()))
            msg = first.get("error", "Connection failed.")
        return ConnectionReport(ok, self.name, msg, results)

    # ---- structured text / vision ----------------------------------------------------------------
    def structured(self, role: str, *, system: str, text: str, images: list[ImagePart] | None,
                   schema_name: str, response_model: type[BaseModel], operation: str,
                   watch_id: str | None = None, job_id: str | None = None) -> BaseModel:
        model = self._model(role)
        usage_mod.check_budget(self.name, model, operation)
        content: list[dict] = [{"type": "input_text", "text": text}]
        for i, img in enumerate(images or []):
            if img.label:
                content.append({"type": "input_text", "text": f"Image {i}: {img.label}"})
            content.append({"type": "input_image", "detail": "high",
                            "image_url": "data:image/jpeg;base64," + base64.b64encode(img.jpeg).decode("ascii")})
        fmt = {"type": "json_schema", "name": schema_name, "schema": strict_schema(response_model), "strict": True}
        t0 = time.monotonic()
        try:
            resp = self.client.responses.create(
                model=model,
                instructions=system,
                input=[{"role": "user", "content": content}],
                text={"format": fmt},
                store=False,
            )
        except Exception as e:  # noqa: BLE001
            err = self._translate(e)
            usage_mod.log_usage(self.name, model, operation, status="error", error=str(err),
                                latency_ms=int((time.monotonic() - t0) * 1000), image_in=len(images or []),
                                watch_id=watch_id, job_id=job_id)
            raise err
        latency = int((time.monotonic() - t0) * 1000)
        u = _usage_dict(getattr(resp, "usage", None))
        cost = usage_mod.estimate_cost(model, u)
        raw = getattr(resp, "output_text", None) or ""
        try:
            parsed = response_model.model_validate(json.loads(raw))
        except (json.JSONDecodeError, ValidationError) as e:
            usage_mod.log_usage(self.name, model, operation, usage=u, cost=cost, status="invalid_output",
                                latency_ms=latency, image_in=len(images or []), watch_id=watch_id, job_id=job_id,
                                error=f"Response did not match the schema: {type(e).__name__}")
            raise ProviderError("The AI response did not match the expected format; try again.", retryable=True)
        usage_mod.log_usage(self.name, model, operation, usage=u, cost=cost, latency_ms=latency,
                            image_in=len(images or []), watch_id=watch_id, job_id=job_id)
        return parsed

    # ---- images ----------------------------------------------------------------------------------
    @staticmethod
    def _api_size(width: int, height: int) -> str:
        """gpt-image-2 family accepts custom sizes (multiples of 16, ratio ≤ 3:1, ≤ 3840×2160)."""
        scale = min(1.0, 1536 / max(width, height))
        w = max(256, int(width * scale) // 16 * 16)
        h = max(256, int(height * scale) // 16 * 16)
        return f"{w}x{h}"

    def _decode_image(self, resp, model: str, operation: str, t0: float, watch_id, job_id, image_in: int) -> bytes:
        latency = int((time.monotonic() - t0) * 1000)
        u = _usage_dict(getattr(resp, "usage", None))
        cost = usage_mod.estimate_cost(model, u, image_call=True)
        data = resp.data[0].b64_json if resp.data else None
        if not data:
            usage_mod.log_usage(self.name, model, operation, usage=u, cost=cost, status="invalid_output",
                                latency_ms=latency, watch_id=watch_id, job_id=job_id, error="No image returned")
            raise ProviderError("The image model returned no image.", retryable=True)
        usage_mod.log_usage(self.name, model, operation, usage=u, cost=cost, latency_ms=latency, image_in=image_in,
                            image_out=1, watch_id=watch_id, job_id=job_id)
        return base64.b64decode(data)

    def generate_image(self, *, prompt: str, width: int, height: int, operation: str,
                       watch_id: str | None = None, job_id: str | None = None) -> bytes:
        model = self._model("image")
        usage_mod.check_budget(self.name, model, operation)
        t0 = time.monotonic()
        try:
            resp = self.client.images.generate(model=model, prompt=prompt, size=self._api_size(width, height),
                                               quality=get_settings().openai_image_quality, n=1,
                                               output_format="png")
        except Exception as e:  # noqa: BLE001
            err = self._translate(e)
            usage_mod.log_usage(self.name, model, operation, status="error", error=str(err),
                                latency_ms=int((time.monotonic() - t0) * 1000), watch_id=watch_id, job_id=job_id)
            raise err
        return self._decode_image(resp, model, operation, t0, watch_id, job_id, 0)

    def edit_image(self, *, image_png: bytes, mask_png: bytes, prompt: str, width: int, height: int,
                   operation: str, watch_id: str | None = None, job_id: str | None = None) -> bytes:
        model = self._model("image")
        usage_mod.check_budget(self.name, model, operation)
        t0 = time.monotonic()
        try:
            resp = self.client.images.edit(model=model, image=("frame.png", image_png, "image/png"),
                                           mask=("mask.png", mask_png, "image/png"), prompt=prompt,
                                           size=self._api_size(width, height),
                                           quality=get_settings().openai_image_quality, n=1, output_format="png")
        except Exception as e:  # noqa: BLE001
            err = self._translate(e)
            usage_mod.log_usage(self.name, model, operation, status="error", error=str(err),
                                latency_ms=int((time.monotonic() - t0) * 1000), image_in=1,
                                watch_id=watch_id, job_id=job_id)
            raise err
        return self._decode_image(resp, model, operation, t0, watch_id, job_id, 1)
