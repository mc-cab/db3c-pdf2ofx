# TODO

High-level backlog and ideas. Not ordered by priority unless stated.

---

## Progress indicator during batch

- **Need:** A progress indicator so the operator can see how many files have been sanity-checked and how many are left.
- **Basis:** Use the input folder file count: e.g. "Sanity 2/5" or "2 of 5 files" so it’s clear how far through the batch we are.
- **Place:** Likely in the sanity panel header or just above/below it (e.g. "File 2 of 5" when showing the sanity panel for the second PDF). Requires passing current index and total count into the sanity UI.

---

## Inbox / outbox workflow (inbox → input → process → outbox)

**Context:** First real use of the tool showed a recurring pattern:

- An **input** folder is created, with a **subfolder per sender** (person who sent the PDFs to convert), then **subfolders per client** (whose bank statements they are).
- An **output** folder is created that mirrors that structure.
- The idea is to support this flow in a clearer, safer way.

**Conceptual behaviour (to be refined and planned before implementation):**

1. **Before the process starts** (before any PDFs are sent to Mindee):
   - If an **inbox** folder exists and has non-empty nested folders:
     - Ask the operator to **select which sender** to process (e.g. list of inbox subfolders).
     - Then **list that sender’s subfolders** (e.g. clients) and ask to **pick one**.
     - Show the **list of files** in that subfolder; operator can **select with checkboxes** or **select all**.
     - **Copy** (do not move) the selected PDFs into the **input** folder so originals are never lost by accident.
   - Then the **existing process** runs as today (Mindee, sanity, OFX write from `input/` → `output/`).

2. **After OFX are generated** (in `output/`):
   - Ask the operator whether they want to **store them in outbox**.
   - If the **outbox** structure mirrors the inbox choices (e.g. same sender/client layout):
     - **Store automatically** in the matching outbox path.
   - Otherwise:
     - Ask the operator to **pick sender** and **subfolder** in outbox, then **move** (or copy) the OFX from output to that location.

3. **Inbox side (source PDFs):**
   - In the **inbox**, under the directory where the selected source PDFs lived, create a subfolder (e.g. at the root of that selected path) and store the **processed** PDFs there.
   - Organise with **date + run id**: e.g. `processed/YYYY-MM-DD/<runid>/` so each run is identifiable. (Run ID is new and would need to be defined and implemented.)

**Important:** This is highly UX-sensitive. It requires a proper reflection and a written plan (e.g. flows, edge cases, folder layout, run ID format) before any implementation. Do not start coding until the design is agreed and documented.

---

## References

- Batch failure modes and wasted Mindee credits: [docs/BATCH_FAILURE_POINTS.md](docs/BATCH_FAILURE_POINTS.md).
- Performance (time between sanity checks, Mindee vs our code): [docs/PERFORMANCE_AUDIT.md](docs/PERFORMANCE_AUDIT.md).
