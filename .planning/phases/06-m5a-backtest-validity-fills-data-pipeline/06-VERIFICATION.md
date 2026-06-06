---
phase: 06-m5a-backtest-validity-fills-data-pipeline
verified: 2026-06-06T17:00:00Z
status: human_needed
score: 4/4 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Verify REQUIREMENTS.md traceability table is updated to mark M5-03 and M5-05 as Complete"
    expected: "REQUIREMENTS.md checkboxes for M5-03 and M5-05 show [x], and the traceability table rows for both show 'Complete'"
    why_human: "The 06-03-SUMMARY.md explicitly deferred REQUIREMENTS.md checkoffs to the orchestrator after wave merge (worktree mode). The codebase implements both requirements but the documentation file was never updated. This is a doc-only change that cannot be verified by grep."
  - test: "Assess WR-06 dead-code risk: update_portfolios_market reads Bar.close_price (wrong field — Bar has 'close' not 'close_price'), always returns None prices"
    expected: "Either the broken method is deleted, or a comment confirms it is dead code with no caller on any run path (confirmed: event handler routes to update_portfolios_market_value, not this method)"
    why_human: "The method is dead on the run path (verified: full_event_handler uses update_portfolios_market_value) but exists in the code with a wrong field reference. Owner should decide whether to delete it to prevent confusion, or accept the WR-06 advisory finding as a known carryforward."
  - test: "Assess CR-01 from 06-REVIEW.md: bracket children can fill before their parent entry fills"
    expected: "The defect path (LIMIT/STOP parent + SL/TP children, non-MARKET primary) is not exercised by the golden SMA_MACD run (sl=0, tp=0, market orders only), so the oracle is unaffected. Owner should acknowledge whether this is a blocking concern for Phase 7 or an acceptable known gap."
    why_human: "CR-01 is a real defect in MatchingEngine.on_bar affecting bracket orders with non-MARKET primaries. The golden run path uses only market orders with sl=0/tp=0, so the current oracle and tests are not affected. The REVIEW marks it Critical; the verifier cannot determine whether this was intentionally deferred to Phase 7 (M5b risk layer) or is an unacknowledged blocker."
---

# Phase 6: M5a — Backtest Validity, Fills & Data Pipeline Verification Report

**Phase Goal:** Fix the correctness of the backtest itself — remove resampling look-ahead, make fills realistic, replace the per-tick pandas Series payload with an immutable `Bar` struct, precompute resampled frames, correct fee/slippage, and split the price handler into Provider/Store/Feed seams with an offline-deterministic read path. This is where results are first allowed to change.
**Verified:** 2026-06-06T17:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | Backtest validity fixed — resampling look-ahead removed, limit fills no longer slip past the limit, bar-timing documented and consistent | ✓ VERIFIED | `label="left"`, `closed="left"`, `searchsorted` in bar_feed.py; limit-or-better SELL/BUY gap cases tested in test_matching_engine.py; timing contract rules 1-7 in bar_feed.py module docstring; 12 feed tests green |
| 2 | Per-tick market-data payload is immutable `Bar` struct (no pandas Series, no hasattr/get_last_close type-branching); resampled frames precomputed once per (ticker, timeframe) and sliced per tick | ✓ VERIFIED | `Bar` @dataclass(frozen=True, slots=True, kw_only=True) at itrader/core/bar.py; BarEvent.bars: dict[str, Bar]; zero get_last_* matches across all consumer files; feed.precompute() called at run-init in backtest_trading_system.py:145; hot loop calls feed.window() (pure searchsorted slice); test_zero_resample_calls_on_per_tick_path passes |
| 3 | Fee/slippage models correct — maker fees live, tiered model deleted, slippage not applied to limit fills, time.sleep removed | ✓ VERIFIED | tiered_fee_model.py absent; grep for TieredFeeModel: 0 matches; grep for time.sleep in simulated.py: 0 matches; simulated.py:202 derives is_maker from real order context; simulated.py:206 guards LIMIT fills from slippage; 21 fee model tests + 15 slippage model tests pass |
| 4 | Price handler splits into Provider/Store/Feed seams; run path read-only, errors loudly on missing data; bare except/None and to_megaframe bugs fixed; strategies use resampled-bars API | ✓ VERIFIED | PriceStore/PriceProvider/BarFeed ABCs at store/base.py, providers/base.py, feed/base.py; data_provider.py and base.py deleted; exchange/ and live_streaming/ directories deleted; CsvPriceStore raises MissingPriceDataError (not None); megaframe uses keys=included (FR8 fix); SMA_MACD receives pd.DataFrame from strategies_handler.feed.window(); no price_handler.prices access on the hot loop |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/core/bar.py` | frozen/slots/kw_only Bar dataclass + from_row | ✓ VERIFIED | Contains `@dataclass(frozen=True, slots=True, kw_only=True)`, `from_row`, `Decimal(str(` |
| `tests/unit/core/test_bar.py` | Bar construction, micro-price, immutability tests | ✓ VERIFIED | 6 tests pass; asserts Decimal("0.000005") equality, FrozenInstanceError |
| `tests/conftest.py` | make_bar / make_bar_struct / make_bar_event fixtures | ✓ VERIFIED | All three factory fixtures defined at lines 97-109 |
| `itrader/price_handler/store/base.py` | PriceStore ABC: read_bars/write_bars/has/symbols/index | ✓ VERIFIED | All 5 abstract methods present; class PriceStore(ABC) |
| `itrader/price_handler/store/csv_store.py` | CsvPriceStore with loud typed errors | ✓ VERIFIED | CSV_START_DATE = '2018-01-01'; raises MissingPriceDataError; no bare except |
| `itrader/price_handler/providers/base.py` | PriceProvider ABC: fetch_ohlcv/get_symbols | ✓ VERIFIED | class PriceProvider(ABC) with both abstract methods |
| `itrader/price_handler/ingestion.py` | stub offline ingestion entry point | ✓ VERIFIED | Contains `def ingest(` and `NotImplementedError` |
| `tests/unit/price/test_csv_store.py` | store read-path + loud-error tests | ✓ VERIFIED | 6 tests pass; pytest.raises(MissingPriceDataError) present |
| `itrader/price_handler/feed/base.py` | BarFeed ABC: current_bars/window/megaframe | ✓ VERIFIED | class BarFeed(ABC) with all abstract methods |
| `itrader/price_handler/feed/bar_feed.py` | BacktestBarFeed with precompute + searchsorted | ✓ VERIFIED | Contains label="left", closed="left", searchsorted; timing contract rules 1-7 in module docstring |
| `tests/unit/price/test_bar_feed.py` | Look-ahead regression, precompute, megaframe tests | ✓ VERIFIED | 274 lines, 12 test functions; look_ahead/forming tests in both boundary directions; precompute equality + zero-resample tests; megaframe keys assertion |
| `tests/unit/execution/test_fee_models.py` | Decimal fee math, maker/taker, typed validation | ✓ VERIFIED | 21 tests pass; typed exception raises; Decimal return type; is_maker tests |
| `tests/unit/execution/test_slippage_models.py` | Decimal slippage factor, validation raises | ✓ VERIFIED | 15 tests pass; no silent 1.0 return; deterministic seeded jitter |
| `itrader/execution_handler/matching_engine.py` | Decimal-native with limit-or-better gap fills | ✓ VERIFIED | fill_price: Decimal; no float() calls; limit-or-better semantics in LIMIT branch |
| `tests/golden/REFREEZE-M5A.md` | expected-diff note: what changed, why, deltas | ✓ VERIFIED | Contains old/new trade counts (134/134), old equity 53229.68512642489, new equity 53103.01549885479 |
| `tests/golden/REFREEZE-06-04.md` | ULP-level re-freeze note | ✓ VERIFIED | Documents D-23 owner-approved ULP re-freeze from plan 06-04 |
| `itrader/trading_system/backtest_trading_system.py` | Store+Feed wiring at composition root | ✓ VERIFIED | Contains CsvPriceStore, BacktestBarFeed; no PriceHandler construction |
| `itrader/strategy_handler/strategies_handler.py` | push-based window delivery via feed.window(...) | ✓ VERIFIED | Contains `feed.window(` at line 58; no price_handler attribute |
| `tests/unit/portfolio/test_cash_reservations.py` | Pitfall 6 gap-up reservation lock | ✓ VERIFIED | 2 tests: gap_up_settlement_above_reservation_succeeds, release_after_gap_up_is_idempotent |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `itrader/events_handler/events/market.py` | `itrader/core/bar.py` | `BarEvent.bars: dict[str, Bar]` | ✓ WIRED | Line 9: `from itrader.core.bar import Bar`; line 50: `bars: dict[str, Bar]` |
| `itrader/portfolio_handler/portfolio.py` | `BarEvent.bars` | close-marked equity via `bars[ticker].close` | ✓ WIRED | Line 336: `for ticker, bar in bar_event.bars.items()` |
| `itrader/execution_handler/matching_engine.py` | `BarEvent.bars` | trigger evaluation reads bars[ticker] | ✓ WIRED | No longer uses `.bars[` directly — consumes Bar struct passed by SimulatedExchange from on_market_data |
| `itrader/price_handler/store/csv_store.py` | `itrader/core/exceptions` | MissingPriceDataError raises | ✓ WIRED | Line 19: `from itrader.core.exceptions import MalformedDataError, MissingPriceDataError` |
| `pyproject.toml` | relocated quarantined modules | `[[tool.mypy.overrides]]` | ✓ WIRED | Lines 87-91: itrader.price_handler.store.sql_store, providers.ccxt_provider, oanda_provider, exchange_base, binance_stream |
| `itrader/price_handler/feed/bar_feed.py` | `itrader/price_handler/store/base.py` | constructor consumes PriceStore.read_bars | ✓ WIRED | BacktestBarFeed.__init__ calls store.read_bars; uses store.symbols() |
| `itrader/price_handler/feed/bar_feed.py` | `itrader/core/bar.py` | current_bars builds Bar via Bar.from_row | ✓ WIRED | Import confirmed; current_bars calls Bar.from_row(time, row) |
| `itrader/trading_system/backtest_trading_system.py` | `itrader/price_handler/store/csv_store.py` | CsvPriceStore construction + store.index(...) | ✓ WIRED | Lines 10, 70-73: imports and constructs CsvPriceStore |
| `itrader/strategy_handler/strategies_handler.py` | `itrader/price_handler/feed/bar_feed.py` | per-tick window query | ✓ WIRED | Line 58: `self.feed.window(ticker, strategy.timeframe, strategy.max_window, asof=event.time)` |
| `itrader/universe/dynamic.py` | `itrader/price_handler/feed/bar_feed.py` | feed.current_bars builds BarEvent | ✓ WIRED | Line 73: `bars = self.feed.current_bars(time_event.time)` |
| `itrader/execution_handler/exchanges/simulated.py` | `itrader/execution_handler/matching_engine.py` | on_order routes ALL NEW orders to matching_engine.submit | ✓ WIRED | Line 287: `self.matching_engine.submit(event)`; no execution_timing attribute |
| `itrader/execution_handler/exchanges/simulated.py` | `decision.order_event.order_type` | real order context for maker/taker + slippage gating | ✓ WIRED | Lines 201-206: `event.order_type.value`, `is_maker = event.order_type is OrderType.LIMIT`, LIMIT guard for slippage |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `itrader/strategy_handler/strategies_handler.py` | `data` (window DataFrame) | `self.feed.window(ticker, tf, max_window, asof=event.time)` | Yes — searchsorted slice of precomputed resampled frames from CsvPriceStore | ✓ FLOWING |
| `itrader/universe/dynamic.py` | `bars` (BarEvent payload) | `self.feed.current_bars(time_event.time)` | Yes — exact-stamp lookup in base frame from CsvPriceStore | ✓ FLOWING |
| `itrader/portfolio_handler/portfolio.py` | `current_prices` dict | `bar_event.bars.items()` → `bar.close` | Yes — Decimal close from Bar struct built from CsvPriceStore data | ✓ FLOWING |
| `itrader/execution_handler/matching_engine.py` | `bar_struct` | `bar.bars.get(ticker)` in on_market_data | Yes — Bar struct from BarEvent built by current_bars | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Backtest runs end-to-end producing 134 trades | `make backtest` | 134 trades, final_equity 53103.01549885479 | ✓ PASS |
| Full suite green against re-frozen oracle | `poetry run pytest tests/ -q` | 586 passed | ✓ PASS |
| Oracle test passes (behavioral + numeric identity) | `poetry run pytest tests/integration/test_backtest_oracle.py -q` | 2 passed | ✓ PASS |
| mypy --strict clean | `make typecheck` | Success: no issues in 161 source files | ✓ PASS |
| Determinism: two consecutive runs byte-identical | `run_backtest.py` twice + diff | BYTE-IDENTICAL | ✓ PASS |
| Core unit tests: Bar, CsvPriceStore, BarFeed | `poetry run pytest tests/unit/core/test_bar.py tests/unit/price/ -q` | 24 passed | ✓ PASS |
| Execution layer tests: fee models, slippage, matching | `poetry run pytest tests/unit/execution/test_fee_models.py tests/unit/execution/test_slippage_models.py tests/unit/execution/test_matching_engine.py -q` | 73 passed | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|---------|
| M5-01 | 06-03, 06-04, 06-06 | Backtest validity: look-ahead removed, limit fills bounded, bar-timing documented | ✓ SATISFIED | Feed cutoff B+TF<=T+tf_base implemented; limit-or-better in matching engine; next-bar-open fill via on_order→matching_engine.submit; tests lock all three sub-requirements |
| M5-02 | 06-01 | Immutable Bar struct replaces pandas Series; hasattr ladders deleted | ✓ SATISFIED | Bar@dataclass(frozen=True,slots=True,kw_only=True); BarEvent.bars:dict[str,Bar]; 0 get_last_* matches |
| M5-03 | 06-03, 06-05 | Resampled frames precomputed once per (ticker, timeframe); no resample in hot loop | ✓ SATISFIED (codebase) / PENDING (REQUIREMENTS.md) | feed.precompute() at run-init; feed.window() is pure searchsorted; 0 .resample() calls in strategy/universe/trading_system; test_zero_resample_calls_on_per_tick_path passes. **Note: REQUIREMENTS.md checkbox still [ ] — orchestrator update deferred per 06-03-SUMMARY.md** |
| M5-04 | 06-04 | Fee/slippage correct: maker fees live, tiered deleted, no slippage on limits, time.sleep removed | ✓ SATISFIED | tiered_fee_model.py absent; is_maker from real context; LIMIT guard in _emit_fill; grep time.sleep: 0 matches; REQUIREMENTS.md marked [x] |
| M5-05 | 06-02, 06-03, 06-05 | Provider/Store/Feed seams; offline read-only run path; loud errors; strategies use Feed API | ✓ SATISFIED (codebase) / PENDING (REQUIREMENTS.md) | PriceStore/PriceProvider/BarFeed ABCs live; data_provider.py deleted; CsvPriceStore raises MissingPriceDataError; SMA_MACD receives pd.DataFrame from feed.window(); strategies_handler has no price_handler. **Note: REQUIREMENTS.md checkbox still [ ] — orchestrator update deferred per 06-03-SUMMARY.md** |

**Orphaned Requirements Check:** REQUIREMENTS.md traceability table maps exactly M5-01..M5-05 to Phase 6. No orphaned IDs found.

**REQUIREMENTS.md documentation gap:** M5-03 and M5-05 are fully delivered in the codebase but their REQUIREMENTS.md checkboxes remain `[ ]` and the traceability table shows `Pending`. The 06-03-SUMMARY.md explicitly deferred these updates: "REQUIREMENTS.md checkoffs left to the orchestrator after the wave merges (worktree mode — shared-file writes are orchestrator-owned)." This is a documentation artifact requiring a one-line fix per requirement, not an implementation gap.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `itrader/portfolio_handler/portfolio_handler.py` | 361 | `getattr(bar, 'close_price', None)` — Bar struct has `close` not `close_price`; always returns None | WARNING | Dead code path (not called from any production or test caller on the run path); if ever invoked, silently feeds None prices into portfolio update. Documented as WR-06 in 06-REVIEW.md. |
| `itrader/portfolio_handler/portfolio_handler.py` | 355-377 | `update_portfolios_market` — entire method is dead, broken, and encodes pre-M5 payload shape | WARNING | No callers; event handler uses `update_portfolios_market_value`; advisory finding only. |

No `TBD`, `FIXME`, or `XXX` markers found in any phase-modified files. No unreferenced debt markers. No stub return values (`return []`, `return {}`, `return null`) in production code paths.

### Human Verification Required

#### 1. REQUIREMENTS.md Traceability Update

**Test:** Open `.planning/REQUIREMENTS.md` and update:
- Line 135: Change `- [ ] **M5-03**` to `- [x] **M5-03**`
- Line 139: Change `- [ ] **M5-05**` to `- [x] **M5-05**`
- Traceability table: Change M5-03 row `Pending` → `Complete` and M5-05 row `Pending` → `Complete`

**Expected:** REQUIREMENTS.md accurately reflects the codebase — both requirements are delivered and their checkboxes should be checked.

**Why human:** Pure documentation update. The codebase implementation is fully verified. The 06-03-SUMMARY.md explicitly deferred these checkoffs to the orchestrator after the wave merge. No code change required.

#### 2. WR-06 Dead-Code Disposition (update_portfolios_market)

**Test:** Review `itrader/portfolio_handler/portfolio_handler.py:355-377` — the `update_portfolios_market` method reads `bar.close_price` (wrong field; Bar has `close`), so all prices resolve to None. Confirmed dead: only called from `tests/unit/portfolio/test_portfolio_update.py:37` in a test, never from the production event handler.

**Expected:** Either (a) the method is deleted (preferred — WR-06 clean-up), or (b) owner confirms it is an acceptable known carryforward to Phase 7, or (c) the test at test_portfolio_update.py:37 is removed along with the dead method.

**Why human:** Requires a policy decision — whether to clean up dead code now or defer. The test exists for the broken method and would need updating. This is not blocking phase goal achievement (the run path is correct) but is a code-quality carryforward.

#### 3. CR-01 Disposition: Bracket Children Can Fill Before Parent

**Test:** Review `06-REVIEW.md` CR-01. The defect: bracket children (SL/TP) for a LIMIT or STOP primary entry are emitted to the book at signal time; `MatchingEngine.on_bar` evaluates ALL resting orders without checking that a child's parent has filled. A BUY-LIMIT entry at 95 + TP SELL-LIMIT at 110 will see the TP fill on a rally bar before the entry ever triggers, opening an unintended short.

**Expected:** Owner acknowledges whether:
(a) This is already known/deferred to Phase 7 M5b risk-layer work (acceptable — golden run uses only market orders with sl=0/tp=0, so oracle is unaffected), OR
(b) This should be fixed before proceeding to Phase 7 (blocking concern).

**Why human:** The REVIEW marks it Critical. The golden run path (SMA_MACD, market orders, sl=0/tp=0) cannot trigger this defect, so the current oracle and test suite are unaffected. The verifier cannot determine whether the owner considers this a Phase 6 blocker or an explicitly deferred Phase 7 item. A human decision is required before the phase is closed.

### Gaps Summary

No implementation gaps were found. All 4 ROADMAP Success Criteria are satisfied:

1. **SC-1 (Backtest validity):** Look-ahead removed (BacktestBarFeed completed-bars cutoff); limit-or-better fills implemented and tested; bar-timing contract documented in bar_feed.py module docstring as rules 1-7; same/other-timeframe branches agree by construction (D-02).

2. **SC-2 (Bar struct + precomputed frames):** Bar@dataclass(frozen=True,slots=True,kw_only=True) with Decimal OHLCV; BarEvent.bars:dict[str,Bar]; all get_last_* accessors deleted; feed.precompute() at run-init; feed.window() is pure searchsorted; 0 resample calls on the hot loop.

3. **SC-3 (Fee/slippage):** Maker fees from real order context; tiered model deleted; slippage only on MARKET/STOP; time.sleep removed. Full model-level test coverage.

4. **SC-4 (Provider/Store/Feed):** Three ABC seams live; data_provider.py deleted; CsvPriceStore raises loud typed errors; strategies pushed windows from feed.window(); no mid-run network fetch possible.

The only outstanding items are:
- A documentation update to REQUIREMENTS.md (M5-03 and M5-05 checkboxes — deferred to orchestrator)
- A policy decision on the WR-06 dead method (advisory)
- A policy decision on CR-01 from the code review (Critical finding; golden run unaffected but requires owner disposition)

---

_Verified: 2026-06-06T17:00:00Z_
_Verifier: Claude (gsd-verifier)_
