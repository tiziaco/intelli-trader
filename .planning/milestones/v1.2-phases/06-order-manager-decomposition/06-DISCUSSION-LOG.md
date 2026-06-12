# Phase 6: Order-Manager Decomposition - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-11
**Phase:** 6-Order-Manager Decomposition
**Areas discussed:** Ambiguous-method placement, Shared _pending_brackets ownership, OrderManager residual role + collaborator shape, Decomposition + verification sequencing, Collaborator naming + folder layout, Opportunistic-cleanup policy, Test organization, BracketBook coverage

---

## Ambiguous-method placement — modify_order / cancel_order

| Option | Description | Selected |
|--------|-------------|----------|
| New lifecycle/ collaborator (4th bucket) | Add order_handler/lifecycle/lifecycle_manager.py; OrderManager becomes thin facade; extends the locked 3-bucket set; pulls FRAGILE WR-03/WR-04 into the new module | ✓ |
| Keep on OrderManager facade | OrderManager retains modify/cancel; only admission/brackets/reconcile extracted; literal 3-bucket criterion | |

**User's choice:** New lifecycle/ bucket (conditional on a clean _pending_brackets owner).
**Notes:** User asked for concrete examples of the facade vs lifecycle/ options, then asked which is architecturally cleanest. Recommendation accepted: the order domain is verb/pipeline-shaped, so lifecycle/ sits naturally beside admission/reconcile; mirror-portfolio_handler is about layout, not which methods Portfolio retained. Recorded as an intentional, documented extension of criterion 1.

## Ambiguous-method placement — read/query delegators

| Option | Description | Selected |
|--------|-------------|----------|
| Keep on OrderManager facade | 7 pass-throughs stay on the manager (D-18 read interface); OrderHandler.get_X delegates to it; no 5th folder | ✓ |
| New queries/ collaborator | Extract reads into order_handler/queries/ for symmetry | |

**User's choice:** Keep on OrderManager.
**Notes:** User asked whether keeping reads on OrderManager makes OrderHandler redundant. Clarified the two-layer distinction: OrderHandler = queue boundary (only queue-aware layer, on_signal/on_fill, emits OrderEvents); OrderManager = no-queue business-logic coordinator. OrderHandler stays essential. _estimate_commission→admission/, _PendingBracket→brackets/, both signal entries→admission/ recorded as settled (not contested).

## Shared _pending_brackets ownership

| Option | Description | Selected |
|--------|-------------|----------|
| Coordinator-owned star | OrderManager owns one BracketBook, injects into brackets/reconcile/lifecycle; no sibling state edges | ✓ |
| Brackets-owned hub | brackets/ owns it; reconcile/lifecycle hold a ref to the brackets collaborator | |

**Encapsulation sub-decision:** Thin BracketBook class (named arm/get/consume/refresh_quantity, 1:1 over current dict ops) ✓ — over relocating the raw dict.
**User's choice:** Coordinator-owned star + thin BracketBook class.
**Notes:** Accepted both recommendations directly.

## OrderManager residual role + pipeline split

| Option | Description | Selected |
|--------|-------------|----------|
| Full Option B — entry-points move intact + stateless helpers | process_signal→admission/, on_fill→reconcile/ relocated intact (FRAGILE on_fill never bisected); cross-stage via injected BracketBook + pure helpers; no sibling-class edges | ✓ |
| Coordinator orchestrates (pure star) | process_signal/on_fill orchestration stays on OrderManager; splits the FRAGILE on_fill try/finally from its body | |
| Hybrid — orchestrate process_signal, on_fill intact | Lowest coupling on signal path but asymmetric | |

**DI sub-decision:** Constructor injection — collaborators hold dep refs (mirror portfolio managers) ✓.
**User's choice:** Full Option B + constructor injection.
**Notes:** User asked (a) whether to rename process_signal→on_signal for consistency, and (b) whether to refactor on_fill instead of preserving the fragile behavior. Both redirected: the rename violates the criterion-3 isolation rule (deferred to a future naming touch — and the consistent target is itself an open question); the on_fill refactor is a behavior change forbidden in behavior-preserving v1.2 (deferred to 999.5 with re-baseline + cross-validation). Reframed Option B's intact move as the *enabler* of the future refactor, not a compromise. "Fragile" = delicate-to-change (a working T-05-17 fix), not broken.

## Decomposition + verification sequencing

| Option | Description | Selected |
|--------|-------------|----------|
| Incremental, golden-gated, reconcile last | BracketBook in-place → brackets → admission → lifecycle → reconcile; golden re-run gates each step | ✓ |
| Atomic single code-motion | One move, gate once at the end | |

**Verification-depth sub-decision:** Full milestone gate per step (+ determinism double-run at reconcile) ✓ — over light-per-step/full-at-end.
**User's choice:** Incremental + full gate per step.
**Notes:** Accepted both recommendations directly.

## Collaborator naming + folder layout

| Option | Description | Selected |
|--------|-------------|----------|
| Mirror portfolio_handler exactly | Subfolder-per-collaborator + __init__ re-export; unprefixed AdmissionManager/BracketManager/ReconcileManager/LifecycleManager + BracketBook + levels.py; collaborators internal | ✓ |
| Order-prefixed class names | OrderAdmissionManager, etc. | |

**User's choice:** Mirror portfolio_handler exactly.
**Notes:** Confirmed against portfolio_handler/__init__.py (exports only PortfolioHandler/Portfolio; managers internal) and cash/__init__.py re-export pattern.

## Opportunistic-cleanup policy

| Option | Description | Selected |
|--------|-------------|----------|
| Strictly zero + spot-and-log | Pure code-motion; new opportunities appended to 999.5 backlog, not fixed inline | ✓ |
| Allow touched-path cleanup | Permit CLEANUP-STANDARD.md tidying during the move | |

**User's choice:** Strictly zero + spot-and-log.
**Notes:** User initially leaned toward allowing cleanup and asked whether there were many opportunities. Investigated: no TODO/FIXME markers; safe order_manager.py cleanup already done in Phases 2-5; remainder is FRAGILE/contract work booked for 999.5 (W2-02 action→Side sits in the bracket/reconcile path — the exact trap). Evidence shifted the choice to strictly-zero, with spot-and-log to still capture any genuine new finding.

## Test organization + BracketBook coverage

| Option | Description | Selected |
|--------|-------------|----------|
| Keep facade-level tests as-is + lean BracketBook test | Existing tests prove behavior through public methods; one focused BracketBook unit test for the new primitive | ✓ |
| Add per-collaborator test files | test_admission/test_brackets/test_reconcile/test_lifecycle importing internal classes | |

**User's choice:** Keep facade-level tests as-is + lean BracketBook test.
**Notes:** User asked why per-collaborator tests couple to internal structure. Explained: they must import/instantiate the internal collaborator classes, binding tests to the decomposition boundaries — re-introducing the internals-coupling Phase 5/NAME-04 removed, and breaking under the deferred 999.5 reconcile refactor despite unchanged behavior. Facade tests bind to the public contract and survive reorg. BracketBook is the principled exception — a genuinely-new self-contained primitive with a stable invariant.

---

## Claude's Discretion

- Exact wave/plan decomposition within the D-10 extraction order (likely one plan per step).
- Exact BracketBook method + levels.py helper signatures (1:1 behavior-equal to current ops).
- Per-method subset of deps injected into each collaborator.
- Whether `_build_primary_order` lands in admission/ or brackets/.
- Module-docstring wording (must cite load-bearing tags: D-13, WR-03/04, T-05-17, T-07-15, RESEARCH Pattern 5).

## Deferred Ideas

- Refactor/streamline `on_fill` reconciliation + `should_release` flow → milestone 999.5 (behavior change; needs oracle re-baseline + cross-validation).
- Rename manager-layer `process_signal` for on_fill symmetry → future naming touch (isolation rule forbids ride-along; consistent target is its own open question).
- 999.5-booked order_manager.py items spotted during scout (do NOT fix here): W2-02 action→Side, W1-11 double get_position, W4-09 create_order path, SYN-05 OrderConfig/market_execution enum.
