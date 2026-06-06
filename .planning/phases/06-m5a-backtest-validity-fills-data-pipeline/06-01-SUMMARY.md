---
phase: 06-m5a-backtest-validity-fills-data-pipeline
plan: 01
subsystem: events
tags: [bar-struct, decimal, barevent, m5-02, fr1, inert-cutover]
requires: []
provides:
  - "itrader/core/bar.py — frozen/slots/kw_only Bar value object with Decimal OHLCV + from_row"
  - "BarEvent.bars: dict[str, Bar] payload (absent key = no bar at T)"
  - "shared make_bar / make_bar_struct / make_bar_event factory fixtures in tests/conftest.py"
affects: [06-03, 06-04, 06-05]
tech-stack:
  added: []
  patterns:
    - "Decimal(str(x)) string-path entry at the bar boundary (D-14)"
    - "event = fact, feed = query (D-15): BarEvent carries one Bar per ticker, no history"
key-files:
  created:
    - itrader/core/bar.py
    - tests/unit/core/test_bar.py
  modified:
    - itrader/events_handler/events/market.py
    - itrader/strategy_handler/base.py
    - itrader/execution_handler/matching_engine.py
    - itrader/portfolio_handler/portfolio_handler.py
    - itrader/portfolio_handler/portfolio.py
    - itrader/portfolio_handler/position/position_manager.py
    - itrader/universe/dynamic.py
    - tests/conftest.py
    - tests/unit/order/test_stop_limit_orders.py
    - tests/unit/execution/test_matching_engine.py
    - tests/unit/execution/exchanges/test_simulated_exchange.py
    - tests/unit/portfolio/test_portfolio_update.py
    - tests/unit/events/test_bar_event_ohlc.py
    - tests/unit/events/test_events.py
    - tests/unit/events/test_event_immutability.py
    - tests/unit/strategy/test_strategy.py
    - tests/integration/test_execution_handler_routing.py
decisions:
  - "Plan 06-01: shared bar helpers exposed as pytest factory fixtures (make_bar/make_bar_struct/make_bar_event) in tests/conftest.py — tests/ is not an importable package, so fixture injection replaces module-level helper imports"
  - "Plan 06-01: market-value path annotations widened to Mapping[str, float | Decimal] (covariant) so Decimal Bar closes type-check without runtime change (Rule 3)"
metrics:
  duration: "15 min"
  tasks: 2
  files: 19
  completed: 2026-06-06
---

# Phase 6 Plan 01: Bar Value Object + BarEvent Cutover Summary

Immutable Decimal `Bar` struct replaces the per-tick pandas-Series payload: `BarEvent.bars` is now `dict[str, Bar]`, the four `get_last_*` hasattr ladders are deleted, and all consumers read `bars[ticker].field` directly — proven inert by a byte-exact oracle run.

## What Was Built

### Task 1 — `itrader/core/bar.py` (commit 8e4faa9)
- `@dataclass(frozen=True, slots=True, kw_only=True) class Bar` with `time` (open-time stamp, D-04) and Decimal `open/high/low/close/volume` (D-14).
- `Bar.from_row(time, row)` converts each field once via `Decimal(str(x))` — byte-identical to the legacy `to_money(float)` path (the D-21 inertness argument). No `quantize` call exists in the module (prices/quantities are never rounded to the cash quantum).
- `tests/unit/core/test_bar.py` (6 tests): kwargs construction, float64-Series `from_row` string-path equality, open-time stamping, micro-price exactness (`Decimal("0.000005")` by `==`), `FrozenInstanceError` on assignment, slots rejection of unknown attributes.
- `mypy --strict` clean with no new override.

### Task 2 — BarEvent redesign + consumer collapse + 9-test-file conversion in ONE commit (bec7eba)
- `events/market.py`: `BarEvent.bars: dict[str, Bar]`; `get_last_close/open/high/low` DELETED (FR1); docstring rewritten to the payload contract (one immutable Bar per ticker, absent key = no bar at T, history from the Feed per D-15); pandas import gone from the events package.
- `strategy_handler/base.py`: `bars.get(ticker)` membership guard replaces the WR-12 Optional accessor (same log message); `to_money(bar.close)` is now value-identity on Decimal — D-22 boundary comment updated.
- `matching_engine.py`: `bar.bars.get(ticker)` with same no-data semantics; engine internals stay float via three inert `float(bar_struct.x)` casts, each tagged `# D-12: removed in plan 06-04`.
- `portfolio_handler.py` / `portfolio.py`: close-marked equity (D-05) reads `bar.close` (Decimal) directly off the dict items; downstream `Position.update_current_price_time` enters via `to_money` (identity on Decimal).
- `universe/dynamic.py`: temporary bridge builds `Bar.from_row(time_event.time, series)` from `price_handler.get_bar`; `None` (the FR7 bare-except path, fixed in 06-02/06-05) leaves the ticker ABSENT from the payload; last_bar caching and queue-put shape kept.
- `tests/conftest.py`: shared `_bar_struct`/`_bar_event` helpers + `make_bar`, `make_bar_struct`, `make_bar_event` factory fixtures keeping the legacy positional `(open_, high, low, close)` signature.
- All 9 BarEvent-constructing test files converted to `dict[str, Bar]` payloads; `test_bar_event_ohlc.py` rewritten as payload tests (Decimal fields, absent-key contract, frozen event AND frozen payload struct, accessor-deletion regression); `test_event_immutability.py` now covers the `bars` field and the inner Bar.

## Verification Evidence

- `make test`: **513 passed** (full suite green in the same commit as the BarEvent change — Pitfall 9 satisfied).
- `make typecheck` (`mypy itrader`): **clean, 136 files** (bar.py strict-clean, no new override).
- Oracle tripwire (D-21): `tests/integration/test_backtest_oracle.py` — **both `test_oracle_behavioral_identity` and `test_oracle_numeric_values` pass unmodified, byte-exact**. The workstream is proven inert.
- Acceptance grep: zero `get_last_(close|open|high|low)` matches under `itrader/events_handler/`, `strategy_handler/base.py`, `execution_handler/matching_engine.py`, `portfolio_handler/portfolio{,_handler}.py`, `universe/`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Widened market-value annotations to `Mapping[str, float | Decimal]`**
- **Found during:** Task 2 (`make typecheck` gate)
- **Issue:** `Portfolio.update_market_value_of_portfolio(prices: Dict[str, float])` and `PositionManager.update_position_market_values(price_data: Dict[str, float])` rejected the now-Decimal close prices (`dict` invariance also rejects `dict[str, Decimal]` against a union-valued `dict`).
- **Fix:** Parameters retyped to covariant `Mapping[str, float | Decimal]` — annotation-only, zero runtime change; the runtime path already enters via `to_money` (MoneyInput).
- **Files modified:** `itrader/portfolio_handler/portfolio.py`, `itrader/portfolio_handler/position/position_manager.py` (the latter not in the plan's file list)
- **Commit:** bec7eba

No other deviations — plan executed as written.

## Notes for Downstream Plans

- Plans 06-03/06-04/06-05 can import `itrader.core.bar.Bar` exactly per the interfaces block; the three `# D-12: removed in plan 06-04` float casts in `matching_engine._evaluate` mark the retype sites.
- `universe/dynamic.py` `generate_bar_event` is an explicitly-tagged TEMPORARY bridge for 06-05 (`feed.current_bars(T)`).
- `portfolio_handler.update_portfolios_market` (the legacy "backward compatible" method at ~:353) still probes `close_price` via `getattr` — it was equally dead against DataFrames and remains untouched (out of scope; the live path is `update_portfolios_market_value`).

## Known Stubs

None — no placeholder values or unwired data paths introduced.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or trust-boundary schema changes. `Bar.from_row` is the T-06-01 mitigation as planned (string-path enforcement + micro-price test; no `Decimal(float)` and no `quantize` in `bar.py`).

## Self-Check: PASSED

- itrader/core/bar.py: FOUND
- tests/unit/core/test_bar.py: FOUND
- 06-01-SUMMARY.md: FOUND
- Commit 8e4faa9 (Task 1): FOUND
- Commit bec7eba (Task 2): FOUND
