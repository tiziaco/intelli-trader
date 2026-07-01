---
phase: 02-okx-connector
plan: 04
subsystem: price_handler/providers
tags: [okx, data-arm, confirm-flag, native-websocket, aiohttp, sandbox-routing, decimal-edge, backfill]

# Dependency graph
requires:
  - phase: 02-okx-connector
    plan: 02
    provides: "OkxConnector session/transport (sandbox bool + shared ccxt client + spawn) the data arm keys off"
provides:
  - "OkxDataProvider — the independent data arm: a native OKX /ws/v5/business candle socket that carries the confirm flag (index 8), gates on confirm==\"1\" (only completed bars flow), and a REST fetch_ohlcv backfill through the shared connector.client — every numeric field across the Decimal edge via to_money(str)"
  - "The confirm-flag escape hatch (CONN-01): the one place OKX's closed-bar flag survives (ccxt's unified watch_ohlcv drops it) — forming bars (confirm==\"0\") are dropped, never handed downstream"
  - "Sandbox host routing for the native socket (CONN-03): wspap.okx.com when connector.sandbox is True, ws.okx.com otherwise — the x-simulated-trading header is REST-only and never routes WS"
  - "A minimal closed-bar seam (set_bar_sink / _hand_closed_bar) the Phase-3 LiveBarFeed registers against — the provider hands raw ClosedBar dicts; BarEvent construction is Phase 3"
affects: [03-livebarfeed, 04-paper-path]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "native aiohttp business-candle socket spawned on the connector loop (connector.spawn); async-with guarantees session close on task cancellation (Pitfall 4)"
    - "confirm gate on business-row index 8 with >= 9-field length validation before indexing (V5 input validation)"
    - "Decimal edge held with to_money(str(row[i])) on every candle + backfill field — no float ever forms (OKX sends numeric strings)"
    - "data arm types the LiveConnector Protocol only (D-04); no import of the concrete session class (grep-guarded)"

key-files:
  created:
    - itrader/price_handler/providers/okx_provider.py
    - tests/unit/connectors/test_okx_data_provider.py
  modified: []

key-decisions:
  - "The Phase-3 feed seam is a minimal set_bar_sink(callable) + _hand_closed_bar(bar) pair (Claude's Discretion, D-03): the provider hands raw ClosedBar TypedDict dicts and Phase 3 co-shapes BarEvent construction + the ring buffer — the offline PriceProvider ABC is NOT subclassed (it is never on the run path)"
  - "OKX interval tokens are looked up verbatim (no case-folding) because the month token 1M would collide with a naive .lower() of the minute token 1m — the map holds both lowercase input keys and already-OKX passthrough keys"
  - "REST backfill pagination advances since past the last bar (last_ts + 1) to drop the duplicated boundary bar ccxt returns when since is inclusive"

requirements-completed: [CONN-01, CONN-03, CONN-05]

# Metrics
duration: 18min
completed: 2026-07-01
---

# Phase 2 Plan 04: OKX Data Arm (native confirm socket + REST backfill) Summary

**`OkxDataProvider` — the independent data arm and the phase's confirm-flag escape hatch: a native OKX `/ws/v5/business` candle socket (the only place the closed-bar `confirm` flag survives ccxt's unified `watch_ohlcv`) that gates on `confirm=="1"` and hands only completed bars to the Phase-3 feed seam, with its host driven off the injected connector's `sandbox` bool (`wspap` demo vs `ws` live — host, not header) and a REST `fetch_ohlcv` backfill through the shared client, every numeric field crossing the Decimal edge via `to_money(str)` — strict-typed (not in the mypy overrides).**

## Performance

- **Duration:** ~18 min
- **Tasks:** 2 (both `type=auto`)
- **Files modified:** 2 (2 created, 0 modified)

## Accomplishments
- Built `itrader/price_handler/providers/okx_provider.py::OkxDataProvider` (4-SPACE, matched to the `providers/base.py` seam + the Phase-3 `feed/` tree) — the genuinely-new no-analog piece of the data arm: an async `_stream_candles(symbol_okx, channel)` coroutine that opens an aiohttp WS to `wss://{host}:8443/ws/v5/business`, sends the OKX subscribe op, and forwards only completed bars downstream.
- Encoded the **confirm gate** (CONN-01, D-05, LX-08): `_process_row` validates the raw business row is `>= 9` fields (V5 input validation) before reading `confirm` at index 8, then drops every forming push (`confirm != "1"`) so only the terminal closed bar reaches the sink — the single most likely source of paper-parity failure if missed.
- Encoded the **sandbox host routing** (CONN-03, D-02 correction): `host = "wspap.okx.com" if self._connector.sandbox else "ws.okx.com"` — the native socket keys its host off the same single bool the connector exposes; the `x-simulated-trading` header is REST-only and never routes WS.
- Implemented the **REST backfill** (CONN-05): `fetch_ohlcv_backfill` paginates `client.fetch_ohlcv` in 1000-row windows through `connector.call`, advancing `since` past the last bar to drop the duplicated boundary bar, and crosses every numeric cell via `to_money(str(...))` — no bulk float cast, no `Decimal(float)`.
- Held the **Decimal edge** end-to-end: a `ClosedBar` TypedDict carries `Decimal` OHLCV + an int `ts` (venue bar-open ms, kept verbatim — never wall-clock); OKX sends numeric strings, so `to_money(str(row[i]))` never lets a float form.
- Shaped the **minimal Phase-3 feed seam** (Claude's Discretion, D-03): `set_bar_sink(callable)` / `_hand_closed_bar(bar)` — the provider hands raw `ClosedBar` dicts; the offline `PriceProvider` ABC is deliberately NOT subclassed (never on the run path).
- Kept the data arm **DI-clean** (D-04): it types the `LiveConnector` Protocol only (imported from the `itrader.connectors` barrel) and never imports the concrete session class — grep-guarded in verify.
- `mypy --strict` clean on `okx_provider.py` (the highest type-risk file in the phase — raw aiohttp WS JSON row indexing; it is NOT in `pyproject.toml [[tool.mypy.overrides]]`).
- Wrote `tests/unit/connectors/test_okx_data_provider.py` (9 tests) driving a teardown-safe fake aiohttp WS over the recorded-shape `okx_business_candles.json` fixture: the confirm gate (only the `confirm=="1"` bar delivered; forming closes never appear), sandbox host routing (`wspap` vs `ws` on `/ws/v5/business`), the subscribe-op shape, the Decimal-edge backfill (OHLCV byte-equal to `to_money(str(raw))`, no float leaks — streamed and backfilled), and malformed-row skip-not-index.

## Task Commits

Each task was committed atomically:

1. **Task 1: OkxDataProvider (native confirm socket + sandbox host + REST backfill)** — `4050a463` (feat)
2. **Task 2: confirm gate / sandbox host / Decimal-edge backfill tests** — `086952cb` (test)

**Plan metadata:** committed separately (docs: complete plan).

## Files Created/Modified
- `itrader/price_handler/providers/okx_provider.py` (created) — `OkxDataProvider` + the `ClosedBar` TypedDict: native business-candle stream, confirm gate, sandbox host routing, REST backfill, minimal feed sink seam. 4-space, strict-typed.
- `tests/unit/connectors/test_okx_data_provider.py` (created) — 9 tests over the recorded-shape fixture with a teardown-safe fake aiohttp WS (no real socket).

## Decisions Made
- **Minimal feed seam (D-03):** `set_bar_sink` + `_hand_closed_bar` handing raw `ClosedBar` dicts. Phase 3 co-shapes `BarEvent` construction and the ring buffer, so the seam is intentionally thin. The offline `PriceProvider` ABC is not reused (it is offline-ingestion-only, never on the run path).
- **Verbatim interval lookup:** the OKX interval map is looked up without case-folding because the month token `1M` collides with a naive `.lower()` of the minute token `1m`; the map holds lowercase input keys (`1d` -> `1D`) and already-OKX passthrough keys.
- **Backfill boundary-bar dedup:** pagination advances `since` to `last_ts + 1` so the bar ccxt repeats at an inclusive `since` boundary is not double-counted.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Reworded docstrings to avoid the grep-guarded literal tokens `astype(float)` and `OkxConnector`**
- **Found during:** Task 1 (first verify run)
- **Issue:** The Task-1 automated verify greps the *entire* module source (docstrings included) and asserts `'astype(float)' not in s` and `'OkxConnector' not in s / 'connectors.okx' not in s`. The module docstrings described the Decimal edge as "never `data.astype(float)`" and the DI discipline as "never the `OkxConnector` concretion" — using the exact literal tokens the guard forbids, so the verify failed despite the code being clean (identical class of issue to 02-02's docstring token hygiene).
- **Fix:** Reworded to "never a bulk float cast of the frame" and "never the concrete session class" — same meaning, no forbidden literals. No behavior change.
- **Files modified:** itrader/price_handler/providers/okx_provider.py
- **Verification:** the Task-1 verify command reads `ok`; `grep -cE "connectors\.okx|OkxConnector"` == 0; `grep -c 'astype(float)'` == 0.
- **Committed in:** 4050a463 (Task 1)

---

**Total deviations:** 1 auto-fixed (blocking, Rule 3 — docstring token hygiene). No architectural changes, no scope creep.
**Impact on plan:** Mechanical wording change required to clear the plan's own automated verify. Every must-have and acceptance criterion is honored.

## Milestone Gate
- **Oracle byte-exact:** `tests/integration/test_backtest_oracle.py` passes within the full suite (1492 passed / 1 skipped) — the backtest hot path imports no async/connector/data-arm code (the provider is additive, off the run path).
- **No W1/W2 regression:** no change to any backtest-path module; `okx_provider.py` is imported only by the (future) Phase-3 live feed.
- **Held constraints:** `mypy --strict` clean on the new file; full suite green under `filterwarnings=["error"]` (no ResourceWarning/RuntimeWarning escalation — the fake WS opens no real socket and the finite stream leaves no un-cancelled task, Pitfall 4); Decimal money end-to-end (`to_money(str)` at the venue edge, no float); business `ts` kept verbatim (never wall-clock); 4-space indentation matched to the `providers/`/`feed/` seam.

## Known Stubs
None functional. The Phase-3 feed seam (`set_bar_sink` / `_hand_closed_bar`) is intentionally minimal — the provider hands raw `ClosedBar` dicts and `BarEvent` construction + the ring buffer are Phase 3's concern (D-03, co-shaped). This is a documented seam boundary, not an incomplete stub: closed-bar streaming and REST backfill are both fully implemented and tested.

## Verification Evidence
- `poetry run pytest tests/unit/connectors/test_okx_data_provider.py -x` -> 9 passed.
- `poetry run pytest tests/unit/connectors/test_okx_data_provider.py -k backfill -x` -> 2 passed (CONN-01 backfill / CONN-05).
- `poetry run pytest tests/unit/connectors/test_okx_data_provider.py -k sandbox -x` -> 2 passed (CONN-03).
- `poetry run pytest tests/unit/connectors -k decimal -x` -> 3 passed (CONN-05).
- `poetry run pytest tests/unit/connectors` -> 14 passed (connector + data-provider).
- `poetry run pytest tests` -> 1492 passed, 1 skipped (no warning escalation).
- `poetry run mypy --strict itrader/price_handler/providers/okx_provider.py` -> Success: no issues found.
- `grep -cP '^\t' okx_provider.py` == 0 (4-space); `grep -cE "connectors\.okx|OkxConnector"` == 0 (D-04).

## Next Phase Readiness
- Phase 3 (`LiveBarFeed`) registers its closed-bar consumer via `provider.set_bar_sink(...)`, launches the native stream via `provider.start_stream()` (spawned on the connector loop), and warms up through `provider.fetch_ohlcv_backfill(...)` replayed one-by-one via the feed's `update(bar)` (LX-09). The confirm gate + sandbox routing + Decimal edge are locked and tested — Phase 3 builds `BarEvent` construction on top of a proven data seam.
- Phase 4 DoD (paper-parity) is reachable on the connector **data arm only** (this plan) + Phase 1 + Phase 3 — the order arm is not on the DoD path.

## Self-Check: PASSED

- FOUND: itrader/price_handler/providers/okx_provider.py
- FOUND: tests/unit/connectors/test_okx_data_provider.py
- FOUND commit: 4050a463 (feat, Task 1)
- FOUND commit: 086952cb (test, Task 2)

---
*Phase: 02-okx-connector*
*Completed: 2026-07-01*
