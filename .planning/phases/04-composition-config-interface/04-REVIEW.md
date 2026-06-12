---
phase: 04-composition-config-interface
reviewed: 2026-06-12T00:00:00Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - itrader/config/__init__.py
  - itrader/config/merge.py
  - itrader/config/order.py
  - itrader/core/commission_estimator.py
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/execution_handler/execution_handler.py
  - itrader/order_handler/order_handler.py
  - itrader/order_handler/order_manager.py
  - itrader/portfolio_handler/portfolio.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/price_handler/feed/bar_feed.py
  - itrader/reporting/summary.py
  - itrader/strategy_handler/strategies_handler.py
  - itrader/trading_system/__init__.py
  - itrader/trading_system/backtest_runner.py
  - itrader/trading_system/backtest_trading_system.py
  - itrader/trading_system/compose.py
  - itrader/trading_system/system_spec.py
findings:
  critical: 0
  warning: 0
  info: 0
  total: 0
status: clean
---

# Phase 4: Code Review Report (Re-review)

**Reviewed:** 2026-06-12
**Depth:** standard
**Files Reviewed:** 18
**Status:** clean

## Summary

Re-review of Phase 4 (composition / config / interface) after the 7 findings from
the prior review were fixed in commits `96494c1..e8e0061` (one commit per finding).

All 7 fixes were verified at the source and in surrounding context, and were
cross-checked against `mypy --strict` (clean over the 5 changed source files) and
the unit suite (504 passed across `tests/unit/execution`, `tests/unit/order`,
`tests/unit/portfolio`). No new issues were introduced.

### Verification of prior findings

- **WR-01** (`failure_rate` float cache, `simulated.py:81/650`) — RESOLVED by the
  documented-exception route (commit `96494c1`). Inline comments at both the
  `__init__` and `update_config` cache sites now explain the float cast as an
  intentional probability-boundary edge (compared against `self._rng.random()`,
  a native float), analogous to the float() serialization edges. The value is
  still re-derived in `update_config`, so no staleness after reconfigure. Correct.
- **WR-02** (`order_value < 1.0` Decimal-vs-float, `simulated.py:412`) — RESOLVED
  (commit `82a6f75`). Now `order_value < Decimal("1")`. `Decimal` is imported at
  module top (line 3); the comparison is now Decimal-vs-Decimal. Correct.
- **WR-03** (false `TradingSystem` backward-compat alias claim, docstring) —
  RESOLVED (commit `a7a9103`). Docstring corrected to state Wave 4 migrated all
  sites and no alias is exported. Grep confirms no `TradingSystem` alias import
  exists anywhere in `itrader/`, `tests/`, or `scripts/`, so the docstring now
  matches reality. Correct.
- **WR-04** (dead `steps` param on `rollback_config`, `portfolio_handler.py:484`)
  — RESOLVED (commit `a308868`). Signature is now `rollback_config(self) -> bool`.
  Grep confirms no caller passed `steps`, so removal is non-breaking. Correct.
- **IN-01** (`print()` in `BacktestRunner`, `backtest_runner.py:111`) — RESOLVED
  (commit `213b4a6`). Now `self.logger.info('Backtest completed',
  duration_seconds=duration.total_seconds())`. No `print(` remains in the file.
  Correct.
- **IN-02** (stray `)` / f-string log in `OrderHandler`, `order_handler.py:93`) —
  RESOLVED (commit `b717b2b`). Now `self.logger.info('Order Handler initialized',
  market_execution=self.market_execution)` — structlog kwargs, no stray paren.
  Correct.
- **IN-03** (redundant double-connect log for `csv` alias,
  `execution_handler.py:163-181`) — RESOLVED (commit `e8e0061`). The connect loop
  now dedups by `id(exchange)` via a `seen_connect: set[int]`, matching the
  pattern already used in `on_market_data`. `connect()` is still invoked once on
  the shared instance; only `'simulated'` logs and `'csv'` is silently skipped,
  which is the intended dedup behavior. No behavioral regression. Correct.

### New-issue scan

The fix sites and their neighbors were re-read for regressions introduced by the
changes. None found:

- The IN-03 dedup correctly skips `None` entries first (`exchange is None or
  id(exchange) in seen_connect`), preserving the `'ccxt': None` skip. `id()`
  reuse across the loop is not a hazard — all exchange objects are held live in
  the `exchanges` dict for the loop's duration, so no id collision from a
  garbage-collected object is possible.
- The WR-01 comments accurately describe the runtime: `failure_rate` is only ever
  compared against `self._rng.random()` (float), never used in money math.
- The WR-02 `Decimal("1")` comparison is exact and does not depend on decimal
  context flags; both operands are now `Decimal`.

No correctness bugs, security vulnerabilities, or data-loss risks were found.
All prior findings are resolved and no new findings were introduced.

---

_Reviewed: 2026-06-12_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
