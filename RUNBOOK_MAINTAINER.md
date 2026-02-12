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

## Mindee Schema Constraints

The normalizer (`canonicalize.py`) supports **custom schema A only**.

### Expected prediction fields

**Statement-level:** `Transactions`, `Bank Name`, `Start Date`, `End Date`

**Transaction-level:** `Operation Date`, `Posting Date`, `Value Date`, `Amount Signed`, `Debit Amount`, `Credit Amount`, `Description`, `Row Confidence Notes`

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
