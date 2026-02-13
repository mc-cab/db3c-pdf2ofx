"""Tests for page grouping and choice-building helpers (v0.1.6)."""
from __future__ import annotations

from decimal import Decimal

import pytest

from InquirerPy.base.control import Choice
from InquirerPy.separator import Separator

from pdf2ofx.sanity.page_grouping import (
    build_tx_choices_for_checkbox,
    build_tx_choices_for_select,
    format_separator_line,
    get_page_groups,
    has_any_page,
)


def _tx_label(i: int, tx: dict) -> str:
    date_str = (tx.get("posted_at") or "?")[:10]
    amt = tx.get("amount", "")
    return f"{date_str}  {amt}  {tx.get('name', '-')}"


# ---------------------------------------------------------------------------
# has_any_page
# ---------------------------------------------------------------------------


def test_has_any_page_no_page() -> None:
    transactions = [
        {"amount": Decimal("10"), "name": "A"},
        {"amount": Decimal("-5"), "name": "B"},
    ]
    assert has_any_page(transactions, [0, 1]) is False


def test_has_any_page_all_have_page() -> None:
    transactions = [
        {"amount": Decimal("10"), "name": "A", "page": 1},
        {"amount": Decimal("-5"), "name": "B", "page": 2},
    ]
    assert has_any_page(transactions, [0, 1]) is True


def test_has_any_page_mixed() -> None:
    transactions = [
        {"amount": Decimal("10"), "name": "A"},
        {"amount": Decimal("-5"), "name": "B", "page": 1},
    ]
    assert has_any_page(transactions, [0, 1]) is True


# ---------------------------------------------------------------------------
# get_page_groups
# ---------------------------------------------------------------------------


def test_get_page_groups_no_page_returns_none() -> None:
    transactions = [
        {"amount": Decimal("10"), "name": "A"},
        {"amount": Decimal("-5"), "name": "B"},
    ]
    assert get_page_groups(transactions, [0, 1]) is None


def test_get_page_groups_all_have_page_ordered() -> None:
    transactions = [
        {"amount": Decimal("100"), "name": "A", "page": 2},
        {"amount": Decimal("-50"), "name": "B", "page": 1},
        {"amount": Decimal("25"), "name": "C", "page": 1},
    ]
    groups = get_page_groups(transactions, [0, 1, 2])
    assert groups is not None
    assert len(groups) == 2
    label1, items1, pc1, pd1, cum_c1, cum_d1 = groups[0]
    assert label1 == "Page 1"
    assert [i for i, _ in items1] == [1, 2]
    assert pc1 == Decimal("25")
    assert pd1 == Decimal("50")
    assert cum_c1 == Decimal("25")
    assert cum_d1 == Decimal("50")
    label2, items2, pc2, pd2, cum_c2, cum_d2 = groups[1]
    assert label2 == "Page 2"
    assert [i for i, _ in items2] == [0]
    assert pc2 == Decimal("100")
    assert pd2 == Decimal("0")
    assert cum_c2 == Decimal("125")
    assert cum_d2 == Decimal("50")


def test_get_page_groups_mixed_unknown_last() -> None:
    transactions = [
        {"amount": Decimal("10"), "name": "A", "page": 1},
        {"amount": Decimal("-5"), "name": "B"},
        {"amount": Decimal("3"), "name": "C", "page": 2},
    ]
    groups = get_page_groups(transactions, [0, 1, 2])
    assert groups is not None
    assert len(groups) == 3
    assert groups[0][0] == "Page 1"
    assert groups[1][0] == "Page 2"
    assert groups[2][0] == "Page ?"
    assert [i for i, _ in groups[2][1]] == [1]


# ---------------------------------------------------------------------------
# format_separator_line
# ---------------------------------------------------------------------------


def test_format_separator_line_contains_page_and_totals() -> None:
    line = format_separator_line(
        "Page 1",
        Decimal("1234.56"),
        Decimal("987.65"),
        Decimal("1234.56"),
        Decimal("987.65"),
    )
    assert "Page 1" in line
    assert "234.56" in line
    assert "987.65" in line
    assert "cum+" in line
    assert "cum-" in line


# ---------------------------------------------------------------------------
# build_tx_choices_for_checkbox
# ---------------------------------------------------------------------------


def test_build_tx_choices_for_checkbox_no_page_no_separator() -> None:
    transactions = [
        {"amount": Decimal("10"), "posted_at": "2024-01-01", "name": "A"},
        {"amount": Decimal("-5"), "posted_at": "2024-01-02", "name": "B"},
    ]
    choices = build_tx_choices_for_checkbox(transactions, [0, 1], _tx_label)
    assert len(choices) == 2
    assert all(isinstance(c, Choice) for c in choices)
    assert [c.value for c in choices] == [0, 1]


def test_build_tx_choices_for_checkbox_with_page_has_separators() -> None:
    transactions = [
        {"amount": Decimal("100"), "posted_at": "2024-01-01", "name": "A", "page": 1},
        {"amount": Decimal("-50"), "posted_at": "2024-01-02", "name": "B", "page": 1},
        {"amount": Decimal("25"), "posted_at": "2024-01-03", "name": "C", "page": 2},
    ]
    choices = build_tx_choices_for_checkbox(transactions, [0, 1, 2], _tx_label)
    assert len(choices) >= 3
    separators = [c for c in choices if isinstance(c, Separator)]
    choices_only = [c for c in choices if isinstance(c, Choice)]
    assert len(separators) == 2
    assert len(choices_only) == 3
    assert [c.value for c in choices_only] == [0, 1, 2]
    assert "Page 1" in (separators[0].line if hasattr(separators[0], "line") else str(separators[0]))
    assert "Page 2" in (separators[1].line if hasattr(separators[1], "line") else str(separators[1]))


# ---------------------------------------------------------------------------
# build_tx_choices_for_select
# ---------------------------------------------------------------------------


def test_build_tx_choices_for_select_no_page_back_then_flat() -> None:
    transactions = [
        {"amount": Decimal("10"), "posted_at": "2024-01-01", "name": "A"},
    ]
    choices = build_tx_choices_for_select(
        transactions, [0], _tx_label, "__back__", "← Back"
    )
    assert choices[0].value == "__back__"
    assert choices[0].name == "← Back"
    assert len([c for c in choices if isinstance(c, Choice)]) == 2
    assert not any(isinstance(c, Separator) for c in choices)


def test_build_tx_choices_for_select_with_page_separators_and_back_first() -> None:
    transactions = [
        {"amount": Decimal("10"), "posted_at": "2024-01-01", "name": "A", "page": 1},
        {"amount": Decimal("-5"), "posted_at": "2024-01-02", "name": "B", "page": 1},
    ]
    choices = build_tx_choices_for_select(
        transactions, [0, 1], _tx_label, "__back__", "← Back"
    )
    assert choices[0].value == "__back__"
    assert isinstance(choices[1], Separator)
    choice_vals = [c.value for c in choices if isinstance(c, Choice)]
    assert choice_vals == ["__back__", 0, 1]
