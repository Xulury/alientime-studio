"""Structured logging with secret redaction.

Log lines are JSON objects (one per line). A filter scrubs anything that looks like an API key,
bearer token or password so credentials never end up in log files.
"""
from __future__ import annotations

import json
import logging
import re
import sys
from datetime import datetime, timezone

_SECRET_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),                      # OpenAI-style keys
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{8,}"),            # bearer tokens
    re.compile(r"(?i)(api[_-]?key|token|secret|password)(\"?\s*[:=]\s*\"?)[^\s\"',}]+"),
    re.compile(r"shp(at|ss|ca|pa)_[A-Za-z0-9]{8,}"),            # Shopify tokens
    re.compile(r"EAA[A-Za-z0-9]{20,}"),                         # Meta tokens
    re.compile(r"at_[A-Za-z0-9_\-]{20,}"),                      # our own agent tokens
]


def redact(text: str) -> str:
    if not text:
        return text
    out = text
    for pat in _SECRET_PATTERNS:
        if pat.groups >= 2:
            out = pat.sub(lambda m: f"{m.group(1)}{m.group(2)}[REDACTED]", out)
        else:
            out = pat.sub("[REDACTED]", out)
    return out


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover - defensive
            return True
        record.msg = redact(msg)
        record.args = ()
        return True


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        for key in ("job_id", "watch_id", "asset_id", "channel", "event"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False)


def configure_logging(level: str = "INFO", json_lines: bool = True) -> None:
    root = logging.getLogger()
    if getattr(root, "_studio_configured", False):
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(RedactingFilter())
    handler.setFormatter(JsonFormatter() if json_lines else logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.handlers = [handler]
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpx2", "httpcore", "openai", "urllib3", "PIL", "multipart", "alembic", "pooch", "botocore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    root._studio_configured = True  # type: ignore[attr-defined]
