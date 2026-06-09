---
phase: 02-m2a-identity-money-determinism
plan: 02
subsystem: core (shared-core foundation tier)
tags: [identity, money, determinism, decimal, clock, newtype]
requires: []
provides:
  - "itrader.core.ids: OrderId/PortfolioId/PositionId/TransactionId/StrategyId/ScreenerId NewType aliases (D-12)"
  - "itrader.core.money: to_money (str-entry) + quantize (per-instrument HALF_UP) (D-01..D-04)"
  - "itrader.core.clock: Clock protocol + BacktestClock (advance contract) + WallClock (D-09/D-10)"
affects:
  - "itrader/core/__init__.py barrel (now re-exports ids)"
tech-stack:
  added: []
  patterns:
    - "NewType over uuid.UUID for distinct nominal id types (no runtime cost)"
    - "Decimal(str(x)) entry path; quantize at boundaries only with ROUND_HALF_UP"
    - "injectable Clock seam (Protocol + BacktestClock/WallClock) for determinism"
key-files:
  created:
    - test/test_core/test_money.py
    - test/test_core/test_clock.py
    - itrader/core/ids.py
    - itrader/core/money.py
    - itrader/core/clock.py
  modified:
    - itrader/core/__init__.py
decisions:
  - "D-12: six NewType ID aliases over stdlib uuid.UUID, no discriminator/type-prefix (D-13)"
  - "D-04: to_money enters Decimal via Decimal(str(x)) to avoid float-repr artifacts"
  - "D-03/D-02: quantize applies per-instrument scale with ROUND_HALF_UP at money boundaries only (D-01)"
  - "D-09/D-10: clock is mechanism-only here; engine-path wiring is Plan 06, order/txn timestamps are M2b"
metrics:
  duration: 4
  completed: 2026-06-04
---

# Phase 2 Plan 02: Shared-Core Foundation (ids / money / clock) Summary

Created the three pure-new shared-core foundation modules every downstream Phase 2 plan imports:
`core/ids.py` (six `NewType` id aliases over `uuid.UUID`), `core/money.py` (centralized
`Decimal(str(x))` entry + per-instrument `ROUND_HALF_UP` quantization), and `core/clock.py`
(injectable `Clock` protocol with `BacktestClock`/`WallClock`) — plus the co-located Wave 0
`test_core` money + clock scaffolds. No existing code was edited beyond the `core/__init__.py`
barrel re-export.

## What Was Built

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 1 | Co-located Wave 0 scaffolds (money + clock) | `bfaae9c` | test/test_core/test_money.py, test/test_core/test_clock.py |
| 2 | core/ids.py — six NewType ID aliases (D-12) | `72d5b98` | itrader/core/ids.py, itrader/core/__init__.py |
| 3 | core/money.py — Decimal quantization policy (D-01..D-04) | `9805e07` | itrader/core/money.py |
| 4 | core/clock.py — injectable Clock (D-09/D-10) | `aa2b943` | itrader/core/clock.py |

### `itrader/core/ids.py`
Six `NewType` aliases over stdlib `uuid.UUID`: `OrderId`, `PortfolioId`, `PositionId`,
`TransactionId`, `StrategyId`, `ScreenerId`. Distinct nominal types to mypy, identity-passthrough at
runtime (`OrderId(u) is u`). No discriminator field or type-prefix encoding (D-13). Barrel-exported
from `itrader.core` (importable as both `from itrader.core.ids import OrderId` and
`from itrader.core import OrderId`).

### `itrader/core/money.py`
`to_money(x)` enters Decimal via `Decimal(str(x))` (D-04 — avoids the `Decimal(10.1)` float-repr
artifact). `quantize(value, instrument, kind)` looks up the per-instrument scale
(`_INSTRUMENT_SCALES` with a `BTCUSD` override over `_DEFAULT_SCALES`) and applies `ROUND_HALF_UP`
at the boundary only (D-01/D-02/D-03). Unknown instruments fall back to defaults. Module docstring
documents the boundary-only quantize discipline (Pitfall 5).

### `itrader/core/clock.py`
`Clock` Protocol (`now() -> datetime`), `BacktestClock` (asserts "BacktestClock not advanced" before
`set_time`, returns injected time after), `WallClock` (real `datetime.now()`). Mechanism only —
engine-path wiring deferred to Plan 06; order-audit / transaction timestamps deferred to M2b (D-10).

## Verification Evidence

- `poetry run pytest test/test_core/test_money.py test/test_core/test_clock.py` → **8 passed**
- `poetry run python -c "from itrader.core.ids import OrderId"` → exit 0
- `poetry run mypy itrader/core/ids.py itrader/core/money.py itrader/core/clock.py` →
  **Success: no issues found in 3 source files** (all three new files are mypy-strict clean)

## Deviations from Plan

None — plan executed exactly as written.

The Task 1 scaffolds collect as import-time errors (not `--strict-markers` errors) until Tasks 3/4
land the modules they import; this is the plan's intended "red pending Tasks 3/4" state, and both go
green after Tasks 3/4. The explicit module-level `pytestmark = pytest.mark.unit` was carried on each
scaffold as specified, so the failure mode is purely `ImportError`, never a marker-strictness error.

## Authentication Gates

None.

## Known Stubs

None — all three modules are fully implemented and their consuming Wave 0 tests pass green.

## Self-Check: PASSED

- FOUND: test/test_core/test_money.py
- FOUND: test/test_core/test_clock.py
- FOUND: itrader/core/ids.py
- FOUND: itrader/core/money.py
- FOUND: itrader/core/clock.py
- FOUND commit: bfaae9c (Task 1)
- FOUND commit: 72d5b98 (Task 2)
- FOUND commit: 9805e07 (Task 3)
- FOUND commit: aa2b943 (Task 4)
