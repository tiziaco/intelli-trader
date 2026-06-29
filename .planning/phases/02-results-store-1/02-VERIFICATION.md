---
phase: 02-results-store-1
verified: 2026-06-29T00:00:00Z
status: human_needed
score: 4/4
overrides_applied: 0
human_verification:
  - test: "Run the W1 benchmark (`make backtest` or equivalent timing probe) and confirm wall-clock time is not worse than the v1.5 frozen baseline of 15.7 s"
    expected: "Wall-clock time within noise of 15.7 s — no regression from Phase 2's post-loop dump (the hot loop is structurally unchanged; `persist=False` adds only one un-entered `if persist:` branch)"
    why_human: "Timing benchmarks cannot be verified by static analysis or import tests alone; a thermal-clean machine run is the agreed measurement discipline (per MEMORY.md v1.5 gate thermal-drift note and GATE-01 formal binding to Phase 4)"
---

# Phase 02: Results Store (#1) — Verification Report

**Phase Goal:** Results Store (#1) — every backtest/optimization run persisted on ephemeral SQLite (`runs` Float metrics + JSON settings, `run_artifacts` JSON/gzip text frame, cross-run query, Optuna-FK-ready); validates the SQL spine "oracle-dark" (default backtest path stays byte-exact and SQL-import-inert).
**Verified:** 2026-06-29
**Status:** human_needed (one W1/W2 benchmark item; all code truths VERIFIED)
**Re-verification:** No — initial verification
**Requirements covered:** RESULT-01, RESULT-02, RESULT-03, RESULT-04

---

## Goal Achievement

### Observable Truths (from ROADMAP.md Success Criteria)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| SC-1 | After a backtest run, a `runs` row (Float metrics + JSON settings, Optuna-FK nullable study/trial ids) and a `run_artifacts` row (JSON/gzip'd-text) are persisted and the artifact round-trips to an equal DataFrame | ✓ VERIFIED | `test_persist_end_to_end_writes_runs_portfolios_and_artifacts` passes; `save_run` + `save_artifact` confirmed; gzip codec round-trips with `orient="table"` (CR-01 fix: dtype-stable) |
| SC-2 | Cross-run query surface (`top_runs` / `top_portfolios` top-N by metric) works; schema carries nullable Optuna FK columns (no sweep loop built) | ✓ VERIFIED | `top_runs("sharpe", 2)` verified programmatically; `study_id`/`trial_id` confirmed `nullable=True` on `runs` table; `test_top_runs_orders_best_first` + `test_top_runs_max_drawdown_direction` pass |
| SC-3 | SQLite default via `create_all()` (ephemeral, no Alembic); in-process SQLite DB round-trip passes deterministically; same frame encodes to identical bytes | ✓ VERIFIED | `SqlResultsStore.__init__` calls `backend.metadata.create_all(checkfirst=True)`; `_encode_frame` pins `mtime=0` + `compresslevel=6`; `test_codec_byte_determinism` + `test_codec_roundtrip_preserves_datetime_and_integral_float_dtypes` pass; 33 unit tests green |
| SC-4 | Oracle byte-exact 134 / `46189.87730727451` under `persist=False`; `mypy --strict` clean; `filterwarnings=["error"]` green; batch dump is post-loop (backtest hot loop touches no SQL) | ✓ VERIFIED | `test_backtest_oracle.py` 3/3 pass; `test_oracle_byte_exact_under_persist_false` passes; `test_backtest_module_import_is_sql_import_inert` subprocess test passes; `mypy itrader` clean (200 source files); 1409 tests pass warning-clean; `if persist:` guard confirmed after `self.runner.run()` |

**Score:** 4/4 ROADMAP success criteria verified

**Note on SC-4 W1/W2 benchmark:** The structural evidence (SQL-free hot loop, import inertness proven by subprocess test) guarantees no hot-path regression. The formal GATE-01 timing benchmark (15.7 s / 152.8 MB baseline) is bound to Phase 4 per REQUIREMENTS.md; Phase 2 carries it as a recurring SC. See Human Verification section.

---

### Observable Truths (from Plan must_haves — all 4 plans)

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `ResultsNotFound` is a `NotFoundError` subclass importable from `itrader.core.exceptions` (D-16) | ✓ VERIFIED | File exists at `itrader/core/exceptions/results.py`; `__init__.py` barrel exports it in `__all__`; programmatic import confirmed |
| 2 | `SqlSettings` carries `strict_persist: bool = False` field and `results_default()` classmethod returning `database="output/results.db"` (D-12, D-17) | ✓ VERIFIED | `SqlSettings().strict_persist is False`; `SqlSettings.results_default().database == "output/results.db"`; `SqlSettings.default().database == ":memory:"` — programmatically confirmed |
| 3 | `RunMetrics` / `PortfolioRecord` / `RunRecord` frozen DTOs with the 11 Float metric fields; `METRIC_NAMES` tuple with 11 names (D-08, D-13) | ✓ VERIFIED | `records.py` confirms all 3 DTOs are `@dataclass(frozen=True, slots=True, kw_only=True)`; `len(METRIC_NAMES) == 11`; `RunMetrics` field set equals `set(METRIC_NAMES)` |
| 4 | `runs` / `run_portfolios` / `run_artifacts` Core tables declared with agreed PK shapes and Optuna-FK-ready nullable `study_id`/`trial_id` (D-05/06/07/09) | ✓ VERIFIED | `build_results_tables(MetaData())` returns `{'runs','run_portfolios','run_artifacts'}`; `study_id`/`trial_id` nullable confirmed; `run_portfolios.run_id` FKs to `runs.run_id`; `run_artifacts` PK is `(run_id, portfolio_id, artifact_type)` with all NOT NULL (WR-01 fix: sentinel UUID for aggregate rows) |
| 5 | `ResultsStore` ABC widened to 5 abstract methods; `MetricName` Literal covers all 11 rankable metrics (D-08, D-13, D-15, D-18) | ✓ VERIFIED | `ResultsStore` has `save_run`, `save_artifact`, `get_artifact`, `top_runs`, `top_portfolios`; `set(typing.get_args(MetricName)) == set(METRIC_NAMES)` confirmed |
| 6 | Curated run-settings serializer hand-picks a credential-free envelope; per-strategy params serializer reads `strategy.to_dict()` (D-11, T-02-03) | ✓ VERIFIED | `curate_run_settings` hand-picks 14 keys; grep confirms no `database_url`/`SecretStr` read; `serializers.py` imports only stdlib/pandas/`itrader.reporting`/`itrader.results.records`/`itrader.outils` — zero handler imports |
| 7 | `build_run_metrics` computes all 11 metrics by REUSING `reporting/metrics.py` formulas; derived `total_return`/`calmar` from helpers (D-08) | ✓ VERIFIED | `serializers.py` imports `sharpe, sortino, cagr, calmar, max_drawdown, profit_factor, win_rate, total_return` from `itrader.reporting.metrics`; no reimplementation; 16 serializer unit tests pass |
| 8 | `build_aggregate_equity_curve` outer-joins on union timestamp index, forward-fills, sums — mixed-timeframe-safe (D-14) | ✓ VERIFIED | Implementation uses `pd.concat(axis=1, join="outer").ffill().bfill().sum(axis=1)`; test for 1d+1h pair with no NaN passes |
| 9 | `SqlResultsStore` composes an injected `SqlBackend`; `create_all(checkfirst=True)` is idempotent (D-12) | ✓ VERIFIED | `__init__` stores `self.backend`, calls `build_results_tables(backend.metadata)`, `backend.metadata.create_all(self.engine, checkfirst=True)` |
| 10 | `save_run` writes `runs` row AND all `run_portfolios` rows in ONE `engine.begin()` transaction; `save_artifact` writes separately (D-13) | ✓ VERIFIED | Single `with self.engine.begin() as connection:` block executes both inserts; `test_save_run_atomic_persists_run_and_portfolios` confirms 1 `runs` row + 2 `run_portfolios` rows atomically |
| 11 | Frame artifacts byte-deterministic with `orient="table"`, `mtime=0`, fixed `compresslevel`; round-trip dtype-stable (CR-01 fix: not `orient="split"`) (D-10, RESULT-04) | ✓ VERIFIED | `_encode_frame` uses `orient="table"`; `_decode_frame` uses `pd.read_json(..., orient="table")`; `test_codec_roundtrip_preserves_datetime_and_integral_float_dtypes` asserts datetime + integral-float columns survive round-trip against the ORIGINAL frame |
| 12 | `get_artifact(run_id)` returns `{(portfolio_id, artifact_type): DataFrame}`; unknown `run_id` raises `ResultsNotFound`; known run without artifacts returns `{}`; `top_runs` empty-safe (D-15, D-16, IN-02 fix) | ✓ VERIFIED | `test_get_artifact_unknown_run_raises`, `test_get_artifact_known_run_without_artifacts_returns_empty`, `test_top_runs_empty_table_returns_empty` all pass |
| 13 | `top_runs`/`top_portfolios` resolve `ORDER BY` through `MetricName→Column` allow-list map (never f-string); `max_drawdown` ranks DESC; `n<=0` returns `[]` (D-18, IN-01 fix, T-02-01) | ✓ VERIFIED | `grep -nE "order_by\(f\"\|text\(f\"" sql_storage.py` returns no matches; `_run_metric_columns` / `_portfolio_metric_columns` map confirmed; `test_top_runs_max_drawdown_direction` + `test_top_runs_non_positive_n_returns_empty` pass |
| 14 | `itrader.results` package import does NOT pull `SqlResultsStore`/SQLAlchemy (GATE-01 import inertness) | ✓ VERIFIED | `import itrader.results; assert 'sqlalchemy' not in sys.modules` confirmed; `SqlResultsStore` absent from `itrader/results/__init__.py` |
| 15 | `run(persist: bool = False)` performs POST-LOOP dump only when `persist=True`; hot loop touches no SQL (D-01, D-04) | ✓ VERIFIED | `if persist:` guard follows `self.runner.run()`; `SqlResultsStore`/`SqlBackend` NOT imported at module top; `test_backtest_module_import_is_sql_import_inert` subprocess test passes |
| 16 | `results_store` injected ONCE at composition: `SystemSpec` → `compose_engine(results_store=)` → `Engine.results_store` (D-02, D-19) | ✓ VERIFIED | `SystemSpec.__dataclass_fields__` contains `results_store`; `Engine.__dataclass_fields__` contains `results_store`; `compose_engine` signature contains `results_store`; `build_backtest_system` reads `getattr(spec, "results_store", None)` and passes to `compose_engine` |
| 17 | `run(persist=True)` with no store injected raises `ConfigurationError` (D-03) | ✓ VERIFIED | `_persist_results` checks `store = self.engine.results_store; if store is None: raise ConfigurationError(...)`; `test_persist_true_without_store_raises_configuration_error` passes |
| 18 | `run_id` is a single-UUIDv7 `idgen.generate_run_id()` value | ✓ VERIFIED | `idgen.generate_run_id()` method exists, returns `uuid.UUID`, uses `self._uuid7()` |
| 19 | Dump failure honors `strict_persist`: entire assembly+write body in `try/except`; `strict_persist=False` logs-and-swallows; `True` re-raises; empty-portfolio short-circuit (D-17, WR-02 fix) | ✓ VERIFIED | Lines 303–385 of `backtest_trading_system.py` confirm: empty-portfolio short-circuit before `try`; `try:` covers entire assembly + store writes; `except Exception: if getattr(store, "_strict_persist", False): raise` |

**Score:** 19/19 plan must-haves verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/core/exceptions/results.py` | `ResultsNotFound(NotFoundError)` | ✓ VERIFIED | 23 lines; substantive implementation mirroring `PortfolioNotFoundError` |
| `itrader/core/exceptions/__init__.py` | Barrel export of `ResultsNotFound` | ✓ VERIFIED | `from .results import ResultsNotFound` + `__all__` entry present |
| `itrader/config/sql.py` | `strict_persist` field + `results_default()` + `ensure_local_storage()` | ✓ VERIFIED | All three additions confirmed; `results_default()` returns `database="output/results.db"` |
| `itrader/results/records.py` | `RunMetrics`, `PortfolioRecord`, `RunRecord`, `METRIC_NAMES` | ✓ VERIFIED | 77 lines; all 4 frozen DTOs + tuple with 11 names |
| `itrader/results/models.py` | `build_results_tables` Core Table builder | ✓ VERIFIED | 113 lines; idempotent builder; all 3 tables with correct PK shapes |
| `itrader/results/base.py` | Widened `ResultsStore` ABC + `MetricName` Literal | ✓ VERIFIED | 164 lines; 5 abstract methods; 11-name `Literal` |
| `itrader/results/serializers.py` | 5 serializer functions (curate settings/params, build metrics/curve, annual_periods) | ✓ VERIFIED | 256 lines; all 5 functions implemented; purity contract holds |
| `itrader/results/sql_storage.py` | `class SqlResultsStore(ResultsStore)` | ✓ VERIFIED | 320 lines; all 5 ABC methods + codec + dispose |
| `itrader/results/__init__.py` | Barrel exports ABC + records; excludes `SqlResultsStore` | ✓ VERIFIED | Exports `ResultsStore`, `RunRecord`, `PortfolioRecord`, `RunMetrics`, `METRIC_NAMES`; `SqlResultsStore` absent |
| `itrader/trading_system/system_spec.py` | `results_store: Any = None` field | ✓ VERIFIED | Line 111 confirmed |
| `itrader/trading_system/compose.py` | `Engine.results_store` + `compose_engine(results_store=)` | ✓ VERIFIED | Lines 113, 126, 261 confirmed |
| `itrader/trading_system/backtest_trading_system.py` | `run(persist=)` + `_persist_results` + `build_backtest_system` store injection | ✓ VERIFIED | `run` signature line 196–198; `_persist_results` line 259; `build_backtest_system` getattr+forward at line 436, 446 |
| `itrader/outils/id_generator.py` | `generate_run_id() -> uuid.UUID` | ✓ VERIFIED | Lines 54–60; TAB-indented; returns `self._uuid7()` |
| `tests/unit/results/test_results_store_abc.py` | Updated 5-method ABC test | ✓ VERIFIED | 2 tests pass |
| `tests/unit/results/test_results_serializers.py` | Full serializer unit suite | ✓ VERIFIED | 16 tests pass |
| `tests/unit/results/test_sql_results_store.py` | In-process SQLite round-trip + determinism + ranking | ✓ VERIFIED | 15 tests pass; no `__init__.py` sibling |
| `tests/integration/test_results_persist.py` | E2E persist + oracle inertness + import inertness | ✓ VERIFIED | 4 tests pass (2018–2021 window) |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `itrader/results/models.py` | `itrader/storage/types.py` | `Uuid` / `json_variant` column types | ✓ WIRED | `from itrader.storage import Uuid, json_variant` confirmed; used in all 3 tables |
| `itrader/results/base.py` | `itrader/results/records.py` | `RunRecord` type in `save_run` signature | ✓ WIRED | `from itrader.results.records import PortfolioRecord, RunRecord` confirmed |
| `itrader/results/serializers.py` | `itrader/reporting/metrics.py` | reuse sharpe/sortino/cagr/max_drawdown/calmar/total_return/profit_factor/win_rate | ✓ WIRED | `from itrader.reporting.metrics import PERIODS, cagr, calmar, ...` confirmed |
| `itrader/results/serializers.py` | `itrader/results/records.py` | `build_run_metrics` returns `RunMetrics` | ✓ WIRED | `from itrader.results.records import RunMetrics` confirmed; `build_run_metrics` returns `RunMetrics(...)` |
| `itrader/results/sql_storage.py` | `itrader/storage/backend.py` | composed `SqlBackend` | ✓ WIRED | `from itrader.storage import SqlBackend`; `self.backend = backend`; `self.engine = backend.engine` |
| `itrader/results/sql_storage.py` | `itrader/results/models.py` | `build_results_tables` on `backend.metadata` | ✓ WIRED | `from itrader.results.models import build_results_tables`; called in `__init__` |
| `itrader/results/sql_storage.py` | `itrader/core/exceptions/results.py` | `raise ResultsNotFound` on missing read | ✓ WIRED | `from itrader.core.exceptions import ResultsNotFound`; raised in `get_artifact` |
| `itrader/trading_system/backtest_trading_system.py` | `itrader/results/sql_storage.py` | `SqlResultsStore` forwarded via `build_backtest_system` | ✓ WIRED | `getattr(spec, "results_store", None)` forwarded into `compose_engine(results_store=...)`; `store = self.engine.results_store` in `_persist_results` |
| `itrader/trading_system/backtest_trading_system.py` | `itrader/results/serializers.py` | `build_run_metrics`/`curate_run_settings`/`build_aggregate_equity_curve` in dump hook | ✓ WIRED | `from itrader.results.serializers import annual_periods, build_aggregate_equity_curve, build_run_metrics, curate_portfolio_params, curate_run_settings`; all 5 called in `_persist_results` |
| `itrader/trading_system/compose.py` | `itrader/results/base.py` | `Engine.results_store: Optional[ResultsStore]` | ✓ WIRED | `from itrader.results import ResultsStore`; used in `Engine` dataclass field annotation |

---

### Data-Flow Trace (Level 4)

Not applicable — Phase 2 delivers persistence infrastructure, not UI/display components. All dynamic data flow is verified through DB round-trip tests (values written and read back are asserted equal).

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `ResultsNotFound` importable + `SqlSettings` checks | `python -c "from itrader.core.exceptions import ResultsNotFound; ..."` | All assertions pass | ✓ PASS |
| MetricName = 11 metrics, 5 ABC methods, 3 tables build | `python -c "import typing; from itrader.results.base import MetricName..."` | Methods: 5; set equal | ✓ PASS |
| `itrader.results` import is SQL-inert | `python -c "import itrader.results, sys; assert 'sqlalchemy' not in sys.modules"` | `PASS` | ✓ PASS |
| No f-string ORDER BY in `sql_storage.py` | `grep -nE "order_by\(f\"\|text\(f\"" sql_storage.py` | No matches | ✓ PASS |
| `results_store` threaded through composition chain | `python -c "from itrader.trading_system.compose import Engine, compose_engine..."` | `PASS` | ✓ PASS |
| `generate_run_id()` returns `uuid.UUID` | `python -c "from itrader import idgen; assert isinstance(idgen.generate_run_id(), uuid.UUID)"` | `PASS` | ✓ PASS |
| Backtest module import is SQL-inert (GATE-01) | `python -c "import itrader.trading_system.backtest_trading_system, sys; assert 'sqlalchemy' not in sys.modules"` | `PASS` | ✓ PASS |
| Byte-determinism + CR-01 dtype-stable codec | `python -c "...encode twice == encode twice; orient='table' round-trip with datetime+float64"` | `PASS` | ✓ PASS |
| Optuna FK + run_portfolios FK + run_artifacts PK | `python -c "...nullable study_id/trial_id; FK to runs.run_id; PK=(run_id,portfolio_id,artifact_type) NOT NULL"` | `PASS` | ✓ PASS |
| Cross-run query surface (`top_runs`) | `python -c "...top_runs('sharpe', 2) returns best-first"` | `PASS` | ✓ PASS |
| Unit tests (33) | `pytest tests/unit/results -q` | 33 passed | ✓ PASS |
| Integration persist tests (4) | `pytest tests/integration/test_results_persist.py -q` | 4 passed | ✓ PASS |
| Oracle byte-exact test | `pytest tests/integration/test_backtest_oracle.py -q` | 3 passed | ✓ PASS |
| Full test suite | `pytest tests/ -q` | 1409 passed | ✓ PASS |
| mypy --strict | `mypy itrader` | Success: no issues found in 200 source files | ✓ PASS |

---

### Probe Execution

No phase-declared probes. The GATE-01 inertness assertion is covered by `test_backtest_module_import_is_sql_import_inert` in `tests/integration/test_results_persist.py` (subprocess-based, exit-code 0 confirmed).

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| RESULT-01 | 02-01, 02-02, 02-04 | Every backtest run persists a `runs` row (summary metrics as Float + JSON settings) | ✓ SATISFIED | `save_run` writes runs + run_portfolios atomically; `test_persist_end_to_end_writes_runs_portfolios_and_artifacts` passes end-to-end on real SMA_MACD run |
| RESULT-02 | 02-01, 02-03 | Each run's equity-curve/trade-log frame persists as `run_artifacts` JSON/gzip'd-text; round-trips to pandas DataFrame | ✓ SATISFIED | `save_artifact` + `get_artifact` round-trip value-equal; `test_codec_roundtrip_preserves_datetime_and_integral_float_dtypes` asserts dtype-stable (CR-01 fix applied) |
| RESULT-03 | 02-01, 02-03 | SQLite default; cross-run query surface (`top_runs`/`top_portfolios`); Optuna-FK-ready schema | ✓ SATISFIED | `create_all(checkfirst=True)` on SQLite; 11-metric ranking; `study_id`/`trial_id` nullable confirmed |
| RESULT-04 | 02-03 | DB round-trip tests on in-process SQLite (write → read → assert equality) | ✓ SATISFIED | 15 unit tests in `test_sql_results_store.py` cover codec, round-trip, atomic save, ranking, ResultsNotFound, IN-01/IN-02 fixes; byte-determinism proven |

---

### Anti-Patterns Found

No TBD, FIXME, or XXX markers in any Phase 2 modified file. No placeholder implementations — all 5 `ResultsStore` ABC methods are fully implemented in `SqlResultsStore`. No hardcoded empty returns in the critical path.

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none found) | — | — | — | — |

---

### Human Verification Required

#### 1. W1/W2 Benchmark — Confirm No Performance Regression

**Test:** Run the W1 benchmark (e.g. `make backtest` or the timing probe used in v1.5) on a thermally stable machine and record the wall-clock time for the default `persist=False` path.

**Expected:** Wall-clock time within noise range of the v1.5 frozen baseline of **15.7 s** (152.8 MB). The Phase 2 hot loop is structurally unchanged — the only new code on the default path is a single `if persist:` branch that is never entered, plus a module-level `from itrader.results.serializers import ...` import which is pure-Python/pandas (no SQL). The subprocess import-inertness test (`test_backtest_module_import_is_sql_import_inert`) confirms no SQLAlchemy is pulled on the backtest import path.

**Why human:** Timing benchmarks cannot be verified by static analysis or import tests — a thermal-clean machine run is the agreed measurement discipline per MEMORY.md (`v1.5-perf-gateb-thermal-drift.md`). GATE-01 is formally bound to Phase 4 in REQUIREMENTS.md; Phase 2 carries it as a recurring success criterion only.

**Structural confidence:** HIGH. The hot-loop path is byte-identical to v1.5 (oracle 134 / `46189.87730727451` confirmed). No SQL on the backtest import path (subprocess test confirmed). The risk of a W1 regression from this phase is structurally zero.

---

### Gaps Summary

No code gaps. All must-have truths are VERIFIED, all artifacts are substantive and wired, all tests pass (1409/1409), all four requirements (RESULT-01/02/03/04) are satisfied, and the code review findings (CR-01, WR-01, WR-02, WR-03, IN-01, IN-02) were all fixed before this verification.

The single human verification item (W1 benchmark timing) is a recurring milestone-wide gate that is formally bound to Phase 4 and carries very low risk given the structural evidence.

---

_Verified: 2026-06-29_
_Verifier: Claude (gsd-verifier)_
