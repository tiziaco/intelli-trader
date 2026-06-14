---
phase: 04-composition-config-interface
fixed_at: 2026-06-12T00:00:00Z
review_path: .planning/phases/04-composition-config-interface/04-REVIEW.md
iteration: 1
findings_in_scope: 7
fixed: 7
skipped: 0
status: all_fixed
---

# Phase 4: Code Review Fix Report

**Fixed at:** 2026-06-12
**Source review:** .planning/phases/04-composition-config-interface/04-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 7 (4 Warning + 3 Info — fix_scope=all)
- Fixed: 7
- Skipped: 0

**Verification:**
- Full test suite: `946 passed` (`PYTHONPATH=$PWD poetry run pytest tests/ -q`)
- Targeted suites (execution/order/portfolio): `504 passed`
- Integration backtest oracle + smoke tests: passing (backtest path still produces correct, deterministic numbers)
- mypy `--strict` on all 6 affected modules: `Success: no issues found in 6 source files`

## Fixed Issues

### WR-01: `failure_rate` cached as `float` — inconsistent with Decimal-first policy

**Files modified:** `itrader/execution_handler/exchanges/simulated.py`
**Commit:** 96494c1
**Applied fix:** Kept the existing `float()` cast (it is compared directly against `self._rng.random()`, a native float) but documented it as an intentional probability-boundary edge — NOT money — analogous to the float() serialization-edge comments elsewhere in the codebase. Added the explanatory comment at the `__init__` cache site and a back-reference comment at the `update_config` re-derivation site (line ~648). This removes the undocumented policy exception without changing runtime behaviour (deterministic RNG comparison preserved).

### WR-02: `order_value < 1.0` compares `Decimal` to float literal

**Files modified:** `itrader/execution_handler/exchanges/simulated.py`
**Commit:** 82a6f75
**Applied fix:** Changed the threshold literal in `validate_order` from `1.0` (float) to `Decimal("1")`, so the comparison stays within the Decimal domain like every other numeric threshold in that method. `Decimal` is already imported in the module.

### WR-03: Documented `TradingSystem` backward-compat alias is not implemented

**Files modified:** `itrader/trading_system/backtest_trading_system.py`
**Commit:** a7a9103
**Applied fix:** Chose to correct the docstring rather than introduce a dead alias. Verified via grep that NO code (tests/scripts/itrader) imports `TradingSystem` — all remaining references are docstring/comment prose, and the Wave 4 (04-05) migration is already complete per recent commit history. Reworded the D-03 docstring paragraph to state the migration is done and no alias is exported, eliminating the false contract without adding an unused symbol.

### WR-04: `rollback_config(steps: int = 1)` — `steps` parameter is dead code

**Files modified:** `itrader/portfolio_handler/portfolio_handler.py`
**Commit:** a308868
**Applied fix:** Removed the never-read `steps: int = 1` parameter; signature is now `rollback_config(self) -> bool`. Verified via grep that no caller passes `steps`. The implementation (unconditional reset to the `default` preset) is unchanged.

### IN-01: `print()` in `BacktestRunner` bypasses structlog

**Files modified:** `itrader/trading_system/backtest_runner.py`
**Commit:** 213b4a6
**Applied fix:** Replaced `print("Backtest duration:", duration)` with `self.logger.info('Backtest completed', duration_seconds=duration.total_seconds())`, matching the bound-structlog style used everywhere else in the runner. `self.logger` is bound in `__init__`.

### IN-02: Stray `)` in `OrderHandler` initialization log message

**Files modified:** `itrader/order_handler/order_handler.py`
**Commit:** b717b2b
**Applied fix:** Removed the trailing stray `)` and converted the f-string log to structlog keyword form: `self.logger.info('Order Handler initialized', market_execution=self.market_execution)`. This is the only log call in the file; the kwargs form matches the project's structlog convention.

### IN-03: Redundant double-connect log for the `csv` exchange alias

**Files modified:** `itrader/execution_handler/execution_handler.py`
**Commit:** e8e0061
**Applied fix:** Added a `seen_connect: set[int]` instance-identity dedup to the connect loop, mirroring the existing `seen` dedup in `on_market_data`. Aliases (`'simulated'` and `'csv'`) that point to the same exchange object now connect — and log "Successfully connected" — only once. Indentation matches the file (tabs, with the existing tab+space continuation-alignment style for the multi-line warning call).

---

_Fixed: 2026-06-12_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
