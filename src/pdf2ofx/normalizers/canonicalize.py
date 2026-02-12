from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

@dataclass
class NormalizationResult:
    statement: dict
    warnings: list[str]


class NormalizationError(Exception):
    pass


def _extract_value(value: Any) -> Any:
    if isinstance(value, dict):
        if "value" in value:
            return value["value"]
        if "values" in value:
            return value["values"]
    return value


def _parse_date(value: Any) -> str | None:
    if not value:
        return None
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, str):
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            for fmt in ("%d/%m/%Y", "%Y/%m/%d"):
                try:
                    return datetime.strptime(value, fmt).date().isoformat()
                except ValueError:
                    continue
    return None


def _parse_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _extract_prediction(raw: dict) -> dict:
    # V1: document.inference.prediction
    if "document" in raw:
        document = raw.get("document") or {}
        inference = document.get("inference") or {}
        prediction = inference.get("prediction")
        if prediction:
            return prediction
    if "inference" in raw:
        inference = raw.get("inference") or {}
        # V1: inference.prediction
        prediction = inference.get("prediction")
        if prediction:
            return prediction
        # V2: inference.result.fields
        result = inference.get("result") or {}
        fields = result.get("fields")
        if fields:
            return fields
    return raw


def _normalize_schema_a(prediction: dict, account_defaults: dict | None) -> NormalizationResult:
    warnings: list[str] = []
    account_defaults = account_defaults or {}

    def field(name: str) -> Any:
        return _extract_value(prediction.get(name))

    transactions_raw = field("Transactions") or []
    if not isinstance(transactions_raw, list):
        raise NormalizationError(
            "Transactions field is not a list. Expected custom model schema A."
        )

    transactions: list[dict] = []
    for item in transactions_raw:
        item = item or {}
        op_date = _parse_date(_extract_value(item.get("Operation Date")))
        post_date = _parse_date(_extract_value(item.get("Posting Date")))
        val_date = _parse_date(_extract_value(item.get("Value Date")))
        posted_at = op_date or post_date or val_date
        if op_date:
            posted_at_source = "operation"
        elif post_date:
            posted_at_source = "posting"
        elif val_date:
            posted_at_source = "value"
        else:
            posted_at_source = None

        amount_signed = _parse_decimal(_extract_value(item.get("Amount Signed")))
        debit = _parse_decimal(_extract_value(item.get("Debit Amount")))
        credit = _parse_decimal(_extract_value(item.get("Credit Amount")))

        amount = amount_signed
        if amount is None:
            if debit not in (None, Decimal("0")):
                amount = -abs(debit)
            elif credit not in (None, Decimal("0")):
                amount = abs(credit)

        description = _extract_value(item.get("Description"))
        memo = None
        notes = _extract_value(item.get("Row Confidence Notes"))
        if notes:
            memo = f"{notes}"
        name = description or "UNKNOWN"

        transactions.append(
            {
                "fitid": "",
                "posted_at": posted_at,
                "posted_at_source": posted_at_source,
                "amount": amount,
                "debit": debit,
                "credit": credit,
                "name": name,
                "memo": memo,
            }
        )

    # Account fields: Mindee wins if present, else fall back to defaults
    mindee_account_id = (
        field("Account Number") or field("Account ID") or field("Account Id")
    )
    account_id = mindee_account_id or account_defaults.get("account_id")
    bank_id = field("Bank ID") or field("Bank Id") or field("Bank Name")
    raw_account_type = (
        field("Account Type") or field("Account type")
        or account_defaults.get("account_type")
    )
    account_type = raw_account_type.upper() if isinstance(raw_account_type, str) else raw_account_type
    currency = field("Currency") or account_defaults.get("currency")

    statement = {
        "schema_version": "1.0",
        "source": {"origin": "mindee", "document_id": prediction.get("document_id")},
        "account": {
            "account_id": account_id,
            "bank_id": bank_id,
            "account_type": account_type,
            "currency": currency,
        },
        "period": {
            "start_date": _parse_date(field("Start Date")),
            "end_date": _parse_date(field("End Date")),
        },
        "transactions": transactions,
    }

    return NormalizationResult(statement=statement, warnings=warnings)


def _normalize_schema_a_v2(prediction: dict, account_defaults: dict | None) -> NormalizationResult:
    """Normalize V2 API response with snake_case field names."""
    warnings: list[str] = []
    account_defaults = account_defaults or {}

    def field(name: str) -> Any:
        return _extract_value(prediction.get(name))

    transactions_field = prediction.get("transactions") or {}
    transactions_raw = transactions_field.get("items") if isinstance(transactions_field, dict) else transactions_field
    if transactions_raw is None:
        transactions_raw = []
    if not isinstance(transactions_raw, list):
        raise NormalizationError(
            "transactions.items field is not a list. Expected V2 custom model schema."
        )

    transactions: list[dict] = []
    for item in transactions_raw:
        item = item or {}
        # V2 items may have a nested "fields" dict
        fields = item.get("fields", item) if isinstance(item, dict) else item

        op_date = _parse_date(_extract_value(fields.get("operation_date")))
        post_date = _parse_date(_extract_value(fields.get("posting_date")))
        val_date = _parse_date(_extract_value(fields.get("value_date")))
        posted_at = op_date or post_date or val_date
        if op_date:
            posted_at_source = "operation"
        elif post_date:
            posted_at_source = "posting"
        elif val_date:
            posted_at_source = "value"
        else:
            posted_at_source = None

        amount_signed = _parse_decimal(_extract_value(fields.get("amount")))
        debit = _parse_decimal(_extract_value(fields.get("debit_amount")))
        credit = _parse_decimal(_extract_value(fields.get("credit_amount")))

        amount = amount_signed
        if amount is None:
            if debit not in (None, Decimal("0")):
                amount = -abs(debit)
            elif credit not in (None, Decimal("0")):
                amount = abs(credit)

        description = _extract_value(fields.get("description"))
        memo = None
        notes = _extract_value(fields.get("row_confidence_notes"))
        if notes:
            memo = f"{notes}"
        name = description or "UNKNOWN"

        transactions.append(
            {
                "fitid": "",
                "posted_at": posted_at,
                "posted_at_source": posted_at_source,
                "amount": amount,
                "debit": debit,
                "credit": credit,
                "name": name,
                "memo": memo,
            }
        )

    # Account fields: Mindee wins if present, else fall back to defaults
    mindee_account_id = (
        field("account_number") or field("account_id")
    )
    account_id = mindee_account_id or account_defaults.get("account_id")
    bank_id = field("bank_id") or field("bank_name")
    raw_account_type = field("account_type") or account_defaults.get("account_type")
    account_type = raw_account_type.upper() if isinstance(raw_account_type, str) else raw_account_type
    currency = field("currency") or account_defaults.get("currency")

    statement = {
        "schema_version": "1.0",
        "source": {"origin": "mindee", "document_id": prediction.get("document_id")},
        "account": {
            "account_id": account_id,
            "bank_id": bank_id,
            "account_type": account_type,
            "currency": currency,
        },
        "period": {
            "start_date": _parse_date(field("start_date")),
            "end_date": _parse_date(field("end_date")),
        },
        "transactions": transactions,
    }

    return NormalizationResult(statement=statement, warnings=warnings)


def canonicalize_mindee(raw: dict, account_defaults: dict | None = None) -> NormalizationResult:
    prediction = _extract_prediction(raw)

    # V1 schema A: Title Case field names
    if any(key in prediction for key in ("Transactions", "Bank Name", "Start Date")):
        return _normalize_schema_a(prediction, account_defaults)

    # V2 schema: snake_case field names
    if any(key in prediction for key in ("transactions", "bank_name", "start_date")):
        return _normalize_schema_a_v2(prediction, account_defaults)

    if any(key in prediction for key in ("account_number", "list_of_transactions")):
        raise NormalizationError(
            "Mindee default bank statement schema is not implemented yet."
        )

    raise NormalizationError(
        "Unrecognized Mindee schema. Expected custom schema A fields."
    )
