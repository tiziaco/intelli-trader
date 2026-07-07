---
phase: 03-livebarfeed
plan: 03
subsystem: price-handler
tags: [live-feed, warmup, reconnect, backfill, indicator-readiness, decimal, tdd]

# Dependency graph
requires:
  - phase: 03-livebarfeed
    plan: 02
    provides: "LiveBarFeed.update() monotonic guard + _backfill_gap replay path + set_provider seam"
  - phase: 03-livebarfeed
    plan: 01
    provides: "ClosedBar (symbol, timeframe) D-12 routing keys; OkxDataProvider.fetch_ohlcv_backfill REST source"
provides:
  - "LiveBarFeed.warmup(symbol, timeframe, depth) — FEED-03 live-start warmup: K = cache_capacity() + _WARMUP_MARGIN bars replayed one-by-one through update() (no bulk warmup_from fast-path, LX-09)"
  - "LiveBarFeed.backfill_on_resume(symbol, timeframe, latest_completed_ts) — D-08 reconnect: completed-bar boundary gate → REST-backfill [L+tf .. latest] via the shared update() gap path; cold-start/no-boundary no-op; re-sent bar absorbed by the duplicate branch"
affects: [03-04 composition-root wiring calls warmup on live start; Phase 5 RES-01 reconnect/backoff hardening builds on backfill_on_resume]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single replay path: both warmup and reconnect route every REST-fetched ClosedBar one-by-one through update() — no second state-building path exists (parity-gate safe)"
    - "Reconnect recovery is a completed-bar BOUNDARY check (latest > L), not raw outage duration (D-08) — a short outage straddling a bar close still recovers"
    - "Warmup depth = cache_capacity() + fixed additive margin (D-10), NOT a multiplier — the driver is an indicator readiness threshold (RESEARCH §Warmup safety-margin survey)"

key-files:
  created:
    - tests/integration/test_live_bar_feed_warmup.py
  modified:
    - itrader/price_handler/feed/live_bar_feed.py

key-decisions:
  - "backfill_on_resume reuses the 03-02 _backfill_gap helper verbatim — its range signature (first_missing, last_missing) fits [L+tf .. latest] exactly, so no new shared replay method was factored (single replay path preserved with zero duplication)"
  - "_WARMUP_MARGIN = 5 module constant (fixed additive, D-10) — the RESEARCH additive-not-multiplier recommendation"

patterns-established:
  - "warmup() timestamps come from the venue bars only (never datetime.now()) — business-time discipline held on the live warmup path"

requirements-completed: [FEED-03]

# Metrics
duration: 3min
completed: 2026-07-01
---

# Phase 03 Plan 03: LiveBarFeed warmup + reconnect backfill Summary

**`LiveBarFeed` gains its two backfill entry points — FEED-03 live-start `warmup()` (`K = cache_capacity() + margin` bars) and the D-08 boundary-gated `backfill_on_resume()` — both replaying every REST-fetched `ClosedBar` one-by-one through the SAME 03-02 `update()` guard, with no bulk `warmup_from` fast-path (LX-09 parity audit), proven by an offline integration matrix that drives an SMA(100) handle to `is_ready`.**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-07-01T20:08:04Z
- **Completed:** 2026-07-01T20:10:41Z
- **Tasks:** 1 (`type="tdd"`)
- **Files:** 1 created, 1 modified

## Accomplishments
- Added `warmup(symbol, timeframe, depth=None)`: resolves `depth` to `cache_capacity() + _WARMUP_MARGIN` (D-10 — the derived ring depth plus a fixed additive `+5`, RESEARCH additive-not-multiplier), calls `fetch_ohlcv_backfill(..., limit=depth)` ONCE, and replays each returned `ClosedBar` one-by-one through `update()` — no bulk state-building path (LX-09).
- Added `backfill_on_resume(symbol, timeframe, latest_completed_ts)`: the D-08 reconnect case — a completed-bar BOUNDARY check (`latest > L`, not raw outage duration), reusing the 03-02 `_backfill_gap` helper to REST-backfill `[L+tf .. latest]` (inclusive of the boundary bar) and replay through the same `update()` gap path; cold-start (`L is None`) and no-boundary (`latest == L`) are no-ops.
- Proved the Pitfall-1 guard end-to-end: after warming `100 + margin` bars, an `SMA(100)` `IndicatorHandle` reaches `is_ready` — the zero-trades starvation failure is caught by an explicit assertion, honoring D-13's capacity derivation.
- Proved duplicate-safety: a resumed-stream re-send of the boundary bar lands on `update()`'s duplicate branch (D-06) — no double-delivery (T-03-03-DOUBLEDELIVER mitigated).
- New offline integration matrix (6 tests, socket-free local `_StubProvider` + fixed epoch-ms literals) — no aiohttp, no asyncio, no wall-clock.

## Task Commits

The single TDD task followed the RED → GREEN gate:

1. **Task 1 (RED): failing warmup + reconnect matrix** — `14f54915` (test)
2. **Task 1 (GREEN): warmup + backfill_on_resume through update()** — `73127eac` (feat)

## Files
- **Created** `tests/integration/test_live_bar_feed_warmup.py` — FEED-03 one-by-one warmup replay, depth = capacity+margin, SMA(100) readiness (Pitfall-1), and D-08 reconnect boundary / duplicate-dedup / cold-start-noop / no-boundary-noop (6 tests, offline).
- **Modified** `itrader/price_handler/feed/live_bar_feed.py` — `_WARMUP_MARGIN = 5` constant + `warmup()` + `backfill_on_resume()` (a new "Backfill entry points" section); both call `update()` per bar, reconnect reuses `_backfill_gap`.

## Decisions Made
- **Reuse `_backfill_gap` for reconnect (no new shared method):** the plan permitted either reusing the 03-02 helper "if its range signature fits" or factoring a new private method. The helper's `(first_missing, last_missing)` signature fits `[L+tf .. latest]` exactly (`limit = (last-first)/tf + 1`, `since = first`), so `backfill_on_resume` calls it directly — the single replay path is preserved with zero duplication.
- **`_WARMUP_MARGIN = 5` (fixed additive):** the RESEARCH §Warmup safety-margin survey's additive-not-multiplier recommendation (`K = required_warmup + 5`); the margin absorbs REST boundary-bar dedup slack.

## Deviations from Plan
None — plan executed exactly as written. Both entry points route through the shared `update()` path; the reconnect helper reuse was an explicitly-offered plan option.

## Issues Encountered
None. RED confirmed 6 failing (missing `warmup`/`backfill_on_resume` attributes); GREEN turned all green; the 03-02 guard suite (14 tests) and price+connectors suite (69 tests) stayed green; `mypy --strict` clean.

## User Setup Required
None — build and gate run fully offline (synthetic `ClosedBar` sequences + local stub provider); no OKX socket or credentials required.

## Next Phase Readiness
- **03-04 (composition-root wiring):** the live start sequence calls `feed.warmup(symbol, timeframe)` after `set_provider()`; `backfill_on_resume` is the reconnect hook the connector's resume callback drives. D-13 `RawBarConsumer` registration sizes `cache_capacity()` to 100, making warmup depth resolve to 105.
- **Phase 5 (RES-01):** socket-level reconnect/backoff hardening builds on `backfill_on_resume` (D-08 ships the gap-driven recovery here; RES-01 is the hardening home).

## Verification
- `poetry run pytest tests/integration/test_live_bar_feed_warmup.py -q` → 6 passed.
- `poetry run pytest tests/unit/price/test_live_bar_feed.py -q` → 14 passed (guard unchanged).
- `poetry run pytest tests/unit/price tests/unit/connectors -q` → 69 passed (no regressions).
- `poetry run mypy --strict itrader/price_handler/feed/live_bar_feed.py` → clean.
- Greps: `def warmup(` + `def backfill_on_resume(` present, both call `self.update(` / `_backfill_gap` in a per-bar loop; `warmup_from` appears ONLY in a docstring (no method/attr — LX-09 no bulk path); no `datetime.now()` on the new path.

## Self-Check: PASSED
- FOUND: itrader/price_handler/feed/live_bar_feed.py
- FOUND: tests/integration/test_live_bar_feed_warmup.py
- FOUND commit: 14f54915 (Task 1 RED)
- FOUND commit: 73127eac (Task 1 GREEN)

## TDD Gate Compliance
- Task 1: `test(03-03)` (`14f54915`, RED — 6 failing) → `feat(03-03)` (`73127eac`, GREEN — 6 passing). Both gates present in git log, RED verified failing before GREEN.

---
*Phase: 03-livebarfeed*
*Completed: 2026-07-01*
