---
phase: 04-paper-path-milestone-dod
plan: 03
subsystem: trading-system
tags: [paper-path, worker-entrypoint, lifecycle, command-surface, run-01, cov-01]

# Dependency graph
requires:
  - phase: 04-paper-path-milestone-dod (plan 02)
    provides: "run_paper_replay() synchronous offline paper driver + the 'paper' venue arm in LiveTradingSystem"
  - phase: 01-account-abstraction-portfolio-handler-refactor
    provides: "the surviving thin engine command surface (start/stop/get_status/is_running) after TradingInterface deletion"
provides:
  - "scripts/run_live_paper.py — runnable standalone paper worker (RUN-01, D-08): --mode replay (offline, run_paper_replay, CI-safe default) + --mode okx (opt-in manual live smoke via start/stop/get_status, D-11)"
  - "tests/integration/test_live_paper_lifecycle.py — FL-13 lifecycle/command-surface coverage: clean startup, graceful thread-joining stop, status-before-start (COV-01 lifecycle half, D-10)"
affects: [04-04-paper-parity-gate]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Worker composition mirrors scripts/run_backtest.py (construct system -> add_strategy -> add_portfolio -> subscribe -> run -> read-result-state) with the golden SMA_MACD literals verbatim (parity anchor)"
    - "Prose-token discipline: the RUN-01 scope note avoids the literal tokens the acceptance grep gate forbids (worded 'Postgres command/status channel' / 'web-framework wrapper' instead of the forbidden literals)"
    - "Lifecycle tests poll for the asynchronously-set RUNNING status (the processing thread sets it after start() returns) and always stop() in a finally so no daemon thread leaks under filterwarnings=[error]"

key-files:
  created:
    - scripts/run_live_paper.py
    - tests/integration/test_live_paper_lifecycle.py
  modified: []

key-decisions:
  - "RUN-01 delivered per the D-08 revision: Phase 4 ships the runnable worker + start/stop/status lifecycle ONLY; the Postgres command/status channel and any web-framework wrapper are DEFERRED to Phase 5 (verified absent by the acceptance grep gate)"
  - "The worker's replay mode reuses run_paper_replay() (D-02/D-03) — the offline, synchronous, CI-safe default; the okx mode is the opt-in network-gated manual smoke (D-11), present but never invoked by the default main() or on the CI path"
  - "Lifecycle coverage runs exchange='paper' only (offline replay arm) — no OKX network on the CI path (D-11); the strict warning filter stays green because every test joins the daemon thread"

requirements-completed: [RUN-01]

# Metrics
duration: 6min
completed: 2026-07-02
---

# Phase 4 Plan 03: Paper Worker Entrypoint + Lifecycle Coverage Summary

**Delivers the RUN-01 runnable paper worker (`scripts/run_live_paper.py`) — an offline replay run (the CI-safe default, 134 trades / final equity 46189.87730727451 by construction) plus an opt-in real-OKX manual smoke over the start/stop/status lifecycle — and the COV-01 lifecycle half: FL-13 coverage proving clean startup, graceful thread-joining stop, and status reporting, offline and warning-clean.**

## Performance
- **Duration:** ~6 min
- **Completed:** 2026-07-02
- **Tasks:** 2
- **Files created:** 2

## Accomplishments
- Added `scripts/run_live_paper.py` (4-space, mirrors `run_backtest.py`): a standalone `LiveTradingSystem` bootstrap that wires the golden SMA_MACD strategy (`FractionOfCash(Decimal("0.95"))`, `LONG_ONLY`, `allow_increase=False`) + a single `'simulated'`-exchange `paper_pf` portfolio and runs the live-paper engine. `--mode replay` (default) drives `run_paper_replay()` offline and prints a NON-ZERO trade count + final equity (verified: 134 trades / 46189.87730727451 — oracle-matching by construction). `--mode okx` is the opt-in manual live smoke exercising the daemon-thread `start()` -> poll -> `stop(timeout=...)` -> `get_status()` surface (network-gated, D-11, never on the CI path). No command/status channel and no web-framework wiring (Phase 5 scope, D-08).
- Added `tests/integration/test_live_paper_lifecycle.py` (4-space, `integration` marker auto-applied by the folder): three FL-13 cases on `exchange='paper'` — (1) clean startup (`start()` True, `is_running()` True, `get_status()` reports RUNNING with the expected keys `{status, is_running, exchange, queue_size, statistics}`), (2) graceful stop (`stop(timeout=...)` True, thread joins — post-stop `is_running()` False and `get_status()['thread_alive']` False, second `stop()` a safe no-op True), (3) status-before-start (fresh system reports STOPPED / not running without raising). Every test joins the daemon thread so nothing leaks under `filterwarnings=["error"]`.
- Verified all acceptance grep gates: no `LISTEN`/`NOTIFY`/`fastapi`/`FastAPI`/`uvicorn` tokens, no `BTC/USDT` in the worker (uses `BTCUSD`), no `exchange='okx'` in the test, no tab indentation in either file.

## Task Commits
1. **Task 1: scripts/run_live_paper.py — the runnable paper worker (RUN-01, D-08)** — `de839f05` (feat)
2. **Task 2: Lifecycle / command-surface coverage (COV-01 / FL-13, D-10)** — `fbf4a312` (test)

## Files Created/Modified
- `scripts/run_live_paper.py` (created) — standalone paper worker; `main(mode="replay")` + argparse `--mode {replay,okx}`; shared `_compose()`; offline `run_paper_replay` path + opt-in okx smoke.
- `tests/integration/test_live_paper_lifecycle.py` (created) — 3 lifecycle/command-surface tests on the paper venue.

## Decisions Made
- None beyond the plan's locked decisions (D-02/D-03/D-08/D-10/D-11). RUN-01's channel + FastAPI framing followed the D-08 revision (deferred to Phase 5).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worded the RUN-01 scope note to clear the acceptance grep gate**
- **Found during:** Task 1 authoring (against the acceptance gate `grep -n "LISTEN\|NOTIFY\|fastapi\|FastAPI\|uvicorn"` expected to return nothing).
- **Issue:** The plan's `<action>` asks the docstring to cite the RUN-01 scope note "NO Postgres LISTEN/NOTIFY channel, NO FastAPI"; those literal tokens would trip the same acceptance gate that asserts the channel/FastAPI are absent.
- **Fix:** Worded the scope note as "does NOT build the Postgres command/status channel or any web-framework wrapper — those move to Phase 5" (same meaning, no forbidden tokens). Identical to the 04-02 prose-token discipline.
- **Files modified:** scripts/run_live_paper.py
- **Commit:** de839f05

## Requirements Status
- **RUN-01** — the Phase-4 D-08 deliverable (runnable worker + start/stop/status lifecycle) is COMPLETE. The Postgres command/status channel + web-framework wrapper it originally named are DEFERRED to Phase 5 per the D-08 revision (flagged in 04-CONTEXT for a REQUIREMENTS text update).
- **COV-01** — already `[x]` in REQUIREMENTS.md; this plan adds its lifecycle/command-surface half (D-10 item 2). The parity-gate half (D-10 item 1) lands in 04-04.

## Issues Encountered
None.

## User Setup Required
None — the replay path is credential-free and offline. The `--mode okx` smoke needs the existing `OKX_API_*` env triple (Phase 2 `OkxSettings`) and is manual/opt-in only.

## Next Phase Readiness
- The worker's `run_paper_replay()` path already reproduces the oracle trade count (134) and final equity (46189.87730727451) — the 04-04 parity gate diffs live-paper vs a fresh backtest with no re-freeze (parity by construction, D-01).
- The lifecycle surface is covered offline; the real-OKX automated coverage remains Phase 5 (D-11).

## Self-Check: PASSED
- `scripts/run_live_paper.py` — FOUND
- `tests/integration/test_live_paper_lifecycle.py` — FOUND
- Commit `de839f05` — FOUND
- Commit `fbf4a312` — FOUND
- `poetry run python scripts/run_live_paper.py --mode replay` — 134 trades / 46189.87730727451, exit 0 — CONFIRMED
- `poetry run pytest tests/integration/test_live_paper_lifecycle.py` — 3 passed — CONFIRMED

---
*Phase: 04-paper-path-milestone-dod*
*Completed: 2026-07-02*
