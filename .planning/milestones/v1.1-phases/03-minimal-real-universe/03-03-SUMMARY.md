---
phase: 03-minimal-real-universe
plan: 03
subsystem: trading-system-engine
tags: [csv_paths, oracle-dark, integration, no-look-ahead, heterogeneous-spans, D-06, UNIV-02]

# Dependency graph
requires:
  - phase: 03-minimal-real-universe
    plan: 01
    provides: "is_active / active_membership span-model availability primitive (UNIV-01)"
  - phase: 03-minimal-real-universe
    plan: 02
    provides: "span-aware feed (_spans cache + D-04 generate_bar_event warn loop); oracle-dark bar/fill path"
provides:
  - "TradingSystem.__init__ optional csv_paths passthrough to CsvPriceStore (default None → single-golden-ticker behavior, oracle-dark)"
  - "tests/integration/test_universe_spans.py — UNIV-02 engine proof over heterogeneous spans (mid-run listing + differing end dates, no crash, no look-ahead)"
affects: [phase-9-e2e-harness (reuses the csv_paths seam for real ETH/SOL/AAVE differing-span E2E, ROBUST-03)]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Minimal oracle-dark constructor seam: optional csv_paths param forwarded straight to the store; default None reproduces the golden behavior byte-identically (RESEARCH Pitfall 5 / Open Q2 option b)"
    - "Synthetic-fixture engine proof (D-06): UTC-midnight golden-schema CSVs in tmp_path drive a tiny purpose-built strategy through the public constructor — no real-data load, no private-wiring monkeypatch"

key-files:
  created:
    - tests/integration/test_universe_spans.py
  modified:
    - itrader/trading_system/backtest_trading_system.py

key-decisions:
  - "csv_paths added as an optional keyword param after the existing ctor params; all existing defaults unchanged so default construction is byte-identical (oracle-dark)"
  - "Synthetic CSVs anchored at 00:00 UTC (not just whole-day-in-TIMEZONE) so the daily ticks pass the UTC-grid check_timeframe alignment seam and the strategy actually fires end-to-end"
  - "Test registers its synthetic tickers on the simulated exchange's instance _supported_symbols set (same instance-mutation the engine uses for BTCUSD at execution_handler.py:109) — test-only wiring, production preset untouched"
  - "max_window=1 on the proof strategy so the pushed window is non-empty without real warm-up; FixedQuantity(qty=1) sizing for an obvious, hand-pinned expected outcome (D-06)"

patterns-established:
  - "csv_paths injection seam: the clean multi-ticker constructor extension the Phase-9 E2E harness reuses (default None = golden behavior)"
  - "Heterogeneous-span engine proof: anchor + mid-run lister + ends-early ticker over a union window, asserting position entry timestamps bracket each ticker's listed span (no look-ahead, no post-end fill)"

requirements-completed: [UNIV-02]

# Metrics
duration: 12min
completed: 2026-06-09
---

# Phase 3 Plan 03: csv_paths Seam + UNIV-02 Engine Proof Summary

**Landed the minimal oracle-dark `csv_paths` passthrough on `TradingSystem.__init__` (default None → byte-identical golden behavior) and used it to drive a new synthetic-fixture integration test that proves UNIV-02 end-to-end: the engine runs over the union window of a mid-run lister + an ends-early ticker with no crash and no look-ahead (no fill before listing date, no fill after end date), with the BTCUSD oracle verified byte-identical (oracle-dark gate).**

## Performance

- **Duration:** ~12 min
- **Started:** 2026-06-09
- **Completed:** 2026-06-09
- **Tasks:** 2
- **Files modified:** 2 (1 modified, 1 created)

## Accomplishments
- `TradingSystem.__init__` now accepts an optional `csv_paths: dict[str, str | Path] | None = None` keyword (added `from pathlib import Path`), forwarded straight through to `CsvPriceStore(csv_paths=csv_paths, ...)`. Default `None` makes the store fall back to its single-golden-ticker default — byte-identical to today (oracle-dark, RESEARCH Pitfall 5 / Open Q2 option b). All existing params/defaults unchanged; only the store-construction line and the import were touched. TABS preserved.
- `tests/integration/test_universe_spans.py` (NEW, 4 spaces, folder-derived `integration` marker): writes three tiny synthetic daily CSVs into `tmp_path` — EARLYUSD (Jan 1..20 full-window anchor), LATEUSD (Jan 10..20, lists mid-run), ENDSEARLYUSD (Jan 1..5, ends early) — drives a tiny `BuyEachTickerOnce` long-only strategy through the Task-1 `csv_paths` seam, runs the engine over the union window, and asserts UNIV-02: (a) no crash over the union ping grid; (b) LATEUSD has ≥1 position and every entry timestamp ≥ its Jan 10 listing date (no look-ahead); (c) ENDSEARLYUSD positions only on/before its Jan 5 last bar (an absent bar produces no fill); plus a sanity anchor that EARLYUSD trades (the engine actually ran).
- Verified the BTCUSD golden oracle stays byte-identical (`test_backtest_oracle.py` green) — the whole phase remains behavior-preserving.

## Task Commits

Each task was committed atomically:

1. **Task 1: optional oracle-dark csv_paths passthrough on TradingSystem.__init__** — `a1c7664` (feat)
2. **Task 2: UNIV-02 engine proof over heterogeneous spans** — `ebbb818` (test)

## Files Created/Modified
- `itrader/trading_system/backtest_trading_system.py` (TABS) — added `from pathlib import Path`; added the `csv_paths` keyword param after the existing ctor params; forwarded it to `CsvPriceStore(csv_paths=csv_paths, ...)` with a Phase-3 multi-ticker injection-seam comment (Pitfall 5 / Open Q2, reusable by the Phase-9 E2E harness).
- `tests/integration/test_universe_spans.py` (4 spaces, NEW) — UTC-midnight golden-schema `write_kline_csv` + tz-aware `utc_midnight()` stamp helper; the `BuyEachTickerOnce` proof strategy; the heterogeneous-span run + no-crash / no-look-ahead / no-post-end-fill assertions. Registers the synthetic tickers on the simulated exchange instance set (mirrors `execution_handler.py:109`).

## Decisions Made
- Honored locked CONTEXT decisions: D-06 (synthetic controlled fixtures only — the real ETH/SOL/AAVE E2E stays deferred to Phase 9), and the oracle-dark behavior-preserving constraint (default `csv_paths=None` reproduces the golden run byte-identically).
- Two discretionary calls required by the end-to-end run path (both flagged as deviations below): UTC-midnight CSV anchoring (so the daily tick passes the UTC-grid `check_timeframe` alignment seam) and registering the synthetic tickers on the exchange's instance `_supported_symbols` set (so the simulated exchange admits them rather than emitting `REFUSED: Invalid symbol`). Both are test-only and do not touch production behavior.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Synthetic CSVs must be anchored at 00:00 UTC, not whole-day-in-TIMEZONE**
- **Found during:** Task 2 (the first engine run produced zero positions).
- **Issue:** The unit-test `write_kline_csv` helper stamps bars at midnight in `TIMEZONE` (then converts to UTC for the CSV), so the loaded bar index lands at `00:00 TIMEZONE` = `23:00 UTC`. The engine's `check_timeframe`/`_aligned` seam aligns on the **UTC** grid (`seconds_since_UTC_midnight % tf == 0`), so a `23:00 UTC` daily bar is never aligned — `calculate_signals` skipped every strategy and `generate_signal` was never called. (The unit feed tests don't hit this because they call `generate_bar_event` directly, bypassing `check_timeframe`.)
- **Fix:** The integration test writes its own `write_kline_csv` that anchors each bar at `00:00 UTC` (`<day> 00:00:00.000000 UTC`), so the loaded index is `00:00 UTC` and the daily ticks fire. Assertion stamps use a tz-aware `utc_midnight()` helper to match. Whole-day daily stamps preserved (Pitfall 3 — no resample path touched).
- **Files modified:** tests/integration/test_universe_spans.py (test-only)
- **Commit:** ebbb818

**2. [Rule 3 - Blocking] Synthetic tickers must be registered with the simulated exchange**
- **Found during:** Task 2 (orders were emitted but the exchange returned `REFUSED: Invalid symbol: EARLYUSD`).
- **Issue:** `SimulatedExchange.validate_order` rejects any ticker not in `_supported_symbols`. The default preset only lists `*USDT` symbols plus `BTCUSD` (the latter added at `execution_handler.py:109` for the golden run). The synthetic tickers were refused, so no fills, no positions.
- **Fix:** After construction the test unions its synthetic tickers into `system.execution_handler.exchanges["simulated"]._supported_symbols` — the same instance-set mutation the engine itself uses for BTCUSD (test-only; the shared preset and production behavior are untouched). The Phase-9 E2E harness will own a richer symbol setup.
- **Files modified:** tests/integration/test_universe_spans.py (test-only)
- **Commit:** ebbb818

Both deviations are test-wiring corrections needed to drive a real end-to-end run on synthetic tickers; neither touches a result-bearing production path (the BTCUSD oracle remains byte-identical).

## Issues Encountered
None beyond the two test-wiring blockers documented above (both auto-fixed under Rule 3).

## Verification
- `poetry run pytest tests/integration/test_universe_spans.py -x` → 1 passed (UNIV-02 engine proof: no crash, no look-ahead, no post-end fill).
- `poetry run pytest tests/integration/test_backtest_oracle.py tests/integration/test_backtest_smoke.py -x` → 3 passed (oracle BYTE-IDENTICAL — the oracle-dark invariant gate; smoke default-path construction still works).
- `poetry run mypy itrader/trading_system/backtest_trading_system.py` → Success: no issues found.
- `make test` → 734 passed (full unit + integration, incl. the Plan-01/02 suites and the oracle invariant).
- Indentation: `backtest_trading_system.py` TABS preserved (grep `^\t.*csv_paths` confirms); the new test file has zero tabs (4-space).
- The new test does NOT load the real `data/ETH|SOL|AAVE` CSVs (deferred to Phase 9, D-06).

## Known Stubs
None — no placeholder/empty-data stubs introduced. The `csv_paths` param is a real passthrough; the integration test loads real (synthetic, hand-pinned) frames.

## Next Phase Readiness
- UNIV-02 is now engine-proven on synthetic fixtures (D-06): the engine survives a mid-run listing and differing end dates over the union window with no crash and no look-ahead. Combined with Plan-01 (the primitive) and Plan-02 (the span-aware feed), the phase's minimal-real-universe goal is met.
- The `csv_paths` seam is the clean, reusable multi-ticker injection point the Phase-9 E2E harness (ROBUST-03) will reuse for the real ETH/SOL/AAVE differing-span run.
- Behavior-preserving: the BTCUSD golden oracle is byte-identical — no result-bearing path was touched across the phase (oracle-dark).

## Self-Check: PASSED
- FOUND: itrader/trading_system/backtest_trading_system.py (csv_paths param + CsvPriceStore(csv_paths=...) passthrough + from pathlib import Path)
- FOUND: tests/integration/test_universe_spans.py (UNIV-02 heterogeneous-span proof, no-look-ahead assertions)
- FOUND: commit a1c7664 (Task 1 feat)
- FOUND: commit ebbb818 (Task 2 test)

---
*Phase: 03-minimal-real-universe*
*Completed: 2026-06-09*
