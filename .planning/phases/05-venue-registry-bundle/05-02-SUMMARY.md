---
phase: 05-venue-registry-bundle
plan: 02
subsystem: execution / universe / core-money
tags: [venue-precision, abstract-exchange, money-policy, universe-handler, D-09, VENUE-04]
requires:
  - "05-01 (StreamSupervisor delegation on OkxExchange — not regressed)"
provides:
  - "AbstractExchange.resolve_precision capability (base.py Protocol)"
  - "OkxExchange.resolve_precision (loaded-markets precision -> Instrument)"
  - "SimulatedExchange.resolve_precision (None sensible default)"
  - "core/money.py::precision_to_scale (shared, public money util)"
affects:
  - "universe_handler binds precision on the exchange capability (resolve_precision)"
  - "live_trading_system wiring passes the exchange directly to set_precision_resolver"
tech-stack:
  added: []
  patterns:
    - "Venue capability on the AbstractExchange Protocol (beside validate_symbol)"
    - "TYPE_CHECKING import for Protocol return-type Instrument (keeps modules import-lean)"
key-files:
  created:
    - tests/unit/execution/test_precision.py
  modified:
    - itrader/core/money.py
    - itrader/execution_handler/exchanges/base.py
    - itrader/execution_handler/exchanges/okx.py
    - itrader/execution_handler/exchanges/simulated.py
    - itrader/universe/universe_handler.py
    - itrader/trading_system/live_trading_system.py
    - tests/unit/core/test_money.py
    - tests/unit/universe/test_universe_poll.py
decisions:
  - "precision_to_scale relocated to core/money.py as a shared public util (D-04 string entry preserved); core/money.py stays import-inert"
  - "resolve_precision is an AbstractExchange capability (D-09): OkxExchange reads its markets map; SimulatedExchange returns None"
  - "_PrecisionResolver Protocol replaced by _SupportsResolvePrecision (resolve_precision); the exchange itself is the bound object"
metrics:
  duration: ~6m
  completed: 2026-07-12
  tasks: 3
  commits: 3
  files-created: 1
  files-modified: 8
status: complete
---

# Phase 5 Plan 02: Venue Precision as an AbstractExchange Capability Summary

Made precision a first-class `AbstractExchange.resolve_precision` capability (VENUE-04 / D-09): relocated `_precision_to_scale` into `core/money.py` as the shared public `precision_to_scale` util, implemented `resolve_precision` on `OkxExchange` (from the loaded-markets map) and `SimulatedExchange` (None default), deleted the two LTS resolvers plus the universe `_PrecisionResolver` Protocol, and rewired the universe handler + LTS wiring to bind precision directly on the exchange — with both standing gates (oracle byte-exact, OKX inertness) green.

## What Was Built

- **Task 1 — `precision_to_scale` in `core/money.py`** (`39a54314`): moved the venue-precision→Decimal-scale converter verbatim (None/InvalidOperation/ValueError → None; non-positive → None; integer DECIMAL_PLACES → `1e-n`; else the tick-size Decimal), made it public via `__all__`, kept the D-04 string entry (`Decimal(str(value))`, never `Decimal(float)`). `core/money.py` stays import-inert. Extended `test_money.py` with 6 behavior cases.
- **Task 2 — `resolve_precision` capability** (`89e8bdc9`): declared on the `AbstractExchange` Protocol (`base.py`, beside `validate_symbol`); implemented on `OkxExchange` reading `_connector.client.markets[key]['precision']` via `_to_symbol` normalization → an `Instrument` carrying Decimal scales (returns None on cold/absent/unusable markets — never raises, T-05-06); implemented on `SimulatedExchange` as `return None` (D-09 sensible default). New `tests/unit/execution/test_precision.py` (7 cases: tick-size, DECIMAL_PLACES, cold-markets None, absent-symbol None, unusable-entry None, Simulated None, Protocol isinstance).
- **Task 3 — rewire + delete resolvers** (`45c62325`): replaced the universe `_PrecisionResolver` Protocol with `_SupportsResolvePrecision` (bound on `resolve_precision`), retyped the field/setter, changed `resolver.resolve(sym)` → `resolver.resolve_precision(sym)`; deleted `_OkxPrecisionResolver` + `_precision_to_scale` from `live_trading_system.py`; rewired the wiring site to `set_precision_resolver(self._okx_exchange)` with the `if self._okx_exchange is not None:` D-10 None-guard preserved; dropped now-dead `InvalidOperation`/`Instrument` imports; updated the universe test's fake resolver to expose `resolve_precision`.

## Verification Results

- `poetry run pytest tests/unit/core tests/unit/execution tests/unit/universe -q` → **499 passed**.
- `poetry run mypy --strict itrader/universe/universe_handler.py itrader/trading_system/live_trading_system.py itrader/core/money.py` → **clean**; also clean on the three edited exchange files.
- Acceptance greps: LTS `_OkxPrecisionResolver|_precision_to_scale` = **0**; universe `_PrecisionResolver` = **0**; universe `.resolve(` on the added path = **0**.
- **Standing gates**: `test_backtest_oracle.py` (byte-exact `46189.87730727451`) + `test_okx_inertness.py` + `test_import_quarantine.py` → **7 passed**. Oracle byte-exact (backtest never reaches `resolve_precision` — live-only capability); `core/money.py` stays SQL/ccxt-free.
- D-10 None-guard preserved at wiring (`live_trading_system.py:1367` / `:1373`).

## Deviations from Plan

**1. [Rule 1 - Bug] Updated `_FakeResolver` in `tests/unit/universe/test_universe_poll.py`**
- **Found during:** Task 3 (targeted test run)
- **Issue:** the pre-existing `test_on_poll_added_symbol_takes_resolver_precision` test's `_FakeResolver` exposed the old `resolve` method name; rewiring the interface to `resolve_precision` broke it (directly caused by this plan's contract rename — in scope).
- **Fix:** renamed the fake's method `resolve` → `resolve_precision` to match the rewired `_SupportsResolvePrecision` bound.
- **Files modified:** tests/unit/universe/test_universe_poll.py
- **Commit:** 45c62325

## Threat Surface

No new threat surface beyond the plan's `<threat_model>`. Mitigations applied as specified:
- T-05-05 (Tampering, Decimal entry): `precision_to_scale` keeps string-entry discipline and returns None on non-positive/unparseable/missing entries.
- T-05-06 (DoS, cold markets): `OkxExchange.resolve_precision` returns None (never raises) on non-dict markets / absent symbol.

## Self-Check: PASSED

- Created file exists: `tests/unit/execution/test_precision.py` — FOUND.
- Commits exist: `39a54314`, `89e8bdc9`, `45c62325` — all FOUND in git log.
