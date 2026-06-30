---
phase: 04-retention-live-write-through-2-live-path
plan: 03
subsystem: strategy_handler/storage
tags: [signal-store, cached-sql, write-through, live-path, D-04]
requires:
  - SqlSignalStorage (Phase-3 system of record, untouched)
  - InMemorySignalStore (working-set mirror)
  - SignalStore ABC
  - pg_backend testcontainers fixture
provides:
  - CachedSqlSignalStorage (live-only store-first append-only full mirror)
  - SignalStorageFactory 'live' arm wired to the wrapper
affects:
  - itrader/strategy_handler/storage/storage_factory.py ('live' arm only)
tech-stack:
  added: []
  patterns: [composition-not-inheritance, store-first-write-through, GATE-01-lazy-quarantine, RLock-single-writer]
key-files:
  created:
    - itrader/strategy_handler/storage/cached_sql_storage.py
    - tests/integration/storage/test_cached_sql_signal_storage.py
  modified:
    - itrader/strategy_handler/storage/storage_factory.py
    - .gitignore
decisions:
  - "D-04 wrapper composes the untouched SqlSignalStorage — never modifies it"
  - "D-02 scope: no purge/terminal-gate/read-through for signals (append-only full mirror)"
  - "D-01: live_trading_system.py:113 hardcode stays 'backtest' (N+4) — built + component-tested only"
  - "Pitfall 8: store-first persist-then-acknowledge; duplicate signal_id rejected up front with house ValueError"
metrics:
  tasks: 2
  files-created: 2
  files-modified: 2
  completed: 2026-06-30
---

# Phase 04 Plan 03: CachedSqlSignalStorage (live signal write-through) Summary

Live-only `CachedSqlSignalStorage` — a store-first, append-only full-mirror decorator that
composes the untouched Phase-3 `SqlSignalStorage` (system of record) with an
`InMemorySignalStore` working set, completing the `InMemory` / `Sql` / `CachedSql` triple for
the strategy/signal seam (D-04); the factory `'live'` arm now returns it behind the lazy
quarantined import.

## What Was Built

- **`CachedSqlSignalStorage`** (`itrader/strategy_handler/storage/cached_sql_storage.py`, 103 lines):
  implements the 4-method `SignalStore` ABC by forwarding. `add` is store-first then
  cache-mirror (Pitfall 8 persist-then-acknowledge); a duplicate `signal_id` is rejected up
  front against the full mirror with the house `ValueError` (inherits
  `InMemorySignalStore`'s contract) so no doomed row is persisted. `get_all` / `by_strategy` /
  `by_ticker` serve straight from the full mirror — **no purge, no terminal gate, no
  read-through** (D-02's purge gate is orders/positions, not signals). Optional idempotent
  `rehydrate()` rebuilds the mirror from the store's stable `(time, signal_id)` ORDER BY
  (Pitfall 10). Single `threading.RLock` guards the mirror (uncontended under daemon-sole-writer,
  API-thread-safe for the imminent FastAPI layer — research A4). `SqlSignalStorage` /
  `SignalRecord` are `TYPE_CHECKING`-only imports; the module is not re-exported from any
  `__init__.py` (GATE-01 inertness).

- **Factory `'live'` arm** (`storage_factory.py`): now returns
  `CachedSqlSignalStorage(SqlSignalStorage(backend))`; the wrapper import stays INSIDE the
  `'live'` branch (lazy quarantine). The `'backtest'`/`'test'` arm, the unknown-environment
  `ConfigurationError`, and `live_trading_system.py:113` (D-01 hardcode) are untouched.

- **Integration suite** (`tests/integration/storage/test_cached_sql_signal_storage.py`, 145
  lines): `test_add_store_first` (row in Postgres AND in the mirror, verified via a separate
  store), `test_filters_from_mirror`, `test_duplicate_rejected`, `test_rehydrate_full_mirror`
  (out-of-order writes restored to chronological order). Runs on the `pg_backend`
  testcontainers Postgres fixture (skips Dockerless, D-11).

## Verification

- `poetry run pytest tests/integration/storage/test_cached_sql_signal_storage.py` — **4 passed** (Docker-enabled run).
- `poetry run mypy --strict itrader/strategy_handler/storage/cached_sql_storage.py` — **clean** (A5; new module enters strict, no override).
- `poetry run mypy --strict itrader/strategy_handler/storage/storage_factory.py` — **clean**.
- Backtest quarantine probe: `SignalStorageFactory.create('backtest')` pulls no `sqlalchemy` / `cached_sql_storage` — prints `quarantine ok`.
- No-tabs check on the new module — passes (4-space).
- Regression: `test_sql_signal_storage.py` — 6 passed (composed store untouched, D-04).
- `live_trading_system.py` unchanged (D-01).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Un-ignored the mandated `cached`-named artifacts**
- **Found during:** Task 1 (committing the RED test)
- **Issue:** The over-broad `**cache**` rule in `.gitignore` (line 32) matches any path
  containing the substring "cache" — including "cached" — so both mandated artifacts
  (`cached_sql_storage.py` and `test_cached_sql_signal_storage.py`) were silently ignored and
  could not be committed.
- **Fix:** Added two `!`-negation exceptions following the existing in-file precedent (the file
  already negates `cache_registration.py`, `test_bar_cache_registration.py`,
  `test_position_cache.py` for the same reason). Scoped to this plan's two files only.
- **Files modified:** `.gitignore`
- **Commit:** 101f644

NOTE: the sibling Phase-4 plans (order/portfolio `cached_sql_storage.py` + their tests) will
hit the same `**cache**` rule and add their own negations in their worktrees.

## Known Stubs

None. The wrapper is fully wired and component-tested. Per D-01, the live composition root's
`live_trading_system.py:113` signal-store hardcode intentionally stays `'backtest'` until N+4
— this plan is "built + component-tested only" by design, not an unfinished stub.

## Threat Flags

None. The wrapper writes no SQL of its own (T-04-01 — forwards to the parameterized-Core
Phase-3 store) and never re-resolves DB creds (T-04-02 / SEC-01 — sources the injected
backend). No new trust boundary beyond the plan's threat register.

## Self-Check: PASSED

- FOUND: itrader/strategy_handler/storage/cached_sql_storage.py
- FOUND: tests/integration/storage/test_cached_sql_signal_storage.py
- FOUND: storage_factory.py 'live' arm change
- Commits: 101f644 (test+gitignore), 25e1480 (feat impl), a7050ed (feat factory)

## Commits

- `101f644` test(04-03): add failing CachedSqlSignalStorage integration suite + un-ignore artifacts
- `25e1480` feat(04-03): implement CachedSqlSignalStorage store-first mirror
- `a7050ed` feat(04-03): wire signal factory 'live' arm to CachedSqlSignalStorage

## TDD Gate Compliance

Task 1 followed RED→GREEN: `test(04-03)` (101f644, suite failed on missing module) preceded
`feat(04-03)` (25e1480, suite green). No refactor commit needed — the implementation was
minimal as written.
