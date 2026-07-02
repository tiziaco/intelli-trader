---
phase: 04-paper-path-milestone-dod
reviewed: 2026-07-02T12:58:50Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - itrader/price_handler/providers/replay_provider.py
  - itrader/trading_system/live_trading_system.py
  - scripts/run_live_paper.py
  - tests/unit/price/test_replay_provider.py
  - tests/integration/test_live_paper_lifecycle.py
  - tests/integration/test_paper_parity.py
  - tests/integration/test_okx_inertness.py
findings:
  critical: 0
  warning: 5
  info: 4
  total: 9
status: resolved
resolution:
  resolved_at: 2026-07-02
  via: quick task 260702-m8d (commits 13d083ef, 8a4a507e)
  fixed: 6      # IN-01, IN-02, IN-03, IN-04, WR-03, WR-05
  partial: 1    # WR-02 (assertion/window-guard done; structural shared-config refactor deferred)
  deferred: 2   # WR-01, WR-04 — deferred to Phase 5 (live-drive path)
---

## Resolution (2026-07-02)

Fixes applied via quick task `260702-m8d`; parity gate re-verified byte-exact
(oracle `134 / 46189.87730727451`), full gate 13 passed, `mypy --strict` clean.

| Finding | Disposition | Where |
|---------|-------------|-------|
| WR-01 | **Deferred → Phase 5** | Live daemon metrics belong to the real/sandbox live-drive path Phase 5 builds; record cadence decided there. |
| WR-02 | **Partially resolved** | Assertion half done — wiring-time window guard added (`13d083ef`). Structural single-shared-config refactor **deferred → Phase 5**. |
| WR-03 | **Resolved** | `13d083ef` — per-bar metric stamped off the replayed bar; skip-on-mismatch (no stale re-record). |
| WR-04 | **Deferred → Phase 5** | Error-policy divergence (publish-and-continue vs fail-fast) is a parity-semantics decision for Phase 5. |
| WR-05 | **Resolved** | `8a4a507e` — `_run_okx_smoke` teardown made unconditional (try/finally). |
| IN-01 | **Resolved** | `13d083ef` — removed unused `import time`. |
| IN-02 | **Resolved** | `13d083ef` — trimmed unused `TimeEvent`/`OrderEvent` imports. |
| IN-03 | **Resolved** | `8a4a507e` — deleted dead `DATASET` literal. |
| IN-04 | **Resolved** | `13d083ef` — magic `'ORDER'` → `EventType.ORDER.name`; TODO removed. |

The two deferred warnings + the WR-02 structural half are tracked as Phase 5 inputs.

# Phase 4: Code Review Report

**Reviewed:** 2026-07-02T12:58:50Z
**Depth:** standard
**Files Reviewed:** 7
**Status:** issues_found

## Summary

Phase 04 adds the offline paper-trading path: `ReplayDataProvider` (offline OKX
stand-in), `LiveTradingSystem.run_paper_replay()`, a runnable worker
(`run_live_paper.py`), and the milestone DoD paper-parity gate plus the OKX-inertness
gate. The core replay provider is small, well-scoped, and correctly holds the Decimal
edge (`to_money(str(x))`), stamps trusted routing keys, and preserves the tz-aware
bar-open instant via `int(row.Index.value // 1_000_000)`. Indentation is clean (4-space,
no stray tabs in either new module). The inertness gate and lifecycle tests are sound.

No BLOCKER-level correctness defects were found on the DoD paper path itself. However
the review surfaces one real defect on the sibling live-daemon path (metrics never
record in daemon mode), several **implicit parity couplings** that make the DoD gate
pass by coincidence rather than by construction (the exact thing the phase brief warned
against), a connector-leak on the manual smoke path, and dead/unused imports and
config literals.

## Warnings

### WR-01: Live daemon mode never records portfolio metrics (keys on TIME, feed emits only BAR)

**File:** `itrader/trading_system/live_trading_system.py:606-608`
**Issue:** The daemon `_event_processing_loop` records portfolio metrics only when
`event.type == EventType.TIME`:
```python
if hasattr(event, 'type') and event.type == EventType.TIME:
    for portfolio in self.portfolio_handler.get_active_portfolios():
        portfolio.record_metrics(event.time)
```
But `LiveBarFeed` emits **only `BarEvent`** directly onto the queue
(`live_bar_feed.py:353`, `_emit`); it never produces a `TimeEvent` — its
`generate_bar_event` is a dormant no-op and there is no `TimeGenerator` in the live
system. Therefore in the live daemon path (`start()` -> `_event_processing_loop`, i.e.
the `okx` venue), `record_metrics` is **never called** and no equity curve is ever
produced. This branch is effectively dead code on the live path. The DoD paper path
sidesteps it (`run_paper_replay` records metrics directly per bar, correctly), so the
milestone gate is unaffected — but the reviewed live path is silently metric-less.
**Fix:** Record metrics on the driving event the live feed actually emits. Either key
on `EventType.BAR` (using `event.time`) or, mirroring `run_paper_replay`, record after
processing a bar via `self.feed.newest_bar(...).time`:
```python
if hasattr(event, 'type') and event.type == EventType.BAR:
    for portfolio in self.portfolio_handler.get_active_portfolios():
        portfolio.record_metrics(event.time)
```

### WR-02: Paper/backtest parity is coincidental, not structurally enforced (date window + exchange_config)

**File:** `itrader/price_handler/providers/replay_provider.py:89`,
`itrader/trading_system/live_trading_system.py:204,341-342`
**Issue:** The DoD brief explicitly requires the parity gate to survive future rework by
anchoring paper to a fresh backtest run — but the two paths are wired from **different
sources** and only happen to agree today:
1. **Date window.** The backtest in `test_paper_parity.py` is constructed with explicit
   `start_date="2018-01-01", end_date="2026-06-03"`. The paper path constructs
   `ReplayDataProvider()` -> `CsvPriceStore()` with **no window**, relying on the store
   class defaults `CSV_START_DATE='2018-01-01'` / `CSV_END_DATE='2026-06-03'`
   (`csv_store.py:47-48`). Parity holds only because the test's literals equal the store
   defaults. If either the backtest date literals or the store defaults change (they live
   in different files), paper silently replays a different bar set and the count-equality
   assertions break with a confusing diff instead of a clear config error.
2. **Exchange config.** The backtest threads a factory-selected, symbol-seeded
   `exchange_config` into `ExecutionHandler` (`compose.py:187`,
   default preset ∪ {BTCUSD}); the live path passes **none**
   (`ExecutionHandler(self.global_queue)`, line 204) and falls back to the default
   preset. Byte-parity depends on the default preset admitting `BTCUSD` and yielding the
   same limits — not on any shared wiring.
**Fix:** Make the coupling explicit. Thread the same window into the replay store
(`ReplayDataProvider(store=CsvPriceStore(start_date=..., end_date=...))`) and/or add a
wiring-time assertion in `run_paper_replay`/`_run_paper_frames` that the replay store's
`(start_date, end_date, symbols)` equals the backtest window. Prefer constructing both
sides from one shared config literal so a future date change cannot desync them.

### WR-03: `run_paper_replay` records metrics off `newest_bar`, which repeats a stale stamp if a bar is dropped

**File:** `itrader/trading_system/live_trading_system.py:555-560`
**Issue:** The per-bar metric is stamped from `self.feed.newest_bar(_PAPER_STREAM_SYMBOL).time`:
```python
newest = self.feed.newest_bar(_PAPER_STREAM_SYMBOL)
if newest is None:
    continue
bar_time = newest.time
for portfolio in self.portfolio_handler.get_active_portfolios():
    portfolio.record_metrics(bar_time)
```
`newest_bar` returns the last **delivered** bar. If the `LiveBarFeed` monotonic guard
drops the just-replayed bar (stale / duplicate / off-grid / forward-only revision —
`live_bar_feed.py:167-183`), `replay_bar` still returns and this loop still runs, but
`newest.time` is the **previous** bar's stamp. The result is a second `record_metrics`
call at an already-recorded timestamp (a duplicated/misaligned equity point), diverging
from the backtest, whose loop keys record_metrics off the tick grid
(`backtest_runner.py:153`) and records exactly once per tick regardless of feed state.
The golden dataset is contiguous so no drop fires today, but this is a latent
correctness gap in the parity mechanism.
**Fix:** Drive record_metrics off the bar actually replayed this iteration, not the
feed's newest-delivered state — e.g. stamp from `cb["ts"]` (the bar being pushed) or
skip the metric when the guard dropped the bar (compare `newest.time` against the
replayed stamp and `continue` on mismatch).

### WR-04: Paper replay inherits the live publish-and-continue error policy, not backtest fail-fast

**File:** `itrader/trading_system/live_trading_system.py:358,511-567`
**Issue:** `__init__` rebinds `self.event_handler._on_handler_error =
self._publish_and_continue` for the whole system, so `run_paper_replay` (the "mirror the
backtest discipline" synchronous driver) actually runs under **publish-and-continue**,
while the backtest it is diffed against is **fail-fast** (`backtest_runner.py` re-raises
via the EventHandler seam). On the golden happy path no handler raises, so results
agree; but if a handler ever fails mid-replay, paper swallows it (emits an `ErrorEvent`,
keeps draining) and produces a partial result that the parity test could compare against
a backtest that would have aborted — a false green or a confusing diff instead of a
loud failure. The determinism/parity claim in the `run_paper_replay` docstring does not
mention this policy divergence.
**Fix:** Either document that the paper driver deliberately keeps the live error policy
(and accept that error-path parity is out of scope), or, for the deterministic replay
driver specifically, run it under fail-fast so a handler failure aborts the replay the
same way the backtest aborts.

### WR-05: `_run_okx_smoke` leaks the OKX connector when `start()` returns False

**File:** `scripts/run_live_paper.py:130-144`
**Issue:**
```python
started = system.start()
...
if not started:
    print(f"Status: {system.get_status()}")
    return                      # <-- returns before the try/finally
try:
    time.sleep(5.0)
finally:
    stopped = system.stop(timeout=10.0)
```
`stop()` is the documented unconditional teardown for the OKX connector (its
`disconnect()` runs in a `finally` regardless of `_running`, per CR-01 in
`live_trading_system.py:693-740`). But the early `return` on `not started` skips
`stop()` entirely, so a partially-connected connector (e.g. `connect()` built the ccxt
client / loaded markets before a later failure) is never torn down — a leaked
authenticated socket / `ResourceWarning`. This is the manual network smoke path (never
CI), so impact is low, but it defeats the connector-teardown guarantee the code went to
lengths to provide.
**Fix:** Call `system.stop(timeout=...)` on the failed-start path too (or wrap the whole
smoke body in `try/finally` around `stop()`), so `connector.disconnect()` always runs.

## Info

### IN-01: Unused import `time` in live_trading_system.py

**File:** `itrader/trading_system/live_trading_system.py:5`
**Issue:** `import time` at module scope is never used — all time access goes through
`datetime.now(UTC)`. (Confirmed: no `time.` call in the module.)
**Fix:** Remove `import time`.

### IN-02: Unused imports `TimeEvent`, `OrderEvent`

**File:** `itrader/trading_system/live_trading_system.py:28`
**Issue:** `from itrader.events_handler.events import EventType, TimeEvent, OrderEvent,
ErrorEvent` — only `EventType` and `ErrorEvent` are referenced in code; `TimeEvent` and
`OrderEvent` appear only inside a comment (line 374).
**Fix:** Trim to `from itrader.events_handler.events import EventType, ErrorEvent`.

### IN-03: Dead/misleading `DATASET` literal in the paper worker

**File:** `scripts/run_live_paper.py:47`
**Issue:** `DATASET = "data/BTCUSD_1d_ohlcv_2018_2026.csv"  # D-02 (same golden feed as
the backtest)` is documented as pinning the golden feed but is **never passed** to
`ReplayDataProvider`, `CsvPriceStore`, or `LiveTradingSystem` — the actual dataset comes
from `CsvPriceStore` class defaults. A maintainer editing `DATASET` to point the paper
run at another file would see no effect (silent no-op), and it falsely advertises a
wiring seam that does not exist.
**Fix:** Either wire `DATASET` through (`ReplayDataProvider(store=CsvPriceStore(
csv_paths={TICKER: DATASET}))`) so it is load-bearing, or delete the constant and let
the store default stand as the single source.

### IN-04: Leftover TODO and magic string in `_update_stats`

**File:** `itrader/trading_system/live_trading_system.py:427-429`
**Issue:** `_update_stats` compares `event_type == 'ORDER'` (a stringly-typed magic
literal) and carries a leftover `# TODO: Add more specific event type handling ...`
comment. The event-type namespace already exists as `EventType`; the string compare is
brittle relative to the enum used elsewhere in the same file.
**Fix:** Compare against the enum name via the existing `EventType` (or drop the
per-type stat if unused) and resolve/remove the TODO.

---

_Reviewed: 2026-07-02T12:58:50Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
