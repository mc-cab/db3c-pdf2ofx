"""Sanity & Reconciliation Layer — computation logic.

Pure functions.  No I/O, no prompts, no mutations to input data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class SanityResult:
    """Result of sanity checks for a single PDF / statement."""

    pdf_name: str
    period_start: str | None
    period_end: str | None
    extracted_count: int
    kept_count: int
    dropped_count: int
    total_credits: Decimal
    total_debits: Decimal
    net_movement: Decimal
    starting_balance: Decimal | None
    ending_balance: Decimal | None
    reconciled_end: Decimal | None
    delta: Decimal | None
    reconciliation_status: str          # OK | WARNING | ERROR | SKIPPED
    quality_score: int
    quality_label: str                  # GOOD | DEGRADED | POOR
    warnings: list[str] = field(default_factory=list)
    skipped: bool = False


# ---------------------------------------------------------------------------
# Balance extraction from raw Mindee response
# ---------------------------------------------------------------------------

_START_BALANCE_KEYS = [
    "Starting Balance", "starting_balance",
    "Start Balance", "start_balance",
    "Balance Start", "balance_start",
    "Opening Balance", "opening_balance",
]

_END_BALANCE_KEYS = [
    "Ending Balance", "ending_balance",
    "End Balance", "end_balance",
    "Balance End", "balance_end",
    "Closing Balance", "closing_balance",
]


def _get_prediction(raw: dict) -> dict | None:
    """Navigate raw Mindee response to the prediction / fields dict."""
    try:
        if "document" in raw:
            doc = raw.get("document")
            if isinstance(doc, dict):
                inf = doc.get("inference")
                if isinstance(inf, dict):
                    pred = inf.get("prediction")
                    if isinstance(pred, dict) and pred:
                        return pred
        if "inference" in raw:
            inf = raw.get("inference")
            if isinstance(inf, dict):
                pred = inf.get("prediction")
                if isinstance(pred, dict) and pred:
                    return pred
                result = inf.get("result")
                if isinstance(result, dict):
                    fields = result.get("fields")
                    if isinstance(fields, dict) and fields:
                        return fields
    except (AttributeError, TypeError):
        return None
    return raw


def _extract_decimal_field(prediction: dict, candidate_keys: list[str]) -> Decimal | None:
    """Try multiple key names; return first parseable Decimal or None."""
    for key in candidate_keys:
        val: Any = prediction.get(key)
        if val is None:
            continue
        if isinstance(val, dict) and "value" in val:
            val = val["value"]
        if val is None or val == "":
            continue
        try:
            return Decimal(str(val))
        except (InvalidOperation, ValueError, TypeError):
            continue
    return None


def extract_balances(raw: dict | None) -> tuple[Decimal | None, Decimal | None]:
    """Best-effort balance extraction from raw Mindee response."""
    if not raw:
        return None, None
    prediction = _get_prediction(raw)
    if not prediction:
        return None, None
    starting = _extract_decimal_field(prediction, _START_BALANCE_KEYS)
    ending = _extract_decimal_field(prediction, _END_BALANCE_KEYS)
    return starting, ending


# ---------------------------------------------------------------------------
# Reconciliation
# ---------------------------------------------------------------------------

def compute_reconciliation(
    starting_balance: Decimal | None,
    ending_balance: Decimal | None,
    net_movement: Decimal,
) -> tuple[Decimal | None, Decimal | None, str]:
    """Return (reconciled_end, delta, status).

    Status is one of: OK, WARNING, ERROR, SKIPPED.
    """
    if starting_balance is None or ending_balance is None:
        return None, None, "SKIPPED"
    reconciled_end = starting_balance + net_movement
    delta = reconciled_end - ending_balance
    if abs(delta) <= Decimal("0.01"):
        status = "OK"
    elif abs(delta) <= Decimal("1.00"):
        status = "WARNING"
    else:
        status = "ERROR"
    return reconciled_end, delta, status


# ---------------------------------------------------------------------------
# Quality score  (spec §6)
# ---------------------------------------------------------------------------

def compute_quality_score(
    reconciliation_status: str,
    balances_missing: bool,
    drop_ratio: float,
    warning_count: int,
    low_mindee_confidence: bool = False,
) -> tuple[int, str]:
    """Return (score, label).  Score in [0, 100]."""
    score = 100
    if reconciliation_status == "ERROR":
        score -= 60
    if balances_missing:
        score -= 25
    if drop_ratio > 0.10:
        score -= 15
    score -= min(warning_count * 10, 30)
    if low_mindee_confidence:
        score -= 15
    score = max(score, 0)

    if score >= 80:
        label = "GOOD"
    elif score >= 50:
        label = "DEGRADED"
    else:
        label = "POOR"
    return score, label


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def compute_sanity(
    statement: dict,
    pdf_name: str,
    extracted_count: int,
    raw_response: dict | None = None,
    validation_issues: list[Any] | None = None,
    starting_balance: Decimal | None = None,
    ending_balance: Decimal | None = None,
) -> SanityResult:
    """Compute the full sanity result for one validated statement.

    **This function does NOT mutate *statement*.**
    """
    transactions = statement.get("transactions", [])
    period = statement.get("period", {})

    kept_count = len(transactions)
    dropped_count = extracted_count - kept_count

    total_credits = Decimal("0")
    total_debits = Decimal("0")
    for tx in transactions:
        amount = tx.get("amount")
        if amount is None:
            continue
        try:
            amt = Decimal(str(amount))
        except (InvalidOperation, ValueError, TypeError):
            continue
        if amt >= 0:
            total_credits += amt
        else:
            total_debits += amt
    net_movement = total_credits + total_debits

    # Try raw Mindee response for any balance not provided explicitly
    if starting_balance is None or ending_balance is None:
        raw_start, raw_end = extract_balances(raw_response)
        if starting_balance is None and raw_start is not None:
            starting_balance = raw_start
        if ending_balance is None and raw_end is not None:
            ending_balance = raw_end

    reconciled_end, delta, recon_status = compute_reconciliation(
        starting_balance, ending_balance, net_movement,
    )

    balances_missing = starting_balance is None or ending_balance is None
    drop_ratio = dropped_count / extracted_count if extracted_count > 0 else 0.0

    warning_count = 0
    if validation_issues:
        for issue in validation_issues:
            if hasattr(issue, "severity") and str(issue.severity.value) == "WARNING":
                warning_count += 1

    quality_score, quality_label = compute_quality_score(
        reconciliation_status=recon_status,
        balances_missing=balances_missing,
        drop_ratio=drop_ratio,
        warning_count=warning_count,
    )

    warnings: list[str] = []
    if balances_missing:
        warnings.append("Balance data not available — reconciliation skipped")
    if drop_ratio > 0.10:
        warnings.append(
            f"High drop rate: {dropped_count}/{extracted_count} transactions dropped"
        )

    return SanityResult(
        pdf_name=pdf_name,
        period_start=period.get("start_date"),
        period_end=period.get("end_date"),
        extracted_count=extracted_count,
        kept_count=kept_count,
        dropped_count=dropped_count,
        total_credits=total_credits,
        total_debits=total_debits,
        net_movement=net_movement,
        starting_balance=starting_balance,
        ending_balance=ending_balance,
        reconciled_end=reconciled_end,
        delta=delta,
        reconciliation_status=recon_status,
        quality_score=quality_score,
        quality_label=quality_label,
        warnings=warnings,
        skipped=False,
    )
