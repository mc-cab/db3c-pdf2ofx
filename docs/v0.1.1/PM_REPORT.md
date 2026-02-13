# Recovery Mode v0.1.1 — PM Report

## 1. What Shipped

- **Docs:** `docs/v0.1.1/SCOPE.md`, `SPEC.md`, `UI_UX.md`; PARKED RFCs (Mindee model refactor, Settings wizard). SPEC defines `recover_*.canonical.json` format and the hard rule for recovery candidates.
- **Recovery mode:** First menu offers "Process PDFs" and "Recovery mode". Recovery: local preflight (dirs, local_settings, output writable); list `tmp/*.json` (excluding `tmp/recovery/**` and `*.raw.json` / `*.canonical.json`); RecoveryCandidate in-memory (raw + canonical + validation + sanity); multi-select; two artifacts per candidate (`recover_<name>.raw.json`, `recover_<name>.canonical.json`); sequential SANITY with "Back to list"; final summary with Confirm & proceed / Go back; conversion from `.canonical.json` only; cleanup prompt.
- **Selective tmp cleanup:** When operator chooses "Delete tmp/" after a run, only "clean" tmp files are deleted (reconciliation OK, quality GOOD, not skipped, not forced_accept). Others are kept and listed with reason in a panel.
- **Sanity:** `forced_accept` on SanityResult; "Back to list" in recovery; consistent menu (Accept, Edit balances, Edit transactions, Skip, Open source PDF, Quit; Back to list in recovery).

## 2. Commands Executed + Results

| Command | Result |
|--------|--------|
| `uv run pytest tests/ -v` | 47 passed, 1 warning |
| (Manual) Start pdf2ofx → Recovery mode | Lists tmp candidates; flow as per SPEC |

## 3. Risks / Known Gaps

- Recovery is interactive only; no automated E2E test.
- "Back to list" from SANITY goes to confirm/go_back prompt, not full candidate re-selection (acceptable for v0.1.1).
- Mindee integration test may hit pypdfium2 access violation on Windows; unrelated to this release.

## 4. How to Use Recovery Mode (Operator View)

1. Run `pdf2ofx` (or `uv run pdf2ofx`). At "Start pdf2ofx?" choose **Recovery mode**.
2. Ensure you have existing `tmp/*.json` files (from a previous run that wrote Mindee responses). If none, the tool exits.
3. Review the list of candidates (hash, period, tx count, quality). Select one or more with the checkbox; confirm.
4. For each selected file, the SANITY review runs (Accept / Edit balances / Edit transactions / Skip / Open source PDF / Back to list / Quit). On Accept or Skip, your choices are saved to `tmp/recovery/recover_<name>.canonical.json`; the raw Mindee JSON is never overwritten (`recover_<name>.raw.json`).
5. After all selected items are reviewed, choose **Confirm & proceed** to convert to OFX, or **Go back** to re-run SANITY for the modified subset.
6. Choose output mode (A = one OFX per file, B = concatenate) and format (OFX2/OFX1). OFX files are written to `output/`.
7. When asked, choose to delete or keep the recovery copies in `tmp/recovery/`. Original `tmp/*.json` files are never deleted by recovery.

## 5. Tmp Retention (Regular Process)

When you choose "Delete tmp/" after processing PDFs, only files that passed SANITY as "clean" (reconciliation OK, quality GOOD, not skipped, not forced accept) are removed. Any file that was questionable is kept and shown in a short panel with the reason (e.g. "reconciliation ERROR", "forced accept on ERROR").
