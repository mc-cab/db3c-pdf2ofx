# Recovery Mode v0.1.1 — Scope

## Goals

- Let the operator re-open existing `tmp/*.json` Mindee responses and re-run the SANITY review flow without calling Mindee again.
- Provide a final summary and confirm/back loop before OFX conversion.
- Never lose raw Mindee JSON (paid artifact); persist two artifacts in recovery: raw + canonical.
- Improve regular-process deletion: never automatically delete "questionable" tmp files (reconciliation skipped/error, forced accept, quality &lt; GOOD).
- Keep sanity menu consistent (Accept / Edit balances / Edit transactions / Skip / Open source PDF / Quit) and add Back to list in recovery.

## Non-Goals

- No Mindee API calls in Recovery Mode.
- No change to canonicalization, validation, FITID, or emission logic (except wiring for recovery entrypoint).
- No settings/profile wizard; no Mindee model refactor (parked as RFCs).

## Constraints

- Minimal, additive code; accountant-friendly and robust.
- Recovery candidates: only `tmp/*.json`, excluding `tmp/recovery/**` and any `*.raw.json` / `*.canonical.json`.

## Acceptance Criteria

- Entry: first menu offers "Process PDFs" and "Recovery mode".
- Recovery: list candidates (per exclusion rule), show summary (hash + period + count + quality; stem if available), multi-select, copy to `tmp/recovery/` as `.raw.json` + `.canonical.json`, run SANITY sequentially, final summary, confirm or go back (to modified subset).
- On confirm: convert using `.canonical.json` only; no Mindee.
- Cleanup: prompt to delete or keep recovery copies; never touch original tmp.
- Regular run: "Delete tmp/" only removes clean files; keep and report questionable (status/label/forced_accept per spec).
