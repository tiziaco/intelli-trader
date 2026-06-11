---
phase: 03-minimal-real-universe
plan: 02
subsystem: price-handler-feed
tags: [span-aware, availability, observability, oracle-dark, log-surface, D-04, D-05]

# Dependency graph
requires:
  - phase: 03-minimal-real-universe
    plan: 01
    provides: "is_active(spans, ticker, asof) pure availability primitive (UNIV-01)"
provides:
  - "BacktestBarFeed._spans — {ticker: (first, last)} tz-aware span cache built once at __init__ from loaded frames (M5-03 compute-once)"
  - "Span-aware generate_bar_event warn loop (D-04): silent for expected absence, warns only on a true mid-life gap"
  - "Single observability owner: the feed (D-04) — the strategy-handler duplicate warning removed (D-05)"
affects: [03-03 (integration over synthetic differing-span fixtures), v1.3-screener (consumes the same availability seam)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Compute-once-at-init span cache reusing the existing frame loop (zero extra store reads, M5-03)"
    - "Span-aware absence observability consulting is_active as a derived read, NOT a gate (D-02)"
    - "tz-aware pd.Timestamp span bounds matching the tick type (Pitfall 2 — no naive/aware TypeError)"

key-files:
  created: []
  modified:
    - itrader/price_handler/feed/bar_feed.py
    - itrader/strategy_handler/strategies_handler.py
    - tests/unit/price/test_bar_feed.py

key-decisions:
  - "Span bounds stored as tz-aware pd.Timestamp (NOT .to_pydatetime()) — same type the tick carries, mirrors current_bars' searchsorted (Pitfall 2)"
  - "is_active consulted as a derived read in the log-only warn loop; bars/current_bars/BarEvent byte-unchanged (D-02, oracle-dark)"
  - "LATEUSD pre-listing test INVERTED (silence) not appended — a D-04 semantics change; added post-end silence + mid-life-gap WARN + span-cache cases"

requirements-completed: [UNIV-02]

# Metrics
duration: 4min
completed: 2026-06-09
---

# Phase 3 Plan 02: Span-Aware Feed Observability Summary

**Wired the Plan-01 `is_active` primitive into the feed as a derived read (D-02): a compute-once `{ticker: (first, last)}` tz-aware span cache plus a span-aware `generate_bar_event` warn loop (D-04 — silent for pre-listing/post-end, warns only on a true mid-life gap), the duplicate strategy-handler warning deleted (D-05), all log/query-surface only so the BTCUSD oracle stays byte-identical.**

## Performance

- **Duration:** ~4 min
- **Started:** 2026-06-09
- **Completed:** 2026-06-09
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments
- `BacktestBarFeed.__init__` now builds `self._spans: dict[str, tuple[datetime, datetime]]` inside the SAME existing frame loop — bound a local `frame` once, so `store.read_bars` is still called exactly twice in the module (no second read added, M5-03 compute-once). Span bounds are the loaded frame's own `index[0]`/`index[-1]`, kept as tz-aware `pd.Timestamp` (the same type the tick carries — Pitfall 2: no naive/aware `TypeError` under `filterwarnings=["error"]`).
- `generate_bar_event` warn loop is now span-aware (D-04): warns iff `ticker not in bars and is_active(self._spans, ticker, time_event.time)` (a true mid-life gap), otherwise SILENT for expected absence (pre-listing / post-end). `bars`, `current_bars`, and the `BarEvent(...)` construction are byte-unchanged (oracle-dark, log-only).
- `strategies_handler.py` (TABS): deleted ONLY the `'No last close for %s — signal skipped'` `logger.warning` (D-05), keeping the load-bearing `if bar is None: continue` skip (price stamped from `bar.close` three lines later). The feed is now the single span-aware observability owner.
- `tests/unit/price/test_bar_feed.py`: INVERTED the LATEUSD pre-listing case (now `test_no_warn_before_listing`, asserts `caplog.records == []`); added `test_no_warn_after_end` (post-end silence), `test_warn_on_mid_life_gap` (new `gappy_feed` fixture, Jan 1..4 + Jan 6..10 missing Jan 5 → WARN naming ticker + date), and `test_spans_cache_matches_loaded_frame` (`feed._spans[ticker] == (index[0], index[-1])`, tz-aware).

## Task Commits

Each task was committed atomically:

1. **Task 1: _spans cache + span-aware generate_bar_event (D-04)** — `a196512` (feat)
2. **Task 2: delete the duplicate strategy-handler warning, keep the skip (D-05)** — `0b49f45` (refactor)
3. **Task 3: invert LATEUSD case + mid-life-gap & span-cache tests** — `60ff83f` (test)

## Files Created/Modified
- `itrader/price_handler/feed/bar_feed.py` (4 spaces) — added `from itrader.universe import is_active`; the `_spans` cache in the existing `__init__` loop (local `frame` bound once); span-aware warn condition in `generate_bar_event`. `current_bars`, `bars`, and the `BarEvent` tail untouched.
- `itrader/strategy_handler/strategies_handler.py` (TABS) — removed the legacy `logger.warning` absence line; kept `bar = event.bars.get(ticker)` / `if bar is None: continue` and the `price=to_money(bar.close)` stamp; expanded the WR-12 comment to record the D-04/D-05 single-owner rationale.
- `tests/unit/price/test_bar_feed.py` (4 spaces) — inverted the pre-listing case, added the `gappy_feed` fixture and three new tests (post-end silence, mid-life-gap WARN, span-cache equality). All stamps via `ts()`; fixtures via `write_kline_csv`.

## Decisions Made
None new — followed the plan and honored locked CONTEXT decisions D-02 (derived read, not a gate), D-04 (feed is the single span-aware observability owner), D-05 (delete only the warning, keep the skip). The one discretionary call (keep span bounds as tz-aware `pd.Timestamp` rather than `.to_pydatetime()`) follows the plan's explicit guidance and Pitfall 2.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None. Note: after Task 1 the old LATEUSD warn-all test failed by design (the D-04 semantics change), and was inverted in Task 3 (its plan-designated task), not patched in Task 1.

## Verification
- `poetry run pytest tests/unit/price/test_bar_feed.py -x` → 19 passed (span cache + D-04 warn semantics incl. inverted LATEUSD).
- `poetry run pytest tests/unit/strategy/ -x` → 9 passed (D-05 deletion did not break strategy units; `test_sparse_ticker_guard_skips_silently` green).
- `grep -r "No last close" itrader/ tests/` → no matches (warning fully removed).
- `grep -c "store.read_bars" itrader/price_handler/feed/bar_feed.py` → 2 (unchanged — no second store read added).
- `poetry run mypy itrader/price_handler/feed/bar_feed.py` → Success: no issues found.
- `poetry run pytest tests/integration/test_backtest_oracle.py -x` → 2 passed (oracle-dark invariant: BTCUSD byte-identical).

## Known Stubs
None — no placeholder/empty-data stubs introduced. All changes are log/query-surface refinements over real loaded frames.

## Next Phase Readiness
- UNIV-02's observability half is in place: the feed is the single span-aware owner (D-04), the duplicate warning is gone (D-05), and the inverted LATEUSD case locks the semantics change.
- The bar/fill path (`current_bars`, `bars`, `BarEvent`) was not touched — the BTCUSD oracle stays byte-identical (oracle-dark).
- Ready for Plan 03 (synthetic-fixture engine integration proving mid-run listing + differing end dates end-to-end, D-06).

## Self-Check: PASSED
- FOUND: itrader/price_handler/feed/bar_feed.py (self._spans + is_active(self._spans warn condition)
- FOUND: itrader/strategy_handler/strategies_handler.py (if bar is None: continue preserved, warning removed)
- FOUND: tests/unit/price/test_bar_feed.py (_spans test + inverted pre-listing + mid-life-gap)
- FOUND: commit a196512 (Task 1 feat)
- FOUND: commit 0b49f45 (Task 2 refactor)
- FOUND: commit 60ff83f (Task 3 test)

---
*Phase: 03-minimal-real-universe*
*Completed: 2026-06-09*
