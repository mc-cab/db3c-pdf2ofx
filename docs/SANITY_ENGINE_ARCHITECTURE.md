# SANITY Engine — Conceptual Architecture

This document describes the **logical architecture** of the SANITY engine: its layers, data flow, and relationship to RECOVERY. It deliberately ignores CLI implementation details (menus, prompts, Rich panels) and focuses on concepts, extension points, and bottlenecks.

---

## 1. Role in the Pipeline

SANITY sits between **VALIDATE** and **EMIT**:

```
… → VALIDATE → SANITY → EMIT → WRITE
```

**Input to SANITY:** A validated canonical statement (plus optional raw Mindee response, validation issues, and extracted transaction count).

**Output:** A confirmation result (accept/skip/forced-accept) and, when the operator edits, a possibly mutated statement. SANITY does not emit OFX; it only decides whether the statement is approved for emission and may modify it.

---

## 2. SANITY vs RECOVERY

| Aspect | SANITY | RECOVERY |
|--------|--------|----------|
| **Role** | Logical engine: diagnose, decide, strategize, mutate, confirm. | **Transport**: how statement + raw data are *delivered to* SANITY and how the *result* is persisted or passed downstream. |
| **Input** | Validated statement + optional raw + validation issues. | Same logical input, but **sourced from** `tmp/*.json` (no Mindee call). |
| **Output** | SanityResult + possibly mutated statement. | Writes `tmp/recovery/*.canonical.json` and later drives OFX conversion from that file. |
| **Invariant** | SANITY is **transport-agnostic**. It does not know whether it was invoked from the main PDF pipeline or from Recovery. | RECOVERY reuses the same SANITY engine; it only changes *where* the statement comes from and *where* the mutated statement is written. |

**Summary:** RECOVERY is a **transport layer**. It discovers candidates, normalizes/validates them, feeds them into SANITY, then persists the result and runs conversion. SANITY is the same in both flows.

---

## 3. Logical Layers

The SANITY engine can be described as four logical layers. Data flows through them in a loop until the operator accepts or skips.

### 3.1 Diagnostic Layer

**Purpose:** Produce a read-only, structured view of the statement’s health and reconciliation state.

**Responsibilities:**

- **Statement-level metrics:** Period, extracted/kept/dropped transaction counts, total credits/debits, net movement.
- **Balance resolution:** Starting and ending balance from (a) raw Mindee response (best-effort key scan) or (b) explicit override (e.g. operator entry). No mutation of the statement.
- **Reconciliation:** Compute `reconciled_end = starting_balance + net_movement`, `delta = reconciled_end - ending_balance`; classify as OK / WARNING / ERROR / SKIPPED.
- **Quality score:** Base 100, deductions for reconciliation ERROR, missing balances, high drop rate, validation warnings, low Mindee confidence (if available); label GOOD / DEGRADED / POOR.

**Output:** A single **SanityResult** (and its presentation, e.g. a summary panel — presentation is a consumer of this layer, not part of the “diagnostic” logic itself).

**Current mapping:**

| Feature | Location (logical) |
|---------|--------------------|
| Balance extraction from raw | `extract_balances`, `_get_prediction`, `_extract_decimal_field` |
| Reconciliation math + status | `compute_reconciliation` |
| Quality score + label + deductions | `compute_quality_score` |
| Full diagnostic run | `compute_sanity` → `SanityResult` |
| Panel rendering | Consumer of `SanityResult` (display only) |

**Invariant:** The diagnostic layer **never mutates** the canonical statement. It may take optional overrides (e.g. starting/ending balance) as parameters.

---

### 3.2 Decision Layer

**Purpose:** Capture the operator’s choice at each step — what to do next.

**Responsibilities:**

- **L1 (top):** Accept / Edit / Skip reconciliation; optionally Preview source file; in recovery, Back to list.
- **L2 (Edit):** Edit balances / Edit transactions / Transaction triage / Invert sign(s) / Back.
- **L2a:** Enter starting & ending balance or Back.
- **L2b:** Remove some transactions / Edit one transaction / Back.
- **L3:** Select which transaction to edit or Back.
- **L4:** Edit fields / Invert sign / Back.
- **Triage sub:** Validate transactions vs Flag transactions (which set of indices to mark).
- **Accept with ERROR:** Force accept yes/no.

**Current mapping:** All of these are “decision points”: the set of choices and the selected action. No persistent state beyond “what was chosen.” The implementation uses prompts; conceptually the layer is “decision events.”

---

### 3.3 Strategy Layer

**Purpose:** Interpret the current diagnostic result and the last decision to determine *which* options are available and *how* to apply the next step (e.g. which transactions are in scope).

**Responsibilities:**

- **Reconciliation status:** If status is ERROR, “Accept” requires an extra “Force accept?” step (strategy rule).
- **Triage filter:** Maintain which indices are “validated” vs “flagged”; use this to filter which transactions are shown for “Edit one” and “Invert sign(s)” (e.g. “only flagged” or “only not validated”).
- **Constraints:** e.g. “Remove some” must leave at least one transaction; “Edit one” only shows transactions that match the current triage filter.
- **Return targets:** After a mutation, return to a defined screen (e.g. after edit one tx → back to tx list L2b, not L1) so that the loop is consistent.

**Current mapping:**

| Feature | Strategy behavior |
|---------|-------------------|
| Force accept on ERROR | Accept → if reconciliation_status == ERROR → prompt force; else return result. |
| Triage state | `valid` / `flagged` sets; “Edit transactions” and “Invert batch” filter by these. |
| “At least one tx remains” | Reject remove-all. |
| Back / return-after-edit | Defined per action (e.g. after L4 edit → L3). |

Strategy uses **Diagnostic output** (e.g. `reconciliation_status`) and **Decision** (e.g. “Edit one”) to drive what the **Mutation** layer is allowed to do and what the next Decision context is.

---

### 3.4 Mutation Layer

**Purpose:** Apply concrete changes to the canonical statement (or to inputs that affect the next diagnostic run).

**Responsibilities:**

- **Balance override:** Provide starting/ending balance for the *next* diagnostic run only. In the current design this is passed as parameters into `compute_sanity`; it is **ephemeral** unless some other component persists it (e.g. recovery could write it into a sidecar or into the statement if the schema allowed).
- **Remove transactions:** Replace `statement["transactions"]` with a list that omits selected indices.
- **Edit one transaction:** Update `posted_at`, `amount`, `trntype`, `name`, `memo` (and optionally `debit`/`credit`) for one transaction.
- **Invert sign (single or batch):** Negate `amount`, swap `trntype` CREDIT/DEBIT, swap `debit`/`credit` for selected transaction(s).

**Current mapping:**

| Mutation | Effect |
|----------|--------|
| Edit balances (L2a) | No change to statement; next `compute_sanity` is called with `starting_balance` / `ending_balance` overrides. |
| Remove some | `statement["transactions"] = [t for i, t in enumerate(…) if i not in to_remove_set]`. |
| Edit one (date, amount, name, memo) | In-place update of one `tx` in `statement["transactions"]`. |
| Invert sign (one or batch) | In-place `_invert_tx_sign(tx)` on selected transaction(s). |
| Triage (validate/flag) | Updates in-memory triage sets only; **does not mutate** the statement. It only changes which transactions are in scope for Edit/Invert. |

**Invariant:** Only the canonical statement (and optional balance overrides for the next run) are mutated. The diagnostic layer remains pure relative to the statement.

---

## 4. Feature-to-Layer Map (Summary)

| Feature | Primary layer | Notes |
|---------|----------------|-------|
| Statement stats (counts, totals, net) | Diagnostic | |
| Balance extraction from raw | Diagnostic | |
| Reconciliation (reconciled_end, delta, status) | Diagnostic | |
| Quality score & label | Diagnostic | |
| SanityResult / panel | Diagnostic (output) + presentation | |
| Accept / Edit / Skip / Preview / Back to list | Decision | |
| Edit balances / Edit tx / Triage / Invert batch / Back | Decision | |
| Force accept on ERROR | Strategy | |
| Triage filter (valid/flagged) | Strategy | |
| “At least one tx remains” | Strategy | |
| Return-after-edit targets | Strategy | |
| Balance override for next run | Mutation (input to Diagnostic) | Ephemeral unless persisted elsewhere. |
| Remove transactions | Mutation | |
| Edit one tx (fields) | Mutation | |
| Invert sign (one or batch) | Mutation | |
| Triage state (valid/flagged sets) | Strategy (state), not Mutation | Does not change statement. |

---

## 5. Feedback Loop (Diagram)

The engine runs in a loop until the operator chooses Accept or Skip. Each mutation (or balance override) is followed by a fresh diagnostic run and display.

```
                    ┌─────────────────────────────────────────────────────────┐
                    │                     SANITY Engine                        │
                    │                                                          │
   ┌───────────────►│  ┌─────────────┐                                        │
   │  Validated     │  │ Diagnostic  │  SanityResult (stats, reconciliation,  │
   │  statement +   │  │   Layer     │  quality score)                         │
   │  raw + issues  │  └──────┬──────┘                                        │
   │                │         │                                                │
   │                │         ▼                                                │
   │                │  ┌─────────────┐  "Accept / Edit / Skip / …"            │
   │                │  │  Decision   │◄─────────── Operator choice            │
   │                │  │   Layer     │                                        │
   │                │  └──────┬──────┘                                        │
   │                │         │                                                │
   │                │         ▼                                                │
   │                │  ┌─────────────┐  Filter by triage; force-accept rule;   │
   │                │  │  Strategy   │  return target                          │
   │                │  │   Layer     │                                         │
   │                │  └──────┬──────┘                                         │
   │                │         │                                                 │
   │                │         ▼                                                 │
   │                │  ┌─────────────┐  Balance override; remove tx;           │
   │                │  │  Mutation   │  edit one tx; invert sign(s)             │
   │                │  │   Layer     │                                          │
   │                │  └──────┬──────┘                                          │
   │                │         │                                                  │
   │                │         │  (mutated statement or overrides)               │
   │                │         └──────────────────┐                              │
   │                │                             │                             │
   │                │                             ▼                             │
   │                │                    Re-run Diagnostic (compute_sanity)      │
   │                │                    then show result  ─────────────────────┤
   │                │                                                          │
   └────────────────┤  Accept → return result (+ statement if mutated)       │
                     │  Skip   → return result (skipped)                        │
                     └─────────────────────────────────────────────────────────┘
```

**In words:**

1. **Diagnostic** runs on the current statement (and optional balance overrides) → produces **SanityResult**.
2. Result is displayed; **Decision** layer gets operator choice (Accept / Edit / … / Skip).
3. **Strategy** interprets choice and context (triage, ERROR, etc.) and determines allowed actions and return target.
4. **Mutation** applies the chosen change (or none for Accept/Skip).
5. If a mutation (or balance override) was applied, loop to step 1 with the updated statement/overrides; otherwise (Accept or Skip) exit and return the final **SanityResult** (and the possibly mutated statement to the caller).

---

## 6. Extension Points

- **Diagnostic**
  - New balance sources (e.g. other OCR keys, or persisted operator balance in a sidecar).
  - Additional quality deductions or new signals (e.g. duplicate detection, date-range checks).
  - Pluggable “health rules” that append to `SanityResult` (warnings, deductions) without changing core reconciliation.
- **Decision**
  - New top-level or sub-menu choices (e.g. “Export summary”, “Compare with previous run”) without changing Diagnostic/Strategy/Mutation contracts.
  - Different UIs (e.g. headless/API) that still emit the same decision events.
- **Strategy**
  - New triage categories or filters.
  - Configurable thresholds (e.g. reconciliation ERROR threshold, quality bands).
  - Policies for “return after mutation” (e.g. always L2 vs L1).
- **Mutation**
  - New mutation types (e.g. “merge two transactions”, “split transaction”) as long as they produce a valid canonical statement for the next Diagnostic run.
  - Persisting balance overrides (e.g. into statement or sidecar) so they survive across runs or recovery.

---

## 7. Potential Bottlenecks

| Area | Risk | Mitigation idea |
|------|------|------------------|
| **Diagnostic** | Large statements (many transactions): single-threaded sum over all tx, repeated after every mutation. | Optional incremental stats or sampling for display; full recompute only on Accept. |
| **Strategy** | Triage state and filter logic live in one place; adding many strategies can become hard to reason about. | Explicit strategy registry or small state machine; keep “which tx are in scope” as a single derived value. |
| **Mutation** | In-place mutation of the statement: any bug can corrupt the only copy. | Consider immutable updates (copy-on-write) for critical paths, or a single “apply patch” function used by all mutations. |
| **Loop** | After every mutation, full diagnostic + display; for many small edits, many recomputes. | Batch multiple edits before recompute, or debounce recompute (with clear “dirty” semantics). |
| **Recovery** | Reloading `.canonical.json` from disk after each SANITY run to persist mutations; I/O and consistency. | Clear contract: Recovery writes canonical only on Accept/Skip (or on explicit “Save”); in-memory statement is source of truth during the loop. |

---

## 8. Document Metadata

- **Scope:** Conceptual architecture of the SANITY engine; CLI-agnostic.
- **Audience:** Maintainers, designers, and anyone extending SANITY or RECOVERY.
- **Related:** `docs/SPEC_SANITY_LAYER_v0.1.md`, `RUNBOOK_MAINTAINER.md` (Sanity & Reconciliation, Recovery Mode), `docs/v0.1.1/SPEC.md` (Recovery behavior).
