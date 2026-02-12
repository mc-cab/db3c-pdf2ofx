from __future__ import annotations

from decimal import Decimal

from pdf2ofx.converters.ofx_emitter import emit_ofx
from pdf2ofx.validators.contract_validator import validate_statement
from pdf2ofx.normalizers.fitid import assign_fitids


def _statement() -> dict:
    statement = {
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
                "fitid": "",
                "posted_at": "2024-01-05",
                "amount": Decimal("-3.50"),
                "debit": Decimal("3.50"),
                "credit": None,
                "name": "Coffee",
            }
        ],
    }
    assign_fitids(statement["account"]["account_id"], statement["transactions"])
    statement = validate_statement(statement).statement
    return statement


def test_ofx2_emission_contains_required_tags() -> None:
    payload = emit_ofx(_statement(), "OFX2")
    text = payload.decode("utf-8")
    assert "<OFX" in text
    assert "<CURDEF>EUR" in text
    assert "<BANKACCTFROM>" in text
    assert "<STMTTRN>" in text
    assert "<FITID>" in text
