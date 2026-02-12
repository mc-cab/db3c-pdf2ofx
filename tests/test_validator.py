from __future__ import annotations

from decimal import Decimal

from helpers.reporting import Severity
from validators.contract_validator import validate_statement


def _base_statement() -> dict:
    return {
        "schema_version": "1.0",
        "source": {"origin": "mindee"},
        "account": {
            "account_id": "ACC",
            "bank_id": "BANK",
            "account_type": "CHECKING",
            "currency": "EUR",
        },
        "period": {"start_date": "2024-01-01", "end_date": "2024-01-31"},
        "transactions": [
            {
                "fitid": "FIT1",
                "posted_at": "2024-01-05",
                "amount": Decimal("-3.50"),
                "debit": Decimal("3.50"),
                "credit": None,
                "name": "Coffee",
            }
        ],
    }


def test_validator_passes() -> None:
    result = validate_statement(_base_statement())
    assert result.statement["transactions"][0]["trntype"] == "DEBIT"
    assert result.issues == []


def test_validator_missing_fields() -> None:
    statement = _base_statement()
    statement["transactions"][0]["posted_at"] = None
    result = validate_statement(statement)
    assert result.statement["transactions"] == []
    assert any(issue.severity == Severity.ERROR for issue in result.issues)


def test_validator_debit_credit_conflict() -> None:
    statement = _base_statement()
    statement["transactions"][0]["credit"] = Decimal("1.00")
    result = validate_statement(statement)
    assert any(issue.severity == Severity.WARNING for issue in result.issues)
