---
status: complete
phase: quick-260610-sjp
plan: 01
subsystem: portfolio-handler / events / order-handler
tags: [exception-migration, type-annotation, fix-list, behavior-preserving]
requires: []
provides:
  - "Typed domain exceptions at the 7 former portfolio.py ValueError sites (FL-01)"
  - "portfolio_id: PortfolioId on Signal/Order/Fill event facts + Order entity (FL-02)"
  - "FIX-LIST.md FL-01..FL-04 status reconciled"
affects:
  - itrader/portfolio_handler/portfolio.py
  - itrader/events_handler/events/{signal,order,fill}.py
  - itrader/order_handler/{order,order_manager,order_validator}.py
  - itrader/strategy_handler/strategies_handler.py
tech-stack:
  added: []
  patterns: ["typed domain exceptions over bare ValueError", "NewType PortfolioId end-to-end on the event chain"]
key-files:
  created: []
  modified:
    - itrader/portfolio_handler/portfolio.py
    - itrader/events_handler/events/signal.py
    - itrader/events_handler/events/order.py
    - itrader/events_handler/events/fill.py
    - itrader/order_handler/order.py
    - itrader/order_handler/order_manager.py
    - itrader/order_handler/order_validator.py
    - itrader/strategy_handler/strategies_handler.py
    - tests/unit/portfolio/test_portfolio_handler.py
    - .planning/codebase/FIX-LIST.md
decisions:
  - "FL-01 site-by-site mapping: ValidationError (cash/name construction), StateError (state transitions / transact guard), ConfigurationError (unknown config key), PortfolioError (limit breaches)"
  - "FL-02 entity tightened (order.py:55 PortfolioId|int -> PortfolioId) because mypy --strict demanded it after the event retype — per plan §5, not pre-emptive"
metrics:
  duration: ~25min
  completed: 2026-06-10
---

# Phase quick-260610-sjp Plan 01: Close FL-01 / FL-02 Summary

Replaced 7 bare `ValueError` sites in `portfolio.py` with per-condition typed domain
exceptions (FL-01), retyped `portfolio_id` from `int` to the UUIDv7-backed `PortfolioId`
NewType across the Signal/Order/Fill event facts and the propagated downstream seams
(FL-02), and reconciled the FIX-LIST.md ledger — all behavior-preserving (BTCUSD oracle
byte-exact, mypy --strict clean).

## Tasks Completed

| Task | Name | Commit | Files |
| ---- | ---- | ------ | ----- |
| 1 | FL-01 — 7 ValueError sites -> typed exceptions | `1cc9b76` | portfolio.py |
| 2 | FL-02 — portfolio_id int -> PortfolioId on event facts | `8e9a4e7` | signal/order/fill.py, order.py, order_manager.py, order_validator.py, strategies_handler.py |
| 3 | Reconcile FIX-LIST.md + align portfolio tests | `4db1907` | FIX-LIST.md, test_portfolio_handler.py |

## FL-01 exception mapping (per-site)

| portfolio.py site | Former | Now |
| ----------------- | ------ | --- |
| `:101` negative starting cash | `ValueError` | `ValidationError("cash", ...)` |
| `:103` empty name | `ValueError` | `ValidationError("name", message=...)` |
| `:124` invalid state transition (`set_state`) | `ValueError` | `StateError(portfolio_id, state, required_state, "set_state")` |
| `:183` unknown config key | `ValueError` | `ConfigurationError(config_key, reason=...)` |
| `:410` cannot trade (`transact_shares`) | `ValueError` | `StateError(portfolio_id, state, ACTIVE, "transact_shares")` |
| `:431` max positions limit | `ValueError` | `PortfolioError(...)` |
| `:436` transaction value exceeds limit | `ValueError` | `PortfolioError(...)` |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] order.py:55 entity tightened (plan-anticipated)**
- **Found during:** Task 2, after the event retype
- **Issue:** `mypy --strict` reported `Argument "portfolio_id" to "SignalEvent" has
  incompatible type "int"` at strategies_handler.py:152 plus 4 redundant-cast errors in
  order_manager.py, then 6 more redundant-cast errors (order_manager + order_validator)
  once the Order entity was tightened.
- **Fix:** Per plan §5, tightened `Order.portfolio_id` from `"PortfolioId | int"` to
  `PortfolioId` and removed the stale 02-05 carry-over comment. Cascaded the now-required
  cleanups: dropped 6 redundant `cast(PortfolioId, ...)` bridges in order_manager.py,
  simplified `_portfolio_id` in order_validator.py to a direct pass-through (removed the
  unused `cast` import), and changed the strategies_handler construction-site bridge from
  `cast(int, portfolio_id)` to `cast(PortfolioId, portfolio_id)` (adding the `PortfolioId`
  import). All annotation-only and behavior-preserving — runtime values were already UUIDs.
- **Files modified:** itrader/order_handler/order.py, order_manager.py, order_validator.py,
  itrader/strategy_handler/strategies_handler.py
- **Commit:** `8e9a4e7`
- **Note:** `cancel_order(...)`'s legacy `cast(int, order.portfolio_id)` seam at
  order_manager.py:224 was intentionally left untouched (IN-06 deferred; mypy did not flag it).

**2. [Rule 1 - Test alignment] Two portfolio tests asserted the old ValueError**
- **Found during:** Task 3 behavior-preservation gate
- **Issue:** `test_portfolio_state_management` and `test_fill_event_processing_inactive_portfolio`
  asserted `pytest.raises(ValueError)` against the two `set_state`/`transact` sites that FL-01
  retyped to `StateError` (which is NOT a `ValueError` subclass), so they failed.
- **Fix:** Updated both `pytest.raises(ValueError)` to `pytest.raises(StateError)` (added the
  `StateError` import). These tests verify the exact behavior FL-01 introduces.
- **Files modified:** tests/unit/portfolio/test_portfolio_handler.py
- **Commit:** `4db1907`
- **Out-of-scope left alone:** `test_simulated_exchange.py:174` asserts
  `ValueError("Unknown configuration key")` against the *exchange's* `update_config`
  (simulated.py:591), a separate site outside FL-01's portfolio.py scope.

## Verification Results

- `grep -c 'raise ValueError' itrader/portfolio_handler/portfolio.py` -> **0**
- `mypy --strict itrader/` -> **Success: no issues found in 161 source files**
- Oracle `tests/integration/test_backtest_oracle.py` -> **3 passed (byte-exact)**
- Full unit suite -> **743 passed** (no warnings; filterwarnings=["error"] satisfied)
- FIX-LIST.md: FL-01/FL-02 = `done (quick 260610-sjp)`, FL-03 = `done (phase 4)`,
  FL-04 = `done (phase 5)`; FL-05..FL-14 untouched.
- No float introduced; money stays Decimal. Indentation matched per file (portfolio.py /
  order.py / order_manager.py TABS; the 3 event files 4 SPACES).

## Self-Check: PASSED

- portfolio.py, signal.py, order.py (event), fill.py, order.py (entity), order_manager.py,
  order_validator.py, strategies_handler.py, test_portfolio_handler.py, FIX-LIST.md — all present and modified.
- Commits `1cc9b76`, `8e9a4e7`, `4db1907` all exist in git log.
