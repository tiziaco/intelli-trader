---
phase: 08-m5c-cross-validation-final-oracle
plan: 05
subsystem: tooling
tags: [cross-validation, reference-engines, backtesting, backtrader, force-match, ta-indicators, D-01, D-03, D-10, M5-10]

# Dependency graph
requires:
  - phase: 08-m5c-cross-validation-final-oracle
    plan: 04
    provides: "Pinned + smoke-verified gating engines backtesting==0.6.5 + backtrader==1.9.78.123 (plain, no fork) — the known-working versions this harness builds against"
provides:
  - "scripts/crossval/indicators.py — shared `ta`-indicator precompute (compute_indicators: SMA(50)/SMA(100)/MACD-hist(6,12,3) via iTrader's verbatim ta.trend calls) + Binance-format golden-CSV loader (load_golden_csv / load_golden_with_indicators) normalizing to lowercase OHLCV on a UTC DatetimeIndex sliced to 2018-01-01..2026-06-03"
  - "scripts/crossval/backtesting_py_run.py — FractionalBacktest force-match module exposing run(prices=None, indicators=None) -> (trade_log_df[entry_date,exit_date,side,realised_pnl], equity_series); 134 trades, final_equity 46027.30"
  - "scripts/crossval/backtrader_run.py — custom-float-Sizer force-match module exposing the same uniform run() contract; 134 trades, final_equity 46189.8773 (matches iTrader golden to ~10 decimals)"
  - "scripts/crossval/__init__.py — script-only package marker (D-10)"
affects: [08-06-nautilus-run, 08-07-cross-validate-orchestrator]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "D-03 inject-identical-indicators: compute SMA/MACD ONCE via iTrader's exact ta calls, feed the SAME arrays to every engine (self.I for backtesting.py; extra PandasData lines for backtrader) — indicator-library divergence collapses to zero by construction"
    - "Fractional-units landmine fix: backtesting.py uses FractionalBacktest (fractional_unit=1e-6); backtrader uses a CUSTOM bt.Sizer returning a FLOAT 0.95*cash/price (NOT PercentSizer which int-floors to 0 BTC)"
    - "Uniform engine contract run(prices=None, indicators=None) -> (trade_log_df, equity_series): None loads/computes internally (standalone/verify); injected args used as-is (orchestrator path)"
    - "Script-only isolation (D-10): engine imports live only in scripts/crossval/*; never under tests/ or itrader/ — keeps filterwarnings=['error'] suite contract intact"

key-files:
  created:
    - "scripts/crossval/__init__.py — package marker; documents the D-10 script-only isolation rule"
    - "scripts/crossval/indicators.py — load_golden_csv + compute_indicators + load_golden_with_indicators + the SHORT/LONG/FAST/SLOW/WIN/MIN_BARS param constants (single source for both engines); imports only pandas + ta + run_backtest constants"
    - "scripts/crossval/backtesting_py_run.py — SMAMACDBacktesting(Strategy) + run(); FractionalBacktest with D-01 force-match kwargs"
    - "scripts/crossval/backtrader_run.py — FractionalSizer + GoldenPandasData + SMAMACDBacktrader + run()"
  modified: []

key-decisions:
  - "finalize_trades=False (backtesting.py): iTrader's 134 are CLOSED positions and the golden run ends flat (last golden trade exits 2026-06-03, the final bar). Finalizing an open final trade would mis-count; left a code comment that 08-07 confirms final-open-trade handling against the frozen oracle."
  - "FractionalBacktest rescales prices internally, which also rescales the injected SMA/MACD columns — but every signal comparison (sma_short vs sma_long; macd_hist vs 0) is scale-invariant, so injected-array semantics are preserved. Documented inline."
  - "SMA computed over the FULL close series (not the strategy's per-bar windowed slice): a rolling SMA(window) value depends only on the trailing `window` bars, so full-series rolling gives per-bar-identical values; MACD already uses the full close series in the strategy. The slicing in SMA_MACD_strategy is a perf optimization, not a semantic one."
  - "Golden-CSV loader normalizes to a tz-aware UTC DatetimeIndex; backtrader's PandasData requires tz-naive datetimes so run() tz_localize(None) only at the feed edge. Cross-engine timestamp-tz alignment is 08-07's reconcile concern."

patterns-established:
  - "When building a pandas frame from Series that carry their own (non-matching) index while passing a new `index=`, use `.to_numpy()` on each Series so the new index REPLACES the source index rather than reindexing against it (which silently yields all-NaN)."

requirements-completed: [M5-10]

# Metrics
duration: 4min
completed: 2026-06-08
---

# Phase 8 Plan 05: Cross-Validation Force-Match Harness Summary

**Built the two gating reference-engine force-match modules + the shared `ta`-indicator precompute that feeds them. `scripts/crossval/indicators.py` computes SMA(50)/SMA(100)/MACD-hist(6,12,3) ONCE via iTrader's verbatim `ta.trend` calls and loads the golden BTCUSD CSV (Binance format → lowercase OHLCV, UTC index, 2018-01-01..2026-06-03 window). `backtesting_py_run.py` (FractionalBacktest) and `backtrader_run.py` (custom float Sizer) each consume those IDENTICAL injected arrays (D-03 — indicator divergence is zero by construction), replicate the SMA_MACD filter-gates-both-entry-AND-exit QUIRK verbatim with next-bar-open fills (D-01), and expose the uniform `run(prices=None, indicators=None) -> (trade_log_df[entry_date,exit_date,side,realised_pnl], equity_series)` contract the 08-07 orchestrator consumes. Both engines return EXACTLY 134 trades — matching iTrader's frozen golden count (the primary D-02 trade-level gate). backtrader's final_equity 46189.8773 matches iTrader's golden 46189.87730727451 to ~10 decimals; backtesting.py's 46027.30 is within ~0.35% (D-04 secondary tolerance). Engines are script-only (D-10): the 724-test suite still collects clean with no crossval/engine import under tests/ or itrader/.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-06-08T14:27Z
- **Completed:** 2026-06-08T14:31Z
- **Tasks:** 3 (shared precompute; backtesting.py module; backtrader module)
- **Files created:** 4 (`scripts/crossval/{__init__.py, indicators.py, backtesting_py_run.py, backtrader_run.py}`)

## Accomplishments

- **Task 1 — shared `ta`-indicator precompute + golden-CSV loader.** `indicators.py` provides `load_golden_csv` (Binance CSV → lowercase `open/high/low/close/volume`, UTC `DatetimeIndex` from `Open time`, sorted, sliced inclusive to the run_backtest.py window) and `compute_indicators` (SMA short/long via `trend.SMAIndicator(close, window, True).sma_indicator()`, MACD-hist via `trend.MACD(..., window_fast=6, window_slow=12, window_sign=3, fillna=False).macd_diff()` — verbatim iTrader calls, no hand-rolled math), plus `load_golden_with_indicators` joining them into one index-aligned frame. Param constants `SHORT/LONG/FAST/SLOW/WIN/MIN_BARS` are module-level so both engine modules share one source. Imports only pandas + ta + the run_backtest constants — no engine import. Verify: `OK 3076 bars`.
- **Task 2 — backtesting.py FractionalBacktest module.** `SMAMACDBacktesting(Strategy)` registers the injected arrays via `self.I(...)` (no engine-native indicators) and replicates THE QUIRK verbatim in `next()` (SMA filter gates both entry and the nested-elif exit; held long not closed when filter False; `MIN_BARS` warm-up gate). `run()` builds `FractionalBacktest(cash=10_000, commission=0.0, spread=0.0, margin=1.0, trade_on_close=False, exclusive_orders=True, finalize_trades=False, fractional_unit=1e-6)` and normalizes `stats['_trades']` → `entry_date/exit_date/side/realised_pnl`, returning `stats['_equity_curve']['Equity']`. **134 trades** (matches iTrader golden), final_equity 46027.30.
- **Task 3 — backtrader custom-float-sizer module.** `FractionalSizer(bt.Sizer)._getsizing` returns a FLOAT `0.95*cash/price` (the landmine fix — `PercentSizer` would int-floor to 0 BTC); `GoldenPandasData(bt.feeds.PandasData)` feeds the three injected `ta` arrays as extra lines; `SMAMACDBacktrader(bt.Strategy).next()` replicates THE QUIRK verbatim with the `MIN_BARS` gate; `notify_trade` captures per-trade entry/exit datetimes + pnl and equity is recorded per-bar via `broker.getvalue()`. Broker cash 10000, commission 0, default next-bar-open fills (`set_coc(False)`/`set_coo(False)`). **134 trades**, final_equity **46189.877307274444** — matches iTrader's golden 46189.87730727451 to ~10 decimal places.

## Force-Match Results (handoff to 08-07)

| Engine | Trades | Final equity | vs iTrader golden (46189.87730727451) |
|---|---|---|---|
| iTrader (frozen golden) | 134 | 46189.87730727451 | — |
| backtrader 1.9.78.123 | 134 | 46189.877307274444 | match to ~10 decimals |
| backtesting.py 0.6.5 | 134 | 46027.30313542994 | ~0.35% (within D-04 ~1% secondary tolerance) |

Both engines hit the **primary D-02 gate** (134 trades, exact). 08-07 will run these raw frames through `itrader.reporting.metrics` for the full headline reconciliation + per-divergence root-cause.

## Task Commits

1. **Task 1 (shared precompute):** `db54439` (feat) — `scripts/crossval/__init__.py` + `scripts/crossval/indicators.py`.
2. **Task 2 (backtesting.py):** `1d3a0b3` (feat) — `scripts/crossval/backtesting_py_run.py`.
3. **Task 3 (backtrader):** `a04c655` (feat) — `scripts/crossval/backtrader_run.py`.
4. **Plan metadata:** final docs commit (this SUMMARY + STATE + ROADMAP + REQUIREMENTS).

## Files Created/Modified

- `scripts/crossval/__init__.py` (created) — package marker documenting the D-10 script-only isolation rule.
- `scripts/crossval/indicators.py` (created, 145 lines) — shared precompute + golden-CSV loader; pandas + ta + run_backtest constants only.
- `scripts/crossval/backtesting_py_run.py` (created, 170 lines) — FractionalBacktest force-match module.
- `scripts/crossval/backtrader_run.py` (created, 198 lines) — custom-float-sizer force-match module.

## Decisions Made

- **`finalize_trades=False` (backtesting.py).** iTrader's 134 trades are closed positions and the golden run ends flat (last golden trade exits on the final bar 2026-06-03). Finalizing an open final trade would mis-count; the code comments that 08-07 confirms final-open-trade handling against the frozen oracle. Empirically 134 trades resulted with `finalize_trades=False` — exact match.
- **Scale-invariance under FractionalBacktest rescaling.** FractionalBacktest rescales prices internally (also rescaling injected SMA/MACD columns), but every signal comparison is scale-invariant (`sma_short` vs `sma_long`; `macd_hist` vs 0), so the injected-array semantics are preserved. Documented inline.
- **SMA over the full close series.** The strategy slices the close window before SMA for performance; a rolling SMA(window) depends only on the trailing `window` bars, so full-series rolling yields per-bar-identical values. MACD already uses the full close series. The precompute computes over the full series — semantically identical, no per-bar slicing needed.
- **Frame-construction NaN trap fixed.** Initial `load_golden_csv` passed `pd.Series` (with the source RangeIndex) into a `pd.DataFrame(..., index=datetime_index)` constructor, which reindexed the Series against the new index → all-NaN `close`. Fixed by passing `.to_numpy()` so the new index replaces rather than aligns. (Rule 1 auto-fix, caught by the Task 1 verify before commit.)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] All-NaN OHLCV from index-misaligned frame construction**
- **Found during:** Task 1 (verify failed on `df['close'].notna().all()`)
- **Issue:** Building `pd.DataFrame({...Series...}, index=datetime_index)` reindexed each source Series (default RangeIndex) against the datetime index, silently producing all-NaN columns; `compute_indicators` then yielded all-NaN indicators too.
- **Fix:** Pass `.to_numpy()` for each OHLCV column so the new datetime index REPLACES the source index instead of aligning against it.
- **Files modified:** `scripts/crossval/indicators.py`
- **Commit:** `db54439` (fixed before Task 1 was committed — never shipped broken)

No other deviations — the force-match plan executed as written; both engines matched iTrader's trade count exactly on the first run after the precompute was correct.

## Known Stubs

None — both engine modules run end-to-end on the real golden data, returning non-empty (134-trade) trade logs and full equity curves (3076 / 3062 points). No placeholder data, no TODO/FIXME stubs.

## Threat Flags

None — no new security-relevant surface. These are offline reference-engine harness modules reading a fixed local golden CSV and producing in-memory frames; no network, no untrusted input, no secrets, no result-bearing engine path mutated. The T-08-SC (supply-chain) and T-08-KO (test-suite isolation) threats from the register are mitigated as planned: engines were vetted/pinned in 08-04, and the D-10 script-only guard (`grep crossval tests/` empty; no engine import under tests/ or itrader/) holds.

## Verification

- `poetry run python -c "from scripts.crossval.indicators import load_golden_with_indicators; ..."` → `OK 3076 bars` (windowed bar+indicator frame, lowercase OHLCV + sma_short/sma_long/macd_hist, monotonic index, >1000 non-NaN sma_long).
- `poetry run python -c "from scripts.crossval.backtesting_py_run import run; ..."` → `trades 134 final_equity 46027.30313542994`, exit 0 (normalized columns present, equity >1000 points, >0 trades = fractional sizing proven).
- `poetry run python -c "from scripts.crossval.backtrader_run import run; ..."` → `trades 134 final_equity 46189.877307274444`, exit 0 (normalized columns present, equity >1000 points, fractional BTC sizing).
- `grep -rn "crossval" tests/` → empty (exit 1): D-10 keep-out-of-tests guard holds.
- `grep -rn "import backtesting|import backtrader" tests/ itrader/` → empty (exit 1): engines script-only.
- `poetry run pytest tests/ -q --collect-only` → 724 tests collected, exit 0 (suite unaffected; filterwarnings=['error'] contract intact).

## Handoff to 08-06 / 08-07

- **08-06 (Nautilus, non-gating):** extends `scripts/crossval/__init__.py` (already created here) and adds `scripts/crossval/nautilus_run.py` exposing the same uniform `run(prices=None, indicators=None)` contract; consumes the shared `indicators.load_golden_with_indicators` / `compute_indicators`. Note: 08-04 dropped `nautilus-trader` (python `<3.15` cap conflicts with repo `^3.13`), so 08-06 must guard its import and degrade gracefully.
- **08-07 (orchestrator):** import `run` from both engine modules, precompute the shared `ta` arrays once via `indicators`, pass them to each `run(prices=..., indicators=...)`, and reconcile the returned `(trade_log_df, equity_series)` against `tests/golden/{trades.csv,equity.csv,summary.json}` through `itrader.reporting.metrics` (recompute headline on identical formulas — do NOT trust engine-native Sharpe/CAGR). The returned `trade_log_df` is already in the `[entry_date, exit_date, side, realised_pnl]` reconcile shape. Both engines hit 134 trades exactly; backtrader equity is essentially exact, backtesting.py within ~0.35%.

## Self-Check: PASSED

- Files: `scripts/crossval/__init__.py`, `scripts/crossval/indicators.py`, `scripts/crossval/backtesting_py_run.py`, `scripts/crossval/backtrader_run.py` — all FOUND on disk (line counts 145/170/198 exceed plan min_lines 40/60/70).
- Commits: `db54439` (Task 1), `1d3a0b3` (Task 2), `a04c655` (Task 3) — verified present in git history.
- Force-match: both engines return 134 trades; backtrader final_equity matches iTrader golden to ~10 decimals; suite collects 724 clean; D-10 isolation guards empty.

---
*Phase: 08-m5c-cross-validation-final-oracle*
*Completed: 2026-06-08*
