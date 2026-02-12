"""Integration test — calls the live Mindee API.

Requires:
  - MINDEE_V2_API_KEY and MINDEE_MODEL_ID set in environment (or .env)
  - At least one .pdf file in tests/fixtures/

Skipped automatically when either condition is missing.
Drop any bank statement PDF into tests/fixtures/ to enable.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest
from dotenv import load_dotenv

load_dotenv(override=False)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
API_KEY = os.getenv("MINDEE_V2_API_KEY")
MODEL_ID = os.getenv("MINDEE_MODEL_ID")
PDF_FILES = sorted(FIXTURES_DIR.glob("*.pdf"))

skip_no_creds = pytest.mark.skipif(
    not API_KEY or not MODEL_ID,
    reason="MINDEE_V2_API_KEY / MINDEE_MODEL_ID not set",
)
skip_no_pdf = pytest.mark.skipif(
    not PDF_FILES,
    reason="No .pdf files in tests/fixtures/",
)


@skip_no_creds
@skip_no_pdf
def test_mindee_response_is_compatible() -> None:
    """Call Mindee API and verify the response normalizes successfully."""
    from pdf2ofx.handlers.mindee_handler import infer_pdf
    from pdf2ofx.normalizers.canonicalize import canonicalize_mindee
    from pdf2ofx.normalizers.fitid import assign_fitids
    from pdf2ofx.validators.contract_validator import validate_statement

    pdf_path = PDF_FILES[0]
    raw = infer_pdf(API_KEY, MODEL_ID, pdf_path)

    # --- raw response structure ---
    assert isinstance(raw, dict), "Mindee response should be a dict"

    # --- normalization ---
    result = canonicalize_mindee(raw, account_defaults={"account_id": "INTEGRATION_TEST"})
    statement = result.statement

    assert "account" in statement
    assert "transactions" in statement
    assert "period" in statement
    assert isinstance(statement["transactions"], list)
    assert len(statement["transactions"]) > 0, (
        "Mindee returned 0 transactions — check model training data or PDF quality"
    )

    # --- FITID assignment ---
    assign_fitids(statement["account"]["account_id"], statement["transactions"])
    for tx in statement["transactions"]:
        assert tx.get("fitid"), "Every transaction should have a FITID after assignment"

    # --- validation ---
    validation = validate_statement(statement)
    valid_txs = validation.statement["transactions"]
    assert len(valid_txs) > 0, (
        "All transactions dropped by validator — check Mindee extraction quality"
    )

    # --- spot-check a transaction ---
    tx = valid_txs[0]
    assert tx.get("posted_at"), "Transaction missing posted_at after validation"
    assert tx.get("amount") is not None, "Transaction missing amount after validation"
    assert tx.get("fitid"), "Transaction missing fitid after validation"
    assert tx.get("trntype") in ("CREDIT", "DEBIT"), "trntype should be CREDIT or DEBIT"
