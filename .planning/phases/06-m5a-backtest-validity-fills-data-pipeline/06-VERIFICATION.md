---
phase: 06-m5a-backtest-validity-fills-data-pipeline
verified: 2026-06-06T21:00:00Z
status: passed
score: 6/6 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 4/4
  gaps_closed:
    - "WR-06: dead update_portfolios_market method deleted; zero codebase references survive"
    - "CR-01: two-pass on_bar parent-filled gate added to MatchingEngine; bracket children dormant while parent entry rests"
    - "REQUIREMENTS.md M5-03 and M5-05 checkboxes updated to [x] with traceability rows marked Complete"
  gaps_remaining: []
  regressions: []
---

# Phase 6: M5a — Backtest Validity, Fills & Data Pipeline Verification Report

**Phase Goal:** Fix the correctness of the backtest itself — remove resampling look-ahead, make fills realistic, replace the per-tick pandas Series payload with an immutable `Bar` struct, precompute resampled frames, correct fee/slippage, and split the price handler into Provider/Store/Feed seams with an offline-deterministic read path. This is where results are first allowed to change.
**Verified:** 2026-06-06T21:00:00Z
**Status:** passed
**Re-verification:** Yes — after gap closure (plans 06-07 and 06-08 merged; 06-HUMAN-UAT.md shows both gaps `status: resolved`; 06-REVIEW.md re-reviewed with critical count now 0)

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Backtest validity fixed — resampling look-ahead removed, limit fills bounded, bar-timing documented and consistent | ✓ VERIFIED | `label="left"`, `closed="left"`, `searchsorted` in bar_feed.py; limit-or-better SELL/BUY gap cases tested; timing contract rules 1-7 in bar_feed.py module docstring; 12 feed tests green |
| 2 | Per-tick market-data payload is immutable `Bar` struct; no pandas Series; resampled frames precomputed once per (ticker, timeframe) and sliced per tick | ✓ VERIFIED | `Bar` @dataclass(frozen=True, slots=True, kw_only=True) at itrader/core/bar.py; BarEvent.bars: dict[str, Bar]; zero get_last_* matches; feed.precompute() at run-init; feed.window() is pure searchsorted slice |
| 3 | Fee/slippage models correct — maker fees live, tiered model deleted, slippage not applied to limit fills, time.sleep removed | ✓ VERIFIED | tiered_fee_model.py absent; grep TieredFeeModel: 0 matches; grep time.sleep in simulated.py: 0 matches; is_maker derived from real order context; LIMIT guard for slippage; 21 fee + 15 slippage tests pass |
| 4 | Price handler splits into Provider/Store/Feed seams; run path read-only, errors loudly on missing data; strategies use resampled-bars API | ✓ VERIFIED | PriceStore/PriceProvider/BarFeed ABCs live; data_provider.py deleted; CsvPriceStore raises MissingPriceDataError; strategies_handler.feed.window() used; no price_handler.prices on hot loop |
| 5 | Bracket children (SL/TP) cannot fill or OCO-cancel while their parent entry still rests in the book (CR-01 parent-filled gate) | ✓ VERIFIED | matching_engine.py two-pass on_bar: pass 1 fills/pops parents, pass 2 skips children where `parent_order_id in self._resting` (line 240); 4 new regression tests (test_limit_parent_resting_shields_children, test_limit_parent_fill_same_bar_unlocks_children, test_children_dormant_until_parent_triggers_then_work_later_bar, test_stop_parent_resting_shields_children at lines 433, 450, 469, 501); oracle byte-exact |
| 6 | Dead `update_portfolios_market` method (reads nonexistent `close_price` field) is deleted with zero surviving references (WR-06) | ✓ VERIFIED | grep `update_portfolios_market\b` across itrader/ and tests/ excluding `_value` suffix: 0 matches; grep `close_price` in portfolio_handler.py: 0 matches; live `update_portfolios_market_value` at line 327 untouched; test renamed to `test_update_portfolios_market_value` at line 37 of test_portfolio_update.py |

**Score:** 6/6 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/core/bar.py` | frozen/slots/kw_only Bar dataclass + from_row | ✓ VERIFIED | Contains `@dataclass(frozen=True, slots=True, kw_only=True)`, `from_row`, `Decimal(str(` |
| `tests/unit/core/test_bar.py` | Bar construction, micro-price, immutability tests | ✓ VERIFIED | 6 tests pass; asserts Decimal equality, FrozenInstanceError |
| `tests/conftest.py` | make_bar / make_bar_struct / make_bar_event fixtures | ✓ VERIFIED | All three factory fixtures defined |
| `itrader/price_handler/store/base.py` | PriceStore ABC | ✓ VERIFIED | All 5 abstract methods present |
| `itrader/price_handler/store/csv_store.py` | CsvPriceStore with loud typed errors | ✓ VERIFIED | Raises MissingPriceDataError; no bare except |
| `itrader/price_handler/providers/base.py` | PriceProvider ABC | ✓ VERIFIED | class PriceProvider(ABC) with both abstract methods |
| `itrader/price_handler/ingestion.py` | stub offline ingestion entry point | ✓ VERIFIED | Contains `def ingest(` and `NotImplementedError` |
| `tests/unit/price/test_csv_store.py` | store read-path + loud-error tests | ✓ VERIFIED | 6 tests pass; pytest.raises(MissingPriceDataError) present |
| `itrader/price_handler/feed/base.py` | BarFeed ABC | ✓ VERIFIED | class BarFeed(ABC) with all abstract methods |
| `itrader/price_handler/feed/bar_feed.py` | BacktestBarFeed with precompute + searchsorted | ✓ VERIFIED | label="left", closed="left", searchsorted; timing contract rules 1-7 in module docstring |
| `tests/unit/price/test_bar_feed.py` | Look-ahead regression, precompute, megaframe tests | ✓ VERIFIED | 274 lines, 12 test functions; look_ahead/forming boundary tests; precompute + zero-resample tests |
| `tests/unit/execution/test_fee_models.py` | Decimal fee math, maker/taker, typed validation | ✓ VERIFIED | 21 tests pass |
| `tests/unit/execution/test_slippage_models.py` | Decimal slippage factor, validation raises | ✓ VERIFIED | 15 tests pass |
| `itrader/execution_handler/matching_engine.py` | Two-pass on_bar with CR-01 parent-filled gate | ✓ VERIFIED | Two-pass on_bar (pass 1: parents/standalone; pass 2: children gated by `parent_order_id in self._resting`); module docstring documents parent-filled gate; 41 total test functions in test_matching_engine.py |
| `tests/unit/execution/test_matching_engine.py` | 4 new CR-01 regression tests | ✓ VERIFIED | test_limit_parent_resting_shields_children (433), test_limit_parent_fill_same_bar_unlocks_children (450), test_children_dormant_until_parent_triggers_then_work_later_bar (469), test_stop_parent_resting_shields_children (501) |
| `tests/golden/REFREEZE-M5A.md` | expected-diff note: old/new trade counts, equity | ✓ VERIFIED | old equity 53229.68512642489, new equity 53103.01549885479, trade count 134/134 |
| `tests/golden/REFREEZE-06-04.md` | ULP-level re-freeze note | ✓ VERIFIED | D-23 owner-approved ULP re-freeze documented |
| `itrader/trading_system/backtest_trading_system.py` | Store+Feed wiring at composition root | ✓ VERIFIED | CsvPriceStore, BacktestBarFeed; no PriceHandler construction |
| `itrader/strategy_handler/strategies_handler.py` | push-based window delivery via feed.window(...) | ✓ VERIFIED | feed.window( at line 58; no price_handler attribute |
| `itrader/portfolio_handler/portfolio_handler.py` | update_portfolios_market deleted; update_portfolios_market_value live | ✓ VERIFIED | Dead method gone (confirmed by zero-reference grep); live method at line 327 untouched |
| `tests/unit/portfolio/test_portfolio_update.py` | test renamed to test_update_portfolios_market_value | ✓ VERIFIED | def test_update_portfolios_market_value at line 37; body and assertions unchanged (cash == 980, total_equity == 990, total_pnl == -10) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `itrader/events_handler/events/market.py` | `itrader/core/bar.py` | `BarEvent.bars: dict[str, Bar]` | ✓ WIRED | `from itrader.core.bar import Bar`; `bars: dict[str, Bar]` |
| `itrader/portfolio_handler/portfolio.py` | `BarEvent.bars` | close-marked equity via `bars[ticker].close` | ✓ WIRED | `for ticker, bar in bar_event.bars.items()` |
| `itrader/execution_handler/matching_engine.py` | `self._resting` | `parent_order_id in self._resting` dormancy check (CR-01 gate) | ✓ WIRED | Line 240: `if order.parent_order_id in self._resting: continue` |
| `itrader/price_handler/store/csv_store.py` | `itrader/core/exceptions` | MissingPriceDataError raises | ✓ WIRED | `from itrader.core.exceptions import MalformedDataError, MissingPriceDataError` |
| `itrader/price_handler/feed/bar_feed.py` | `itrader/price_handler/store/base.py` | constructor consumes PriceStore.read_bars | ✓ WIRED | BacktestBarFeed.__init__ calls store.read_bars; uses store.symbols() |
| `itrader/trading_system/backtest_trading_system.py` | `itrader/price_handler/store/csv_store.py` | CsvPriceStore construction + store.index(...) | ✓ WIRED | Imports and constructs CsvPriceStore |
| `itrader/strategy_handler/strategies_handler.py` | `itrader/price_handler/feed/bar_feed.py` | per-tick window query | ✓ WIRED | `self.feed.window(ticker, strategy.timeframe, strategy.max_window, asof=event.time)` |
| `itrader/events_handler/full_event_handler.py` | `portfolio_handler.update_portfolios_market_value` | BAR event dispatch | ✓ WIRED | Production BAR routing confirmed at full_event_handler.py:71; dead `update_portfolios_market` no longer exists |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `itrader/strategy_handler/strategies_handler.py` | `data` (window DataFrame) | `self.feed.window(ticker, tf, max_window, asof=event.time)` | Yes — searchsorted slice of precomputed resampled frames from CsvPriceStore | ✓ FLOWING |
| `itrader/universe/dynamic.py` | `bars` (BarEvent payload) | `self.feed.current_bars(time_event.time)` | Yes — exact-stamp lookup in base frame from CsvPriceStore | ✓ FLOWING |
| `itrader/portfolio_handler/portfolio.py` | `current_prices` dict | `bar_event.bars.items()` → `bar.close` | Yes — Decimal close from Bar struct built from CsvPriceStore data | ✓ FLOWING |
| `itrader/execution_handler/matching_engine.py` | `bar_struct` | `bar.bars.get(ticker)` in on_bar via _evaluate | Yes — Bar struct from BarEvent built by current_bars | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Full suite green under filterwarnings=["error"] — 590 passed (586 baseline + 4 new CR-01 tests) | `poetry run pytest tests/ -q` | 590 passed | ✓ PASS (reported in 06-07-SUMMARY.md) |
| Oracle integration test byte-exact: 134 trades, final_equity 53103.01549885479 | `poetry run pytest tests/integration/test_backtest_oracle.py -q` | 2 passed | ✓ PASS (reported in both 06-07-SUMMARY.md and 06-08-SUMMARY.md) |
| mypy --strict clean after both gap-closure commits | `poetry run mypy itrader` | Success: no issues in 139 source files | ✓ PASS (reported in both summaries) |
| Portfolio unit tests after WR-06 deletion | `poetry run pytest tests/unit/portfolio/test_portfolio_update.py -q` | 3 passed | ✓ PASS (reported in 06-08-SUMMARY.md) |
| Matching engine tests after CR-01 fix | `poetry run pytest tests/unit/execution/test_matching_engine.py -q` | 41 passed (37 existing + 4 new) | ✓ PASS (reported in 06-07-SUMMARY.md) |
| tests/golden/ untouched — no re-freeze required | `git status --porcelain tests/golden/` | empty — no changes | ✓ PASS (confirmed: fixes are D-21 inert) |

### Probe Execution

Step 7c: SKIPPED — no probe scripts declared in any phase plan or discoverable under `scripts/*/tests/probe-*.sh`.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| M5-01 | 06-03, 06-04, 06-06, 06-07 | Backtest validity: look-ahead removed, limit fills bounded, bar-timing documented, bracket-child gate | ✓ SATISFIED | Feed cutoff implemented; limit-or-better in matching engine; CR-01 parent-filled gate (plan 06-07, commits 7e63dd3/fc65dd2); REQUIREMENTS.md [x]; traceability: Complete |
| M5-02 | 06-01, 06-08 | Immutable Bar struct; hasattr ladders deleted; pre-M5 close_price shape eradicated | ✓ SATISFIED | Bar@dataclass(frozen=True,slots=True,kw_only=True); BarEvent.bars:dict[str,Bar]; WR-06 dead method deleted (plan 06-08, commit dca839c); REQUIREMENTS.md [x]; traceability: Complete |
| M5-03 | 06-03, 06-05 | Resampled frames precomputed once per (ticker, timeframe); no resample in hot loop | ✓ SATISFIED | feed.precompute() at run-init; feed.window() is pure searchsorted; 0 .resample() calls on hot loop; REQUIREMENTS.md [x] (was [ ] in initial verification — now updated); traceability: Complete |
| M5-04 | 06-04 | Fee/slippage correct: maker fees live, tiered deleted, no slippage on limits, time.sleep removed | ✓ SATISFIED | tiered_fee_model.py absent; is_maker from real context; LIMIT guard in _emit_fill; REQUIREMENTS.md [x]; traceability: Complete |
| M5-05 | 06-02, 06-03, 06-05 | Provider/Store/Feed seams; offline read-only run path; loud errors; strategies use Feed API | ✓ SATISFIED | PriceStore/PriceProvider/BarFeed ABCs live; data_provider.py deleted; CsvPriceStore raises MissingPriceDataError; SMA_MACD receives pd.DataFrame from feed.window(); REQUIREMENTS.md [x] (was [ ] in initial verification — now updated); traceability: Complete |

**Orphaned Requirements Check:** REQUIREMENTS.md traceability table maps exactly M5-01..M5-05 to Phase 6. All five are now marked Complete. No orphaned IDs.

**REQUIREMENTS.md documentation gap (from initial verification): RESOLVED.** M5-03 and M5-05 checkboxes are now `[x]` and their traceability rows show `Complete`. Verified directly against .planning/REQUIREMENTS.md lines 134, 139, 231, 233.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | — | — | — | — |

All former anti-pattern findings from the initial verification are resolved:
- WR-06 (`update_portfolios_market` with `getattr(bar, 'close_price', None)`) — deleted by plan 06-08. Zero surviving references.
- No `TBD`, `FIXME`, or `XXX` markers found in any phase-modified files. No unreferenced debt markers. No stub return values in production code paths.

### Human Verification Required

None. All three items from the initial human verification list are closed:

1. **REQUIREMENTS.md Traceability Update** — RESOLVED. M5-03 and M5-05 are `[x]` in the checklist and `Complete` in the traceability table (verified by grep against .planning/REQUIREMENTS.md).

2. **WR-06 Dead-Code Disposition** — RESOLVED. Plan 06-08 (commit dca839c) deleted `update_portfolios_market`; `test_update_portfolios_market` renamed to `test_update_portfolios_market_value`; zero references survive (verified by grep); oracle byte-exact.

3. **CR-01 Bracket Children Gate** — RESOLVED. Plan 06-07 (commits 7e63dd3, fc65dd2) added two-pass `on_bar` with parent-filled gate; 4 regression tests lock the behavior; all 41 matching-engine tests green; oracle byte-exact. The 06-REVIEW.md marks CR-01 RESOLVED with critical count now 0.

### Gaps Summary

No gaps. All 6 observable truths are VERIFIED. All 5 in-scope requirements (M5-01 through M5-05) are SATISFIED with REQUIREMENTS.md documentation fully updated. The two gap-closure plans delivered exactly what the UAT requested:

- **Plan 06-07 (CR-01):** Two-pass `MatchingEngine.on_bar` with parent-filled gate — bracket children dormant while their parent entry still rests in the book. Same-bar market-parent semantics and children-only-book evaluability preserved. Oracle byte-exact (behavior-inert on the market-order-only golden path, as anticipated).

- **Plan 06-08 (WR-06):** Dead `update_portfolios_market` method deleted. Pre-M5 `close_price` payload shape eradicated. Test renamed, production coverage retained. Oracle byte-exact (structural deletion, D-21 inert).

The phase goal is fully achieved: backtest correctness is fixed across all five M5a dimensions — look-ahead, Bar struct, precomputed frames, fee/slippage, and Provider/Store/Feed seams — with bracket ordering correctness added via the gap-closure wave.

---

_Verified: 2026-06-06T21:00:00Z_
_Verifier: Claude (gsd-verifier)_
_Re-verification: Yes — initial status was human_needed; all human items resolved by gap-closure plans 06-07 and 06-08_
