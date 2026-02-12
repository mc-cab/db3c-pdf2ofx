# pdf2ofx

Interactive PDF-to-OFX converter driven by Mindee extraction.

```
input/*.pdf ──► Mindee API ──► normalize ──► validate ──► emit OFX ──► output/*.ofx
                 (or --dev-canonical JSON)
```

---

## Quick Start

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

- Auto-deleted when all PDFs succeed
- Preserved on any failure (prompt in interactive mode)
- Preserved on user abort (`q`)

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
