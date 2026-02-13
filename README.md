# pdf2ofx

Interactive PDF-to-OFX converter driven by Mindee extraction.

```
input/*.pdf ──► Mindee API ──► normalize ──► validate ──► SANITY ──► emit OFX ──► output/*.ofx
                 (or --dev-canonical JSON)

Recovery mode: tmp/*.json ──► list & select ──► SANITY ──► confirm ──► emit OFX (no Mindee call)
```

---

## Quick Start

### Set environment variables

Required for processing real PDFs (not needed for dev mode):

```cmd
setx MINDEE_V2_API_KEY "your-api-key"
setx MINDEE_MODEL_ID   "your-model-id"
```

Then **open a new terminal** (`setx` only takes effect in new sessions).

Alternatively, create a `.env` file in the project root:

```
MINDEE_V2_API_KEY=your-api-key
MINDEE_MODEL_ID=your-model-id
```

The app loads `.env` automatically. The file is gitignored.

### Using uv (recommended)

```bash
uv sync
uv run pdf2ofx --help
```

### Using pip (editable install)

```bash
pip install -e .
pdf2ofx --help
```

### Recovery mode (re-run SANITY on existing tmp JSON)

If you have `tmp/*.json` from a previous run, you can re-run the SANITY review and convert to OFX without calling Mindee again:

1. Run `pdf2ofx` and choose **Recovery mode** at the first menu.
2. Select one or more JSONs from the list, run SANITY (edit/accept/skip), then confirm and convert.
3. Raw Mindee responses are kept as `tmp/recovery/recover_<name>.raw.json`; only the canonical statement is updated after edits. See `docs/v0.1.1/` for full spec.

### Run without Mindee (dev mode)

```bash
# uv
uv run pdf2ofx --dev-canonical tests/fixtures/canonical_statement.json --dev-non-interactive

# pip
pdf2ofx --dev-canonical tests/fixtures/canonical_statement.json --dev-non-interactive
```

Expected output: `output/canonical_statement.ofx`

---

## Configuration

### Environment Variables

| Variable            | Required | Purpose                          |
|---------------------|----------|----------------------------------|
| `MINDEE_V2_API_KEY` | Yes *    | Mindee Platform API key          |
| `MINDEE_MODEL_ID`   | Yes *    | Mindee custom model identifier   |

\* Not required in dev mode (`--dev-canonical`).

Place a `.env` file in the working directory. Loaded via `python-dotenv` at startup.

### local_settings.json

Persists account metadata (`account_id`, `bank_id`, `currency`, `account_type`) between runs.
Created interactively when the user chooses to save.

---

## Directory Structure

```
db3c-pdf2ofx/
├── src/pdf2ofx/
│   ├── __init__.py
│   ├── __main__.py              # python -m pdf2ofx
│   ├── cli.py                   # Typer CLI + orchestration
│   ├── converters/
│   │   └── ofx_emitter.py       # OFX 1/2 emission
│   ├── handlers/
│   │   └── mindee_handler.py    # Mindee API client
│   ├── helpers/
│   │   ├── errors.py            # Stage enum + StageError
│   │   ├── fs.py                # File I/O utilities
│   │   ├── reporting.py         # Issue + Severity models
│   │   ├── timing.py            # Timer context manager
│   │   └── ui.py                # Rich console rendering
│   ├── normalizers/
│   │   ├── canonicalize.py      # Mindee → canonical statement
│   │   └── fitid.py             # Deterministic FITID generation
│   └── validators/
│       └── contract_validator.py
├── tests/
│   ├── fixtures/
│   │   ├── canonical_statement.json
│   │   └── mindee_custom_schema.json
│   ├── test_canonicalize.py
│   ├── test_cli.py
│   ├── test_fitid.py
│   ├── test_ofx_emitter.py
│   └── test_validator.py
├── docs/
├── pyproject.toml
└── README.md
```

---

## CLI Reference

All options are hidden dev flags (`hidden=True` in Typer).

| Flag                    | Type              | Default      | Behavior                                                       |
|-------------------------|-------------------|--------------|----------------------------------------------------------------|
| `--dev-canonical`       | `PATH` (repeat)   | unset        | Bypass Mindee; read canonical JSON files directly              |
| `--dev-non-interactive` | bool              | `False`      | Skip prompts; force output mode A + format OFX2; use fallbacks |
| `--dev-simulate-failure`| bool              | `False`      | Inject one simulated post-validation failure (first item)      |
| `--base-dir`            | `PATH`            | CWD          | Override working directory for `input/`, `output/`, `tmp/`     |

---

## Entry Points

| Method                    | Command                     |
|---------------------------|-----------------------------|
| Console script (installed)| `pdf2ofx [OPTIONS]`         |
| Python module             | `python -m pdf2ofx [OPTIONS]`|
| uv                        | `uv run pdf2ofx [OPTIONS]`  |

---

## Architecture

### Processing Pipeline

1. **Extract** — Mindee API inference (or load canonical JSON in dev mode)
2. **Normalize** — Map Mindee custom schema A to canonical statement
3. **Ensure metadata** — Prompt for or apply account defaults
4. **Assign FITIDs** — Deterministic SHA-256 hash per transaction
5. **Validate** — Drop invalid transactions, derive missing period/trntype
6. **Emit OFX** — Generate OFX 1 or OFX 2 via `ofxtools`
7. **Summary** — Rich console output + `tmp/` cleanup decision

### Key Modules

| Module                  | Responsibility                              |
|-------------------------|---------------------------------------------|
| `cli.py`                | Typer app, orchestration, prompts            |
| `mindee_handler.py`     | Mindee API client wrapper                    |
| `canonicalize.py`       | Mindee response → canonical dict             |
| `fitid.py`              | FITID generation (SHA-256, deterministic)    |
| `contract_validator.py` | Transaction validation, period derivation    |
| `ofx_emitter.py`        | Canonical dict → OFX bytes                   |

---

## Inputs and Outputs

### Accepted Inputs

| Mode   | Input                                                     |
|--------|-----------------------------------------------------------|
| Normal | `*.pdf` files from `<base_dir>/input/`                    |
| Dev    | Canonical JSON files passed via `--dev-canonical` (repeat) |

### Generated Outputs

| Type                   | Path Pattern                                 |
|------------------------|----------------------------------------------|
| Raw Mindee JSON        | `<base_dir>/tmp/<pdf_stem>.json`             |
| Dev marker JSON        | `<base_dir>/tmp/<canonical_stem>.json`       |
| OFX (mode A, default)  | `<base_dir>/output/<input_stem>.ofx`         |
| OFX (mode B, concat)   | `<base_dir>/output/concat_<timestamp>.ofx`   |

### `tmp/` Cleanup

- When you choose "Delete tmp/" after a run, only **clean** tmp files are deleted (reconciliation OK, quality GOOD, not skipped, not forced accept). Questionable files are kept and listed with a reason.
- Preserved on any failure (prompt in interactive mode).
- Preserved on user abort (`q`).
- **Recovery mode** uses `tmp/recovery/` for working copies (`.raw.json` + `.canonical.json`); originals in `tmp/` are never touched by recovery.

---

## Common Errors

| Symptom                                        | Likely Cause                                          |
|------------------------------------------------|-------------------------------------------------------|
| `[PREFLIGHT] Missing Mindee configuration.`    | `MINDEE_V2_API_KEY` / `MINDEE_MODEL_ID` not set       |
| `No PDFs found in input/. Exiting.`            | No `.pdf` files in `<base_dir>/input/`                |
| Failure at stage `NORMALIZE`                   | Mindee payload doesn't match custom schema A          |
| `No usable transactions after validation.`     | All transactions dropped by validator                 |
| Exit code `1`                                  | No OFX files generated                                |

---

## Testing

```bash
# uv
uv run pytest -q

# pip
python -m pytest -q
```

### Individual Tests

| Test file | Command | Description |
|-----------|---------|-------------|
| `test_cli.py` | `uv run pytest tests/test_cli.py -v` | CLI smoke test: invokes Typer with --dev-canonical, --dev-non-interactive, --dev-simulate-failure; verifies exit code 0, OFX output exists, and tmp/ is preserved on partial failure. |
| `test_canonicalize.py` | `uv run pytest tests/test_canonicalize.py -v` | Normalization: loads Mindee custom schema fixture and verifies canonicalize_mindee produces correct account, period, transaction dates, amounts, names, and memos. |
| `test_fitid.py` | `uv run pytest tests/test_fitid.py -v` | FITID determinism: verifies compute_fitid returns identical hashes for identical inputs, and assign_fitids produces unique FITIDs for duplicate transactions (via sequence counter). |
| `test_ofx_emitter.py` | `uv run pytest tests/test_ofx_emitter.py -v` | OFX emission: builds a canonical statement, runs validation and FITID assignment, emits OFX2, and checks required OFX tags (CURDEF, BANKACCTFROM, STMTTRN, FITID) are present. |
| `test_validator.py` | `uv run pytest tests/test_validator.py -v` | Contract validation: verifies validator derives trntype, passes clean statements, drops transactions with missing fields, and warns on debit/credit conflicts. |
| `test_mindee_integration.py` | `uv run pytest tests/test_mindee_integration.py -v` | Live Mindee API integration: calls real API with PDF from fixtures, normalizes, assigns FITIDs, validates, and checks full pipeline. Skipped if env vars or test PDFs are missing. |

Test extras: `pip install -e ".[test]"` or `uv sync` (auto-includes test deps).

---

## Dev Mode

Dev mode bypasses Mindee entirely. Use it for:

- Local testing without API keys
- Validating canonical JSON fixtures
- CI pipelines

```bash
uv run pdf2ofx \
  --dev-canonical tests/fixtures/canonical_statement.json \
  --dev-non-interactive \
  --base-dir /tmp/test-run
```
