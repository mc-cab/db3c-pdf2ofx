# Recovery Mode v0.1.1 — Behavioral Spec

## 1. Recovery candidate discovery

**Hard rule:** Recovery candidates are exactly:

- **Included:** Files matching `tmp/*.json` (top-level `tmp/` only).
- **Excluded:**
  - Any path under `tmp/recovery/` (i.e. `tmp/recovery/**`).
  - Any file whose name ends with `.raw.json` or `.canonical.json`.

So: only raw Mindee response JSONs in the top-level tmp directory are candidates; recovery artifacts and subdirectories are never listed as candidates.

## 2. Recovery artifacts (two per selected candidate)

For each selected candidate, recovery creates **two** files under `tmp/recovery/` (same basename stem, different suffixes):

| File | Content | Mutated by SANITY? |
|------|--------|--------------------|
| `recover_<name>.raw.json` | Raw Mindee API response (paid artifact) | **Never.** Copy once; never overwrite. |
| `recover_<name>.canonical.json` | Canonical statement (see §3) used for conversion | **Yes.** Updated after each Accept/Skip in SANITY. |

Conversion (OFX emission) reads **only** `recover_<name>.canonical.json`.

## 3. Format of `recover_*.canonical.json`

`recover_*.canonical.json` must be a **canonical statement** as consumed by the converter (validator + OFX emitter). No ambiguity: the following shape is required.

### 3.1 Top-level keys (required)

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `schema_version` | string | Yes | e.g. `"1.0"` |
| `account` | object | Yes | Account metadata; see §3.2 |
| `period` | object | Yes | Statement period; see §3.3 |
| `transactions` | array | Yes | Non-empty array of transaction objects; see §3.4 |
| `source` | object | No | Optional; e.g. `{"origin": "mindee", "document_id": "..."}` |

### 3.2 `account` object

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `account_id` | string | Yes | Account identifier |
| `bank_id` | string | No | Bank identifier (defaulted if missing) |
| `account_type` | string | No | e.g. `CHECKING` |
| `currency` | string | No | e.g. `EUR` |

### 3.3 `period` object

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `start_date` | string | Yes | ISO date `YYYY-MM-DD` |
| `end_date` | string | Yes | ISO date `YYYY-MM-DD` |

### 3.4 Each element of `transactions` array

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `fitid` | string | Yes | Unique FITID (assigned before SANITY) |
| `posted_at` | string | Yes | ISO date `YYYY-MM-DD` |
| `amount` | number/string | Yes | Signed decimal (credit &gt; 0, debit &lt; 0) |
| `trntype` | string | Yes | `CREDIT` or `DEBIT` (validator derives if missing) |
| `name` | string | No | Transaction description (OFX NAME) |
| `memo` | string | No | Memo (OFX MEMO) |
| `debit` | number/string | No | Debit amount if present |
| `credit` | number/string | No | Credit amount if present |

The converter (and validator) expects this exact shape. Recovery must persist the validated canonical statement (after FITID assignment and SANITY edits) as `.canonical.json`; no extra or different keys are required for conversion.

## 4. Recovery flow (sequence)

1. **Local preflight:** Ensure dirs, load `local_settings.json`, verify output dir writable. No Mindee checks.
2. **List candidates:** Per §1; if empty, exit with message.
3. **Build RecoveryCandidates:** For each candidate path, load raw JSON, canonicalize, validate, assign FITIDs, compute sanity. Store in-memory (raw, canonical statement, validation issues, sanity result). Labels: hash + period + count + quality; stem if available.
4. **Multi-select:** Operator selects which candidates to recover (order = processing order).
5. **Copy to recovery:** For each selected candidate, write `recover_<name>.raw.json` (copy of raw) and `recover_<name>.canonical.json` (initial canonical from step 3). Never overwrite `.raw.json` afterward.
6. **Sequential SANITY:** For each selected item, run SANITY (reuse RecoveryCandidate if no prior edits; else reload from `.raw.json` and recompute). On Accept/Skip: write updated canonical statement to `recover_<name>.canonical.json` only. "Back to list" returns to **candidate selection** (step 4).
7. **Final summary:** List changed items; prompt "Confirm & proceed" / "Go back". **Go back** = show subset of **modified items** only; re-run SANITY for that subset (loop to step 6).
8. **Conversion:** Load each `recover_<name>.canonical.json`, validate (idempotent), emit OFX, write to output. No Mindee.
9. **Cleanup:** Prompt to delete or keep files in `tmp/recovery/`. Do not touch original `tmp/*.json`.

## 5. Selective tmp cleanup (regular process)

When operator chooses "Delete tmp/" after a run:

- **Delete** only files for which the corresponding SANITY result is **clean**:
  - `reconciliation_status == "OK"`
  - `quality_label == "GOOD"`
  - `skipped == False`
  - `forced_accept == False`
- **Keep** all other tmp files (and report reason: e.g. reconciliation ERROR, quality DEGRADED, skipped, forced accept, or N_A when SANITY was absent).
- Use explicit statuses: `reconciliation_status` in `OK | WARNING | ERROR | SKIPPED | N_A`, `quality_label` in `GOOD | DEGRADED | POOR | N_A`. `N_A` = SANITY was not run for that file.

## 6. Back semantics

- **"Back to list"** (from SANITY in recovery): return to **candidate selection** (full list of tmp candidates).
- **Final summary "Go back"**: return to **selection among modified items** only; then re-run SANITY for that subset.
