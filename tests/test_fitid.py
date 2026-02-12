from __future__ import annotations

from decimal import Decimal

from normalizers.fitid import assign_fitids, compute_fitid, normalize_label


def test_fitid_deterministic():
    label = normalize_label("Coffee", "Morning")
    fitid1 = compute_fitid("ACC", "2024-01-01", Decimal("-3.50"), label, 0)
    fitid2 = compute_fitid("ACC", "2024-01-01", Decimal("-3.50"), label, 0)
    assert fitid1 == fitid2


def test_fitid_unique_for_duplicates():
    txs = [
        {
            "posted_at": "2024-01-01",
            "amount": Decimal("-3.50"),
            "name": "Coffee",
            "memo": "Morning",
        },
        {
            "posted_at": "2024-01-01",
            "amount": Decimal("-3.50"),
            "name": "Coffee",
            "memo": "Morning",
        },
    ]
    assign_fitids("ACC", txs)
    assert txs[0]["fitid"] != txs[1]["fitid"]
