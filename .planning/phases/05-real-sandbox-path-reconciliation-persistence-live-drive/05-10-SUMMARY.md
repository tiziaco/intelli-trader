---
phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
plan: 10
subsystem: live-trading
tags: [live-fill-path, okx-connect, reconnect-resume, atomic-halt, thread-safety, CR-01, WR-04, WR-01, RECON-02, RES-01, RECON-03]

# Dependency graph
requires:
  - phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
    plan: 02
    provides: "OkxExchange.connect() → connector.spawn(_stream_fills/_stream_orders) — the SOLE live fill/order stream spawn site"
  - phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
    plan: 04
    provides: "Halt-aware LiveTradingSystem (HALTED status, _dispatch_live gate, freeze-in-place halt)"
  - phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
    plan: 07
    provides: "VenueReconciler.reconcile() + _halt_on_orphan_positions — the startup two-sided reconcile whose orphan-halt justifies WR-04"
  - phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
    plan: 08
    provides: "Reconnect supervisor + pause/resume (D-19) — dead code in production until CR-01 spawned the streams"
provides:
  - "CR-01 closed: LiveTradingSystem.start() calls self._okx_exchange.connect() before RUNNING — the live fill/order streams are actually spawned so real FillEvents reach OrderHandler/PortfolioHandler on_fill; a failed ConnectionResult re-raises → SystemStatus.ERROR / start() False"
  - "WR-04 closed: resume docstrings + log honestly describe a fresh REST balance/position SNAPSHOT (not a full two-sided reconcile); justified from _halt_on_orphan_positions (a mid-session blind reconcile would spuriously HALT)"
  - "WR-01 closed: halt() check-and-set is atomic under one _status_lock acquisition — concurrent halt callers fire exactly one CRITICAL alert and the first halt_reason wins"
  - "3 regression tests that would have CAUGHT these gaps (fill-stream-spawned, failed-connect→ERROR, resume-snapshots-before-clearing, concurrent-halt-single-alert)"
affects: [live-fill-path, reconciliation, reconnect-resilience, RECON-06-sandbox-e2e]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "ConnectionResult check-then-raise: OkxExchange.connect() RETURNS a ConnectionResult (never raises, unlike OkxConnector.connect()), so start() checks .success and re-raises to reuse the ONE existing except → ERROR path rather than inventing a second error branch"
    - "Atomic check-and-set: the status FLIP happens under the SAME lock acquisition as the guard; _notify_status_change is split out of _update_status so the winner emits the callback/log/alert ONCE outside the lock"

key-files:
  created:
    - .planning/phases/05-real-sandbox-path-reconciliation-persistence-live-drive/05-10-SUMMARY.md
  modified:
    - itrader/trading_system/live_trading_system.py
    - tests/integration/test_live_system_okx_wiring.py
    - tests/unit/execution/test_reconnect_resilience.py

key-decisions:
  - "CR-01 wire placed AFTER _okx_data_provider.start_stream() (client + load_markets live, which the watch_* streams need) and BEFORE VenueReconciler.reconcile() — the fill/order streams are live during reconcile; the 05-05 fill-ID dedup covers the concurrent-stream case. connect() is guarded by `self.exchange == 'okx' and self._okx_exchange is not None` so it never touches the non-OKX or backtest path (inertness held)."
  - "WR-04 DECISION (grounded in venue_reconciler.reconcile / _halt_on_orphan_positions): resume does a fresh REST balance/position snapshot, NOT the full two-sided reconcile. A blind mid-session reconcile would spuriously HALT — _halt_on_orphan_positions treats any venue position whose symbol has no ACTIVE order in the rehydrated working set as an orphan, but mid-session the engine legitimately holds positions from filled (terminal, non-bracket) orders; re-running _adopt_fill_deltas against a store whose filled_quantity lags an in-flight live fill also risks a double-adopt. The full two-sided reconcile is a startup-before-RUNNING contract only. Control flow was NOT changed (snapshot-before-resume + stay-paused-on-failure already held) — only docstrings/log/comment made honest."
  - "WR-01: made halt() atomic by flipping self._status = HALTED UNDER the guard's lock acquisition (the status flip IS the check-and-set), not in a second _update_status lock. Extracted _notify_status_change from _update_status so the winning caller reuses the exact callback/log path once, outside the lock (status_callback / queue.put must never run holding _status_lock; threading.Lock is non-reentrant). The old two-acquisition form let both concurrent callers see a non-HALTED status → both clobbered halt_reason and both fired the CRITICAL alert."

patterns-established:
  - "Split lock-set from notify: _update_status now = (flip under lock) + _notify_status_change (log + callback outside lock); halt() reuses the notify half after its own atomic flip"

requirements-completed: [RECON-02, RES-01, RECON-03]

# Metrics
duration: ~20min
completed: 2026-07-02
---

# Phase 05 Plan 10: Gap-Closure — Live Fill Path + Honest Resume + Atomic Halt Summary

**Wired `self._okx_exchange.connect()` into `start()` (CR-01) so the live fill/order streams are actually spawned, made the reconnect-resume path honestly a REST snapshot (WR-04), and made `halt()`'s check-and-set atomic (WR-01) — each closure backed by a regression test that would have caught the gap.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 3 / 3
- **Files modified:** 3 (1 source, 2 tests)

## Accomplishments

### Task 1 — CR-01: wire `_okx_exchange.connect()` into `start()`
`LiveTradingSystem.start()` now calls `self._okx_exchange.connect()` on the OKX arm before `status=RUNNING` and before `VenueReconciler.reconcile()`. This is the SOLE spawn site for `OkxExchange._stream_fills()`/`_stream_orders()` (via `connector.spawn`) — without it, no real `FillEvent` ever streamed back, the order mirror stayed PENDING forever, and the 05-08 order-arm reconnect supervisor was dead code in production. Because `connect()` RETURNS a `ConnectionResult` (never raises, unlike `OkxConnector.connect()`), the wire checks `.success` and re-raises a `RuntimeError` carrying `error_message` so the failure flows through the existing `except Exception` → `SystemStatus.ERROR` → `return False` path (no second error branch invented). Guarded by `self.exchange == 'okx' and self._okx_exchange is not None`, so the backtest/non-OKX path is untouched.

### Task 2 — CR-01 regression tests
Added to `tests/integration/test_live_system_okx_wiring.py`:
- `test_start_spawns_okx_order_arm_fill_stream` — builds `LiveTradingSystem(exchange="okx")` fully offline, stubs every network-touching call (`_okx_connector.connect`, `feed.warmup`, `_okx_data_provider.start_stream`, `_venue_account`), spies `_okx_exchange.connect`, drives `start()`, and asserts the spy was called once and status is RUNNING. This is the assertion the verification proved absent (`grep _okx_exchange.connect(` returned 0 across `tests/`); reverting the Task-1 call makes it fail.
- `test_start_fails_when_okx_exchange_connect_fails` — stubs `connect()` to return `ConnectionResult(success=False, ...)`, asserts `start()` returns False and status is ERROR.
Both `stop()` in a `finally` so no authenticated socket leaks under `filterwarnings=["error"]`.

### Task 3 — WR-04 honest resume + WR-01 atomic halt + tests
- **WR-04:** Updated `_maybe_resume_after_reconnect` / `pause_submission` / `resume_submission` docstrings, the resume log line, and the wire comments so they say "fresh REST balance/position snapshot" instead of "REST reconcile" — `grep -ci 'REST reconcile'` on the module now returns 0. Added the decision comment citing `_halt_on_orphan_positions` as why the full two-sided reconcile is a startup contract, not a per-reconnect action. Control flow unchanged.
- **WR-01:** `halt()` now flips `self._status = SystemStatus.HALTED` under the SAME `_status_lock` acquisition as the idempotency guard (atomic check-and-set); extracted `_notify_status_change` from `_update_status` so only the winning caller emits the callback/log and the single CRITICAL `ErrorEvent`, outside the lock.
- Added `test_resume_snapshots_before_clearing_pause` (snapshot-before-clear happy path + stays-paused-and-re-flags on a raising snapshot) and `test_concurrent_halt_fires_single_alert` (32 barrier-synchronised halt callers → exactly one CRITICAL `EngineHalted` alert, `_halt_reason` is one of the racers, status HALTED).

## Deviations from Plan

None — plan executed exactly as written. Rules 1–3 not triggered; no architectural (Rule 4) decisions surfaced. The WR-04 DECISION called for in Task 3 was made as specified (snapshot-not-reconcile, grounded in `_halt_on_orphan_positions`).

## Verification

- `poetry run pytest tests/integration/test_live_system_okx_wiring.py tests/unit/execution/test_reconnect_resilience.py -q` → 21 passed (incl. the 4 new tests).
- `poetry run pytest tests/integration/test_backtest_oracle.py -q` → 3 passed (byte-exact 134 / 46189.87730727451 — milestone gate held).
- `poetry run pytest tests/integration/test_okx_inertness.py -q` → 1 passed (live/venue machinery stays off the backtest hot path).
- `mypy --strict itrader/trading_system/live_trading_system.py` → Success: no issues found.
- `grep -c 'self\._okx_exchange\.connect(' itrader/trading_system/live_trading_system.py` → 1; `grep -ci 'REST reconcile' …` → 0; `grep -c '_okx_exchange\.connect(' tests/integration/test_live_system_okx_wiring.py` → 4.

## Commits

- `a24d5e89` fix(05-10): wire okx_exchange.connect() into start() — CR-01 live fill path
- `e95e786d` test(05-10): CR-01 regression — start() spawns fill stream, failed connect → ERROR
- `fdb6c11d` fix(05-10): honest resume snapshot (WR-04) + atomic halt (WR-01) + tests

## Self-Check: PASSED
