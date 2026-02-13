# Recovery Mode v0.1.1 — UI/UX

## First menu (non–dev mode)

- **Prompt:** "Start pdf2ofx?"
- **Choices:** "Process PDFs" (default), "Recovery mode", "Quit (q)"
- **Tone:** Short, clear.

## Recovery mode

### Candidate list

- **Panel title:** e.g. "Recovery candidates (tmp/*.json)"
- **Per row:** Label = hash + period + count + quality; use original stem if available. Example: `e36118847891  2025-01-01 → 2025-01-31  42 tx  GOOD (85)` or `statement_jan  …  DEGRADED (62)`.
- **Control:** Checkbox list (Space to toggle, Enter to confirm). At least one must be selected to proceed.

### SANITY (recovery)

- **Options (always shown where applicable):** Accept, Edit balances, Edit transactions, Skip, Open source PDF (if path exists), **Back to list**, Quit.
- **Copy:** "Back to list" = return to candidate selection. No conditional hiding of Accept/Edit/Skip.

### Final summary

- **Content:** Which recovery items changed; high-level deltas (quality, reconciliation status).
- **Choices:** "Confirm & proceed" (to conversion), "Go back" (to modified-items subset, then re-run SANITY).

### Cleanup

- **Prompt:** "Delete recovery copies in tmp/recovery/ or keep for analysis?"
- **Choices:** Delete / Keep. Short explanation that original tmp files are never touched.

## Regular process — tmp cleanup

- When operator chooses "Delete tmp/": after selective delete, show a **short panel** listing any kept files and reason, e.g. "Kept: a1b2c3d4e5f6.json — reconciliation ERROR". Tone: factual, accountant-friendly.

## Tone

- Deliberate, minimal text. No wall of copy. Options visible and consistent.
