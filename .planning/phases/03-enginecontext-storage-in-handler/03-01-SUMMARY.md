---
phase: 03-enginecontext-storage-in-handler
plan: 01
subsystem: infra
tags: [sqlalchemy, storage, engine-context, rename, refactor, mypy, backtest-oracle, inertness]

# Dependency graph
requires:
  - phase: 02-event-bus
    provides: "EngineContext (4-field infra bundle) + compose_engine(ctx, spec) + handler-owned storage (CTX-01/02/03)"
provides:
  - "class SqlEngine (renamed from SqlBackend) — the shared Engine+MetaData SQL spine"
  - "itrader/storage/engine.py (module moved from storage/backend.py, history preserved)"
  - "from itrader.storage import SqlEngine (barrel re-export)"
  - "EngineContext.sql_engine: Optional[SqlEngine] (tightened from Optional[Any] via TYPE_CHECKING forward-ref)"
  - "unified sql_engine=/_sql_engine vocabulary across order/portfolio/strategy storage factories + PortfolioHandler + Portfolio"
affects: [phase-04, live-trading, storage, compose, portfolio_handler]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "TYPE_CHECKING forward-ref annotation to narrow a type without pulling an eager SQLAlchemy import onto the backtest path (GATE-01 inertness seam)"
    - "Hard rename with no deprecation alias (D-02) — mypy --strict + grep are the completeness nets"

key-files:
  created:
    - itrader/storage/engine.py
  modified:
    - itrader/storage/__init__.py
    - itrader/storage/migrations/env.py
    - itrader/trading_system/engine_context.py
    - itrader/trading_system/compose.py
    - itrader/order_handler/storage/storage_factory.py
    - itrader/portfolio_handler/storage/storage_factory.py
    - itrader/strategy_handler/storage/storage_factory.py
    - itrader/portfolio_handler/portfolio_handler.py
    - itrader/portfolio_handler/portfolio.py

key-decisions:
  - "D-01: full consistency sweep — backend= params -> sql_engine=, _backend fields -> _sql_engine, including the four invisible getattr string-keys"
  - "D-02: hard rename, no SqlBackend = SqlEngine alias"
  - "Renamed the portfolio-factory local sql_backend -> resolved to satisfy the _backend\\b grep-clean gate (out-of-plan but required by the acceptance criteria)"

patterns-established:
  - "Pattern 1: concrete type narrowing via TYPE_CHECKING + string forward-ref keeps the annotation unevaluated at runtime (inertness-safe)"
  - "Pattern 2: scripted token find-replace for a unique PascalCase identifier preserves indentation automatically (no tab/space normalization)"

requirements-completed: [CTX-04]

coverage:
  - id: D1
    description: "SqlBackend class renamed to SqlEngine and its module moved backend.py -> engine.py (history preserved); no SqlBackend name or alias survives"
    requirement: "CTX-04"
    verification:
      - kind: unit
        ref: "tests/unit/storage/test_sql_backend.py (5 passed)"
        status: pass
      - kind: other
        ref: "grep -rn 'SqlBackend' itrader/ tests/ -> empty"
        status: pass
    human_judgment: false
  - id: D2
    description: "EngineContext.sql_engine tightened from Optional[Any] to Optional[SqlEngine] via TYPE_CHECKING forward-ref with no eager SQLAlchemy import on the backtest path"
    requirement: "CTX-04"
    verification:
      - kind: integration
        ref: "tests/integration/test_okx_inertness.py (2 passed)"
        status: pass
      - kind: other
        ref: "poetry run mypy itrader -> Success: no issues found in 237 source files"
        status: pass
    human_judgment: false
  - id: D3
    description: "D-01 vocabulary unification — sql_engine=/_sql_engine params/fields/getattr-keys/call-sites across the enumerated scope; D-03 signal_store owner seam untouched"
    requirement: "CTX-04"
    verification:
      - kind: other
        ref: "grep -rn '\"_backend\"' itrader/ AND grep '_backend\\b' (excl _system_db_backend) -> empty"
        status: pass
      - kind: integration
        ref: "tests/integration/test_backtest_oracle.py (3 passed, 134/46189.87730727451 byte-exact)"
        status: pass
    human_judgment: false

# Metrics
duration: 11min
completed: 2026-07-09
status: complete
---

# Phase 3 Plan 01: CTX-04 SqlBackend->SqlEngine Rename Summary

**Renamed the shared SQL spine class `SqlBackend` to `SqlEngine`, moved `storage/backend.py` to `storage/engine.py` (history preserved), tightened `EngineContext.sql_engine` to `Optional[SqlEngine]` via a TYPE_CHECKING forward-ref, and unified the `backend`/`_backend` vocabulary to `sql_engine`/`_sql_engine` across ~41 files — all behavior-preserving (oracle byte-exact, inertness green, mypy --strict clean).**

## Performance

- **Duration:** 11 min
- **Started:** 2026-07-09T15:10:24Z
- **Completed:** 2026-07-09T15:21:44Z
- **Tasks:** 2
- **Files modified:** 41 (1 renamed: backend.py -> engine.py)

## Accomplishments
- `class SqlEngine` in the new `itrader/storage/engine.py` module (git mv from `backend.py`, history preserved); barrel + Alembic `migrations/env.py` repointed to `itrader.storage.engine`.
- `EngineContext.sql_engine` narrowed from `Optional[Any]` to `Optional[SqlEngine]` via a TYPE_CHECKING-guarded string forward-ref — no eager SQLAlchemy import on the backtest path (GATE-01 inertness preserved).
- Full D-01 vocabulary sweep: the three storage factories (order/portfolio/strategy), `PortfolioHandler.__init__`, and `Portfolio.__init__` now use `sql_engine=`/`_sql_engine`; the four invisible `getattr(portfolio, "_backend", None)` string-keys swept to `"_sql_engine"`; every call site (compose/order_handler/strategies_handler/live) keyword-updated.
- D-02 hard rename with zero alias: `grep -rn 'SqlBackend' itrader/ tests/` returns nothing.
- The D-03 `signal_store` owner seam in `strategies_handler.py` was left untouched (that collapse is the separate wave-2 plan 03-02).

## Task Commits

Each task was committed atomically:

1. **Task 1: CTX-04 core — rename class + move module + tighten EngineContext type** - `c9dc650b` (refactor)
2. **Task 2: D-01 consistency sweep — repoint all importers + unify backend->sql_engine vocabulary** - `85a59d7e` (refactor)

## Files Created/Modified
- `itrader/storage/engine.py` - the renamed `SqlEngine` spine (moved from backend.py; class + docstrings refreshed)
- `itrader/storage/__init__.py` - barrel re-exports `SqlEngine`
- `itrader/storage/migrations/env.py` - `NAMING_CONVENTION` import repointed to `itrader.storage.engine`
- `itrader/trading_system/engine_context.py` - TYPE_CHECKING forward-ref import + `sql_engine: Optional["SqlEngine"]`
- `itrader/{order,portfolio,strategy}_handler/storage/storage_factory.py` - `create(..., sql_engine=)` param rename
- `itrader/portfolio_handler/portfolio_handler.py`, `portfolio.py` - `_sql_engine` field + `sql_engine` param + call-site keyword
- `itrader/portfolio_handler/{metrics,transaction,position}/*.py`, `account/simulated.py` - getattr string-key `"_sql_engine"`
- `itrader/trading_system/compose.py`, `live_trading_system.py`, `order_handler/order_handler.py`, `strategy_handler/strategies_handler.py` - call-site keywords
- ~20 test files (unit + integration + e2e) - `SqlBackend`->`SqlEngine` token + import-path repoints; `backend_mod`->`engine_mod`; `test_store_live_drive.py` factory-call keyword

## Decisions Made
- Ordered the work module-move-first (Task 1) then importer-sweep (Task 2), keeping each task's gates green independently.
- Used a scripted `perl` token replace for the unique `SqlBackend` identifier (indentation-preserving), then per-file Edits for the vocabulary renames.
- Renamed the portfolio-factory local `sql_backend` -> `resolved` (matching the order factory's local name). This local was not enumerated in the plan body but was required by the `_backend\b` grep-clean acceptance criterion; treated as an in-scope consequence of the D-01 sweep, not a scope change.

## Deviations from Plan

None - plan executed exactly as written. (The `sql_backend` -> `resolved` local rename noted under Decisions is an explicit acceptance-criterion requirement of Task 2, not unplanned work.)

## Issues Encountered
- The zsh Bash shell does not word-split unquoted variables, so the first attempt to pass a file list to `perl` treated the whole newline-joined list as one filename. Resolved by piping `grep -rl` through `xargs perl -pi -e`. No source impact — caught before any commit.

## Next Phase Readiness
- Plan 03-02 (D-03 signal_store surface collapse) is unblocked and independent — the owner seam in `strategies_handler.py` was deliberately preserved here.
- The `SqlEngine` name + `itrader/storage/engine.py` path are the stable symbols downstream (Phase 4 live wiring) depends on.
- No blockers.

## Self-Check: PASSED

---
*Phase: 03-enginecontext-storage-in-handler*
*Completed: 2026-07-09*
