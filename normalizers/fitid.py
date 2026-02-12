from __future__ import annotations

import hashlib
import re
from decimal import Decimal
from typing import Iterable


def _collapse_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _strip_repeated_punct(value: str) -> str:
    return re.sub(r"([\.,;:!\-_/])\1+", r"\1", value)


def normalize_label(name: str | None, memo: str | None) -> str:
    parts = [name or "", memo or ""]
    joined = " ".join([p for p in parts if p]).strip()
    if not joined:
        return "UNKNOWN"
    joined = _collapse_whitespace(joined)
    joined = _strip_repeated_punct(joined)
    return joined.upper()


def compute_fitid(
    account_id: str,
    posted_at: str,
    amount: Decimal,
    label: str,
    seq: int,
) -> str:
    token = f"{account_id}|{posted_at}|{amount}|{label}|{seq}"
    digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return digest[:20]


def assign_fitids(account_id: str, transactions: list[dict]) -> None:
    seen: dict[str, int] = {}
    for tx in transactions:
        label = normalize_label(tx.get("name"), tx.get("memo"))
        posted_at = tx.get("posted_at")
        amount = tx.get("amount")
        key = f"{posted_at}|{amount}|{label}"
        seq = seen.get(key, 0)
        seen[key] = seq + 1
        tx["fitid"] = compute_fitid(account_id, str(posted_at), amount, label, seq)
