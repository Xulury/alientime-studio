"""AI usage logging, cost estimates and spending limits."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from app.config import get_settings
from app.core.settings_store import get_setting
from app.db.base import SessionLocal, utcnow
from app.db.models import AIUsage
from app.providers.base import BudgetExceeded

# Used only when the API response carries no usage numbers for an image call.
FALLBACK_IMAGE_COST_USD = 0.25


def _prices(model: str) -> dict:
    db = SessionLocal()
    try:
        table = get_setting(db, "ai_pricing")
    finally:
        db.close()
    for key in (model, model.rsplit("-20", 1)[0]):  # snapshot names fall back to the base model
        if key in table:
            return table[key]
    return table.get("_default", {"input": 10.0, "output": 50.0})


def estimate_cost(model: str, usage: dict[str, Any] | None, *, image_call: bool = False) -> float:
    if not usage:
        return FALLBACK_IMAGE_COST_USD if image_call else 0.0
    p = _prices(model)
    inp = int(usage.get("input_tokens") or 0)
    out = int(usage.get("output_tokens") or 0)
    details = usage.get("input_tokens_details") or {}
    if image_call and details:
        text_t = int(details.get("text_tokens") or 0)
        img_t = int(details.get("image_tokens") or 0)
        cost = text_t * p.get("text_input", p["input"]) + img_t * p["input"] + out * p["output"]
    else:
        cost = inp * p["input"] + out * p["output"]
    return round(cost / 1_000_000, 6)


def spend_since(since: datetime) -> float:
    db = SessionLocal()
    try:
        v = db.scalar(select(func.coalesce(func.sum(AIUsage.cost_usd), 0.0))
                      .where(AIUsage.at >= since, AIUsage.status == "ok"))
        return float(v or 0.0)
    finally:
        db.close()


def month_start(now: datetime | None = None) -> datetime:
    now = now or utcnow()
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def day_start(now: datetime | None = None) -> datetime:
    now = now or utcnow()
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def check_budget(provider: str, model: str, operation: str) -> None:
    s = get_settings()
    today = spend_since(day_start())
    month = spend_since(month_start())
    if today >= s.ai_daily_budget_usd or month >= s.ai_monthly_budget_usd:
        which = "daily" if today >= s.ai_daily_budget_usd else "monthly"
        limit = s.ai_daily_budget_usd if which == "daily" else s.ai_monthly_budget_usd
        log_usage(provider, model, operation, status="blocked_budget",
                  error=f"{which} AI budget of USD {limit:.2f} reached")
        raise BudgetExceeded(f"The {which} AI spending limit (USD {limit:.2f}) has been reached. "
                             f"Raise AI_{which.upper()}_BUDGET_USD in .env to continue.")


def log_usage(provider: str, model: str, operation: str, *, usage: dict | None = None, cost: float = 0.0,
              status: str = "ok", latency_ms: int = 0, image_in: int = 0, image_out: int = 0,
              watch_id: str | None = None, job_id: str | None = None, error: str | None = None) -> None:
    db = SessionLocal()
    try:
        db.add(AIUsage(provider=provider, model=model, operation=operation,
                       input_tokens=int((usage or {}).get("input_tokens") or 0),
                       output_tokens=int((usage or {}).get("output_tokens") or 0),
                       image_input_count=image_in, image_output_count=image_out, cost_usd=cost, status=status,
                       latency_ms=latency_ms, watch_id=watch_id, job_id=job_id, error=(error or "")[:1000] or None))
        db.commit()
    except Exception:  # usage logging must never break the AI call itself
        logging.getLogger(__name__).warning("could not record AI usage for %s/%s", provider, operation, exc_info=True)
        db.rollback()
    finally:
        db.close()


def usage_summary(days: int = 30) -> dict:
    s = get_settings()
    db = SessionLocal()
    try:
        since = utcnow() - timedelta(days=days)
        rows = db.execute(
            select(AIUsage.operation, AIUsage.model, func.count(), func.sum(AIUsage.input_tokens),
                   func.sum(AIUsage.output_tokens), func.sum(AIUsage.image_output_count), func.sum(AIUsage.cost_usd))
            .where(AIUsage.at >= since).group_by(AIUsage.operation, AIUsage.model)
        ).all()
        recent = db.scalars(select(AIUsage).order_by(AIUsage.at.desc()).limit(25)).all()
        errors = db.scalar(select(func.count()).select_from(AIUsage)
                           .where(AIUsage.at >= since, AIUsage.status != "ok")) or 0
    finally:
        db.close()
    return {
        "today_usd": round(spend_since(day_start()), 4),
        "month_usd": round(spend_since(month_start()), 4),
        "daily_budget_usd": s.ai_daily_budget_usd,
        "monthly_budget_usd": s.ai_monthly_budget_usd,
        "errors_30d": errors,
        "by_operation": [
            {"operation": r[0], "model": r[1], "calls": r[2], "input_tokens": int(r[3] or 0),
             "output_tokens": int(r[4] or 0), "images": int(r[5] or 0), "cost_usd": round(float(r[6] or 0), 4)}
            for r in rows
        ],
        "recent": [
            {"at": u.at.isoformat() + "Z", "operation": u.operation, "model": u.model, "status": u.status,
             "input_tokens": u.input_tokens, "output_tokens": u.output_tokens, "cost_usd": round(u.cost_usd, 5),
             "latency_ms": u.latency_ms, "error": u.error}
            for u in recent
        ],
        "note": "Costs are estimates from the pricing table in Settings; your OpenAI invoice is authoritative.",
    }
