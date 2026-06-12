---
phase: 03-hot-path-performance
fixed_at: 2026-06-11T13:40:00Z
review_path: .planning/phases/03-hot-path-performance/03-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 3: Code Review Fix Report

**Fixed at:** 2026-06-11T13:40:00Z
**Source review:** .planning/phases/03-hot-path-performance/03-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 4 (WR-01 .. WR-04; fix_scope=critical_warning, 6 Info findings excluded)
- Fixed: 4
- Skipped: 0

## Fixed Issues

### WR-01: `record_snapshot` / `get_current_metrics` reach wall-clock `datetime.now()` on a determinism-sensitive path

**Files modified:** `itrader/portfolio_handler/metrics/metrics_manager.py`, `tests/unit/portfolio/test_metrics_manager.py`
**Commit:** 1b2ef41
**Applied fix:** Removed the wall-clock fallback. `record_snapshot(None)` now raises `ValueError` rather than stamping `datetime.now()`. Threaded an optional business `timestamp` through `get_current_metrics(timestamp=None)` so the auto-snapshot branch passes business time. `calculate_performance_metrics` now raises when no snapshots exist and no explicit `end_date` is supplied (instead of falling back to wall clock). `export_metrics_to_dict` short-circuits to `None` when no snapshots exist, preserving its prior "insufficient data" contract without reaching the determinism guard. Note: the wall-clock `datetime.now()` at the cache-TTL boundary (`_cache_timestamp[...] = datetime.now()`) was intentionally left — that is wall-clock cache-expiry timing, not a snapshot business timestamp, so it is not a determinism leak. Updated four tests (`test_get_current_metrics`, `test_get_current_metrics_money_fields_are_decimal`, `test_get_current_metrics_auto_snapshot`, `test_calculate_performance_metrics_insufficient_data`) to supply explicit business timestamps under the new contract.

### WR-03: `_metrics_cache` is never cleared on invalidation — entries accumulate unbounded

**Files modified:** `itrader/portfolio_handler/metrics/metrics_manager.py`
**Commit:** 1b2ef41 (committed together with WR-01: both edits are interleaved in the same `record_snapshot`/cache region of one file and cannot be cleanly split into separate hunks via the positional-path commit tool)
**Applied fix:** Added `self._metrics_cache.clear()` alongside the existing `self._cache_timestamp.clear()` on cache invalidation in `record_snapshot`, so cached `PerformanceMetrics` entries (each holding a `daily_returns` list) are freed rather than left growing unbounded.

### WR-02: Metrics analytics drop to float, breaking the Decimal money guarantee and returning an inconsistent type

**Files modified:** `itrader/portfolio_handler/metrics/metrics_manager.py`
**Commit:** 4c82019
**Applied fix:** `get_drawdown_analysis` now keeps equity values and the drawdown ratio in Decimal end-to-end (no `float()` cast), and the else-branch sentinel for the flat-equity case is `Decimal('0')` (a single shared `_ZERO`) instead of bare `int 0`, giving a uniform return type. The `drawdown_periods`/`recovery_periods` comparison literals were switched to `Decimal('-0.01')` / `_ZERO` to keep the money domain uniform. `_calculate_metrics_from_snapshots` computes `total_return` directly in Decimal (`(final - initial) / initial`) instead of `Decimal(str(float_expr))`, removing the binary-float round-trip baked into the reported Decimal field. The float cast remains only where it is a genuine statistical/math input (the `math` annualization exponent and `statistics.stdev` volatility input).

### WR-04: `PortfolioHandler.update_config` does a shallow merge — partial nested updates silently reset sibling fields

**Files modified:** `itrader/portfolio_handler/portfolio_handler.py`, `tests/unit/portfolio/test_portfolio_handler.py`
**Commit:** f6d677c
**Applied fix:** Added a `_deep_merge` static helper that recurses into nested dicts, and routed `update_config` through it instead of the shallow `{**base, **updates}`. A partial nested update such as `{"limits": {"max_portfolios": 7}}` now preserves sibling limits fields (e.g. `max_positions`). Added regression test `test_update_config_partial_nested_preserves_siblings` asserting the intended field changes while siblings are retained.

## Verification

- Tier 1 (re-read) performed on every edit.
- Tier 2 syntax check (`ast.parse`) passed for all modified files.
- Targeted test suites run green: `tests/unit/portfolio/test_metrics_manager.py` (26 passed), `tests/unit/portfolio/test_portfolio_handler.py` (27 passed), and the full `tests/unit/portfolio/` domain (190 passed).
- WR-02 changes Decimal vs float arithmetic in reported analytics (drawdown / total_return). Tests pass and Decimal division is exact-precision, but these are cross-validated reported figures — worth a glance during numerical re-baselining to confirm the values match the float-derived baseline within the expected rounding tolerance.

---

_Fixed: 2026-06-11T13:40:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
