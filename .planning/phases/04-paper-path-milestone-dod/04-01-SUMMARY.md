---
phase: 04-paper-path-milestone-dod
plan: 01
subsystem: price-handler
tags: [replay-provider, paper-path, closed-bar, decimal-edge, csv-store, live-bar-feed]

# Dependency graph
requires:
  - phase: 02-okx-connector
    provides: "OkxDataProvider.ClosedBar TypedDict + set_bar_sink/fetch_ohlcv_backfill seam (the analog mirrored)"
  - phase: 03-livebarfeed
    provides: "LiveBarFeed.update(ClosedBar) + set_provider/set_bar_sink live feed seam (the consumer)"
provides:
  - "ReplayDataProvider: offline synchronous stand-in for OkxDataProvider replaying the golden CsvPriceStore as Decimal-edge ClosedBar dicts"
  - "The set_bar_sink/replay_bar push seam + fetch_ohlcv_backfill warmup seam the 04-02 wiring and 04-04 parity gate build on"
  - "COV-01 synthetic replay fixture (the 'mock connector' for the paper path)"
affects: [04-02-paper-wiring, 04-03-worker-entrypoint, 04-04-paper-parity-gate]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Replay-provider seam parity: a drop-in for OkxDataProvider on set_bar_sink/fetch_ohlcv_backfill, diverging only in the synchronous in-thread replay loop (D-03) that replaces the async _stream_candles"
    - "Business-time epoch-ms stamping off the tz-aware CsvPriceStore index (int(index.value // 1_000_000)) — bar-open grid parity (D-09)"

key-files:
  created:
    - itrader/price_handler/providers/replay_provider.py
    - tests/unit/price/test_replay_provider.py
  modified: []

key-decisions:
  - "ClosedBar imported from okx_provider (not redefined) — single TypedDict home; symbol/timeframe stamped from trusted provider config, never the CSV row (D-12)"
  - "Golden rows sourced via CsvPriceStore (same store the backtest reads) so iter order/values are byte-identical — the parity anchor (D-01/D-02)"
  - "Decimal edge held via to_money(str(cell)) on every OHLCV cell; ts = int(index.value // 1_000_000) epoch-ms verbatim, never wall-clock (D-09)"

patterns-established:
  - "Pattern 1: synchronous replay_bar push (public analog of OkxDataProvider._hand_closed_bar) — drop-and-log when no sink registered, no raise"
  - "Pattern 2: fetch_ohlcv_backfill returns iter_closed_bars() filtered by since and truncated to limit — a working _provider seam for LiveBarFeed warmup"

requirements-completed: [PAPER-03, COV-01]

# Metrics
duration: 6min
completed: 2026-07-02
---

# Phase 4 Plan 01: ReplayDataProvider Summary

**Offline synchronous ReplayDataProvider that replays the golden BTCUSD CsvPriceStore as Decimal-edge, BTCUSD/1d-stamped, epoch-ms-bar-open ClosedBar dicts through the Phase-3 set_bar_sink/replay_bar feed seam — the paper-parity gate's replay entry point.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-07-02T12:28:00Z
- **Completed:** 2026-07-02T12:34:00Z
- **Tasks:** 2
- **Files modified:** 2 (2 created)

## Accomplishments
- `ReplayDataProvider` — a drop-in for `OkxDataProvider` on the two seam methods the live wiring calls (`set_bar_sink`, `fetch_ohlcv_backfill`), plus a synchronous `replay_bar`/`iter_closed_bars` pair that replaces the async `_stream_candles` loop (D-03).
- Every golden row crosses the Decimal edge via `to_money(str(cell))`; `ts` is the CSV bar-open epoch-ms kept verbatim off the tz-aware index (D-09); `symbol`/`timeframe` stamped from trusted config (D-12).
- 5 offline unit tests proving symbol-form stamping (BTCUSD/1d), the Decimal edge, the monotonic epoch-ms grid, in-order sink delivery, and the no-sink warn-and-drop path — the COV-01 replay fixture.
- mypy --strict clean on the new provider; full `tests/unit/price` (61 tests) green — no collection/regression.

## Task Commits

Each task was committed atomically:

1. **Task 1: ReplayDataProvider over the golden CsvPriceStore** - `1d02b6ab` (feat)
2. **Task 2: Offline unit coverage for the replay provider (COV-01 fixture)** - `5c329319` (test)

_Note: this was a TDD-flagged plan structured as implementation (Task 1) then test coverage (Task 2); each committed once._

## Files Created/Modified
- `itrader/price_handler/providers/replay_provider.py` - The replay provider: `set_bar_sink`/`replay_bar`/`iter_closed_bars`/`fetch_ohlcv_backfill` over the golden `CsvPriceStore`, import-light (no async/connector surface).
- `tests/unit/price/test_replay_provider.py` - 5 offline unit tests (symbol stamping, Decimal edge, monotonic ts, sink delivery, no-sink warn-and-drop).

## Decisions Made
- None beyond the plan's locked decisions (D-02/D-03/D-09/D-12). `ClosedBar` imported (not redefined), golden rows via `CsvPriceStore`, Decimal edge and epoch-ms stamping applied verbatim per the pattern map.

## Deviations from Plan

None - plan executed exactly as written.

The only in-scope adjustment: three module/method **docstring** phrases were reworded to avoid the literal tokens `Decimal(float)`, `aiohttp`, and `ccxt` so the plan's grep acceptance gates (which forbid those tokens anywhere in the file, including prose) pass cleanly. No code behavior change — the Decimal edge and import-light constraints were already satisfied in code; this only removed false-positive prose matches.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The replay provider is ready to be wired into `LiveTradingSystem` (04-02): `feed.set_provider(replay_provider)` + `replay_provider.set_bar_sink(self.feed.update)` (mirror the OKX arm, synchronous/offline).
- `iter_closed_bars()` / `replay_bar()` give the 04-02 driver the synchronous per-bar push to interleave with `process_events`; `fetch_ohlcv_backfill` gives `LiveBarFeed.warmup` a working seam.
- The parity anchor holds by construction: rows come from the same `CsvPriceStore` the backtest reads, so the 04-04 gate can diff live-paper vs a fresh backtest with no re-freeze (D-01).

## Self-Check: PASSED
- `itrader/price_handler/providers/replay_provider.py` — FOUND
- `tests/unit/price/test_replay_provider.py` — FOUND
- Commit `1d02b6ab` — FOUND
- Commit `5c329319` — FOUND

---
*Phase: 04-paper-path-milestone-dod*
*Completed: 2026-07-02*
