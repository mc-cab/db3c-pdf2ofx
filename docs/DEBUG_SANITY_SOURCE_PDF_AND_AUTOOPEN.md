# Debug report + fix plan: SANITY "Open source PDF" and auto-open

## Issue summary

- **Recovery mode:** SANITY menu does not show "Open source PDF".
- **Requirement:** Regular mode should still show it; recovery should show it when provenance exists.
- **Additional requirement:** When operator chooses "Edit balances" or "Edit transactions", auto-open the source PDF when available (both modes).

---

## 1) Where "Open source PDF" is decided and what `source_path` is passed

### 1.1 Inclusion of "Open source PDF" in the menu

**File:** `src/pdf2ofx/cli.py`  
**Location:** Lines 371–372 inside `_run_sanity_stage`:

```python
if source_path is not None and source_path.exists():
    choices.append(("Open source PDF", "open"))
```

So the option is shown only when `source_path` is set and the path exists.

### 1.2 Normal flow — `source_path` is set

**File:** `src/pdf2ofx/cli.py`  
**Location:** Line 906 (inside the main "Process PDFs" loop):

```python
source_path=source if not dev_mode else None,
```

- `source` is the `Path` of the PDF being processed.
- In normal (non–dev) mode, `source_path` is the PDF path → "Open source PDF" is shown.
- In dev mode it is `None` → option hidden.

**Conclusion:** Regular mode shows "Open source PDF" when not in dev mode.

### 1.3 Recovery flow — `source_path` is always `None`

**File:** `src/pdf2ofx/cli.py`  
**Location:** Line 664 (recovery SANITY loop):

```python
source_path=None,
```

Recovery always passes `None`, so "Open source PDF" is never added.

**Reason:** Recovery builds candidates only from `tmp/*.json`. Tmp filenames are hashes of the original PDF stem (`tmp_json_path(tmp_dir, source.stem)` → `tmp/<hash>.json` in `fs.py`). The original PDF path is not stored anywhere, so recovery has no way to pass a `source_path`.

---

## 2) Provenance today

- **No sidecar or meta file** exists in the codebase (grep for `.meta`, `provenance`, `source_pdf`, `sidecar` returns nothing).
- **Tmp path computation:** `fs.tmp_json_path(tmp_dir, source_stem)` → `tmp_dir / f"{hashlib.sha256(source_stem.encode()).hexdigest()[:12]}.json"`. The stem is hashed; the original path is not persisted.
- **Where tmp JSON is written:** `_process_raw_pdf` in `cli.py` (lines 312–322) receives `tmp_json_path` and writes the raw Mindee response with `write_json(tmp_json_path, raw)`. At that moment both `pdf_path` and `tmp_json_path` are available; no meta is written.
- **Legacy tmp:** Old `tmp/*.json` files have no associated meta; recovery cannot infer the source PDF for them.

---

## 3) Exact insertion points for the fix

### 3.1 Persist PDF provenance at extraction time

- **Where:** Right after `write_json(tmp_json_path, raw)` in `_process_raw_pdf` (after line 319 in `cli.py`). Alternatively, the caller could write the meta immediately after `_process_raw_pdf` returns (in the same loop around line 854), which keeps `_process_raw_pdf` unchanged and leaves all provenance logic in the CLI.
- **What:** Create a sidecar path from the tmp JSON path: same directory, same stem, suffix `.meta.json` (e.g. `tmp/<hash>.meta.json`). Write a small JSON payload, e.g. `{"source_pdf_path": str(pdf_path.resolve()), "source_name": pdf_path.name}`.
- **New helper (recommended):** In `fs.py`, add e.g. `write_tmp_meta(tmp_json_path: Path, source_pdf_path: Path) -> None` that writes `tmp_json_path.with_name(tmp_json_path.stem + ".meta.json")` with the above payload, and optionally `read_tmp_meta(tmp_json_path: Path) -> dict | None` that returns the parsed meta or `None` if missing/invalid. This keeps CLI thin and testable.

### 3.2 Exclude `.meta.json` from recovery candidates

- **Where:** `fs.list_tmp_jsons` in `src/pdf2ofx/helpers/fs.py` (lines 56–77).
- **Change:** Skip files whose name ends with `.meta.json` (e.g. `if p.name.endswith(".meta.json"): continue`). Otherwise `tmp/<hash>.meta.json` would be listed as a candidate (same `.json` suffix).

### 3.3 Recovery: load meta and pass `source_path` into sanity

- **Where:**  
  - When building `RecoveryCandidate` (loop starting at line 577 in `cli.py`): for each `path` (tmp JSON), try to load meta from `path.with_name(path.stem + ".meta.json")` (or use `read_tmp_meta(path)`). Set `source_path: Path | None` to `Path(meta["source_pdf_path"])` if meta exists and the path is valid, else `None`.  
  - Extend `RecoveryCandidate` with a field: `source_path: Path | None = None`.  
  - When calling `_run_sanity_stage` in recovery (line 656), pass `source_path=c.source_path` instead of `source_path=None`.
- **Legacy tmp:** If meta is missing or path does not exist, `source_path` stays `None` → "Open source PDF" is not shown (current behaviour). Optionally show a short note in the SANITY panel or in the recovery candidate label that source is unavailable when `source_path is None` in recovery (e.g. "source PDF unknown" in the label or a one-line message before the menu). No change to canonicalize/validate/fitid/emitter.

### 3.4 Auto-open PDF on "Edit balances" / "Edit transactions"

- **Where:** `_run_sanity_stage` in `cli.py`, immediately after the `action` branches that handle `"edit"` and `"edit_tx"`.
  - Right after `if action == "edit":` (line 399), before prompting for balances: if `source_path is not None and source_path.exists(): open_path_in_default_app(source_path)`.
  - Right after `if action == "edit_tx":` (line 428), before the submenu: same condition and call.
- Effect: In both normal and recovery mode, when the user chooses Edit balances or Edit transactions and a source path is available, the PDF opens automatically. No change to Mindee or to canonicalize/validate/fitid/emitter.

---

## 4) Minimal safe fix plan (no implementation until GO)

### 4.1 Persist provenance at extraction time

1. **`fs.py`**
   - Add `write_tmp_meta(tmp_json_path: Path, source_pdf_path: Path) -> None`: write `tmp/<stem>.meta.json` with `source_pdf_path` (resolved) and `source_name`.
   - Add `read_tmp_meta(tmp_json_path: Path) -> dict | None`: read and return the dict if file exists and is valid JSON with expected keys; otherwise return `None`.
   - In `list_tmp_jsons`, exclude files with `p.name.endswith(".meta.json")`.

2. **`cli.py` (normal flow)**
   - After a successful `_process_raw_pdf` (and after `write_json(tmp_json_path, raw)` is done inside it), call `write_tmp_meta(tmp_path, source)` so that every new tmp JSON gets a meta sidecar. Do not write meta in dev mode if you want to avoid cluttering tmp with dev-only artifacts, or write it anyway for consistency (recommended: write only when we have a real PDF path, i.e. not in dev_mode).

   **Precise call site:** In the main loop, right after `statement, per_warnings, raw_response = _process_raw_pdf(...)` (around line 854), add `write_tmp_meta(tmp_path, source)`. Do not add this in the `if dev_mode` branch (where `_process_dev_canonical` is used), so meta is only written for real PDF extraction.

### 4.2 Recovery: use meta as `source_path`

3. **`RecoveryCandidate`**
   - Add field `source_path: Path | None = None`.

4. **Recovery candidate construction**
   - When building each `RecoveryCandidate`, call `read_tmp_meta(path)`. If meta exists and `source_pdf_path` is present and the path exists, set `source_path = Path(meta["source_pdf_path"])`; else `source_path = None`. Pass `source_path` into the `RecoveryCandidate` constructor.

5. **Recovery SANITY call**
   - Replace `source_path=None` with `source_path=c.source_path` in the `_run_sanity_stage` call in the recovery loop.

6. **Optional UX for legacy tmp**
   - When in recovery and `source_path is None`, you can append to the candidate label something like " (no source PDF)" or show a single-line console message before the first SANITY menu for that candidate: "Source PDF unknown for this candidate (no meta)." No functional change to SANITY logic.

### 4.3 Auto-open on Edit balances / Edit transactions

7. **`_run_sanity_stage`**
   - In the `if action == "edit":` block, at the top (before balance prompts), add:
     - `if source_path is not None and source_path.exists(): open_path_in_default_app(source_path)`
   - In the `if action == "edit_tx":` block, at the top (before the "Edit transactions" submenu), add the same two lines.

### 4.4 What we do not change

- No changes to Mindee calls, `canonicalize_mindee`, `validate_statement`, `assign_fitids`, or OFX emission.
- No changes to the format of `tmp/<hash>.json` or to recovery `recover_*.raw.json` / `recover_*.canonical.json` content.
- No new burn of Mindee pages.

---

## 5) Tests to add

1. **`tests/test_fs.py`**
   - **`list_tmp_jsons`:** In a tmp dir containing `a.json`, `b.meta.json`, `c.raw.json`, `d.canonical.json`, and optionally a file under `tmp/recovery/`, assert that the returned list contains only `a.json` (exclude `*.meta.json`, `*.raw.json`, `*.canonical.json`, and recovery subdir).
   - **`write_tmp_meta` / `read_tmp_meta`:** Write meta for a path, read it back, assert `source_pdf_path` and `source_name`; assert `read_tmp_meta` returns `None` for missing or invalid file.

2. **Integration / CLI (if you have a way to run CLI steps without full PDF run)**
   - **Normal mode:** Run SANITY for one PDF and assert "Open source PDF" is present in the menu when not in dev mode; optionally assert that choosing "Edit balances" or "Edit transactions" triggers opening the PDF (e.g. mock or capture `open_path_in_default_app`).
   - **Recovery mode with meta:** Create a tmp JSON and a corresponding `tmp/<stem>.meta.json` pointing to an existing PDF; run recovery SANITY and assert "Open source PDF" is shown and that Edit balances / Edit transactions open the PDF.
   - **Recovery mode without meta:** Use a tmp JSON with no meta file; assert "Open source PDF" is not shown (and optionally that a "source unavailable" note appears).

3. **Unit-level for `_run_sanity_stage` (if feasible with mocks)**
   - With `source_path` set and existing, assert that "open" is in the choices and that on "edit" or "edit_tx" `open_path_in_default_app` is called with that path.

---

## 6) Summary

| Item | Location | Action |
|------|----------|--------|
| Show "Open source PDF" | `_run_sanity_stage` | Already conditional on `source_path`; no change. |
| Normal flow `source_path` | Call site ~906 | Already passes `source`; no change. |
| Recovery flow `source_path` | Call site ~664 | Pass `c.source_path` after adding meta + `RecoveryCandidate.source_path`. |
| Provenance storage | After `_process_raw_pdf` + new in `fs` | Add `write_tmp_meta`; call from CLI after extraction. |
| Provenance load | Recovery candidate build | Add `read_tmp_meta`; set `RecoveryCandidate.source_path`. |
| Exclude meta from list | `list_tmp_jsons` | Skip `*.meta.json`. |
| Auto-open on Edit | `_run_sanity_stage` "edit" / "edit_tx" | Call `open_path_in_default_app(source_path)` when path exists. |

No implementation beyond this plan until you say **GO**.
