---
phase: 03-livebarfeed
plan: 04
subsystem: infra
tags: [live-feed, composition-root, okx, feed-05, d-13, inertness-gate, event-routing]

# Dependency graph
requires:
  - phase: 03-livebarfeed (03-02)
    provides: LiveBarFeed core — ring read-model, FEED-04 monotonic guard, direct BarEvent emission, set_provider() seam, dormant no-op generate_bar_event
  - phase: 03-livebarfeed (03-03)
    provides: warmup() + backfill_on_resume() entry points (REST replay through update())
  - phase: 02-okxconnector (02-05)
    provides: OkxDataProvider (set_bar_sink, fetch_ohlcv_backfill, start_stream) + lazy OKX composition-root arm
provides:
  - LiveBarFeed wired into LiveTradingSystem as the live driver (replaces the BacktestBarFeed placeholder), lazy-imported for backtest-path inertness
  - D-13 raw-bar consumer registration sizing cache_capacity() to max(strategy.warmup) (=100 for SMA_MACD)
  - Real OKX provider injected into the feed via set_provider(); provider sink wired to feed.update
  - warmup-before-start_stream single-thread hand-off (FEED-05 driver replacement)
  - FEED-05 route-order integration test + extended inertness probe forbidding live_bar_feed on the backtest path
affects: [04-paperpath, 06-dynamicuniverse]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Lazy import inside __init__ mirrors the OKX/SQL lazy pattern to keep the live feed off the backtest import graph"
    - "D-13 capacity derivation: a tiny frozen RawBarConsumer registered at wiring time sizes the ring + warmup via cache_capacity()"
    - "Provider->feed injection uses the public set_provider setter (writes private _provider) — never a bare public-attribute assignment"

key-files:
  created:
    - tests/integration/test_live_bar_feed_route_order.py
  modified:
    - itrader/trading_system/live_trading_system.py
    - tests/integration/test_live_system_okx_wiring.py
    - tests/integration/test_okx_inertness.py

key-decisions:
  - "LiveBarFeed constructed provider-less and UNCONDITIONALLY (constructible for every venue); the OKX provider is injected only in the okx arm"
  - "warmup + start_stream are OKX-venue-gated in start() so a None provider is never dereferenced on a non-OKX venue"
  - "cache_capacity() capacity derivation happens in _initialize_live_session (before bind), so the check is offline-testable without a network connect"

patterns-established:
  - "Composition-root live-feed swap-in with venue-gated provider injection + sink wiring + D-13 capacity registration"
  - "Order-recording SimpleNamespace spies drive an EventHandler _dispatch to assert BAR-route callable order offline"

requirements-completed: [FEED-05]

# Metrics
duration: 14min
completed: 2026-07-01
---

# Phase 03 Plan 04: LiveBarFeed Composition-Root Wiring Summary

**LiveBarFeed wired into LiveTradingSystem as the FEED-05 live driver — lazy-imported (backtest-path inert), OKX provider injected via set_provider, D-13 consumer sizing cache_capacity() to 100, warmup-before-start_stream hand-off, with the recurring milestone gate (oracle byte-exact + inertness) green.**

## Performance

- **Duration:** ~14 min
- **Started:** 2026-07-01
- **Completed:** 2026-07-01
- **Tasks:** 2
- **Files modified:** 4 (1 created, 3 modified)

## Accomplishments

- Swapped the `BacktestBarFeed` placeholder for a LAZY-imported `LiveBarFeed` at the `LiveTradingSystem` composition root — constructed provider-less and unconditionally so it is constructible for every venue while never touching the backtest import graph.
- Injected the real OKX provider into the LIVE feed via the exact public setter `self.feed.set_provider(self._okx_data_provider)` (writes the private `_provider` that `warmup()`/gap-backfill read) and wired the provider's closed-bar sink to `feed.update`.
- Registered the D-13 `_LiveWarmupConsumer(required_history_depth=max(strategy.warmup))` in `_initialize_live_session` so `cache_capacity()` derives to 100 for SMA_MACD (not the newest-bar floor of 1) — the Pitfall-1 guard against a never-warming feed producing zero trades.
- Gated `feed.warmup(...)` before `start_stream()` in `start()` to the OKX arm so every `update()` stays single-threaded until the socket goes live (FEED-05 driver replacement, RESEARCH thread hand-off).
- Added a FEED-05 route-order integration test (direct `BarEvent` emission preserves the declared BAR-route callable order) and extended the inertness probe's `_FORBIDDEN` to forbid `live_bar_feed` on the backtest path — the oracle stays byte-exact (134 / 46189.87730727451).

## Task Commits

Each task was committed atomically:

1. **Task 1: Swap in LiveBarFeed (lazy) + D-13 consumer + provider injection + sink/bind/warmup wiring** - `ff5c8547` (feat)
2. **Task 2: FEED-05 route-order test + extend inertness probe** - `400857d2` (test)

## Files Created/Modified

- `itrader/trading_system/live_trading_system.py` - Lazy LiveBarFeed swap-in; `_LiveWarmupConsumer` frozen dataclass; `set_provider(okx)` + `set_bar_sink(feed.update)` in the okx arm; D-13 `register_raw_bar_consumer` before `bind`; OKX-gated `warmup` before `start_stream` in `start()`.
- `tests/integration/test_live_system_okx_wiring.py` - Added construction tests: provider injected into `feed._provider` before warmup, sink wired to `feed.update`, and `cache_capacity()` derives to the strategy warmup after session init.
- `tests/integration/test_live_bar_feed_route_order.py` - New. Drives `LiveBarFeed.update()` against a real queue and dispatches the emitted `BarEvent` through `EventHandler._routes`, asserting the BAR-route order (mark-to-market -> matching -> signals) and exactly one emitted event.
- `tests/integration/test_okx_inertness.py` - Extended `_FORBIDDEN` with `itrader.price_handler.feed.live_bar_feed`.

## Decisions Made

- **LiveBarFeed built provider-less and unconditionally.** Construction must not require an OKX venue, so the feed is created for every venue and the provider is injected only inside the okx arm via `set_provider`.
- **warmup/start_stream OKX-venue-gated in `start()`.** A non-OKX venue has no provider; gating on `self.exchange == 'okx' and self._okx_data_provider is not None` mirrors the existing CR-02 guard and prevents a None-provider dereference.
- **D-13 registration lives in `_initialize_live_session`** (before `bind`), which performs no network I/O — so the capacity derivation is offline-testable by calling `_initialize_live_session()` directly, without an OKX connect.
- `self.store` (CsvPriceStore) construction was retained even though the live feed no longer consumes it, to minimize the diff and avoid touching unrelated seams.

## Deviations from Plan

None - plan executed exactly as written. All acceptance-criteria greps match, and the plan's verification suite plus the broader `tests/unit/price` + `tests/integration` suites are green with no regressions.

## Issues Encountered

None. The plan note flagged `live_trading_system.py` as a tab file, but the actual file uses 4-space indentation (verified via `od -c`); edits matched the file's real convention.

## Threat Flags

None - no new security surface beyond the plan's threat register (all dispositions `mitigate`, all satisfied: T-03-04-INERT via lazy import + extended probe, T-03-04-STARVE via D-13 consumer, T-03-04-WIRE via set_provider + construction test, T-03-04-RACE via warmup-before-start_stream, T-03-04-DORMANT via the feed's own no-op generate_bar_event).

## Next Phase Readiness

- FEED-05 complete; the live feed is the driver, replacing TimeGenerator with direct BarEvent emission while preserving downstream route ordering.
- Phase 4 (Paper Path / DoD) can reach the paper-parity gate on the data arm: the composition root now wires the feed, provider injection, D-13 capacity, and warmup hand-off.
- The recurring milestone gate is green (oracle byte-exact; live_bar_feed inert on the backtest path).

## Self-Check: PASSED

All created/modified files exist on disk; both task commits (`ff5c8547`, `400857d2`) are present in git history.

---
*Phase: 03-livebarfeed*
*Completed: 2026-07-01*
