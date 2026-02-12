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
