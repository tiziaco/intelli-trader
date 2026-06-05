---
phase: 04-m3-event-dispatch-core
plan: 06
subsystem: events
tags: [dispatch, registry, get-nowait, toctou, error-route, fail-fast, d-23]
requires:
  - "04-05 (big-bang cutover — single events surface, PortfolioErrorEvent with type=EventType.ERROR)"
provides:
  - "Race-free dispatcher: get_nowait() + queue.Empty -> break drain (no empty() precheck, TOCTOU gone)"
  - "EventHandler-owned _routes dict[EventType, list[Callable]] literal — list order IS execution order (BAR: portfolios->execution->strategies; FILL: portfolio->order mirror)"
  - "Explicit empty SCREENER/UPDATE routes; unknown event types raise NotImplementedError"
  - "ERROR route -> _log_error_event structlog consumer; _on_handler_error fail-fast policy seam (D-live override point)"
  - "D-23 groups 1+3 regression-locked (route lists as data, error flow, latent-UPDATE crash)"
affects: [04-07, 04-08]
tech-stack:
  added: []
  patterns:
    - "routing-as-data: one reviewable dict literal in __init__; no registration API (D-14)"
    - "policy seam: _on_handler_error bare-raise (backtest fail-fast); live overrides the method, not _dispatch"
    - "TYPE_CHECKING-only event imports in the dispatcher (events package pulls pandas at runtime)"
    - "stub-block hygiene: pre-import heavy packages OUTSIDE patch.dict(sys.modules) blocks or eviction duplicates numpy's _NoValue and breaks scipy"
key-files:
  created:
    - tests/unit/events/test_dispatch_registry.py
    - tests/unit/events/test_error_flow.py
  modified:
    - itrader/events_handler/full_event_handler.py
key-decisions:
  - "Events imported TYPE_CHECKING-only in full_event_handler: a runtime import pulls pandas inside test_event_wiring's patch.dict stub block, whose exit evicts freshly-imported numpy/pandas from sys.modules — a later genuine numpy import re-executes the package, duplicating _NoValue and crashing scipy (oracle ERROR). Type-only import keeps module load light and the wiring test unmodified."
  - "Route value type is Callable[[Any], Any] (not None): two collaborators return values (generate_bar_event -> BarEvent|None, portfolio on_fill -> bool) and the dispatcher ignores returns — mypy strict rejects covariant non-None returns against Callable[..., None]"
  - "Per-TIME DEBUG log lives in _dispatch (not as a route entry) so the TIME route literal stays exactly the two documented handlers"
metrics:
  duration: "~12 min"
  completed: "2026-06-05"
  tasks: 2
  files: 3
---

# Phase 4 Plan 06: Race-Free Routing Registry Summary

The fused if/elif dispatch is replaced by an EventHandler-owned routing registry with a get_nowait()/queue.Empty drain (TOCTOU gone), explicit empty SCREENER/UPDATE routes, a real ERROR-route structlog consumer, the _on_handler_error fail-fast seam, and NotImplementedError on unknown types — locked by 14 new D-23 group 1+3 tests (411 passed, mypy strict clean, both oracle layers byte-exact with unmodified assertions).

## Tasks Completed

| Task | Name | Commit | Key Files |
| ---- | ---- | ------ | --------- |
| 1 | Rewrite EventHandler — registry literal, get_nowait drain, error seam, ERROR consumer | 71171d4 | itrader/events_handler/full_event_handler.py |
| 2 | D-23 group 1+3 tests — dispatch-ordering as data, error flow, latent-UPDATE regression | f2b0903 | tests/unit/events/test_dispatch_registry.py, tests/unit/events/test_error_flow.py |

## What Was Built

- **Drain (D-15):** `process_events` is `while True: get_nowait() / except queue.Empty: break` — no `empty()` precheck, no None-deref path; the old `continue`-on-Empty (potential infinite loop if `empty()` lied) is gone.
- **Registry (D-14/D-17):** `self._routes: dict[EventType, list[Callable[[Any], Any]]]` built as one literal in `__init__`. List order IS execution order, annotated inline: BAR = mark-to-market → resting-order matching → new signals; FILL = positions/cash → order-mirror reconciliation. TIME/SIGNAL/ORDER routes preserved exactly; SCREENER and UPDATE are explicit empty lists with deferral comments (D-screener / D-live). No registration API — handlers stay passive. Constructor signature and collaborator attribute names unchanged (both TradingSystems wire positionally, unmodified).
- **Unknown types (KB1/T-04-18):** missing registry key raises `NotImplementedError(f"EventHandler: unsupported event type {event.type!r}")`.
- **Error flow (D-16/D-17, T-04-15/T-04-17):** every handler call is wrapped; unexpected exceptions route to `_on_handler_error(event, handler)` whose backtest policy is a bare `raise` (re-raises the active exception — A1 verified by test; original exception type preserved). Docstring documents the D-live publish-and-continue override seam. `EventType.ERROR` routes to `_log_error_event`, which logs via the bound structlog logger at a severity mapped from `event.severity` (WARNING/CRITICAL/else-ERROR), binding source, error_type, error_message, operation, correlation_id, portfolio_id when present, and details — never secrets.
- **D-21 slice:** the per-tick `TIME EVENT:` log demoted INFO→DEBUG (lives in `_dispatch`); the init lifecycle log stays INFO. Plan 04-08 owns the rest of the logging work.
- **Tests (D-23 groups 1+3, 14 new):** route lists asserted as literal data (BAR, FILL, TIME, SIGNAL, ORDER), explicit-empty SCREENER/UPDATE, registry covers every EventType member, FIFO drain over N events + empty-queue termination, NotImplementedError on unknown types; ErrorEvent→consumer with the run continuing, severity→warning mapping, seam re-raise with the original exception type, the Pitfall 5 latent-UPDATE-crash regression (`PortfolioErrorEvent` with `type=EventType.ERROR` reaches the consumer instead of raising), and UPDATE dispatching to the empty route with zero collaborator calls.

## Verification Results

- `grep "global_queue.empty()"` → 0; `get_nowait` present; zero if/elif `event.type` chain
- `tests/integration/test_event_wiring.py` — **passes unmodified** (`git diff` empty)
- `tests/integration/test_backtest_oracle.py` — **2 passed UNMODIFIED**: behavioral + numerical oracle byte-exact (M3-04)
- Full suite: **411 passed** (Wave 5 baseline 397 + 14 new; zero tests lost)
- `poetry run mypy itrader` (the `make typecheck` command): Success — 133 files

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Runtime events import in the dispatcher broke the oracle when run after test_event_wiring**
- **Found during:** Task 1 verification (combined `test_event_wiring.py` + `test_backtest_oracle.py` run)
- **Issue:** the new `from itrader.events_handler.events import ErrorEvent, Event` executes inside test_event_wiring's `patch.dict(sys.modules, _STUB_MODULES)` block (the events package imports pandas via `market.py`); on block exit patch.dict EVICTS the freshly-imported numpy/pandas modules, so the oracle's later `import scipy` re-executes numpy — duplicated `_NoValueType` sentinel → `TypeError: int() argument ... not '_NoValueType'` during scipy import
- **Fix:** moved the events import under `if TYPE_CHECKING:` with quoted annotations — zero runtime imports added to the dispatcher module; test_event_wiring stays byte-identical
- **Files modified:** itrader/events_handler/full_event_handler.py
- **Commit:** 71171d4

**2. [Rule 3 - Blocking] mypy strict rejected Callable[[Any], None] route values**
- **Found during:** Task 1 verification (`mypy itrader`)
- **Issue:** `universe.generate_bar_event` returns `BarEvent | None` and `portfolio_handler.on_fill` returns `bool` — return types are covariant, so neither is assignable to `Callable[[Any], None]`
- **Fix:** route value type `Callable[[Any], Any]` with a comment (the dispatcher ignores handler return values); behavior identical
- **Files modified:** itrader/events_handler/full_event_handler.py
- **Commit:** 71171d4

### Minor in-scope clarifications

- **Per-TIME DEBUG log placement:** the plan pins the TIME route to exactly two handlers, so the demoted log lives at the top of `_dispatch` (fires only for `EventType.TIME`) rather than as a route entry.
- **New unit tests pre-import the events package outside their stub blocks** (same hygiene as deviation 1) — documented in the test module docstrings so future stub-block tests copy the safe shape.
- Worktree environment notes from 04-01..04-05 applied: all test runs with `PYTHONPATH=<worktree-root>`, `poetry run pytest tests/` / `poetry run mypy itrader` in place of `make test` / `make typecheck` (gitignored `.env` absent in the worktree).

## Known Stubs

None — no placeholder values or unwired data. The SCREENER and UPDATE empty routes are intentional, documented deferrals (D-screener / D-live), not stubs: events of those types are consciously consumed with no action on the backtest path.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or trust-boundary schema changes. T-04-15 mitigated (`_on_handler_error` fail-fast re-raise, locked by test_error_flow); T-04-16 mitigated (get_nowait + queue.Empty drain, no TOCTOU/None-deref path); T-04-17 mitigated (dedicated ERROR route with structlog consumer + Pitfall 5 regression test); T-04-18 mitigated (unknown types raise NotImplementedError, locked by test).

## TDD Gate Compliance

Not applicable — plan type is `execute`, not `tdd`.

## Self-Check: PASSED

- `itrader/events_handler/full_event_handler.py` contains `_routes`, `get_nowait`, `_on_handler_error`, `_log_error_event`; zero `empty()` prechecks
- `tests/unit/events/test_dispatch_registry.py` exists and contains `_routes`; `tests/unit/events/test_error_flow.py` exists and contains `NotImplementedError`
- Commits exist: 71171d4, f2b0903
- Deletion check: `git diff --diff-filter=D` empty for both commits
- Oracle assertions untouched: `git diff` over `tests/integration/test_backtest_oracle.py` and `tests/integration/test_event_wiring.py` empty across the plan
