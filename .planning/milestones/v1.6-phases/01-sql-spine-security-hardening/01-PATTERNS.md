# Phase 1: SQL Spine + Security Hardening - Pattern Map

**Mapped:** 2026-06-27
**Files analyzed:** 14 new/modified (incl. optional `results/base.py`)
**Analogs found:** 12 with matches / 12 code-bearing files (the two NEW infra files — `storage/backend.py`, `storage/types.py` — and the Alembic skeleton are green-field; see "No Analog Found")

> **Indentation is load-bearing — VERIFIED ON DISK (do NOT normalize).** A byte-level
> tab/space scan resolved a CONTEXT.md↔RESEARCH.md conflict. Ground truth (use this, ignore
> RESEARCH.md §"Project Constraints" which wrongly tags `order_handler/storage/` + `portfolio_handler/storage/` as tabs):
>
> | Path | Indent (verified) |
> |------|-------------------|
> | `itrader/storage/` (NEW), `config/`, `config/sql.py` (NEW) | **4-space** |
> | `order_handler/storage/*`, `order_handler/base.py` | **4-space** |
> | `portfolio_handler/storage/*` | **4-space** |
> | `portfolio_handler/base.py` | **TAB imports + 4-space class body** (mixed — don't touch this phase) |
> | `strategy_handler/storage/*` | **4-space** |
> | `tests/unit/*`, `tests/integration/*` | **4-space** |
> | `price_handler/store/sql_store.py` | **TABS** (69 tab-lines, 0 space-lines) — the FL-06 target |
>
> CONTEXT.md's indentation map (lines 189-192) is correct; RESEARCH.md line 611 is NOT. Pin the verified value in each plan's `read_first`/acceptance.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality | Indent |
|-------------------|------|-----------|----------------|---------------|--------|
| `itrader/storage/types.py` (NEW) | utility (cross-dialect type helpers) | transform | RESEARCH.md Pattern 2 (no codebase analog) | **no-analog** (green-field) | 4-space |
| `itrader/storage/backend.py` (NEW) | service / infra (Engine+MetaData holder) | request-response | `sql_store.py::init_engine` (engine ctor only) + RESEARCH.md Pattern 1 | partial (engine-ctor only) | 4-space |
| `itrader/storage/__init__.py` (NEW) | config / barrel | n/a | `price_handler/store/__init__.py`, `config/__init__.py` | exact | 4-space |
| `itrader/config/sql.py` (NEW) | config (`SqlSettings` Pydantic) | transform (URL build) | `config/order.py` + `config/system.py` (BaseModel + `str,Enum` + `default()`) | exact | 4-space |
| `itrader/storage/migrations/env.py` + `script.py.mako` + `versions/` (NEW) | config / migration | batch | RESEARCH.md Pattern 5 (alembic boilerplate, no codebase analog) | **no-analog** (green-field) | 4-space |
| `alembic.ini` (NEW) | config | n/a | none (alembic-init artifact) | **no-analog** | n/a |
| `price_handler/store/sql_store.py` (MODIFY) | model / store (price-data persistence) | CRUD + file-I/O (pandas↔SQL) | itself (FL-06 rework) + RESEARCH.md Pattern 4 | exact (self-rework) | **TABS today** → planner's D-06 call |
| `itrader/results/base.py` (OPTIONAL NEW) | model (ResultsStore ABC seam) | CRUD | `strategy_handler/storage/base.py::SignalStore` | exact | 4-space |
| `tests/integration/storage/conftest.py` (NEW) | test (fixtures: `pg_engine`) | n/a | `tests/integration/conftest.py` (deferred-import fixture) | role-match | 4-space |
| `tests/integration/storage/test_spine_roundtrip.py` (NEW) | test (SPINE-03) | n/a | `tests/unit/order/test_order_storage.py` + RESEARCH.md round-trip shape | role-match | 4-space |
| `tests/integration/storage/test_migrations.py` (NEW) | test (MIG-01) | n/a | `tests/unit/order/test_order_storage.py` | role-match | 4-space |
| `tests/unit/storage/test_sql_settings.py` (NEW) | test (SPINE-01) | n/a | `tests/unit/order/test_order_storage.py` | role-match | 4-space |
| `tests/unit/price_handler/test_sql_handler.py` (NEW) | test (SEC-01) | n/a | `tests/unit/order/test_order_storage.py` | role-match | 4-space |
| `pyproject.toml` (MODIFY) | config (deps + mypy override) | n/a | itself (D-09 override removal) | exact (self-edit) | — |

---

## Pattern Assignments

### `itrader/config/sql.py` — `SqlSettings` (config, transform)

**Analog:** `itrader/config/order.py` (Pydantic `BaseModel` + `str,Enum` config-enum + `default()`),
reinforced by `itrader/config/system.py` (`str,Enum` member shape).
**Cred source consumed:** `itrader/config/settings.py:39` (`database_url: SecretStr`).

**`str, Enum` driver-enum pattern** — copy the member shape from `config/system.py:15-21` / `config/order.py:29-46`:
```python
# config/system.py:15-21 — (str, Enum) with explicit string values, validated-by-value
class Environment(str, Enum):
    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"
```
SqlDriver mirrors this exactly (`SQLITE_PYSQLITE = "sqlite+pysqlite"`, …, plus the unwired `SQLITE_LIBSQL` slot — D-15).

**Pydantic model + `default()` classmethod pattern** (`config/system.py:66-98`, `config/order.py:48-63`):
```python
# config/order.py:48-63
class OrderConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")          # mass-assignment defense
    market_execution: MarketExecution = MarketExecution.IMMEDIATE

    @classmethod
    def default(cls) -> "OrderConfig":
        return cls()
```
> RESEARCH.md Pattern 3 uses `BaseModel` (NOT `BaseSettings`) for `SqlSettings` and an `engine_url()`
> method — consistent with this analog. Choose `extra="forbid"` (order.py) vs `extra="ignore"` (system.py);
> order.py's forbid is the security-leaning default for a new minimal model.

**Cred source — the FL-06 secret seam** (`config/settings.py:37-39`):
```python
# config/settings.py:37-39 — required-no-default SecretStr; read ONLY via .get_secret_value()
# Secrets: NO default -> ValidationError if a live path ever instantiates Settings
# without ITRADER_DATABASE_URL set. Access only via database_url.get_secret_value().
database_url: SecretStr
```
**Import-side-effect trap (Pitfall 8 — load-bearing):** `Settings.database_url` is required-no-default,
so `Settings()` raises `ValidationError` if `ITRADER_DATABASE_URL` is unset. Do NOT instantiate
`Settings()` at import time in `config/sql.py` or `storage/`; resolve it lazily inside `engine_url()` on
the Postgres arm only (the SQLite/backtest path stays env-free, mirroring `config/settings.py` docstring lines 30-34).

---

### `price_handler/store/sql_store.py` — FL-06 rework (model/store, CRUD + file-I/O)

**Analog:** itself (the rework target) + RESEARCH.md Pattern 4. The three vulns and current
SQLAlchemy usage, with exact lines to eliminate:

**Vuln 1 — hardcoded creds (L17):** replace with `Settings.database_url.get_secret_value()`.
```python
# sql_store.py:16-20 — DELETE this hardcoded user:pass@host
def init_engine(self):
    engine = create_engine('postgresql+psycopg2://tizianoiacovelli:1234@localhost:5432/trading_system_prices')
    if not database_exists(engine.url):
        create_database(engine.url)
    return engine
```

**Vuln 2 — f-string `DROP TABLE` DDL (L35):** replace with constant DDL / parameterized Core delete.
```python
# sql_store.py:28-39 — f-string interpolation inside text() is the injection vector
def delete_all_tables(self):
    symbols = self.get_symbols_SQL()
    connection = self.engine.connect()
    for sym in symbols:
        qry_str = text(f'DROP TABLE IF EXISTS {"%s"};'%sym)   # <-- DELETE
        connection.execute(qry_str)
    connection.commit()
    connection.close()
```

**Vuln 3 — symbol-as-table-name (L56/58/69):** collapse into one `prices` table, symbol as a VALUE column (D-07).
```python
# sql_store.py:56,58 (write) and 69 (read) — dynamic identifier = the schema-sprawl + injection surface
prices.to_sql(symbol.lower(), self.engine, index=True, if_exists='replace')   # L56
prices.to_sql(symbol.lower(), self.engine, index=True, if_exists='append')    # L58
df = pd.read_sql(symbol, connection, index_col='date')                        # L69
```

**Replacement shape** (RESEARCH.md Pattern 4 — single `prices` table, bound params, Float not money-Decimal):
```python
prices = Table(
    "prices", backend.metadata,
    Column("symbol", String, primary_key=True),
    Column("date",   UtcIsoText, primary_key=True),   # business-time, uniform encoding (types.py)
    Column("open", Float), Column("high", Float), Column("low", Float),
    Column("close", Float), Column("volume", Float),
)
# write:  df.to_sql("prices", engine, if_exists="append", index=False)   # literal name = injection-safe
# read:   select(prices).where(prices.c.symbol == bindparam("symbol"))   # bound param, never f-string
# purge:  prices.delete().where(prices.c.symbol == bindparam("symbol"))  # or DROP TABLE prices (constant)
```

**Logger pattern to preserve** (`sql_store.py:13`): `self.logger = get_itrader_logger().bind(component="SQLHandler")`.
Never log the resolved secret URL (SecretStr masks repr; do not call `.get_secret_value()` into a log).

**Indentation decision (D-06):** file is TABS today. Either keep TABS if logic stays in `sql_store.py`,
or relocate the SQL logic into the 4-space `storage/` spine and leave a thin typed shim. NEVER mix
tabs+spaces in one file (Pitfall 5 — `TabError`).

**mypy (D-09 / GATE-02):** `sql_store` is in the `ignore_errors` D-sql override at `pyproject.toml:92`.
The rework lifts it into `--strict`; remove that line and make the ~84-line file strict-clean
(`pandas .to_sql/read_sql` may need a narrow `# type: ignore[no-untyped-call]` at the pandas boundary).

---

### `itrader/storage/backend.py` — `SqlBackend` (service/infra, request-response)

**Analog:** the engine-construction half of `sql_store.py::init_engine` (lines 16-20) is the only
existing `create_engine` call on the live path; everything else is green-field (RESEARCH.md Pattern 1).
```python
# itrader/storage/backend.py  (4-space)  — RESEARCH.md Pattern 1
from sqlalchemy import create_engine, MetaData
from sqlalchemy.engine import Engine
from itrader.config.sql import SqlSettings

class SqlBackend:
    """Shared SQL spine: Engine + MetaData + Core SQL. NO business logic."""
    def __init__(self, settings: SqlSettings) -> None:
        self.engine: Engine = create_engine(settings.engine_url())   # driver from config, not code
        self.metadata = MetaData()
```
**No god base class** (Anti-Pattern): there is deliberately NO `SqlStorageBase` the four ABCs inherit —
each `Sql<Concern>Storage` *composes* this `SqlBackend` (Phases 2-3). Phase 1 ships only the spine.

---

### `itrader/storage/types.py` — cross-dialect helpers (utility, transform)

**Analog:** none in-tree (green-field). The only template is RESEARCH.md Pattern 2 (VERIFIED against
installed SQLAlchemy 2.0.50). Shape: `Uuid(as_uuid=True)` used directly + `UtcIsoText(TypeDecorator)`
(business-time, `cache_ok = True` REQUIRED for mypy-strict) + `json_variant()` → `JSON().with_variant(JSONB(), "postgresql")`.
**NO `DecimalAsText`** (D-13 — money never touches SQLite this milestone).
Cross-check existing business-time type: it is a **tz-aware Python `datetime`** (see `order_handler/base.py:4`
`from datetime import datetime`; events carry tz-aware business `time`), microsecond max → ISO-8601-UTC-text is lossless (D-04/D-05).

---

### `itrader/results/base.py` — `ResultsStore` ABC (OPTIONAL, model, CRUD)

**Analog:** `strategy_handler/storage/base.py::SignalStore` (the narrowest existing storage ABC — 4 methods).
```python
# strategy_handler/storage/base.py:17-46 — ABC + @abstractmethod, narrow domain seam, NumPy docstrings
from abc import ABC, abstractmethod

class SignalStore(ABC):
    """Abstract base class for signal-record storage backends (D-07)."""
    @abstractmethod
    def add(self, record: SignalRecord) -> None: ...
    @abstractmethod
    def get_all(self) -> List[SignalRecord]: ...
```
> Q5 (RESEARCH.md Open Questions): adding `results/base.py` now is cheap and makes the "all four compose"
> shape concrete, but deferring the whole `results/` package to Phase 2 is equally valid. Planner's call;
> not load-bearing for SPINE-03. If added, mirror `SignalStore`'s narrow-ABC shape — do NOT widen it.

---

### Test files (SPINE-01/03, SEC-01, MIG-01)

**Analog (structure):** `tests/unit/order/test_order_storage.py` — the storage-test idiom: module-level
imports of the public storage surface, a `@pytest.fixture` building seeded entities with native
`uuid.UUID`, then `def test_*` functions asserting through the public API.
```python
# tests/unit/order/test_order_storage.py:1-29 — imports + fixture shape
import uuid
from datetime import datetime, UTC
import pytest
from itrader.order_handler.storage import InMemoryOrderStorage, OrderStorageFactory

@pytest.fixture
def store():
    storage = InMemoryOrderStorage()
    oid1 = uuid.uuid4()
    ...
    return SimpleNamespace(storage=storage, oid1=oid1, ...)
```

**Analog (fixture / deferred import):** `tests/integration/conftest.py` — the `pg_engine` fixture mirrors
its factory-returning, deferred-import discipline so `--collect-only` succeeds without Docker:
```python
# tests/integration/conftest.py:45-72 — factory fixture; heavy import lives INSIDE the inner fn
@pytest.fixture
def backtest_engine():
    def _make(...):
        from itrader.trading_system.backtest_trading_system import BacktestTradingSystem  # deferred
        return BacktestTradingSystem(...)
    return _make
```
**`pg_engine` specifics (D-10/D-11):** session-scoped `testcontainers.postgres.PostgresContainer`; import
testcontainers INSIDE the fixture body and `pytest.skip(...)` on `DockerException`/absent Docker so a
Dockerless `poetry run pytest` skips the PG arm but still runs the SQLite half (must NOT hard-fail).
Tests live under `tests/integration/storage/` → folder-derived `integration` marker (no marker decorator needed).

**SPINE-03 round-trip assertion shape** (RESEARCH.md Code Examples, lines 565-582):
```python
run_id = uc.uuid7()                              # native uuid.UUID, single scheme
bt = datetime(2018, 1, 1, tzinfo=timezone.utc)   # business time, never wall clock
got_id, got_bt = roundtrip(engine, run_id, bt)
assert got_id == run_id    # SPINE-03 value equality (D-03)
assert got_bt == bt        # instant equality (D-04/D-05)
# SAME assertions on SQLite AND testcontainers Postgres (D-10).
```

---

## Shared Patterns

### Factory string-arm backend selection (the established idiom — Phase 3 adds the SQL arm)
**Source:** `order_handler/storage/storage_factory.py:40-58` (canonical), copied verbatim by
`portfolio_handler/storage/storage_factory.py:53-68` and `strategy_handler/storage/storage_factory.py:49-68`.
**Apply to:** any factory the spine touches (Phase 1 does NOT add a SQL arm — it only ships the spine
the future arm will compose). Record the idiom so Phase 3 plans inherit it.
```python
# order_handler/storage/storage_factory.py:40-58
environment = environment.lower()
if environment in ('backtest', 'test'):
    return InMemoryOrderStorage()
elif environment == 'live':
    if not db_url:
        raise ConfigurationError("db_url", None, "Database URL is required for live environment")
    from .postgresql_storage import PostgreSQLOrderStorage   # deferred import — avoids pulling SQL into backtest
    return PostgreSQLOrderStorage(db_url)
else:
    raise ConfigurationError("environment", environment, f"Unknown environment: {environment}. ...")
```
> Note the deferred `from .postgresql_storage import …` INSIDE the live arm — keeps SQLAlchemy off the
> backtest import path (GATE-01 inertness). The PG sibling is a `NotImplementedError` stub today
> (`order_handler/storage/postgresql_storage.py:14`; portfolio raises at `storage_factory.py:61`;
> signal raises at `storage_factory.py:59`). The spine does NOT change these in Phase 1.

### Storage ABC shape (compose-this, never inherit a god base)
**Source:** `strategy_handler/storage/base.py` (4 methods, narrowest) and `order_handler/base.py`
(~15 methods, widest). Both: `class X(ABC)` + `@abstractmethod` + NumPy `Parameters`/`Returns` docstrings.
**Apply to:** the optional `ResultsStore` ABC, and as the reference for what each `Sql<Concern>Storage`
must satisfy in Phases 2-3 (`PortfolioStateStorage` ~21 methods lives in `portfolio_handler/base.py`).

### Barrel `__init__.py` with quarantine note
**Source:** `price_handler/store/__init__.py:1-14` — re-exports the public store surface and DELIBERATELY
does NOT import `sql_store` at package level ("pulls sqlalchemy/psycopg2 … deferred persistence milestone").
**Apply to:** `itrader/storage/__init__.py` (re-export `SqlBackend` + the `types.py` helpers) and the FL-06
rework — if `sql_store` stays SQL-heavy, keep the quarantine pattern so backtest import stays SQL-free (Pitfall 3).

### Secret handling (FL-06 / SEC-01)
**Source:** `config/settings.py:37-39` (`database_url: SecretStr`, `.get_secret_value()` only).
**Apply to:** `config/sql.py::engine_url()` (Postgres arm) and the reworked `sql_store.py`. One canonical
source — do NOT add a third (the legacy `live_trading_system.py:34` `SYSTEM_DB_URL` is a separate seam;
reconcile-or-document per RESEARCH.md Open Q4, do not wire a new source).

### Determinism + strict-suite discipline (cross-cutting, every file)
- **Business `time` only**, never `datetime.now()`/wall clock at the persistence edge (Pitfall 6).
- **`filterwarnings=["error", ignore::UserWarning, ignore::DeprecationWarning]`** (`pyproject.toml:74-78`)
  — `SAWarning` and others are NOT ignored; fix the code, do not broaden the ignore list (Pitfall 2).
- **mypy `--strict`** over `itrader` (`pyproject.toml:80-83`); new `storage/`, `config/sql.py`, `results/`
  are auto-in-scope (no override). The `sql_store` D-sql override (`pyproject.toml:92`) is removed by the rework (D-09).
- **Markers folder-derived** (`pyproject.toml:63-68`): only `unit`/`integration`/`slow`/`e2e` registered —
  PG round-trip tests in `tests/integration/storage/` get `integration` automatically; no decorator.

---

## No Analog Found

Files with no close in-tree match — planner uses RESEARCH.md patterns (all VERIFIED against installed SQLAlchemy 2.0.50):

| File | Role | Data Flow | Reason / Source |
|------|------|-----------|-----------------|
| `itrader/storage/types.py` | utility | transform | First cross-dialect TypeDecorator in the tree. Use RESEARCH.md Pattern 2 (`Uuid(as_uuid=True)`, `UtcIsoText`, `json_variant()`; NO `DecimalAsText`). |
| `itrader/storage/migrations/env.py` + `script.py.mako` + `versions/` | config/migration | batch | No Alembic exists anywhere (green-field, grep-confirmed). Use RESEARCH.md Pattern 5 (`render_as_batch=True`, EMPTY `versions/`, live-PG only; research/results DB uses `create_all()` — no `alembic_version` table). |
| `alembic.ini` | config | n/a | `alembic init` artifact; `script_location` → `storage/migrations`. |
| `itrader/storage/backend.py` | service/infra | request-response | Only the `create_engine` ctor half resembles `sql_store.py:16-20`; the `MetaData`/Core-SQL spine role is new. |

> **Do NOT build (locked OUT — re-litigation risk):** `DecimalAsText` (D-13), `pyarrow`/Parquet (locked),
> `sqlalchemy-libsql` driver (D-15 — enum slot only), any `write_through` knob (Phase 4),
> a DB autoincrement / `Integer primary_key` (second ID scheme — violates single-UUIDv7 lock).

## Metadata

**Analog search scope:** `itrader/{storage(absent),config,order_handler,portfolio_handler,strategy_handler,price_handler/store}/`,
`tests/{unit,integration}/`, `pyproject.toml`.
**Files scanned:** 17 read in full/part + a byte-level indentation scan across 11 files.
**Pattern extraction date:** 2026-06-27
