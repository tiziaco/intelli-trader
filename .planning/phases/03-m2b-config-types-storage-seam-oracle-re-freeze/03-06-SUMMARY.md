---
phase: 03-m2b-config-types-storage-seam-oracle-re-freeze
plan: 06
subsystem: portfolio_handler
tags: [refactor, reorg, git-mv, subdomain-packages, D-11, M2-08]
requires: ["03-03 (enums centralized to core/enums)", "03-05 (config Pydantic collapse)"]
provides:
  - "portfolio_handler/ reorganized into position/ transaction/ cash/ metrics/ subdomain packages"
  - "subdomain package __init__.py re-exports for short consumer import paths"
  - "clean seam for the 03-07 storage/ peer package + 03-08 pytest move"
affects:
  - itrader/portfolio_handler/portfolio.py
  - "4 portfolio_handler test files (import rewire)"
tech-stack:
  added: []
  patterns:
    - "subdomain-named packages (NOT *_manager/) per D-11"
    - "history-preserving git mv + package __init__ re-export"
key-files:
  created:
    - itrader/portfolio_handler/position/__init__.py
    - itrader/portfolio_handler/transaction/__init__.py
    - itrader/portfolio_handler/cash/__init__.py
    - itrader/portfolio_handler/metrics/__init__.py
  modified:
    - itrader/portfolio_handler/position/position.py (moved via git mv)
    - itrader/portfolio_handler/position/position_manager.py (moved via git mv)
    - itrader/portfolio_handler/transaction/transaction.py (moved via git mv)
    - itrader/portfolio_handler/transaction/transaction_manager.py (moved via git mv)
    - itrader/portfolio_handler/cash/cash_manager.py (moved via git mv)
    - itrader/portfolio_handler/metrics/metrics_manager.py (moved via git mv)
    - itrader/portfolio_handler/portfolio.py (manager imports rewired)
    - test/test_portfolio_handler/test_position_manager.py (import rewired)
    - test/test_portfolio_handler/test_transaction_manager.py (import rewired)
    - test/test_portfolio_handler/test_cash_manager.py (import rewired)
    - test/test_portfolio_handler/test_metrics_manager.py (import rewired)
decisions:
  - "Enum re-exports (TransactionType/PositionSide) sourced from core.enums in the package __init__ (their canonical home post 03-03), not re-exported through the moved entity submodule — satisfies mypy --strict explicit-export and keeps existing test import paths (...transaction import TransactionType) unchanged."
metrics:
  duration: 9
  completed: 2026-06-05
---

# Phase 03 Plan 06: portfolio_handler Subdomain Reorg Summary

Pure history-preserving `git mv` of the four flat portfolio manager modules + their entities into
subdomain packages (`position/`, `transaction/`, `cash/`, `metrics/`) per D-11, with all importers
rewired and zero behavior change — suite green, mypy --strict clean, behavioral oracle byte-exact.

## What Was Done

Task 1 (single auto task) — one atomic reorg commit:

- `git mv` (100% rename, history preserved) of:
  - `position.py` + `position_manager.py` → `position/`
  - `transaction.py` + `transaction_manager.py` → `transaction/`
  - `cash_manager.py` → `cash/`
  - `metrics_manager.py` → `metrics/`
- Added a small `__init__.py` per package re-exporting the public classes:
  - `position/`: `Position`, `PositionManager`, `PositionSide`
  - `transaction/`: `Transaction`, `TransactionManager`, `TransactionType`
  - `cash/`: `CashManager`, `CashOperation`
  - `metrics/`: `MetricsManager`, `PortfolioSnapshot`, `PerformanceMetrics`
- Rewired importers to the new subdomain paths:
  - `portfolio.py` — the four manager imports
  - 4 test files — manager imports (`position.position_manager`, `transaction.transaction_manager`,
    `cash.cash_manager`, `metrics.metrics_manager`)
  - Entity imports (`...transaction import Transaction, TransactionType`,
    `...position import Position, PositionSide`) resolve unchanged via the new package `__init__` re-exports.
- No `*_manager/` folder names exist — folders are subdomain-named per D-11.

## Verification

| Gate | Result |
|------|--------|
| `python -c` import of all four new manager paths | exits 0 (OK) |
| No `*_manager/` folders | confirmed (none) |
| `git log --follow itrader/portfolio_handler/transaction/transaction_manager.py` | rename history visible (100%), prior commit `a34b548` reachable |
| `make test` | 321 passed, 4 skipped, 1 xfailed — identical to pre-reorg |
| `pytest --collect-only` count | 326 — unchanged from baseline |
| `make typecheck` (`mypy --strict`) | Success: no issues found in 145 source files |
| `test_oracle_behavioral_identity` | PASSED — byte-exact, zero behavior change |

## Deviations from Plan

None — plan executed exactly as written. One discretionary decision (logged above): the package
`__init__` files import `TransactionType`/`PositionSide` from `core.enums` (canonical home) rather
than re-exporting them through the moved entity submodule, which mypy --strict requires for explicit
export. This keeps the existing `from itrader.portfolio_handler.transaction import TransactionType`
test import paths working with zero test churn beyond the manager-path rewires.

## Known Stubs

None.

## Threat Flags

None — internal module reorganization only; no new external surface (matches threat register T-03-06,
disposition `accept`).

## Notes for Downstream

- The peer `storage/` package (03-07) lands beside these four subdomain packages.
- This plan runs at Wave 4, BEFORE the 03-08 `test/`→`tests/` move; all oracle/test paths here use
  the CURRENT pre-move `test/test_integration/...` location.
- Commit `024b135` is isolated (reorg only) and bisectable per D-11.

## Self-Check: PASSED

- itrader/portfolio_handler/position/__init__.py — FOUND
- itrader/portfolio_handler/transaction/__init__.py — FOUND
- itrader/portfolio_handler/cash/__init__.py — FOUND
- itrader/portfolio_handler/metrics/__init__.py — FOUND
- itrader/portfolio_handler/position/position_manager.py — FOUND
- itrader/portfolio_handler/transaction/transaction_manager.py — FOUND
- itrader/portfolio_handler/cash/cash_manager.py — FOUND
- itrader/portfolio_handler/metrics/metrics_manager.py — FOUND
- Commit 024b135 — FOUND
