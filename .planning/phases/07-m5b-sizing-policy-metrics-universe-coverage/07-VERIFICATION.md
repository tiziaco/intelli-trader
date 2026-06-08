---
phase: 07-m5b-sizing-policy-metrics-universe-coverage
verified: 2026-06-08T00:00:00Z
status: human_needed
score: 4/4 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Run make backtest (scripts/run_backtest.py) and confirm it prints the formatted metrics block to stdout and produces output/summary.json with a 'metrics' object containing sharpe, sortino, cagr, max_drawdown, profit_factor, win_rate"
    expected: "The run completes, a metrics block is printed (via format_metrics), and output/summary.json contains a nested 'metrics' dict. The header of output/trades.csv includes slippage_entry and slippage_exit."
    why_human: "The integration test (test_backtest_oracle.py) runs the full backtest but the output/ directory is generated outside the test suite. Confirming the actual JSON/CSV shape requires a real run-script invocation."
  - test: "Verify the two owner-approved REFREEZE notes are complete and the golden reference is long-only"
    expected: "tests/golden/REFREEZE-M5B-DIRECTION.md and tests/golden/REFREEZE-M5B-INCREASE.md both carry 'APPROVED' status lines; tests/golden/trades.csv has 0 rows with side==SHORT; the summary.json metrics block values are sane (max_drawdown negative, win_rate in [0,1], profit_factor > 0)."
    why_human: "Ownership of the golden re-freeze content requires a human to confirm the expected-diff notes match the actual trade changes — automated checks can only verify file existence and structural shape."
---

# Phase 7: M5b — Sizing Policy, Metrics, Universe & Coverage Verification Report

**Phase Goal:** Complete the strategy-declared sizing policy started minimally in M1 (closing the #24/#31/KB11 span), make reporting/metrics correct, collapse the universe to a documented stub, and add strategy/data/reporting/universe test coverage.
**Verified:** 2026-06-08
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths (ROADMAP Success Criteria)

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | Strategy-declared sizing policy fully resolved per-portfolio in the order/risk layer — `VariableSizer` finished, `RiskManager.check_cash` covers increases, `calculate_signal` contract enforced (closes #24/#31/KB11) | ✓ VERIFIED | `SizingResolver` wired in `order_manager.py` dispatching on `signal.sizing_policy`; `FractionOfCash/FixedQuantity/RiskPercent` in `core/sizing.py`; direction+increase+max_positions admission gates present with `triggered_by` fields; `strategy_setting` dict gone from all files; 711 tests green |
| 2 | Reporting/metrics correct — drawdown math, pandas-2/plotly breakage, `is np.nan` bug, rolling-stats stub resolved, dead `EngineLogger` removed, computation split from presentation | ✓ VERIFIED | `itrader/reporting/metrics.py` (pure, numpy/pandas-only imports, `PERIODS=365`, `ddof=1`, `rolling_sharpe`, `format_metrics`); `statistics.py`, `engine_logger.py`, `base.py`, `performance.py` all deleted; `reporting/` has only `__init__.py`, `metrics.py`, `frames.py`, `plots.py`; no `titlefont_size` in plots.py; no `reporting.*` ignore_errors overrides in pyproject.toml; `backtest_trading_system.py` calls `format_metrics` in `run(print_summary=True)` |
| 3 | `universe/` collapses to a thin documented symbol-set stub (false "dynamic"/redundant copies removed) | ✓ VERIFIED | `universe/dynamic.py`, `static.py`, `universe.py` deleted; `universe/membership.py` contains `derive_membership`, `UniverseSelectionModel` mention, and D-screener docstring; `bar_feed.py` has `generate_bar_event`; `full_event_handler.py` uses `bar_event_source` not `Universe`; no `DynamicUniverse/StaticUniverse` imports anywhere in `itrader/` |
| 4 | Strategy/data/reporting/universe paths gain test coverage | ✓ VERIFIED | `tests/unit/reporting/test_metrics.py` (27 tests), `tests/unit/reporting/test_plots_smoke.py` (5 tests), `tests/unit/universe/test_membership.py` (6 tests), `tests/unit/strategy/test_strategy.py` (rewritten with intent contract), `tests/unit/price/test_csv_store.py` (6 tests), `tests/unit/price/test_bar_feed.py` extended; full suite: 711 passed |

**Score:** 4/4 truths verified

### Deferred Items

No items deferred to later phases.

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `itrader/core/sizing.py` | SizingPolicy union, SLTPPolicy, TradingDirection, SignalIntent | ✓ VERIFIED | All 9 required classes/aliases present; zero imports from handler layers |
| `itrader/order_handler/sizing_resolver.py` | ONE resolver, match/assert_never, PortfolioReadModel-injected | ✓ VERIFIED | `class SizingResolver`, `assert_never` import and use confirmed |
| `itrader/core/exceptions/order.py` | `SizingPolicyViolation` | ✓ VERIFIED | `class SizingPolicyViolation(OrderError)` at line 21 |
| `itrader/core/portfolio_read_model.py` | `total_equity` Protocol member | ✓ VERIFIED | `def total_equity` at line 196 |
| `itrader/portfolio_handler/portfolio_handler.py` | `total_equity` concrete implementation | ✓ VERIFIED | `def total_equity` returning `Decimal` at line 264 |
| `itrader/universe/membership.py` | `derive_membership`, `UniverseSelectionModel` reference | ✓ VERIFIED | Both present; D-screener rebalance target documented |
| `itrader/price_handler/feed/bar_feed.py` | `generate_bar_event` factory | ✓ VERIFIED | `def generate_bar_event` at line 230 |
| `itrader/reporting/metrics.py` | Pure metric functions, `PERIODS=365`, `rolling_sharpe`, `format_metrics` | ✓ VERIFIED | All present; numpy/pandas imports only; `ddof=1` pinned |
| `itrader/reporting/frames.py` | `build_trade_log`, `build_equity_curve` — pure, duck-typed | ✓ VERIFIED | Both present; zero itrader handler imports |
| `itrader/strategy_handler/base.py` | `generate_signal` abstract method, no `_generate_signal`/`global_queue`/`last_event` | ✓ VERIFIED | `def generate_signal` as `@abstractmethod`; forbidden symbols absent |
| `itrader/events_handler/events/signal.py` | `sizing_policy` field, no `strategy_setting` | ✓ VERIFIED | `sizing_policy: SizingPolicy` present; `strategy_setting` absent codebase-wide |
| `itrader/strategy_handler/SMA_MACD_strategy.py` | `FractionOfCash(Decimal("0.95"))`, `LONG_ONLY`, `bars.index[-1]` | ✓ VERIFIED | All three present |
| `itrader/order_handler/order_manager.py` | `SizingResolver`, `sizing_policy`, `admission_direction`, `admission_increase`, `admission_max_positions`, `PercentFromFill/PercentFromDecision` | ✓ VERIFIED | All confirmed present |
| `itrader/order_handler/order_validator.py` | `ZERO_QUANTITY_TRANSITION` bypass deleted | ✓ VERIFIED | Zero occurrences found |
| `tests/golden/REFREEZE-M5B-DIRECTION.md` | Owner-approved expected-diff note | ✓ VERIFIED | File exists, `Status: APPROVED` present |
| `tests/golden/REFREEZE-M5B-INCREASE.md` | Owner-approved expected-diff note | ✓ VERIFIED | File exists, `Status: APPROVED` present |
| `tests/golden/trades.csv` | 0 SHORT rows, slippage columns | ✓ VERIFIED | `grep -c "SHORT"` returns 0; header contains `slippage_entry,slippage_exit` |
| `tests/golden/summary.json` | `"metrics"` object with all 6 keys | ✓ VERIFIED | `"metrics"` present with `cagr`, `max_drawdown`, `profit_factor`, `sharpe`, `sortino`, `win_rate` |
| `tests/unit/order/test_admission_rules.py` | Direction + increase + max_positions guard tests | ✓ VERIFIED | `triggered_by == "admission_direction"` assertions confirmed |
| `tests/unit/order/test_sltp_policy.py` | SLTP mechanics coverage | ✓ VERIFIED | `PercentFromDecision`, `PercentFromFill`, explicit-level precedence, rejected-parent-discard tests |
| `tests/unit/core/test_sizing.py` | Policy construction + validation tests | ✓ VERIFIED | File exists, 30 tests |
| `tests/unit/order/test_sizing_resolver.py` | Resolver byte-exact tests | ✓ VERIFIED | File exists, 15 tests |
| `tests/unit/universe/test_membership.py` | Membership union coverage | ✓ VERIFIED | 6 tests covering tuple-pair flattening, deduplication, empty inputs |
| `tests/unit/reporting/test_metrics.py` | Hand-computed fixture tests (TC4) | ✓ VERIFIED | `max_drawdown` == `pytest.approx(-0.10)`, all-winners → inf, `format_metrics` str assertions |
| `tests/unit/reporting/test_plots_smoke.py` | Plotly smoke tests | ✓ VERIFIED | 5 tests |
| Deleted: `statistics.py`, `engine_logger.py`, `base.py`, `performance.py` | Legacy reporting gone | ✓ VERIFIED | All four absent from `itrader/reporting/` |
| Deleted: `universe/dynamic.py`, `static.py`, `universe.py` | False dynamic machinery gone | ✓ VERIFIED | All three absent |
| Deleted: `strategy_handler/position_sizer/`, `risk_manager/`, `sltp_models/` | Orphaned packages gone | ✓ VERIFIED | No `.py` source files remain (only stale `__pycache__` bytecode — not importable) |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `sizing_resolver.py` | `core/sizing.py` | `from itrader.core.sizing import` | ✓ WIRED | Line 39 confirmed |
| `order_manager.py` | `sizing_resolver.py` | `SizingResolver(` constructor | ✓ WIRED | Line 116 confirmed |
| `order_manager.py` | `signal.sizing_policy` | dispatch in `_resolve_signal_quantity` | ✓ WIRED | Multiple confirmed lines |
| `events_handler/events/signal.py` | `core/sizing.py` | `from itrader.core.sizing import` | ✓ WIRED | Line 14 confirmed; no order_handler imports |
| `full_event_handler.py` | `bar_event_source` (feed-backed) | TIME route via `self.bar_event_source` | ✓ WIRED | Line 71; no `Universe` import |
| `backtest_trading_system.py` | `universe/membership.py` | `derive_membership` | ✓ WIRED | Lines 19 + 145 confirmed |
| `scripts/run_backtest.py` | `reporting/metrics.py` | `build_metrics_block` call | ✓ WIRED | Line 186 builds metrics block |
| `scripts/run_backtest.py` | `reporting/frames.py` | `from itrader.reporting.frames import` | ✓ WIRED | Line 33 confirmed; no local `build_trade_log`/`build_equity_curve` |
| `backtest_trading_system.py` | `reporting/metrics.py` | `format_metrics` call in `run()` | ✓ WIRED | Lines 24 + 226 confirmed |
| `oracle test` | `tests/golden/summary.json` | `summary["metrics"]` exact comparison | ✓ WIRED | Lines 231-237 in test_backtest_oracle.py |
| `oracle test` | `_TRADE_SLIPPAGE_COLUMNS` | presence assertion | ✓ WIRED | Lines 68 + 199 confirmed |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `backtest_trading_system.py run()` | `metrics` dict | `compute_metrics(equity, trades)` → `metrics.py` pure functions | Yes — fed from `build_equity_curve`/`build_trade_log` which read portfolio internals | ✓ FLOWING |
| `order_manager.py` sizing | `sized_qty` | `SizingResolver.resolve_entry(signal.sizing_policy, ...)` → reads `available_cash` from `PortfolioHandler` | Yes — reads live portfolio cash state | ✓ FLOWING |
| `tests/golden/summary.json` | `"metrics"` | `scripts/run_backtest.py` `build_metrics_block` → `reporting.metrics` functions | Yes — computed from equity/trades frames | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| 711 tests pass | `poetry run pytest tests/ -q --tb=no` | `711 passed in 8.70s` | ✓ PASS |
| live_trading_system imports | `python -c "import itrader.trading_system.live_trading_system"` | exit 0 | ✓ PASS |
| mypy --strict clean | `poetry run mypy itrader/ --ignore-missing-imports` | `Success: no issues found in 151 source files` | ✓ PASS |
| M5-07 formulas correct | hand-verified Python assertions (max_drawdown, profit_factor, format_metrics) | all assertions pass | ✓ PASS |
| No strategy_setting in codebase | `grep -rn strategy_setting itrader/ tests/` | zero results | ✓ PASS |
| No DynamicUniverse imports | `grep -rn DynamicUniverse itrader/` | zero results | ✓ PASS |

### Probe Execution

No probes declared in PLAN files for this phase. Step 7c: SKIPPED (no probe scripts declared).

### Requirements Coverage

| Requirement | Source Plans | Description | Status | Evidence |
| ----------- | ------------ | ----------- | ------ | -------- |
| M5-06 | 07-01, 07-04, 07-05, 07-06, 07-07, 07-08 | Strategy-declared sizing policy fully resolved per-portfolio | ✓ SATISFIED | `SizingResolver` wired in `order_manager.py`; typed `SignalEvent`; pure `Strategy.generate_signal`; admission guards (direction/increase/max_positions); `ZERO_QUANTITY_TRANSITION` bypass deleted; orphaned `position_sizer/risk_manager/sltp_models/` deleted; `PercentFromFill/PercentFromDecision` in `order_manager.py`; 711 tests green |
| M5-07 | 07-03 | Reporting/metrics correct | ✓ SATISFIED | `reporting/metrics.py` (pure, `PERIODS=365`, `ddof=1`, `rolling_sharpe`, `format_metrics`); legacy 4 files deleted; `plots.py` plotly-6 fixed; `frames.py` pure; `backtest_trading_system.py` prints metrics block; pyproject.toml overrides removed; REQUIREMENTS.md checkbox not updated (doc tracking gap — WARNING, not a code gap) |
| M5-08 | 07-02 | universe/ collapses to thin documented stub | ✓ SATISFIED | `membership.py` only; 3 old files deleted; `bar_feed.py` owns `generate_bar_event`; `full_event_handler.py` uses `bar_event_source` |
| M5-09 | 07-02, 07-03, 07-04 | Strategy/data/reporting/universe test coverage | ✓ SATISFIED | Coverage: strategy (intent contract tests), reporting (27+5 unit tests), universe (6 unit tests), CSV price store (6 unit tests), bar_feed factory tests; REQUIREMENTS.md checkbox not updated (doc tracking gap — WARNING, not a code gap) |

**Documentation tracking gap (WARNING):** `REQUIREMENTS.md` has M5-07 and M5-09 as `[ ]` (unchecked) and the traceability table has all four Phase 7 IDs as "Pending" (even M5-06 and M5-08 which are checked). The ROADMAP marks Phase 7 as `[x] Complete`. This is a stale documentation state — the implementation clearly satisfies all four requirements. The traceability table inconsistency (even M5-06 "Pending" despite `[x]`) confirms this is a documentation-update omission rather than a code defect.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| `strategy_handler/position_sizer/` | — | `__pycache__` bytecode remains in deleted directories | ℹ️ Info | Not importable; stale build artifact; git status will show these as untracked (`.pyc` files are gitignored) |
| `REQUIREMENTS.md` | 146, 151 | M5-07 and M5-09 checkboxes `[ ]` despite implementation existing | ⚠️ Warning | Documentation tracking inconsistency; does not affect runtime behavior or test correctness |

No TBD/FIXME/XXX/HACK/PLACEHOLDER markers found in any modified source files.

### Human Verification Required

### 1. make backtest end-to-end run

**Test:** Run `poetry run python scripts/run_backtest.py` and inspect the output
**Expected:** Backtest completes; formatted metrics block printed to stdout (containing "sharpe" and "max_drawdown"); `output/summary.json` has a `"metrics"` nested dict with 6 keys; `output/trades.csv` header contains `slippage_entry` and `slippage_exit`; two consecutive runs produce byte-identical output/ trees
**Why human:** The oracle test runs the backtest but the artifact shape of the real output/ directory (vs the golden/) is confirmed by the integration test; a human run-through confirms the D-14 amendment (engine-level metrics printout) is visible in the terminal

### 2. Golden re-freeze content review

**Test:** Read `tests/golden/REFREEZE-M5B-DIRECTION.md` and `tests/golden/REFREEZE-M5B-INCREASE.md`; spot-check `tests/golden/trades.csv` against the notes
**Expected:** Both notes carry "APPROVED" status; the DIRECTION note attributes the 13.13% equity drop entirely to 2 SHORT → 2 LONG replacements with fraction-of-cash compounding knock-on; the INCREASE note records N=3 rejected increases with old→new headline numbers; `trades.csv` has 0 SHORT rows, 134 LONG rows, and the slippage columns
**Why human:** The owner's approval was captured inside the planning workflow; an independent human reviewer should confirm the attribution is complete and no unexplained residual trade delta exists between the old and new reference

### Gaps Summary

No code gaps. All four ROADMAP success criteria are fully implemented and verified in the codebase. The 711-test suite passes. mypy --strict is clean.

The only open items are:
1. A documentation tracking inconsistency in `REQUIREMENTS.md` (M5-07 and M5-09 checkboxes not updated to `[x]`, traceability table not updated to "Complete") — does not affect code correctness.
2. Two human verification items for end-to-end run confirmation and golden re-freeze content review — standard phase completion checks.

---

_Verified: 2026-06-08_
_Verifier: Claude (gsd-verifier)_
