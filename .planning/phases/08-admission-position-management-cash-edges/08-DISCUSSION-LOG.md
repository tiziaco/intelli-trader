# Phase 8: Admission, Position Management & Cash Edges - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-10
**Phase:** 8-Admission, Position Management & Cash Edges
**Areas discussed:** CASH-01 vs SIZE-03 overlap, CASH-02 release golden vehicle, CASH-02 terminal-state triggers, Leaf granularity / mapping

---

## CASH-01 vs SIZE-03 overlap

| Option | Description | Selected |
|--------|-------------|----------|
| Distinct trigger + ledger lens | Position-management trigger (scale-in 2nd entry exhausts cash) AND assert from the cash-ledger angle (RESERVATION never commits / available_cash intact); SIZE-03 used a single over-cash entry asserted via orders-snapshot REJECTED. Different bars, different lens, zero overlap. | ✓ |
| Same trigger, ledger lens only | Reuse a single over-cash entry like SIZE-03 but assert via the cash-operations ledger instead of the orders-snapshot. | |
| Pure cross-reference | Accept SIZE-03 covers it; CASH-01 is a documented cross-reference with no new leaf. | |

**User's choice:** Distinct trigger + ledger lens
**Notes:** Couples CASH-01 to ADMIT-01 scale-in (its trigger) and to the cash-ledger vehicle (next decision). User explicitly did not want CASH-01 to re-prove SIZE-03.

---

## CASH-02 release golden vehicle

| Option | Description | Selected |
|--------|-------------|----------|
| New opt-in cash-ledger snapshot | New opt-in golden serializing the CashOperation ledger (type/amount/reference_id/balance trail), mirroring the Phase 6 orders-snapshot opt-in pattern; shows actual reserve-then-release ops; reusable for CASH-01 (no commit) and CASH-02 (release per terminal state). | ✓ |
| Lightweight available_cash assertion | Assert available_cash / summary final_cash returns to pre-order value; no per-operation rows — can't distinguish never-reserved from reserved-then-released. | |
| Orders-snapshot + cash column | Extend the orders-snapshot with a reserved/released-cash column rather than a standalone ledger artifact. | |

**User's choice:** New opt-in cash-ledger snapshot
**Notes:** Determinism constraint captured for planner — exclude UUIDv7 operation_id / raw reference_id; assert on the stable trail (type, amount, balance_before/after, business-time) + a derived stable order correlation.

---

## CASH-02 terminal-state triggers

| Option | Description | Selected |
|--------|-------------|----------|
| Honest asymmetric coverage | CANCELLED + REFUSED prove POSITIVE release (reserve → terminal → RELEASE_RESERVATION op); REJECTED proves the NEGATIVE (fires at/before reserve, available_cash intact, no orphan). Faithful to engine semantics. | ✓ |
| Cover only CANCELLED + REFUSED | Restrict to the two states that genuinely hold-then-release; document REJECTED can't hold a reservation. | |
| Force a reserve-then-reject path | Construct an order that reserves then transitions to REJECTED for symmetry — no such path today; would need engine changes (violates behavior-preserving). | |

**User's choice:** Honest asymmetric coverage
**Notes:** Pre-question codebase check confirmed: REFUSED is provokable via a tiny `max_order_size` on `spec.exchange` (validate_order failure); CANCELLED reuses Phase 6 operator/cancel on a resting limit buy; REJECTED always fires at/before reserve() so it never holds a reservation.

---

## Leaf granularity / mapping

| Option | Description | Selected |
|--------|-------------|----------|
| Hybrid (~7 leaves) | Fold CASH-01 into the scale-in leaf (pyramid-until-cash-runs-out, Phase 7 D-11 two-outcome precedent); keep ADMIT-02 scale-out, ADMIT-03 max_positions, ADMIT-04 re-entry, and the 3 CASH-02 states as isolated leaves. | ✓ |
| Strict one-shape-per-leaf (~8 leaves) | Phase 6/7 default applied rigidly; CASH-01 gets its own leaf re-authoring near-identical scale-in bars. | |
| Aggressive folding (~4-5 leaves) | Also fold re-entry into scale-out and collapse CASH-02 into one 3-sequence leaf. Fewest artifacts, more to hand-verify per leaf, weaker isolation. | |

**User's choice:** Hybrid
**Notes:** 7 leaves — scale_in(+CASH-01), scale_out, max_positions, re_entry, cash/release_{cancelled,refused,rejected}. CASH-02 stays 3 isolated leaves so the honest-asymmetric coverage reads clearly.

---

## Claude's Discretion

- Emitter extension shape (D-06): thread `allow_increase` + `max_positions` as ScriptedEmitter constructor params (Phase 7 D-12 precedent); per-instance; defaults preserve existing leaves (`allow_increase=False`, `max_positions=1`).
- Exact cash-ledger snapshot column set / file name / opt-in point (subject to determinism-safe + orders-snapshot pattern).
- Exact contrived `bars.csv` per leaf; exact `tests/e2e/{admission,cash}/` sub-dir names/depth.
- Canary choice for the foundational plan; wave composition within the ADMISSION / CASH clusters.

## Deferred Ideas

- RNG-driven REFUSED (`simulate_failures`) — not used; deterministic `max_order_size` chosen instead.
- Multi-portfolio / contended cash reservation — Phase 9 (MULTI-03/MULTI-04).
- Explicit reserve-then-REJECTED engine path — rejected (no such path; would need engine changes).
- Per-bar `order_type` override in the emitter — carried from Phase 7 deferred; still unwired.
