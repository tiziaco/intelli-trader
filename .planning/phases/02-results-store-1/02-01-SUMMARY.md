---
phase: 02-results-store-1
plan: 01
subsystem: database
tags: [sqlalchemy, results-store, dataclasses, pydantic, schema, mypy-strict]

# Dependency graph
requires:
  - phase: 01-sql-spine
    provides: "SqlBackend + cross-dialect types (Uuid, json_variant, UtcIsoText); ResultsStore 4-method ABC seam; SqlSettings"
provides:
  - "ResultsNotFound(NotFoundError) raise type for missing results reads (D-16)"
  - "SqlSettings.strict_persist flag (D-17) + results_default() on-disk path (D-12)"
  - "RunMetrics / PortfolioRecord / RunRecord frozen DTOs + METRIC_NAMES (D-08/D-13)"
  - "runs / run_portfolios / run_artifacts Core Table builder (D-05/06/07/09)"
  - "Widened 5-method ResultsStore ABC with 11-metric MetricName Literal (D-08/D-13/D-15/D-18)"
affects: [results-store-serializers, sql-results-store, backtest-run-persist-hook, optuna-sweep]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "METRIC_NAMES as single source of truth for the metric column set (records.py -> models.py + base.py MetricName)"
    - "Idempotent Core-Table builder on shared MetaData (build_results_tables, reuse-if-registered guard)"
    - "MetricName Literal allow-list as the ORDER-BY SQL-injection guard at the ABC boundary"

key-files:
  created:
    - itrader/core/exceptions/results.py
    - itrader/results/records.py
    - itrader/results/models.py
  modified:
    - itrader/core/exceptions/__init__.py
    - itrader/config/sql.py
    - itrader/results/base.py
    - tests/unit/results/test_results_store_abc.py

key-decisions:
  - "results_default() returns database='output/results.db'; generic default() stays ':memory:' so other consumers/tests are untouched (D-12)"
  - "strict_persist lives on SqlSettings (store/settings), NOT on run() — the run loop stays persist-agnostic (D-17)"
  - "run_artifacts uses composite PK (run_id, portfolio_id, artifact_type) with portfolio_id nullable for aggregate-level frames (D-07)"
  - "5th method top_portfolios added (vs a target arg on top_runs) so each return type stays clean — PortfolioRecord vs RunRecord (planner ABC-widening flag resolved)"

patterns-established:
  - "Frozen DTOs: @dataclass(frozen=True, slots=True, kw_only=True) for plain mypy-strict value objects in the 4-space results layer"
  - "Core (not ORM) Table definitions registered on the injected backend.metadata, idempotent on a shared backend"

requirements-completed: [RESULT-01, RESULT-02, RESULT-03]

# Metrics
duration: ~12min
completed: 2026-06-29
---

# Phase 02 Plan 01: Results Store Contract + Schema Foundation Summary

**Interface-first wave: ResultsNotFound exception, SqlSettings strict_persist/on-disk path, three frozen result DTOs, three SQLAlchemy Core tables, and a widened 5-method ResultsStore ABC — all 4-space and mypy --strict clean.**

## Performance

- **Duration:** ~12 min
- **Completed:** 2026-06-29
- **Tasks:** 3
- **Files modified:** 7 (3 created, 4 modified)

## Accomplishments
- `ResultsNotFound(NotFoundError)` added and exported from the `core.exceptions` barrel — the D-16 missing-read raise type.
- `SqlSettings` gained a `strict_persist: bool = False` flag (D-17 dump-failure policy) and a `results_default()` classmethod returning an on-disk `output/results.db` path (D-12); generic `default()` stays `:memory:`.
- Frozen result DTOs (`RunMetrics`, `PortfolioRecord`, `RunRecord`) plus the `METRIC_NAMES` 11-name tuple — the single source of truth for the metric column set.
- `build_results_tables(metadata)` registers the `runs` / `run_portfolios` / `run_artifacts` Core tables on a shared `MetaData`, idempotent on re-call, with agreed PK shapes and Optuna-FK-ready nullable `study_id`/`trial_id`.
- The `ResultsStore` ABC is widened to 5 abstract methods with the 11-metric `MetricName` Literal, typed `RunRecord`/`PortfolioRecord` signatures, the keyed-collection `get_artifact` return, and the new `top_portfolios`; the existing ABC test was updated and passes.

## Task Commits

Each task was committed atomically:

1. **Task 1: ResultsNotFound exception + SqlSettings strict_persist/results_default** - `020f1fc` (feat)
2. **Task 2: Frozen result DTOs (RunMetrics / PortfolioRecord / RunRecord)** - `599703e` (feat)
3. **Task 3: Core tables (models.py) + widen ResultsStore ABC** - `4af07d6` (feat)

## Files Created/Modified
- `itrader/core/exceptions/results.py` (created) - `ResultsNotFound(NotFoundError)` mirroring `PortfolioNotFoundError`.
- `itrader/core/exceptions/__init__.py` (modified) - import + `__all__` entry for `ResultsNotFound`.
- `itrader/config/sql.py` (modified) - `strict_persist` field + `results_default()` classmethod.
- `itrader/results/records.py` (created) - `METRIC_NAMES` + `RunMetrics`/`PortfolioRecord`/`RunRecord` frozen DTOs.
- `itrader/results/models.py` (created) - `build_results_tables` Core-Table builder for the three tables.
- `itrader/results/base.py` (modified) - widened `MetricName` Literal + 5-method ABC surface.
- `tests/unit/results/test_results_store_abc.py` (modified) - stub updated to the widened 5-method surface.

## Decisions Made
- `results_default()` keeps the generic `default()` at `:memory:` untouched (D-12) so Phase-1 consumers and tests are unaffected.
- `strict_persist` placed on `SqlSettings` rather than `run()` (D-17).
- `run_artifacts` composite PK `(run_id, portfolio_id, artifact_type)` with nullable `portfolio_id` for aggregate frames (D-07) — SQLAlchemy honors an explicit `nullable=True` on a PK column.
- Added a dedicated `top_portfolios` method rather than overloading `top_runs` with a target argument, keeping return types clean (resolves the planner's ABC-widening flag).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- The worktree's Poetry created a fresh empty in-project `.venv` (no dependencies). Per the project's worktree-venv-shadowing convention, verification commands were run against the main checkout's interpreter (`/Users/tizianoiacovelli/Desktop/projects/intelli-trader/.venv/bin/{python,pytest,mypy}`) with `PYTHONPATH`/`MYPYPATH` pointed at the worktree root, so worktree edits are exercised rather than the editable-installed copy. No project files changed as a result.

## Verification Results
- `mypy --strict itrader` — Success: no issues found in 176 source files.
- `pytest tests/unit/results` — 2 passed.
- Schema assertions: `runs`/`run_portfolios`/`run_artifacts` build; `run_artifacts` PK `(run_id, portfolio_id, artifact_type)` with nullable `portfolio_id`; `run_portfolios.run_id` FK to `runs.run_id`; metric columns indexed; builder idempotent on re-call.
- `set(typing.get_args(MetricName)) == set(METRIC_NAMES)` (11 metrics); `ResultsStore` declares 5 abstract methods including `top_portfolios`.
- Import inertness preserved: `itrader/results/__init__.py` untouched; `models.py` (the only SQLAlchemy-importing module) is not on the package import path.

## Next Phase Readiness
- Every downstream 02-xx plan (serializers, concrete `SqlResultsStore`, the `run(persist=)` hook) now compiles against these contracts.
- `build_results_tables` is ready for `metadata.create_all(checkfirst=True)` in the concrete store; the gzip-blob encode/decode and `top_runs`/`top_portfolios` ORDER-BY column resolution remain for the implementation plan.

## Self-Check: PASSED

---
*Phase: 02-results-store-1*
*Completed: 2026-06-29*
