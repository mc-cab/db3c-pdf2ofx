—-

doc_id: spec_pdf2ofx_v0_1
title: “SPEC — pdf2ofx (Mindee → JSON → OFX)”
owner: Mathieu
status: draft
doc_type: spec
version: 0.1.1
created: 2026-02-06
updated: 2026-02-06

—-

# NOTE

This SPEC was updated to reflect a **new output strategy**:

* **Target**: OFX2 (real XML)
* **Fallback**: OFX1 via **ofxtools** (no hand-rolled SGML writer)

## authority: source_of_truth

# SPEC — pdf2ofx (Mindee → JSON → OFX) — v0.1.1

## 1) Overview

**Purpose:** Batch-convert PDF bank statements into **importable OFX** by using **Mindee extraction** + a strict **canonical JSON contract** + **ofxtools** to emit OFX.

**Why:** PDF statements keep showing up. Manual entry is slow. OFX imports natively into ACD/Pennylane (they handle entry logic + downstream reaffectation), so this tool is the fastest POC outcome.

**Target (v0.1.1):** Devtool-grade POC: correct enough to import, fast to implement, zip-friendly, isolated.

**Output strategy (critical):**

* 🎯 **Target format:** **OFX2** (real XML)
* 🛟 **Fallback:** **OFX1** generated via **ofxtools** (NOT a homemade converter)

—

## 2) Goals (v0.1.1)

* Operator drops PDFs into `input/`.
* Tool calls Mindee (polling) for each PDF.
* Tool stores **raw extraction JSON** in `tmp/`.
* Tool normalizes raw extraction into a **canonical JSON** contract (post-Mindee, pre-OFX).
* Tool converts canonical JSON → OFX using **ofxtools**.
* Operator chooses output mode:

  * **A (default):** one OFX per PDF
  * **B:** concatenate into one OFX
* Tool writes OFX to `output/`.
* Tool deletes `tmp/` according to the success rule.
* Tool prints a **scan-friendly Rich summary**.

—

## 3) Hard Constraints (MUST / MUST NOT)

### MUST

* Live in **isolated folder**: `Python_devtools/pdf2ofx/` (portable/zippeable, no coupling).
* Use standard devtool stack:

  * Typer (CLI)
  * Rich (pretty output + summary)
  * InquirerPy (interactive prompts)
  * Include **”q” to quit** (consistent with other devtools)
* Be modular but minimal (allowed: `helpers/`, `handlers/`, `converters/`, `validators/`, `normalizers/`).
* Use **ofxtools** for OFX emission:

  * Target: **OFX2 XML**
  * Fallback: **OFX1** emitted by ofxtools (no hand-built SGML)
* Keep a temp JSON output directory `tmp/` and **delete it only after successful processing** (see §9).
* Surface errors clearly + provide actionable suggestions.
* Default flow is interactive and folder-based (no pasting input paths).

### MUST NOT

* Turn into a packaged/public release.
* Add scope beyond v0.1.
* Log raw bank transaction details to console.

—

## 4) Scope & Non-Goals

### In scope

* PDF → Mindee inference (polling)
* Save raw Mindee responses (`tmp/`)
* Normalize extraction into **canonical JSON contract** (validator enforced)
* OFX generation aimed at **ACD and Pennylane import** using **ofxtools**

  * Target: OFX2 XML
  * Fallback: OFX1 via ofxtools
* Two output modes (per-file / concatenated)
* Minimal config strategy (API key + model id)
* Minimal interactive prompts **only if required canonical fields are missing**

### Out of scope (explicit)

* Any Toolkit integration refactor
* Packaging/installer/publishing
* Advanced bank heuristics beyond what Mindee returns
* Reconciliation / contrepartie mapping
* UI beyond terminal
* Indexing/archiving beyond `output/`

—

## 5) Folder Layout (v0.1.1)

Inside `Python_devtools/pdf2ofx/`:

```
Python_devtools/pdf2ofx/
  README.md
  pyproject.toml
  pdf2ofx.py                 # devtool entry point (Typer)

  input/                     # operator drops PDFs here
  output/                    # generated OFX here
  tmp/                       # raw JSON responses (temporary)

  handlers/
    mindee_handler.py         # Mindee API calls + retry/backoff

  normalizers/
    canonicalize.py           # Mindee → canonical JSON

  validators/
    contract_validator.py     # enforce v0.1.1 JSON→OFX2 contract constraints

  converters/
    ofx_emitter.py            # ofxtools-based OFX2 (target) + OFX1 (fallback)

  helpers/
    fs.py                     # folder checks, safe delete, naming
    timing.py                 # perf timer helpers
    ui.py                     # Rich helpers (tables, panels)
    errors.py                 # user-facing error types + formatting
```

Repo root convenience:

* `ofx.bat` at repo root → launches this devtool in interactive mode.

—

## 6) Inputs

### 6.1 Local inputs

* `input/*.pdf` (batch)

### 6.2 Secrets / config inputs

* Mindee API key (env var preferred)
* Mindee model id (env var preferred)
* Optional OFX account metadata (prompted once per run; can be stored locally in a gitignored file)

—

## 7) Data Contracts

### 7.1 Raw extraction (Mindee)

Mindee output is saved as-is into `tmp/` for traceability/debug.

> Note: In v0.1.1 we stop treating Mindee’s schema as “the OFX schema”.
> Mindee is **input**. The tool’s **truth** is the canonical contract below.

#### 7.1.1 Your custom model schema (reference)

This tool must treat **field names as authoritative**, including spaces/case.

```json
{
  “Bank Name”: {“type”: “string”},
  “Start Date”: {“type”: “date”},
  “End Date”: {“type”: “date”},
  “Starting Balance”: {“type”: “number”},
  “Ending Balance”: {“type”: “number”},
  “Transactions”: {
    “type”: “array”,
    “items”: {
      “type”: “object”,
      “properties”: {
        “Operation Date”: {“type”: “date”},
        “Value Date”: {“type”: “date”},
        “Posting Date”: {“type”: “date”},
        “Description”: {“type”: “string”},
        “Amount Signed”: {“type”: “number”},
        “Debit Amount”: {“type”: “number”},
        “Credit Amount”: {“type”: “number”},
        “Row Confidence Notes”: {“type”: “string”}
      }
    }
  }
}
```

### 7.2 Canonical JSON contract (post-Mindee, pre-OFX)

This is the **designer-grade contract** the pipeline must enforce before any OFX emission.

#### 7.2.1 Canonical schema (minimal)

**Statement (root)**

* `schema_version` (string, e.g. `”1.0”`)
* `source` (object, optional)

  * `origin` (string, e.g. `”mindee” | “manual” | “other”`)
  * `document_id` (string, optional)
* `account` (object)

  * `account_id` (string, required)
  * `bank_id` (string, required-ish)
  * `account_type` (string, required; default `”CHECKING”`)
  * `currency` (string, required; default `”EUR”`)
* `period` (object, optional but recommended)

  * `start_date` (date, optional)
  * `end_date` (date, optional)
* `transactions` (array[Transaction], required)

**Transaction**

* `fitid` (string, required, unique within file)
* `posted_at` (date, required) — **operation date** (firm standard)
* `amount` (number, required, signed)
* `debit` (number, optional)
* `credit` (number, optional)
* `name` (string, required-ish)
* `memo` (string, optional)
* `trntype` (string, optional; derive from sign if missing)

#### 7.2.2 Hard constraints (validator, v0.1.1)

* `posted_at` present and parseable
* `amount` present and parseable
* `fitid` present, non-empty, **unique** within output file
* `account.currency` present (default `EUR`)

#### 7.2.3 Coherence constraints (recommended)

* Debit/credit coherence:

  * If `debit` present and non-zero → expected `amount = -abs(debit)`
  * If `credit` present and non-zero → expected `amount = +abs(credit)`
  * If both debit and credit non-zero → invalid (reject/flag)
  * If signed `amount` exists + debit/credit exists → verify matches within tolerance (0.01)
* Period coherence:

  * If `period` present: start_date ≤ posted_at ≤ end_date (warn/flag)
  * If missing: derive start=min(posted_at), end=max(posted_at)

#### 7.2.4 FITID strategy (v0.1.1)

**Strategy A (required): stable hash of normalized tuple**

* Hash over: `account_id | posted_at | amount | normalized_label | seq`
* normalized_label = cleaned name/memo (trim, collapse whitespace, uppercase, strip repeated punctuation)
* seq = occurrence index for duplicates (0..n)

### 7.3 Mapping cheat sheet (canonical JSON → OFX2)

| Canonical JSON                        | OFX2 Element/Tag        |
| -———————————— | ———————— |
| `account.currency`                    | `CURDEF`                |
| `account.bank_id`                     | `BANKACCTFROM/BANKID`   |
| `account.account_id`                  | `BANKACCTFROM/ACCTID`   |
| `account.account_type`                | `BANKACCTFROM/ACCTTYPE` |
| `period.start_date` (or derived)      | `BANKTRANLIST/DTSTART`  |
| `period.end_date` (or derived)        | `BANKTRANLIST/DTEND`    |
| `transactions[].posted_at`            | `STMTTRN/DTPOSTED`      |
| `transactions[].amount`               | `STMTTRN/TRNAMT`        |
| `transactions[].trntype` (or derived) | `STMTTRN/TRNTYPE`       |
| `transactions[].fitid`                | `STMTTRN/FITID`         |
| `transactions[].name`                 | `STMTTRN/NAME`          |
| `transactions[].memo`                 | `STMTTRN/MEMO`          |

Notes:

* Signon (`SONRS`) can be generated statically (no need to carry in JSON).
* Balances are optional (v0.2+).

—

## 8) Output Contracts

### 8.1 Output files

* Mode A: `output/<pdf_stem>.ofx`
* Mode B: `output/concat_<YYYYMMDD-HHMMSS>.ofx`

### 8.2 OFX format requirements (v0.1.1)

**Primary:** emit **OFX2 (XML)** using **ofxtools**.

**Fallback:** if needed, emit **OFX1** using **ofxtools** (still library-generated, not handwritten).

Compliance target:

* We do **not** aim for DTD-level perfection.
* We aim for “accepted by Pennylane and ACD” (import success) with a sane bank statement structure.

OFX content requirements (minimal for import):

* `<CURDEF>` from `account.currency`
* `<BANKACCTFROM>` built from `account.*`
* `<BANKTRANLIST>` with `DTSTART/DTEND` (provided or derived)
* `<STMTTRN>` entries with: `DTPOSTED`, `TRNAMT`, `FITID`, `NAME` (+ `MEMO` optional), `TRNTYPE` (provided or derived)

Output files:

* Mode A: `output/<pdf_stem>.ofx`
* Mode B: `output/concat_<YYYYMMDD-HHMMSS>.ofx`

—

## 9) tmp/ retention + cleanup rule

**Goal:** keep JSON available if something fails; delete only when we know the run is good.

Rule:

* If **all PDFs** were successfully processed by Mindee AND all selected conversions succeeded AND OFX file(s) were written:

  * Delete `tmp/` automatically.
* If **any failure** occurred:

  * Prompt operator:

    * Default = **KEEP** `tmp/` for debugging.
    * Offer `Delete tmp/ anyway` as an explicit choice.

—

## 10) Configuration

### 10.1 Mindee auth

* API key read from **env var first**.
* Optional local `.env` for dev convenience (gitignored).

Required keys:

* `MINDEE_V2_API_KEY`
* `MINDEE_MODEL_ID` (or `PDF2OFX_MODEL_ID` — pick one and document it)

### 10.2 Canonical contract completion (operator prompts)

We minimize prompts. The operator is only prompted **when required canonical fields are missing/unusable** after normalization.

Promptable fields (only if missing):

* `account.account_id` (prefer IBAN, else account number)
* `account.bank_id` (bank/routing id; may be derived if absent)
* `account.account_type` (default `CHECKING`)
* `account.currency` (default `EUR`)

Persistence:

* Allow saving these values locally in a gitignored file (e.g. `local_settings.json`) to avoid repeated prompts.

—

## 11) UX Flow (interactive-first)

1. Launch tool (`ofx.bat` or `python pdf2ofx.py`)
2. Preflight checks:

   * Ensure `input/`, `output/`, `tmp/` exist (create if missing)
   * Validate API key + model id present
3. Scan `input/` for PDFs

   * If none → show message + exit
4. Processing loop (per PDF):

   * Send to Mindee
   * Save raw response JSON to `tmp/<pdf_stem>.json`
   * Normalize Mindee output → **canonical JSON**
   * Validate canonical JSON (hard constraints)
   * If required fields missing: prompt operator **once per run** (with defaults) and re-validate
5. After all PDFs processed:

   * Prompt output mode:

     * A) One OFX per PDF (default)
     * B) Concatenate all into a single OFX
   * Prompt output format (default OFX2):

     * OFX2 XML (default)
     * OFX1 via ofxtools (fallback)
6. Emit OFX using ofxtools
7. tmp cleanup per §9
8. Print final Rich summary (table + totals + execution time)

UX rules:

* In every menu/prompt: allow **q** to abort.
* Abort should be graceful:

  * No partial tmp deletion
  * Output files already written remain

## 12) Error Handling Strategy

### 12.1 Error categories

* **Preflight**: missing API key, missing model id, missing folders, no PDFs
* **Mindee call**: network issues, auth (401), rate limit (429), invalid file
* **Schema / extraction**: required fields missing, empty transactions
* **Conversion**: invalid date, invalid amount, write permissions

### 12.2 Error UX requirements

* For each failed PDF, show:

  * PDF name
  * stage (Mindee / parse / convert)
  * short error summary
  * suggested fix (1–2 bullet points)
* Never print raw full JSON or raw bank lines to console.
* Keep a `—debug` flag reserved for later (v0.2) if you want to print extra info.

—

## 13) Acceptance Tests (v0.1.1)

### Manual acceptance checks

1. Put 2+ PDFs into `input/`.
2. Run tool.
3. Default path (OFX2, Mode A):

   * `output/` contains `*.ofx` per PDF.
4. Mode B (concat):

   * `output/` contains `concat_<timestamp>.ofx`.
5. Fallback path (OFX1 via ofxtools):

   * Run again, choose OFX1, ensure file emits and imports.
6. Import into Pennylane and/or ACD:

   * OFX is accepted.
   * Transactions appear with dates/amounts/descriptions.
7. Trigger common failures:

   * No API key → readable error + fix.
   * Wrong API key → readable error + fix.
   * Password-protected PDF → readable error + fix.
   * Empty extraction → PDF marked failed; summary reflects it.
   * Missing canonical account fields → operator prompted; values persisted.
8. tmp cleanup behavior:

   * All succeed → tmp deleted.
   * Any fail → prompt; default keep.

### “Done” checklist

* ✅ Interactive flow works without pasting paths
* ✅ OFX2 generated (default)
* ✅ OFX1 fallback generated via ofxtools
* ✅ tmp cleanup rule implemented
* ✅ Rich summary is scan-friendly
* ✅ Root `ofx.bat` exists and works

## 14) Upgrade Path (post v0.1)

### v0.2 (still devtool-grade)

* Add optional `—mode` and `—keep-tmp` flags (non-interactive support)
* Add schema fields to reduce operator prompts:

  * IBAN / Account Number / BankID
* Add “dry-run” (extract + validate only)

### v0.3 (toward Toolkit integration)

* Move core logic into a reusable internal module (still private)
* Add structured run logs (sanitized)
* Add basic test fixtures with sample JSON (not real bank data)

—

## 15) Risks & Limitations (v0.1.1)

* OCR/extraction varies by bank layout; some PDFs may fail.
* FITID stability is crucial: wrong strategy → duplicates on re-import.
* Concat mode may mix periods; period derivation must stay sane.
* OFX2 vs OFX1 importer quirks: fallback exists to reduce risk.

## 16) Changelog

* v0.1 (2026-02-06): Initial SPEC for devtool POC
