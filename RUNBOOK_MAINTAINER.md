# Maintainer Runbook — pdf2ofx

Internal reference for developers maintaining this tool.

---

## Dev Setup

### Option A: uv (recommended)

```bash
uv sync
uv run pdf2ofx --help
```

### Option B: pip editable

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
pip install -e ".[test]"
pdf2ofx --help
```

Both methods install the package in editable mode. Source lives under `src/pdf2ofx/`.

---

## Running Tests

```bash
# uv
uv run pytest -q

# pip (after editable install)
python -m pytest -q
```

All tests are in `tests/`. Fixtures live in `tests/fixtures/`.

The test suite does **not** call the Mindee API. It uses canonical JSON fixtures and the `--dev-canonical` / `--dev-non-interactive` flags.

---

## Packaging Validation Checklist

Run these after any change to `pyproject.toml`, imports, or file layout:

```bash
# 1. Clean install
pip install -e . --no-deps

# 2. CLI entry point
pdf2ofx --help

# 3. Module entry point
python -m pdf2ofx --help

# 4. uv roundtrip
uv sync
uv run pdf2ofx --help

# 5. Tests
uv run pytest -q
```

All five must exit 0.

---

## FITID Determinism Invariants

**These must never change.** Any modification to FITID generation is a breaking change for users who have already imported OFX files — their financial software tracks transactions by FITID.

### How FITIDs are computed

```
token = "{account_id}|{posted_at}|{amount}|{normalized_label}|{seq}"
fitid = sha256(token)[:20]
```

### What must remain stable

| Component          | Rule                                                                 |
|--------------------|----------------------------------------------------------------------|
| `account_id`       | Verbatim from canonical statement                                    |
| `posted_at`        | ISO date string (YYYY-MM-DD)                                        |
| `amount`           | Decimal as-is (sign-significant)                                     |
| `normalized_label` | `normalize_label(name, memo)` — collapse whitespace, strip repeated punct, uppercase |
| `seq`              | 0-indexed duplicate counter within same `(posted_at, amount, label)` |
| Hash               | SHA-256, first 20 hex chars                                          |

### Safe changes

- Adding new fields to the canonical statement (as long as existing fields remain unchanged)
- Changing display/rendering logic

### Unsafe changes (require migration plan)

- Changing `normalize_label` logic (whitespace, punctuation, casing rules)
- Changing hash algorithm or truncation length
- Changing the token format string
- Reordering transactions before FITID assignment

---

## Sanity & Reconciliation Layer

The pipeline includes a **SANITY** stage between VALIDATE and EMIT:

```
PREFLIGHT → MINDEE → NORMALIZE → VALIDATE → SANITY → EMIT → WRITE
```

### What SANITY does

For each PDF (after validation passes):

1. **Computes statement-level statistics** — extracted/kept/dropped transaction counts, total credits/debits, net movement
2. **Attempts balance reconciliation** — if starting & ending balances are available (from raw Mindee response or operator entry), computes `reconciled_end = starting_balance + net_movement` and delta against expected ending balance
3. **Computes quality score** — base 100, with deductions per spec §6
4. **Displays structured Rich panel** — summary per PDF with colour-coded status
5. **Prompts operator** — Accept / Edit balances / Skip reconciliation

### Reconciliation thresholds

| Delta (abs) | Status |
|-------------|--------|
| ≤ 0.01 | OK |
| 0.01 – 1.00 | WARNING |
| > 1.00 | ERROR (requires force-accept) |

### Quality score deductions

| Condition | Points |
|-----------|--------|
| Reconciliation ERROR | -60 |
| Balances missing | -25 |
| >10% transactions dropped | -15 |
| Per validation WARNING category | -10 (cap 30) |
| Low Mindee confidence (if available) | -15 |

Classification: 80–100 = GOOD, 50–79 = DEGRADED, <50 = POOR.

### Non-interactive mode

With `--dev-non-interactive`, the sanity stage auto-accepts without prompting. Quality score is still computed and displayed in the batch summary.

### Balance data sources

1. **Raw Mindee response** — the SANITY layer scans the prediction dict for keys like `Starting Balance`, `starting_balance`, `opening_balance` etc. This works if the Mindee custom model includes balance fields.
2. **Operator manual entry** — prompted during the "Edit balances" flow.
3. **Not available** — if neither source provides balances, reconciliation is SKIPPED and quality is downgraded by 25 points.

### Key invariants

- The SANITY stage **never mutates** the validated statement. It is read-only.
- The SANITY stage **never blocks** the pipeline — it can always be skipped.
- Exceptions in the SANITY stage are caught and converted to `StageError(stage=Stage.SANITY)`, so one PDF's sanity failure does not crash the batch.

### Code layout

| File | Responsibility |
|------|----------------|
| `src/pdf2ofx/sanity/checks.py` | Pure computation: reconciliation math, quality scoring, balance extraction |
| `src/pdf2ofx/sanity/panel.py` | Rich panel rendering (display only) |
| `src/pdf2ofx/cli.py` → `_run_sanity_stage()` | Operator confirmation flow, wiring |
| `tests/test_sanity.py` | 24 unit tests covering reconciliation, quality, extraction, edge cases |

---

## Mindee Data Schema Reference

The full production schema is documented in [`docs/MINDEE_DATA_SCHEMA_REFERENCE.md`](docs/MINDEE_DATA_SCHEMA_REFERENCE.md). That file is the **canonical backup** of the Mindee custom model configuration.

### When to use it

- If the Mindee model or account is lost, deleted, or needs to be recreated from scratch
- When onboarding a new team member who needs to understand what Mindee extracts
- When adding or modifying fields in the Mindee UI — check the reference first to understand the current state

### How to recreate the schema

1. Open [`docs/MINDEE_DATA_SCHEMA_REFERENCE.md`](docs/MINDEE_DATA_SCHEMA_REFERENCE.md)
2. In the Mindee UI, create a new Custom Extraction model
3. For each field table in the document, create the field with the exact **Field Name** and **Field Type** shown
4. Copy **Description** and **Guideline** text into the Mindee UI
5. For the `transactions` field: set type to Nested Object, enable "Multiple items can be extracted", then add each subfield
6. Enable the **Confidence** option in model settings
7. Train the model with sample bank statement PDFs
8. Update `MINDEE_MODEL_ID` in `.env` with the new model ID

### Keeping it current

When you add or change fields in the Mindee UI, update `docs/MINDEE_DATA_SCHEMA_REFERENCE.md` to match. The reference document must always reflect the production model.

---

## Mindee Schema Constraints

The normalizer (`canonicalize.py`) supports **custom schema A only**.

### Expected prediction fields

**V1 (Title Case) statement-level:** `Transactions`, `Bank Name`, `Start Date`, `End Date`

**V1 transaction-level:** `Operation Date`, `Posting Date`, `Value Date`, `Amount Signed`, `Debit Amount`, `Credit Amount`, `Description`, `Row Confidence Notes`

**V2 (snake_case) statement-level:** `bank_name`, `bank_id`, `account_id`, `account_type`, `currency`, `start_date`, `end_date`, `starting_balance`, `ending_balance`, `detected_iban`, `detected_aid`, `transactions`

**V2 transaction-level:** `operation_date`, `posting_date`, `value_date`, `amount`, `debit_amount`, `credit_amount`, `description`

For the full field-by-field reference, see [`docs/MINDEE_DATA_SCHEMA_REFERENCE.md`](docs/MINDEE_DATA_SCHEMA_REFERENCE.md).

### Detection logic

- Custom schema A: any of `Transactions`, `Bank Name`, `Start Date` present
- Default Mindee bank statement: `account_number` or `list_of_transactions` present — **rejected** with `NormalizationError`
- Unknown: no recognized keys — **rejected**

### Adding a new schema

1. Add a detection branch in `canonicalize_mindee()`
2. Write a `_normalize_schema_X()` function
3. Map to the same canonical dict structure
4. Add fixture + test in `test_canonicalize.py`
5. Do **not** change the canonical dict shape — downstream (validator, FITID, OFX emitter) depends on it

---

## How to Safely Modify Normalization

### Guardrails

1. **Never change the canonical dict schema.** Validator, FITID, and OFX emitter all depend on its shape.
2. **Never change field mapping for existing schemas.** Changing which Mindee field maps to `posted_at` would alter FITIDs.
3. **Add, don't modify.** New schemas = new normalizer function, same output shape.
4. **Test with fixtures.** Every schema variant should have a fixture in `tests/fixtures/`.

### Adding a new Mindee field

1. Add extraction in the relevant `_normalize_schema_*` function
2. Map to an existing canonical field, or add a new one that downstream ignores
3. Add fixture data + assertions in tests

---

## Release Checklist

1. **Bump version** in `pyproject.toml` and `src/pdf2ofx/__init__.py`
2. **Run full validation:**
   ```bash
   uv sync
   uv run pytest -q
   uv run pdf2ofx --dev-canonical tests/fixtures/canonical_statement.json --dev-non-interactive
   ```
3. **Verify output:** `output/canonical_statement.ofx` exists and contains valid OFX
4. **Check FITID stability:** Re-run and confirm FITIDs in output match previous run
5. **Commit and tag:** `git tag v<version>`
6. **Push:** `git push && git push --tags`

---

## Known Failure Modes

| Failure | Cause | Resolution |
|---------|-------|------------|
| `[PREFLIGHT] Missing Mindee configuration.` | `.env` missing or incomplete | Add `MINDEE_V2_API_KEY` and `MINDEE_MODEL_ID` to `.env` |
| `NormalizationError: Mindee default bank statement schema` | Using Mindee's built-in schema instead of custom model | Switch to the correct custom model ID |
| `NormalizationError: Unrecognized Mindee schema` | API returned unexpected structure | Check Mindee model config, inspect `tmp/*.json` |
| All transactions dropped by validator | Missing dates, amounts, or FITIDs in extraction | Inspect canonical JSON, check Mindee model training data |
| OFX import shows duplicate transactions | FITID collision (same date + amount + label) | Expected for true duplicates; `seq` counter handles most cases |
| `pip install -e .` fails | Missing `__init__.py` or broken import paths | Run packaging validation checklist above |
| `[SANITY] Sanity check failed: ...` | Unexpected data in raw Mindee response | Inspect `tmp/<pdf>.json`; check for malformed prediction structure |
| Quality score DEGRADED with "balances missing" | Mindee model does not extract balances | Enter balances manually via "Edit balances", or skip to proceed |
| Reconciliation ERROR with large delta | OCR misread balance or amount values | Verify amounts in panel, edit balances, or force-accept |

---

## Troubleshooting

### Inspect intermediate state

Raw Mindee responses and dev markers are saved to `<base_dir>/tmp/`. On failure, `tmp/` is preserved by default.

### Force a clean state

```bash
Remove-Item -Recurse -Force input, output, tmp -ErrorAction SilentlyContinue
```

### Test a single fixture

```bash
uv run pdf2ofx --dev-canonical tests/fixtures/canonical_statement.json --dev-non-interactive --base-dir /tmp/debug
```

Then inspect `/tmp/debug/output/` and `/tmp/debug/tmp/`.
