---
phase: 08-m5c-cross-validation-final-oracle
reviewed: 2026-06-08T15:45:24Z
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
  warning: 5
  info: 6
  total: 11
status: issues_found
---

# Phase 8: Code Review Report

**Reviewed:** 2026-06-08T15:45:24Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Reviewed the Phase 8 (M5c) production Decimal cleanup (`itrader/*`) and the offline
cross-validation harness (`scripts/crossval/*`, `scripts/cross_validate.py`), at the
two bars set by the phase context: production source judged for correctness
(Decimal/float boundaries, type/transition correctness), the script harness judged
as offline diagnostic tooling.

The 49 unit tests across the three reviewed test files pass, and the targeted
Decimal regression locks are well-constructed (notably `test_cash_check_is_decimal_exact_at_boundary`,
which genuinely distinguishes Decimal arithmetic from float narrowing). The
production Decimal retype on `Portfolio.total_*` and the validator golden-path
comparisons is clean: no float-money leaks remain on the golden run path, and the
`Decimal(str(...))` threshold-wrapping discipline (never `Decimal(float)`) is
followed consistently.

**No BLOCKER findings.** The production changes are correct on the golden path.

The findings below are: (1) a pre-existing but now-touched mathematically-wrong
`annualized_return` formula in `MetricsManager` that the Decimal edit passed through
unchanged; (2) a residual float-narrowing path in `MetricsManager` statistical
metrics that re-introduces binary-float artifacts on a Decimal source (acceptable
per the stated D-06 ratio boundary, but the round-trip is sloppier than it needs to
be); (3) a malformed-markdown truncation row in the reconcile table builder; (4) a
cross-engine equity-length asymmetry that makes the CAGR/Sharpe metric comparison
not strictly apples-to-apples; plus quality/dead-code items. None of these block the
production money correctness that this phase is about, but several degrade the
trustworthiness of the cross-validation evidence the phase is meant to produce.

## Warnings

### WR-01: `annualized_return` uses a mathematically incoherent compounding formula

**File:** `itrader/portfolio_handler/metrics/metrics_manager.py:543-547`
**Issue:** The annualized return is computed as:
```python
days = (end_date - start_date).days
daily_return = float(total_return) / days       # period total divided by calendar days
annualized_return = Decimal(str((1 + daily_return) ** 365 - 1))
```
`total_return` is the *whole-period* simple return (e.g. 0.07 over the window).
Dividing it by `days` does NOT yield a per-day return — it yields a linear average
that is then compounded 365×, which is neither a geometric daily rate nor a correct
annualization. The correct geometric form is
`(1 + total_return) ** (365 / days) - 1`. The current formula systematically
mis-states `annualized_return` and, downstream, `sharpe_ratio` (which divides
`annualized_return - risk_free_rate` by `volatility` at line 558-559). This is
pre-existing logic, but the M5-10 edit retyped this exact block to Decimal and
re-blessed it, so it is in scope for this review. Note this code is NOT the golden
oracle path (`run_backtest.py`/`reporting.metrics.cagr` is), which limits blast
radius — but `MetricsManager.calculate_performance_metrics` is live, test-covered,
and exported via `export_metrics_to_dict`, so any consumer of those numbers is wrong.
**Fix:**
```python
days = (end_date - start_date).days
annualized_return = Decimal('0.00')
if days > 0 and initial_equity > 0:
    # Geometric annualization of the period total return.
    annualized_return = Decimal(str((1.0 + float(total_return)) ** (365.0 / days) - 1.0))
```

### WR-02: Decimal money is narrowed to float and back to Decimal, re-introducing binary-float artifacts in `daily_returns`

**File:** `itrader/portfolio_handler/metrics/metrics_manager.py:526-532`
**Issue:** The phase rule is "Money = Decimal end-to-end; float only at ratio
inputs." Here the ratio is computed in float and then *re-wrapped into Decimal* and
stored as the canonical `daily_returns` (a `List[Decimal]` per the `PerformanceMetrics`
dataclass):
```python
prev_equity = float(snapshots[i-1].total_equity)
curr_equity = float(snapshots[i].total_equity)
if prev_equity > 0:
    daily_return = (curr_equity - prev_equity) / prev_equity   # float division
    daily_returns.append(Decimal(str(daily_return)))           # float artifact frozen into Decimal
```
The `float → Decimal(str(float))` round-trip bakes a binary-float rounding artifact
into a value the dataclass advertises as Decimal, defeating the point of the Decimal
typing for `daily_returns`. Since the source (`total_equity`) is already Decimal, the
ratio can be computed in Decimal directly and stay exact. The same pattern repeats at
lines 540 (`total_return`), 565-567 (`win_rate`/`average_win`/`average_loss`). This
is below BLOCKER because the stated D-06 contract explicitly tolerates float at the
ratio metric boundary and these are not on the golden oracle path — but the Decimal
field type is misleading given the value inside it is float-derived.
**Fix:** Compute the period return in Decimal where the inputs are already Decimal:
```python
prev_equity = snapshots[i-1].total_equity   # Decimal
curr_equity = snapshots[i].total_equity      # Decimal
if prev_equity > 0:
    daily_returns.append((curr_equity - prev_equity) / prev_equity)
```
(volatility/statistics that genuinely require float can narrow at their own call site
without re-promoting to a Decimal field.)

### WR-03: Truncation footer emits a malformed Markdown row (wrong column count)

**File:** `scripts/crossval/reconcile.py:242-245`
**Issue:** `build_trade_table` builds a header with `cols = 1 + 2*len(sources) + len(engine_names)`
columns, but the truncation footer appends a 2-cell row:
```python
lines.append(f"| ... | _{len(aligned) - len(body)} aligned rows omitted_ |")
```
A 2-column row in an N-column Markdown table renders as a broken/ragged row in the
committed `CROSS-VALIDATION.md` evidence artifact. Since this file is the durable
human-facing evidence that iTrader's numbers are trustworthy, a malformed table
undercuts the artifact's credibility. Offline tooling, hence WARNING not BLOCKER.
**Fix:** Pad the footer to the full column width, e.g.:
```python
if max_rows and len(aligned) > len(body):
    omitted = len(aligned) - len(body)
    pad = ["" for _ in range(cols - 2)]
    lines.append("| ... | " + f"_{omitted} aligned rows omitted_" + " | " + " | ".join(pad) + " |")
```

### WR-04: Cross-engine CAGR/Sharpe comparison is not apples-to-apples — equity series have different lengths

**File:** `scripts/crossval/reconcile.py:47-69`; `scripts/crossval/backtrader_run.py:86-89`; `scripts/crossval/nautilus_run.py:211-222`
**Issue:** The phase's whole reason for existing is the D-04 "apples-to-apples"
guarantee: every engine's headline metrics are recomputed through
`itrader.reporting.metrics`. But `cagr` and the annualized `sharpe`/`sortino` depend
on the *length* of the equity series (`years = len(equity) / PERIODS` in
`metrics.py:115`; `sqrt(periods)` scaling in sharpe/sortino). The engines do NOT
produce equal-length equity series:
- backtrader records equity from **bar 0** including the 100-bar warm-up (`next()` appends every bar, `backtrader_run.py:87-89`).
- nautilus likewise records from the first `on_bar` (`nautilus_run.py:221-222`).
- iTrader's frozen `equity.csv` and backtesting.py's `stats['_equity_curve']` may
  start/align differently (iTrader records via `record_metrics` per ping; backtesting.py
  emits an equity point per bar).

A length delta of even a handful of bars shifts `years` and therefore CAGR, and the
`sqrt(365)` annualization makes Sharpe/Sortino length-sensitive too. The result is
that a flagged metric DIVERGE may be a harness artifact (unequal series length), not
a genuine engine-semantics divergence — exactly the false signal D-04 is supposed to
eliminate. This weakens the evidence value of the report. WARNING (offline evidence
tooling), not BLOCKER.
**Fix:** Normalize each engine's equity series to the same index/length before
`recompute_headline` (e.g. slice all to the post-warm-up window starting at the same
bar, or reindex to iTrader's equity index), or document explicitly in the report that
length-sensitive metrics are informational only and lean on the D-02 trade-level
primary gate.

### WR-05: `align_trades` aligns trades positionally by index — a single inserted/dropped trade cascades every subsequent row into SHIFT

**File:** `scripts/crossval/reconcile.py:147-193`
**Issue:** Trades are aligned purely by positional index `i` (`itrader_trades[i]` vs
`engine[i]`). If an engine produces one extra or one fewer trade early in the run,
every subsequent trade is compared against the wrong iTrader trade and flagged SHIFT,
producing a flood of false divergence stubs in the committed report and obscuring the
single real divergence. For a 134-trade golden run, one early off-by-one trade would
mark ~133 rows divergent. This is the classic alignment-by-position pitfall; a
date-anchored or sequence-alignment (LCS / nearest-entry-date matching) would localize
the divergence. Offline evidence tooling → WARNING.
**Fix:** Anchor alignment on entry_date proximity (match each iTrader trade to the
nearest engine trade within a ±N-bar tolerance) rather than raw positional index, so a
single insert/delete does not cascade. At minimum, when trade counts differ, note in
the report that positional alignment makes downstream rows unreliable.

## Info

### IN-01: Dead locals in cross-validation orchestrator (already noted)

**File:** `scripts/cross_validate.py:128 (param `itrader_headline`), 129 (param `engine_metrics`), 233 (`_itrader_equity`)`
**Issue:** `build_report` accepts `itrader_headline` and `engine_metrics` but never
references them in the body (the function only renders versions/tables/divergences).
`_itrader_equity` is unpacked from `load_itrader_frozen()` and never used. Confirmed
as accepted/known per phase context.
**Fix:** Drop the two unused `build_report` parameters and their call-site arguments;
discard the equity element with `_, _, itrader_headline = load_itrader_frozen()` only
if `itrader_headline` is still consumed (it is, by `build_metric_table`).

### IN-02: `_norm_ts` raises an exception type the caller does not guard

**File:** `scripts/crossval/reconcile.py:137-144`
**Issue:** `_norm_ts` calls `pd.Timestamp(value)` on arbitrary trade-cell values; a
malformed/unparseable cell raises `ValueError`/`pd.errors` that propagates out of the
"pure" reconcile layer into `cross_validate.main`, which has no guard around the
gating-engine reconciliation (only Nautilus is try-guarded). A bad cell in a gating
engine's trade frame would abort the whole report with a traceback. Low severity:
the normalized trade frames are constructed by the harness itself with known dtypes.
**Fix:** Either document the precondition (cells are always Timestamp/None) or wrap the
parse in a try/except returning None.

### IN-03: Redundant `Decimal(str(...))` on a value documented to already be Decimal

**File:** `itrader/portfolio_handler/portfolio.py:396`
**Issue:** `_get_max_position_percentage` does
`max(abs(Decimal(str(pos.market_value))) for ...)` while the inline comment states
`pos.market_value is Decimal`. If it is already Decimal, the `Decimal(str(...))`
wrap is dead defensive code (and would mask a real type regression by silently
coercing a stray float). Harmless to correctness but inconsistent with the
"trust the Decimal source" stance taken elsewhere in this same edit.
**Fix:** Use `abs(pos.market_value)` directly, or keep the coercion only if
`market_value` is genuinely allowed to be float (then the comment is wrong).

### IN-04: `MockPortfolio` test fixture exposes float money, exercising only the fallback coercion path

**File:** `tests/unit/portfolio/test_metrics_manager.py:21-41`
**Issue:** `MockPortfolio.total_equity` etc. are floats (`100000.0`, `i * 100`),
so every MetricsManager test exercises the `_as_decimal(Decimal(str(value)))`
*fallback* branch, never the production "already Decimal, pass-through" branch the
phase added. The Decimal regression lock for MetricsManager money therefore does not
test the production type path; it tests the lightweight-test-portfolio path. Coverage
gap, not a defect.
**Fix:** Add one test where the mock exposes `Decimal` money attributes, asserting
`_as_decimal` returns the same object (pass-through) so the production path is locked.

### IN-05: `n_open_positions` in tests passed as `int` where some snapshot fields expect prior-Decimal context

**File:** `tests/unit/portfolio/test_metrics_manager.py:106 (`i * 100`), 305, 327, 344`
**Issue:** Several `update_values` calls pass integer pnl (`i * 100`, `i * 500`)
which become `Decimal(str(int))` = `Decimal("0")`, `Decimal("100")` (no fractional
part). Assertions like `Decimal("2000.0")` elsewhere still pass because Decimal
equality is value-based, but the mixed int/float inputs make the fixtures harder to
reason about. Pure test-hygiene observation.
**Fix:** Use consistent float (or Decimal) literals across `update_values` calls.

### IN-06: `nautilus_run.run()` docstring/signature drift vs orchestrator call

**File:** `scripts/crossval/nautilus_run.py:426-451` vs `scripts/cross_validate.py:115-117`
**Issue:** The orchestrator imports `run` and calls `run(prices=prices, indicators=indicators)`.
`run()` then re-derives `short/long/hist` from `indicators[...]`, and `run_nautilus`
re-derives the frame again. The data threading is correct but doubly indirected
(`run` → `run_nautilus` → `_indicators`), and the module docstring describes
`run(prices=None, indicators=None)` while the internal `run_nautilus` uses a
different parameter shape (`ohlcv, short_sma, long_sma, macd_hist`). Not a bug, but
the two-layer parameter remap is a maintenance trap if the indicator column names
ever change. Offline tooling, informational only.
**Fix:** Consider collapsing to a single entry shape, or add an assertion that the
expected indicator columns are present before the remap.

---

_Reviewed: 2026-06-08T15:45:24Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
