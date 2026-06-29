---
phase: 03-operational-sql-backends-2-store-layer
plan: 03
subsystem: portfolio-state-persistence
tags: [sql, persistence, portfolio, operational-store, OPS-02, OPS-04]
requires:
  - "itrader.storage.SqlBackend (spine) + Uuid/UtcIsoText types (Phase 1)"
  - "PortfolioStateStorage ABC + InMemoryPortfolioStateStorage (M2-08)"
  - "tests/integration/storage/conftest.py pg_backend fixture (Plan 03-01)"
provides:
  - "build_portfolio_tables(metadata) — six normalized portfolio-state tables"
  - "SqlPortfolioStateStorage(backend, portfolio_id) — bound-scope operational backend"
  - "PortfolioStateStorageFactory 'live' arm wired to the SQL backend"
affects:
  - "itrader/portfolio_handler/storage/ (new SQL backend; in-memory arm untouched)"
tech-stack:
  added: []
  patterns:
    - "Composition over inheritance — SqlPortfolioStateStorage has-a SqlBackend (D-06)"
    - "Bound portfolio_id scoping — every query filtered/injected (Pitfall 1)"
    - "Parameterized Core only — no f-string SQL (SEC-01 / T-03-09)"
    - "Explicit per-portfolio seq for append-only ordering (Pitfall 7)"
key-files:
  created:
    - itrader/portfolio_handler/storage/models.py
    - itrader/portfolio_handler/storage/sql_storage.py
    - tests/integration/storage/test_sql_portfolio_storage.py
  modified:
    - itrader/portfolio_handler/storage/storage_factory.py
decisions:
  - "No portfolios parent table (A4) — bind portfolio_id, no FK target needed"
  - "locked_margin.position_id is String (A2) — the ABC types it str, not uuid"
  - "Closed positions ordered by (exit_date, id) — no seq column modelled for positions"
  - "Factory 'live' default backend = SqlBackend(SqlSettings.default()) when none passed (per plan); Phase 4 injects the real Postgres backend"
metrics:
  duration: ~25m
  tasks: 3
  files: 4
  completed: 2026-06-29
---

# Phase 3 Plan 3: Portfolio-State Operational SQL Backend Summary

`SqlPortfolioStateStorage` persists the richest of the three operational seams — six
portfolio collections on Postgres-native `Numeric` money — scoped to a construction-bound
`portfolio_id` so no cross-portfolio bleed is possible (the isolation invariant Phase 4
rehydration depends on).

## What Was Built

**Task 1 — `build_portfolio_tables(metadata)` (six normalized tables).** An idempotent Core
registrar mirroring `itrader/results/models.py`: `positions` (open + closed via the `is_open`
flag, with the D-08 composite index `ix_positions_portfolio_open`), `transactions`,
`cash_reservations` (`reference_id` String PK-part), `locked_margin` (`position_id` **String**
PK-part per A2), `cash_operations`, and `equity_snapshots` (`(portfolio_id, seq)` composite PK,
`autoincrement=False` — the explicit per-portfolio `seq` is the single-UUID-rule-compliant
stable-ordering key, Pitfall 7 / A3). Every table carries a `portfolio_id`; money columns are
`Numeric` (OPS-04). Commit `4467c66`.

**Task 2 — `SqlPortfolioStateStorage` + factory `'live'` arm.** A `PortfolioStateStorage`
implementation that composes a `SqlBackend` (has-a, D-06), binds a `portfolio_id` at
construction, and implements all ~21 ABC methods via parameterized Core. The defining nuance
(Pitfall 1): the ABC has NO `portfolio_id` parameter on any method, so EVERY SELECT/DELETE
carries `.where(table.c.portfolio_id == self._portfolio_id)` and EVERY INSERT injects it —
including `cash_operations` / `equity_snapshots` rows whose source objects carry no
`portfolio_id` field. Reservations/locked-margin are upsert-by-composite-key maps with
idempotent `pop_*`; append-only histories `ORDER BY` a stable key (`seq` for snapshots,
`(time, id)` for transactions, `(timestamp, operation_id)` for cash ops). Money moves
`Decimal` ↔ `Numeric` at full precision (no quantize on reservation/locked-margin amounts).
The `storage_factory.py` `'live'` arm now routes to `SqlPortfolioStateStorage(backend,
portfolio_id)` via a lazy import (GATE-01 inertness); `'backtest'`/`'test'` and `max_snapshots`
handling are untouched; there is no `'postgresql'` arm (the live arm IS the Postgres path,
D-06). Commit `40cbe19`.

**Task 3 — six-table round-trip + isolation + projection + money tests.** 16 Postgres-arm
tests over the `pg_backend` fixture: round-trip of all six collections; the Position
**projection** equality (`to_dict()` + `id` + `leverage` + `_last_accrual_time`, never `==` —
Pitfall 3, Position has identity-only `__eq__`); field-wise `==` for Transaction (msgspec),
CashOperation / PortfolioSnapshot (@dataclass); a two-portfolio **isolation** test proving a
backend bound to A returns nothing written under B (Pitfall 1 / T-03-08); full-precision
exact-`Decimal` money for reservations + locked margin (OPS-04); and stable snapshot `seq`
ordering on tied timestamps (Pitfall 7). The suite skips cleanly without Docker. Commit
`aef70b7`.

## Verification Results

- `poetry run pytest tests/integration/storage/test_sql_portfolio_storage.py -x -q` — **16 passed** (Postgres arm, Docker present).
- `poetry run mypy itrader` — **clean** (180 source files; `SqlPortfolioStateStorage` in strict scope).
- GATE-01: backtest oracle **byte-exact** (`tests/integration/test_backtest_oracle.py` 3/3 green); the backtest factory path imports NO `sqlalchemy` (asserted) — the SQL backend stays off the hot path.
- Full suite: **1428 passed** under `filterwarnings=["error"]` (zero warnings).

## Deviations from Plan

None — plan executed as written. The three Rules 1–3 auto-fix triggers did not fire; the
implementation matched the planned interfaces, table maps, and equality contracts.

## Observations (non-blocking, out of plan scope)

- `tests/unit/portfolio/test_state_storage.py::test_factory_live_raises` still passes
  (the live arm now raises `ValueError` for a missing `portfolio_id` rather than
  `NotImplementedError` for deferral), but its docstring ("live backend is deferred to
  D-sql") is now stale since the live backend EXISTS. The test file is outside this plan's
  `files_modified`, so it was left untouched; a future cleanup could refresh the wording.

## Self-Check: PASSED
