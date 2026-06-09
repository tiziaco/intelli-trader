---
phase: 03-m2b-config-types-storage-seam-oracle-re-freeze
plan: 03
subsystem: core/enums
tags: [enums, type-centralization, M2-07, de-map, behavior-preserving]
requires: ["03-01"]
provides:
  - "core.enums.FillStatus (class-based, _missing_ case-insensitive parse)"
  - "core.enums.CashOperationType / PositionEvent / MetricsPeriod / TransactionState (relocated)"
  - "core.enums.TransactionType._missing_ (case-insensitive parse for uppercase action strings)"
affects:
  - itrader/events_handler/event.py
  - itrader/portfolio_handler/transaction.py
  - itrader/portfolio_handler/cash_manager.py
  - itrader/portfolio_handler/position_manager.py
  - itrader/portfolio_handler/metrics_manager.py
  - itrader/portfolio_handler/transaction_manager.py
  - itrader/order_handler/order_manager.py
  - itrader/portfolio_handler/portfolio_handler.py
tech-stack:
  added: []
  patterns:
    - "Enum _missing_ classmethod for case-insensitive string parse (D-04 Pattern 4)"
    - "Single source of truth per enum in core/enums; parse-on-the-type replaces string->enum map dicts"
key-files:
  created: []
  modified:
    - itrader/core/enums/execution.py
    - itrader/core/enums/portfolio.py
    - itrader/core/enums/__init__.py
    - itrader/events_handler/event.py
    - itrader/portfolio_handler/transaction.py
    - itrader/portfolio_handler/cash_manager.py
    - itrader/portfolio_handler/position_manager.py
    - itrader/portfolio_handler/metrics_manager.py
    - itrader/portfolio_handler/transaction_manager.py
    - itrader/order_handler/order_manager.py
    - itrader/portfolio_handler/portfolio_handler.py
decisions:
  - "D-04: relocate + de-map only — kept OrderStatus/FillStatus/TransactionState DISTINCT (FillStatus.EXECUTED->OrderStatus.FILLED reconciliation in order_manager preserved)"
  - "D-05: EventType left inline in event.py (M3 owns its redesign); event_type_map kept as-is"
  - "Added _missing_ to pre-existing TransactionType (Rule 3) so uppercase action strings ('BUY'/'SELL') parse case-insensitively, preserving old transaction_type_map behavior"
  - "Repointed FillStatus import in order_manager + portfolio_handler from event.py to core.enums (Rule 3) — event.py re-import is not an explicit export under mypy --strict"
metrics:
  duration: 5
  completed: 2026-06-05
  tasks: 2
  files: 11
---

# Phase 3 Plan 3: Type Centralization (M2-07) Summary

Relocated `FillStatus` and the four inline portfolio-manager enums into `core/enums` as
class-based enums with a case-insensitive `_missing_` parse, and replaced the scattered
string->enum map dicts (`fill_status_map`, `transaction_type_map`) and their buggy
`raise ValueError('Value %s', x)` printf-tuple forms with parse-on-the-type — behavior-preserving
(behavioral oracle byte-exact, suite + `mypy --strict` green).

## What Was Built

**Task 1 — Relocate five enums to core/enums (commit `61107b6`)**
- `FillStatus` added to `core/enums/execution.py` (members `EXECUTED`/`REFUSED`/`CANCELLED`),
  rewritten from the prior functional `Enum("FillStatus", "EXECUTED REFUSED CANCELLED")`.
- `CashOperationType`, `PositionEvent`, `MetricsPeriod`, `TransactionState` added to
  `core/enums/portfolio.py`, member values preserved exactly from the prior class-based defs.
- Each enum carries a `_missing_` classmethod: case-insensitive match over members, raising
  `ValueError(f"Unknown {Name}: {value!r}")` on no match (RESEARCH Pattern 4 / Pitfall 2).
- All five re-exported from `core/enums/__init__.py` with `__all__` entries.

**Task 2 — Rewire consumers + delete the maps (commit `a34b548`)**
- `event.py`: imports `FillStatus` from `core.enums`; deleted inline functional def, deleted
  `fill_status_map`, and replaced `fill_status_map.get(status)` + buggy `ValueError` at the
  `FillEvent.new_fill` boundary with `FillStatus(status)` (drives `_missing_`).
- `transaction.py`: deleted `transaction_type_map`; replaced `.get(action)` + buggy
  `raise ValueError('Value %s', x)` with `TransactionType(filled_order.action)`.
- The four managers (`cash`/`position`/`metrics`/`transaction`): import the relocated enum from
  `core.enums`, delete the local class def, and drop the now-dead `from enum import Enum`.
- `EventType` left inline (D-05); `event_type_map` untouched.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Added `_missing_` to pre-existing `TransactionType`**
- **Found during:** Task 2 (de-mapping `transaction.py`)
- **Issue:** The old `transaction_type_map` keyed on uppercase strings (`"BUY"`/`"SELL"`), but
  `TransactionType` member values are lowercase (`"buy"`/`"sell"`) and the enum had no `_missing_`.
  `TransactionType("BUY")` would raise a non-descriptive `ValueError` and break the transaction
  path. The plan key_links explicitly call for `TransactionType._missing_`-driven parsing here.
- **Fix:** Added a case-insensitive `_missing_` classmethod to `TransactionType` in
  `core/enums/portfolio.py`, mirroring the relocated enums. `TransactionType("BUY")` now parses
  to `TransactionType.BUY` and unknown values raise the clear f-string error.
- **Files modified:** itrader/core/enums/portfolio.py
- **Commit:** a34b548

**2. [Rule 3 - Blocking] Repointed `FillStatus` import in two consumers to `core.enums`**
- **Found during:** Task 2 verification (`make typecheck`)
- **Issue:** `order_manager.py` and `portfolio_handler.py` imported `FillStatus` from
  `event.py`. After `event.py` switched to *importing* `FillStatus` (no longer defining it),
  mypy --strict flagged `Module "itrader.events_handler.event" does not explicitly export
  attribute "FillStatus"` (re-import is not an explicit export).
- **Fix:** Changed both consumers to import `FillStatus` directly from `core.enums` (the new
  single source of truth). The `FillStatus.EXECUTED -> OrderStatus.FILLED` reconciliation
  semantics in `order_manager` are unchanged — only the import source moved.
- **Files modified:** itrader/order_handler/order_manager.py, itrader/portfolio_handler/portfolio_handler.py
- **Commit:** a34b548

## Verification Results

- `poetry run pytest test/test_core/test_enums.py` — 2 passed (Wave-0 stub's skip-gate lifted;
  case-insensitive parse + clear-error assertions green).
- `from itrader.core.enums import FillStatus, CashOperationType, PositionEvent, MetricsPeriod,
  TransactionState` succeeds; `FillStatus('executed') is FillStatus.EXECUTED` True.
- `make test` — 302 passed, 9 skipped, 1 xfailed (identical profile to 03-01 baseline plus the
  2 newly-green enum tests).
- `make typecheck` — `Success: no issues found in 153 source files`.
- `test_oracle_behavioral_identity` — PASSED (behavioral oracle byte-exact; numeric oracle
  `test_oracle_numeric_values` remains the expected xfail per DEF-02-08-A).
- Acceptance grep: no functional `Enum(...)` syntax for any relocated name remains; `fill_status_map`
  and `transaction_type_map` deleted (only docstring mentions remain in core/enums); no
  `('Value %s', x)` printf-tuple `ValueError` remains.

## Threat Surface

T-03-03 (Tampering, string->enum parse) mitigated as planned: `_missing_` raises a clear
`ValueError` on unknown input (no silent `None`/swallow), replacing the buggy printf-tuple form.
No new external surface introduced.

## Known Stubs

None — this plan is a behavior-preserving relocation/de-map; no data-source stubs introduced.

## Self-Check: PASSED

- itrader/core/enums/execution.py — FOUND (FillStatus present)
- itrader/core/enums/portfolio.py — FOUND (4 relocated enums + TransactionType._missing_)
- itrader/core/enums/__init__.py — FOUND (re-exports present)
- Commit 61107b6 — FOUND
- Commit a34b548 — FOUND
