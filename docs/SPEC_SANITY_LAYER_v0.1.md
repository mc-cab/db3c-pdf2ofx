---
doc_id: spec_sanity_layer_v0_1
title: pdf2ofx — Sanity & Reconciliation Layer
owner: Mathieu
scope: Add explicit sanity-check, reconciliation, and confidence UX layer before OFX emission
status: draft
doc_type: spec
version: 0.1
created: 2026-02-12
tags: [pdf2ofx, sanity, reconciliation, ux, validation]
---

# 1. Purpose

Introduce a deterministic **Sanity & Reconciliation Layer** between `VALIDATE` and `EMIT` to:

* Increase trust before importing OFX into Pennylane
* Reduce OCR risk exposure
* Surface extraction statistics clearly
* Provide operator confirmation for critical financial fields
* Quantify confidence in a transparent way

This layer does **not** change core business logic.
It adds structured checks + UI presentation.

---

# 2. Non-Goals

* No redesign of canonical schema
* No change to FITID algorithm
* No refactor of validator logic
* No dashboard UI
* No persistent database
* No CI enforcement
* No automation redesign

---

# 3. Pipeline Modification

Current:

```
PREFLIGHT → MINDEE → NORMALIZE → VALIDATE → EMIT → WRITE
```

New:

```
PREFLIGHT → MINDEE → NORMALIZE → VALIDATE → SANITY → EMIT → WRITE
```

The SANITY stage operates on validated statements.

---

# 4. Sanity Layer Responsibilities

## 4.1 Statement-Level Fields

For each PDF:

Extract or compute:

* Period start
* Period end
* Starting balance (if present in Mindee response)
* Ending balance (if present)
* Transaction count (extracted)
* Transaction count (kept after validation)
* Dropped count
* Total credits
* Total debits
* Net movement

---

## 4.2 Balance Reconciliation

If starting + ending balances are available (from OCR or operator):

Compute:

```
reconciled_end = starting_balance + net_movement
delta = reconciled_end - ending_balance
```

Threshold:

```
abs(delta) <= 0.01 → OK
0.01 < abs(delta) <= 1.00 → WARNING
abs(delta) > 1.00 → ERROR
```

If balances missing:

* Prompt operator for manual input (optional)
* If skipped → downgrade confidence score

---

## 4.3 Operator Confirmation Flow

For each PDF:

### Step 1 — Display Sanity Summary Panel

Show:

* Period
* Extracted / Kept / Dropped
* Credits / Debits / Net
* Starting balance
* Ending balance
* Reconciliation delta
* Quality score (see §6)

### Step 2 — Prompt

Options:

* Accept
* Edit sanity fields
* Skip reconciliation

If Edit:

* Prompt for starting balance
* Prompt for ending balance
* Recalculate delta
* Re-display summary
* Require explicit confirmation

If delta > threshold:

* Require explicit “Force accept”

---

# 5. UI Requirements (Rich-based)

Use structured panels with color:

* Green → OK
* Yellow → WARNING
* Red → ERROR

Sanity fields must be visually separated from transaction validation issues.

Minimal example layout:

```
──────────────── PDF: FirstCitizensBank.pdf ────────────────

Period:         2024-11-01 → 2024-11-30
Transactions:   Extracted 12 | Kept 11 | Dropped 1
Totals:         +416,000.00 | -80,000.00 | Net +336,000.00

Starting balance:  100,000.00
Ending balance:    436,000.00
Reconciled end:    436,000.00
Delta:             0.00   ✓

Quality: GOOD (92/100)
```

No walls of text.

---

# 6. Confidence / Quality Score

Base = 100

Subtract:

* -60 if reconciliation ERROR
* -25 if balances missing
* -15 if >10% transactions dropped
* -10 per WARNING bucket (cap 30)
* -15 if low Mindee confidence on core fields (if available)

Classification:

* 80–100 → GOOD
* 50–79 → DEGRADED
* <50 → POOR

Displayed per PDF and in final batch summary.

---

# 7. Mindee Confidence Usage

If V2 API exposes confidence:

Aggregate:

* Transaction list confidence
* Balance field confidence
* Period confidence

If confidence < “Certain”:

* Emit WARNING
* Affect quality score

Do not block execution.

---

# 8. Failure Modes Addressed

This layer mitigates:

* Wrong but parseable amounts
* OCR sign errors
* Missing transactions (visible via count mismatch)
* Date misinterpretation (visible via period)
* Silent reconciliation mismatches

It does not eliminate OCR risk, but makes it explicit.

---

# 9. Acceptance Criteria

The feature is complete when:

* Each PDF displays a structured sanity summary before emission
* Reconciliation delta is computed when possible
* Manual balance entry works
* Quality score reflects reconciliation state
* No change to transaction validation logic
* No change to OFX emission logic
* All existing tests pass
* New tests added for reconciliation computation

---

# 10. Risks

| Risk                   | Mitigation                                    |
| ---------------------- | --------------------------------------------- |
| Overcomplicating CLI   | Keep to single panel per PDF                  |
| Blocking workflows     | Allow skip with downgraded quality            |
| Breaking emission flow | SANITY must not mutate validated transactions |

---

# 11. Version
- v0.1 — Initial introduction of Sanity Layer