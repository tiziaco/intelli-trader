---
phase: 03-livebarfeed
plan: 01
subsystem: testing
tags: [okx, closedbar, typeddict, live-feed, pytest-fixtures, decimal]

# Dependency graph
requires:
  - phase: 02-okxconnector
    provides: OkxDataProvider + ClosedBar TypedDict (native confirm-gated stream + REST backfill)
provides:
  - "ClosedBar TypedDict extended with symbol:str + timeframe:str (D-12 routing keys)"
  - "Both provider paths (live _process_row + REST fetch_ohlcv_backfill) populate the routing keys from trusted config"
  - "tests/unit/price/conftest.py shared offline fixtures: closed_bar builder, closed_bar_sequence, _StubProvider"
affects: [03-02 LiveBarFeed ring keying, 03-03 warmup, 03-04 composition-root wiring]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Self-routing ClosedBar: the payload carries its own (symbol, timeframe) so LiveBarFeed.update() self-routes to a per-key ring (D-01/D-12)"
    - "Trusted-config stamping: routing keys sourced from provider config / method params, never the untrusted venue row (T-03-01-TAMPER)"
    - "Socket-free offline test fixtures mirroring the Phase-2 fake discipline (no aiohttp/asyncio)"

key-files:
  created:
    - tests/unit/price/conftest.py
    - tests/unit/price/test_fixtures.py
  modified:
    - itrader/price_handler/providers/okx_provider.py
    - tests/unit/connectors/test_okx_data_provider.py

key-decisions:
  - "D-12: ClosedBar carries its own (symbol, timeframe); live path stamps from self._symbol/self._timeframe, backfill path stamps from the method's own params so an ad-hoc backfill routes correctly"
  - "Routing keys never read from the venue row — a spoofed row cannot forge a ring key (T-03-01-TAMPER)"

patterns-established:
  - "closed_bar factory: vary only ts_ms; Decimal OHLCV via Decimal(str(...)); fixed epoch-ms literals (byte-reproducible)"
  - "closed_bar_sequence: advance ts by exactly one timeframe so warmup replay fires no spurious gap"
  - "_StubProvider: programmable fetch_ohlcv_backfill + captured-call log for gap/backfill assertions"

requirements-completed: [FEED-01, FEED-03]

# Metrics
duration: 3min
completed: 2026-07-01
---

# Phase 03 Plan 01: ClosedBar D-12 Co-Shape + Offline Feed Fixtures Summary

**ClosedBar TypedDict extended with self-routing (symbol, timeframe) keys on both OKX provider paths, plus shared socket-free LiveBarFeed test fixtures (synthetic ClosedBar builder + stub backfill provider)**

## Performance

- **Duration:** ~3 min
- **Started:** 2026-07-01T19:47:46Z
- **Completed:** 2026-07-01T19:50:24Z
- **Tasks:** 2
- **Files modified:** 4 (2 created, 2 modified)

## Accomplishments
- Resolved the D-12 code-vs-decision gap that gated the whole feed: `ClosedBar` now carries `symbol`/`timeframe`, so `LiveBarFeed.update()` can self-route to a per-`(symbol, timeframe)` ring (FEED-01) and warm up (FEED-03).
- Populated the keys on BOTH provider paths — live stream (`_process_row`, from `self._symbol`/`self._timeframe`) and REST backfill (`fetch_ohlcv_backfill`, from the method params) — with the Decimal edge untouched.
- Stood up `tests/unit/price/conftest.py`: a `closed_bar` factory, a `closed_bar_sequence` one-timeframe-advance helper, and a socket-free programmable `_StubProvider` — the offline infrastructure the 03-02 LiveBarFeed matrix consumes.
- Kept `mypy --strict` clean on the strict-typed provider module and preserved the package-less `tests/unit/price/` directory.

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend ClosedBar with (symbol, timeframe) and populate both provider paths (D-12)** - `e5f6ecfe` (feat)
2. **Task 2: Shared offline LiveBarFeed test fixtures (_StubProvider + synthetic ClosedBar builder)** - `8febfdb6` (test)

## Files Created/Modified
- `itrader/price_handler/providers/okx_provider.py` - `ClosedBar` TypedDict + both provider paths carry the D-12 routing keys
- `tests/unit/connectors/test_okx_data_provider.py` - live + backfill assertions on the new symbol/timeframe keys
- `tests/unit/price/conftest.py` - shared offline fixtures (closed_bar, closed_bar_sequence, stub_provider)
- `tests/unit/price/test_fixtures.py` - smoke test greening the fixtures

## Decisions Made
- Followed the plan/03-PATTERNS D-12 co-shape exactly: live path stamps from provider config, backfill path stamps from method params (ad-hoc symbol correctness).
- Routing keys sourced only from trusted config — never the untrusted venue row (threat register T-03-01-TAMPER mitigation held by construction).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The feed's routing seam is unblocked: 03-02 can key its ring off `ClosedBar["symbol"]`/`["timeframe"]` and warm up via `stub_provider.fetch_ohlcv_backfill`.
- Offline fixtures are in place so the LiveBarFeed unit matrix runs socket-free under `filterwarnings=["error"]`.

## Verification
- `poetry run pytest tests/unit/connectors/test_okx_data_provider.py tests/unit/price -q` → 50 passed.
- `poetry run mypy --strict itrader/price_handler/providers/okx_provider.py` → clean.
- No `__init__.py` under `tests/unit/price/`.

## Self-Check: PASSED
- FOUND: itrader/price_handler/providers/okx_provider.py (modified)
- FOUND: tests/unit/price/conftest.py
- FOUND: tests/unit/price/test_fixtures.py
- FOUND: tests/unit/connectors/test_okx_data_provider.py (modified)
- FOUND commit: e5f6ecfe
- FOUND commit: 8febfdb6

---
*Phase: 03-livebarfeed*
*Completed: 2026-07-01*
