from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal
from xml.etree import ElementTree as ET

from ofxtools.Client import OFXClient
from ofxtools.models import (
    BANKACCTFROM,
    BANKMSGSRSV1,
    BANKTRANLIST,
    OFX,
    SIGNONMSGSRSV1,
    SONRS,
    STATUS,
    STMTRS,
    STMTTRN,
)
from ofxtools.models.bank.msgsets import STMTTRNRS
from ofxtools.models.bank.stmt import LEDGERBAL

OFXFormat = Literal["OFX2", "OFX1"]

_OFX_NAME_MAX = 32
_OFX_MEMO_MAX = 254
_OFX_BANKID_MAX = 9  # OFX BANKID element max length (ofxtools enforces this)

# OFX curdef is OneOf(ISO 4217 codes). Map common Mindee/display values to ISO.
_CURRENCY_ALIASES: dict[str, str] = {
    "EURO": "EUR",
    "DOLLAR": "USD",
    "DOLLARS": "USD",
    "POUND": "GBP",
    "POUNDS": "GBP",
}


def _split_name_memo(
    name: str | None, memo: str | None,
) -> tuple[str | None, str | None]:
    """Ensure NAME fits the OFX 32-char limit; overflow goes to MEMO."""
    if not name or len(name) <= _OFX_NAME_MAX:
        return name, memo
    # Try to truncate at a word boundary (keep at least 10 chars)
    truncated = name[:_OFX_NAME_MAX]
    last_space = truncated.rfind(" ")
    if last_space > 10:
        truncated = truncated[:last_space]
    # Full description goes to MEMO
    if memo:
        full_memo = f"{name} | {memo}"
    else:
        full_memo = name
    if len(full_memo) > _OFX_MEMO_MAX:
        full_memo = full_memo[:_OFX_MEMO_MAX]
    return truncated, full_memo


def _to_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _build_ofx(statement: dict) -> OFX:
    account = statement["account"]
    period = statement["period"]
    transactions = statement["transactions"]

    stmt_trns = []
    for tx in transactions:
        name, memo = _split_name_memo(tx.get("name"), tx.get("memo"))
        stmt_trns.append(
            STMTTRN(
                trntype=tx["trntype"],
                dtposted=_to_datetime(tx["posted_at"]),
                trnamt=Decimal(tx["amount"]),
                fitid=tx["fitid"],
                name=name,
                memo=memo,
            )
        )

    bank_tran_list = BANKTRANLIST(
        *stmt_trns,
        dtstart=_to_datetime(period["start_date"]),
        dtend=_to_datetime(period["end_date"]),
    )

    ledger_bal = LEDGERBAL(
        balamt=Decimal("0"),
        dtasof=_to_datetime(period["end_date"]),
    )

    bank_id_raw = account.get("bank_id") or ""
    bank_id = (
        bank_id_raw[:_OFX_BANKID_MAX]
        if len(bank_id_raw) > _OFX_BANKID_MAX
        else bank_id_raw
    )

    currency_raw = (account.get("currency") or "").strip().upper()
    currency = _CURRENCY_ALIASES.get(currency_raw, currency_raw or "XXX")

    stmtrs = STMTRS(
        curdef=currency,
        bankacctfrom=BANKACCTFROM(
            bankid=bank_id,
            acctid=account["account_id"],
            accttype=account["account_type"],
        ),
        banktranlist=bank_tran_list,
        ledgerbal=ledger_bal,
    )

    stmttrnrs = STMTTRNRS(
        trnuid="1",
        status=STATUS(code=0, severity="INFO"),
        stmtrs=stmtrs,
    )

    bankmsgsrsv1 = BANKMSGSRSV1(stmttrnrs)
    sonrs = SONRS(
        status=STATUS(code=0, severity="INFO"),
        dtserver=datetime.now(timezone.utc),
        language="ENG",
    )
    signon = SIGNONMSGSRSV1(sonrs=sonrs)

    return OFX(signonmsgsrsv1=signon, bankmsgsrsv1=bankmsgsrsv1)


def emit_ofx(statement: dict, fmt: OFXFormat = "OFX2") -> bytes:
    ofx = _build_ofx(statement)
    if fmt == "OFX2":
        client = OFXClient(url="", version=200, prettyprint=True, close_elements=True)
        return client.serialize(ofx)

    client = OFXClient(url="", version=102, prettyprint=True, close_elements=False)
    return client.serialize(ofx)
