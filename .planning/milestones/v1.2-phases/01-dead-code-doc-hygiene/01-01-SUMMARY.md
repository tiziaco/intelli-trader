---
phase: 01-dead-code-doc-hygiene
plan: 01
subsystem: order_handler, portfolio_handler
tags: [dead-code, cleanup, byte-exact, DEAD-01]
requirements_completed: [DEAD-01]
dependency_graph:
  requires: []
  provides:
    - "portfolio_handler/base.py with PortfolioStateStorage only (3 dead ABCs removed)"
    - "order_handler/base.py with OrderStorage only (OrderBase removed)"
    - "standalone OrderHandler class (no base)"
  affects:
    - itrader/order_handler/__init__.py
    - itrader/order_handler/order_handler.py
tech_stack:
  added: []
  patterns:
    - "barrel re-export edit = update both import and __all__"
    - "partial-file deletion preserving co-located kept ABC + its imports"
key_files:
  created: []
  modified:
    - itrader/portfolio_handler/base.py
    - itrader/portfolio_handler/portfolio.py
    - itrader/order_handler/base.py
    - itrader/order_handler/order_handler.py
    - itrader/order_handler/__init__.py
decisions:
  - "D-04: full importer sweep — OrderHandler made standalone, OrderBase dropped from import + __all__"
  - "D-05: touched-path cleanup only — no orphaned imports existed to remove (all top imports still used by kept ABCs)"
  - "Kept PortfolioStateStorage and OrderStorage ABCs untouched (per D-04 / import_retention_facts)"
  - "Left tests/unit/events/test_bar_event_ohlc.py untouched — get_last_close there is a Bar string assertion (cleared false alarm)"
metrics:
  duration_min: 2
  tasks_completed: 3
  files_modified: 5
  completed: 2026-06-11
---

# Phase 1 Plan 01: Code Deletions Summary

Byte-exact, behavior-preserving deletion of three dead portfolio ABCs, the orphan
`get_last_close` abstractmethod, the unused `OrderBase` base class (with full importer
sweep making `OrderHandler` standalone), and a dead `import numpy as np` — golden master
held byte-exact (134 trades / final_equity 46189.87730727451), mypy --strict clean, full
suite + 58/58 e2e green.

## What Was Built

- **Task 1 — dead portfolio ABCs + numpy import** (`refactor(01-01): delete dead portfolio ABCs and dead numpy import`):
  Removed `AbstractPortfolioHandler` / `AbstractPortfolio` / `AbstractPosition` (and the orphan
  `get_last_close` abstractmethod) from `portfolio_handler/base.py`, leaving the live
  `PortfolioStateStorage` ABC and every top-of-file import intact (all still used by the kept
  class). Removed the dead `import numpy as np` from `portfolio_handler/portfolio.py`.
- **Task 2 — OrderBase deletion + importer sweep** (`refactor(01-01): delete OrderBase and make OrderHandler standalone`):
  Removed `OrderBase` from `order_handler/base.py` (kept `OrderStorage`). Made `OrderHandler`
  a standalone class (`class OrderHandler:`), changed its import to `from .base import OrderStorage`,
  and dropped `OrderBase` from the `order_handler/__init__.py` import and `__all__` (kept `OrderStorage`).
- **Task 3 — milestone gate** (verification only): mypy --strict, integration oracle, e2e, full suite.

## Key Decisions

- **D-04 (full importer sweep):** `OrderBase` was inherited by `OrderHandler` and re-exported in the
  barrel, so zero-breakage required real importer edits, not just a class deletion.
- **D-05 (touched-path cleanup):** Confirmed against `import_retention_facts` — after the deletions,
  every top-of-file import in both `base.py` files is still used by the kept ABCs (`PortfolioStateStorage`,
  `OrderStorage`) and the `IdLike` alias; there were NO orphaned imports to remove.
- **Indentation discipline held:** deleted classes were tab-indented; the kept `PortfolioStateStorage`
  (4-space) and `OrderStorage` (4-space) classes were left exactly as-is — no normalization.
- **False alarm left intact:** `tests/unit/events/test_bar_event_ohlc.py:62` references `get_last_close`
  as a string in a `not hasattr(bar, ...)` assertion against a `Bar` struct — unrelated to the deleted
  ABC method; not touched.

## Verification Results

- `grep -rn "AbstractPortfolioHandler\|AbstractPortfolio\|AbstractPosition\|OrderBase" itrader/` — no hits.
- Kept ABCs present: `class PortfolioStateStorage` and `class OrderStorage` both still exist.
- `grep -n "import numpy" itrader/portfolio_handler/portfolio.py` — no hits.
- `poetry run mypy --strict` — Success: no issues found in 161 source files.
- `poetry run pytest tests/integration` — 12 passed; oracle byte-exact: **134 trades / final_equity 46189.87730727451** (summary.json `trade_count: 134`, `final_equity: 46189.87730727451`).
- `poetry run pytest tests/e2e -m e2e` — **58 passed**.
- `poetry run pytest` (full suite) — **810 passed**.
- Module imports clean: `import itrader.portfolio_handler.base; import itrader.portfolio_handler.portfolio` and `from itrader.order_handler import OrderHandler, OrderStorage` both exit 0.

## Deviations from Plan

None — plan executed exactly as written. The byte-exact oracle did not move, confirming the
deletions were behavior-preserving (no live path touched).

## Commits

- `0e3e353` refactor(01-01): delete dead portfolio ABCs and dead numpy import
- `6a817ed` refactor(01-01): delete OrderBase and make OrderHandler standalone

## Self-Check: PASSED

- itrader/portfolio_handler/base.py — modified, `class PortfolioStateStorage` present, dead ABCs absent.
- itrader/portfolio_handler/portfolio.py — modified, numpy import absent.
- itrader/order_handler/base.py — modified, `class OrderStorage` present, `OrderBase` absent.
- itrader/order_handler/order_handler.py — modified, `class OrderHandler:` standalone.
- itrader/order_handler/__init__.py — modified, `OrderBase` absent from import and `__all__`.
- Commit 0e3e353 — present in git log.
- Commit 6a817ed — present in git log.
