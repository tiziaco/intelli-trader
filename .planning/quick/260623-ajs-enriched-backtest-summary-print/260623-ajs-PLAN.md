---
phase: quick-260623-ajs
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - itrader/reporting/metrics.py
  - itrader/reporting/summary.py
  - itrader/trading_system/backtest_runner.py
  - itrader/trading_system/backtest_trading_system.py
  - tests/unit/reporting/test_metrics.py
autonomous: true
requirements: [SUMMARY-PRINT]

must_haves:
  truths:
    - "An end-of-run backtest prints a grouped Capital / Trades / Risk-Return block per portfolio under one shared run-level header (Period + Duration)."
    - "Nine new derived metric functions exist in reporting/metrics.py, each guarding empty/degenerate input to 0.0 with no warning under filterwarnings=['error']."
    - "format_backtest_summary renders %-scaled return/cagr/max_drawdown/win_rate/exposure_time, raw 4dp sharpe/sortino/profit_factor/calmar, thousands-sep currency, human duration, and a +N-more-truncated instrument list."
    - "The existing format_metrics function and its tests are UNCHANGED; the existing logger.info('Backtest summary', ...) and logger.info('Backtest completed', ...) lines are kept."
    - "The byte-exact SMA_MACD oracle (134 trades / final_equity 46189.87730727451) is unchanged — this is display-only / oracle-inert."
  artifacts:
    - path: "itrader/reporting/metrics.py"
      provides: "total_return, avg_trade_pnl, avg_win, avg_loss, best_trade, worst_trade, avg_trade_duration, exposure_time, calmar + format_backtest_summary"
      contains: "def format_backtest_summary"
    - path: "itrader/reporting/summary.py"
      provides: "print_metrics_summary with kw-only duration_seconds/period/portfolio_tickers params"
      contains: "format_backtest_summary"
    - path: "itrader/trading_system/backtest_runner.py"
      provides: "self.duration_seconds attribute set after the run"
      contains: "self.duration_seconds"
    - path: "itrader/trading_system/backtest_trading_system.py"
      provides: "run() assembles duration/period/portfolio_tickers and passes them to print_metrics_summary"
      contains: "portfolio_tickers"
    - path: "tests/unit/reporting/test_metrics.py"
      provides: "Unit tests for the nine new metrics + a format_backtest_summary rendering test"
      contains: "format_backtest_summary"
  key_links:
    - from: "itrader/trading_system/backtest_trading_system.py::run"
      to: "itrader/reporting/summary.py::print_metrics_summary"
      via: "keyword args duration_seconds=, period=, portfolio_tickers="
      pattern: "print_metrics_summary\\("
    - from: "itrader/reporting/summary.py::print_metrics_summary"
      to: "itrader/reporting/metrics.py::format_backtest_summary"
      via: "formatter call after computing per-portfolio metrics"
      pattern: "format_backtest_summary"
    - from: "itrader/trading_system/backtest_runner.py"
      to: "itrader/trading_system/backtest_trading_system.py::run"
      via: "self.runner.duration_seconds read post-run"
      pattern: "duration_seconds"
---

<objective>
Implement the enriched end-of-run backtest summary print exactly as specified in the
approved design spec `docs/superpowers/specs/2026-06-23-backtest-summary-print-design.md`.

Replace the six-line `0.4f` per-portfolio printout with a grouped **Capital / Trades /
Risk-Return** block under a shared run-level header (Period + Duration), sourced from
nine new pure metric functions and a new `format_backtest_summary` formatter. Thread the
already-computed run duration, the date span, and the per-portfolio instrument universe
into the printer.

Purpose: Make the backtest console output actually informative without touching any
artifact bytes — this is display-only / oracle-inert (the W4-07 contract).
Output: Enriched console summary; nine new guarded metrics; new formatter; new unit tests.

NON-NEGOTIABLE SCOPE LOCKS (from the spec — do NOT redesign):
- Per-portfolio only. Per-strategy breakdown is DEFERRED (trades carry no strategy_id).
- NO new artifact files — `summary.json` and every golden are unchanged.
- NO timeframe line (the Period span conveys it).
- `format_metrics` is left UNTOUCHED (it has tests); the new block is a separate function.
- The formatter is named `format_backtest_summary`.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@docs/superpowers/specs/2026-06-23-backtest-summary-print-design.md
@.planning/STATE.md
@./CLAUDE.md
@itrader/reporting/metrics.py
@itrader/reporting/summary.py
@itrader/reporting/frames.py
@itrader/trading_system/backtest_runner.py
@tests/unit/reporting/test_metrics.py

<interfaces>
<!-- Contracts the executor needs — extracted from the codebase. Use directly; no exploration needed. -->

Equity-curve frame columns (itrader/reporting/frames.py::EQUITY_COLUMNS):
  timestamp, total_equity, cash_balance, positions_value, unrealized_pnl,
  realized_pnl, total_pnl, open_positions_count, portfolio_return
  -> `total_equity` is the equity Series; `open_positions_count` is the exposure column.

Trade-log frame columns (itrader/reporting/frames.py::TRADE_COLUMNS):
  entry_date, exit_date, side, net_quantity, avg_price, avg_bought, avg_sold,
  total_bought, total_sold, realised_pnl, pair
  -> `realised_pnl` is the per-trade PnL; `entry_date`/`exit_date` are the trade timestamps.

Existing pure metrics already in metrics.py (reuse, do not duplicate):
  compute_returns(equity) -> pd.Series
  max_drawdown(equity: pd.Series) -> float   # NEGATIVE sign convention
  cagr(equity: pd.Series, periods=PERIODS) -> float
  sharpe / sortino / profit_factor / win_rate

Existing formatter, leave UNTOUCHED:
  format_metrics(metrics: dict[str, float], title="Backtest metrics") -> str

print_metrics_summary current signature (itrader/reporting/summary.py):
  def print_metrics_summary(portfolios: Any, logger: Any) -> None

Strategy / Portfolio attributes for header assembly (confirmed in codebase):
  strategy.tickers: list[str]
  strategy.subscribed_portfolios: list[PortfolioId | int]
  portfolio.portfolio_id  /  portfolio.name  /  portfolio.cash (Decimal)  /  portfolio.total_equity (Decimal)
  engine.time_generator.dates  (pd.Index of bar dates; may be empty/None)
  self.runner.duration_seconds  (float | None, new attr added by this plan)
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Add nine guarded metric functions to reporting/metrics.py</name>
  <files>itrader/reporting/metrics.py, tests/unit/reporting/test_metrics.py</files>
  <behavior>
    For each new function (happy path + empty/degenerate guard), mirroring the existing
    hand-computed fixture style in test_metrics.py:
    - total_return: equity [100, 121] -> 0.21; empty -> 0.0; start<=0 -> 0.0.
    - avg_trade_pnl: pnl [10, -5, 20] -> 25/3; empty -> 0.0.
    - avg_win: mean over pnl>0 of [10,-5,20] -> 15.0; no winners -> 0.0.
    - avg_loss: mean over pnl<0 (negative) of [10,-5,20] -> -5.0; no losers -> 0.0.
    - best_trade: max([10,-5,20]) -> 20.0; empty -> 0.0.
    - worst_trade: min([10,-5,20]) -> -5.0; empty -> 0.0.
    - avg_trade_duration: mean (exit_date - entry_date) in SECONDS as float; empty -> 0.0.
      Build the fixture with pd.Timestamp entry/exit columns; assert the hand-computed
      mean seconds.
    - exposure_time: takes the equity FRAME; (open_positions_count > 0).mean() in [0,1];
      empty -> 0.0. Fixture: a small DataFrame with an open_positions_count column.
    - calmar: cagr(equity)/abs(max_drawdown(equity)); drawdown==0 -> 0.0. Assert against
      the existing EQUITY fixture composed via the already-tested cagr/max_drawdown.
  </behavior>
  <action>
    Add nine new pure, stateless functions to itrader/reporting/metrics.py (4-SPACE indent,
    match the file), each guarding empty/degenerate input to 0.0 using pandas-2-safe idioms
    (.iloc indexing, explicit empty guards, whole-column ops) so nothing trips
    filterwarnings=['error']. Per the spec §1:
      - total_return(equity: pd.Series) -> float: final/start - 1; 0.0 if empty or start<=0
        (use .iloc[0]/.iloc[-1], mirror cagr's guards).
      - avg_trade_pnl(trades: pd.DataFrame) -> float: mean realised_pnl; 0.0 if empty.
      - avg_win(trades) -> float: mean realised_pnl over pnl>0; 0.0 if no winners.
      - avg_loss(trades) -> float: mean realised_pnl over pnl<0 (NEGATIVE value); 0.0 if none.
      - best_trade(trades) -> float: max realised_pnl; 0.0 if empty.
      - worst_trade(trades) -> float: min realised_pnl; 0.0 if empty.
      - avg_trade_duration(trades) -> float: mean of (exit_date - entry_date) in SECONDS
        (float); 0.0 if empty. Compute via (trades['exit_date'] - trades['entry_date'])
        .dt.total_seconds().mean(); the formatter renders the human form, not this function.
      - exposure_time(equity_frame: pd.DataFrame) -> float: (open_positions_count > 0).mean()
        as a fraction in [0,1]; 0.0 if empty. Takes the FRAME (needs open_positions_count),
        NOT the equity Series.
      - calmar(equity: pd.Series) -> float: cagr(equity) / abs(max_drawdown(equity)); 0.0 if
        drawdown is 0. Reuse the existing cagr/max_drawdown functions.
    Keep the module's purity contract: no itrader imports, numpy/pandas only, no print/I/O
    (the existing test_metrics_module_imports_numpy_pandas_only / _is_pure_no_print guards
    still apply). Add the matching tests in tests/unit/reporting/test_metrics.py and import
    the new names alongside the existing imports.
  </action>
  <verify>
    <automated>poetry run pytest tests/unit/reporting/test_metrics.py -q</automated>
  </verify>
  <done>Nine new functions exist and are tested (happy + empty guard each); the full reporting unit-test file passes; existing format_metrics tests still pass; no itrader import added to metrics.py.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Add format_backtest_summary to metrics.py and rewire print_metrics_summary</name>
  <files>itrader/reporting/metrics.py, itrader/reporting/summary.py, tests/unit/reporting/test_metrics.py</files>
  <behavior>
    A format_backtest_summary rendering test asserting (per spec §2):
    - Percentages: total_return / cagr / max_drawdown / win_rate / exposure_time render as
      value*100 with '%' (signed where natural — e.g. '+99.11%', '-53.83%').
    - Ratios: sharpe / sortino / profit_factor / calmar render raw %.4f; inf passes through
      (assert 'inf' appears, no raise).
    - Currency: thousands separators, 2dp (e.g. '10,000.00'); signed for return/PnL.
    - Duration: seconds -> human 'Nd Nh' / 'Nh Nm' / 'Nm Ns' form.
    - Instrument list: comma-joined, '+N more' past the cap (cap 6); line OMITTED if empty.
    - Empty-portfolio path: a portfolio with zero trades / empty equity renders without raising.
    Build the test by calling format_backtest_summary with an explicit per-portfolio value bag
    plus the run-level header values (period tuple, duration, ticker list).
  </behavior>
  <action>
    In itrader/reporting/metrics.py (4-SPACE indent), add format_backtest_summary as a sibling
    to the UNTOUCHED format_metrics. Pure string building, no I/O. It consumes a small
    per-portfolio value bag (the six existing metrics + the nine new ones + capital values:
    starting_cash, final_cash, final_equity, total_return, realised_pnl, trade count) plus the
    run-level header values (period tuple (start, end, bar_count), duration_seconds, and the
    per-portfolio instrument ticker list). Render the grouped block from the spec mockup
    (§ "Output (target)"): a Period + Duration header, then per-portfolio
    Capital / Trades / Risk-Return groups. Rendering rules per spec §2:
      - Currency: thousands separators + 2dp ('{:,.2f}'); signed ('{:+,.2f}') for return/PnL.
      - Percentages (total_return, cagr, max_drawdown, win_rate, exposure_time): value*100 with
        '%', signed where natural.
      - Ratios (sharpe, sortino, profit_factor, calmar): raw '%.4f'; inf passes through.
      - Duration: seconds -> 'Nd Nh' / 'Nh Nm' / 'Nm Ns' human form (write a small helper).
      - Instrument list: comma-joined; '+N more' past a cap of 6; OMIT the line if empty.
      - Period line: omit if the period tuple is None.
    Decide the exact signature at implementation time, but keep it pure (no I/O, no itrader
    imports). DO NOT modify format_metrics.

    Then rewire itrader/reporting/summary.py::print_metrics_summary (4-SPACE indent): add the
    kw-only optional params exactly as the spec §3 signature shows —
    duration_seconds: float | None = None, period: tuple[Any, Any, int] | None = None,
    portfolio_tickers: dict[Any, list[str]] | None = None — so EVERY existing caller (incl. the
    oracle) is preserved by defaults. In the body, for each portfolio compute the new metrics
    alongside the existing six (starting cash = equity.iloc[0] per spec; final cash/equity via
    portfolio.cash / portfolio.total_equity with Decimal->float ONLY at the print edge, no money
    arithmetic), look up the portfolio's tickers via portfolio_tickers.get(portfolio.portfolio_id)
    (default empty), call format_backtest_summary, and print. KEEP the existing
    logger.info('Backtest summary', ...) line. Preserve the duck-typed purity contract (no handler
    imports). Build the run-level header once (not per portfolio).
  </action>
  <verify>
    <automated>poetry run pytest tests/unit/reporting/test_metrics.py -q</automated>
  </verify>
  <done>format_backtest_summary exists and is tested (% vs ratio, inf pass-through, duration formatting, currency, ticker truncation, empty-portfolio path); format_metrics is byte-unchanged and its tests pass; print_metrics_summary has the three kw-only params with defaults that preserve existing callers; the existing logger.info('Backtest summary', ...) line remains.</done>
</task>

<task type="auto">
  <name>Task 3: Thread duration + period + portfolio_tickers from the runner/system into the printer</name>
  <files>itrader/trading_system/backtest_runner.py, itrader/trading_system/backtest_trading_system.py</files>
  <action>
    Both files are TAB-indented (trading_system/ convention) — match exactly; do NOT normalize.

    In itrader/trading_system/backtest_runner.py:
      - Initialise self.duration_seconds: float | None = None in __init__.
      - In _run_backtest, AFTER the existing duration computation, set
        self.duration_seconds = duration.total_seconds() beside the existing
        logger.info('Backtest completed', duration_seconds=...) line. KEEP that log line.

    In itrader/trading_system/backtest_trading_system.py::run, before calling
    print_metrics_summary (currently in the `if print_summary:` block), assemble the three
    header inputs from reachable handles (spec §5):
      - duration = self.runner.duration_seconds
      - dates = self.engine.time_generator.dates; if dates is None or empty, set period = None
        (so the Period line is omitted, never raising). Otherwise
        period = (dates[0], dates[-1], len(dates)).
      - portfolio_tickers: a dict keyed by portfolio.portfolio_id mapping to a deduped,
        order-preserving list of tickers. Iterate self.strategies_handler.strategies; for each
        strategy, for each pid in strategy.subscribed_portfolios, extend that pid's list with
        strategy.tickers (dedup while preserving first-seen order). NOTE: subscribed_portfolios
        holds PortfolioId|int handles — key by those same values; portfolio.portfolio_id used in
        the printer lookup must match the key type used here (both are the PortfolioId handle).
    Pass all three into print_metrics_summary as
    duration_seconds=duration, period=period, portfolio_tickers=portfolio_tickers.
    Guard for an empty/None dates index so the period line is simply omitted rather than raising.
  </action>
  <verify>
    <automated>poetry run pytest tests/unit/reporting tests/integration/test_backtest_oracle.py -q</automated>
  </verify>
  <done>self.runner.duration_seconds is set after the run; run() assembles duration/period/portfolio_tickers and passes them to print_metrics_summary; both existing log lines are kept; the byte-exact oracle test passes (no artifact bytes changed); reporting unit tests pass.</done>
</task>

</tasks>

<verification>
Run the reporting unit tests and the byte-exact oracle together:

```
poetry run pytest tests/unit/reporting tests/integration/test_backtest_oracle.py -q
```

Oracle-inertness: the oracle test (SMA_MACD, 134 trades / final_equity 46189.87730727451)
MUST still pass — this change is display-only and writes no artifact bytes. Confirm
filterwarnings=['error'] is not tripped (any warning fails the suite). Indentation: confirm
reporting/*.py + tests stayed 4-space and trading_system/*.py stayed TAB.
</verification>

<success_criteria>
- Nine new guarded metric functions in reporting/metrics.py, each tested (happy + empty guard).
- format_backtest_summary renders the grouped Capital/Trades/Risk-Return block per spec, tested
  for % vs ratio, inf pass-through, duration formatting, ticker truncation, empty-portfolio path.
- format_metrics is byte-unchanged and its tests pass.
- print_metrics_summary gains the three kw-only params with caller-preserving defaults; the
  existing logger.info('Backtest summary', ...) line is kept.
- backtest_runner stores duration_seconds (existing 'Backtest completed' log kept);
  backtest_trading_system.run assembles and passes duration/period/portfolio_tickers.
- The byte-exact SMA_MACD oracle is unchanged (oracle-inert).
- No new float-for-money arithmetic (Decimal->float only at the print edge); no itrader import
  added to metrics.py.
</success_criteria>

<output>
Create `.planning/quick/260623-ajs-enriched-backtest-summary-print/260623-ajs-SUMMARY.md` when done
</output>
