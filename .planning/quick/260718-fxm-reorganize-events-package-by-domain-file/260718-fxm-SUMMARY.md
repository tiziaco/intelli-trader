---
phase: 260718-fxm
plan: 01
subsystem: events_handler
tags: [refactor, events, relocation, code-organization]
requires: []
provides:
  - "One-class-per-domain events package layout (portfolio.py/screener.py/strategy.py/feed.py added; ack.py removed)"
affects:
  - itrader/events_handler/events/
  - itrader/universe/universe_handler.py
tech-stack:
  added: []
  patterns:
    - "Barrel (__init__.py) as the stable public surface — public name set unchanged, only source modules re-pointed"
key-files:
  created:
    - itrader/events_handler/events/portfolio.py
    - itrader/events_handler/events/screener.py
    - itrader/events_handler/events/strategy.py
    - itrader/events_handler/events/feed.py
  modified:
    - itrader/events_handler/events/market.py
    - itrader/events_handler/events/universe.py
    - itrader/events_handler/events/order.py
    - itrader/events_handler/events/__init__.py
    - itrader/universe/universe_handler.py
    - tests/unit/events/test_universe_update_event.py
    - tests/unit/universe/test_universe_poll.py
    - tests/unit/universe/test_retry_policy_cr01.py
    - tests/unit/universe/test_universe_warmup_consumers.py
    - tests/integration/conftest.py
    - itrader/core/enums/event.py
    - CLAUDE.md
  deleted:
    - itrader/events_handler/events/ack.py
decisions:
  - "Pure relocation: every moved class preserved verbatim (class docstrings with D-NN tags, factory classmethods, __str__/__repr__, field defaults, ClassVar type pin). Only file location + module docstrings + imports changed."
  - "Barrel public name set + __all__ kept identical — the blast-radius shield for the many barrel importers; only the 6 direct-submodule importers of UniverseUpdateEvent needed re-pointing (market -> universe)."
metrics:
  duration: 4min
  completed: 2026-07-18
status: complete
---

# Phase 260718-fxm Plan 01: Reorganize Events Package by Domain Summary

Pure-relocation refactor of `itrader/events_handler/events/` to a cohesive one-class-per-trading-domain layout — 4 new domain files, `ack.py` removed, `OrderAckEvent` merged into `order.py`, `UniverseUpdateEvent` moved market→universe, barrel re-pointed with an unchanged public surface — with zero behavior change (oracle byte-exact 134 / 46189.87730727451).

## What Was Built

**Task 1 (commit 6e3f6f4c) — the atomic relocation:**
- Created `portfolio.py` (`PortfolioUpdateEvent`), `screener.py` (`ScreenerEvent`), `strategy.py` (`StrategyCommandEvent` + its 9 factory classmethods), `feed.py` (`BarsLoaded`, `BarsLoadFailed`) — each moved class verbatim, each new file carrying exactly the imports its classes need, 4-space indented.
- Trimmed `market.py` to `TimeEvent` + `BarEvent` (dropped the now-unused `Any` from the typing import).
- Rewrote `universe.py` to hold exactly `UniverseUpdateEvent` (moved in from market.py) + `UniversePollEvent`; trimmed imports (dropped `datetime`, `Any`, `Bar`).
- Merged `OrderAckEvent` into `order.py` after `OrderEvent` (no new imports — all symbols already present) and added a one-line module-docstring note; deleted `ack.py`.
- Updated the barrel `__init__.py` to source each name from its new module with refreshed grouping comments; `__all__` and the public name set are byte-identical.
- Re-pointed the 6 direct-submodule importers of `UniverseUpdateEvent` from `events.market` to `events.universe`.

**Task 2 (commit 3fbeedc7):** Corrected the stale `STRATEGY_COMMAND` inline comment in `core/enums/event.py` to list the full D-09 verb set. Enum member value unchanged.

**Task 3 (commit 51d94e7b):** Synced the CLAUDE.md "Event-driven core" events-split parenthetical to the new file set (added portfolio.py/screener.py/strategy.py/feed.py/control.py; removed the ack.py reference).

## Verification

Full Task-1 gate, all green:
- Barrel import smoke — all moved classes import from `itrader.events_handler.events`.
- `poetry run mypy --strict itrader` — Success: no issues found in 269 source files.
- `poetry run pytest tests/integration/test_backtest_oracle.py -v` — 3 passed; oracle byte-exact **134 / 46189.87730727451**.
- `poetry run pytest tests` — **2464 passed, 75 skipped** (all skips environmental: PostgreSQL container / OKX demo creds absent).
- `ack.py` no longer exists; 4 new files exist; grep confirms no stale submodule imports of any moved class; `fill.py`'s `from .order import OrderEvent` correctly preserved.

## Deviations from Plan

None — plan executed exactly as written. No auto-fixes, no authentication gates, no checkpoints. The 6 known importers proved exhaustive (a full-tree grep surfaced no additional direct-submodule importers of moved classes).

## Self-Check: PASSED

- Created files present: portfolio.py, screener.py, strategy.py, feed.py — all FOUND.
- ack.py — confirmed removed.
- Commits present: 6e3f6f4c (Task 1), 3fbeedc7 (Task 2), 51d94e7b (Task 3) — all FOUND in git log.
