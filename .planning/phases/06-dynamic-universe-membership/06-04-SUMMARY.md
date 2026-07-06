---
phase: 06-dynamic-universe-membership
plan: 04
subsystem: api
tags: [universe, admission, remove-policy, orphan-and-track, force-close, simulated-exchange, paper-replay]

# Dependency graph
requires:
  - phase: 06-01
    provides: "Universe.mark_leaving/leaving_symbols/clear_leaving + UniverseUpdateEvent"
  - phase: 06-03
    provides: "UniverseHandler poll + on_universe_update ADD branch + remove-branch placeholder"
provides:
  - "OrderTriggerSource.ADMISSION_LEAVING reason"
  - "AdmissionManager._enforce_leaving_symbol_admission — FIRST admission gate (blocks new entries for a leaving symbol, allows sanctioned exits)"
  - "UniverseHandler remove-policy consumer (orphan-and-track default vs force-close) + detach-on-flat on_fill hook"
  - "Multi-symbol paper/replay integration harness (remove_policy_harness) proving orphan-and-track + force-close deterministically offline"
affects: [06-05, universe wiring, live route composition]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Leaving-symbol admission gate reads Universe.leaving_symbols() as the FIRST gate (before direction), no-op when no universe/empty leaving-set (oracle-dark)"
    - "Remove policy defers unsubscribe until flat (orphan-and-track) — WS/ring kept alive so the stop can fire; detach on the flat FILL"
    - "Deterministic multi-symbol replay harness driving two symbols through LiveBarFeed.update + reused SimulatedExchange, offline"

key-files:
  created:
    - tests/integration/test_universe_remove_policy.py
    - tests/integration/test_universe_force_close.py
  modified:
    - itrader/core/enums/order.py
    - itrader/order_handler/admission/admission_manager.py
    - itrader/universe/universe_handler.py
    - tests/unit/order/test_leaving_symbol_admission.py
    - tests/unit/universe/test_universe_poll.py
    - tests/integration/conftest.py

key-decisions:
  - "remove_policy flag lives in the live/poll-seam config (UniverseHandler ctor, default orphan-and-track), NOT SystemConfig.PerformanceSettings — backtest oracle untouched (§8/D-01)"
  - "The plan-04 UniverseHandler seams (on_universe_update REMOVE, on_fill detach) are integration-tested by DIRECT call against the REAL PortfolioHandler read model; the EventHandler route wiring is plan 05"
  - "Integration harness uses two synthetic symbols (AAAUSD/BBBUSD) on the paper venue so it never touches the BTCUSD golden replay provider — additive, oracle/parity untouched"

patterns-established:
  - "Detach-on-flat: a leaving symbol reaching flat (read model open-count == 0) unsubscribes + clears the leaving set"
  - "Force-close: emit an opposite-side full-exit market SignalEvent (Decimal) then unsubscribe; the exit passes the leaving gate as a sanctioned exit and settles through the reused SimulatedExchange"

requirements-completed: [UNIV-02]

# Metrics
duration: 20min
completed: 2026-07-06
---

# Phase 6 Plan 04: Open-Position-on-Remove Policy Summary

**D-01 remove policy delivered: a leaving-symbol admission gate (ADMISSION_LEAVING) that blocks new entries while allowing sanctioned exits, an orphan-and-track vs force-close remove consumer with detach-on-flat, and a deterministic multi-symbol paper/replay proof that settles force-close through the reused SimulatedExchange.**

## Performance

- **Duration:** ~20 min (this session: Task 3 only; Tasks 1-2 pre-committed on the branch)
- **Completed:** 2026-07-06
- **Tasks:** 3 (Tasks 1-2 previously committed; Task 3 executed this session)
- **Files modified:** 8 (3 src, 5 tests)

## Accomplishments

- **Task 1 (pre-committed):** `OrderTriggerSource.ADMISSION_LEAVING` + `AdmissionManager._enforce_leaving_symbol_admission` wired as the FIRST admission gate — audited-REJECTS a NEW entry for a symbol in `Universe.leaving_symbols()` while PASSING a sanctioned exit (SELL vs open LONG / BUY vs open SHORT). No-op with no universe / empty leaving-set (oracle-dark).
- **Task 2 (pre-committed):** `UniverseHandler` remove-policy consumer — orphan-and-track (`mark_leaving`, DEFER unsubscribe; unsubscribe-now only when nothing is held) vs force-close (emit opposite-side full-exit `SignalEvent`, then unsubscribe) + an `on_fill` detach-on-flat hook (unsubscribe + `clear_leaving` once the leaving symbol is flat). `remove_policy` lives on the live/poll-seam ctor, not `SystemConfig`.
- **Task 3 (this session):** a multi-symbol replay harness (`remove_policy_harness` in `tests/integration/conftest.py`) driving two symbols' bars through `LiveBarFeed.update` and settling through the reused `SimulatedExchange`, plus two integration tests proving orphan-and-track (defer-until-flat + new-entry block + detach-on-flat) and force-close (emit exit → settle via exchange → detach) — fully offline, no live venue.

## Task Commits

1. **Task 1: ADMISSION_LEAVING reason + leaving-symbol admission gate** — `fbe3a9c4` (test, RED) → `e594543a` (feat, GREEN)
2. **Task 2: remove-policy consumer (orphan/force-close) + detach-on-flat** — `ad85ceba` (test, RED) → `b19d6c56` (feat, GREEN)
3. **Task 3: multi-symbol replay fixture + orphan-and-track & force-close integration tests** — `637339e2` (test)

_Tasks 1-2 followed the plan's `tdd="true"` RED→GREEN cadence and were committed by a prior executor before this session resumed._

## Files Created/Modified

- `itrader/core/enums/order.py` — added `ADMISSION_LEAVING = "admission_leaving"` (Task 1)
- `itrader/order_handler/admission/admission_manager.py` — `_enforce_leaving_symbol_admission` gate, wired first in `process_signal` (Task 1)
- `itrader/universe/universe_handler.py` — `remove_policy` ctor param, `set_portfolio_read_model`, `on_universe_update` REMOVE branch, `on_fill` detach-on-flat, force-close exit emit (Task 2)
- `tests/unit/order/test_leaving_symbol_admission.py` — 7 unit behaviors for the gate (Task 1)
- `tests/unit/universe/test_universe_poll.py` — remove-policy + detach-on-flat unit behaviors (Task 2)
- `tests/integration/conftest.py` — `remove_policy_harness` two-symbol paper/replay fixture (Task 3)
- `tests/integration/test_universe_remove_policy.py` — orphan-and-track E2E (Task 3)
- `tests/integration/test_universe_force_close.py` — force-close settle-then-detach E2E (Task 3)

## Decisions Made

- Built the Task-3 harness on `LiveTradingSystem(exchange="paper")` (the ready-made LiveBarFeed + reused SimulatedExchange wiring) rather than reconstructing the graph, so bars flow through the REAL `feed.update` seam OKX uses and fills settle through the REAL exchange — while the `UniverseHandler` remove/on_fill seams are driven by direct call against the REAL `PortfolioHandler` read model (route wiring is plan 05).
- Used two synthetic symbols (AAAUSD/BBBUSD) registered on the simulated exchange so the harness is purely additive and never interacts with the BTCUSD golden replay provider (oracle + paper-parity stay untouched).
- Observed the ADMISSION_LEAVING rejection two ways: the `process_signal` `OperationResult` (failure, no order emitted) AND the audited REJECTED order's `triggered_by` history — proving no fresh exposure can open.

## Deviations from Plan

None - plan executed exactly as written. (Task 3's harness attaches to `LiveTradingSystem(exchange="paper")` as the plan's suggested "reused SimulatedExchange / same seam OKX uses" vehicle; this is a harness-shape choice within the plan's stated options, not a deviation.)

## Issues Encountered

- Initial harness used `order.order_id` to look up the audited rejection history; the `Order` entity's id attribute is `id`. Fixed to `order.id` (get_order_history keyed by it). Tests green thereafter.

## Verification

- `poetry run pytest tests/unit/order/test_leaving_symbol_admission.py tests/unit/universe/test_universe_poll.py tests/integration/test_universe_remove_policy.py tests/integration/test_universe_force_close.py` → **21 passed**
- `poetry run pytest tests/integration/test_backtest_oracle.py tests/integration/test_paper_parity.py` → **4 passed** (oracle byte-exact `46189.87730727451`; paper-parity green — oracle-dark: empty leaving-set = gate no-op)
- `poetry run mypy --strict itrader/universe/universe_handler.py` → **Success: no issues found**

## Next Phase Readiness

- The remove policy + admission gate + detach-on-flat are complete and proven; plan 05 wires the live TIME poll timer + the `UniverseHandler` onto the LIVE `_routes` (poll `on_time`, `on_universe_update`, `on_fill`) and the composition-root `set_portfolio_read_model`/`set_provider`/`set_symbol_validator` seams. UNIV-02 satisfied (remove half).

---
*Phase: 06-dynamic-universe-membership*
*Completed: 2026-07-06*

## Self-Check: PASSED

All created files verified present; all five task commits (`fbe3a9c4`, `e594543a`, `ad85ceba`, `b19d6c56`, `637339e2`) verified in git history.
