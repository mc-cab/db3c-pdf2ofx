# pdf2ofx CLI — SANITY Stage UX Audit Report

**Tool:** pdf2ofx (Mindee → JSON → OFX)  
**Audience:** Accountant (low tolerance for confusing menus)  
**Scope:** SANITY stage navigation and operator ergonomics (Normal + Recovery). No code changes.

---

## Executive Verdict: **GO** — Refactor Necessary

The current SANITY flow uses a **single top-level loop**: every "← Back" and every post-action step returns to the **SANITY Level 1 menu** (Accept / Edit / Skip / …). That violates the operator’s mental model when they are deep in Edit → Edit transactions → Select tx → Per-tx action: they expect "Back" to mean **one level up** (e.g. back to transaction list to fix the next one). The result is repetitive re-navigation and high cognitive load during batch correction. A refactor to **hierarchical Back semantics** and **post-action return to the right level** is justified and should be implemented.

---

## A) Current-State UX Map (Normal + Recovery)

### Normal mode — Entry until SANITY

1. **Start** → "Start pdf2ofx?" → **Process PDFs** (or Recovery mode).
2. Preflight (API key, model).
3. For each PDF in `input/`: **Mindee** → normalize → validate → **SANITY** (one SANITY run per PDF; no batch SANITY).

So: **Entry to SANITY** = after validation for that PDF; one statement at a time.

### Recovery mode — Entry until SANITY

1. **Start** → "Start pdf2ofx?" → **Recovery mode**.
2. List `tmp/*.json` → **multi-select** (checkbox) → confirm.
3. For each selected: write `recover_<stem>.raw.json` + `recover_<stem>.canonical.json`; then **SANITY** for that candidate (same `_run_sanity_stage` with `recovery_mode=True`).
4. After SANITY for one candidate: either "Back to list" (exit SANITY, return to recovery list) or continue to next candidate; then "Confirm & proceed" or "Go back (re-run SANITY for modified)".

So: **Entry to SANITY** = from recovery candidate list, one candidate at a time; "Back to list" exits SANITY and returns to that list.

### SANITY loop — Screens (both modes)

All of the following live inside **one** `while True` in `_run_sanity_stage`. Every `continue` goes back to **Level 1**.

| Level | Screen | Options | What "Back" / action does |
|-------|--------|--------|---------------------------|
| **1** | Sanity check: | Accept, Edit, Skip reconciliation, [Preview source file], [Back to list] | Back to list (recovery only): exit SANITY (raise). Accept: return. Skip: return (skipped). Edit: go to Level 2. Preview: open PDF, then **Level 1**. |
| **2** | Edit: | Edit balances, Edit transactions, Transaction triage, ← Back | ← Back → **Level 1**. |
| **2a** | Edit balances: | ← Back (no change), Enter starting & ending balance | Back → **Level 1**. After balance edit: recompute sanity, render, → **Level 1**. |
| **2b** | Edit transactions: | ← Back, Remove some, Edit one transaction | Back → **Level 1**. Remove: checkbox → mutate → recompute → **Level 1**. Edit one → Level 3. |
| **2c** | Transaction triage: | Validate transactions, Flag transactions, ← Back | Back → **Level 1**. After triage (validate/flag): → **Level 1**. |
| **3** | Select transaction to edit: | ← Back, Tx1, Tx2, … | Back / cancel → **Level 1**. Select tx → Level 4. |
| **4** | Transaction: | Edit fields, Invert sign, ← Back | Back → **Level 1**. Invert sign → recompute → **Level 1**. Edit fields → prompts → recompute → **Level 1**. |

*(Quit (q) is available on every `_prompt_select` and aborts the run; not shown in table.)*

### Compact flow (pseudo-diagram)

```
NORMAL:
  [Start] → Process PDFs → per-PDF: Mindee → validate → SANITY ─────────────────────────────────┐
                                                                                                  │
RECOVERY:                                                                                         │
  [Start] → Recovery → tmp list (multi-select) → per-selected: SANITY ───────────────────────────┤
                                                                                                  │
SANITY (single while True):                                                                       ▼
  L1: Accept | Edit | Skip | [Preview] | [Back to list]  ←────────────────────────────────────────┐
       │         │      │       │            │                                                      │
       ▼         ▼      ▼       └─ open PDF ─┘            (Back to list → exit SANITY, recovery)   │
    return   ┌───┴───┐ return                                                                       │
             │  L2   │                                                                               │
             │ Edit: balances | transactions | triage | ← Back                                     │
             │   │         │           │           └─────────────────────────────────────────────────┘
             │   │         │           │   (triage Back → L1; after triage → L1)
             │   │         │           │
             │   ▼         ▼           ▼
             │  L2a      L2b        (checkbox + confirm → L1)
             │  balances  Edit tx: Remove | Edit one | ← Back
             │  Back/ok→L1   Back→L1    │         │
             │                          │         ▼
             │                          │      L3: Select tx (Back→L1)
             │                          │         ▼
             │                          │      L4: Edit fields | Invert sign | ← Back
             │                          │         (Back→L1; after edit/invert→L1)
             └─────────────────────────┴──────────────────────────────────────────────────────────┘
```

### Exact navigation outcomes (reference)

- **L1 Accept** → return from SANITY (success).
- **L1 Skip** → return from SANITY (skipped).
- **L1 Preview** → open PDF, **L1**.
- **L1 Back to list** (recovery only) → exit SANITY (RecoveryBackRequested).
- **L1 Edit** → L2.
- **L2 ← Back** → L1.
- **L2 Edit balances** → L2a; L2a ← Back → L1; L2a "Enter balances" + done → L1.
- **L2 Edit transactions** → L2b; L2b ← Back → L1; L2b Remove + done → L1; L2b Edit one → L3.
- **L2 Transaction triage** → submenu; ← Back → L1; Validate/Flag + confirm → L1.
- **L3 Select transaction** → ← Back → L1; choose tx → L4.
- **L4 Transaction** → ← Back → L1; Invert sign → L1; Edit fields → L1.

So: **every** Back and **every** post-mutation step from L2b/L2c/L4 goes to **L1**, not to the previous screen.

---

## B) Pain Points (Ranked)

### P0 — Critical

| # | Failure | Why it’s bad (mental model) | Frequency / impact | Where |
|---|--------|-----------------------------|--------------------|-------|
| 1 | **Back from per-tx action returns to SANITY top (L1)** | Operator thinks: "I fixed one tx, now I go back to the **list** to pick the next." Actual: back at Accept/Edit/Skip. Must choose Edit → Edit transactions again to see the list. | Every time operator fixes more than one transaction; batch correction becomes hell. | L4 (Transaction: Edit fields / Invert sign) → Back or after apply → L1 |
| 2 | **Back from "Select transaction" returns to L1** | Same: "Back" from picker should return to "Edit transactions" (L2b), not to top. | Same as above. | L3 (Select transaction) → Back → L1 |

### P1 — High

| # | Failure | Why it’s bad (mental model) | Frequency / impact | Where |
|---|--------|-----------------------------|--------------------|-------|
| 3 | **Back from triage returns to L1** | After Validate/Flag, operator expects Back to return to **Edit** (L2), not to Accept/Edit/Skip. | When operator uses triage then wants to edit balances or transactions. | L2c (Transaction triage) → Back → L1 |
| 4 | **After triage confirm → L1** | Same: after applying triage, staying in Edit (L2) would allow immediate "Edit transactions" with filter applied. | Same workflow. | L2c → confirm → L1 |
| 5 | **Back from "Edit transactions" (L2b) goes to L1** | Some operators may expect Back from L2b to return to L2 (Edit). Currently both L2 ← Back and L2b ← Back go to L1; at least L2b → Back could go to L2. | Medium; compounds with P0 when fixing many txs. | L2b → Back → L1 |

### P2 — Medium

| # | Failure | Why it’s bad (mental model) | Frequency / impact | Where |
|---|--------|-----------------------------|--------------------|-------|
| 6 | **No breadcrumbs / context title** | Operator can’t see "you are here" (e.g. "Edit → Transactions → Select transaction"). In long sessions, disorienting. | All deep flows. | All submenus |
| 7 | **Sanity panel re-rendered after every mutation** | Good for feedback but can be noisy; no "keep editing without re-render" option. | Lower; acceptable for v0. | After edit/invert/remove/triage |

---

## C) Target UX Principles + Decisions

### 1. Hierarchical navigation

- **Back = one level up** from current screen, not "always return to SANITY top."
- **Quit** remains "exit run" (current behavior).
- **Recovery:** "Back to list" remains "exit SANITY and return to recovery candidate list" (already correct).

### 2. After per-transaction edit / invert

- **Return to transaction list (L3 / "Select transaction")**, not to L2b and not to L1.
- **Justification:** Operator is in "fix N transactions" mode; after fixing one they should immediately see the list and pick the next without re-entering Edit → Edit transactions.

### 3. After triage operations

- **Back** from triage submenu → **Edit (L2)**.
- **After** Validate/Flag + confirm → **Edit (L2)** (so they can go to "Edit transactions" with filter applied, or Edit balances, or Back to L1).

### 4. When to recompute sanity and where to show the panel

- **Recommendation:** Recompute and show the sanity panel **after every mutation** (balance, remove tx, edit one tx, invert, triage). No "keep editing without re-render" for v0 to avoid state inconsistency.
- **Where:** After the mutation, show the panel **then** return to the **agreed return screen** (e.g. after per-tx edit → panel, then back to tx list). So: mutate → recompute → render panel → then navigate to the correct level (e.g. tx list), not always to L1.

### 5. Orientation (breadcrumbs, titles, labels)

- **Breadcrumbs:** e.g. `Sanity › Edit › Transactions` or short: `Edit › Transactions` so operator always knows depth.
- **Titles:** Use consistent prompt titles (e.g. "Edit transactions" when at tx list, "Select transaction" when picking one).
- **Labels:** Keep short; prefer "← Back" everywhere for Back; "Back to list" only in recovery for "exit SANITY."

---

## D) Recommended Target Flow ("Golden Path")

### Screen list in order (hierarchy)

1. **L1 — Sanity check**  
   Accept | Edit | Skip reconciliation | [Preview source file] | [Back to list]  
   - Back: N/A (only "Back to list" in recovery exits).  
   - Accept → return. Skip → return. Edit → L2. Preview → open PDF, stay L1.

2. **L2 — Edit**  
   Edit balances | Edit transactions | Transaction triage | ← Back  
   - ← Back → L1.  
   - Edit balances → L2a. Edit transactions → L2b. Transaction triage → L2c.

3. **L2a — Edit balances**  
   ← Back (no change) | Enter starting & ending balance  
   - ← Back → L2.  
   - After balance edit: recompute + show panel → **L2** (not L1).

4. **L2b — Edit transactions**  
   ← Back | Remove some transactions | Edit one transaction  
   - ← Back → L2.  
   - Remove: checkbox → mutate → recompute + panel → **L2b** (stay in list; operator can remove more or Back).  
   - Edit one → L3.

5. **L3 — Select transaction**  
   ← Back | Tx1 | Tx2 | …  
   - ← Back → L2b.  
   - Select tx → L4.

6. **L4 — Transaction (for selected tx)**  
   Edit fields | Invert sign | ← Back  
   - ← Back → L3.  
   - Invert sign: mutate → recompute + panel → **L3**.  
   - Edit fields: prompts → mutate → recompute + panel → **L3**.

7. **L2c — Transaction triage**  
   Validate transactions | Flag transactions | ← Back  
   - ← Back → L2.  
   - After Validate/Flag + confirm: → **L2** (not L1).

### Post-action return points (summary)

| Action | Return to |
|--------|-----------|
| L2 ← Back | L1 |
| L2a ← Back | L2 |
| L2a balance edit done | L2 |
| L2b ← Back | L2 |
| L2b Remove done | L2b |
| L2b Edit one → L4; L4 ← Back | L3 → L2b (Back from L4 → L3, Back from L3 → L2b) |
| L4 Invert sign / Edit fields done | L3 |
| L2c ← Back | L2 |
| L2c Validate/Flag done | L2 |

### Normal vs Recovery

- **Normal:** No "Back to list." Rest of flow identical.  
- **Recovery:** L1 has "Back to list" → exit SANITY (RecoveryBackRequested). All other Back/return rules as above.

---

## E) Implementation Guidance (No Code)

### Control-flow structure

- **Preferred:** **Explicit screen stack or state machine**, not one flat `while True` with many `continue` to the same top.
  - **Option A — Screen stack:** Push current "screen" (e.g. L1, L2, L2b, L3, L4); "Back" = pop and show previous; after mutation, recompute/render then push/switch to the **target** screen (e.g. after L4 edit → push L3).
  - **Option B — State machine:** States = L1, L2, L2a, L2b, L2c, L3, L4; transitions on choice + "return after action" rules; one main loop that dispatches to the right prompt and transition logic.
- **Alternative:** Nested loops (e.g. inner loop for L2b→L3→L4 with Back from L4→L3, L3→L2b, L2b Back→L2) and from L2 Back→L1. This can be done with less structural change but tends to duplicate "recompute + render + where to go" and is harder to keep consistent.

### Functions to refactor

- **`_run_sanity_stage`** in `cli.py`: holds the single `while True` and all L1–L4 logic. This is the only function that must be refactored for navigation; no changes to `compute_sanity`, `render_sanity_panel`, canonicalize/validate/FITID/emitter.

### v0 minimal fix (surgical)

- **Goal:** Fix P0 (and optionally P1) with minimal structural change.
- **Approach:** Introduce **one** inner loop for "Edit transactions" (L2b + L3 + L4):
  - From L1, on Edit → L2 as now.
  - From L2, on "Edit transactions" → enter **inner loop**: show L2b (Back → exit inner loop to L2). "Edit one" → L3 (Back → L2b). Select tx → L4 (Back → L3; after edit/invert → L3). From L3 Back → L2b. From L2b Back → exit inner loop to L2.
  - Triage: from L2, triage submenu; Back → L2; after confirm → L2 (requires branching so that after triage you don’t `continue` to L1 but re-show L2).
  - Edit balances: after balance edit, `continue` to L2 only (e.g. set a "return_to_L2" flag and break out of balance block to a point that shows L2, not L1).
- **Risk:** Some duplication of "show L2" vs "show L1"; easy to regress if more menus added later.

### v1 proper refactor (clean navigation)

- **Goal:** Hierarchical Back and consistent return points; easy to extend.
- **Approach:** Implement a small **screen stack** or **state enum** and a **single** dispatch loop, e.g.:
  - `current_screen = L1`; loop: `current_screen = dispatch(current_screen, choice)`; each handler returns the next screen (and optionally "recompute + render").
  - Back always means "pop stack" or "transition to parent state"; after mutation, transition to the defined return screen (e.g. L4 → L3, L2a → L2, L2c → L2).
- **Risks:** Larger diff; need to ensure every path sets next screen correctly. **Test strategy:** Add navigation tests (e.g. "from L4 Back goes to L3", "after invert sign we are at L3") and keep existing sanity logic tests.

### Risks and test strategy

- **Risks:**  
  - Changing `continue` targets can break flows that currently depend on "always L1" (e.g. dev or edge paths).  
  - Recovery mode: ensure "Back to list" still raises and is handled by recovery loop; no new persistence.
- **Existing tests:** Any test that assumes "after edit we see L1 menu" (e.g. prompt order or default choice) may break; need to update expectations to new return screen.
- **New tests (high-level):**  
  - Navigation: from each screen, Back goes to the specified parent; after per-tx edit/invert, next prompt is tx list (L3); after triage confirm, next prompt is L2.  
  - Recovery: "Back to list" still raises and returns to candidate list.  
  - No new persistence: triage still in-memory; no change to canonicalize/validate/FITID/emitter.

---

## Proposed Menu Strings (label → action)

| Label | Action |
|-------|--------|
| Accept | Accept sanity and return (proceed to next step). |
| Edit | Open Edit submenu (balances / transactions / triage). |
| Skip reconciliation | Mark statement skipped and return. |
| Preview source file | Open source PDF in default app (recovery: from meta). |
| Back to list | (Recovery only.) Exit SANITY and return to recovery candidate list. |
| ← Back | Go back one level (parent screen). |
| ← Back (no change) | (Edit balances.) Cancel balance edit and go back one level. |
| Edit balances | Enter balance edit submenu. |
| Edit transactions | Enter transaction list (remove / edit one). |
| Transaction triage | Validate or flag transactions (filter for Edit transactions). |
| Validate transactions | Checkbox: mark selected as validated. |
| Flag transactions | Checkbox: mark selected for edit (filter). |
| Remove some transactions | Checkbox: remove selected transactions. |
| Edit one transaction (date, amount, description) | Open transaction picker, then per-tx actions. |
| Edit fields | Edit date, amount, name, memo for selected tx. |
| Invert sign | Invert amount sign for selected tx. |
| Quit (q) | Abort run (UserAbort). |

---

## Punchlist: Decisions for Implementer Before Coding

1. **Adopt hierarchical Back (Back = one level up)** for L2, L2a, L2b, L2c, L3, L4. Confirm.
2. **After per-tx edit or invert sign:** return to **transaction list (L3)**, not L1 or L2. Confirm.
3. **After triage (Validate/Flag) confirm:** return to **Edit (L2)**. Confirm.
4. **After Edit balances done:** return to **L2**. Confirm.
5. **After Remove some transactions:** return to **L2b** (transaction list) so operator can remove more or Back. Confirm.
6. **Breadcrumbs / context title:** v0 = no breadcrumbs; v1 = add short context (e.g. "Edit › Transactions"). Confirm which scope.
7. **Recompute sanity:** after every mutation; show panel then navigate to the agreed return screen. Confirm no "skip re-render" in v0.
8. **Control flow:** v0 = nested loops (inner loop for L2b–L3–L4 + triage/balance return to L2); v1 = screen stack or state machine. Confirm choice.
9. **Recovery:** Keep "Back to list" as only way to exit SANITY to list; no other behavior change. Confirm.
10. **Tests:** Add navigation tests for Back and post-action return screens; update any test that assumed "always return to L1."

---

*End of report. No code changes by auditor.*
