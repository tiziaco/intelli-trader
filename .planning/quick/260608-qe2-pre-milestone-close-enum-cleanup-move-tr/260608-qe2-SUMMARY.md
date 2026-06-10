---
status: complete
phase: quick-260608-qe2
plan: 01
subsystem: core-enums, config
tags: [refactor, enums, hygiene, naming-collision]
requires: []
provides:
  - "core/enums/trading.py::TradingDirection (canonical home)"
  - "core/enums/system.py::SystemStatus (canonical home)"
  - "config.ExchangeVenue (renamed from config ExchangeType)"
  - "config.ConfigOrderType (renamed from config OrderType)"
affects:
  - itrader/core/sizing.py
  - itrader/trading_system/live_trading_system.py
  - itrader/config/exchange.py
  - itrader/config/trading.py
tech-stack:
  added: []
  patterns: ["barrel re-export from core/enums/__init__.py", "backward-compat re-export from sizing.py"]
key-files:
  created:
    - itrader/core/enums/trading.py
    - itrader/core/enums/system.py
  modified:
    - itrader/core/enums/__init__.py
    - itrader/core/sizing.py
    - itrader/trading_system/live_trading_system.py
    - itrader/config/exchange.py
    - itrader/config/trading.py
    - itrader/config/models.py
    - itrader/config/__init__.py
    - tests/unit/execution/exchanges/test_simulated_exchange.py
decisions:
  - "TradingDirection re-exported from sizing.py to keep the 6 existing call sites unchanged (zero churn)"
  - "Removed now-unused `from enum import Enum` imports in sizing.py and live_trading_system.py for clean import lists"
  - "Config collision enums renamed (not deleted) per quick-fix scope; core enums untouched"
metrics:
  duration: ~15m
  completed: 2026-06-08
requirements: [QE2-ENUM-CLEANUP]
---

# Phase quick-260608-qe2 Plan 01: Pre-Milestone-Close Enum Cleanup Summary

Relocated `TradingDirection` and `SystemStatus` to their canonical home in `core/enums/`,
and resolved two config-layer name collisions by renaming the config-domain enums
(`ExchangeType`→`ExchangeVenue`, `OrderType`→`ConfigOrderType`) — behavior-preserving,
no member changes, all 725 tests green and `mypy --strict` clean.

## What Was Built

### Task 1 — Relocate misplaced enums into core/enums/ (commit 34a90b8)
- Created `itrader/core/enums/trading.py` housing `TradingDirection` (moved verbatim from
  `core/sizing.py`, including its case-insensitive `_missing_` classmethod).
- Created `itrader/core/enums/system.py` housing `SystemStatus` (moved verbatim from
  `live_trading_system.py`).
- Both new modules import stdlib `enum` only — the `core/enums/` dependency-free rule holds.
- `core/enums/__init__.py` now re-exports both via the barrel and lists them in `__all__`.
- `core/sizing.py` deletes its local `TradingDirection` class and instead imports it from
  `core/enums` (added to the existing `Side` import), keeping `"TradingDirection"` in its
  `__all__` so the 6 downstream `from itrader.core.sizing import TradingDirection` call sites
  work unchanged. The now-unused `from enum import Enum` import was removed.
- `live_trading_system.py` deletes its local `SystemStatus` class and imports it from
  `core/enums`; the ~10 `SystemStatus.X` usages resolve unchanged. The now-unused
  `from enum import Enum` import was removed.

### Task 2 — Rename config collision enums (commit 6608300)
- `config/exchange.py`: `class ExchangeType(str, Enum)` → `class ExchangeVenue(str, Enum)`;
  updated the `exchange_type` field annotation/default and the 4 factory presets.
- `config/trading.py`: `class OrderType(str, Enum)` → `class ConfigOrderType(str, Enum)`;
  updated the `default_order_type` field annotation/default.
- `config/models.py` and `config/__init__.py`: updated the import blocks and `__all__` lists
  to re-export the new names.
- The canonical core enums (`core/enums/execution.py::ExchangeType` execution-mode and
  `core/enums/order.py::OrderType`) were NOT touched.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed stale dead import of the old config `ExchangeType` name in a test**
- **Found during:** Task 2 (the final collision grep / test gate)
- **Issue:** `tests/unit/execution/exchanges/test_simulated_exchange.py` imported `ExchangeType`
  from `itrader.config.exchange` (an unused/dead import). The plan's investigation note said
  "no domain code imports these config enums outside config/" but missed this test-side import.
  After the rename it raised `ImportError: cannot import name 'ExchangeVenue'`-style failures
  (the old name no longer existed), breaking test-module collection for the whole file.
- **Fix:** Renamed the import `ExchangeType` → `ExchangeVenue` to match the new config name.
  The symbol was never used in the test body, so no further edits were needed.
- **Files modified:** tests/unit/execution/exchanges/test_simulated_exchange.py
- **Commit:** 6608300

## Verification

- **Import smoke (combined):** `import itrader; from itrader.core.enums import TradingDirection, SystemStatus; from itrader.config import ExchangeVenue, ConfigOrderType` — PASS
- **Task 1 smoke:** `TradingDirection is sizing.TradingDirection`, `TradingDirection('long_only') is LONG_ONLY`, `SystemStatus.RUNNING.value == 'running'` — PASS
- **Task 2 smoke:** `ExchangeVenue.SIMULATED.value == 'simulated'`, `ConfigOrderType.MARKET.value == 'market'`, core `ExchangeType is not ExchangeVenue`, core `OrderType is not ConfigOrderType` — PASS
- **mypy --strict:** Success, no issues found in 131 source files.
- **Test suite:** 725 passed, no warnings (pyproject `filterwarnings=["error"]` + `--strict-markers` active).
- **Collision grep:** `grep -rn "ExchangeType|\bOrderType\b" itrader/ tests/ scripts/` — every remaining
  hit resolves to a CORE enum (`from itrader.core.enums import ...`). No dangling references to the
  old config names anywhere in the repo.

### Verification environment note
The poetry `.venv` and editable `itrader` install live in the main checkout, not the worktree.
To exercise the worktree code, the test/import/mypy gates were run with the worktree root on the
import path (`PYTHONPATH=<worktree>` for pytest/python; `mypy` run from the worktree cwd where
`files=["itrader"]` resolves to the worktree package). A gitignored `.env` was copied into the
worktree so the Settings layer initialized correctly.

## Known Stubs

None.

## Threat Flags

None — pure internal enum relocation/rename; no new network, auth, file-access, or schema surface.

## Self-Check: PASSED

- FOUND: itrader/core/enums/trading.py
- FOUND: itrader/core/enums/system.py
- FOUND: .planning/quick/260608-qe2-pre-milestone-close-enum-cleanup-move-tr/260608-qe2-SUMMARY.md
- FOUND commit: 34a90b8 (Task 1)
- FOUND commit: 6608300 (Task 2)
