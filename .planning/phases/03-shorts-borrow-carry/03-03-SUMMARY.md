---
phase: 03-shorts-borrow-carry
plan: 03
subsystem: strategy-registration
tags: [shorts, registration-gate, two-flag, D-07, SHORT-01, oracle-byte-exact]
requires:
  - "config/portfolio.py TradingRules (allow_short_selling/enable_margin flags, already present)"
  - "tests/unit/strategy/test_strategies_handler_registration.py (Wave-0 short_registration stub)"
provides:
  - "StrategiesHandler.__init__ two-flag params (allow_short_selling/enable_margin, default off)"
  - "add_strategy two-flag registration gate (non-LONG_ONLY admitted only when both flags on)"
  - "compose.py + live_trading_system.py flag threading from trading_rules at construction"
affects:
  - "Plan 03-04+ short execution path (registration door now opens under both flags)"
tech-stack:
  added: []
  patterns:
    - "two-flag config gate read at construction, never mutated in the handler"
    - "construction reorder: StrategiesHandler built AFTER the trading_rules binding"
key-files:
  created: []
  modified:
    - itrader/strategy_handler/strategies_handler.py
    - itrader/trading_system/compose.py
    - itrader/trading_system/live_trading_system.py
    - tests/unit/strategy/test_strategies_handler_registration.py
    - tests/unit/strategy/test_strategy.py
decisions:
  - "D-07 two-flag gate: non-LONG_ONLY admitted ONLY when allow_short_selling AND enable_margin both on; either off raises ValueError naming both flags"
  - "enable_margin coupled into the gate because it turns on the lock-and-settle model (Phase 2 D-09) — the only model that can represent a short"
  - "Both flags default off → SMA_MACD (LONG_ONLY) unaffected; oracle byte-exact 134 / 46189.87730727451"
metrics:
  duration: ~12m
  completed: 2026-06-15
---

# Phase 3 Plan 03: Two-Flag Short Registration Gate Summary

Relaxed the `StrategiesHandler.add_strategy` `LONG_ONLY`-only guard into a two-flag gate (SHORT-01/D-07): a `SHORT_ONLY`/`LONG_SHORT` strategy is admitted only when both `allow_short_selling` AND `enable_margin` are on, threaded from `trading_rules` at construction in both composition roots; both flags default off so the golden SMA_MACD path stays byte-exact (134 / `46189.87730727451`).

## What Was Built

**Task 1 — two-flag gate in `strategies_handler.py` (commits `8b832a1` RED, `dbed733` GREEN):**
- Implemented the Wave-0 `short_registration` stub as 5 real tests (`test_strategies_handler_registration.py`): both-flags-on admits `SHORT_ONLY` and `LONG_SHORT`; either flag off raises `ValueError` naming both flags; default-off keeps `LONG_ONLY` admitted while rejecting `SHORT_ONLY`. Test names embed `short_registration` so the plan's `-k short_registration` selector resolves to all 5 (Nyquist contract, no silent green).
- `StrategiesHandler.__init__` gained `allow_short_selling: bool = False` and `enable_margin: bool = False`, stored as `self._allow_short_selling` / `self._enable_margin` (defaults keep every existing caller/test working).
- `add_strategy` replaced the unconditional `if direction is not LONG_ONLY: raise` with: admit a non-`LONG_ONLY` direction only when `self._allow_short_selling and self._enable_margin`; otherwise raise a `ValueError` naming BOTH flags. The `LONG_ONLY` path is unchanged. Updated the `Raises` docstring and the inline guard comment to the D-07 two-flag relaxation (cite enable_margin → lock-and-settle model; fully-collateralized shorts by default, levered shorts a separate opt-in).

**Task 2 — construction-time wiring (commit `a8a4e25`):**
- `compose.py`: moved the `StrategiesHandler(...)` construction to AFTER the existing `trading_rules = portfolio_handler.config_data.trading_rules` binding (the binding lived below the original construction site), then threaded `allow_short_selling=trading_rules.allow_short_selling` and `enable_margin=trading_rules.enable_margin`. `strategies_handler` is first consumed by `EventHandler` further down, so the reorder is safe.
- `live_trading_system.py`: same pattern — moved `self.strategies_handler = StrategiesHandler(...)` to after the `_trading_rules` binding and threaded the two flags. First consumed by `EventHandler` below, so safe.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Realigned two pre-existing registration-rejection tests to the new D-07 message**
- **Found during:** Task 1 (running the full `tests/unit/strategy/` suite after the guard change)
- **Issue:** `test_strategy.py::test_long_short_registration_rejected` and `::test_short_only_registration_rejected` asserted `pytest.raises(ValueError, match="Only LONG_ONLY is admissible")` — the OLD guard wording my task legitimately replaced. They were directly affected by the in-scope guard change (the handler is still built default-off, so the rejection behavior holds — only the message changed).
- **Fix:** Updated both `match=` strings to `"allow_short_selling AND enable_margin"` and refreshed their docstrings to cite SHORT-01/D-07. Behavior asserted is unchanged (default-off → loud rejection).
- **Files modified:** `tests/unit/strategy/test_strategy.py`
- **Commit:** `dbed733`

## Authentication Gates

None.

## Verification

- `poetry run pytest tests/unit/strategy/test_strategies_handler_registration.py -q -k short_registration` → 5 passed (selector resolves; stub turned green).
- `poetry run pytest tests/unit/strategy/` → 94 passed (no regression from the `__init__` signature change).
- `poetry run pytest tests/integration` → 16 passed, including all 3 backtest-oracle tests (trade_count pinned exact; golden-frame equity comparison) — SMA_MACD byte-exact 134 / `46189.87730727451`.
- `poetry run mypy --strict itrader/strategy_handler/strategies_handler.py itrader/trading_system/compose.py itrader/trading_system/live_trading_system.py` → Success, 3 source files.

## Known Stubs

None — the only stub touched (`short_registration`) was implemented and turned green.

## TDD Gate Compliance

RED gate: `test(03-03)` commit `8b832a1` (5 failing tests, failing for the right reason — `__init__` rejected the new kwargs). GREEN gate: `feat(03-03)` commit `dbed733` (implementation, tests pass). No REFACTOR needed.

## Self-Check: PASSED

- `itrader/strategy_handler/strategies_handler.py` — modified, present.
- `itrader/trading_system/compose.py` — modified, present.
- `itrader/trading_system/live_trading_system.py` — modified, present.
- `tests/unit/strategy/test_strategies_handler_registration.py` — modified, present.
- Commits `8b832a1`, `dbed733`, `a8a4e25` — all present in `git log`.
