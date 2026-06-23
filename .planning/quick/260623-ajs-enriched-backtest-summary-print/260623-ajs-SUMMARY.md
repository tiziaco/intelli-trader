---
phase: quick-260623-ajs
plan: 01
subsystem: reporting
tags: [reporting, backtest, display, metrics, oracle-inert]
requires: []
provides:
  - "nine guarded derived metrics (total_return, avg_trade_pnl, avg_win, avg_loss, best_trade, worst_trade, avg_trade_duration, exposure_time, calmar)"
  - "format_backtest_summary grouped Capital/Trades/Risk-Return formatter"
  - "print_metrics_summary kw-only duration_seconds/period/portfolio_tickers params"
  - "backtest_runner.duration_seconds attribute"
affects:
  - itrader/reporting/metrics.py
  - itrader/reporting/summary.py
  - itrader/trading_system/backtest_runner.py
  - itrader/trading_system/backtest_trading_system.py
tech-stack:
  added: []
  patterns: ["pure-formatter (no I/O, no itrader imports in metrics.py)", "Decimal->float only at the print edge", "caller-preserving kw-only optional params"]
key-files:
  created: []
  modified:
    - itrader/reporting/metrics.py
    - itrader/reporting/summary.py
    - itrader/trading_system/backtest_runner.py
    - itrader/trading_system/backtest_trading_system.py
    - tests/unit/reporting/test_metrics.py
decisions:
  - "format_backtest_summary signature: list[per-portfolio value-bag dict] + kw-only period/duration_seconds; portfolio bag carries name/tickers/capital/15-metric set"
  - "Ticker cap = 6 (+N more past it); duration shows the two largest non-zero units, sub-minute as fractional seconds"
  - "format_metrics left byte-unchanged (still exported by metrics.py); summary.py dropped its now-unused format_metrics import"
metrics:
  duration: ~25 min
  completed: 2026-06-23
---

# Quick Task 260623-ajs: Enriched end-of-run backtest summary print Summary

Replaced the six-line `0.4f` per-portfolio printout with a grouped Capital / Trades /
Risk-Return block under a shared Period + Duration header, sourced from nine new pure
guarded metric functions and a new `format_backtest_summary` formatter — display-only and
oracle-inert (the SMA_MACD byte-exact oracle holds at 134 trades / 46189.87730727451).

## What was built

- **Task 1 — nine guarded metrics** (`reporting/metrics.py`): `total_return`,
  `avg_trade_pnl`, `avg_win`, `avg_loss` (negative), `best_trade`, `worst_trade`,
  `avg_trade_duration` (seconds), `exposure_time` (fraction over `open_positions_count > 0`),
  `calmar` (`cagr/abs(max_drawdown)`, reusing the pinned formulas). Each guards
  empty/degenerate input to `0.0` with pandas-2-safe idioms (`.iloc`, explicit empty-subset
  guards) so nothing trips `filterwarnings=['error']`. Module stays pure (zero itrader
  imports). Commit `ccc990a`.
- **Task 2 — formatter + printer rewire** (`reporting/metrics.py`, `reporting/summary.py`):
  `format_backtest_summary` renders the grouped block — `%`-scaled
  return/cagr/max_drawdown/win_rate/exposure_time, raw 4dp sharpe/sortino/profit_factor/calmar
  (`inf` passes through), thousands-sep signed currency, human duration helper, and a
  `+N more` truncated instrument list (cap 6, line omitted if empty; Period line omitted if
  None). `print_metrics_summary` gained the three kw-only optional params
  (`duration_seconds`, `period`, `portfolio_tickers`) with caller-preserving defaults,
  computes the nine new metrics + capital bag per portfolio (Decimal->float only at the
  print edge), and keeps the existing `logger.info('Backtest summary', ...)` line.
  `format_metrics` is untouched. Commit `f1c499e`.
- **Task 3 — thread the header inputs** (`trading_system/backtest_runner.py`,
  `backtest_trading_system.py`): runner stores `self.duration_seconds` after the run (the
  existing `'Backtest completed'` log line kept); `run()` assembles `duration`, a
  None/empty-guarded `period` from `time_generator.dates`, and a deduped order-preserving
  `portfolio_tickers` map (keyed by the `PortfolioId` handle) from the subscribed
  strategies, passing all three to the printer. TAB indentation preserved. Commit `ef0dd6e`.

## Verification

- `poetry run pytest tests/unit/reporting tests/integration/test_backtest_oracle.py -q` →
  68 passed (65 reporting unit + 3 oracle). No `filterwarnings=['error']` trips.
- `poetry run mypy itrader/reporting/metrics.py itrader/reporting/summary.py
  itrader/trading_system/backtest_runner.py itrader/trading_system/backtest_trading_system.py`
  → clean (strict).
- Live `scripts/run_backtest.py` run renders the grouped block correctly: 134 trades,
  final equity 46,189.88, the BTCUSD instrument list, `+361.90%` total return, `10d 14h`
  avg duration — matching the spec mockup shape.
- Indentation: `reporting/*.py` + tests stayed 4-space; `trading_system/*.py` stayed TAB
  (`grep -nP "^    [^ ]"` on the tab files returned nothing).

## Deviations from Plan

None — plan executed exactly as written. The `format_backtest_summary` signature
(`list[value-bag dict]` + kw-only `period`/`duration_seconds`) was decided at implementation
time as the plan/spec permitted; one incidental tidy was removing the now-unused
`format_metrics` import from `summary.py` (the function itself is byte-unchanged in
`metrics.py` and still exported).

## Self-Check: PASSED

- itrader/reporting/metrics.py — FOUND (contains `def format_backtest_summary` + nine new funcs)
- itrader/reporting/summary.py — FOUND (kw-only params on `print_metrics_summary`)
- itrader/trading_system/backtest_runner.py — FOUND (`self.duration_seconds`)
- itrader/trading_system/backtest_trading_system.py — FOUND (`portfolio_tickers` assembly)
- tests/unit/reporting/test_metrics.py — FOUND (new metric + formatter tests)
- Commits ccc990a, f1c499e, ef0dd6e — all present in `git log`.
