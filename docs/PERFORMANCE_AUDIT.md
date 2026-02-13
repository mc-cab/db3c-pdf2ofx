# Performance audit: time between sanity checks

**Scope:** Where does time go between the user hitting **Accept** on one PDF’s sanity check and the **next** PDF’s response returning from the Mindee API? Goal: determine whether the bottleneck is Mindee or our code.

**No code was changed.** This is an analysis only.

---

## 1. Flow after “Accept” (PDF N)

When the user chooses **Accept** in the sanity menu:

1. **`_run_sanity_stage`** returns the `SanityResult` to `main()` ([cli.py](src/pdf2ofx/cli.py) ~639–651).
2. **In `main()`:**  
   `sanity_results.append(sanity_result)`  
   then (if no dev_simulate_failure):  
   `statements.append(ProcessItem(...))`,  
   `result_index[source.stem] = len(results)`,  
   `results.append(PdfResult(...))`.  
   No I/O, no network, no heavy work.
3. The **for** loop advances to the **next** `(index, source)` (PDF N+1).
4. **Top of the next iteration:**  
   `tmp_path = tmp_json_path(...)`,  
   `stem_to_tmp_path[source.stem] = tmp_path`,  
   then immediately:  
   `statement, per_warnings, raw_response = _process_raw_pdf(source, api_key, model_id, tmp_path, settings)`.

So right after Accept we only do a few in-memory operations, then we call `_process_raw_pdf` for the **next** file.

---

## 2. What runs inside `_process_raw_pdf` (PDF N+1)

From [cli.py](src/pdf2ofx/cli.py) ~289–299:

```text
raw = infer_pdf(api_key, model_id, pdf_path)   # ① Mindee API (blocking)
write_json(tmp_json_path, raw)                 # ② Write JSON to disk
normalization = canonicalize_mindee(raw, ...)   # ③ In-memory normalization
return normalization.statement, ...
```

- **① `infer_pdf`** ([mindee_handler.py](src/pdf2ofx/handlers/mindee_handler.py)): builds client, reads PDF from path, calls `client.enqueue_and_get_inference(...)`. This is a **blocking HTTP request** to Mindee (upload + inference + response). Typically **several seconds** per document depending on size and API load.
- **② `write_json`**: one small synchronous write to `tmp/`. Usually **tens of milliseconds**.
- **③ `canonicalize_mindee`**: pure in-memory work on the response. **Milliseconds**.

So for PDF N+1, almost all of the time from “we entered the loop for N+1” until “we have `statement` for N+1” is **Mindee API**.

---

## 3. Timeline: Accept (PDF 1) → second file back from API (PDF 2)

| Moment | What happens |
|--------|-------------------------------|
| **T0** | User hits Accept (PDF 1). |
| **T1** | `_run_sanity_stage` returns; we append to `sanity_results`, `statements`, `results`. Loop moves to PDF 2. |
| **T2** | We call `_process_raw_pdf` for PDF 2. First line: `infer_pdf(...)` — **blocking Mindee call**. |
| **T3** | Mindee responds; `infer_pdf` returns. Then `write_json`, `canonicalize_mindee`, return. |

**“Time between Accept and the second file returning from the API”** = (T1→T2) + (T2→T3).

- **T1→T2:** Our code only. A few list/dict operations and the next loop iteration. **Negligible** (well under 100 ms).
- **T2→T3:** Dominated by **Mindee API** (upload + inference). Typically **seconds** per PDF. The rest (write_json + canonicalize) is small (tens of ms).

So **almost all of that delay is the Mindee API** for the second file, not our code.

---

## 4. Conclusion

- **Between “Accept” and “second file returns from API”:**  
  Our code adds only a tiny amount of time (loop + appends). The vast majority of the wait is the **Mindee API** call for the next PDF (`infer_pdf` in `_process_raw_pdf`).
- **If you wanted to measure it:**  
  Add two timestamps (no other code change): one when `_run_sanity_stage` returns (right after Accept), one when `infer_pdf` returns for the next PDF. The difference is “our code + Mindee”; a second pair (entry to `_process_raw_pdf` and return from `infer_pdf`) would isolate Mindee-only time. Expect ~99%+ of the first interval to be Mindee.

---

## 5. Other phases (for context)

- **After Mindee returns (PDF N):** We then do `transaction_line_numbers`, `_ensure_account_id` (maybe prompt), `assign_fitids`, `_collect_posted_at_fallbacks`, `validate_statement`, then `_run_sanity_stage` (compute_sanity + panel + user prompts). All of that is either in-memory or one small read; the only “slow” part is **user time** in the sanity menu. So for a single PDF, the only long machine-bound delay is the Mindee call; the rest is either fast or user-driven.
