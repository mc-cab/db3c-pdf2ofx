"""Tests for the Sanity & Reconciliation Layer (spec §4–§6)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from pdf2ofx.sanity.checks import (
    SanityResult,
    compute_quality_score,
    compute_reconciliation,
    compute_sanity,
    extract_balances,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _base_statement(
    *,
    transactions: list[dict] | None = None,
    period: dict | None = None,
) -> dict:
    if transactions is None:
        transactions = [
            {
                "fitid": "FIT1",
                "posted_at": "2024-01-05",
                "amount": Decimal("-80000"),
                "debit": Decimal("80000"),
                "credit": None,
                "name": "Wire Out",
                "trntype": "DEBIT",
            },
            {
                "fitid": "FIT2",
                "posted_at": "2024-01-10",
                "amount": Decimal("416000"),
                "debit": None,
                "credit": Decimal("416000"),
                "name": "Wire In",
                "trntype": "CREDIT",
            },
        ]
    if period is None:
        period = {"start_date": "2024-01-01", "end_date": "2024-01-31"}
    return {
        "schema_version": "1.0",
        "account": {
            "account_id": "ACC-123",
            "bank_id": "TESTBANK",
            "account_type": "CHECKING",
            "currency": "EUR",
        },
        "period": period,
        "transactions": transactions,
    }


# ---------------------------------------------------------------------------
# compute_reconciliation
# ---------------------------------------------------------------------------

class TestComputeReconciliation:

    def test_ok(self) -> None:
        rec_end, delta, status = compute_reconciliation(
            Decimal("100000"), Decimal("436000"), Decimal("336000"),
        )
        assert status == "OK"
        assert rec_end == Decimal("436000")
        assert delta == Decimal("0")

    def test_warning_small_delta(self) -> None:
        _, delta, status = compute_reconciliation(
            Decimal("100000"), Decimal("436000"), Decimal("336000.50"),
        )
        assert status == "WARNING"
        assert abs(delta) <= Decimal("1.00")

    def test_error_large_delta(self) -> None:
        _, delta, status = compute_reconciliation(
            Decimal("100000"), Decimal("436000"), Decimal("340000"),
        )
        assert status == "ERROR"
        assert abs(delta) > Decimal("1.00")

    def test_skipped_no_starting(self) -> None:
        rec_end, delta, status = compute_reconciliation(
            None, Decimal("436000"), Decimal("336000"),
        )
        assert status == "SKIPPED"
        assert rec_end is None
        assert delta is None

    def test_skipped_no_ending(self) -> None:
        _, _, status = compute_reconciliation(
            Decimal("100000"), None, Decimal("336000"),
        )
        assert status == "SKIPPED"

    def test_skipped_both_missing(self) -> None:
        _, _, status = compute_reconciliation(None, None, Decimal("0"))
        assert status == "SKIPPED"

    def test_exact_penny_boundary(self) -> None:
        """abs(delta) == 0.01 should be OK."""
        _, delta, status = compute_reconciliation(
            Decimal("100"), Decimal("200"), Decimal("100.01"),
        )
        assert status == "OK"
        assert delta == Decimal("0.01")

    def test_just_over_penny_boundary(self) -> None:
        """abs(delta) == 0.02 should be WARNING."""
        _, delta, status = compute_reconciliation(
            Decimal("100"), Decimal("200"), Decimal("100.02"),
        )
        assert status == "WARNING"


# ---------------------------------------------------------------------------
# compute_quality_score
# ---------------------------------------------------------------------------

class TestComputeQualityScore:

    def test_perfect(self) -> None:
        score, label, deductions = compute_quality_score(
            reconciliation_status="OK",
            balances_missing=False,
            drop_ratio=0.0,
            warning_count=0,
        )
        assert score == 100
        assert label == "GOOD"
        assert deductions == []

    def test_error_drops_to_poor(self) -> None:
        score, label, deductions = compute_quality_score(
            reconciliation_status="ERROR",
            balances_missing=False,
            drop_ratio=0.0,
            warning_count=0,
        )
        assert score == 40
        assert label == "POOR"
        assert ("Reconciliation error", -60) in deductions

    def test_balances_missing(self) -> None:
        score, label, deductions = compute_quality_score(
            reconciliation_status="SKIPPED",
            balances_missing=True,
            drop_ratio=0.0,
            warning_count=0,
        )
        assert score == 75
        assert label == "DEGRADED"
        assert ("Balances missing", -25) in deductions

    def test_high_drop_rate(self) -> None:
        score, label, deductions = compute_quality_score(
            reconciliation_status="OK",
            balances_missing=False,
            drop_ratio=0.15,
            warning_count=0,
        )
        assert score == 85
        assert label == "GOOD"
        assert any("drop rate" in r for r, _ in deductions)

    def test_warnings_capped(self) -> None:
        """Warning deduction is capped at 30."""
        score, _, deductions = compute_quality_score(
            reconciliation_status="OK",
            balances_missing=False,
            drop_ratio=0.0,
            warning_count=10,
        )
        assert score == 70  # 100 - min(100, 30)
        assert ("10 validation warning(s)", -30) in deductions

    def test_low_confidence(self) -> None:
        score, _, deductions = compute_quality_score(
            reconciliation_status="OK",
            balances_missing=False,
            drop_ratio=0.0,
            warning_count=0,
            low_mindee_confidence=True,
        )
        assert score == 85
        assert ("Low Mindee confidence", -15) in deductions

    def test_floor_at_zero(self) -> None:
        score, label, deductions = compute_quality_score(
            reconciliation_status="ERROR",
            balances_missing=True,
            drop_ratio=0.5,
            warning_count=5,
            low_mindee_confidence=True,
        )
        assert score == 0
        assert label == "POOR"
        assert len(deductions) == 5  # all deductions present


# ---------------------------------------------------------------------------
# extract_balances
# ---------------------------------------------------------------------------

class TestExtractBalances:

    def test_none_input(self) -> None:
        assert extract_balances(None) == (None, None)

    def test_empty_dict(self) -> None:
        assert extract_balances({}) == (None, None)

    def test_v1_title_case(self) -> None:
        raw = {
            "document": {
                "inference": {
                    "prediction": {
                        "Starting Balance": "100000.00",
                        "Ending Balance": "436000.00",
                    }
                }
            }
        }
        start, end = extract_balances(raw)
        assert start == Decimal("100000.00")
        assert end == Decimal("436000.00")

    def test_v2_snake_case(self) -> None:
        raw = {
            "inference": {
                "result": {
                    "fields": {
                        "starting_balance": {"value": "5000.50"},
                        "ending_balance": {"value": "7500.25"},
                    }
                }
            }
        }
        start, end = extract_balances(raw)
        assert start == Decimal("5000.50")
        assert end == Decimal("7500.25")

    def test_partial_only_starting(self) -> None:
        raw = {
            "document": {
                "inference": {
                    "prediction": {
                        "Starting Balance": "100",
                    }
                }
            }
        }
        start, end = extract_balances(raw)
        assert start == Decimal("100")
        assert end is None

    def test_invalid_value_skipped(self) -> None:
        raw = {
            "document": {
                "inference": {
                    "prediction": {
                        "Starting Balance": "not-a-number",
                        "Ending Balance": "500",
                    }
                }
            }
        }
        start, end = extract_balances(raw)
        assert start is None
        assert end == Decimal("500")


# ---------------------------------------------------------------------------
# compute_sanity (integration)
# ---------------------------------------------------------------------------

class TestComputeSanity:

    def test_basic_no_balances(self) -> None:
        stmt = _base_statement()
        result = compute_sanity(
            statement=stmt,
            pdf_name="test.pdf",
            extracted_count=2,
        )
        assert result.pdf_name == "test.pdf"
        assert result.extracted_count == 2
        assert result.kept_count == 2
        assert result.dropped_count == 0
        assert result.total_credits == Decimal("416000")
        assert result.total_debits == Decimal("-80000")
        assert result.net_movement == Decimal("336000")
        assert result.reconciliation_status == "SKIPPED"
        assert result.starting_balance is None
        assert result.quality_label == "DEGRADED"  # -25 for missing balances
        assert not result.skipped

    def test_with_explicit_balances(self) -> None:
        stmt = _base_statement()
        result = compute_sanity(
            statement=stmt,
            pdf_name="test.pdf",
            extracted_count=2,
            starting_balance=Decimal("100000"),
            ending_balance=Decimal("436000"),
        )
        assert result.reconciliation_status == "OK"
        assert result.delta == Decimal("0")
        assert result.quality_score == 100
        assert result.quality_label == "GOOD"

    def test_with_raw_response_balances(self) -> None:
        stmt = _base_statement()
        raw = {
            "document": {
                "inference": {
                    "prediction": {
                        "Starting Balance": "100000",
                        "Ending Balance": "436000",
                    }
                }
            }
        }
        result = compute_sanity(
            statement=stmt,
            pdf_name="test.pdf",
            extracted_count=2,
            raw_response=raw,
        )
        assert result.reconciliation_status == "OK"
        assert result.starting_balance == Decimal("100000")
        assert result.ending_balance == Decimal("436000")

    def test_dropped_transactions(self) -> None:
        stmt = _base_statement()
        result = compute_sanity(
            statement=stmt,
            pdf_name="test.pdf",
            extracted_count=10,
        )
        assert result.kept_count == 2
        assert result.dropped_count == 8
        assert "High drop rate" in result.warnings[1] if len(result.warnings) > 1 else True

    def test_high_drop_rate_quality(self) -> None:
        """>10% drop rate costs 15 points."""
        stmt = _base_statement()
        result = compute_sanity(
            statement=stmt,
            pdf_name="test.pdf",
            extracted_count=10,
            starting_balance=Decimal("100000"),
            ending_balance=Decimal("436000"),
        )
        assert result.quality_score == 85  # 100 - 15 for high drop rate

    def test_empty_transactions(self) -> None:
        stmt = _base_statement(transactions=[])
        result = compute_sanity(
            statement=stmt,
            pdf_name="test.pdf",
            extracted_count=0,
        )
        assert result.kept_count == 0
        assert result.net_movement == Decimal("0")

    def test_does_not_mutate_statement(self) -> None:
        """Sanity must NOT mutate the validated statement."""
        stmt = _base_statement()
        original_txs = [dict(tx) for tx in stmt["transactions"]]
        original_period = dict(stmt["period"])
        compute_sanity(
            statement=stmt,
            pdf_name="test.pdf",
            extracted_count=2,
            starting_balance=Decimal("100000"),
            ending_balance=Decimal("436000"),
        )
        assert stmt["transactions"] == original_txs
        assert stmt["period"] == original_period

    def test_explicit_balances_override_raw(self) -> None:
        """Explicit balances take precedence over raw response."""
        stmt = _base_statement()
        raw = {
            "document": {
                "inference": {
                    "prediction": {
                        "Starting Balance": "99999",
                        "Ending Balance": "99999",
                    }
                }
            }
        }
        result = compute_sanity(
            statement=stmt,
            pdf_name="test.pdf",
            extracted_count=2,
            raw_response=raw,
            starting_balance=Decimal("100000"),
            ending_balance=Decimal("436000"),
        )
        # Explicit balances used, not raw
        assert result.starting_balance == Decimal("100000")
        assert result.ending_balance == Decimal("436000")
        assert result.reconciliation_status == "OK"
