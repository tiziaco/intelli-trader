---
phase: 07-live-dynamic-universe-hardening
plan: 03
subsystem: price-handler (live feed + data arm)
tags: [live-warmup, async, msgspec-events, ring-buffer, decimal-edge, security-scrub]

# Dependency graph
requires:
  - phase: 07-01 (v1.7)
    provides: BarsLoaded / BarsLoadFailed frozen event structs + EventType members
  - phase: 03 (v1.7)
    provides: LiveBarFeed ring/L monotonic guard + _deliver/_build_bar; OkxDataProvider REST backfill + connector.spawn
provides:
  - "LiveBarFeed.absorb_warmup(sym, tf, bars) — non-emitting silent ring/L absorb (warms ring + advances L, NO BarEvent)"
  - "OkxDataProvider.spawn_warmup(sym, tf, limit) — async loop-native REST fetch emitting ONE BarsLoaded/BarsLoadFailed"
  - "LiveBarFeed._build_bar promoted to @staticmethod — the ONE canonical ClosedBar→Bar conversion, reusable read-only"
  - "OkxDataProvider.set_global_queue seam + _on_warmup_done supervisor"
affects: [07-04, 07-06, 07-07, live-warmup-before-subscribe, per-symbol-readiness-gate]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Non-emitting deliver twin (absorb = _deliver minus _emit) — single-purpose absorb, not a second state path (D-03a)"
    - "Async fetch-and-emit arm: connector.spawn (threadsafe) + supervised done-callback, scrubbed failure event (mirrors spawn_gap_backfill)"

key-files:
  created:
    - tests/unit/price/test_absorb_warmup.py
    - tests/unit/price/test_spawn_warmup.py
  modified:
    - itrader/price_handler/feed/live_bar_feed.py
    - itrader/price_handler/providers/okx_provider.py

key-decisions:
  - "absorb_warmup reuses the EXACT _deliver ring/L/newest-bar logic MINUS _emit (single divergence, D-03b/OQ1) — no tradeable BarEvent during warmup"
  - "_build_bar made @staticmethod so spawn_warmup reuses the ONE canonical ClosedBar→Bar conversion read-only (D-03a) — no second bulk conversion"
  - "spawn_warmup schedules via connector.spawn (threadsafe call_soon_threadsafe, engine-thread trigger, Pitfall 6), never create_task/call().result()"
  - "BarsLoaded.time = newest venue bar's open-time (business time, Pitfall 5); BarsLoadFailed.reason = exception TYPE name only (scrub, T-05-27/V5)"
  - "BarsLoadFailed.time = datetime.now(UTC): live-only control-plane failure signal with no venue bar to source from (oracle-inert, mirrors the allowed poll-timer wall-clock)"
  - "Empty warmup fetch → scrubbed BarsLoadFailed (readiness→FAILED) rather than an empty BarsLoaded that breaks the non-empty payload contract"
  - "set_global_queue post-construction seam (like set_bar_sink); provider carries no membership/readiness knowledge — it fetches and emits"

patterns-established:
  - "Warmup pipeline halves: provider spawn_warmup (I/O → BarsLoaded) and feed absorb_warmup (BarsLoaded → silent ring/L) are the two seams the plan-06 consumer wires"

requirements-completed: [WR-02]

# Metrics
duration: ~10min
completed: 2026-07-06
---

# Phase 7 Plan 03: Async Warmup Halves (absorb + spawn_warmup) Summary

**Split the synchronous `warmup()` flood into the two non-blocking WR-02 halves (D-03): a NEW non-emitting `LiveBarFeed.absorb_warmup` (silent ring/L absorb, `_deliver` minus `_emit`) and a NEW async `OkxDataProvider.spawn_warmup` (loop-native REST fetch → ONE bulk `BarsLoaded`, or ONE scrubbed `BarsLoadFailed` on failure) — live-only, oracle-inert.**

## Performance

- **Duration:** ~10 min
- **Tasks:** 2 (both `tdd="true"`)
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments
- `LiveBarFeed.absorb_warmup(symbol, timeframe, bars)` warms the ring + advances the last-delivered stamp `L` from a pre-built `Bar` tuple with the EXACT `_deliver` ring/L/newest-bar logic MINUS `_emit` — closing the warmup-before-subscribe `L` contract (RESEARCH OQ1) so the first live `update()` lands in-sequence, and putting ZERO `BarEvent`s on the queue (D-03b: no tradeable bar during warmup).
- `LiveBarFeed._build_bar` promoted to `@staticmethod` (it was self-less) so it is the ONE canonical `ClosedBar → Bar` conversion, reused read-only by the provider (D-03a — no second bulk conversion path).
- `OkxDataProvider.spawn_warmup(symbol, timeframe, limit)` runs ONLY the loop-native async REST fetch (`_fetch_ohlcv_backfill_async`, no `call().result()` bridge) scheduled via `connector.spawn` (threadsafe — engine-thread trigger, Pitfall 6), and hands ALL fetched bars back to the engine thread as ONE `BarsLoaded` (bulk transport, D-03) with business `time` = newest venue bar.
- Failure path emits exactly ONE `BarsLoadFailed` with a SCRUBBED `reason` (exception TYPE name only, never `str(exc)`/secrets — T-05-27/Security V5), plus a supervised `_on_warmup_done` done-callback (D-11 → halt) for any crash outside the coroutine's own scrubbed except.
- Two new socket-free unit suites (`test_absorb_warmup.py` 4 tests, `test_spawn_warmup.py` 6 tests) lock all four behaviors of each method, including the scrub assertion (raised message absent from `reason`) and the `connector.spawn`-not-`create_task` scheduling.

## Task Commits

1. **Task 1: LiveBarFeed.absorb_warmup (non-emitting ring/L absorb)** — `6fae84e0` (feat)
2. **Task 2: OkxDataProvider.spawn_warmup async fetch → BarsLoaded/BarsLoadFailed** — `11fa56f2` (feat)

## Files Created/Modified
- `itrader/price_handler/feed/live_bar_feed.py` (modified, 4-SPACE) — `absorb_warmup` added; `_build_bar` → `@staticmethod`
- `itrader/price_handler/providers/okx_provider.py` (modified, 4-SPACE) — `spawn_warmup` + `_run_warmup` + `_closed_bars_to_bars` + `_on_warmup_done` + `set_global_queue` + `_global_queue` field; imports `BarsLoaded`/`BarsLoadFailed`/`StateError`/`MissingPriceDataError`/`datetime`/`queue`
- `tests/unit/price/test_absorb_warmup.py` (created, 4-SPACE, `unit`) — 4 tests
- `tests/unit/price/test_spawn_warmup.py` (created, 4-SPACE, `unit`) — 6 tests

## Decisions Made
- Followed the plan exactly. Key pins: absorb = `_deliver` minus `_emit` (single divergence, D-03a/OQ1); `_build_bar` static reuse (D-03a); `connector.spawn` threadsafe scheduling (Pitfall 6); newest-bar business time on success + `datetime.now(UTC)` on the live-only failure signal (Pitfall 5, oracle-inert); scrubbed `reason` (T-05-27/V5).
- Matched per-file 4-SPACE indentation across `price_handler/feed` and `price_handler/providers`.

## Deviations from Plan

### Auto-added (Rule 2 — correctness requirements not spelled out in the plan snippet)

**1. [Rule 2] `set_global_queue` seam + `StateError` unbound guard**
- **Found during:** Task 2 — the plan's `self._global_queue.put(...)` presumes a queue reference the provider did not have (it was a pure fetch-and-hand-to-sink arm).
- **Fix:** Added a `set_global_queue` post-construction seam (mirroring `set_bar_sink`) + a `_global_queue` field; `spawn_warmup` raises a typed `StateError` (never a `-O`-strippable assert) if unbound before scheduling. Composition-root wiring is deferred to the consumer plan (07-06/07).
- **Files:** `itrader/price_handler/providers/okx_provider.py`
- **Commit:** `11fa56f2`

**2. [Rule 2] Empty-fetch → scrubbed `BarsLoadFailed`**
- **Found during:** Task 2 — an empty warmup window cannot warm indicators and would emit an empty `BarsLoaded` breaking the non-empty payload contract.
- **Fix:** Raise `MissingPriceDataError` on an empty fetch (caught by the same scrub path → `BarsLoadFailed(reason="MissingPriceDataError")` → readiness FAILED).
- **Files:** `itrader/price_handler/providers/okx_provider.py`
- **Commit:** `11fa56f2`

**3. [Rule 2] `BarsLoadFailed.time` source**
- **Found during:** Task 2 — the plan snippet omits `time`, but `Event.time` is required with no default and no venue bar exists on failure.
- **Fix:** `datetime.now(UTC)` for the live-only control-plane failure signal (oracle-inert, documented as the allowed control-plane wall-clock, mirroring the poll-timer emit). Success `BarsLoaded.time` stays business-sourced (newest bar).
- **Files:** `itrader/price_handler/providers/okx_provider.py`
- **Commit:** `11fa56f2`

## Issues Encountered
None.

## User Setup Required
None — no external service configuration; all tests are socket-free.

## Verification
- `poetry run pytest tests/unit/price -q` — 89 passed.
- `poetry run mypy itrader/price_handler/feed/live_bar_feed.py itrader/price_handler/providers/okx_provider.py` — clean (`--strict`).
- Milestone gate: `tests/integration/test_okx_inertness.py` + `tests/integration/test_backtest_oracle.py` — 4 passed (oracle byte-exact 134 / `46189.87730727451`; both new methods live-only, never on the backtest path).

## Threat Flags

None — the two new trust-boundary surfaces (OKX REST → engine via `BarsLoaded`/`BarsLoadFailed`; connector loop → engine via `queue.put`) are exactly the threat register's `mitigate` rows (T-07-03-LEAK scrub, T-07-03-RACE threadsafe `connector.spawn`, T-07-03-FLOOD bulk transport + non-emitting absorb), all implemented and unit-asserted.

## Next Phase Readiness
- The two warmup seams are in place: the plan-06 `on_bars_loaded` consumer wires `feed.absorb_warmup(sym, tf, ev.bars)` → `universe.mark_ready(sym)` → `provider.subscribe(sym)` (route-order-guaranteed, D-03b), and `on_bars_load_failed` → `universe.mark_failed(sym)` (D-04). `spawn_warmup`'s composition-root queue wiring (`set_global_queue`) is the one deferred wiring hook.

## Self-Check: PASSED

- FOUND: itrader/price_handler/feed/live_bar_feed.py::absorb_warmup
- FOUND: itrader/price_handler/providers/okx_provider.py::spawn_warmup
- FOUND: tests/unit/price/test_absorb_warmup.py
- FOUND: tests/unit/price/test_spawn_warmup.py
- FOUND commit: 6fae84e0
- FOUND commit: 11fa56f2

---
*Phase: 07-live-dynamic-universe-hardening*
*Completed: 2026-07-06*
