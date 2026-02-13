# Reconciling large statements (unverifiable delta)

**Edge case:** When a statement has hundreds of transactions (e.g. 420+), the sanity panel shows a reconciliation error (e.g. Delta: 17,541.12 ✗) but there is **no practical way** for the operator to verify the delta by eye. Scrolling through an "Edit one transaction" list of 420 lines is not viable to find one wrong amount or missing line.

This doc suggests possible solutions for later. No code changes; read and pick a direction when you have time.

---

## 1. Export transactions for external verification

**Idea:** From the sanity step (or from a "Verify reconciliation" action), export the current transaction list to a file the operator can open elsewhere (Excel, Sheets, diff tool).

- **Format:** CSV or similar: date, amount, name/memo, running balance (optional).
- **Use:** Operator opens in a spreadsheet, sorts/filters, or compares against a bank export. Or they run a diff against a "correct" export from the bank.
- **Pros:** Uses tools people already know; no need to build a full reconciliation UI. Can be implemented as "Export to CSV" that writes `tmp/<stem>_transactions.csv` or into a chosen path.
- **Cons:** Manual step; operator leaves the CLI, does the check elsewhere, then comes back. Doesn’t directly "fix" the delta in the tool.

**Sketch:** Add a sanity menu option or a post-panel action: "Export transactions to CSV". Write `posted_at`, `amount`, `name`, `memo` (and optionally a computed running balance). Path could be `output/` or a dedicated `exports/` or user-chosen.

---

## 2. Running balance in the panel or export

**Idea:** Compute a **running balance** from start_balance + cumulative net movement up to each transaction. Then either show it in the sanity UI or in the export.

- **In export:** Add a column "running_balance". Operator can scan for the first row where running_balance diverges from what they expect (e.g. from the PDF).
- **In UI:** For large statements we don’t want to render 420 lines in the terminal. So running balance is more useful in the **export** (CSV) than in the sanity panel. Optionally, show a short "first N" and "last N" with running balance so they can at least see start/end consistency.
- **Pros:** Pinpoints where the error is (first transaction where running balance is wrong). Combines well with export.
- **Cons:** Requires knowing the "correct" running balance at some point (e.g. from the PDF) to compare. Still some manual work.

**Sketch:** In sanity or in a small helper: iterate transactions in order, maintain `running = start_balance + sum(amounts so far)`, attach to each row in the export. Optionally in the panel show "Running balance at first tx: X, at last tx: Y" and compare Y to ending_balance.

---

## 3. "Accept despite reconciliation error" (trust and proceed)

**Idea:** Make it explicit that for large statements the operator may **choose to accept** even when they cannot verify the delta.

- **Current behaviour:** Reconciliation ERROR already allows "Force accept?" (yes/no). So they can proceed. The issue is **psychological / UX**: it feels wrong to "force accept" when the delta is large and unverifiable.
- **Improvement:** Add a short line of copy when transaction count > N (e.g. > 100): e.g. "With this many transactions, manual verification of the delta is not practical. You can Accept to proceed or Export to verify elsewhere (see docs)." Or add a third option: "Accept (cannot verify — large statement)" that is the same as force-accept but framed for this case.
- **Pros:** No new features; just clearer wording and maybe a dedicated choice so they don’t feel they’re "hiding" an error.
- **Cons:** Doesn’t help them find or fix the cause of the delta; they’re still trusting or guessing.

**Sketch:** In the sanity panel or the "Force accept?" prompt, if `kept_count > 100` (or similar), add one line of text. Optionally add a menu entry "Accept (large statement — verify later via export)" that goes straight to accept after one confirmation.

---

## 4. Filter / subset by date or amount to narrow down

**Idea:** Help the operator **narrow down** where the delta might come from by focusing on a subset of transactions.

- **By date:** "Show only transactions between date X and Y" and show net movement for that window + running balance at start/end of window. If the delta is 17,541.12, they might try a date range that sums to around that and inspect those lines.
- **By amount:** "Show transactions with |amount| > N" or "Show transactions with amount in [−X, +X]". Large deltas often come from one or a few big amounts; listing only large amounts makes the list short.
- **Pros:** Shrinks the list to something reviewable. Can be combined with "Edit one transaction" on the filtered list (only allow editing among filtered) or with export of the subset.
- **Cons:** Requires UI to set filters (date range, amount threshold). More logic and prompts.

**Sketch:** Add "Narrow down" or "Filter transactions" from the sanity menu: prompt for date range and/or min |amount|, then show a table or export with only those rows (with running balance if possible). Operator uses that to find suspicious lines, then can use "Edit one transaction" if we keep the full list in memory and allow selecting by index.

---

## 5. Skip reconciliation check when transaction count > N

**Idea:** For very large statements, allow **skipping** the reconciliation check entirely (no delta, no ERROR from recon).

- **Behaviour:** If `kept_count > N` (e.g. 200), then in sanity we either (a) don’t compute/show reconciliation at all and treat as "SKIPPED", or (b) compute but show "Reconciliation not validated (large statement)" and do not set quality to POOR solely because of recon error.
- **Pros:** Avoids blocking the operator with an unverifiable ERROR. They can still export and verify offline.
- **Cons:** They might ship an OFX that’s wrong and only notice later. So this is a conscious "I’ll verify elsewhere" choice, not a silent skip. Best combined with a clear prompt: "This statement has N transactions; reconciliation check is skipped. You can export transactions to verify offline."

**Sketch:** In `compute_sanity` or in the sanity panel, if `len(transactions) > 200`: set reconciliation_status to "SKIPPED" and add a warning "Large statement — reconciliation not run; export transactions to verify if needed." Alternatively add a sanity menu option "Skip reconciliation (large statement)" that sets skipped and continues.

---

## 6. Diff against a "correct" list (advanced)

**Idea:** Let the operator provide a reference (e.g. CSV from the bank) and **diff** our transaction list against it (by date + amount, or by some key). Report missing/extra lines and suggested fixes.

- **Pros:** Directly finds discrepancies. Could drive "Edit one transaction" or suggest removals/edits.
- **Cons:** Requires a well-defined format for the reference; banks differ. Likely a separate, optional feature and more design work.

**Sketch:** Out of scope for a first cut; mention as a possible future direction.

---

## Recommendation (for tomorrow)

- **Short term:** Combine **1 (export)** with **2 (running balance in export)**. Add "Export transactions (CSV with running balance)" from the sanity menu or after the panel. Operator can open the CSV, sort by date, and scan the running balance column to find the first divergence. No change to force-accept flow; just a better way to verify when they want to.
- **UX tweak:** **3** — when transaction count is high and recon is ERROR, show one line: "Too many transactions to verify by eye. You can Accept to proceed and/or export transactions to verify offline."
- **Optional later:** **4** (filter by date/amount) if you find yourself often needing to narrow down; **5** (skip recon for large N) only if you’re comfortable treating large statements as "verify elsewhere" by default.

No code in this repo was modified; this is a design note for when you have time.
