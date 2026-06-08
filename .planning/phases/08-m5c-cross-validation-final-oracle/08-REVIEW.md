---
phase: 08-m5c-cross-validation-final-oracle
reviewed: 2026-06-08T17:10:00Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - itrader/order_handler/order_validator.py
  - itrader/portfolio_handler/metrics/metrics_manager.py
  - itrader/portfolio_handler/portfolio.py
  - itrader/trading_system/backtest_trading_system.py
  - pyproject.toml
  - scripts/cross_validate.py
  - scripts/crossval/__init__.py
  - scripts/crossval/backtesting_py_run.py
  - scripts/crossval/backtrader_run.py
  - scripts/crossval/indicators.py
  - scripts/crossval/nautilus_run.py
  - scripts/crossval/reconcile.py
  - scripts/run_backtest.py
  - tests/unit/order/test_order_validator.py
  - tests/unit/portfolio/test_metrics_manager.py
  - tests/unit/portfolio/test_money_decimal.py
findings:
  critical: 0
  warning: 0
  info: 0
  total: 0
status: clean
---

# Phase 8: Code Review Report (Re-Review, iteration 2)

**Reviewed:** 2026-06-08T17:10:00Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** clean

## Summary

Re-review of iteration 2 in the `--auto` fix loop. The previous review (iteration 1)
raised 11 findings (5 WARNING, 6 INFO); all were fixed across 6 targeted commits
(`243a06d`, `8d88dbf`, `b0ab1f2`, `ee0b970`, `caf8968`, `37e1627`). I verified every
fix against the live source, traced the two flagged math/typing changes
(WR-01, WR-02) for correctness and for regressions in their downstream consumers,
and ran the three reviewed test files (50 tests, all green).

All 11 findings are resolved correctly, and the fixes introduced no new defects.

### Verification of each prior finding

- **WR-01 — annualized_return geometric formula** (`metrics_manager.py:545-549`):
  Now `(1.0 + float(total_return)) ** (365.0 / days) - 1.0`, the correct geometric
  annualization, guarded by `days > 0 and initial_equity > 0`. Verified the negative-base
  edge cannot fire on the equity path (`total_return >= -1`, so `1 + total_return >= 0`;
  total wipeout gives `0 ** positive = 0`). Downstream `sharpe_ratio` now divides a
  correctly-annualized excess return. RESOLVED.

- **WR-02 — Decimal-native daily_returns** (`metrics_manager.py:526-534`):
  The float→`Decimal(str(...))` round-trip is gone; the ratio is computed
  `(curr_equity - prev_equity) / prev_equity` directly on Decimal inputs and stored
  exactly in the `List[Decimal]` field. Traced all downstream consumers of
  `daily_returns`: volatility (line 554) and average_win/loss (lines 568-569) convert
  to float explicitly, and the win/loss filters (`r > 0`, `r < 0`, lines 564-565)
  operate correctly on Decimal — no residual type leak. RESOLVED.

- **WR-03 — malformed truncation footer** (`reconcile.py:267-274`): The footer now pads
  to `cols - 2` empty cells; verified by reproduction that the emitted row has exactly
  `cols` cells (a well-formed N-column Markdown row). RESOLVED.

- **WR-04 — length-sensitive CAGR/Sharpe asymmetry** (`reconcile.py:58-67`): Documented
  the apples-to-apples caveat in `recompute_headline`'s docstring (length-sensitive
  metrics are informational; the D-02 trade-level table is the primary gate) — an
  accepted disposition for offline evidence tooling. RESOLVED (documented).

- **WR-05 — positional trade alignment cascade** (`reconcile.py:178-182`): Documented the
  positional-alignment cascade caveat in `align_trades`' docstring so consumers read
  SHIFT rows in light of any trade-count mismatch. RESOLVED (documented).

- **IN-01 — dead build_report params** (`cross_validate.py:127-133`): `itrader_headline`
  and `engine_metrics` removed from the signature and the call site. RESOLVED.

- **IN-02 — unguarded `_norm_ts` parse** (`reconcile.py:155-161`): Wrapped in
  `try/except (ValueError, TypeError, pd.errors.OutOfBoundsDatetime)` returning None.
  RESOLVED.

- **IN-03 — redundant Decimal wrap** (`portfolio.py:398`): Now `abs(pos.market_value)`
  directly, trusting the Decimal source. RESOLVED.

- **IN-04 — production pass-through path untested** (`test_metrics_manager.py:60-72`):
  New `test_as_decimal_passthrough_on_decimal_money` asserts identity pass-through on a
  Decimal input, locking the production branch. RESOLVED.

- **IN-05 — inconsistent test literals** (`test_metrics_manager.py`): `update_values`
  calls now use consistent float literals. RESOLVED.

- **IN-06 — nautilus indicator-column remap trap** (`nautilus_run.py:434-447`): Added a
  fail-fast `required_cols = ("sma_short", "sma_long", "macd_hist")` check raising a
  clear `RuntimeError`. Cross-checked against `indicators.py::compute_indicators`, which
  produces exactly those three column names — the assertion targets the correct keys.
  RESOLVED.

### Regression scan

- The 50 unit tests across the three reviewed test files pass under the strict
  `filterwarnings=["error"]` config — no new warnings.
- The Decimal-typing changes preserve the `daily_returns: List[Decimal]` contract; no
  consumer assumes float without an explicit narrowing call.
- `order_validator.py`, `portfolio.py` (outside the IN-03 line), `run_backtest.py`,
  `backtest_trading_system.py`, `pyproject.toml`, and the engine/indicator harness
  modules were re-scanned and remain clean — no new issues introduced by the fixes.

No BLOCKER, WARNING, or INFO findings remain.

---

_Reviewed: 2026-06-08T17:10:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
