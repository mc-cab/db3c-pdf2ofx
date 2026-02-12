# pdf2ofx (Mindee → JSON → OFX)

## Setup

1. Install dependencies (repo root `requirements.txt` covers runtime).
2. Set environment variables:

```bash
export MINDEE_V2_API_KEY="your_api_key"
export MINDEE_MODEL_ID="your_model_id"
```

Optional: create a `.env` file in `lab/pdf2ofx/` with those values (environment vars override it).

## Usage

1. Drop PDFs into `lab/pdf2ofx/input/`.
2. From repo root, run:

```bat
ofx.bat
```

The tool guides you through:
- Processing PDFs
- Output mode: A) one OFX per PDF (default) or B) concatenated
- Output format: OFX2 (default) or OFX1 fallback

## Output

- Mode A: `lab/pdf2ofx/output/<pdf_stem>.ofx`
- Mode B: `lab/pdf2ofx/output/concat_<timestamp>.ofx`

## tmp/ Cleanup

- Raw Mindee JSON is saved to `lab/pdf2ofx/tmp/<pdf_stem>.json` during processing.
- If all PDFs succeed end-to-end, `tmp/` is deleted automatically.
- If any failure occurs, you are prompted to keep or delete `tmp/` (default keep).
- If you quit with `q`, `tmp/` is preserved.

## Tests

From repo root:

```bash
python -m pytest -q
```
