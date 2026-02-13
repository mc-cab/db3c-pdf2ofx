# RFC: Mindee model refactor (PARKED — NOT IN SCOPE v0.1.1)

**Status:** PARKED. Do not implement in v0.1.1.

**Idea:** Replace debit/credit/signed amount confusion with:

- `transaction_amount_abs` (number, absolute value)
- `transaction_type` (classification: debit/credit)

Add non-breaking fields for account detection: `detected_iban`, `detected_aid`, plus `account_id` (keep parsing safe).

**When to revisit:** After Recovery Mode and tmp retention are stable.
