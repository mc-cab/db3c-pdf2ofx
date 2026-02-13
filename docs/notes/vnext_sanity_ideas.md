# vNext — SANITY improvements per layer (idea dump)

Ideas only; not part of v0.1.6. Preserved for future iteration.

## Diagnostic

- Page-aware diagnostics (e.g. “most issues on page 3”).
- Anomaly hints (unusual amounts, date gaps).
- Quarantine suggestions (e.g. “consider re-running OCR for pages 2–3”).
- Per-page quality or confidence when Mindee exposes it.

## Decision

- Shortcuts driven by diagnostic (e.g. “Jump to page with ERROR”).
- One-shot “Accept all GOOD” when batch is clean.
- Quick “Edit only this page” from summary.

## Strategy

- Scopes/filters concept (e.g. “only Page 2”, “only WARNING”).
- Page scopes for edit/invert (e.g. “Invert all on page 3”).
- Suspect-sign scopes (when debit/credit logic is reliable).
- Configurable return-after-edit targets (e.g. always L2 vs L1).

## Mutation

- Batch invert by page (when page is available).
- Mass operations with preview (e.g. “Remove all flagged — preview diff”).
- Merge/split transaction (if schema allows).

## Recovery

- Sort candidates by quality, delta, or tags.
- Filter recovery list by period or account.
- Bulk “Accept all GOOD” from recovery list.
