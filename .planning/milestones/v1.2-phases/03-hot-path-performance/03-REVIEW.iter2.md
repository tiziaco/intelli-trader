---
phase: 03-hot-path-performance
reviewed: 2026-06-11T00:00:00Z
depth: standard
files_reviewed: 14
files_reviewed_list:
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/order_handler/order_manager.py
  - itrader/portfolio_handler/base.py
  - itrader/portfolio_handler/metrics/metrics_manager.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/portfolio_handler/position/position_manager.py
  - itrader/portfolio_handler/storage/in_memory_storage.py
  - itrader/price_handler/feed/bar_feed.py
  - itrader/price_handler/store/csv_store.py
  - itrader/strategy_handler/strategies/SMA_MACD_strategy.py
  - tests/unit/portfolio/test_metrics_manager.py
  - tests/unit/portfolio/test_on_fill_status_guard.py
  - tests/unit/portfolio/test_state_storage.py
  - tests/unit/price/test_bar_feed.py
findings:
  critical: 0
  warning: 4
  info: 6
  total: 10
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-06-11
**Depth:** standard
**Files Reviewed:** 14
**Status:** issues_found

## Summary

Reviewed the Phase 3 hot-path-performance changeset: the de-pandas bar feed
(`bar_feed.py`), CSV store, the unified `PortfolioStateStorage` seam plus the
position/metrics managers re-routed through it, the Decimal-native simulated
exchange, the order-manager admission/sizing/bracket pipeline, and the
`SMA_MACD` reference strategy, alongside four unit-test modules.

The changeset is well-documented and the correctness-critical seams (Decimal
money, single-writer copy-free containers, fail-fast reconciliation) are
carefully argued in the inline decision tags. No BLOCKER-class defects were
found: the money path is Decimal end-to-end on the engine path, the on_fill
reservation release is correctly placed in a `finally`, and the bar-feed
visibility cutoff matches its tests.

The findings below concentrate on (1) a wall-clock default in the metrics
snapshot path that silently breaks determinism on the auto-snapshot branch,
(2) float/Decimal type mixing in the metrics drawdown/return analytics that
erodes the "Decimal end-to-end" guarantee at the analytics boundary, (3) a
metrics cache that is invalidated for reads but never freed, (4) a shallow-merge
hazard in `update_config`, and a batch of dead imports. None block the golden
backtest, but several touch the project's core "numbers you can trust" value.

## Warnings

### WR-01: `record_snapshot` / `get_current_metrics` reach wall-clock `datetime.now()` on a determinism-sensitive path

**File:** `itrader/portfolio_handler/metrics/metrics_manager.py:139-140, 197, 241`
**Issue:** `record_snapshot(timestamp=None)` falls back to `datetime.now()`
(lines 139-140). The golden run-path caller (`portfolio.py:352`) passes the
business `time`, so the direct call is safe — but `get_current_metrics`'s
auto-snapshot branch calls `record_snapshot()` with NO argument (line 197), so
any snapshot created through that path is stamped with wall clock. The same
wall-clock leak exists in `calculate_performance_metrics` when no snapshots
exist (line 241). This codebase's locked contract is "business time, never wall
clock" (CLAUDE.md determinism section); a wall-clock timestamp poured into the
snapshot history would make downstream period filtering and the snapshot grid
non-reproducible.
**Fix:** Do not silently fall back to wall clock. Require an explicit timestamp
on the engine path (raise if `None` when state must be deterministic), or thread
the injected `BacktestClock`/last-bar time through `get_current_metrics` so its
auto-snapshot passes the latest known business time instead of letting
`record_snapshot()` reach `datetime.now()`.

### WR-02: Metrics analytics drop to float, breaking the Decimal money guarantee and returning an inconsistent type

**File:** `itrader/portfolio_handler/metrics/metrics_manager.py:298-325, 547-559`
**Issue:** `get_drawdown_analysis` converts equity to `float` (line 298) and
computes `(value - current_max) / current_max` in binary float; the returned
`max_drawdown`/`current_drawdown` are floats. `_calculate_metrics_from_snapshots`
likewise casts to float (lines 547-548) and computes `total_return` via
`Decimal(str(float_expr))`, baking a binary-float round-trip into a Decimal
field. The inline comments justify this as "the statistical-ratio metric input
boundary," but `max_drawdown` and `total_return` are reported, money-derived
figures the project promises are trustworthy/cross-validated. Additionally the
else-branches return bare `int 0` (lines 309, 313) intermixed with floats, so a
flat-equity portfolio returns `max_drawdown=0` (int) while a real drawdown
returns a float — an inconsistent return contract for a public method.
**Fix:** Keep the *reported* ratios in Decimal (drawdown, total return) with a
single `quantize` at the report edge; reserve the float cast strictly for the
`statistics.stdev`/`math.sqrt` statistical inputs. Make the else-branch
sentinels `Decimal('0')` not bare `0` so the return type is uniform.

### WR-03: `_metrics_cache` is never cleared on invalidation — entries accumulate unbounded

**File:** `itrader/portfolio_handler/metrics/metrics_manager.py:180`
**Issue:** `record_snapshot` invalidates the cache by clearing only
`self._cache_timestamp` (line 180) and leaves `self._metrics_cache` populated.
`_is_cache_valid` returns `False` once the timestamp is gone, so stale entries
are never *read* (correctness preserved) — but they are never *freed* either.
Over a long run with many distinct `(period, end_date.date())` keys (line 268),
`_metrics_cache` grows without bound, each entry holding a full
`PerformanceMetrics` (with its `daily_returns` list). This directly contradicts
the explicit `max_snapshots` trim discipline elsewhere in the same class.
**Fix:** Clear both dicts together on invalidation:
```python
self._metrics_cache.clear()
self._cache_timestamp.clear()
```

### WR-04: `PortfolioHandler.update_config` does a shallow merge — partial nested updates silently reset sibling fields

**File:** `itrader/portfolio_handler/portfolio_handler.py:437-447`
**Issue:** `update_config` builds `merged = {**self.config_data.model_dump(), **updates}`
(line 440) then `PortfolioConfig.model_validate(merged)`. `{**a, **b}` is a
SHALLOW merge: an `updates={"limits": {"max_portfolios": 50}}` REPLACES the
entire `limits` submodel, silently dropping every other limit field (e.g.
`max_positions`) and resetting it to whatever `model_validate` derives from the
truncated dict. A caller intending a partial limits update gets the rest of the
limits reset. Because the method returns `True` on success, the silent reset is
undetectable to the caller.
**Fix:** Deep-merge nested dicts before `model_validate` (recurse into dict
values), or document that any nested key passed to `update_config` must be a
complete submodel. Add a regression test for a partial nested update preserving
sibling fields.

## Info

### IN-01: Dead imports in `position_manager.py`

**File:** `itrader/portfolio_handler/position/position_manager.py:6,8,10,14`
**Issue:** Unused imports: `ROUND_HALF_UP` (line 6), `Tuple` (line 8),
`numpy as np` (line 10 — zero `np.` references in the file), and `PositionEvent`
(line 14). `numpy` is a heavyweight dependency pulled in for nothing.
**Fix:** Reduce to `from decimal import Decimal`, drop `Tuple` from the typing
import, delete `import numpy as np`, and drop `PositionEvent` from the enums
import.

### IN-02: Dead imports in `metrics_manager.py`

**File:** `itrader/portfolio_handler/metrics/metrics_manager.py:6,8,9,14`
**Issue:** Unused: `ROUND_HALF_UP` (line 6), `Tuple` (line 8), `asdict`
(line 9), `InvalidTransactionError` (line 14 — never raised in this module).
**Fix:** Trim to the names actually referenced.

### IN-03: `_should_close_position` and `_validate_position_consistency` use mismatched zero-tolerances

**File:** `itrader/portfolio_handler/position/position_manager.py:88,188,211`
**Issue:** `self.tolerance = Decimal('0.00001')` (5 dp) gates closure
(line 188), while `_validate_position_consistency` uses `Decimal("0.000001")`
(6 dp) for its negative-quantity guard (line 211). The order-of-magnitude
difference is undocumented; a residual quantity in [1e-6, 1e-5) is treated
inconsistently between the two methods. Not a live defect on the golden
long-only single-ticker run, but a latent inconsistency.
**Fix:** Derive both from one named constant, or document why they differ.

### IN-04: `validate_order` mixes Decimal money with float/int literals

**File:** `itrader/execution_handler/exchanges/simulated.py:395,404`
**Issue:** `event.price > 1000000` (int) and `order_value < 1.0` (float)
compare Decimal money against non-Decimal literals. The comparisons are correct
and oracle-safe (warnings-only), but the float `1.0` literal in a file otherwise
scrupulously Decimal-native invites a future copy-paste defect onto a real money
path.
**Fix:** Use `Decimal("1000000")` and `Decimal("1")` for the comparison literals
to keep the money domain uniform.

### IN-05: `get_return_distribution` percentiles are nominal for tiny samples with no caveat

**File:** `itrader/portfolio_handler/metrics/metrics_manager.py:362-368`
**Issue:** Percentile lookups index by a fraction of the sample length. The
`len(snaps) < period_days + 1` guard (line 339) and the `int(len*0.95) < len`
invariant prevent any IndexError, so this is not a crash. But for very small
samples the percentile values are degenerate (e.g. 2 returns -> "5th" and "25th"
both equal `sorted[0]`) and are reported without any minimum-sample caveat.
**Fix:** Require a minimum sample size before reporting percentiles, or document
that they are nominal below N samples.

### IN-06: Misleading `# Exit` comment indentation in `SMA_MACD_strategy`

**File:** `itrader/strategy_handler/strategies/SMA_MACD_strategy.py:70`
**Issue:** The `# Exit` comment sits at 2-tab indentation directly above an
`elif` at 3-tab indentation. A reader skimming indentation could mistake it for
a sibling of the outer SMA-filter `if`. The logic is correct and
behavior-preserving (the `elif` correctly pairs with the MACD `if` on line 68 —
the sell-exit only fires while the SMA filter holds, per the W1-12 note), but
the comment placement is misleading. Note also that `MACDhist.iloc[-2]`
(line 68/71) assumes at least two post-`dropna` MACD values; this is guaranteed
by the `warmup = max([long_window, 100])` handler short-circuit and is
behavior-preserving, but is a hidden coupling worth a comment.
**Fix:** Indent the `# Exit` comment to 3 tabs to align with the `elif` it
labels.

---

_Reviewed: 2026-06-11_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
