# Batch failure points and wasted Mindee credits

When a batch run crashes (unhandled exception), the process exits. Any PDFs that had **already been sent to Mindee and accepted** in the sanity step are effectively "done" from an API-cost perspective, but if the crash happens later (e.g. during move, tmp cleanup, or on a subsequent PDF), the user gets no summary, no OFX list, and possibly no clean state. Re-running may mean re-calling Mindee for the same PDFs again, i.e. **wasted credits**.

This document lists **where the batch can still fail** (as of the last review). No code changes are implied; it is a reference for future hardening.

---

## Top-level exception handling

In `main()` ([src/pdf2ofx/cli.py](src/pdf2ofx/cli.py)), the entire batch runs inside a `try` that only catches:

- `UserAbort` — user chose Quit; we print and return.
- `StageError` — stage failed; we print and return.

**Any other exception** (e.g. `OSError`, `PermissionError` in places we don’t catch, generic `Exception`) **propagates and exits the process**. The batch is considered "crashed."

---

## Failure points in flow order

### 1. Startup (before any PDF is processed)

| Location | What can raise | Effect |
|----------|----------------|--------|
| `ensure_dirs(base_dir)` | `OSError` (e.g. permission, read-only FS, path too long) | Batch exits before any Mindee call. No credits spent. |
| `_preflight(dev_mode)` | `StageError` if env vars missing | Caught; we print and return. No credits spent. |
| `load_local_settings(settings_path)` | `OSError` on read, `json.JSONDecodeError` (only inside the helper’s try) | If the helper raises (e.g. permission), batch exits. No credits spent. |
| `list_pdfs(input_dir)` | `OSError` (e.g. not a directory, permission on `iterdir()`) | Batch exits. No credits spent. |

So far: no Mindee credits at risk.

---

### 2. Per-PDF loop (Mindee + sanity + validation)

For each source PDF we only catch:

- `StageError`
- `NormalizationError`
- `ValidationError`

**Anything else** in the loop (e.g. `OSError` from `write_json(tmp_json_path, raw)` after Mindee returns, or a bug in sanity/validation that raises `ValueError`/`TypeError`) **is not caught** and **aborts the whole batch**.

- **Credits impact:** Mindee has already been called for this PDF (and possibly for previous PDFs in the same run). If we crash here, those API calls are already billed; re-running will call Mindee again for the same files unless the user removes them from `input/`.
- **Sanity stage:** The sanity stage itself is wrapped in `try`/`except Exception` and re-raised as `StageError`, so failures inside sanity (e.g. `open_path_in_default_app` failing) fail that one PDF and continue the batch. Only uncaught exceptions *outside* that inner try will crash the batch.

---

### 3. After OFX write, before move (tmp cleanup)

| Location | What can raise | Effect |
|----------|----------------|--------|
| `safe_delete_dir(tmp_dir)` | `OSError` from `shutil.rmtree` (e.g. file in use, permission) | Not inside any try/except. **Batch exits.** |

By this point, all Mindee calls for the run have been made, OFX files may have been written, and the user may have already accepted sanity for several PDFs. A crash here means: no summary, no move step, and a messy exit. Re-run might re-use tmp if preserved, but typically the user will re-run from scratch and may re-process the same PDFs → **wasted credits** if they don’t remove already-processed PDFs from `input/`.

---

### 4. Move phase (input → processed / failed)

We only catch **`PermissionError`** (e.g. file in use because the PDF is still open in a viewer).

- **Other `OSError`** (e.g. disk full, path too long, permission on destination dir, read-only filesystem): **not caught** → **batch exits.**

Same credit story: Mindee already called, OFX possibly written; crash here loses the rest of the run and can encourage a full re-run.

---

### 5. After move (summary and exit)

- `render_summary(...)` and the final `if not output_files: raise typer.Exit(1)` are not expected to raise, but any uncaught exception (e.g. from Rich or from a bug) would still exit the process.
- By then, moves have run (or been skipped for locked files); the main risk is already past.

---

## What is already handled (no crash)

- **Move:** `PermissionError` → we skip that file and print a message; batch continues.
- **Per-PDF:** `StageError`, `NormalizationError`, `ValidationError` → we record a failed result for that PDF and continue the loop.
- **OFX write (mode A and B):** Write failures are caught; we add an issue and mark the corresponding result(s) failed; batch continues.
- **Mindee handler:** Exceptions from the Mindee client are converted to `StageError` and thus handled per-PDF.

---

## Summary table (crashes = batch exit)

| Phase | Unhandled exception / condition | Wasted credits? |
|-------|----------------------------------|------------------|
| Startup | `ensure_dirs`, `list_pdfs`, `load_local_settings` raise | No (no Mindee yet). |
| Per-PDF loop | Any non–Stage/Norm/Val exception (e.g. `OSError` from `write_json`) | Yes (this and possibly previous PDFs already sent to Mindee). |
| Tmp cleanup | `safe_delete_dir(tmp_dir)` raises (e.g. file in use) | Yes (all PDFs already processed). |
| Move | `OSError` other than `PermissionError` (e.g. disk full, path too long) | Yes (all PDFs already processed). |
| After move | Any uncaught exception in summary/exit path | Yes. |

---

## Practical mitigation (no code change)

- Close any opened PDF viewer before the run reaches the move step, to avoid `PermissionError` on move (we now skip and warn, but closing avoids leaving files in `input/`).
- If the run crashes after some PDFs were accepted, check `output/` for OFX files that were written; move or back up those and the corresponding PDFs from `input/` so a re-run doesn’t re-send the same PDFs to Mindee.
