---
phase: 03-operational-sql-backends-2-store-layer
verified: 2026-06-29T16:32:58Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
deferred:
  - truth: "The 'live' factory arms default to SqlSettings.default() = SQLite :memory: when no backend is injected — money decays to float and SYSTEM_DB_URL value is silently discarded (CR-01)"
    addressed_in: "Phase 4"
    evidence: "Phase 4 goal: 'Retention + Live Write-Through — live = write-through + working-set cache + purge-on-terminalize + read-through + restart rehydration'; live wiring is a RETAIN-01/02/03 concern. The Phase 3 PLANs explicitly document the SQLite default as a placeholder: '...until Phase 4 wires the shared operational Postgres SqlBackend at the live composition root (D-06 / research §Factory wiring).'"
---

# Phase 3: Operational SQL Backends Verification Report

**Phase Goal:** One Postgres SQL backend per existing seam (order mirror, portfolio state, signal), money as native `Numeric`, testcontainers round-trip; backtest in-memory backends unchanged.
**Verified:** 2026-06-29T16:32:58Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | `SqlOrderStorage` implements `OrderStorage` ABC on Postgres (filling `PostgreSQLOrderStorage` stub); `SqlPortfolioStateStorage` implements `PortfolioStateStorage`; `SqlSignalStorage` implements `SignalStore` ABC — each selectable via the factory `'live'` arm | ✓ VERIFIED | All three classes exist and pass `issubclass` checks. `postgresql_storage.py` stub deleted. `issubclass(SqlOrderStorage, OrderStorage)` / `issubclass(SqlPortfolioStateStorage, PortfolioStateStorage)` / `issubclass(SqlSignalStorage, SignalStore)` all True. Factory `'live'` arm wired for all three (confirmed by reading storage_factory.py files). |
| 2 | Each factory returns the in-memory backend for `backtest` (UNCHANGED, importing no SQLAlchemy symbol); SQL backend is returned for `'live'` — no-serialization-in-backtest-backend rule holds structurally | ✓ VERIFIED | Programmatic check: importing all three factories does NOT load SQLAlchemy (`sqlalchemy loaded: False` on all three). `InMemoryOrderStorage` returned for `'backtest'`/`'test'` in all three factories. Lazy import pattern confirmed in `'live'` arms. |
| 3 | Operational money persists as Postgres-native `Numeric` (Decimal end-to-end, no float-for-money, no `DecimalAsText`) and round-trips as an exact `Decimal` — validated by testcontainers Postgres round-trip tests | ✓ VERIFIED | All three models use `sqlalchemy.Numeric` (direct, no TypeDecorator). 36 integration storage tests pass, including all Postgres-arm round-trips: `test_sql_order_storage.py` (6), `test_sql_portfolio_storage.py` (16), `test_sql_signal_storage.py` (6). Each includes exact-Decimal money assertions gated to the `pg_backend` Postgres arm. Docker was present and the full Postgres arm executed. |
| 4 | (Recurring gates) Oracle byte-exact 134/46189.87730727451; backtest path still routes through in-memory backends; mypy --strict clean; filterwarnings=["error"] green | ✓ VERIFIED | `tests/integration/test_backtest_oracle.py`: 3 passed. `mypy itrader`: 206 source files, no issues. All 36 integration storage tests pass (incl. Postgres arm). GATE-01 SQLAlchemy-free backtest path verified programmatically. No `__init__.py` in `tests/integration/storage/`. |

**Score:** 4/4 truths verified

### Deferred Items

Items not yet met but explicitly addressed in later milestone phases.

| # | Item | Addressed In | Evidence |
|---|------|-------------|----------|
| 1 | `'live'` factory arms default to `SqlSettings.default()` = SQLite `:memory:` when no operational `SqlBackend` is injected — `SYSTEM_DB_URL` value is not threaded through to the factory (CR-01 from code review) | Phase 4 | Phase 4 goal covers "Retention + Live Write-Through" (RETAIN-01/02/03). All three Phase 3 PLAN summaries explicitly document this as a placeholder: "a placeholder until Phase 4 wires the shared operational Postgres SqlBackend at the live composition root." |

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/storage/backend.py` | `NAMING_CONVENTION` constant + `MetaData(naming_convention=...)` | ✓ VERIFIED | `NAMING_CONVENTION` dict with `ix`/`uq`/`ck`/`fk`/`pk` keys present. `SqlBackend.__init__` sets `self.metadata = MetaData(naming_convention=NAMING_CONVENTION)`. Probe: `NAMING_CONVENTION['pk'] == 'pk_%(table_name)s'` passes. |
| `tests/integration/storage/conftest.py` | `pg_backend` fixture yielding `SqlBackend` bound to testcontainers Postgres | ✓ VERIFIED | `def pg_backend(request)` present, disposes backend in `finally`, uses `SecretStr` verbatim-URL escape hatch reusing the session `pg_engine` container. |
| `itrader/order_handler/storage/models.py` | `build_order_tables(metadata)` returning `orders` + `order_state_changes` with self-ref bracket FK | ✓ VERIFIED | `def build_order_tables` present. Probe: `set(t) == {'orders', 'order_state_changes'}` and `t['orders'].c.parent_order_id.foreign_keys` truthy — both pass. D-08 index `ix_orders_portfolio_status` present in migration. |
| `itrader/order_handler/storage/sql_storage.py` | `class SqlOrderStorage(OrderStorage)` — full ABC implementation | ✓ VERIFIED | Class exists, inherits `OrderStorage`, all ~14 abstract methods implemented via parameterized Core. Not re-exported (GATE-01 quarantine). |
| `itrader/portfolio_handler/storage/models.py` | `build_portfolio_tables(metadata)` returning 6 normalized tables | ✓ VERIFIED | `def build_portfolio_tables` present. Probe: `set(pt) == {'positions','transactions','cash_reservations','locked_margin','cash_operations','equity_snapshots'}` passes. `ix_positions_portfolio_open` index present. |
| `itrader/portfolio_handler/storage/sql_storage.py` | `class SqlPortfolioStateStorage(PortfolioStateStorage)` with bound `portfolio_id` | ✓ VERIFIED | Class exists, inherits `PortfolioStateStorage`, constructor takes `(backend, portfolio_id)`. Cross-portfolio isolation test present and passes. |
| `itrader/strategy_handler/storage/models.py` | `build_signal_tables(metadata)` returning `signals` table with indexed `strategy_id`/`ticker` and `config` json_variant | ✓ VERIFIED | `def build_signal_tables` present. `signals` table has `strategy_id` and `ticker` as indexed columns; `config` column is `json_variant()`. |
| `itrader/strategy_handler/storage/sql_storage.py` | `class SqlSignalStorage(SignalStore)` — 4-method ABC implementation | ✓ VERIFIED | Class exists, inherits `SignalStore`, implements `add`/`get_all`/`by_strategy`/`by_ticker` via parameterized Core. Not re-exported. |
| `itrader/order_handler/storage/postgresql_storage.py` | DELETED (NotImplementedError stub removed) | ✓ VERIFIED | File does not exist. `pyproject.toml` override also removed (no `postgresql_storage` in grep). |
| `tests/integration/storage/test_sql_order_storage.py` | Round-trip + bracket + money + determinism tests | ✓ VERIFIED | 6 tests pass. Covers `obj2 == order` field-wise, bracket `child_order_ids` via FK, exact-Decimal money, value-equal UUID, query helpers, UtcIsoText determinism. |
| `tests/integration/storage/test_sql_portfolio_storage.py` | Six-table round-trip + isolation + Position projection + money tests | ✓ VERIFIED | 16 tests pass. Covers Position projection (`to_dict()+id+leverage+_last_accrual_time`, not `==`), cross-portfolio isolation, all 6 collections, exact-Decimal money. |
| `tests/integration/storage/test_sql_signal_storage.py` | Round-trip + filter isolation + config-dict + money tests | ✓ VERIFIED | 6 tests pass. Covers `obj2 == record`, `by_strategy`/`by_ticker` isolation, config decoded-dict equality, exact-Decimal money. |
| `itrader/storage/migrations/env.py` | `target_metadata` built from `NAMING_CONVENTION` + three `build_*_tables` | ✓ VERIFIED | `env.py` imports `NAMING_CONVENTION`, `build_order_tables`, `build_portfolio_tables`, `build_signal_tables`. Constructs `MetaData(naming_convention=NAMING_CONVENTION)` then calls all three registrars. Probe: 9 tables registered, passes. Module stays import-inert (no `SqlBackend`/`Settings()` at module load). |
| `itrader/storage/migrations/versions/2cbf0bf6b0b6_operational_baseline.py` | Autogenerated baseline migration with `def upgrade` creating all operational tables | ✓ VERIFIED | File exists. Contains `def upgrade()` with 10 `op.create_table` / `op.create_index` statements covering all 9 operational tables. Self-ref `parent_order_id` FK, D-08 indexes, `Numeric` money columns, `UtcIsoText` columns all present. `hand-added import itrader.storage.types` included. `alembic upgrade head` verified by migration tests (3 passed). |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `tests/integration/storage/conftest.py::pg_backend` | `itrader.config.sql.SqlSettings` + `itrader.storage.SqlBackend` | `SqlSettings(driver=POSTGRESQL_PSYCOPG2, url=SecretStr(container_url)) -> SqlBackend(settings)` | ✓ WIRED | Confirmed in conftest.py lines 121-135. Uses verbatim-URL escape hatch. |
| `OrderStorageFactory ('live' arm)` | `SqlOrderStorage` | lazy import inside `'live'` branch, passing `SqlBackend` | ✓ WIRED | Lines 53-61 in `storage_factory.py`. SQLAlchemy not imported on module load (GATE-01 verified). |
| `PortfolioStateStorageFactory ('live' arm)` | `SqlPortfolioStateStorage(backend, portfolio_id)` | lazy import inside `'live'` branch | ✓ WIRED | Lines 72-87 in `storage_factory.py`. Requires `portfolio_id` (raises `ValueError` if missing). |
| `SignalStorageFactory ('live' arm)` | `SqlSignalStorage(backend)` | lazy import inside `'live'` branch | ✓ WIRED | Lines 69-79 in `storage_factory.py`. |
| `itrader/storage/migrations/env.py` | `itrader.storage.backend.NAMING_CONVENTION` + three `build_*_tables` | import + register on autogen MetaData | ✓ WIRED | Lines 31-61 in `env.py`. Single source of truth for constraint/index names. |

### Data-Flow Trace (Level 4)

Not applicable. This phase produces storage backends and test infrastructure, not UI components or data-rendering artifacts. The data flow is proven directly by the testcontainers round-trip tests (write → read → assert equality).

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `NAMING_CONVENTION` exported from `backend.py` with all 5 keys | `python -c "from itrader.storage.backend import NAMING_CONVENTION; assert NAMING_CONVENTION['pk'] == 'pk_%(table_name)s'"` | Passes | ✓ PASS |
| SQLAlchemy not loaded on backtest factory imports | `python -c "...import factories; check sys.modules for sqlalchemy"` | `sqlalchemy loaded: False` (all three) | ✓ PASS |
| `build_*_tables` probe: 9 tables on NAMING_CONVENTION MetaData | `python -c "...m=MetaData(naming_convention=NAMING_CONVENTION); build_order/portfolio/signal_tables(m); assert len(m.tables) >= 9"` | 9 tables | ✓ PASS |
| All three SQL classes are proper ABC subclasses | `issubclass` checks for all three | All True | ✓ PASS |
| 36 integration storage tests (incl. Postgres arm) | `poetry run pytest tests/integration/storage/ -x -q` | 36 passed in 2.63s | ✓ PASS |
| Backtest oracle byte-exact | `poetry run pytest tests/integration/test_backtest_oracle.py -x -q` | 3 passed, 134 trades / 46189.87730727451 | ✓ PASS |
| mypy --strict clean | `poetry run mypy itrader` | Success: 206 source files, no issues | ✓ PASS |
| Alembic migration chain (SQLite arm) | `poetry run pytest tests/integration/storage/test_migrations.py -x -q` | 3 passed | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| OPS-01 | 03-02-PLAN.md | `SqlOrderStorage` implements `OrderStorage` ABC on Postgres, stub deleted, selectable via factory | ✓ SATISFIED | `SqlOrderStorage` exists, `issubclass` confirmed, `postgresql_storage.py` deleted, `'live'` arm wired. Factory `'live'` arm satisfies the `postgresql`/`live` wording in ROADMAP SC-1. |
| OPS-02 | 03-03-PLAN.md | `SqlPortfolioStateStorage` implements `PortfolioStateStorage` on Postgres | ✓ SATISFIED | Class exists with bound `portfolio_id`, 6 tables, all 16 round-trip tests pass. |
| OPS-03 | 03-04-PLAN.md | `SqlSignalStorage` implements `SignalStore` ABC on Postgres | ✓ SATISFIED | Class exists, 4 methods, 6 round-trip tests pass including `by_strategy`/`by_ticker` filter isolation. |
| OPS-04 | 03-02/03/04-PLAN.md (cross-cutting) | Operational money as Postgres-native `Numeric`, exact `Decimal` round-trip on testcontainers | ✓ SATISFIED | All three models use `sqlalchemy.Numeric`. Postgres-arm money tests pass in all three test files. |
| GATE-01 | recurring | Backtest oracle byte-exact, no SQLAlchemy on backtest import path | ✓ SATISFIED | Oracle 3/3 passed (134 / 46189.87730727451). SQLAlchemy-free backtest path verified programmatically. |
| GATE-02 | recurring | DB round-trip tests on testcontainers Postgres, mypy clean, filterwarnings green | ✓ SATISFIED | 36 integration tests pass (Docker present, Postgres arm executed). mypy 206 files clean. |

**Note on OPS-01 `postgresql` vs `'live'` arm naming:** REQUIREMENTS.md says "selectable via `OrderStorageFactory` (`in_memory` backtest / `postgresql` live)". The PLANS explicitly chose `'live'` as the selector key and no `'postgresql'` arm (D-06 decision). The ROADMAP SC-1 explicitly accepts both by writing "`postgresql`/`live` arm". The implementation satisfies the intent: the factory selects `SqlOrderStorage` for the non-backtest live path.

### Anti-Patterns Found

| File | Pattern | Severity | Impact |
|------|---------|----------|--------|
| `itrader/portfolio_handler/storage/storage_factory.py:74-75` | `raise ValueError(...)` instead of `ConfigurationError` for missing `portfolio_id` | ⚠️ Warning (WR-04 from code review) | Convention inconsistency vs sibling factories; callers cannot catch storage-construction failures uniformly. Not a correctness defect. |
| `itrader/order_handler/storage/models.py:64-96` | Required columns `time`, `type`, `status`, `ticker`, `action`, `price`, `quantity`, etc. left at implicit `nullable=True` | ⚠️ Warning (WR-02) | DB silently accepts NULLs where `OrderType(None)` would crash on read. Defense-in-depth gap; no data corruption risk in current code paths. |
| `itrader/strategy_handler/storage/models.py:58-69` | Same as above for `signals` table | ⚠️ Warning (WR-02) | Same impact as above. |
| `itrader/order_handler/storage/sql_storage.py:407-420` | `get_orders_by_time_range` passes bounds through `UtcIsoText.process_bind_param` which raises `ValueError` on naive datetimes | ⚠️ Warning (WR-03) | Edge-case: callers passing naive datetimes get a raw `ValueError` from the codec instead of a clean domain error. No current caller exercises this path. |
| `itrader/trading_system/live_trading_system.py:6` | Unused `import json` | ℹ️ Info (IN-01) | Dead import, no functional impact. |

No `TBD`, `FIXME`, or `XXX` markers found in any phase-modified file. No stub patterns (empty implementations returning `[]`/`{}`/`None` without data access) found — all such returns are correct ABC contract returns when no data matches.

### Human Verification Required

None. All truths are directly observable in the code and confirmed by automated checks.

### Gaps Summary

No gaps. All phase goal must-haves are verified.

**CR-01 Assessment (code review advisory):** The code review flagged as CRITICAL that the `'live'` factory arms default to `SqlSettings.default()` = SQLite `:memory:` when no backend is injected, meaning the live production path silently uses a non-durable, float-precision backend and discards the `SYSTEM_DB_URL` value. This is a real production wiring defect. However, it does NOT block the phase goal: the phase goal is about the SQL backends existing and round-tripping correctly on Postgres via testcontainers — which is proven by 36 passing integration tests on a live Docker container. The SQLite default is a documented placeholder pending Phase 4's live write-through wiring (explicitly stated in all three PLAN SUMMARYs). The deferred item is recorded above for Phase 4.

---

_Verified: 2026-06-29T16:32:58Z_
_Verifier: Claude (gsd-verifier)_
