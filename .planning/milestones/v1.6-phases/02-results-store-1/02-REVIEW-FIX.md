---
phase: 02-results-store-1
fixed_at: 2026-06-29T00:00:00Z
review_path: .planning/phases/02-results-store-1/02-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
---

# Phase 02: Code Review Fix Report

**Fixed at:** 2026-06-29
**Source review:** .planning/phases/02-results-store-1/02-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (fix_scope: all — Critical + Warning + Info)
- Fixed: 6
- Skipped: 0

**Verification gate (run in the isolated worktree against the main checkout `.venv`):**
- `pytest tests/unit/results tests/integration` → 70 passed (includes the byte-exact
  SMA_MACD oracle 134 / 46189.87730727451 and the GATE-01 SQL-import-inertness subprocess test)
- `mypy itrader` → Success: no issues found in 178 source files

## Fixed Issues

### CR-01: Artifact gzip/JSON codec round-trip is lossy

**Files modified:** `itrader/results/sql_storage.py`, `tests/unit/results/test_sql_results_store.py`
**Commit:** 85eacd4
**Applied fix:** Switched the frame codec from `to_json(orient="split")` /
`read_json(orient="split")` to `orient="table"` (pandas Table Schema), which embeds each
column's dtype so `read_json` restores it exactly — `entry_date`/`exit_date` stay
`datetime64[ns]` and integral-valued float columns stay `float64` (previously both collapsed
to `int64`). Verified empirically that `orient="table"` is still byte-deterministic with
`mtime=0`/fixed `compresslevel` and round-trips the real trade-log, equity-curve, aggregate
(`timestamp`-indexed), simple-float, and empty-frame shapes value-equal. Added
`test_codec_roundtrip_preserves_datetime_and_integral_float_dtypes`, which asserts
`assert_frame_equal` against the **ORIGINAL** frame (datetime + integral-float columns) — not
a re-encoded copy — closing the gap the old same-codec comparison masked.

### WR-01: `run_artifacts.portfolio_id` nullable PK fails on Postgres

**Files modified:** `itrader/results/models.py`, `itrader/results/sql_storage.py`, `tests/unit/results/test_sql_results_store.py`
**Commit:** 54f72d8
**Applied fix:** Removed `nullable=True` from the composite-PK `portfolio_id` column (a
nullable PK column is implicitly `NOT NULL` on Postgres and rejects a `NULL` insert). The
aggregate-level artifact (`portfolio_id=None`) is now stored under an all-zeros sentinel UUID
(`uuid.UUID(int=0)` — a UUIDv7 can never be all-zeros, so no collision with a real portfolio),
mapped back to `None` on read via a new `_key_portfolio_id` helper. The `(None, artifact_type)`
caller key is preserved. Added `test_aggregate_artifact_stored_portfolio_id_is_not_null`
asserting the persisted PK column is the sentinel (never NULL) while `get_artifact` still keys
on `None`. (A live Postgres-arm round-trip test was not added — no Postgres in the unit/integration
gate — but the NOT-NULL sentinel write is the exact property that makes the insert Postgres-safe.)

### WR-02: Persist assembly runs outside the try/except, bypassing the D-17 swallow policy

**Files modified:** `itrader/trading_system/backtest_trading_system.py`
**Commit:** 9c6c31c
**Applied fix:** Added a short-circuit `active = list(get_active_portfolios()); if not active:
warn + return` before any assembly (no active portfolios → `build_aggregate_equity_curve([])`
→ `pd.concat([], axis=1)` `ValueError`, which previously propagated out of `run()` even with
`strict_persist=False`). Moved the ENTIRE assembly (`build_trade_log` / `build_equity_curve` /
`build_run_metrics` / `build_aggregate_equity_curve` / `curate_run_settings`) inside the
existing `strict_persist`-gated `try/except` so ANY builder failure — not just a store write —
honours D-17 (re-raise only when `strict_persist=True`, else log-and-swallow). The `store is
None` D-03 guard stays outside (a wiring `ConfigurationError`, always raised). The persist
integration suite (4 tests) and the byte-exact oracle stay green.

### WR-03: `results_default()` relative SQLite path the engine cannot open

**Files modified:** `itrader/config/sql.py`, `itrader/storage/backend.py`, `tests/unit/storage/test_sql_backend.py`
**Commit:** dc241c5
**Applied fix:** Added `SqlSettings.ensure_local_storage()` — for a file-backed SQLite arm
(not `:memory:`, not Postgres) it `mkdir(parents=True, exist_ok=True)` on the database path's
parent. `SqlBackend.__init__` calls it before `create_engine`, so the documented
`output/results.db` default self-provisions its `output/` directory instead of raising
`OperationalError: unable to open database file` on first connect. Added
`test_backend_creates_missing_sqlite_parent_dir` (constructs a backend on a non-existent tmp
subdir, asserts the dir is created and a real `SELECT 1` connection opens).

### IN-01: `top_runs`/`top_portfolios` do not validate `n`

**Files modified:** `itrader/results/sql_storage.py`, `tests/unit/results/test_sql_results_store.py`
**Commit:** 048335d
**Applied fix:** Added `if n <= 0: return []` at the top of both ranking methods, removing the
cross-dialect footgun (negative `n` is `LIMIT -1`/no-limit on SQLite but an error on Postgres;
`n == 0` selects nothing). Added `test_top_runs_non_positive_n_returns_empty`.

### IN-02: `get_artifact` conflates unknown run with artifactless run

**Files modified:** `itrader/results/sql_storage.py`, `tests/unit/results/test_sql_results_store.py`
**Commit:** 048335d
**Applied fix:** When there are no `run_artifacts` rows, `get_artifact` now checks `runs`
membership: a known run with zero artifacts returns `{}`; a genuinely unknown `run_id` still
raises `ResultsNotFound` (D-16). Added
`test_get_artifact_known_run_without_artifacts_returns_empty` (and confirmed the unknown-run
case still raises). Committed together with IN-01 because both edits interleave in the same two
files and per-file commit granularity cannot split them.

---

_Fixed: 2026-06-29_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
