# pdf2ofx

Interactive PDF-to-OFX converter driven by Mindee extraction.

---

## Purpose
`pdf2ofx` scans `input/` for bank statement PDFs, calls Mindee for extraction, normalizes the response into a canonical statement structure, validates transactions, then emits OFX files to `output/`.

---

## Quick Start

### 1) Install runtime dependencies

```powershell
python -m pip install typer rich InquirerPy ofxtools mindee python-dotenv
```

`pip install -e .` is currently not usable (see `Packaging Status`).

### 2) Run interactive mode (Mindee path)

```powershell
python .\pdf2ofx.py
```

### 3) Minimal local run without Mindee/API keys

```powershell
python .\pdf2ofx.py --dev-canonical .\tests\fixtures\canonical_statement.json --dev-non-interactive
```

Expected file:

- `output/canonical_statement.ofx`

---

## Inputs

### File Types

| Mode | Accepted Input |
|---|---|
| Normal | `*.pdf` from `<base_dir>/input/` |
| Hidden dev mode | Canonical JSON files passed via repeated `--dev-canonical` |

`<base_dir>` defaults to the directory containing `pdf2ofx.py`, unless overridden with `--base-dir`.

### Supported Mindee Structure (Implemented)

Normalization currently supports custom schema A fields in prediction payloads:

- Statement-level keys: `Transactions`, `Bank Name`, `Start Date`, `End Date`
- Transaction keys: `Operation Date`, `Posting Date`, `Value Date`, `Amount Signed`, `Debit Amount`, `Credit Amount`, `Description`, `Row Confidence Notes`

Mindee default bank statement schema is detected and rejected with `NormalizationError`.

### Required/Assumed Data Rules

- `posted_at`: `Operation Date` -> `Posting Date` -> `Value Date`
- `amount`: `Amount Signed` first, otherwise derived from debit/credit
- Missing `account_id`: prompt in interactive mode, or set to `UNKNOWN` in `--dev-non-interactive`
- Missing account metadata before emission:
  - `bank_id` default: `DUMMY`
  - `currency` default: `EUR`
  - `account_type` default: `CHECKING`

---

## Outputs

### Files Generated

| Type | Path Pattern |
|---|---|
| Raw extraction JSON (normal mode) | `<base_dir>/tmp/<pdf_stem>.json` |
| Dev marker JSON (`--dev-canonical`) | `<base_dir>/tmp/<canonical_stem>.json` |
| OFX mode A (default) | `<base_dir>/output/<input_stem>.ofx` |
| OFX mode B (concat) | `<base_dir>/output/concat_<YYYYMMDD-HHMMSS>.ofx` |

### Output Transform Rules

- FITID generation: hash of `account_id | posted_at | amount | normalized(name+memo) | seq`
- Invalid transactions are removed by validator
- Missing `trntype` is derived:
  - `CREDIT` when amount >= 0
  - `DEBIT` when amount < 0
- Missing period is derived from min/max transaction date

### `tmp/` Cleanup Behavior

- Deleted automatically only if all processed PDFs succeed
- If any failure occurs, prompt defaults to keeping `tmp/`
- If user quits with `q`, `tmp/` is preserved

---

## CLI Reference

All implemented options are hidden internal flags (`hidden=True` in Typer).

| Flag | Type | Default | Behavior |
|---|---|---|---|
| `--dev-canonical` | `PATH` (repeatable) | unset | Bypass Mindee and read canonical JSON files directly |
| `--dev-non-interactive` | bool flag | `False` | Skip prompts; force output mode `A` and format `OFX2`; use fallbacks |
| `--dev-simulate-failure` | bool flag | `False` | In dev mode, inject one simulated post-validation failure (first item) |
| `--base-dir` | `PATH` | directory of `pdf2ofx.py` | Relocate working dirs (`input/`, `output/`, `tmp/`) and `local_settings.json` |

---

## Packaging Status

❌ Not properly structured for packaging.

### Audit Results

- `pyproject.toml`
  - `[project]` exists
  - `name`, `version`, and dependencies exist
  - `[build-system]` is missing
- Package layout
  - flat layout with multiple top-level module directories (`helpers`, `handlers`, `converters`, `validators`, `normalizers`)
  - no `__init__.py` package markers in those directories
- Entry points
  - no `[project.scripts]` / `console_scripts`
- Editable install check
  - `pip install -e . --no-deps` fails
  - setuptools error: `Multiple top-level packages discovered in a flat-layout`
- Runtime-after-install path
  - no install-time CLI path currently works because installation fails and no script entry point is defined

### Structural Fixes Required

1. Add `[build-system]` in `pyproject.toml` (setuptools backend or equivalent).
2. Define packaging layout explicitly:
   - adopt `src/` layout and configure discovery, or
   - declare packages/modules explicitly (`packages` / `py-modules`).
3. Add package markers (`__init__.py`) or explicit namespace-package config.
4. Define CLI entry point in `[project.scripts]` if install execution is required.

---

## Internal Architecture (Short)

### Entry File

- `pdf2ofx.py`

### Core Modules

- `handlers/mindee_handler.py`
- `normalizers/canonicalize.py`
- `normalizers/fitid.py`
- `validators/contract_validator.py`
- `converters/ofx_emitter.py`
- `helpers/fs.py`
- `helpers/ui.py`
- `helpers/errors.py`
- `helpers/reporting.py`
- `helpers/timing.py`

### Processing Pipeline

```text
input/*.pdf (or --dev-canonical)
  -> extract/load
  -> normalize
  -> ensure account metadata
  -> assign FITIDs
  -> validate
  -> emit OFX
  -> summarize + tmp cleanup decision
```

### Important Names (Code)

- `main`
- `infer_pdf`
- `canonicalize_mindee`
- `assign_fitids`
- `validate_statement`
- `emit_ofx`
- `render_summary`
- `StageError`

---

## Common Errors

| Symptom | Likely Cause |
|---|---|
| `[PREFLIGHT] Missing Mindee configuration.` | `MINDEE_V2_API_KEY` and/or `MINDEE_MODEL_ID` missing in non-dev mode |
| `No PDFs found in input/. Exiting.` | No `.pdf` files in `<base_dir>/input/` |
| Failure at stage `NORMALIZE` with schema message | Mindee payload does not match supported custom schema A |
| Failure at stage `VALIDATE` or `No usable transactions after validation.` | Required transaction fields missing/invalid; all transactions dropped |
| Failure at stage `MINDEE` (`Mindee client library unavailable`, `Mindee inference failed`, etc.) | Missing package, API/auth/network issue, or unexpected response structure |
| Exit code `1` with `No OFX files were generated ...` | All inputs failed before successful OFX write |

---

## Dev Notes

### Local Execution

- Interactive: `python .\pdf2ofx.py`
- Deterministic no-Mindee path: `python .\pdf2ofx.py --dev-canonical <file.json> --dev-non-interactive`

### Testing

- Command: `python -m pytest -q`
- Note: `pytest` is optional in `pyproject.toml` (`[project.optional-dependencies].test`), so install test extras or pytest explicitly before running.

### Where Business Logic Lives

- Normalization: `normalizers/canonicalize.py`
- FITID generation: `normalizers/fitid.py`
- Validation: `validators/contract_validator.py`
- OFX mapping/emission: `converters/ofx_emitter.py`

### Assumptions To Preserve

- Custom schema A key names are matched literally
- FITID determinism relies on exact token composition + duplicate sequence
- Validator may drop invalid transactions, and empty post-validation result is treated as failure
- Account defaults (`DUMMY`, `EUR`, `CHECKING`) are applied when metadata is missing