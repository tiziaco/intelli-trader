---
phase: 07-safety-reconciliation-stream-recovery
plan: 04
subsystem: infra
tags: [live-trading, stream-recovery, threading, safety, single-writer, okx]

requires:
  - phase: 07-03
    provides: SafetyController (resume_submission / is_submission_paused) injected into on_reconnect
  - phase: 07-01
    provides: StreamStateEvent / ConnectorFatalEvent CONTROL events (route lands in Plan 06)
provides:
  - StreamRecoveryHandler (engine-thread reconnect-resume I/O — catch-up + snapshot + health-gate -> resume)
  - CF-2 single-writer ring assertion in LiveBarFeed (_loop_backfill_owner + _assert_ring_writer_single_thread)
affects: [07-06, live-trading, stream-recovery, safety]

tech-stack:
  added: []
  patterns:
    - "Engine-thread resume I/O extracted from the pure state machine into a dedicated collaborator (SAFE-04)"
    - "Shared thread-ident tripwire (GIL-atomic) enforcing a single-writer ring contract on loop-native backfill (CF-2/T-07-03)"

key-files:
  created:
    - itrader/trading_system/safety/stream_recovery_handler.py
    - tests/unit/trading_system/test_stream_recovery_handler.py
  modified:
    - itrader/price_handler/feed/live_bar_feed.py
    - tests/integration/test_resume_missed_fill_catchup.py
    - tests/integration/test_resume_gated_on_all_streams.py

key-decisions:
  - "D-12 preserved verbatim: snapshot/catch-up failure stays paused, retries on next stream-up — no failure-counter/halt-escalation"
  - "CF-2 enforced with a SHARED _loop_backfill_owner thread-ident (not the per-thread _replaying_backfill guard) so a ring write from ANY non-owner thread during a loop-native backfill is detectable"
  - "The CF-2 assertion is a fail-loud tripwire (typed StateError), not a lock — the feed is single-writer by contract; it fails loud on violation rather than serializing"

patterns-established:
  - "Reconnect-resume orchestration reached by the STREAM_STATE(up) route, not a per-tick pending-resume flag poll"
  - "Ring-writer guard inert (single is-None check) on warmup / synchronous-backfill / paper-parity paths"

requirements-completed: [SAFE-04]

coverage:
  - id: D1
    description: "StreamRecoveryHandler.on_reconnect does engine-thread catch-up + snapshot + all-streams-healthy gate -> safety.resume_submission (byte-moved from the facade donors)"
    requirement: "SAFE-04"
    verification:
      - kind: unit
        ref: "tests/unit/trading_system/test_stream_recovery_handler.py#test_resume_happy_path_catchup_then_snapshot_then_resume"
        status: pass
      - kind: integration
        ref: "tests/integration/test_resume_missed_fill_catchup.py#test_on_reconnect_does_no_engine_thread_ring_write_cf2"
        status: pass
    human_judgment: false
  - id: D2
    description: "D-12 preserved: snapshot/catch-up Exception during resume stays paused and does NOT resume (no escalation)"
    requirement: "SAFE-04"
    verification:
      - kind: unit
        ref: "tests/unit/trading_system/test_stream_recovery_handler.py#test_resume_stays_paused_on_snapshot_exception_d12"
        status: pass
      - kind: unit
        ref: "tests/unit/trading_system/test_stream_recovery_handler.py#test_resume_stays_paused_on_catchup_exception_d12"
        status: pass
    human_judgment: false
  - id: D3
    description: "CF-2: an engine-thread ring write during an in-flight loop-native backfill fails loud (single-writer contract); the guard is inert on non-backfill paths"
    requirement: "SAFE-04"
    verification:
      - kind: integration
        ref: "tests/integration/test_resume_gated_on_all_streams.py#test_cf2_engine_thread_ring_write_during_loop_backfill_fails_loud"
        status: pass
      - kind: integration
        ref: "tests/integration/test_resume_gated_on_all_streams.py#test_cf2_guard_inert_when_no_backfill_active"
        status: pass
    human_judgment: false
  - id: D4
    description: "Backtest oracle stays byte-exact and OKX import inertness stays green (stream_recovery_handler.py not barrel-exported)"
    verification:
      - kind: integration
        ref: "tests/integration/test_backtest_oracle.py"
        status: pass
      - kind: integration
        ref: "tests/integration/test_okx_inertness.py"
        status: pass
    human_judgment: false

duration: 6min
completed: 2026-07-14
status: complete
---

# Phase 7 Plan 04: StreamRecoveryHandler + CF-2 Single-Writer Ring Assertion Summary

**Engine-thread reconnect-resume I/O (missed-fill catch-up + REST snapshot + all-streams-healthy gate -> resume) byte-moved into `StreamRecoveryHandler`, plus a fail-loud single-writer ring assertion in `LiveBarFeed` that trips if any engine-thread path reaches the ring writer during a loop-native backfill (CF-2).**

## Performance

- **Duration:** 6 min
- **Started:** 2026-07-14T14:31:42Z
- **Completed:** 2026-07-14T14:38:15Z
- **Tasks:** 2
- **Files modified:** 5 (2 created, 3 modified)

## Accomplishments
- `StreamRecoveryHandler.on_reconnect` extracted from `LiveTradingSystem._maybe_resume_after_reconnect` (607-666) + `_all_venue_streams_healthy` (668-684): catch-up missed fills -> account snapshot -> per-arm health gate -> `safety.resume_submission`, reached by the `STREAM_STATE(up)` route (the per-tick pending-resume flag scaffolding is dropped in the move).
- D-12 preserved verbatim: a snapshot/catch-up `Exception` stays paused and retries on the next stream-up signal — no new failure-counter or halt-escalation.
- CF-2 single-writer contract enforced: a shared `_loop_backfill_owner` thread-ident published on the connector-loop replay thread + a `_assert_ring_writer_single_thread` guard in `_deliver` that raises a typed `StateError` if a non-owner (engine) thread reaches the ring append during an in-flight loop-native backfill.
- `on_reconnect` contains no ring-backfill call (loop-native only) — proven at the source level and by an integration test driving `on_reconnect` on a stand-in engine thread with a spied ring writer.

## Task Commits

1. **Task 1: Author StreamRecoveryHandler.on_reconnect (byte-move; engine-thread I/O)** - `39bf3c6a` (feat)
2. **Task 2: CF-2 loop-native backfill assertion in LiveBarFeed** - `eeb3b0d3` (feat)

**Plan metadata:** docs commit (this SUMMARY + STATE + ROADMAP + REQUIREMENTS)

## Files Created/Modified
- `itrader/trading_system/safety/stream_recovery_handler.py` - NEW. `StreamRecoveryHandler` with injected `safety` + OKX exchange/account/provider arms; `on_reconnect` (catch-up + snapshot + gate -> resume, D-12 stay-paused on failure) and `_all_venue_streams_healthy`. Not barrel-exported (inertness-safe).
- `tests/unit/trading_system/test_stream_recovery_handler.py` - NEW. 8 unit tests with fakes: happy-path ordering, arm-down gate (both arms), D-12 stay-paused on snapshot/catch-up Exception, None-arm guard, not-paused no-op, CF-2 source assertion.
- `itrader/price_handler/feed/live_bar_feed.py` - Added `_loop_backfill_owner` shared ident + `_assert_ring_writer_single_thread` guard called in `_deliver`; owner set/cleared around the loop-native replay in `_spawn_loop_native_gap_backfill`.
- `tests/integration/test_resume_missed_fill_catchup.py` - Extended: `on_reconnect` on a stand-in engine thread does the full resume and writes NO ring (CF-2).
- `tests/integration/test_resume_gated_on_all_streams.py` - Extended: non-owner ring write during backfill fails loud; owning-thread + no-backfill paths pass.

## Decisions Made
- Used a SHARED instance `_loop_backfill_owner` rather than the existing per-thread `_replaying_backfill` guard: the per-thread guard (threading.local) can only answer "is THIS thread replaying," which cannot detect a concurrent write from a DIFFERENT thread. A shared ident makes any non-owner ring write during a backfill observable and fail-loud. This is a GIL-atomic tripwire (a fail-loud assertion, not a correctness lock) — the feed is single-writer by contract.
- Reworded the handler module docstring to avoid the literal tokens `backfill_on_resume` / `_pending_stream_resume` so the plan's exact `grep -c ... == 0` acceptance checks hold on the whole file (the meaning is preserved in prose).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `StreamRecoveryHandler` is authored and unit/integration-tested; Plan 06 wires the `STREAM_STATE(up)` route -> `StreamRecoveryHandler.on_reconnect` and removes the donor drains from `LiveTradingSystem`.
- CF-2 assertion is in place and covered; the single-writer ring contract is now provable on resume.
- Per-phase gates green: backtest oracle (byte-exact golden identity) and OKX import inertness; `mypy --strict` clean on both edited/new source files.

## Self-Check: PASSED
- `itrader/trading_system/safety/stream_recovery_handler.py` — FOUND
- `tests/unit/trading_system/test_stream_recovery_handler.py` — FOUND
- Task commits `39bf3c6a`, `eeb3b0d3` — present in `git log`
- Acceptance greps: `backfill_on_resume` 0, `_pending_stream_resume` 0 in handler; CF-2 guard token present in `live_bar_feed.py`
- Suites: 8 unit + 10 resume integration + oracle (3) + inertness (4) all pass; `mypy --strict` clean

---
*Phase: 07-safety-reconciliation-stream-recovery*
*Completed: 2026-07-14*
