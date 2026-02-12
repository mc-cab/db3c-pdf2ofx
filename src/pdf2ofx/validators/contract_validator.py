from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pdf2ofx.helpers.reporting import Issue, Severity

class ValidationError(Exception):
    pass


@dataclass
class ValidationResult:
    statement: dict
    issues: list[Issue]


def _parse_date(value: Any) -> date:
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        return date.fromisoformat(value)
    raise ValidationError("Invalid date format")


def _parse_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def validate_statement(statement: dict) -> ValidationResult:
    issues: dict[tuple[Severity, str], Issue] = {}

    def record_issue(
        severity: Severity,
        reason: str,
        fitid: str | None = None,
        count: int = 1,
    ) -> None:
        key = (severity, reason)
        if key not in issues:
            issues[key] = Issue(severity=severity, reason=reason, fitids=[], count=0)
        issue = issues[key]
        if fitid:
            issue.fitids.append(fitid)
        issue.count += count

    account = statement.get("account") or {}
    statement["account"] = account

    transactions = statement.get("transactions") or []
    if not transactions:
        raise ValidationError("transactions must be a non-empty array")

    fitids: set[str] = set()
    dates: list[date] = []
    valid_transactions: list[dict] = []
    for tx in transactions:
        posted_at = tx.get("posted_at")
        amount = tx.get("amount")
        fitid = tx.get("fitid")

        if not posted_at:
            record_issue(Severity.ERROR, "transaction missing posted_at", fitid)
            continue
        if amount is None:
            record_issue(Severity.ERROR, "transaction missing amount", fitid)
            continue
        if not fitid:
            record_issue(Severity.ERROR, "transaction missing fitid", None)
            continue
        if fitid in fitids:
            record_issue(Severity.ERROR, "transaction fitid is not unique", fitid)
            continue
        fitids.add(fitid)

        try:
            parsed_date = _parse_date(posted_at)
        except ValidationError:
            record_issue(Severity.ERROR, "transaction has invalid posted_at", fitid)
            continue
        dates.append(parsed_date)
        tx["posted_at"] = parsed_date.isoformat()
        try:
            tx["amount"] = _parse_decimal(amount)
        except Exception:
            record_issue(Severity.ERROR, "transaction has invalid amount", fitid)
            continue

        debit = tx.get("debit")
        credit = tx.get("credit")
        debit_val = _parse_decimal(debit) if debit not in (None, "") else None
        credit_val = _parse_decimal(credit) if credit not in (None, "") else None

        if debit_val not in (None, Decimal("0")) and credit_val not in (
            None,
            Decimal("0"),
        ):
            record_issue(
                Severity.WARNING,
                "transaction has both debit and credit amounts",
                fitid,
            )
        if debit_val not in (None, Decimal("0")):
            expected = -abs(debit_val)
            if (tx["amount"] - expected).copy_abs() > Decimal("0.01"):
                record_issue(
                    Severity.WARNING,
                    "signed amount does not match debit amount",
                    fitid,
                )
        if credit_val not in (None, Decimal("0")):
            expected = abs(credit_val)
            if (tx["amount"] - expected).copy_abs() > Decimal("0.01"):
                record_issue(
                    Severity.WARNING,
                    "signed amount does not match credit amount",
                    fitid,
                )

        if not tx.get("trntype"):
            tx["trntype"] = "CREDIT" if tx["amount"] >= 0 else "DEBIT"

        valid_transactions.append(tx)

    period = statement.get("period") or {}
    start = period.get("start_date")
    end = period.get("end_date")
    if dates:
        if not start or not end:
            derived_start = min(dates)
            derived_end = max(dates)
            period["start_date"] = derived_start.isoformat()
            period["end_date"] = derived_end.isoformat()
            record_issue(
                Severity.WARNING, "period missing; derived from transaction dates", None, 0
            )
        else:
            try:
                start_date = _parse_date(start)
                end_date = _parse_date(end)
            except ValidationError:
                derived_start = min(dates)
                derived_end = max(dates)
                period["start_date"] = derived_start.isoformat()
                period["end_date"] = derived_end.isoformat()
                record_issue(
                    Severity.WARNING,
                    "period invalid; derived from transaction dates",
                    None,
                    0,
                )
            else:
                outside_fitids: list[str] = []
                for tx_date, tx in zip(dates, valid_transactions):
                    if tx_date < start_date or tx_date > end_date:
                        outside_fitids.append(tx.get("fitid"))
                if outside_fitids:
                    for fitid in outside_fitids:
                        record_issue(
                            Severity.WARNING,
                            "transaction outside statement period",
                            fitid,
                        )
                period["start_date"] = start_date.isoformat()
                period["end_date"] = end_date.isoformat()

    statement["period"] = period
    statement["transactions"] = valid_transactions

    return ValidationResult(statement=statement, issues=list(issues.values()))
