---
phase: 02-event-bus
plan: 02
subsystem: order-handler, strategy-handler
tags: [ctx-02, d-02, handler-owns-storage, compose-seam, oracle-dark]
status: complete
requires:
  - "OrderStorageFactory.create(environment, backend=) — existing 05-xx seam"
  - "SignalStorageFactory.create(environment, backend=) — existing 05-03 seam"
  - "PortfolioHandler.__init__(environment, backend) — the D-02 shape template (LR-13)"
provides:
  - "OrderHandler.__init__(*, environment='backtest', sql_engine=None) + OrderHandler.storage attribute"
  - "StrategiesHandler.__init__(*, environment='backtest', sql_engine=None); signal_store now optional"
  - "Both handlers own their storage init and expose the concrete on .storage / .signal_store"
affects:
  - "plan 02-03 compose fold reads .storage / .signal_store back (set_order_storage + Engine holder)"
tech-stack:
  added: []
  patterns: [handler-owns-storage-init, keyword-only-additive-ctor-params, factory-environment-seam]
key-files:
  created:
    - tests/unit/order/test_order_handler_storage.py
    - tests/unit/strategy/test_strategies_handler_storage.py
  modified:
    - itrader/order_handler/order_handler.py
    - itrader/strategy_handler/strategies_handler.py
decisions:
  - "D-02: handlers own storage init from (environment, sql_engine), PortfolioHandler template (LR-13)"
  - "D-08 honoured: global_queue param name/type untouched (retype deferred to 02-03)"
  - "D-11 honoured: live_trading_system.py untouched"
  - "D-18 preserved: OrderManager still owns storage for all read paths; .storage is a wiring seam, not a second read path"
metrics:
  duration: ~6min
  completed: 2026-07-09
  tasks: 3
  files: 4
---

# Phase 02 Plan 02: Handler-Owns-Storage Retrofit Summary

`OrderHandler` and `StrategiesHandler` now own their storage init from keyword-only
`(environment='backtest', sql_engine=None)` params — mirroring the `PortfolioHandler`
template (LR-13 / D-02) — and expose the resolved concrete on `.storage` / `.signal_store`
for the plan-02-03 compose back-read. Purely additive: `compose_engine` still passes
storage positionally until 02-03, so the backtest slice constructs the identical
`InMemoryOrderStorage` / `InMemorySignalStore` concretes and the SMA_MACD oracle stays
byte-exact `134 / 46189.87730727451`.

## What Was Built

- **Task 1 — `OrderHandler` (commit `46c50885`):** Added keyword-only `environment`/`sql_engine`
  ctor params (after a bare `*`). Kept `order_storage=` as the explicit override (back-compat).
  Resolved `self.storage = order_storage or OrderStorageFactory.create(environment, backend=sql_engine)`
  and forwarded that exact instance into `OrderManager`. `Any` was already imported. TABS preserved.
- **Task 2 — `StrategiesHandler` (commit `9eb3208c`):** Made `signal_store` optional
  (`Optional[SignalStore] = None`) in the same positional slot; added keyword-only
  `environment`/`sql_engine`; resolved `self.signal_store = signal_store or SignalStorageFactory.create(environment, backend=sql_engine)`.
  Imported `Optional` (typing) and `SignalStorageFactory` (alongside the existing `SignalStore` import). TABS preserved.
- **Task 3 — unit cases (commit `4a7609d6`):** `tests/unit/order/test_order_handler_storage.py`
  (backtest slice → `InMemoryOrderStorage`; override wins; `.storage` identity == the instance
  forwarded to `OrderManager` — the 02-03 back-read seam) and
  `tests/unit/strategy/test_strategies_handler_storage.py` (backtest slice → `InMemorySignalStore`;
  override wins). 4-space; dirs kept package-less (no `__init__.py`).

## Verification Evidence

- New test files: `5 passed`.
- Existing handler suites `tests/unit/order tests/unit/strategy`: `439 passed` (no regression).
- `mypy --strict` on both handlers: `Success: no issues found in 2 source files`.
- Backtest oracle `tests/integration/test_backtest_oracle.py`: `3 passed` — byte-exact `134 / 46189.87730727451`.
- `grep -cP '^    [^ ]'` == 0 on both TABS handler files (no 4-space lines introduced).
- Importing either retrofitted handler pulls **no** `sqlalchemy` (backtest arm in-memory; `'live'` arm SQL imports stay lazy) — D-06 inertness held.
- D-11: `git diff --exit-code itrader/trading_system/live_trading_system.py` — no changes.
- `poetry.lock`: empty diff (zero new dependency).

## Deviations from Plan

None — plan executed exactly as written. No deviation rules triggered; all per-task
`<verify>` commands and plan-level verification passed on first run.

## Threat Surface

No new trust boundary introduced (matches the plan's threat model). T-02-04 (backtest
instance identity) and T-02-05 (import inertness) mitigations are proven by the oracle
gate and the no-sqlalchemy import checks above; T-02-06 (D-18 storage ownership) is
preserved — `.storage` reads the same instance the manager owns.

## Self-Check: PASSED

- FOUND: itrader/order_handler/order_handler.py (modified)
- FOUND: itrader/strategy_handler/strategies_handler.py (modified)
- FOUND: tests/unit/order/test_order_handler_storage.py
- FOUND: tests/unit/strategy/test_strategies_handler_storage.py
- FOUND commit: 46c50885 (OrderHandler)
- FOUND commit: 9eb3208c (StrategiesHandler)
- FOUND commit: 4a7609d6 (unit cases)
