---
phase: 02-results-store-1
plan: 03
subsystem: results-store
tags: [sql, results-store, persistence, sqlite, ranking, gzip]
requires:
  - "itrader.storage.SqlBackend (spine — engine + metadata)"
  - "itrader.results.models.build_results_tables (runs/run_portfolios/run_artifacts)"
  - "itrader.results.records (RunRecord/PortfolioRecord/RunMetrics/METRIC_NAMES)"
  - "itrader.results.base.ResultsStore (ABC, MetricName Literal)"
  - "itrader.core.exceptions.ResultsNotFound"
provides:
  - "itrader.results.sql_storage.SqlResultsStore (concrete ResultsStore on the spine)"
  - "byte-deterministic gzip frame codec (RESULT-04)"
  - "injection-safe top_runs/top_portfolios ranking (allow-list Column map)"
affects:
  - "itrader/results/__init__.py (barrel now exports records; SqlResultsStore stays SQL-quarantined)"
tech-stack:
  added: []
  patterns:
    - "Composition-not-inheritance store over SqlBackend (mirrors sql_store.py SqlHandler)"
    - "MetricName->Column allow-list map as the ORDER BY SQL-injection guard (T-02-01)"
    - "gzip mtime=0 + fixed compresslevel for byte-determinism (D-10)"
key-files:
  created:
    - "itrader/results/sql_storage.py"
    - "tests/unit/results/test_sql_results_store.py"
  modified:
    - "itrader/results/__init__.py"
decisions:
  - "Tasks 1/2 split the concrete store: Task 1 stubs the three read methods with NotImplementedError so the ABC is concrete + testable; Task 2 replaces the stubs. Atomic per-task commits with working verifications."
metrics:
  duration: ~14m
  completed: 2026-06-29
  tasks: 3
  files: 3
---

# Phase 2 Plan 03: SqlResultsStore Summary

Concrete `SqlResultsStore(ResultsStore)` on the shared SQL spine — idempotent schema creation,
byte-deterministic gzip frame codec, atomic `save_run`, separate `save_artifact`, keyed-collection
`get_artifact` (raising `ResultsNotFound` on miss), and injection-safe `top_runs`/`top_portfolios`
ranking — validated by an in-process SQLite round-trip + determinism + ranking suite (RESULT-02/03/04).

## What Was Built

- **`itrader/results/sql_storage.py` (260 lines)** — `SqlResultsStore` composes a `SqlBackend` by
  reference (D-06), registers the three results tables via `build_results_tables`, and calls
  `metadata.create_all(checkfirst=True)` (D-12 idempotent, ephemeral, no Alembic). `dispose()`
  delegates to `backend.dispose()` (WR-03).
  - **Codec (D-10):** `_encode_frame` uses `gzip.GzipFile(..., compresslevel=6, mtime=0)` over
    `frame.to_json(orient="split")`; `_decode_frame` reverses it via `pd.read_json(io.StringIO(...))`.
    Pinning BOTH `mtime=0` and a fixed compresslevel is the byte-determinism requirement (RESULT-04).
  - **Writes (D-13):** `save_run` persists the `runs` row + all `run_portfolios` rows in ONE
    `engine.begin()` transaction; `save_artifact` writes one gzip-blob row in a separate transaction.
    All inserts are parameterized Core inserts against the constant table objects — no string SQL.
  - **Reads:** `get_artifact` returns `{(portfolio_id, artifact_type): DataFrame}` (decoding each
    blob), raising `ResultsNotFound(run_id)` when the result set is empty (D-15/D-16).
  - **Ranking (D-18):** `top_runs`/`top_portfolios` resolve the ORDER BY column through a
    `MetricName -> Column` allow-list map (`self._run_metric_columns` / `self._portfolio_metric_columns`),
    never an f-string (T-02-01). DESC is best-first for every metric including `max_drawdown` (stored
    NEGATIVE, so closest-to-zero = largest-signed = least-bad); tiebreak `run_id` ASC (then
    `portfolio_id` ASC for portfolios). Empty/short tables return `[]`. A `_METRIC_DIRECTION` map
    documents the negative-drawdown direction invariant.
- **`itrader/results/__init__.py`** — barrel now exports `ResultsStore` + records (`RunRecord`,
  `PortfolioRecord`, `RunMetrics`, `METRIC_NAMES`) but deliberately NOT `SqlResultsStore` (importing
  it pulls SQLAlchemy), keeping the package import SQL-free (GATE-01 inertness).
- **`tests/unit/results/test_sql_results_store.py` (11 tests, package-less dir)** — in-process SQLite
  (`:memory:`) fixture; covers codec round-trip + byte-determinism, atomic `save_run`, keyed-collection
  `get_artifact` (incl. `portfolio_id=None` aggregate key), `ResultsNotFound`, empty-safe ranking,
  `top_runs` ordering + `run_id` ASC tiebreak + `max_drawdown` DESC direction, and `top_portfolios`
  ordering.

## Verification

- `pytest tests/unit/results` → 13 passed (11 new + 2 ABC), warning-clean under `filterwarnings=["error"]`.
- `mypy --strict itrader` → clean (177 source files).
- GATE-01 inertness: `import itrader.results` does NOT pull `sqlalchemy`.
- f-string ORDER BY grep gate → clean (no `order_by(f"` / `text(f"`).

Note: tests were run with the main-checkout venv's interpreter + `PYTHONPATH=<worktree>` (the worktree's
fresh Poetry venv has no deps installed; this is the documented `.venv`-shadowing workaround, MEMORY.md).

## Deviations from Plan

### Task structuring (not a code deviation)

**1. Read-method stubs in Task 1 so the concrete ABC is instantiable mid-plan.**
- **Found during:** Task 1 — a `ResultsStore` subclass cannot be instantiated until ALL five abstract
  methods are implemented, but Task 1's scope is only `__init__`/codec/`save_run`/`save_artifact`.
- **Resolution:** Task 1 implements its scoped methods and stubs `get_artifact`/`top_runs`/`top_portfolios`
  with `raise NotImplementedError`; Task 2 replaces the stubs with the real implementations. This keeps
  each task an atomic commit with a passing verification, exactly matching the plan's per-task verify
  commands. No behavioral or API deviation from the plan.

No auto-fixed bugs (Rules 1-3) and no architectural changes (Rule 4) were required — the plan executed
as written.

## Known Stubs

None. All methods are fully implemented and exercised by the test suite.

## Self-Check: PASSED

- FOUND: itrader/results/sql_storage.py
- FOUND: tests/unit/results/test_sql_results_store.py
- FOUND: itrader/results/__init__.py (modified)
- FOUND commit: 71bc0cf (feat — composition/codec/save)
- FOUND commit: 953e3a0 (feat — reads/ranking/barrel)
- FOUND commit: bf915b2 (test — ranking suite)
