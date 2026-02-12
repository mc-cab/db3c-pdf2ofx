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
        stmt_trns.append(
            STMTTRN(
                trntype=tx["trntype"],
                dtposted=_to_datetime(tx["posted_at"]),
                trnamt=Decimal(tx["amount"]),
                fitid=tx["fitid"],
                name=tx.get("name"),
                memo=tx.get("memo"),
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

    stmtrs = STMTRS(
        curdef=account["currency"],
        bankacctfrom=BANKACCTFROM(
            bankid=account["bank_id"],
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
