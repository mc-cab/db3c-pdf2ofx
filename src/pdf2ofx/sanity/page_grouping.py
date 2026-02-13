"""Page-aware transaction grouping for SANITY UI.

Builds grouped transaction lists with optional page separators and per-page/cumulative totals.
Decimal-safe; no page info → flat list (no separators).
"""
from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable

from InquirerPy.base.control import Choice
from InquirerPy.separator import Separator


def _to_decimal(amt: Any) -> Decimal:
    if amt is None:
        return Decimal("0")
    if isinstance(amt, Decimal):
        return amt
    try:
        return Decimal(str(amt))
    except Exception:
        return Decimal("0")


def has_any_page(transactions: list[dict], indices: list[int]) -> bool:
    """True if any transaction at the given indices has a valid page."""
    for i in indices:
        if 0 <= i < len(transactions):
            p = transactions[i].get("page")
            if isinstance(p, int) and p >= 1:
                return True
    return False


def _page_label(tx: dict) -> int | None:
    """Canonical 1-based page or None."""
    p = tx.get("page")
    if isinstance(p, int) and p >= 1:
        return p
    return None


def get_page_groups(
    transactions: list[dict],
    indices: list[int],
) -> list[tuple[str, list[tuple[int, dict]], Decimal, Decimal, Decimal, Decimal]] | None:
    """Group transactions by page; return None if no tx has page (no separators).

    Returns list of (page_label_str, [(index, tx), ...], page_credits, page_debits_abs, cum_credits, cum_debits).
    Order: ascending page (1, 2, …), then "Page ?" last. Within a group, preserve original index order.
    All amounts are Decimal.
    """
    if not has_any_page(transactions, indices):
        return None

    # Build (index, tx, page_or_none) for each index
    indexed: list[tuple[int, dict, int | None]] = []
    for i in indices:
        if 0 <= i < len(transactions):
            tx = transactions[i]
            indexed.append((i, tx, _page_label(tx)))

    # Sort: known page ascending, then unknown (None) last
    def sort_key(item: tuple[int, dict, int | None]) -> tuple[int, int]:
        page = item[2]
        if page is None:
            return (1, item[0])  # unknown after all pages
        return (0, page * 10000 + item[0])  # by page then index

    indexed.sort(key=sort_key)

    # Group by page label
    groups: list[tuple[str, list[tuple[int, dict]], Decimal, Decimal]] = []
    current_label: str | None = None
    current_list: list[tuple[int, dict]] = []
    current_credits = Decimal("0")
    current_debits = Decimal("0")

    for i, tx, page in indexed:
        amt = _to_decimal(tx.get("amount"))
        label = f"Page {page}" if page is not None else "Page ?"
        if label != current_label:
            if current_list:
                groups.append((current_label or "Page ?", current_list, current_credits, current_debits))
            current_label = label
            current_list = [(i, tx)]
            current_credits = Decimal("0")
            current_debits = Decimal("0")
            if amt >= 0:
                current_credits += amt
            else:
                current_debits += abs(amt)
        else:
            current_list.append((i, tx))
            if amt >= 0:
                current_credits += amt
            else:
                current_debits += abs(amt)
    if current_list:
        groups.append((current_label or "Page ?", current_list, current_credits, current_debits))

    # Add cumulative totals
    cum_c = Decimal("0")
    cum_d = Decimal("0")
    result: list[tuple[str, list[tuple[int, dict]], Decimal, Decimal, Decimal, Decimal]] = []
    for label, items, pc, pd in groups:
        cum_c += pc
        cum_d += pd
        result.append((label, items, pc, pd, cum_c, cum_d))

    return result


def format_separator_line(
    page_label: str,
    page_credits: Decimal,
    page_debits_abs: Decimal,
    cum_credits: Decimal,
    cum_debits: Decimal,
) -> str:
    """Short separator line: Page N | +credits  -debits | cum+  cum-."""
    def _fmt(d: Decimal) -> str:
        return f"{d:,.2f}".replace(",", " ")

    return (
        f"--- {page_label} | +{_fmt(page_credits)}  -{_fmt(page_debits_abs)} | "
        f"cum+ {_fmt(cum_credits)}  cum- {_fmt(cum_debits)} ---"
    )


def build_tx_choices_for_checkbox(
    transactions: list[dict],
    indices: list[int],
    tx_label_fn: Callable[[int, dict], str],
) -> list[Choice | Separator]:
    """Build choices for a checkbox list (e.g. Remove some, Invert batch). With page info, insert Separators."""
    if not has_any_page(transactions, indices):
        return [Choice(i, name=tx_label_fn(i, transactions[i])) for i in indices]

    groups = get_page_groups(transactions, indices)
    if not groups:
        return [Choice(i, name=tx_label_fn(i, transactions[i])) for i in indices]

    choices: list[Choice | Separator] = []
    for page_label, items, pc, pd, cum_c, cum_d in groups:
        choices.append(
            Separator(
                line=format_separator_line(page_label, pc, pd, cum_c, cum_d),
            )
        )
        for i, tx in items:
            choices.append(Choice(i, name=tx_label_fn(i, tx)))
    return choices


def build_tx_choices_for_select(
    transactions: list[dict],
    indices: list[int],
    tx_label_fn: Callable[[int, dict], str],
    back_value: str,
    back_name: str,
) -> list[Choice | Separator]:
    """Build choices for a select list (Edit one transaction). First choice is Back; then optional separators + tx."""
    result: list[Choice | Separator] = [Choice(back_value, name=back_name)]

    if not has_any_page(transactions, indices):
        result.extend([Choice(i, name=tx_label_fn(i, transactions[i])) for i in indices])
        return result

    groups = get_page_groups(transactions, indices)
    if not groups:
        result.extend([Choice(i, name=tx_label_fn(i, transactions[i])) for i in indices])
        return result

    for page_label, items, pc, pd, cum_c, cum_d in groups:
        result.append(
            Separator(
                line=format_separator_line(page_label, pc, pd, cum_c, cum_d),
            )
        )
        for i, tx in items:
            result.append(Choice(i, name=tx_label_fn(i, tx)))
    return result
