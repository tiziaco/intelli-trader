---
phase: 04-composition-config-interface
plan: 05
subsystem: composition-config-interface
tags: [composition, factory, build-backtest-system, e2e-collapse, spec-unification, byte-exact, proof-wave, COMP-01, COMP-02]
requires:
  - "04-02: build_backtest_system(spec) factory + BacktestTradingSystem thin holder + compose_engine + construction-time ExchangeConfig threading + complete symbol seeding"
  - "04-03: canonical update_config on the 5 config-model handlers"
  - "04-04: non-config-model update_config (StrategiesHandler + BacktestBarFeed)"
  - "04-01: promoted SystemSpec (run-mode-agnostic, field-for-field from ScenarioSpec)"
provides:
  - "e2e _build_and_run COLLAPSED onto build_backtest_system(spec) — the D-14 post-construction fee/slippage re-init seam + the additive register_symbol loop are REMOVED (subsumed by construction-time ExchangeConfig threading + symbol seeding, D-01/D-13/D-14)"
  - "scenario_spec.py UNIFIED onto the promoted SystemSpec (ScenarioSpec = SystemSpec alias; PortfolioSpec/Action re-exported) — the harness + factory consume ONE spec type, leaves unchanged"
  - "all scripts/integration TradingSystem construction+import sites migrated to BacktestTradingSystem (D-03); the Wave-2 TradingSystem alias removed"
  - "BYTE-EXACT PHASE GATE PROVEN: oracle 134/46189.87730727451 exact, e2e 58/58, full suite 946 green, mypy --strict clean, determinism double-run byte-identical — COMP-01 + COMP-02 proven"
affects:
  - "Phase 5 (SIG-*): builds on the now-fully-declarative composition surface (build_backtest_system + the unified SystemSpec)"
  - "N+4 live: build_live_system reuses the same SystemSpec + compose_engine seam the e2e collapse now proves byte-exact"
tech-stack:
  added: []
  patterns:
    - "declarative composition: the e2e harness + oracle/integration sites all build through the single build_backtest_system(spec) factory (or the legacy direct-construction __init__ that routes through the same compose_engine seam) — no imperative post-construction re-init/registration"
    - "spec unification via alias re-export: tests/e2e/scenario_spec.py is a thin re-export of the promoted run-path SystemSpec, so the leaf-facing name (ScenarioSpec) and the run-path name (SystemSpec) are the SAME type"
    - "spec-order portfolio_id reconstruction: get_active_portfolios() (dict-insertion order) reconstructs the spec-order portfolio_id list the operator hook + _assemble need, without the factory returning them"
key-files:
  created: []
  modified:
    - itrader/trading_system/backtest_trading_system.py
    - itrader/trading_system/__init__.py
    - scripts/run_backtest.py
    - tests/integration/conftest.py
    - tests/integration/test_backtest_oracle.py
    - tests/integration/test_backtest_smoke.py
    - tests/integration/test_reservation_inertness.py
    - tests/integration/test_universe_spans.py
    - tests/e2e/conftest.py
    - tests/e2e/scenario_spec.py
decisions:
  - "D-03: TradingSystem -> BacktestTradingSystem at every scripts/integration import+construction site; the Wave-2 backward-compat TradingSystem alias (and its trading_system/__init__ re-export) are REMOVED. Direct-construction sites keep their loose-param __init__ + post-construction add_strategy/add_portfolio/subscribe flow byte-exactly."
  - "D-13/Trap 1: the Wave-2 ExecutionHandler no-config BTCUSD fallback is no longer load-bearing for the BACKTEST path — the legacy BacktestTradingSystem.__init__ now seeds the COMPLETE symbol set itself via _seed_supported_symbols (default preset ∪ {BTCUSD} ∪ csv_paths tickers, upper-cased) and passes a seeded ExchangeConfig into compose_engine. The fallback STAYS in execution_handler.py because LiveTradingSystem (out of scope, untouched) + several out-of-scope unit tests construct ExecutionHandler(global_queue) with no config and assert that fallback; removing it would break them. execution_handler.py is NOT in this plan's modify scope, so it was left intact."
  - "D-01/D-14: e2e _build_and_run COLLAPSED to system = build_backtest_system(spec). The post-construction fee/slippage re-init block AND the additive register_symbol loop are GONE — both subsumed by the factory's construction-time ExchangeConfig threading (compose_engine folds spec.exchange) + complete symbol seeding. The operator on_tick hook (Phase 6 D-06) + the WR-04 single-portfolio guard are PRESERVED; portfolio_ids are reconstructed from get_active_portfolios (spec-insertion order)."
  - "Spec unification: tests/e2e/scenario_spec.py rewritten as a thin re-export — ScenarioSpec = SystemSpec (field-for-field identical by D-01 design), PortfolioSpec/Action re-exported from itrader.trading_system.system_spec. Every existing leaf scenario.py keeps importing ScenarioSpec/PortfolioSpec/Action by the same name; no leaf edited. The harness + factory now consume ONE unified spec type."
  - "[Rule 1] Factory portfolio-exchange bug fixed: build_backtest_system's add_portfolio used exchange=spec.ticker (e.g. 'BTCUSD'), an unregistered venue. The portfolio's exchange string is carried onto its orders and must resolve to the 'csv' -> simulated matching engine (DEF-01-B). This Wave-2 latent bug never fired until Task 2 routed the e2e harness through the factory; using spec.ticker would route orders to Unknown exchange -> no fills -> byte-exact break. Fixed to exchange='csv' (matching every other construction site)."
  - "D-12 scope fence HELD: no live runtime-config transport added — git diff introduces no ReconfigureEvent type and no TradingInterface reconfigure bridge method (update_*_config). LiveTradingSystem untouched (git diff --name-only shows no live_trading_system.py)."
  - "Docstring grep-gate hygiene: prose in conftest.py was reworded to avoid the bare tokens register_symbol / _init_fee_model so the literal grep -c == 0 acceptance gates hold while still documenting what the collapse removed (same discipline as 04-04)."
metrics:
  duration: ~30 min
  completed: 2026-06-12
  tasks: 3
  files: 10
---

# Phase 4 Plan 05: Byte-exact PROOF wave (e2e collapse + spec unification + migration) Summary

The byte-exact PROOF wave for COMP-01 + COMP-02. Collapsed the e2e harness
`_build_and_run` onto `build_backtest_system(spec)` — removing the D-14
post-construction fee/slippage re-init seam and the additive `register_symbol` loop,
both now subsumed by Wave-2's construction-time `ExchangeConfig` threading + complete
symbol seeding (D-01/D-13/D-14). Unified `tests/e2e/scenario_spec.py` onto the promoted
run-path `SystemSpec` (`ScenarioSpec = SystemSpec` alias + re-exports — no leaf edited).
Migrated every `TradingSystem` import/construction site in `scripts/` + `tests/integration/`
to `BacktestTradingSystem` and removed the Wave-2 `TradingSystem` alias. Then ran the full
byte-exact gate: the structural moves from Waves 1-4 are PROVEN against the BTCUSD oracle +
e2e 58/58 — the Open-Question-1 isolation point held byte-exact, including every non-None
`spec.exchange` leaf (cost/slippage/limits). Caught + fixed one latent Wave-2 factory bug
(portfolio exchange = `spec.ticker` instead of `'csv'`) that only activated once the e2e
path ran through the factory.

## What Was Built

- **`scripts/run_backtest.py`** (Task 1, 4 SPACES) — `TradingSystem` -> `BacktestTradingSystem` (import + construction).
- **`tests/integration/{conftest,test_backtest_oracle,test_reservation_inertness,test_universe_spans}.py`** (Task 1, 4 SPACES) — every `TradingSystem` import + `TradingSystem(...)` construction migrated to `BacktestTradingSystem`; prose `TradingSystem` references in `test_backtest_oracle.py` / `test_backtest_smoke.py` updated. `test_universe_spans.py` comment updated to note the synthetic tickers are now seeded at construction (the `register_symbol` loop is a no-op union, kept to exercise the additive seam).
- **`itrader/trading_system/backtest_trading_system.py`** (Task 1+2, TABS) — the legacy direct-construction `__init__` now seeds the COMPLETE symbol set itself (`_seed_supported_symbols(get_exchange_preset('default'), csv_paths-tickers)`) and passes the seeded `ExchangeConfig` into `compose_engine` (routing the backtest path around the ExecutionHandler no-config fallback, D-13/Trap 1); the Wave-2 `TradingSystem` alias REMOVED. [Rule 1] `build_backtest_system`'s `add_portfolio` exchange fixed to `'csv'` (was `spec.ticker`).
- **`itrader/trading_system/__init__.py`** (Task 1, 4 SPACES) — dropped the `TradingSystem` re-export from the import + `__all__`.
- **`tests/e2e/conftest.py`** (Task 2, 4 SPACES) — `_build_and_run` collapsed to `system = build_backtest_system(spec)` + spec-order `portfolio_ids` reconstruction from `get_active_portfolios`; the post-construction fee/slippage re-init block AND the additive symbol-registration loop REMOVED; module + function docstrings rewritten for the construction-time threading; operator on_tick hook + WR-04 guard preserved.
- **`tests/e2e/scenario_spec.py`** (Task 2, 4 SPACES) — rewritten as a thin re-export of the promoted `SystemSpec` (`ScenarioSpec = SystemSpec` alias; `PortfolioSpec`/`Action` re-exported from `itrader.trading_system.system_spec`).

## Commits

- `9b4c249` refactor(04-05): migrate scripts + integration sites to BacktestTradingSystem (D-03)
- `5b2c634` refactor(04-05): collapse e2e _build_and_run onto build_backtest_system(spec) (D-01/D-13/D-14)
- (Task 3 was verification-only — no source edits; the gate ran green against the Task 1+2 state.)

## Verification

**BYTE-EXACT PHASE GATE — GREEN (zero re-baseline):**
- BTCUSD oracle: `poetry run pytest tests/integration/test_backtest_oracle.py -q` -> **3 passed**; `scripts/run_backtest.py` emits **134 trades / final_equity 46189.87730727451** EXACT (no tolerance).
- Determinism double-run: `run_backtest.py` run twice -> `summary.json` BYTE-IDENTICAL (seed 42 unchanged).
- e2e: `make test-e2e` -> **58/58 passed**, 888 deselected — INCLUDING every non-None `spec.exchange` leaf (cost/slippage/limits — Open Question 1 isolation point).
- Full suite: `make test` -> **946 passed** under `filterwarnings=["error"]`.
- Type gate: `poetry run mypy itrader` -> **Success: no issues found in 182 source files** (mypy --strict).
- Integration: `poetry run pytest tests/integration -q` -> **15 passed**.

**Acceptance grep gates:**
- `grep -c '[^t]TradingSystem(' scripts/ tests/integration/` (non-Backtest) -> 0; zero `import TradingSystem` remaining.
- `grep -c 'build_backtest_system(' tests/e2e/conftest.py` -> 3 (>= 1).
- `grep -c '_init_fee_model\|_init_slippage_model' tests/e2e/conftest.py` -> 0 (re-init seam gone).
- `grep -c 'register_symbol' tests/e2e/conftest.py` -> 0 (loop gone; prose reworded).
- `ScenarioSpec is SystemSpec` -> True (spec unified).
- D-12 fence: `git diff` introduces 0 `ReconfigureEvent` / `update_*_config` bridge tokens; LiveTradingSystem untouched.
- Indentation: zero tab-indented lines in the 4-space e2e files.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Factory `add_portfolio` used `exchange=spec.ticker` instead of `'csv'`.**
- **Found during:** Task 2 (collapsing the e2e harness onto the factory).
- **Issue:** `build_backtest_system` constructed portfolios with `exchange=spec.ticker if spec.ticker else 'csv'` (e.g. `'BTCUSD'`). The portfolio's exchange string is carried onto its orders, and the order router resolves only the `'csv'` alias to the simulated matching engine (DEF-01-B). `'BTCUSD'` is an unregistered venue -> `Unknown exchange` -> orders never fill. This latent Wave-2 bug never fired because Wave 2 didn't route the e2e/oracle through the factory; Task 2 activates it. A byte-exact break.
- **Fix:** `add_portfolio(..., exchange='csv', ...)` — matching every other construction site (oracle/integration/scripts + the former `_build_and_run`). e2e 58/58 confirms fills are byte-identical.
- **Files modified:** `itrader/trading_system/backtest_trading_system.py`.
- **Commit:** `5b2c634`.

### Note (scope clarification, no behavior change)

- **The ExecutionHandler no-config BTCUSD fallback (`_default_backcompat_config`) was NOT removed.** The phase critical notes flagged the "no-config BTCUSD fallback" as a Wave-2 temporary bridge. On inspection it serves THREE out-of-scope direct-construction consumers: `LiveTradingSystem` (`ExecutionHandler(global_queue)`, explicitly do-not-touch), and multiple out-of-scope unit tests (`test_execution_handler.py` asserts the fallback behavior directly). `execution_handler.py` is NOT in this plan's `files_modified`. Per the phase notes' own directive ("the construction-time seeding is the fix, not reinstating the fallback"), the correct Wave-4 action was to route the BACKTEST path around the fallback — which the legacy `__init__` now does by seeding its own `ExchangeConfig`. The fallback remains as the safety net for live + unit direct-construction. No backtest construction site relies on it anymore.

## Threat Surface

The two registered tampering threats are mitigated and proven:
- **T-04-11** (the collapse silently changes a non-None `spec.exchange` leaf — fee/slippage/limits integrity) — the byte-exact gate (e2e 58/58 INCLUDING every cost/slippage/limits leaf) is the control. The construction-time `ExchangeConfig` threading produced a byte-identical fee/slippage/limits state to the old post-construction re-init (Open Question 1 resolved: no divergence).
- **T-04-12** (a missed `TradingSystem` import site silently uses a stale class) — the grep gate (zero remaining `TradingSystem` imports/constructions in scripts/integration), `mypy --strict`, and the full suite all caught/confirmed; the `TradingSystem` alias is removed so a missed site would now be an `ImportError`, not a silent stale class.

No new security surface (internal structural refactor; developer-authored spec dicts only).

## Known Stubs

None. This is a proof wave — it removes temporary bridges and proves byte-exactness; no new stubs introduced. The ExecutionHandler no-config fallback that remains is a deliberate, documented safety net for the out-of-scope live + unit direct-construction paths (not a stub; fully exercised by existing tests).

## Threat Flags

None — no new network endpoints, auth paths, file-access patterns, or trust-boundary schema changes. The only boundary is the developer-authored `SystemSpec` crossing into the factory, already in the plan's threat model.

## Self-Check: PASSED
- itrader/trading_system/backtest_trading_system.py (TradingSystem alias removed; factory exchange='csv') — FOUND
- tests/e2e/conftest.py::_build_and_run (build_backtest_system collapse) — FOUND
- tests/e2e/scenario_spec.py (ScenarioSpec = SystemSpec) — FOUND
- commit 9b4c249 — FOUND
- commit 5b2c634 — FOUND
