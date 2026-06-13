---
phase: 04-composition-config-interface
plan: 02
subsystem: composition-config-interface
tags: [composition, factory, compose-engine, byte-exact, commission-late-binding, symbol-seeding, rng-dedup]
requires:
  - "04-01: CommissionEstimator Protocol, OrderConfig model, SystemSpec frozen spec"
provides:
  - "compose_engine shared mode-agnostic wiring seam (trading_system/compose.py, D-14/D-14a)"
  - "FeeModelCommissionEstimator late-binding adapter conforming to CommissionEstimator (D-15)"
  - "BacktestRunner sync fail-fast driver, record_metrics post-bar order preserved (D-14)"
  - "BacktestTradingSystem thin holder + build_backtest_system(spec) factory (D-03/D-04)"
  - "construction-time ExchangeConfig threading + complete symbol-set seeding (D-13)"
  - "rng_seed read off the process-wide config singleton (D-16)"
  - "print_metrics_summary lifted into reporting/summary.py (W4-07)"
affects:
  - "Wave 3 (04-03): SimulatedExchange/handlers migrate to the dict->model_validate update_config canonical contract"
  - "Wave 4 (04-05): e2e _build_and_run collapses onto build_backtest_system(spec); the no-config BTCUSD fallback + the TradingSystem alias are removed; oracle/integration sites swap to BacktestTradingSystem"
tech-stack:
  added: []
  patterns:
    - "factory/holder split (D-04): factory selects mode-specific backends + seeds config, the class is a dumb holder of a pre-built engine + runner"
    - "shared mode-agnostic wiring seam (compose_engine) — no backend-string literal; concretes injected by the factory (D-14a)"
    - "late-binding read-model adapter (FeeModelCommissionEstimator holds the exchange ref, reads fee_model in __call__)"
    - "replacement-safe construction-time symbol seeding (the complete set folded into ExchangeConfig.limits before the exchange reads it)"
key-files:
  created:
    - itrader/trading_system/compose.py
    - itrader/trading_system/backtest_runner.py
    - tests/integration/test_symbol_seeding.py
  modified:
    - itrader/trading_system/backtest_trading_system.py
    - itrader/trading_system/__init__.py
    - itrader/execution_handler/execution_handler.py
    - itrader/order_handler/order_manager.py
    - itrader/order_handler/order_handler.py
    - itrader/config/__init__.py
    - itrader/reporting/summary.py
    - tests/unit/core/test_commission_estimator.py
    - tests/unit/execution/test_execution_handler.py
decisions:
  - "D-16/Trap 3: ExecutionHandler._resolve_rng_seed reads `from itrader import config; config.performance.rng_seed` off the singleton — the 2nd SystemConfig.default() construction is gone. Seed stays 42, determinism byte-identical."
  - "D-13/Trap 1: the hardcoded register_symbol('BTCUSD') is removed; the COMPLETE supported_symbols set is seeded into ExchangeConfig.limits at construction (replacement-safe). The FACTORY derives default preset ∪ {BTCUSD} ∪ spec tickers (upper-cased). A TEMPORARY no-config fallback (ExecutionHandler builds default preset ∪ {BTCUSD}) keeps direct-construction sites byte-exact until Wave 4 removes it (asserted in tests/unit/execution)."
  - "D-14a: compose_engine is mode-agnostic — order_storage AND signal_store are injected by the factory; the seam contains zero backend-string literals (grep -c \"'backtest'\" == 0). Threaded signal_store as a param (not just order_storage) to fully honor D-14a."
  - "D-15/Trap 2: FeeModelCommissionEstimator holds ONLY the exchange ref; __call__ reads exchange.fee_model late. The oracle-dark late-binding test (zero before swap, non-zero after a fee-model hot-swap) is the single correctness pin. The swap is driven via the LIVE update_config enum API (FeeModelType.PERCENT) — Wave 3 adds the string-coercing dict/model_validate path; the late-binding property is independent of how the swap is expressed."
  - "D-04: build_backtest_system is the factory; BacktestTradingSystem is a thin holder. To preserve direct-construction byte-exactness BEFORE Wave 4 migrates the oracle/integration/e2e/scripts sites, the holder ALSO keeps a legacy __init__ (loose params) that builds the same engine+runner via compose_engine, and exposes the engine components as read-only properties (system.strategies_handler / .portfolio_handler / .store / .order_handler / .execution_handler / ...). The on_tick hook is wrapped so the e2e callback still receives the holder as `system` (not the runner)."
  - "D-05: OrderConfig is threaded into OrderManager/OrderHandler; the str->enum coercion moved into OrderConfig validation. The loose `market_execution=` param is kept as a DEPRECATED backward-compat override (folded into an OrderConfig) so out-of-scope test sites (test_order_manager.py) keep working until Wave 4. commission_estimator retyped Callable -> CommissionEstimator (pure typing)."
metrics:
  duration: ~35 min
  completed: 2026-06-12
  tasks: 3
  files: 11
---

# Phase 4 Plan 02: Composition-Root Collapse (compose_engine / BacktestRunner / factory) Summary

Collapsed the fat `TradingSystem.__init__` + `run()` into the D-04 factory/holder shape, byte-exact: extracted the shared mode-agnostic `compose_engine` wiring seam (D-14/D-14a), the sync fail-fast `BacktestRunner` (D-14, record_metrics order preserved), and the `build_backtest_system(spec)` factory (D-04); threaded construction-time `ExchangeConfig` with replacement-safe complete-symbol-set seeding (D-13/Trap 1); promoted the `_estimate_commission` closure to the typed `FeeModelCommissionEstimator` with proven late binding (D-15/Trap 2); deduped the rng-seed read off the singleton (D-16/Trap 3); and lifted the metrics printout into `reporting/` (W4-07). All six byte-exact traps held.

## What Was Built

- **`itrader/execution_handler/execution_handler.py`** (Task 1, TABS) — `_resolve_rng_seed` now reads `config.performance.rng_seed` off the process-wide singleton (D-16); added an optional `exchange_config` param threaded into `SimulatedExchange(config=...)`; removed the hardcoded `register_symbol('BTCUSD')`; added a `_default_backcompat_config()` helper that builds default preset ∪ {BTCUSD} when no config is supplied (TEMPORARY, Wave 4 removes it).
- **`itrader/trading_system/compose.py`** (Task 2, NEW, TABS) — `compose_engine(*, order_storage, signal_store, csv_paths, start_date, end_date, timeframe, exchange_config, order_config)`: the shared wiring seam returning an `Engine` dataclass; zero backend-string literals (D-14a). `FeeModelCommissionEstimator`: the late-binding adapter (holds the exchange ref, reads `fee_model` in `__call__`).
- **`itrader/order_handler/order_manager.py` + `order_handler.py`** (Task 2, TABS) — threaded `OrderConfig` (coercion moved into validation); retyped `commission_estimator` to `CommissionEstimator`; kept `market_execution=` as a deprecated backward-compat override.
- **`itrader/config/__init__.py`** (Task 2) — exports `OrderConfig`.
- **`itrader/trading_system/backtest_runner.py`** (Task 3, NEW, TABS) — `BacktestRunner`: session setup + the per-tick fail-fast for-loop extracted verbatim (`clock.set_time -> queue.put -> process_events -> record_metrics DIRECT -> on_tick`).
- **`itrader/trading_system/backtest_trading_system.py`** (Task 3, TABS) — renamed to `BacktestTradingSystem` (thin holder); added `build_backtest_system(spec)` factory + the `_seed_supported_symbols` FACTORY-side derivation; kept the legacy `__init__` + a `TradingSystem` alias + engine-delegating properties for the not-yet-migrated sites.
- **`itrader/reporting/summary.py`** (Task 3, 4 SPACES) — `print_metrics_summary(portfolios, logger)` lifted verbatim from the composition root (W4-07).
- **Tests** — appended the D-15 late-binding test to `tests/unit/core/test_commission_estimator.py`; added the BTCUSD no-config fallback assertion to `tests/unit/execution/test_execution_handler.py`; created `tests/integration/test_symbol_seeding.py` (Trap 1, 3 tests incl. replacement-safety).

## Commits

- `33e318f` feat(04-02): rng dedup + construction-time ExchangeConfig threading (D-16/D-13)
- `51b500f` feat(04-02): compose_engine seam + FeeModelCommissionEstimator adapter (D-04/D-14/D-14a/D-15)
- `7ce2afb` feat(04-02): BacktestRunner + thin holder + build_backtest_system factory (D-03/D-04/D-14/W4-07)

## Verification

**BYTE-EXACT GATE — HELD:**
- BTCUSD oracle: `poetry run pytest tests/integration/test_backtest_oracle.py -q` → **3 passed** (134 trades / `final_equity 46189.87730727451`, exact).
- e2e: `make test-e2e` → **58/58 passed**, 854 deselected.
- Determinism: oracle double-run byte-identical (seed 42 unchanged).
- `poetry run mypy itrader` → **Success: no issues found in 181 source files** (179 → 181, +compose.py +backtest_runner.py).
- Full unit + integration suites: **854 passed**.

**Acceptance grep gates:**
- `grep -c 'SystemConfig.default' execution_handler.py` → 0; `config.performance.rng_seed` present.
- `grep -c "register_symbol('BTCUSD')" execution_handler.py` → 0.
- `grep -c "'backtest'" compose.py` → 0 (D-14a).
- `grep -c 'CommissionEstimator' order_manager.py` → ≥1; `self._fee_model =` capture → 0 (late binding).
- `class BacktestTradingSystem` == 1, `def build_backtest_system` == 1, `class TradingSystem` == 0 (alias is an assignment, not a class).
- `record_metrics` in backtest_runner.py present as a DIRECT call (no event type introduced).
- Indentation: zero space-indented body lines in the TAB files (compose.py / backtest_runner.py / backtest_trading_system.py / order_manager.py); reporting/summary.py + the integration test stay 4-space.

## Deviations from Plan

### Auto-fixed / design-clarifying decisions (within Claude's Discretion per CONTEXT.md)

**1. [Design — D-14a] Threaded `signal_store` as a compose_engine param (not just `order_storage`).**
- **Found during:** Task 2.
- **Issue:** The original `__init__` created the signal store via `SignalStorageFactory.create('backtest')` inline — a backend-string literal. Leaving it in `compose_engine` would violate the `grep -c "'backtest'" == 0` D-14a gate.
- **Fix:** `signal_store` is now selected in the FACTORY (and the legacy `__init__`) and injected into `compose_engine` exactly like `order_storage`. This is the consistent application of D-14a (the plan named only `order_storage`, but the signal store is the same mode-specific-backend concern).
- **Files:** compose.py, backtest_trading_system.py.

**2. [Design — D-04 / byte-exact] The holder keeps a legacy `__init__` + engine-delegating properties + a `TradingSystem` alias.**
- **Found during:** Task 3.
- **Issue:** The plan requires `build_backtest_system(spec)` as the new path while keeping the oracle/integration/e2e/scripts direct-construction sites byte-exact "by renaming the class only" until Wave 4 — but those sites read `system.strategies_handler` / `.store` / `.order_handler` etc. and call `.run(...)`. A pure dumb holder of pre-built components would not expose those without the factory.
- **Fix:** The holder accepts BOTH a factory-mode (`engine=`/`runner=`/`signal_store=` kwargs) and the legacy loose-param mode (builds the same engine+runner internally via `compose_engine`), and delegates the component reads through read-only properties. The `TradingSystem = BacktestTradingSystem` alias keeps the import sites compiling. This is the minimal change that satisfies "rename only" for the un-migrated sites; Wave 4 removes the legacy path.
- **Files:** backtest_trading_system.py, __init__.py.

**3. [Design — D-05] `market_execution=` kept as a deprecated backward-compat override.**
- **Found during:** Task 2.
- **Issue:** `tests/unit/order/test_order_manager.py` (out of this plan's modify scope) constructs `OrderManager(..., market_execution="immediate")` and asserts `manager.market_execution is MarketExecution.IMMEDIATE`. Hard-replacing the param would break those out-of-scope tests.
- **Fix:** `OrderConfig` is the primary param; a loose `market_execution=` (when provided) is folded into an `OrderConfig` (coercion via OrderConfig validation, byte-identical stored member). Wave 4 can drop the override.
- **Files:** order_manager.py, order_handler.py.

**4. [Test mechanism — D-15] The late-binding test drives the swap via the LIVE update_config enum API.**
- **Found during:** Task 2 (RED→GREEN).
- **Issue:** The plan `<behavior>` block specifies `exchange.update_config(fee_model_type="percent", fee_rate="0.001")` (string args). The current flat `**kwargs` `update_config` does NOT coerce strings to enums — a string `"percent"` `model_type` hits `_init_fee_model`'s `assert_never`. The dict/`model_validate` canonical contract that coerces strings is Wave 3 (04-03).
- **Fix:** The swap is driven with the working enum form (`FeeModelType.PERCENT`, `Decimal("0.001")`), matching the live `update_config` contract. The **assertion content is unchanged and non-negotiable**: zero before the swap, non-zero after — proving the adapter reads `exchange.fee_model` in `__call__` and never captured it. A comment pins that the swap-expression vs. the late-binding property are independent.
- **Files:** tests/unit/core/test_commission_estimator.py.

## Threat Surface

The two registered tampering threats are mitigated and tested:
- **T-04-03** (symbol-set replacement wipes BTCUSD) — the complete set is seeded at construction (D-13); `test_symbol_seeding.py` asserts the final set == today's union AND replacement-safety; the no-config BTCUSD fallback is asserted in `tests/unit/execution`.
- **T-04-04** (stale commission estimator after fee-model swap) — `FeeModelCommissionEstimator` late binding (D-15); the post-swap non-zero late-binding test pins it (oracle-dark).
- **T-04-05** (rng_seed as a secret) — accepted; rng_seed is determinism config, not a security primitive.

No new security surface introduced (internal structural refactor; no network/auth/untrusted input).

## Known Stubs

None. The `compose_engine` `exchange_config=None` path and the `ExecutionHandler` no-config BTCUSD fallback are deliberate TEMPORARY backward-compat seams (documented, asserted, and scheduled for removal in Wave 4 / 04-05), not stubs that block this plan's goal.

## Self-Check: PASSED
- itrader/trading_system/compose.py — FOUND
- itrader/trading_system/backtest_runner.py — FOUND
- tests/integration/test_symbol_seeding.py — FOUND
- itrader/reporting/summary.py::print_metrics_summary — FOUND
- itrader/trading_system/backtest_trading_system.py::build_backtest_system — FOUND
- commit 33e318f — FOUND
- commit 51b500f — FOUND
- commit 7ce2afb — FOUND
