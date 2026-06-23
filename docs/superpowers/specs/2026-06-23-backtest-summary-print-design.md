# Enriched end-of-run backtest summary print

**Date:** 2026-06-23
**Status:** Approved (design) — pending spec review
**Scope:** `itrader/reporting/` + minimal threading in `itrader/trading_system/`

## Problem

The end-of-run console output (`reporting/summary.py::print_metrics_summary`)
prints only six raw `0.4f` metrics per portfolio:

```
Backtest metrics — oracle_pf
----------------------------
sharpe             0.6584
sortino            1.0385
cagr               0.1991
max_drawdown      -0.5383
profit_factor      1.2911
win_rate           0.3657
```

It omits the run-context "automatics" already computed in `summary.py::build_summary`
(period, starting/final cash, equity, realised PnL, trade count), shows everything
as a bare ratio (drawdown/CAGR/win-rate read better as `%`), and never surfaces the
backtest **duration**, which today is only emitted via `logger.info('Backtest completed', …)`
in `backtest_runner.py`.

## Goals

- Richer, grouped per-portfolio summary: **Capital / Trades / Risk-Return**.
- A run-level header: **Period** (date span + bar count) and **Duration**.
- Per-portfolio **instrument list** sourced from the configured strategy universe.
- New derived metrics: total return, avg trade PnL, avg win/loss, best/worst trade,
  avg trade duration, exposure time, Calmar.
- Percentage rendering for return/CAGR/drawdown/win-rate/exposure; raw 4-dp for
  Sharpe/Sortino/Profit-factor/Calmar.

## Non-goals (YAGNI / deferred)

- **Per-strategy breakdown.** Trades carry no `strategy_id` (a `Position` is built
  from a `Transaction` with no strategy attribution). True per-strategy metrics need
  data-model plumbing through `Transaction→Position→to_dict`, which touches the
  byte-exact oracle trade-log frame. Deferred to its own milestone task.
- **No new artifact files.** `summary.json` and every golden are unchanged. This is
  display-only / oracle-inert (the W4-07 contract on `print_metrics_summary`).
- **No timeframe line.** Not cleanly recoverable post-run; the Period span conveys it.
- `format_metrics` is **left untouched** (it has unit tests and is the only other
  formatter); the new block is a separate function.

## Output (target)

```
══════════════════════════════════════════════
 Backtest Run Summary
══════════════════════════════════════════════
 Period        2018-01-01 → 2026-06-03  (3076 bars)
 Duration      3.42s
──────────────────────────────────────────────
 Portfolio · oracle_pf   (BTCUSD)
──────────────────────────────────────────────
 Capital
   Starting cash       10,000.00
   Final cash           8,432.10
   Final equity        19,910.55
   Total return          +99.11%
   Realised PnL         +9,910.55
 Trades
   Count                      137
   Win rate                36.57%
   Profit factor            1.2911
   Avg trade PnL             72.34
   Avg win                 410.20
   Avg loss               -122.55
   Best trade            1,840.00
   Worst trade            -612.30
   Avg duration             4d 6h
   Exposure time           58.20%
 Risk / Return
   CAGR                    19.91%
   Sharpe                   0.6584
   Sortino                  1.0385
   Max drawdown           -53.83%
   Calmar                   0.3698
══════════════════════════════════════════════
```

Multiple portfolios print one section each, under one shared header.

## Data sourcing (no engine-config threading)

| Field | Source | Notes |
|-------|--------|-------|
| Period start/end + bar count | `engine.time_generator.dates` (`[0]`, `[-1]`, `len`) | Available post-run on the runner/system. |
| Duration | `backtest_runner.duration_seconds` (new attr) | Currently a local var, only logged. |
| Starting cash | `equity.iloc[0]` (first equity-curve snapshot) | Per-portfolio opening equity = starting cash. |
| Final cash / equity | `portfolio.cash` / `portfolio.total_equity` | Decimal→float at the print edge, no arithmetic. |
| Instrument list | union of `strategy.tickers` for strategies with `portfolio.portfolio_id in strategy.subscribed_portfolios` | Configured universe — includes untraded/open tickers. Truncate `+N more` past a cap. Omit line if empty. |
| All metrics | trade-log + equity-curve frames (already built in the printer loop) | Via the new pure functions below. |

## Design

### 1. `reporting/metrics.py` — new pure, guarded functions

Stateless functions over the existing run-artifact frames, matching the module's
empty-guard convention (return `0.0` / zero on empty/degenerate input; no warnings
under `filterwarnings=["error"]`; `.iloc` indexing only).

- `total_return(equity: pd.Series) -> float` — `final/start - 1`; `0.0` if empty or `start<=0`.
- `avg_trade_pnl(trades: pd.DataFrame) -> float` — mean `realised_pnl`; `0.0` if empty.
- `avg_win(trades) -> float` — mean `realised_pnl` over `pnl > 0`; `0.0` if no winners.
- `avg_loss(trades) -> float` — mean `realised_pnl` over `pnl < 0` (negative); `0.0` if none.
- `best_trade(trades) -> float` — `max(realised_pnl)`; `0.0` if empty.
- `worst_trade(trades) -> float` — `min(realised_pnl)`; `0.0` if empty.
- `avg_trade_duration(trades) -> float` — mean of `(exit_date - entry_date)` in
  **seconds** (float); `0.0` if empty. Formatter renders human form.
- `exposure_time(equity_frame: pd.DataFrame) -> float` — `(open_positions_count > 0).mean()`;
  fraction in `[0,1]`; `0.0` if empty. Note: takes the **frame** (needs the
  `open_positions_count` column), not the equity series.
- `calmar(equity: pd.Series) -> float` — `cagr(equity) / abs(max_drawdown(equity))`;
  `0.0` if drawdown is `0`.

Each gets unit tests in `tests/unit/reporting/test_metrics.py` (happy path + empty
guard), mirroring the existing metric tests.

### 2. `reporting/metrics.py` — `format_backtest_summary(...)`

New formatter (sibling to the untouched `format_metrics`). Backtest-scoped by intent
(only the backtest end-of-run printer calls it), so the name is explicit rather than
mode-agnostic. Pure string building, no
I/O. Renders the grouped block above:

- Currency values: thousands separators, 2-dp (`10,000.00`); signed for return/PnL.
- Percentages (`total_return`, `cagr`, `max_drawdown`, `win_rate`, `exposure_time`):
  `value * 100` with `%`, signed where natural.
- Ratios (`sharpe`, `sortino`, `profit_factor`, `calmar`): raw `%.4f`; `inf` passes through.
- Duration: seconds → `Nd Nh` / `Nh Nm` / `Nm Ns` human form.
- Instrument list: comma-joined, `+N more` past a cap (e.g. 6); line omitted if empty.

Exact signature decided at implementation time, but it consumes a small per-portfolio
value bag plus the run-level header values (period tuple, duration, ticker list).

### 3. `reporting/summary.py::print_metrics_summary` — signature + body

Add optional params (defaults preserve every existing caller, incl. tests/oracle):

```python
def print_metrics_summary(
    portfolios: Any,
    logger: Any,
    *,
    duration_seconds: float | None = None,
    period: tuple[Any, Any, int] | None = None,        # (start, end, bar_count)
    portfolio_tickers: dict[Any, list[str]] | None = None,
) -> None:
```

Body: compute the new metrics per portfolio alongside the existing six, build the
header once, call `format_backtest_summary`, print. The duck-typed purity contract holds
(no handler imports). The existing `logger.info('Backtest summary', …)` line is kept.

### 4. `trading_system/backtest_runner.py`

Store the already-computed duration instead of only logging it:

```python
self.duration_seconds: float | None = None    # in __init__
...
self.duration_seconds = duration.total_seconds()   # after the run, beside the log line
```

The `logger.info('Backtest completed', duration_seconds=…)` line stays (no behavior loss).

### 5. `trading_system/backtest_trading_system.py::run`

Before calling the printer, assemble the header inputs from reachable handles:

- `duration = self.runner.duration_seconds`
- `dates = self.engine.time_generator.dates` → `period = (dates[0], dates[-1], len(dates))`
- `portfolio_tickers`: iterate `self.strategies_handler.strategies`, mapping each
  `strategy.subscribed_portfolios` id → extend with `strategy.tickers` (dedup,
  order-preserving).

Pass all three into `print_metrics_summary`. Guard for an empty/None `dates` so the
period line is simply omitted rather than raising.

## Testing

- Unit tests for each new metric function (happy + empty guard) in `test_metrics.py`.
- A `format_backtest_summary` rendering test (names, `%` vs ratio, `inf` pass-through,
  duration formatting, ticker truncation, empty-portfolio path).
- No test asserts on `print_metrics_summary`'s printed text today, so the output
  change breaks nothing. Run `make test-unit` (reporting) + the oracle test
  (`tests/integration/test_backtest_oracle.py`) to confirm oracle-inertness.

## Risks

- **Oracle drift:** none expected — no artifact bytes change. Mitigation: run the
  byte-exact oracle test after the change.
- **`filterwarnings=["error"]`:** new metric functions must use guarded, pandas-2-safe
  idioms (`.iloc`, explicit empty guards) — same discipline as the existing module.
- **Indentation:** `reporting/` and `summary.py` are 4-space; `trading_system/` runner
  + system modules are **tabs**. Match each file (CLAUDE.md hazard).
