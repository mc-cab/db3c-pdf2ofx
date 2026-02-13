from __future__ import annotations

from decimal import Decimal

from pdf2ofx.helpers.reporting import Severity
from pdf2ofx.validators.contract_validator import validate_statement


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


def test_validator_page_valid_passes() -> None:
    statement = _base_statement()
    statement["transactions"][0]["page"] = 1
    result = validate_statement(statement)
    assert len(result.statement["transactions"]) == 1
    assert result.statement["transactions"][0].get("page") == 1
    assert not any(issue.reason == "transaction page invalid; key removed" for issue in result.issues)


def test_validator_page_invalid_warning_and_key_removed_tx_kept() -> None:
    """Tx with page 0 or non-int gets WARNING and page key removed but tx is still kept."""
    statement = _base_statement()
    statement["transactions"][0]["page"] = 0
    result = validate_statement(statement)
    assert len(result.statement["transactions"]) == 1
    assert "page" not in result.statement["transactions"][0]
    assert any(
        issue.severity == Severity.WARNING and "transaction page invalid" in issue.reason
        for issue in result.issues
    )


def test_validator_page_non_int_warning_and_key_removed() -> None:
    statement = _base_statement()
    statement["transactions"][0]["page"] = "one"
    result = validate_statement(statement)
    assert len(result.statement["transactions"]) == 1
    assert "page" not in result.statement["transactions"][0]
    assert any("transaction page invalid" in issue.reason for issue in result.issues)
