---
doc_id: mindee_data_schema_reference
title: pdf2ofx — Mindee Custom Model Data Schema Reference
owner: Mathieu
scope: Canonical backup of the production Mindee extraction model schema
status: current
doc_type: reference
version: 1.0
created: 2026-02-12
model_id: 721de552-09be-43ea-b1c5-7fb66a5c4e6f
tags: [pdf2ofx, mindee, schema, backup]
---

# Mindee Custom Model — Data Schema Reference

This document is the **canonical backup** of the production Mindee custom extraction model used by pdf2ofx.

If the model is lost or needs to be recreated, use this file to manually rebuild the schema field-by-field in the Mindee UI.

See also: [Mindee Data Schema documentation](https://docs.mindee.com/extraction-models/data-schema)

---

## Model Metadata

| Property | Value |
|----------|-------|
| Model ID | `721de552-09be-43ea-b1c5-7fb66a5c4e6f` |
| API version | V2 (`inference.result.fields`) |
| Field naming convention | `snake_case` |
| Active options | `confidence: true`, all others `false` |

---

## Statement-Level Fields

### 1. bank_name

| Property | Value |
|----------|-------|
| Field Title | Bank Name |
| Field Name | `bank_name` |
| Field Type | Text |
| Description | The name of the bank or financial institution that issued the statement. |
| Guideline | — |
| Example value | `CIC Sud Ouest` |

---

### 2. account_type

| Property | Value |
|----------|-------|
| Field Title | Account Type |
| Field Name | `account_type` |
| Field Type | Text |
| Description | The type of bank account (e.g. checking, savings). Used in OFX output as `BANKACCTFROM.accttype`. Value is uppercased by the normalizer. |
| Guideline | Use lowercase values: `checking`, `savings`, `creditline`, `moneymrkt`. |
| Example value | `checking` |

---

### 3. currency

| Property | Value |
|----------|-------|
| Field Title | Currency |
| Field Name | `currency` |
| Field Type | Text |
| Description | The ISO 4217 currency code of the account. Used in OFX output as `CURDEF`. |
| Guideline | Use the 3-letter ISO currency code (e.g. EUR, USD, GBP). |
| Example value | `EUR` |

---

### 4. detected_iban

| Property | Value |
|----------|-------|
| Field Title | Detected IBAN |
| Field Name | `detected_iban` |
| Field Type | Text |
| Description | The IBAN detected on the bank statement. Not currently consumed by pdf2ofx but extracted for reference and future use. |
| Guideline | Extract the full IBAN including country code and spaces. |
| Example value | `FR76 1005 7190 9500 0208 6610 127` |

---

### 5. detected_aid

| Property | Value |
|----------|-------|
| Field Title | Detected AID |
| Field Name | `detected_aid` |
| Field Type | Text |
| Description | The raw account identifier detected on the statement. May match `account_id`. Not currently consumed by pdf2ofx but preserved for traceability. |
| Guideline | — |
| Example value | `00020866101` |

---

### 6. account_id

| Property | Value |
|----------|-------|
| Field Title | Account ID |
| Field Name | `account_id` |
| Field Type | Text |
| Description | The bank account identifier. Used in OFX output as `BANKACCTFROM.acctid` and as a component of the FITID hash. |
| Guideline | Extract the primary account number used by the bank. Prefer the short numeric identifier over the IBAN. |
| Example value | `00020866101` |

---

### 7. bank_id

| Property | Value |
|----------|-------|
| Field Title | Bank ID |
| Field Name | `bank_id` |
| Field Type | Text |
| Description | The BIC/SWIFT code of the bank. Used in OFX output as `BANKACCTFROM.bankid`. |
| Guideline | Extract the BIC/SWIFT code if present. Fall back to the bank's national routing code. |
| Example value | `CMCIFRPP` |

---

### 8. start_date

| Property | Value |
|----------|-------|
| Field Title | Start Date |
| Field Name | `start_date` |
| Field Type | Date |
| Description | The first day of the statement period. |
| Guideline | — |
| Example value | `2025-02-10` |

---

### 9. end_date

| Property | Value |
|----------|-------|
| Field Title | End Date |
| Field Name | `end_date` |
| Field Type | Date |
| Description | The last day of the statement period. |
| Guideline | — |
| Example value | `2025-02-28` |

---

### 10. starting_balance

| Property | Value |
|----------|-------|
| Field Title | Starting Balance |
| Field Name | `starting_balance` |
| Field Type | Number |
| Description | The account balance at the start of the statement period. Used by the SANITY layer for reconciliation. |
| Guideline | Extract the opening balance shown on the statement. Use the signed value (positive for credit balance). |
| Example value | `0.0` |

---

### 11. ending_balance

| Property | Value |
|----------|-------|
| Field Title | Ending Balance |
| Field Name | `ending_balance` |
| Field Type | Number |
| Description | The account balance at the end of the statement period. Used by the SANITY layer for reconciliation. |
| Guideline | Extract the closing balance shown on the statement. Use the signed value (positive for credit balance). |
| Example value | `18500.0` |

---

## Transaction Fields (Nested Objects Array)

### 12. transactions

| Property | Value |
|----------|-------|
| Field Title | Transactions |
| Field Name | `transactions` |
| Field Type | Nested Objects Array |
| Description | The list of individual transactions on the statement. Enable "Multiple items can be extracted". |
| Guideline | Each row in the transaction table is one item. Extract all transactions visible on the statement. |

#### Subfields of `transactions`:

---

#### 12a. operation_date

| Property | Value |
|----------|-------|
| Field Title | Operation Date |
| Field Name | `operation_date` |
| Field Type | Date |
| Description | The date the operation was initiated. This is the primary date used for `posted_at` in the canonical schema. |
| Guideline | — |
| Example value | `2025-02-12` |

---

#### 12b. value_date

| Property | Value |
|----------|-------|
| Field Title | Value Date |
| Field Name | `value_date` |
| Field Type | Date |
| Description | The value date (date the funds are available). Used as fallback if operation_date is missing. |
| Guideline | — |
| Example value | `2025-02-12` |

---

#### 12c. posting_date

| Property | Value |
|----------|-------|
| Field Title | Posting Date |
| Field Name | `posting_date` |
| Field Type | Date |
| Description | The date the transaction was posted to the account. Used as fallback if operation_date is missing. |
| Guideline | — |
| Example value | `2025-02-12` |

---

#### 12d. description

| Property | Value |
|----------|-------|
| Field Title | Description |
| Field Name | `description` |
| Field Type | Text |
| Description | The transaction label/description as printed on the statement. Used as the transaction `name` in OFX output and as a component of the FITID hash. |
| Guideline | Extract the full description text. Include reference numbers if present. |
| Example value | `VIR PETIT FREDERIC ZZ1HS8XHYA7ALLL19` |

---

#### 12e. amount

| Property | Value |
|----------|-------|
| Field Title | Amount |
| Field Name | `amount` |
| Field Type | Number |
| Description | The signed transaction amount. Negative for debits, positive for credits. This is the primary amount field used in the canonical schema and the FITID hash. |
| Guideline | Use the signed value. Debits must be negative. Credits must be positive. |
| Example value | `1000.0` (credit), `-1296.0` (debit) |

---

#### 12f. debit_amount

| Property | Value |
|----------|-------|
| Field Title | Debit Amount |
| Field Name | `debit_amount` |
| Field Type | Number |
| Description | The absolute debit amount. Null if the transaction is a credit. Used for cross-validation against the signed amount. |
| Guideline | Always use the positive (absolute) value for debits. Leave null/empty for credits. |
| Example value | `1296.0` (debit), `null` (credit) |

---

#### 12g. credit_amount

| Property | Value |
|----------|-------|
| Field Title | Credit Amount |
| Field Name | `credit_amount` |
| Field Type | Number |
| Description | The absolute credit amount. Null if the transaction is a debit. Used for cross-validation against the signed amount. |
| Guideline | Always use the positive (absolute) value for credits. Leave null/empty for debits. |
| Example value | `1000.0` (credit), `null` (debit) |

---

## Field Count Summary

| Level | Count |
|-------|-------|
| Statement-level fields | 11 |
| Transaction subfields | 7 |
| **Total fields** | **18** |

Within the Mindee recommended limit of 25 fields.

---

## How to Recreate This Schema in Mindee

1. Log in to [platform.mindee.com](https://platform.mindee.com)
2. Create a new **Custom Extraction** model
3. For each field listed above, create a field with the exact **Field Name** and **Field Type** shown
4. Copy the **Description** and **Guideline** into the corresponding fields in the Mindee UI
5. For `transactions`: set the type to **Nested Object** and enable **"Multiple items can be extracted"**, then add each subfield (12a–12g)
6. Enable the **Confidence** option in model settings
7. Upload sample bank statement PDFs and annotate to train the model
8. Note the new Model ID and update `MINDEE_MODEL_ID` in `.env`

---

## Version History

| Version | Date | Change |
|---------|------|--------|
| 1.0 | 2026-02-12 | Initial schema backup from production model `721de552` |
