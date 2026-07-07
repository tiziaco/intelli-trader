---
phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
plan: 01
subsystem: reconciliation
tags: [decimal, reconciliation, alerting, protocol, enum, tdd]

# Dependency graph
requires:
  - phase: 02-okx-connector
    provides: LiveConnector Protocol swap-a-fake seam pattern (analog for AlertSink)
  - phase: 04-paper-path
    provides: live composition-root wiring seams (LiveTradingSystem)
provides:
  - "is_within_single_unit_tolerance(v1, v2, precision) — precision-epsilon drift-tolerance helper (D-01)"
  - "SystemStatus.HALTED — distinct machine-readable halt state (D-07)"
  - "AlertSink Protocol + LogAlertSink — pluggable CRITICAL/halt egress seam (D-06)"
  - "_log_error_event CRITICAL egress hook — routes ErrorSeverity.CRITICAL through the injected sink"
affects: [05-04-drift-halt-policy, 05-08-resilience, VenueAccount reconciliation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Precision-epsilon tolerance keyed off instrument precision (ported-in-concept from nautilus, never imported)"
    - "Duck-typed egress seam: events_handler routes through a local Protocol, sink injected at wiring (no layer inversion)"

key-files:
  created:
    - itrader/portfolio_handler/reconcile/__init__.py
    - itrader/portfolio_handler/reconcile/drift.py
    - itrader/trading_system/alert_sink.py
    - tests/unit/portfolio/test_drift_tolerance.py
    - tests/unit/execution/test_drift_halt_policy.py
  modified:
    - itrader/core/enums/system.py
    - itrader/events_handler/full_event_handler.py

key-decisions:
  - "Drift helper ports the nautilus reconciliation.py:52 algorithm in concept only — no nautilus runtime import (inertness + import-light)"
  - "AlertSink is a runtime_checkable Protocol with LogAlertSink as the only impl this milestone; external push deferred (RES-01)"
  - "events_handler types the sink via a local _AlertSinkLike Protocol (duck-typed) to avoid an events_handler -> trading_system layer inversion; attribute is None on the backtest path"

patterns-established:
  - "Reconciliation primitives live under portfolio_handler/reconcile/ (4-space indent, barrel-exported)"
  - "CRITICAL/halt egress binds only declared ErrorEvent fields — secret-scrub discipline (Pitfall 16, T-05-01)"

requirements-completed: [RECON-01, RECON-03, RES-01]

# Metrics
duration: 6min
completed: 2026-07-02
---

# Phase 05 Plan 01: Reconciliation-Cluster Primitives Summary

**Precision-epsilon drift-tolerance helper (`is_within_single_unit_tolerance`), a distinct `SystemStatus.HALTED` member, and a pluggable `AlertSink`/`LogAlertSink` egress that escalates CRITICAL `ErrorEvent`s — three venue-agnostic seams gating the Phase-5 drift/halt state machine.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-07-02T17:29:16Z
- **Completed:** 2026-07-02T17:35:02Z
- **Tasks:** 2
- **Files modified:** 7 (5 created, 2 modified)

## Accomplishments
- `is_within_single_unit_tolerance(v1, v2, precision)` — Decimal-only tolerance helper keyed off instrument precision (exact at precision 0, `10**-precision` otherwise), ported in concept from nautilus with no runtime import.
- `SystemStatus.HALTED` — a distinct machine-readable halt state with the D-07 reason vocabulary comment, added without disturbing the existing lifecycle members.
- `AlertSink` Protocol + `LogAlertSink` (marked structured `logger.critical`, the only impl this milestone) in a new `trading_system/alert_sink.py`.
- `_log_error_event` now routes `ErrorSeverity.CRITICAL` events through an injected, duck-typed `self._alert_sink` (default `None` on the backtest path) after the existing log call — no `events_handler -> trading_system` layer inversion, secrets stay scrubbed.

## Task Commits

Each task was committed atomically:

1. **Task 1 (RED): failing drift-tolerance test** - `8f2a8a06` (test)
2. **Task 1 (GREEN): precision-epsilon drift-tolerance helper** - `b1bc16e7` (feat)
3. **Task 2: SystemStatus.HALTED + AlertSink CRITICAL egress** - `41a68a39` (feat)

_Task 1 followed the TDD RED → GREEN cycle; no refactor commit was needed (the GREEN implementation is minimal and clean)._

## Files Created/Modified
- `itrader/portfolio_handler/reconcile/drift.py` - `is_within_single_unit_tolerance` (Decimal-only, nautilus-ported concept, D-01)
- `itrader/portfolio_handler/reconcile/__init__.py` - barrel re-export of the helper
- `itrader/trading_system/alert_sink.py` - `AlertSink` Protocol + `LogAlertSink` egress (D-06)
- `itrader/core/enums/system.py` - added `SystemStatus.HALTED` (D-07)
- `itrader/events_handler/full_event_handler.py` - `_AlertSinkLike` Protocol, `self._alert_sink` attribute, CRITICAL egress in `_log_error_event`
- `tests/unit/portfolio/test_drift_tolerance.py` - 7 cases across precision 0/2/8
- `tests/unit/execution/test_drift_halt_policy.py` - 7 cases: HALTED distinctness, CRITICAL routing, no-egress on backtest path, Protocol satisfaction, secret-scrub

## Decisions Made
- **No nautilus runtime import:** the drift helper reproduces the algorithm from `nautilus_trader/live/reconciliation.py:52` in concept; importing nautilus would break inertness and import-lightness. Documented as a PORTED reference in the module docstring.
- **Duck-typed sink annotation in events_handler:** rather than importing `AlertSink` from `trading_system` (a layer inversion), a local `_AlertSinkLike` Protocol types the injected attribute. This also keeps the acceptance grep `import.*trading_system == 0` clean.
- **`ErrorEvent` under `TYPE_CHECKING` in `alert_sink.py`:** the events package pulls pandas at runtime; the sink stays import-light.

## Deviations from Plan

None - plan executed exactly as written.

The one prose adjustment (rewording a docstring comment in `full_event_handler.py` so it no longer matched the `import.*trading_system` acceptance grep) was a wording fix to satisfy the plan's own acceptance criterion, not a functional deviation.

## Issues Encountered
- An initial docstring comment in `full_event_handler.py` contained the phrase "importing it — ... trading_system" on one line, which tripped the `grep -c 'import.*trading_system' == 0` acceptance check as a false positive. Reworded the comment to remove the substring collision; no code behavior changed.

## Verification

- New unit tests green: `tests/unit/portfolio/test_drift_tolerance.py` (7) + `tests/unit/execution/test_drift_halt_policy.py` (7) — 14 passed.
- `mypy --strict` clean on `reconcile/drift.py`, `trading_system/alert_sink.py`, `full_event_handler.py`, `core/enums/system.py`.
- Backtest oracle byte-exact: `tests/integration/test_backtest_oracle.py` — 3 passed (unchanged).
- Inertness intact: `tests/integration/test_okx_inertness.py` — 1 passed (backtest path imports no OKX/connector stack).
- All acceptance greps satisfied (def count 1, no nautilus import, HALTED present, `class LogAlertSink` 1, `alert_sink` in FEH, `import.*trading_system` == 0).

## Threat Flags

None found — no new network endpoints, auth paths, or trust-boundary surface beyond the plan's `<threat_model>` (T-05-01 mitigation is covered by the secret-scrub test).

## Next Phase Readiness
- The three seams (tolerance helper, HALTED status, AlertSink egress) are stable contracts ready for consumption by 05-04 (drift/halt state machine) and 05-08 (resilience supervisor).
- No blockers. The `_alert_sink` attribute is a `None` default; live wiring (injecting `LogAlertSink` at the `LiveTradingSystem` composition root) is a downstream plan's job.

## Self-Check: PASSED

All 7 created/modified files exist on disk; all 3 task commits (`8f2a8a06`, `b1bc16e7`, `41a68a39`) are present in git history.

---
*Phase: 05-real-sandbox-path-reconciliation-persistence-live-drive*
*Completed: 2026-07-02*
