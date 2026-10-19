"""Missing and conflicting facts.

Each issue is shown to the user as an editable field. Blockers stop approval and publishing;
warnings are shown but do not block.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.settings_store import get_setting
from app.db.models import AIObservation, FactSuggestion, Watch
from app.intel.facts import find_spec, norm_ref


@dataclass
class FactIssue:
    code: str
    field: str
    severity: str  # blocker | warning | info
    message: str
    suggestion: str | None = None
    suggestion_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _same(a: str | None, b: str | None) -> bool:
    return re.sub(r"[^a-z0-9]", "", (a or "").lower()) == re.sub(r"[^a-z0-9]", "", (b or "").lower())


def fact_issues(db: Session, watch: Watch) -> list[FactIssue]:
    issues: list[FactIssue] = []
    add = issues.append

    if not (watch.reference or "").strip():
        add(FactIssue("missing_reference", "reference", "warning",
                      "Reference number is missing. Add it so specs and copy can be matched."))
    if not (watch.year or "").strip():
        add(FactIssue("missing_year", "year", "warning",
                      "Year is missing. Enter it, or type 'Unknown' if it cannot be confirmed."))
    elif not re.fullmatch(r"(c\.\s*)?(19|20)\d{2}|unknown|\d{4}s", watch.year.strip(), re.IGNORECASE):
        add(FactIssue("year_format", "year", "warning",
                      "Year should look like 2021, c. 2019, 2010s or Unknown."))
    if watch.price_sgd is None:
        add(FactIssue("missing_price_sgd", "price_sgd", "blocker", "Price in SGD is missing."))
    if watch.price_usd is None:
        add(FactIssue("missing_price_usd", "price_usd", "warning",
                      "Price in USD is missing. eBay and international channels need it."))
    if not watch.condition:
        add(FactIssue("missing_condition", "condition", "blocker", "Condition grade is missing."))
    elif not (watch.condition_notes or "").strip() and watch.condition != "unworn":
        add(FactIssue("incomplete_condition", "condition_notes", "warning",
                      "Add a condition line (marks, polishing, service) so buyers know what to expect."))
    if watch.box_papers == "unknown":
        add(FactIssue("unknown_box_papers", "box_papers", "blocker",
                      "Box and papers status is unknown. Choose what comes with the watch."))
    if watch.custody == "unknown":
        add(FactIssue("unknown_custody", "custody", "blocker",
                      "Custody is unknown. It controls whether copy may say the watch is in hand."))
    if watch.is_consignment and watch.consignor_signoff != "approved":
        add(FactIssue("consignor_signoff", "consignor_signoff", "blocker",
                      "Consigned watch: record the consignor's sign-off on price and photos before publishing."))

    # FX drift between the two typed prices
    pricing = get_setting(db, "pricing")
    rate = pricing.get("fx_sgd_usd")
    if watch.price_sgd is not None and watch.price_usd is not None:
        if rate:
            expected = float(watch.price_sgd) * float(rate)
            drift = abs(float(watch.price_usd) - expected) / expected * 100 if expected else 0
            if drift > float(pricing.get("drift_tolerance_pct", 3.0)):
                add(FactIssue("fx_drift", "price_usd", "warning",
                              f"USD price is {drift:.1f}% away from SGD × {rate} (≈ USD {expected:,.0f}).",
                              suggestion=f"{expected:.0f}"))
        else:
            add(FactIssue("fx_rate_missing", "price_usd", "info",
                          "Set your SGD→USD rate in Settings to check the two prices agree."))

    # Spec table consistency
    spec = find_spec(db, watch)
    if spec is not None and not _same(spec.model, watch.model):
        add(FactIssue("spec_model_conflict", "model", "warning",
                      f"The specs table lists reference {spec.reference} as '{spec.model}', but the record says '{watch.model}'.",
                      suggestion=spec.model))
    if watch.reference and spec is None:
        add(FactIssue("no_spec_record", "reference", "info",
                      "No approved spec record for this reference. Add one so calibre and case details can be used."))

    # Latest AI observation: mismatches the model reported
    obs = db.scalar(select(AIObservation).where(AIObservation.watch_id == watch.id,
                                                AIObservation.kind == "listing_intel")
                    .order_by(AIObservation.created_at.desc()).limit(1))
    if obs is not None:
        for m in (obs.payload or {}).get("mismatches", []) or []:
            field = m.get("field") or "model"
            add(FactIssue("ai_mismatch", field, "warning",
                          f"Photos may not match the record ({field}): {m.get('explanation') or ''}".strip(),
                          suggestion=m.get("observed_value")))
        if (obs.payload or {}).get("different_watch_suspected"):
            add(FactIssue("wrong_watch", "photos", "blocker",
                          "The photo check suspects at least one frame shows a different watch. Review the photos."))

    # Open suggestions are attached to their field
    for sug in db.scalars(select(FactSuggestion).where(FactSuggestion.watch_id == watch.id,
                                                       FactSuggestion.status == "open")):
        for issue in issues:
            if issue.field == sug.field and issue.suggestion is None:
                issue.suggestion = sug.value
                issue.suggestion_id = sug.id
                break
        else:
            current = getattr(watch, sug.field, None) if hasattr(watch, sug.field) else None
            if current in (None, "", "unknown") or not _same(str(current), sug.value):
                add(FactIssue("suggestion", sug.field, "info",
                              f"Suggested from {sug.source.replace('_', ' ')}: {sug.value}",
                              suggestion=sug.value, suggestion_id=sug.id))
    return issues


def has_blockers(issues: list[FactIssue]) -> bool:
    return any(i.severity == "blocker" for i in issues)


def same_reference(a: str | None, b: str | None) -> bool:
    return norm_ref(a) == norm_ref(b)
