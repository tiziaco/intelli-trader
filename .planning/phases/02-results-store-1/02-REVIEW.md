---
phase: 02-results-store-1
reviewed: 2026-06-29T10:43:28Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - itrader/config/sql.py
  - itrader/core/exceptions/__init__.py
  - itrader/core/exceptions/results.py
  - itrader/outils/id_generator.py
  - itrader/results/__init__.py
  - itrader/results/base.py
  - itrader/results/models.py
  - itrader/results/records.py
  - itrader/results/serializers.py
  - itrader/results/sql_storage.py
  - itrader/trading_system/backtest_trading_system.py
  - itrader/trading_system/compose.py
  - itrader/trading_system/system_spec.py
  - tests/integration/test_results_persist.py
  - tests/unit/results/test_results_serializers.py
  - tests/unit/results/test_results_store_abc.py
  - tests/unit/results/test_sql_results_store.py
findings:
  critical: 1
  warning: 3
  info: 2
  total: 6
status: issues_found
---

# Phase 2: Code Review Report

**Reviewed:** 2026-06-29T10:43:28Z
**Depth:** standard
**Files Reviewed:** 18
**Status:** issues_found

## Summary

This phase adds the results store: a curated serializer layer, frozen result DTOs, the
`ResultsStore` ABC, a concrete `SqlResultsStore` on the shared SQL spine, the `SqlSettings`
backend selector, and the `persist=True` post-loop dump wired into `BacktestTradingSystem.run`.

The security-sensitive surfaces flagged in the brief hold up well:

- **SQL injection (ORDER BY):** the metric column is resolved through a `MetricName` Literal
  plus a `dict[str, Column]` allow-list (`_run_metric_columns[metric]`). An out-of-allow-list
  string raises `KeyError`, never reaches `order_by`, and `n` is parameterized via `.limit()`.
  No injection path found.
- **Credential leakage:** `curate_run_settings` is a hand-picked envelope that never touches
  `Settings`/`database_url`/`SecretStr`; `_json_scalar` str-coerces unknown leaves (a stray
  `SecretStr` would render masked). `SqlSettings.engine_url` resolves the Postgres secret
  lazily and never logs it. No leak found.
- **Money/Decimal:** `RunMetrics` is intentionally `float` (analytical store, not the money
  ledger) — consistent with the documented precedence. No Decimal defect.
- **persist=False inertness:** the dump is structurally post-loop and guarded; `results/__init__`
  does not re-export the SQL concrete; the integration suite asserts both byte-exactness and
  `sqlalchemy`-import-absence. Inertness holds.

However, the **artifact codec round-trip is not value-equal** for real frames (verified
empirically), and the persistence path has two robustness gaps (Postgres NULL-PK incompatibility
and an unguarded assembly section that bypasses the stated dump-failure policy). Details below.

## Critical Issues

### CR-01: Artifact gzip/JSON codec round-trip is lossy — datetime and integral-float columns decode to int64

**File:** `itrader/results/sql_storage.py:104-123`
**Issue:** `_encode_frame`/`_decode_frame` use `DataFrame.to_json(orient="split")` →
`pd.read_json(..., orient="split")`. `read_json` only re-converts date columns whose name matches
a fixed heuristic (`startswith("timestamp")`, `endswith("_at"/"_time")`, `== date/datetime/modified`).
The real artifact frames violate this:

- `build_trade_log` (`reporting/frames.py:24-36`) emits `entry_date` and `exit_date` — neither
  matches the heuristic, so both decode back as **`int64` epoch-millis, not datetime**.
- Integral-valued float columns (e.g. a whole-number `realised_pnl`) decode back as **`int64`**,
  silently changing dtype.

Empirically confirmed:
```
entry_date      int64          # was datetime64[ns]
exit_date       int64          # was datetime64[ns]
timestamp       datetime64[ns] # survives (name matches heuristic)
realised_pnl    int64          # was float64 (integral values)
frame_equal?    False
```
This breaks the D-15 "each frame value-equal to what `save_artifact` stored" contract on the
**default SQLite path** — `get_artifact` hands back wrong-typed columns, so any downstream
join/aggregation on trade dates operates on raw integers.

The tests do not catch this. `test_sql_results_store` uses a float-only frame with
non-integral values; `test_results_persist` asserts
`pdt.assert_frame_equal(stored, decode(encode(rebuilt)))` — comparing two passes through the
*same* lossy codec, so the asymmetry vs. the original frame is masked.

**Fix:** Persist dtype-stable. Either pin `orient="table"` (preserves schema/dtypes) or carry
the schema explicitly, e.g.:
```python
def _encode_frame(self, frame: pd.DataFrame) -> bytes:
    payload = frame.to_json(orient="table", index=True).encode("utf-8")
    ...

def _decode_frame(self, blob: bytes) -> pd.DataFrame:
    text = gzip.decompress(blob).decode("utf-8")
    return pd.read_json(io.StringIO(text), orient="table")
```
(Validate `orient="table"` against the byte-determinism requirement — it is deterministic with
`mtime=0`/fixed compresslevel.) Add a round-trip test that uses a frame with `entry_date`/
`exit_date` datetime columns AND integral-valued float columns, asserting `assert_frame_equal`
against the **original** (not a re-encoded copy).

## Warnings

### WR-01: `run_artifacts.portfolio_id` is `primary_key=True` + `nullable=True` — aggregate frame insert fails on Postgres

**File:** `itrader/results/models.py:104`
**Issue:** `Column("portfolio_id", Uuid(as_uuid=True), primary_key=True, nullable=True)` is
contradictory. SQLite tolerates NULLs in a non-INTEGER PK column, so the aggregate-level artifact
(`save_artifact(run_id, None, "equity_curve", ...)`, called at
`backtest_trading_system.py:366`) inserts fine there. But on the supported `POSTGRESQL_PSYCOPG2`
arm (`config/sql.py:41`, "the operational store"), a PK column is implicitly `NOT NULL`
regardless of `nullable=True`, so inserting `portfolio_id=None` raises a NOT NULL / integrity
error. Because `_persist_results` swallows write failures when `strict_persist=False` (the
default), this becomes **silent loss of the aggregate artifact** on Postgres while runs +
per-portfolio artifacts persist — a partial, undetectable write.

**Fix:** Model the aggregate row without a nullable PK column. Options: use a synthetic sentinel
UUID for the aggregate `portfolio_id` (keeping a real composite PK), or drop `portfolio_id` from
the PK and enforce uniqueness via a partial/expression unique index, or add a separate
`run_artifacts_aggregate` table. Add a Postgres-arm round-trip test for the `portfolio_id=None`
case so the divergence is caught.

### WR-02: `_persist_results` assembly runs outside the try/except — empty portfolios (or any builder error) abort the run, bypassing the D-17 swallow policy

**File:** `itrader/trading_system/backtest_trading_system.py:302-356` (guard at `361-370`)
**Issue:** The dump-failure policy (D-17, documented at lines 273-275) promises that a persist
failure is re-raised only when `strict_persist=True`, otherwise "logged-and-swallowed so a sweep
never loses good in-memory runs to one bad write." But only `store.save_run`/`save_artifact` are
inside the `try` (line 361). All assembly — `build_trade_log`, `build_equity_curve`,
`build_run_metrics`, `build_aggregate_equity_curve`, `curate_run_settings` — runs **before** it.
Concretely, if `get_active_portfolios()` is empty, `equity_frames` is `[]` and
`build_aggregate_equity_curve([])` reaches `pd.concat([], axis=1)` →
`ValueError: No objects to concatenate` (`serializers.py:228`), which propagates out of `run()`
even with `strict_persist=False`. Any exception raised by the metric/serializer builders has the
same effect, contradicting the stated contract.

**Fix:** Either wrap the whole assembly+write body in the same `strict_persist`-gated
try/except, or short-circuit when there are no active portfolios:
```python
active = list(self.portfolio_handler.get_active_portfolios())
if not active:
    self.logger.warning("persist requested but no active portfolios; nothing to dump")
    return
```
and move the assembly inside the guarded block so a builder failure honours `strict_persist`.

### WR-03: `SqlSettings.results_default()` uses a relative path SQLite will not create

**File:** `itrader/config/sql.py:79` (URL built at `103`)
**Issue:** `results_default()` returns `database="output/results.db"`, yielding
`sqlite+pysqlite:///output/results.db`. SQLite creates the database *file* but not the parent
directory; if `output/` does not exist, `create_engine(...)` connection raises
`OperationalError: unable to open database file` the first time the store opens a connection.
This is the documented results-store default path, so a fresh checkout/CI runner without
`output/` fails at store construction.

**Fix:** Create the parent directory before building the engine (e.g. in `SqlBackend.__init__`
for SQLite file URLs, `Path(database).parent.mkdir(parents=True, exist_ok=True)`), or document
that callers must ensure `output/` exists, or use an absolute path under a known writable root.

## Info

### IN-01: `top_runs`/`top_portfolios` do not validate `n`; negative `n` diverges across dialects

**File:** `itrader/results/sql_storage.py:201-238`
**Issue:** `n` is forwarded straight to `.limit(n)` with no bound. A negative `n` is a no-limit
on SQLite (`LIMIT -1`) but an error on Postgres, and `n=0` returns nothing — non-obvious caller
footguns.
**Fix:** Guard at the top: `if n <= 0: return []` (or raise `ValueError` for negatives).

### IN-02: `get_artifact` conflates "unknown run" with "run that has no artifacts"

**File:** `itrader/results/sql_storage.py:194-195`
**Issue:** `get_artifact` raises `ResultsNotFound` whenever zero `run_artifacts` rows match. A run
that exists in `runs` but legitimately has no artifact frames is reported identically to a truly
unknown `run_id`, which can mislead callers/diagnostics.
**Fix:** If the distinction matters, check `runs` membership first and either return `{}` for a
known-but-artifactless run or raise a distinct, clearer condition.

---

_Reviewed: 2026-06-29T10:43:28Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
