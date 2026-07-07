---
phase: 03-livebarfeed
plan: 02
subsystem: price-handler
tags: [live-feed, bar-feed, ring-buffer, monotonic-guard, barevent, decimal, tdd]

# Dependency graph
requires:
  - phase: 03-livebarfeed
    plan: 01
    provides: ClosedBar (symbol, timeframe) D-12 routing keys + offline fixtures (closed_bar, closed_bar_sequence, _StubProvider)
provides:
  - "LiveBarFeed(BarFeed) — capacity-sized deque ring per (symbol, timeframe), 4 ABC read-model members, public set_provider seam"
  - "FEED-04 monotonic-forward-only guard in update(): in-sequence / gap-backfill-replay / duplicate / revision / stale (D-06/D-07)"
  - "Direct single-ticker BarEvent emission onto global_queue (D-02/D-03/D-04) + dormant no-op generate_bar_event (D-05)"
affects: [03-03 warmup+reconnect (extends update() guard), 03-04 composition-root wiring + D-13 registration + inertness gate]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Push-driven ring BarFeed: update(ClosedBar) constructs Bar + appends to deque(maxlen=cache_capacity()) + emits BarEvent directly (no TimeEvent pull)"
    - "Monotonic guard classifies t vs last-delivered L per (symbol, timeframe) — out-of-order/replayed bars cannot rewind indicator state (D-06/D-07)"
    - "Gap backfill-and-replay through the SAME update() path (FEED-03 one path); recursion terminates as each replayed bar advances L by one tf"
    - "TYPE_CHECKING-guarded ClosedBar import + from __future__ import annotations keeps aiohttp/connector code out of the module import graph"

key-files:
  created:
    - itrader/price_handler/feed/live_bar_feed.py
    - tests/unit/price/test_live_bar_feed.py
  modified: []

key-decisions:
  - "Task 1 implements a deliver-only update() (happy path) so its own listed behaviors (tz-aware emit, ring eviction, newest_bar) are testable; the FEED-04 guard is layered on ahead of delivery in Task 2 (the plan's 'do not implement update() yet' could not co-exist with Task-1's emit/ring behaviors — Rule 3 clarification)"
  - "ClosedBar imported under TYPE_CHECKING (annotations only) to keep the module import light and hot-path-inert; live_bar_feed is NOT added to the feed package barrel (inertness gate, 03-04)"
  - "Reused bar_feed._offset_alias + _AGG for window()/resample rather than re-implementing (plan-endorsed; never the legacy time_parser string, Pitfall 4)"

patterns-established:
  - "_emit(sym, bar) is the Phase-6 burst-coalescing seam — a consolidator slots in WITHOUT changing the BarEvent contract (D-04)"
  - "Drops (stale/duplicate/revision) are logged (WARN/debug), never raised, never mutate state — legitimate venue events"

requirements-completed: [FEED-02, FEED-04]

# Metrics
duration: 9min
completed: 2026-07-01
---

# Phase 03 Plan 02: LiveBarFeed ring + monotonic guard + direct BarEvent emission Summary

**`LiveBarFeed(BarFeed)` — a push-driven ring-buffer feed that ingests confirm-gated `ClosedBar`s, enforces the FEED-04 monotonic-forward-only taxonomy, builds tz-aware `Bar`s from the Decimal edge, and emits single-ticker `BarEvent`s directly onto `global_queue`, TDD'd against a socket-free `ClosedBar` matrix.**

## Performance

- **Duration:** ~9 min
- **Started:** 2026-07-01T19:53:01Z
- **Completed:** 2026-07-01T20:02:13Z
- **Tasks:** 2 (both `type="tdd"`)
- **Files:** 2 created

## Accomplishments
- Built the heart of Phase 3: `LiveBarFeed`, a second concrete `BarFeed` with a bounded `deque(maxlen=cache_capacity())` ring per `(symbol, timeframe)` (FEED-01, D-09 — maxlen read lazily at ring creation so the 03-04 D-13 registration sizes it to 100).
- Implemented the four ABC read-model members (`newest_bar`, `current_bars`, `window`, `megaframe`) plus tz-aware `Bar` construction straight from the Decimal `ClosedBar` fields (no float re-cast, no `from_row` — D-14), and `window()` mirroring the backtest rule-4 completed-bars cutoff (D-11 pull-resample via `_offset_alias`).
- Implemented the FEED-04 monotonic guard in `update()`: classifies incoming open-time `t` vs last-delivered `L` per `(symbol, timeframe)` — in-sequence deliver, gap backfill-and-replay, duplicate drop, revision forward-only WARN+drop (no state mutation, D-07), stale reject (D-06) — with direct single-ticker `BarEvent` emission (D-02/D-03/D-04).
- Provided a public `set_provider()` seam (the only post-construction provider write path, D-01/D-13) and a dormant no-op `generate_bar_event` (D-05) so `LiveTradingSystem.__init__` can pass `self.feed.generate_bar_event` to `EventHandler` without crashing on any venue.
- Kept the module hot-path-inert (TYPE_CHECKING-guarded `ClosedBar` import, NOT re-exported from the feed barrel) — the inertness probe confirms a backtest-root import leaks no live/ccxt modules.

## Task Commits

Each task followed the RED → GREEN TDD gate:

1. **Task 1 (RED): failing read-model matrix** — `62212350` (test)
2. **Task 1 (GREEN): LiveBarFeed skeleton + ABC read-model** — `47339838` (feat)
3. **Task 2 (RED): failing monotonic-guard matrix** — `77601a23` (test)
4. **Task 2 (GREEN): monotonic guard update() + D-06 taxonomy** — `052ba207` (feat)

## Files Created
- `itrader/price_handler/feed/live_bar_feed.py` — `LiveBarFeed(BarFeed)`: ring + monotonic guard + direct emission + `set_provider` seam + dormant `generate_bar_event`.
- `tests/unit/price/test_live_bar_feed.py` — FEED-01/02/04 offline unit matrix (14 tests: synthetic `ClosedBar` + real `queue.Queue`, socket-free).

## Decisions Made
- **Task-1 `update()` scope (Rule 3 clarification):** the plan's Task-1 behavior tests (`emit_time_tz_aware`, `ring_maxlen_evicts`, `newest_bar_reads_last`) require an emission/delivery path, which is impossible under a strict "do not implement `update()` yet." Resolved by implementing a **deliver-only `update()`** in Task 1 (construct + ring + emit) and layering the full FEED-04 guard (stale/duplicate/revision/gap) ahead of delivery in Task 2. Both tasks retain real code and real failing-first tests; the requirement split maps cleanly (Task 1 = FEED-01/02, Task 2 = FEED-04).
- **Import hygiene:** `ClosedBar` (a TypedDict, annotations-only) imported under `TYPE_CHECKING` with `from __future__ import annotations`, keeping aiohttp/connector code out of the module's runtime import graph; `LiveBarFeed` deliberately absent from the `feed` package barrel (inertness gate lands in 03-04).
- **Reuse over re-implement:** `window()`/resample reuse `bar_feed._offset_alias` + `_AGG` (plan-endorsed) — never the legacy `time_parser` string for resample rules (Pitfall 4).

## Deviations from Plan

### Auto-fixed / Clarified Issues

**1. [Rule 3 - Blocking plan ambiguity] Task-1 `update()` deliver path**
- **Found during:** Task 1 (writing the RED tests).
- **Issue:** Task 1's `<behavior>` lists `emit_time_tz_aware` and `ring_maxlen_evicts` (both require emission/delivery), yet Task 1's `<action>` says "Do NOT implement `update()` yet (Task 2)." These are mutually exclusive.
- **Fix:** Implemented a minimal deliver-only `update()` in Task 1 (happy path: construct + ring append + emit), and added the full monotonic guard (the D-06 classifier branches) ahead of the delivery call in Task 2. No behavior was skipped; the two-task split remains meaningful.
- **Files modified:** `itrader/price_handler/feed/live_bar_feed.py`
- **Commits:** `47339838` (Task 1 deliver-only), `052ba207` (Task 2 guard).

## Issues Encountered
None beyond the Task-1 `update()` clarification above.

## User Setup Required
None — the build and its gate run fully offline (synthetic `ClosedBar` sequences); no OKX socket or credentials required.

## Next Phase Readiness
- **03-03 (warmup + reconnect):** the FEED-03 warmup driver and D-08 reconnect gap-fill build directly on the `update()` gap-backfill-replay path already in place; `self._provider.fetch_ohlcv_backfill(...)` is the injected seam they extend.
- **03-04 (composition-root wiring):** `set_provider()` is the provider→feed wire; the D-13 `RawBarConsumer` registration will size `cache_capacity()` (and thus the ring `maxlen`) to 100; the inertness gate extends `_FORBIDDEN` with `itrader.price_handler.feed.live_bar_feed` (already inert by construction).

## Verification
- `poetry run pytest tests/unit/price/test_live_bar_feed.py -q` → 14 passed.
- `poetry run pytest tests/unit/price tests/unit/connectors -q` → 69 passed (no regressions).
- `poetry run mypy --strict itrader/price_handler/feed/live_bar_feed.py` → clean.
- Greps: `deque(maxlen=self.cache_capacity())`, `pd.Timestamp(... unit="ms" ... tz="UTC")`, `def set_provider`, `def generate_bar_event`, `global_queue.put(BarEvent`, `self._provider.fetch_ohlcv_backfill` all present; no `Decimal(` float cast, no `.from_row(`, no `datetime.now()` call (only a docstring warning against it).
- Inertness probe: `import itrader.trading_system.backtest_trading_system` leaks no `live_bar_feed`/`ccxt`/`ccxt.pro`.

## Self-Check: PASSED
- FOUND: itrader/price_handler/feed/live_bar_feed.py
- FOUND: tests/unit/price/test_live_bar_feed.py
- FOUND commit: 62212350 (Task 1 RED)
- FOUND commit: 47339838 (Task 1 GREEN)
- FOUND commit: 77601a23 (Task 2 RED)
- FOUND commit: 052ba207 (Task 2 GREEN)

## TDD Gate Compliance
- Task 1: `test(03-02)` (`62212350`, RED) → `feat(03-02)` (`47339838`, GREEN). ✅
- Task 2: `test(03-02)` (`77601a23`, RED) → `feat(03-02)` (`052ba207`, GREEN). ✅
- Both RED commits verified failing before their GREEN implementation (collection error / 4 guard-test failures respectively).

---
*Phase: 03-livebarfeed*
*Completed: 2026-07-01*
