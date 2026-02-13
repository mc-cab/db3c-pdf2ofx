# Recovery Mode v0.1.1 — Post-Integration Report

## Commands Executed

```bash
uv run pytest tests/ -v
```

**Result:** 47 passed, 1 warning (Mindee deprecation). No failures introduced by Recovery Mode changes.

## Acceptable / Known Failure Points

- **test_mindee_integration.py:** May hit a Windows access violation in pypdfium2 when loading the Mindee client; test can still pass. This is an environment/dependency issue, not caused by recovery or tmp changes.
- **Recovery mode:** Interactive only; no automated end-to-end test for the full recovery flow (checkbox, SANITY, confirm/back). Manual QA recommended for first use.

## What Was Verified

- `list_tmp_jsons`: Only top-level `tmp/*.json`; excludes `tmp/recovery/**`, `*.raw.json`, `*.canonical.json`.
- `selective_tmp_cleanup`: Deletes only when keep_reason is None; reports kept files with reasons.
- `is_clean_for_tmp_delete` / `tmp_keep_reason`: Deterministic rules (OK, GOOD, not skipped, not forced_accept); N_A and forced_accept yield keep.
- CLI smoke (`test_cli_smoke`): Dev-canonical path still works; tmp preserved on simulated failure.
- All existing sanity, validator, canonicalize, fitid, ofx_emitter tests pass.

## Gaps / Follow-ups

- Optional: Add a recovery smoke test (e.g. with mocked prompts or fixture tmp dir) to lock behavior.
- "Back to list" from SANITY currently exits to the confirm/go_back prompt rather than full candidate re-selection; spec allows either for v0.1.1.
