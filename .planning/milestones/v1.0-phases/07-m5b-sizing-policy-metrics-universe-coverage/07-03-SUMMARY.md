---
phase: 07-m5b-sizing-policy-metrics-universe-coverage
plan: 03
subsystem: reporting
tags: [metrics, plotly, frames, oracle-inert, d-14, d-15, d-16, d-17, d-18, d-19]
requires:
  - phase: 07-02
    provides: BarEvent factory in BacktestBarFeed; universe collapsed to membership stub (trading-system wiring this plan edits around)
provides:
  - itrader/reporting/metrics.py — pure D-16 metric functions (sharpe/sortino/cagr/max_drawdown/profit_factor/win_rate/rolling_sharpe/compute_returns) + format_metrics, PERIODS=365, ddof=1, negative drawdown sign
  - itrader/reporting/frames.py — build_trade_log/build_equity_curve/TRADE_COLUMNS/EQUITY_COLUMNS relocated verbatim from run_backtest.py, duck-typed portfolio input
  - itrader/reporting/plots.py — plotly-6 minimal figure set (equity, drawdown, trade P/L scatter, sub_plots3)
  - TradingSystem.run(print_summary=True) — engine-level end-of-run metrics printout per portfolio (D-14 amendment)
  - scripts/run_backtest.py — nested summary.json "metrics" block (D-15) + slippage_entry/slippage_exit trade columns (D-17), awaiting the 07-07 re-freeze
affects:
  - 07-07 (re-freeze 1 freezes the metrics block + slippage columns into tests/golden/ and extends the oracle assertions)
  - phase 08 (cross-validation reconciles these exact formula pins against backtesting.py/backtrader)
tech-stack:
  added: []
  patterns:
    - pure computation module (numpy/pandas only, zero itrader imports) split from presentation
    - one formula source, two consumers (engine printout + artifact serialization)
    - verbatim relocation gated by ast body-identity diff + byte-exact oracle
key-files:
  created:
    - itrader/reporting/metrics.py
    - itrader/reporting/frames.py
    - tests/unit/reporting/test_metrics.py
    - tests/unit/reporting/test_plots_smoke.py
  modified:
    - itrader/reporting/plots.py (rewritten for plotly 6.8.0)
    - itrader/reporting/__init__.py (exports metrics/frames/plots)
    - itrader/trading_system/backtest_trading_system.py (StatisticsReporting removed; print_summary repurposed)
    - itrader/trading_system/live_trading_system.py (StatisticsReporting removed; get_statistics returns None)
    - scripts/run_backtest.py (frames rewire, metrics block, slippage columns)
    - pyproject.toml (three reporting ignore_errors overrides removed)
  deleted:
    - itrader/reporting/statistics.py
    - itrader/reporting/engine_logger.py
    - itrader/reporting/base.py
    - itrader/reporting/performance.py
decisions:
  - "D-19 'dead extras': signals_plot deleted (consumed price+transactions frames, not the metric-module frames; outside the minimal set); sub_plots3 KEPT (composes exactly the three kept figures) with append_trace -> add_trace(row=,col=)"
  - "cagr guards non-positive FINAL equity too (not just zero-start): a negative ratio under a fractional exponent is complex-valued in Python — returns 0.0, documented in the docstring"
  - "Engine printout coerces equity column astype(float) before compute_returns so the empty-run path (object-dtype empty column) stays warning-free under filterwarnings=error"
  - "trades.csv serialization pinned to trades[TRADE_COLUMNS + SLIPPAGE_COLUMNS] so column order is explicit and deterministic through the relocation"
metrics:
  duration: ~16 min
  completed: 2026-06-07T20:37:00Z
  tasks: 3
  commits: 5
---

# Phase 7 Plan 03: Reporting Metrics, Plots, Frames & Engine Printout Summary

**One-liner:** Pure backtesting.py-matched metric functions (PERIODS=365, ddof=1, negative drawdown) + verbatim-relocated frame builders now power both an engine-level end-of-run printout and run_backtest.py's D-15 metrics block / D-17 slippage columns, with the four legacy reporting modules deleted and the oracle still byte-exact against unchanged goldens.

## What Was Built

### Task 1 — itrader/reporting/metrics.py (TDD)
Pure computation module: `compute_returns`, `max_drawdown`, `sharpe`, `sortino`, `profit_factor`, `cagr`, `win_rate`, `rolling_sharpe` (D-18 — the rolling-stats stub finished, not deleted), and `format_metrics` (pure string builder for the printout). Conventions pinned in the module docstring (Pitfall 10): drawdown sign NEGATIVE matching backtesting.py `dd.min()`, ddof=1 explicit, PERIODS=365, rf=0, true profit factor, textbook full-period Sortino downside deviation. Every denominator guarded — empty frames, zero std, zero gross loss, zero downside all return 0.0 (all-winners PF returns `inf`) without raising under `filterwarnings=["error"]`. Imports: numpy + pandas only — a test enforces the zero-itrader-imports anti-pattern guard and the no-`print(` purity pin. 27 hand-computed fixture tests (RESEARCH equity 100→110→99→121 ⇒ max_drawdown == -0.10; sharpe/sortino computed step-by-step with stdlib math in comments).

### Task 2 — Legacy deletion, plotly-6 fix, frames relocation, engine printout (TDD)
- **Deleted by `git rm`** (kills by deletion): `statistics.py` (the `is np.nan` identity bug at :147; `_prepare_data` reading nonexistent `portfolio.metrics`; `_to_sql` with its f-string DROP TABLE injection path — T-07-05, nothing replaces it, D-sql owns any rebirth), `performance.py` (unraised ValueError at :28, misspelled `profict_factor` count-ratio, non-standard subset-std Sortino, `periods=355`, zero-seeded HWM drawdown), `engine_logger.py` (`EngineLogger`, M5-07 locked requirement — grep-verified imported nowhere), `base.py` (`AbstractStatistics` + pickle `load`).
- **plots.py** rewritten (tabs preserved) to the D-19 minimal set: `line_equity`/`line_drwdwn`/`profit_loss_scatter` consuming the SAME frames as metrics.py, plus `sub_plots3`. Every `titlefont_size` site replaced with `title=dict(text=..., font=dict(size=14))`; `append_trace` → `add_trace(row=, col=)`; the scatter's column bugs fixed against the real `build_trade_log` columns (`exit_date`/`realised_pnl`); `signals_plot`, dead numpy/enums imports, and "OK, FUNZIONA" dev comments deleted. 5 smoke tests (including empty-trades).
- **frames.py** created: `build_trade_log`/`build_equity_curve`/`TRADE_COLUMNS`/`EQUITY_COLUMNS` relocated VERBATIM — function bodies verified character-identical to the run_backtest.py originals via an ast-extraction diff (T-07-23). pandas + stdlib only, portfolio duck-typed.
- **TradingSystem.run(print_summary: bool = True)** (D-14 amendment, user decision 2026-06-07): at end of run, `_print_metrics_summary` builds the trades/equity frames per active portfolio via `reporting.frames`, computes the D-15 metric set via `reporting.metrics`, and `print(format_metrics(...))` prefixed with the portfolio name, plus final equity + trade count via `self.logger`. Display only — the engine writes no files; empty runs print a guarded-zero block.
- **live_trading_system.py**: mechanical StatisticsReporting removal (A4); `get_statistics` now logs a warning and returns None — no printout added.
- **pyproject.toml**: the three `ignore_errors` overrides (`itrader.reporting.statistics`/`engine_logger`/`plots`) removed — `mypy --strict` now gates metrics/frames/plots un-gated: clean across 137 files.

### Task 3 — run_backtest.py: D-15 metrics block + D-17 slippage columns
- Local frame builders + column pins deleted; all four imported from `itrader.reporting.frames`. `system.run(print_summary=False)` → `system.run()` (the repurposed default-True prints the engine block; the broken StatisticsReporting path it guarded against is dead).
- `build_metrics_block`: nested `"metrics"` dict (RESEARCH OQ3) — sharpe/sortino/cagr/max_drawdown/profit_factor/win_rate, all floats, computed by the same pure functions the engine prints. The docstring's "derived ratios are M5-owned" carve-out deleted — closed this phase.
- `attach_slippage` (Pattern 3, engine-inert): `slippage_entry`/`slippage_exit` = fill price minus decision-bar close, where the decision bar is the bar immediately before the fill bar in the store index (Phase 6 next-bar-open convention; in the zero-slippage golden run these measure the overnight gap). Computed post-hoc from `system.store.read_bars(TICKER)["close"]` — no engine/event/entity change.
- **Oracle safety proven** (Pitfall 6 / T-07-06): `tests/golden/` and `test_backtest_oracle.py` untouched (`git status` clean); oracle passes byte-exact (fresh final_equity 53103.01549885479 == golden); freezing rides the 07-07 re-freeze.
- **Determinism proven**: two consecutive runs produce byte-identical `output/` trees (`diff -r` clean).

## Verification Results

| Gate | Result |
|------|--------|
| `pytest tests/unit/reporting` | 32 passed |
| Full suite (`pytest`) | 680 passed |
| `mypy itrader` (strict, overrides removed) | clean — 137 files |
| Oracle (`test_backtest_oracle.py`) vs UNCHANGED goldens | 2 passed, byte-exact |
| Determinism double-run `diff -r` | byte-identical |
| frames.py body-identity vs run_backtest originals | IDENTICAL (ast diff) |
| `summary.json` metrics block / `trades.csv` slippage header | present |

## Deviations from Plan

### Notes (no functional deviations)

**1. Acceptance grep "returns nothing" satisfied for live code; docstring mentions remain**
- **Found during:** Task 2 verification
- **Issue:** `grep -rn "StatisticsReporting|EngineLogger|profict_factor|titlefont"` still matches 5 docstring/comment lines: frames.py (inside the VERBATIM-relocated `build_equity_curve` docstring — removing it would break the body-identity acceptance gate), metrics.py ×2 (documenting which bugs died), plots.py (documenting the plotly-6 fix), live_trading_system.py (comment explaining the removal).
- **Resolution:** Zero live-code references remain (no imports, constructions, or calls); the mentions are documentation of the deletions. The frames.py mention is structurally required by the verbatim-relocation constraint (T-07-23).

**2. D-19 "minimal set" interpretation**
- `signals_plot` deleted (consumed price + transactions frames — outside the minimal set and not the metric-module frames); `sub_plots3` kept since it composes exactly the three kept figures and was the only `append_trace` consumer the plan instructed to convert.

Plan otherwise executed exactly as written.

## Known Stubs

None blocking the plan goal. `LiveTradingSystem.get_statistics()` returns `None` with a logged warning — intentional per plan ("no metrics printout added there"); live-mode statistics are D-live scope.

## Threat Flags

None — no new security surface. T-07-05 (the `_to_sql` DROP TABLE injection dead path) is deleted with nothing replacing it; T-07-06/T-07-23 mitigations verified by the byte-exact oracle gate against unchanged goldens.

## Commits

| Hash | Type | Description |
|------|------|-------------|
| c4c71e4 | test | failing hand-computed fixture tests for reporting metrics (RED) |
| 61a0bee | feat | pure reporting/metrics module with D-16 pinned formulas (GREEN) |
| 1286ddc | test | failing plotly-6 smoke tests for the kept figure set (RED) |
| 4d1adb9 | feat | delete legacy reporting, fix plots, relocate frames, engine printout (GREEN) |
| fddd80a | feat | run_backtest.py D-15 metrics block + D-17 slippage columns |

## TDD Gate Compliance

Both TDD tasks followed RED→GREEN with separate commits (c4c71e4→61a0bee; 1286ddc→4d1adb9). No refactor commits needed.

## Self-Check: PASSED

All created files exist, all four legacy modules confirmed deleted, all 6 commit hashes present in git log.
