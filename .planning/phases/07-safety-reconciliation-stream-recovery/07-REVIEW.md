---
phase: 07-safety-reconciliation-stream-recovery
reviewed: 2026-07-14T00:00:00Z
depth: standard
files_reviewed: 41
files_reviewed_list:
  - itrader/config/__init__.py
  - itrader/config/safety.py
  - itrader/config/system.py
  - itrader/core/enums/__init__.py
  - itrader/core/enums/order.py
  - itrader/core/exceptions/__init__.py
  - itrader/core/exceptions/portfolio.py
  - itrader/events_handler/events/__init__.py
  - itrader/events_handler/events/control.py
  - itrader/portfolio_handler/account/base.py
  - itrader/portfolio_handler/account/venue.py
  - itrader/portfolio_handler/reconcile/reconciliation_coordinator.py
  - itrader/portfolio_handler/reconcile/venue_reconciler.py
  - itrader/price_handler/feed/live_bar_feed.py
  - itrader/trading_system/live_runner.py
  - itrader/trading_system/live_trading_system.py
  - itrader/trading_system/route_registrar.py
  - itrader/trading_system/safety/__init__.py
  - itrader/trading_system/safety/pre_trade_throttle.py
  - itrader/trading_system/safety/safety_controller.py
  - itrader/trading_system/safety/stream_recovery_handler.py
  - itrader/trading_system/session_initializer.py
  - tests/integration/test_durable_halt.py
  - tests/integration/test_early_durable_halt_refusal.py
  - tests/integration/test_live_portfolio_durable_wiring.py
  - tests/integration/test_live_system_okx_wiring.py
  - tests/integration/test_resume_gated_on_all_streams.py
  - tests/integration/test_resume_missed_fill_catchup.py
  - tests/unit/config/test_safety_config.py
  - tests/unit/core/test_order_risk_role.py
  - tests/unit/events/test_control_events.py
  - tests/unit/execution/test_drift_halt_policy.py
  - tests/unit/execution/test_off_loop_halt_write.py
  - tests/unit/execution/test_reconnect_resilience.py
  - tests/unit/portfolio/test_reconciliation_coordinator.py
  - tests/unit/trading_system/test_pause_defer_replay.py
  - tests/unit/trading_system/test_pre_trade_throttle.py
  - tests/unit/trading_system/test_safety_controller.py
  - tests/unit/trading_system/test_stream_recovery_handler.py
findings:
  critical: 0
  warning: 3
  info: 2
  total: 5
status: resolved
warnings_resolved: 3
info_deferred: 2
resolution: "WR-01/WR-02/WR-03 fixed and independently re-verified on the main checkout (commits 9d600212, 8233315e): full suite 2201 passed / 6 skipped, mypy --strict clean (257 files), oracle byte-exact, OKX inertness green. IN-01/IN-02 reviewed and deferred by decision (documented, not fixed)."
---

# Phase 07: Code Review Report

**Reviewed:** 2026-07-14
**Depth:** standard
**Files Reviewed:** 41
**Status:** issues_found

## Summary

Reviewed the v1.8 Phase 07 (Safety + Reconciliation + Stream Recovery) extraction:
`SafetyController`, `PreTradeThrottle`, `StreamRecoveryHandler`, `ReconciliationCoordinator`,
`VenueReconciler`, the CONTROL-tier events, the `LiveBarFeed` CF-2 single-writer tripwire,
and the `LiveTradingSystem` facade after its donor-block deletions.

The correctness-critical properties the domain brief flagged all hold:

- **Money (Decimal end-to-end):** `PreTradeThrottle._exceeds_notional` computes
  `abs(price * quantity)` on `OrderEvent.price`/`.quantity`, both typed `Decimal`
  (`events/order.py:53-54`); no `float()` on the notional path. `VenueAccount` /
  `VenueReconciler` cross every venue float via `to_money(str(x))`.
- **Determinism:** the throttle sliding window and the D-09 WARNING dedup read the
  INJECTED `self._clock.now()` (`pre_trade_throttle.py:157,234`), never `time.time()`/
  `datetime.now()`. `build_live_system` injects `WallClock()` (correct for the live seam).
- **Threading / CF-2:** `StreamRecoveryHandler.on_reconnect` touches only
  `catch_up_missed_fills` + `snapshot` — never the ring writer; the loop-native ring
  backfill is gated behind `_assert_ring_writer_single_thread` (`live_bar_feed.py:634-661`).
- **Indentation:** the 4-space convention is consistent within each reviewed file.

No blocker-tier defects found. The issues below are a dead-code cluster left by the
07-06 facade deletions (which mypy `ignore_errors` masks — exactly the flagged blind
spot), a stat-accounting inaccuracy introduced by the new pre-submit throttle, and the
stale test coverage that pins the dead facade methods alive.

## Warnings

### WR-01: Orphaned facade methods duplicate `ReconciliationCoordinator` and are dead in production

> **✅ RESOLVED** — commit `9d600212` (atomic with WR-03). Deleted both dead facade methods (`_link_venue_account_to_portfolios`, `_run_session_baseline_guard`) and the two orphaned imports (`Decimal`, `is_within_single_unit_tolerance`); grep-verified 0 references remain in the facade. Re-verified on the main checkout (mypy --strict clean, full suite green).

**File:** `itrader/trading_system/live_trading_system.py:297-381` (also imports at `:3`, `:9`)
**Issue:** `LiveTradingSystem._link_venue_account_to_portfolios` (297-330) and
`_run_session_baseline_guard` (332-381) are full method bodies that are byte-duplicates of
`ReconciliationCoordinator._link_venue_account_to_portfolios` (reconciliation_coordinator.py:151)
and `._run_session_baseline_guard` (:179). Production `start()` reconciles exclusively via
`self._build_reconciliation_coordinator().run_startup_reconcile()` (`:724`) — the coordinator
runs its OWN copies. A grep confirms the two facade methods have ZERO production callers
(only tests reference them). This is precisely the "private helpers left orphaned after the
07-06 deletions" hazard: because this module is under a mypy `ignore_errors` override, the
dead code and its now-single-use imports pass both mypy and the suite silently.

Consequences:
1. Two live copies of the venue-link + baseline-guard logic can drift; the copy production
   actually runs (the coordinator's) is the one that matters, but edits could land on the
   facade copy and appear "tested" while never executing.
2. The imports `from decimal import Decimal` (`:3`) and
   `from itrader.portfolio_handler.reconcile import is_within_single_unit_tolerance` (`:9`)
   exist SOLELY to serve these two dead methods (grep shows no other use — `Decimal` only at
   359/367, `is_within_single_unit_tolerance` only at 369).

**Fix:** Delete both dead facade methods and the two now-unused imports; the
`ReconciliationCoordinator` is the single owner (SAFE-05/D-17).
```python
# live_trading_system.py — remove:
#   line 3:  from decimal import Decimal
#   line 9:  from itrader.portfolio_handler.reconcile import is_within_single_unit_tolerance
#   lines 297-330:  def _link_venue_account_to_portfolios(self) -> None: ...
#   lines 332-381:  def _run_session_baseline_guard(self) -> None: ...
```
(Update WR-03's tests in the same change — they are the only remaining references.)

### WR-02: A throttle-REFUSED order is still counted as `orders_executed`

> **✅ RESOLVED** — commit `8233315e`. A throttle-rejected ORDER now routes to a dedicated `on_order_throttle_rejected` facade hook that bumps a new `orders_throttle_rejected` counter (surfaced in `get_status()['statistics']`) and never touches `orders_executed`. Locked by `tests/unit/trading_system/test_live_runner_stats.py`. (Implemented via an injected hook matching the codebase's D-04 callback pattern rather than the magic-string suggested here — same observable outcome.)

**File:** `itrader/trading_system/live_runner.py:154-167`; `itrader/trading_system/live_trading_system.py:499-509`
**Issue:** In `LiveRunner._run_loop`, when the new pre-submit throttle rejects an ORDER
(`rejected = ... and not self._pre_submit(event)`, `:154-156`), the loop correctly SKIPS
`self._dispatch_gate(event)` — but then still calls
`self._update_stats(event.type.name ...)` unconditionally (`:166`). For an ORDER,
`_update_stats` increments `_stats['orders_executed']`
(`live_trading_system.py:508-509`). A throttle-rejected order emitted only a
`FillEvent(REFUSED)` and never executed, yet it bumps the "orders executed" counter
surfaced in `get_status()['statistics']`. The new SAFE-06 pre-submit path introduced this
rejected-but-counted case; the read-model stat now over-reports executions.

**Fix:** Do not attribute a rejected order to the executed count. E.g. gate the stats key,
or count a rejection separately:
```python
if not rejected:
    self._dispatch_gate(event)
    self._update_stats(event.type.name if hasattr(event, 'type') else 'UNKNOWN')
else:
    # count as processed, not executed (throttle REFUSED it pre-submit)
    self._update_stats('THROTTLE_REJECTED')  # or a dedicated counter
self._record_bar_metrics(event)
```

### WR-03: Tests assert against / stub the DEAD facade methods — false coverage

> **✅ RESOLVED** — commit `9d600212` (atomic with WR-01). `test_early_durable_halt_refusal.py` now asserts `_build_reconciliation_coordinator.assert_not_called()` (proves the durable-halt top-gate short-circuits before venue I/O); `test_live_system_okx_wiring.py` exercises `ReconciliationCoordinator._link_venue_account_to_portfolios` (the copy production runs); `test_live_portfolio_durable_wiring.py` monkeypatches re-pointed to the coordinator class.

**File:** `tests/integration/test_early_durable_halt_refusal.py:86-87,104-105,128-129`;
`tests/integration/test_live_system_okx_wiring.py:286,310`;
`tests/integration/test_live_portfolio_durable_wiring.py:138,148`
**Issue:** Several tests couple to the WR-01 dead facade methods, giving false confidence:
- `test_early_durable_halt_refusal.py:104-105` asserts
  `system._link_venue_account_to_portfolios.assert_not_called()` and
  `_run_session_baseline_guard.assert_not_called()`. Production NEVER calls these facade
  methods (it calls the coordinator's copies), so both assertions pass VACUOUSLY — they
  would pass even if the durable-halt top-gate were removed. The meaningful spies in the
  same test (`_okx_connector.connect`, `_venue_account.snapshot`, etc.) still carry the
  test's weight, but these two lines assert nothing.
- `test_live_system_okx_wiring.py:286,310` call `system._link_venue_account_to_portfolios()`
  DIRECTLY and assert the linking/fail-loud behavior. This validates the facade's dead copy,
  not the `ReconciliationCoordinator` copy that production actually runs — a real drift blind
  spot (the tested code and the shipped code are different methods).
- `test_live_portfolio_durable_wiring.py:138,148` monkeypatch the dead facade methods to
  no-ops; those patches now have no effect on the production reconcile path.

**Fix:** Re-point these tests at `ReconciliationCoordinator` (unit-test its
`_link_venue_account_to_portfolios` / `_run_session_baseline_guard` directly — see the
existing `tests/unit/portfolio/test_reconciliation_coordinator.py`), and for the
durable-halt refusal test, assert that the coordinator's `run_startup_reconcile` (or
`venue_account.snapshot`) is not reached rather than the dead facade methods.

## Info

### IN-01: Asymmetric `None`-guard between `_exceeds_notional` and `_reject`

> **✅ RESOLVED** — quick task `260714-v6n` (commit `baa125f8`). Fixed via "Option B + Option A folded in": `allow()` now opens with an ORDER-only top-gate (`getattr(event, 'type', None) is not EventType.ORDER → return True`), so the throttle meters ORDER events only and no longer relies on `live_runner`'s call-site type gate for safety — past the gate the ENTRY branch provably implies an `OrderEvent`. The now-provably-dead `None`-guard in `_exceeds_notional` was removed. Zero behavior change (CANCEL/PROTECTIVE/ENTRY paths unchanged). Re-verified: mypy --strict clean on the module, 5/5 throttle unit tests, oracle byte-exact (134 / 46189.87730727451) + OKX inertness green.

**File:** `itrader/trading_system/safety/pre_trade_throttle.py:186-191,217-222`
**Issue:** `_exceeds_notional` defensively guards `price`/`quantity` being `None`
(`:188-189`), but `_reject` reads `event.price`/`event.quantity` directly
(`:219-221`). This is safe today because `_reject` only fires for an ENTRY `OrderEvent`,
whose `price`/`quantity` are non-optional `Decimal` (`events/order.py:53-54`) — so the
`_exceeds_notional` `None` guard is effectively dead defense. Harmless, but the two paths
disagree on whether a priced order is guaranteed; if a future non-`OrderEvent` ever reaches
`allow()` on the ENTRY branch, `_reject` would raise `AttributeError` while
`_exceeds_notional` would silently pass.
**Fix:** Either drop the (currently unreachable) `None` guard in `_exceeds_notional` for
consistency, or add a matching guard/typed precondition in `allow()` so both paths assume
the same contract.

### IN-02: `snapshot()` and store `rehydrate()` run twice on the startup reconcile path

> **◻ DEFERRED → tracked** — correctness-neutral (idempotent REST snapshot + rehydrate); a redundant round-trip only. Performance is out of review scope. Owner-approved deferral: filed as a pending todo (`.planning/todos/pending/07-double-startup-snapshot-in02.md`) to fold into the end-of-milestone `live_trading_system.py` / live-reconcile refactor rather than clean now.

**File:** `itrader/portfolio_handler/reconcile/reconciliation_coordinator.py:125,145`;
`itrader/portfolio_handler/reconcile/venue_reconciler.py:135,139`
**Issue:** `ReconciliationCoordinator.run_startup_reconcile` calls `account.snapshot()`
(`:125`) and then constructs a `VenueReconciler` whose `.reconcile()` calls
`self._venue_account.snapshot()` again (`venue_reconciler.py:139`) plus
`self._store.rehydrate()` (`:135`, in addition to the coordinator's
`portfolio_handler.rehydrate` at `:116`). The REST snapshot and rehydrate are idempotent,
so this is correctness-neutral, but it issues a redundant venue REST round-trip on every
startup reconcile. (Performance is out of v1 review scope — noted only as a redundancy.)
**Fix:** If the double round-trip is undesired, have the coordinator take the snapshot once
and let `VenueReconciler.reconcile()` assume a freshly-snapshotted account (drop its inner
`snapshot()`), or vice-versa — pick one owner of the REST snapshot.

---

_Reviewed: 2026-07-14_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
