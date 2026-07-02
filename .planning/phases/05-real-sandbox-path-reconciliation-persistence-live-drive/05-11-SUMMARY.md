---
phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
plan: 11
subsystem: reconciliation
tags: [correlation-adopt, restart-rehydration, partial-fill, mutation-ordering, WR-02, WR-03, WR-05, RECON-05, RECON-02]

# Dependency graph
requires:
  - phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
    plan: 10
    provides: "CR-01 — LiveTradingSystem.start() spawns the live fill/order streams (connect()), making the WR-02 buffered-fill loss reachable in production"
  - phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
    plan: 07
    provides: "VenueReconciler.reconcile() + _relink_brackets — the startup two-sided reconcile this plan extends with the correlation-adopt step"
provides:
  - "WR-02 (RECON-05) closed: OkxExchange.adopt_venue_correlation(order) repopulates the three in-memory correlation maps + drains buffered fills for a rehydrated (pre-restart) order; VenueReconciler.reconcile() calls it for each working-set order carrying a venue_order_id — a post-restart fill now reaches the mirror instead of being silently buffered, and a cancel resolves"
  - "WR-03 (RECON-02) closed: reconcile_manager validates the PARTIALLY_FILLED transition BEFORE mutating filled_quantity — a rejected transition leaves the mirror literally unchanged"
  - "WR-05 recorded documented-only: _compare_symbol_drift's adopt-and-continue branch is an intentional dormant extension point (no code change)"
  - "2 regression tests that would have CAUGHT the gaps (rehydrated-fill-reaches-mirror; rejected-transition-leaves-filled-unchanged)"
affects: [reconciliation, live-fill-path, restart-rehydration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Correlation-adopt seam: adopt_venue_correlation mirrors _submit_order's map-write-under-lock + drain-outside-lock (Lock non-reentrant, _handle_trade re-acquires) — one write pattern, two entry points (submit vs restart-rehydration)"
    - "Validate-before-mutate: compute the prospective value into a local (new_filled), validate the transition, assign to the entity ONLY on success — so a rejected path is a literal no-op"

key-files:
  created:
    - .planning/phases/05-real-sandbox-path-reconciliation-persistence-live-drive/05-11-SUMMARY.md
  modified:
    - itrader/execution_handler/exchanges/okx.py
    - itrader/portfolio_handler/reconcile/venue_reconciler.py
    - itrader/trading_system/live_trading_system.py
    - itrader/order_handler/reconcile/reconcile_manager.py
    - tests/unit/execution/test_okx_fill_idempotency.py
    - tests/unit/order/test_partial_fill_terminalize.py

key-decisions:
  - "WR-02 adopt seam iterates the WORKING SET after _relink_brackets (not a separate re-fetch of legs): a resting bracket child is an active order returned by get_active_orders, so it is already in the working set, and _relink_brackets has just stamped its venue_order_id — one pass covers both plain working-set orders and re-linked legs. Guarded on self._exchange is not None so paper/backtest/test paths (None exchange) are a clean skip."
  - "adopt_venue_correlation with venue_order_id=None returns early (nothing to correlate) — a rehydrated order the venue never acknowledged has no map key to write; keeps the seam idempotent and crash-free."
  - "WR-03 reorder is behavior-identical on the success path (transition then assign, no early return between them) — only the REJECTED path changes: filled_quantity is no longer bumped before the validation rejects. total_filled in additional_data now reads the prospective new_filled (same value that was previously assigned first)."

requirements-completed: [RECON-05, RECON-02]

# Metrics
duration: ~15min
completed: 2026-07-02
---

# Phase 05 Plan 11: Gap-Closure — Correlation-Map Adoption + Partial-Fill Mutation Ordering Summary

**Added `OkxExchange.adopt_venue_correlation()` and wired it into `VenueReconciler.reconcile()` so a rehydrated order's venue correlation is repopulated on restart (WR-02 — its post-restart fill now reaches the mirror instead of being silently buffered), reordered the partial-fill branch to validate the transition before mutating `filled_quantity` (WR-03), and recorded WR-05 as a documented-only dormant extension point — each closure backed by a regression test that would have caught the gap.**

## Performance

- **Duration:** ~15 min
- **Tasks:** 2 / 2
- **Files modified:** 6 (4 source, 2 tests)

## Accomplishments

### Task 1 — WR-02 (RECON-05): `adopt_venue_correlation` seam + wiring + regression
`OkxExchange.adopt_venue_correlation(order)` repopulates the three in-memory correlation maps (`_orders_by_venue_id`, `_venue_id_by_order_id`, `_orders_by_clOrdId`) for a rehydrated Order that never went through `_submit_order` — the ONLY writer of those maps. It builds an `OrderEvent` via `new_order_event(order)`, keys off `order.venue_order_id` (None → early return), writes all three maps under `_correlation_lock` exactly as `_submit_order` does, pops any fills buffered under `_pending_fills_by_venue_id`, and re-drains them OUTSIDE the lock (the lock is non-reentrant and `_handle_trade` re-acquires it). Without this seam, once CR-01 (05-10) spawns the live fill stream, a post-restart fill for a rehydrated resting order resolved to no OrderEvent and was buffered forever (silently lost), and a cancel of a rehydrated order was a silent no-op.

Wired into `VenueReconciler`: added an optional `exchange` kwarg, and a new step 6 in `reconcile()` (a `_adopt_venue_correlation(working)` helper) that runs AFTER `_relink_brackets` (so freshly re-linked bracket legs carry their stamped venue ids) and calls the seam for each working-set order whose `venue_order_id is not None`. A `None` exchange (paper/backtest/test paths) is a clean skip. The construction in `live_trading_system.py` now passes `exchange=self._okx_exchange`.

### Task 1 — regression tests
Added to `tests/unit/execution/test_okx_fill_idempotency.py`:
- `test_adopt_correlation_drains_prebuffered_fill` — a fill delivered BEFORE adoption is buffered under `_pending_fills_by_venue_id`; `adopt_venue_correlation` drains it and a FillEvent emits.
- `test_adopt_correlation_lets_postrestart_fill_reach_mirror` — after adoption, a fresh post-restart fill resolves via the repopulated map and emits (not buffered).
- `test_adopt_correlation_none_venue_id_is_noop` — an order with no venue id is a clean no-op (no map write, no crash).

### Task 2 — WR-03 (RECON-02): validate-before-mutate + regression
`reconcile_manager.py`'s partial-fill branch now computes the prospective `new_filled = to_money(order.filled_quantity + increment)` into a local, builds `additional_data` from it, validates the `PARTIALLY_FILLED` transition via `add_state_change(..., allow_same_status=True)`, and assigns `order.filled_quantity = new_filled` ONLY on success. On a rejected transition it returns `(False, False)` WITHOUT having mutated `filled_quantity` — so the "mirror left unchanged" log/contract now holds literally (pre-reorder the quantity was bumped before the validation could reject it; dormant only because `allow_same_status=True` never fails today). The success path is behavior-identical (validate then assign, no early return between them). TAB indentation, D-12/D-13 comments, and the `to_money` Decimal edge preserved.

Added `test_rejected_partial_transition_leaves_filled_quantity_unchanged` to `tests/unit/order/test_partial_fill_terminalize.py`: forces `add_state_change` to return `False`, applies a strict-shortfall partial through the reconcile path, and asserts `filled_quantity` is unchanged and the call returned `[]` (no release, no terminalization). This fails against the pre-reorder code.

## WR-05 — documented-only (no code change)

`PortfolioHandler._compare_symbol_drift`'s adopt-and-continue branch (`portfolio_handler.py:733-743`) intentionally LOGS a symbol drift without correcting engine state. It is DORMANT this phase because `_drift_reconciler` defaults `None`, so the branch is never reached. This is an **intentional extension point** (a future drift-reconciler plugs in here), not a defect — recorded so a future reviewer does not re-flag it. **No code was written for WR-05, and `itrader/portfolio_handler/portfolio_handler.py` is untouched by this plan** (confirmed: `git diff --stat` shows it unchanged).

## Deviations from Plan

None — plan executed exactly as written. Rules 1–3 not triggered; no architectural (Rule 4) decisions surfaced.

## Verification

- `poetry run pytest tests/unit/execution/test_okx_fill_idempotency.py tests/integration/test_okx_inertness.py -q` → 11 passed (incl. the 3 new adopt tests; okx-inertness held — the seam adds no backtest hot-path import).
- `poetry run pytest tests/unit/order/test_partial_fill_terminalize.py -q` → 7 passed (incl. the new WR-03 test).
- `poetry run pytest tests/integration/test_backtest_oracle.py tests/integration/test_two_sided_restart.py tests/integration/test_bracket_restart_relink.py … -q` → 25 passed (backtest oracle byte-exact — milestone gate held; existing restart suites green — the adopt seam is additive).
- `mypy --strict` clean on all 4 modified source files.
- `grep -c 'def adopt_venue_correlation' itrader/execution_handler/exchanges/okx.py` → 1; `grep -c 'adopt_venue_correlation' itrader/portfolio_handler/reconcile/venue_reconciler.py` → 4; `grep -c 'exchange=self\._okx_exchange' itrader/trading_system/live_trading_system.py` → 1.

## Commits

- `da487e70` fix(05-11): WR-02 — adopt_venue_correlation seam repopulates OKX correlation maps for rehydrated orders
- `cd3fa92b` fix(05-11): WR-03 — validate partial-fill transition before mutating filled_quantity
</content>
</invoke>

## Self-Check: PASSED
