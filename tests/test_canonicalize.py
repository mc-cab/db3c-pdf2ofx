from __future__ import annotations

import json
from pathlib import Path
from decimal import Decimal

from pdf2ofx.normalizers.canonicalize import canonicalize_mindee


def test_canonicalize_schema_a(tmp_path: Path) -> None:
    fixture = Path(__file__).parent / "fixtures" / "mindee_custom_schema.json"
    raw = json.loads(fixture.read_text(encoding="utf-8"))

    result = canonicalize_mindee(raw, account_defaults={"account_id": "ACC"})
    statement = result.statement
    transactions = statement["transactions"]

    assert statement["account"]["account_id"] == "ACC"
    assert statement["period"]["start_date"] == "2024-01-01"
    assert statement["period"]["end_date"] == "2024-01-31"

    assert transactions[0]["posted_at"] == "2024-01-05"
    assert transactions[0]["amount"] == Decimal("-3.50")
    assert transactions[0]["name"] == "Coffee Shop"
    assert transactions[0]["memo"] == "low confidence"

    assert transactions[1]["posted_at"] == "2024-01-10"
    assert transactions[1]["amount"] == Decimal("1000.00")
    assert transactions[1]["name"] == "Salary"


def test_canonicalize_v2_no_locations_no_page() -> None:
    """V2 item with no locations → no page key on tx."""
    raw = {
        "inference": {
            "result": {
                "fields": {
                    "bank_name": {"value": "Test"},
                    "start_date": {"value": "2024-01-01"},
                    "end_date": {"value": "2024-01-31"},
                    "transactions": {
                        "items": [
                            {
                                "locations": [],
                                "fields": {
                                    "posting_date": {"value": "2024-01-05"},
                                    "amount": {"value": -10},
                                    "description": {"value": "Tx1"},
                                },
                            },
                        ],
                    },
                },
            },
        },
    }
    result = canonicalize_mindee(raw, account_defaults={"account_id": "ACC"})
    tx = result.statement["transactions"][0]
    assert "page" not in tx


def test_canonicalize_v2_item_locations_page_zero() -> None:
    """V2 item with item-level locations[].page = 0 → tx has page 1 (1-based)."""
    raw = {
        "inference": {
            "result": {
                "fields": {
                    "bank_name": {"value": "Test"},
                    "start_date": {"value": "2024-01-01"},
                    "end_date": {"value": "2024-01-31"},
                    "transactions": {
                        "items": [
                            {
                                "locations": [{"page": 0}],
                                "fields": {
                                    "posting_date": {"value": "2024-01-05"},
                                    "amount": {"value": -10},
                                    "description": {"value": "Tx1"},
                                },
                            },
                        ],
                    },
                },
            },
        },
    }
    result = canonicalize_mindee(raw, account_defaults={"account_id": "ACC"})
    tx = result.statement["transactions"][0]
    assert tx.get("page") == 1


def test_canonicalize_v2_field_locations_page_one() -> None:
    """V2 item with fields.operation_date.locations[].page = 1 → tx has page 2 (1-based)."""
    raw = {
        "inference": {
            "result": {
                "fields": {
                    "bank_name": {"value": "Test"},
                    "start_date": {"value": "2024-01-01"},
                    "end_date": {"value": "2024-01-31"},
                    "transactions": {
                        "items": [
                            {
                                "locations": [],
                                "fields": {
                                    "operation_date": {
                                        "value": "2024-01-05",
                                        "locations": [{"page": 1}],
                                    },
                                    "amount": {"value": -10},
                                    "description": {"value": "Tx1"},
                                },
                            },
                        ],
                    },
                },
            },
        },
    }
    result = canonicalize_mindee(raw, account_defaults={"account_id": "ACC"})
    tx = result.statement["transactions"][0]
    assert tx.get("page") == 2


def test_canonicalize_v2_page_min_of_candidates() -> None:
    """V2 item with multiple locations (e.g. page 0 and page 2) → min chosen → page 1."""
    raw = {
        "inference": {
            "result": {
                "fields": {
                    "bank_name": {"value": "Test"},
                    "start_date": {"value": "2024-01-01"},
                    "end_date": {"value": "2024-01-31"},
                    "transactions": {
                        "items": [
                            {
                                "locations": [{"page": 2}],
                                "fields": {
                                    "posting_date": {
                                        "value": "2024-01-05",
                                        "locations": [{"page": 0}],
                                    },
                                    "amount": {"value": -10},
                                    "description": {"value": "Tx1"},
                                },
                            },
                        ],
                    },
                },
            },
        },
    }
    result = canonicalize_mindee(raw, account_defaults={"account_id": "ACC"})
    tx = result.statement["transactions"][0]
    assert tx.get("page") == 1  # min(0, 2) + 1


def test_canonicalize_v1_no_page() -> None:
    """V1 schema: no page on any tx (regression)."""
    fixture = Path(__file__).parent / "fixtures" / "mindee_custom_schema.json"
    raw = json.loads(fixture.read_text(encoding="utf-8"))
    result = canonicalize_mindee(raw, account_defaults={"account_id": "ACC"})
    for tx in result.statement["transactions"]:
        assert "page" not in tx
