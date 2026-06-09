---
phase: 04-m3-event-dispatch-core
plan: 01
subsystem: events
tags: [enums, events, ids, rename, behavior-preserving]
requires: []
provides:
  - "EventType class-based enum in core/enums: TIME/BAR/UPDATE/SIGNAL/ORDER/FILL/SCREENER/ERROR with case-insensitive _missing_"
  - "Side enum (BUY/SELL) in core/enums, ready for the D-05 retyping at the Plan 04-05 cutover"
  - "FillId/EventId NewType aliases in core/ids.py"
  - "TimeEvent/TimeGenerator family (PingEvent/PingGenerator/ping_generator fully deleted, D-08)"
affects: [04-02, 04-03, 04-04, 04-05, 04-06]
tech-stack:
  added: []
  patterns:
    - "class-based enum with case-insensitive _missing_ raising ValueError(f'Unknown X: {value!r}') — FillStatus house pattern (Phase 3 D-04)"
    - "explicit re-export `from ..core.enums import EventType as EventType` to satisfy mypy strict no_implicit_reexport while keeping the legacy import path alive until 04-05"
key-files:
  created:
    - itrader/core/enums/event.py
  modified:
    - itrader/core/enums/__init__.py
    - itrader/core/ids.py
    - itrader/events_handler/event.py
    - itrader/events_handler/full_event_handler.py
    - itrader/trading_system/simulation/time_generator.py
    - itrader/trading_system/backtest_trading_system.py
    - itrader/trading_system/live_trading_system.py
    - itrader/universe/dynamic.py
    - itrader/universe/universe.py
    - itrader/config/__init__.py
    - itrader/price_handler/live_streaming/BINANCE_Live.py
    - tests/unit/events/test_events.py
    - tests/unit/events/test_event_immutability.py
key-decisions:
  - "EventType re-exported from events_handler/event.py via the `as` alias form (explicit re-export) — mypy strict's no_implicit_reexport rejects the plain import; legacy import path stays valid until the Plan 04-05 cutover"
  - "Worktree test runs MUST set PYTHONPATH=<worktree-root>: the shared .venv's itrader.pth editable install points at the main repo, so bare `poetry run pytest` silently tests the main checkout, not the worktree"
metrics:
  duration: "~15 min"
  completed: "2026-06-05"
  tasks: 2
  files: 14
---

# Phase 4 Plan 01: Event Vocabulary Foundations Summary

Class-based EventType (TIME replaces PING, ERROR added) + Side enum relocated to core/enums with FillStatus-style `_missing_`, FillId/EventId NewType aliases added, and the full PingEvent→TimeEvent / PingGenerator→TimeGenerator rename executed via history-preserving git mv — suite and both oracle layers byte-exact at every commit.

## Tasks Completed

| Task | Name | Commit(s) | Key Files |
| ---- | ---- | --------- | --------- |
| 1 | Relocate EventType to core/enums, add Side + FillId/EventId | 0294a70 | itrader/core/enums/event.py (new), core/enums/__init__.py, core/ids.py, events_handler/event.py, full_event_handler.py, live_trading_system.py |
| 2 | TimeEvent family rename (git mv + rename edits) | 2001df4 (pure mv), 1ec1904 (renames) | trading_system/simulation/time_generator.py, events_handler/event.py, backtest/live trading systems, universe/*, BINANCE_Live.py, event tests |

## What Was Built

- `itrader/core/enums/event.py` (NEW, 4-space): `class EventType(Enum)` with 8 explicit-uppercase-string members (TIME, BAR, UPDATE, SIGNAL, ORDER, FILL, SCREENER, ERROR) and a case-insensitive `_missing_` raising `ValueError(f"Unknown EventType: {value!r}")` — exact mirror of the FillStatus house pattern. Docstring records: TIME replaces PING ("the clock advanced to T", Nautilus precedent), TICK reserved for D-live, ERROR is new (D-06). `class Side(Enum)` (BUY/SELL) with the same `_missing_`; docstring records the D-05 boundary rule (events carry Side; Portfolio maps Side→TransactionType). No event field retyped — that is the 04-05 cutover.
- `itrader/core/enums/__init__.py`: "# Event enums" grouped import block + matching `__all__` group.
- `itrader/core/ids.py`: `FillId`/`EventId` NewType aliases appended, `__all__` extended, docstring count updated (six→eight), no-discriminator rule intact.
- `itrader/events_handler/event.py`: inline functional `EventType = Enum(...)` and dead `event_type_map` deleted; explicit re-export keeps `from itrader.events_handler.event import EventType` working for existing consumers. `PingEvent` → `TimeEvent` with corrected "simulation clock advanced to T" docstring; structure unchanged (still `frozen=True, slots=True`).
- `itrader/trading_system/simulation/time_generator.py`: history-preserving `git mv` of `ping_generator.py` (rename detected at 100%, `git log --follow` shows pre-rename history). `PingGenerator` → `TimeGenerator`, docstring fixed, yield switched to keyword form `TimeEvent(time=cast(Any, time).item(0))` (pre-empts the kw_only cutover), dead commented block deleted.
- All referencing sites repointed: backtest system (`self.time_generator`, `time_event` loop variable), live system import, universe base + dynamic (param renamed `ping_event` → `time_event`), config comment, BINANCE_Live (D-live minimal class-name fix only), both event test modules (`test_time_event_initialization`, `test_time_event_is_frozen`).
- `EventType.PING` → `EventType.TIME` at all three dispatch/metric sites; the dispatch chain structure itself untouched (Plan 04-06 owns it).

## Verification Results

- `grep EventType.PING` → 0; `grep event_type_map` → 0; `grep "PingEvent|PingGenerator|ping_generator"` → 0 (itrader/, tests/, scripts/)
- `EventType("time") is EventType.TIME`, `Side("buy") is Side.BUY`, `EventType("bogus")` raises `ValueError: Unknown EventType: 'bogus'` — verified
- Full suite: 349 passed at final state AND retro-verified 349 passed at each intermediate commit (0294a70, 2001df4) via throwaway detached worktrees
- `tests/integration/test_backtest_oracle.py`: 2 passed UNMODIFIED — behavioral + numerical oracle byte-exact (M3-04, D-22)
- `poetry run mypy itrader` (the `make typecheck` command): Success, 127 source files

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] mypy strict rejected the implicit EventType re-export**
- **Found during:** Task 1 (typecheck gate)
- **Issue:** `from ..core.enums import EventType` in `event.py` is an implicit re-export under `no_implicit_reexport`; `full_event_handler.py` and `backtest_trading_system.py` failed with `attr-defined`
- **Fix:** explicit re-export form `from ..core.enums import EventType as EventType`
- **Files modified:** itrader/events_handler/event.py
- **Commit:** 0294a70

**2. [Rule 3 - Blocking] pytest in the worktree silently tested the main repo's code**
- **Found during:** Task 2 verification (collection error pointed at the main repo path)
- **Issue:** the worktree shares the main project's `.venv`; its `itrader.pth` editable install puts the MAIN repo root on `sys.path`, and the pytest console script does not add the cwd — so every bare `poetry run pytest` run resolved `itrader` from the main checkout, not the worktree
- **Fix:** all test runs executed with `PYTHONPATH=<worktree-root>` (worktree package then shadows the editable install); commits 0294a70 and 2001df4 retro-verified suite-green via temporary detached `git worktree` checkouts with the same fix, so the "green at every commit" discipline (D-22) holds for all three commits
- **Files modified:** none (environment-only)
- **Commit:** n/a

**3. [Rule 3 - Blocking] `make typecheck` unusable in the worktree**
- **Found during:** Task 1 verification
- **Issue:** the Makefile `include .env` fails — `.env` is gitignored and absent from the worktree
- **Fix:** ran the target's underlying command directly (`poetry run mypy itrader`)
- **Files modified:** none
- **Commit:** n/a

### Minor in-scope extensions

- Renamed the backtest system's local vocabulary (`self.ping` → `self.time_generator`, `ping_event` loop var → `time_event`) — file-local, part of the D-08 rename intent, zero behavior change.
- `core/ids.py` docstring count "Six" → "Eight" to stay factually correct after the two new aliases.

## Known Stubs

None — no placeholder values or unwired data introduced.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or trust-boundary schema changes. T-04-01 mitigated (single EventType definition, zero stale-reference greps, oracle byte-exact); T-04-02 mitigated (`_missing_` raises, no silent default).

## TDD Gate Compliance

Not applicable — plan type is `execute` (behavior-preserving refactor), not `tdd`.

## Self-Check: PASSED

- Created files exist: itrader/core/enums/event.py, itrader/trading_system/simulation/time_generator.py (ping_generator.py gone, history preserved)
- Commits exist: 0294a70, 2001df4, 1ec1904
- No unintended file deletions (only the recorded git-mv rename)
