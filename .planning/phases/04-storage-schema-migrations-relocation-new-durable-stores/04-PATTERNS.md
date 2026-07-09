# Phase 4: Storage Schema: Migrations Relocation + New Durable Stores - Pattern Map

**Mapped:** 2026-07-09
**Files analyzed:** 13 (5 new source + 5 new/moved migrations + 3 extended/new test)
**Analogs found:** 13 / 13 (every new file clones a shipped, tested template)

> **North star:** every new source file is a disciplined *clone* of an existing, tested spine
> asset — `HaltRecordStore` (the store + registrar template), the `dict[str, Table]` multi-table
> registrar, the delete-then-insert portable upsert, and the shipped Alembic revisions. There is
> no new machinery to invent. The failure mode is *re-inventing* a tool (dialect upsert, hand-rolled
> JSON/timestamp type), not lacking one. All new `itrader/storage/` and `migrations/` files are
> **4-space indented** — never normalize (TabError breaks the oracle/inertness gates).

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `itrader/storage/system_store.py` | store + registrar | CRUD (single-table upsert) | `itrader/storage/halt_record_store.py` | exact (literal template) |
| `itrader/storage/venue_store.py` | store + registrar | CRUD + write-time validation | `itrader/storage/halt_record_store.py` | exact + secret guard divergence |
| `itrader/storage/strategy_registry_store.py` | store + 2-table registrar | CRUD + FK join | `halt_record_store.py` (store) + `order_handler/storage/models.py::build_order_tables` (registrar) | exact + role-match |
| `migrations/` (moved from `itrader/storage/migrations/`) | migration tree | schema-evolution | mechanical `git mv` (self) | exact (relocation) |
| `alembic.ini` (edit `script_location`) | config | — | self (line 8) | exact |
| `migrations/versions/system_store.py` | migration | schema-evolution | `d10_halt_records.py` (shape) + baseline (type-import) | exact |
| `migrations/versions/venue_config.py` | migration | schema-evolution | `d10_halt_records.py` + baseline | exact |
| `migrations/versions/strategy_registry.py` | migration (2 tables + FK) | schema-evolution | baseline `2cbf0bf6b0b6` (FK + `op.f`) | role-match |
| `migrations/env.py` (extend `target_metadata`) | config | — | existing `env.py:30-66` register-vs-build | exact |
| `tests/integration/storage/test_migrations.py` (extend + fix `:31`) | test | integration gate | self (existing structure) | exact |
| `tests/integration/test_okx_inertness.py` (extend) | test | integration gate | self (register-vs-build) | exact |
| `tests/unit/storage/test_system_store.py` (NEW) | test | unit round-trip | `tests/integration/test_durable_halt.py` | role-match |
| `tests/unit/storage/test_venue_store.py`, `test_strategy_registry_store.py` (NEW) | test | unit + restart | `test_durable_halt.py` + `test_migrations.py:73-74` file-backed | role-match |

## Pattern Assignments

### `itrader/storage/system_store.py` (store + registrar, single-table CRUD upsert)

**Analog:** `itrader/storage/halt_record_store.py` — clone verbatim; **the ONE line NOT copied** is
the UUIDv7 PK (`:67` `Column("id", Uuid(as_uuid=True), primary_key=True)` and `:109`
`idgen.generate_halt_record_id()`). Natural `key` PK replaces it (D-06). Do **not** import/call `idgen`.

**Imports pattern** (`halt_record_store.py:26-35`):
```python
from datetime import datetime
from typing import NamedTuple, Optional

from sqlalchemy import Boolean, Column, MetaData, String, Table, insert, select, update, delete
from sqlalchemy.engine import Engine

from itrader.logger import get_itrader_logger
from itrader.storage import SqlEngine, UtcIsoText, Uuid, json_variant
```
Note: `json_variant`/`delete` are added vs the template (D-08 JSON column + delete-then-insert upsert);
`idgen` import is dropped (D-06 — no UUIDv7 PK).

**Registrar pattern — single source of truth** (clone `halt_record_store.py:49-71`, idempotent guard):
```python
def build_system_store_table(metadata: MetaData) -> Table:
    if "system_store" in metadata.tables:            # shared-backend idempotency guard
        return metadata.tables["system_store"]
    return Table(
        "system_store", metadata,
        Column("key", String, primary_key=True),                # natural PK (D-06) — NOT Uuid
        Column("value_json", json_variant(), nullable=False),   # D-08
        Column("updated_at", UtcIsoText, nullable=False),       # D-07 caller-supplied `at`
    )
```

**Store `__init__` / `dispose` pattern** (clone `halt_record_store.py:85-96` exactly):
```python
def __init__(self, sql_engine: SqlEngine) -> None:
    self.backend = sql_engine
    self.engine: Engine = sql_engine.engine
    self.system_store: Table = build_system_store_table(sql_engine.metadata)
    sql_engine.metadata.create_all(self.engine, checkfirst=True)  # test / no-op-if-present path
    self.logger = get_itrader_logger().bind(component="SystemStore")

def dispose(self) -> None:
    self.backend.dispose()   # WR-03 — delegate, NEVER self.engine.dispose()
```

**Upsert pattern (delete-then-insert, one txn)** — from `portfolio_handler/storage/sql_storage.py:275-293`
(NOT dialect `ON CONFLICT`). Parameterized Core against the constant `Table` (SEC-01, no f-string):
```python
def upsert(self, key: str, value: dict, at: datetime) -> None:
    with self.engine.begin() as connection:
        connection.execute(delete(self.system_store).where(self.system_store.c.key == key))
        connection.execute(
            insert(self.system_store),
            [{"key": key, "value_json": value, "updated_at": at}],
        )
```

**Read/rehydrate pattern** — mirror `halt_record_store.py:117-140` (`.mappings().first()` for a row,
`.mappings().all()` for read-all). Method surface (D-09): `upsert` / `get` / `delete` / read-all(rehydrate).

---

### `itrader/storage/venue_store.py` (store + registrar, CRUD + write-time secret denylist)

**Analog:** same `HaltRecordStore` template as above. Table schema (D-03):
```python
def build_venue_store_table(metadata: MetaData) -> Table:
    if "venue_store" in metadata.tables:
        return metadata.tables["venue_store"]
    return Table(
        "venue_store", metadata,
        Column("venue_name", String, primary_key=True),        # natural PK (D-06)
        Column("enabled", Boolean, nullable=False),            # typed — serves list_enabled query
        Column("config_json", json_variant(), nullable=False),
        Column("updated_at", UtcIsoText, nullable=False),
    )
```

**DIVERGENCE — write-time secret denylist guard (D-05, defense-in-depth).** No analog in the template;
this is net-new but modeled on the project's paranoid secret-scrub ethos (`halt_record_store.py:10-14`
no-payload discipline). Reject known-secret key names (`api_key`/`secret`/`password`/`passphrase`/`token`/…)
in `config_json` with `ValidationError` (from `itrader/core/exceptions/base.py`). Guard should walk the
JSON **recursively** (nested `{"nested": {"api_key": …}}` must fire — Pitfall 6). Exact key set + depth
is planner's discretion. Fire the guard in `upsert` before the delete-then-insert.

**Typed-column query (D-09):** `list_enabled()` → `select(...).where(venue_store.c.enabled.is_(True))`
mirrors `halt_record_store.py:117-126` `has_unresolved` filter shape.

---

### `itrader/storage/strategy_registry_store.py` (store + 2-table registrar, CRUD + FK join)

**Store analog:** `HaltRecordStore` (same `__init__`/`dispose`/upsert). **Registrar analog:**
`order_handler/storage/models.py:37-52` (`build_order_tables → dict[str, Table]`) — the multi-table
precedent for D-04. Registrar returns `dict[str, Table]` with **both** tables, each behind its own
idempotency guard:
```python
# Pattern from order_handler/storage/models.py:52-61 (dict[str, Table], per-table guard)
def build_strategy_registry_tables(metadata: MetaData) -> dict[str, Table]:
    tables: dict[str, Table] = {}
    if "strategy_registry" in metadata.tables:
        tables["strategy_registry"] = metadata.tables["strategy_registry"]
    else:
        tables["strategy_registry"] = Table(
            "strategy_registry", metadata,
            Column("strategy_name", String, primary_key=True),   # natural PK (D-06) — NOT strategy_id UUID
            Column("enabled", Boolean, nullable=False),
            Column("config_json", json_variant(), nullable=False),
            Column("updated_at", UtcIsoText, nullable=False),
        )
    if "strategy_subscriptions" in metadata.tables:
        tables["strategy_subscriptions"] = metadata.tables["strategy_subscriptions"]
    else:
        tables["strategy_subscriptions"] = Table(
            "strategy_subscriptions", metadata,
            Column("strategy_name", String,
                   ForeignKey("strategy_registry.strategy_name"), nullable=False),
            Column("venue", String, nullable=False),
            Column("symbol", String, nullable=False),
            Column("timeframe", String, nullable=False),
            # natural composite PK (strategy_name, venue, symbol, timeframe) — no autoincrement,
            # no surrogate UUID (D-06 spirit); planner confirms (RESEARCH Open Q2/A3).
        )
    return tables
```
**D-06 correctness-critical:** the durable key is the strategy **name**, NOT the ephemeral runtime
`strategy_id` UUIDv7 (`strategy_handler/base.py:191-192` minted per-construction, `:631` NOT restart-stable;
`STRATEGY_COMMAND` addresses by name at `strategies_handler.py:474`). Persisting `strategy_id` breaks
rehydrate. `ForeignKey` import comes from `sqlalchemy` (see `order_handler/storage/models.py:23-32`).

**Rehydrate joins both tables** (D-04); `set_subscriptions` / subscription-query method surface (D-09).

---

### `migrations/` relocation (movement A — mechanical)

**Analog:** the tree itself (`git mv`, revision IDs preserved — D-10). Only **two** source path
references exist (verified by grep): `alembic.ini:8` and `tests/integration/storage/test_migrations.py:31`.

- `git mv itrader/storage/migrations migrations` (exclude `__pycache__`; `.gitkeep` in `versions/` moves).
- `alembic.ini:8` `script_location = itrader/storage/migrations` → `migrations`. `sqlalchemy.url` stays
  blank (SEC-01). `prepend_sys_path = .` (`:21`) keeps repo root on `sys.path` so `env.py` absolute
  `from itrader.storage… import …` imports resolve unchanged. No `version_locations` key — defaults to
  `<script_location>/versions`.
- `tests/integration/storage/test_migrations.py:31` `_MIGRATIONS_DIR = _REPO_ROOT / "itrader" / "storage" / "migrations"`
  → `_REPO_ROOT / "migrations"` (Pitfall 1 — the test pins the absolute dir onto the Config at `:42`).
- Wheel exclusion is automatic (`pyproject.toml [tool.poetry] packages = [{include = "itrader"}]`;
  moving outside `itrader/` drops it from the wheel — assumption A1, LOW-risk; optional `poetry build` gate).
- Cosmetic: update stale path comments in `engine.py:23` and `env.py` docstring (Claude's discretion).

---

### New Alembic revisions (movement B — hand-authored, D-11)

**Analog (shape):** `itrader/storage/migrations/versions/d10_halt_records.py:27-48` — cleanest revision
*shape* (revision/down_revision header, `op.create_table`, `op.drop_table`). **Analog (type-imports +
`op.f` + FK):** `2cbf0bf6b0b6_operational_baseline.py` and `47f2b41f3ffe_portfolio_account_state.py`
(both add `import itrader.storage.types` at `:18` and use `op.f(...)` / `sa.ForeignKeyConstraint`).

**Chain:** `d10_halt_records` (current head) → `system_store` → `venue_config` → `strategy_registry`
(new head). After: `alembic heads == ("strategy_registry",)` (single linear head — SQL-02).

**Revision template** (clone `d10_halt_records.py` + baseline type-import gotchas):
```python
revision: str = "system_store"
down_revision: Union[str, Sequence[str], None] = "d10_halt_records"
branch_labels = None
depends_on = None

import itrader.storage.types                      # Pitfall 2 — hand-added, autogen omits it
from sqlalchemy.dialects import postgresql         # Pitfall 2 — for json_variant render

def upgrade() -> None:
    op.create_table(
        "system_store",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value_json", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
                  nullable=False),
        sa.Column("updated_at", itrader.storage.types.UtcIsoText(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_system_store")),   # Pitfall 3 — NAMING_CONVENTION
    )

def downgrade() -> None:
    op.drop_table("system_store")
```
- `venue_config` revision (`down_revision="system_store"`) creates the **`venue_store`** table (Pitfall 5 —
  revision slug ≠ table name).
- `strategy_registry` revision (`down_revision="venue_config"`): `upgrade()` calls `op.create_table` **twice**
  (registry then `strategy_subscriptions` with `sa.ForeignKeyConstraint(["strategy_name"],
  ["strategy_registry.strategy_name"], name=op.f("fk_strategy_subscriptions_strategy_name_strategy_registry"))`);
  `downgrade()` drops `strategy_subscriptions` **first** (FK child) then `strategy_registry`. FK-naming
  precedent: baseline `:99` `sa.ForeignKeyConstraint([...], name=op.f('fk_orders_parent_order_id_orders'))`.
- **Pitfall 3:** every PK/FK/index name wrapped in `op.f(...)` matching `NAMING_CONVENTION` (`engine.py:26-32`),
  else the create_all-vs-migration parity gate churns. `alembic revision --autogenerate` once (drafting aid,
  D-11) produces these names — copy verbatim into the 3-link split.

---

### `migrations/env.py` extension (D-02 migration-target wiring — NOT live-system wiring)

**Analog:** existing `env.py:30-66` register-vs-build `target_metadata` construction from `build_order_tables`
/ `build_portfolio_tables` / `build_signal_tables` / `build_halt_records_table` + `NAMING_CONVENTION`.
Append the 3 new registrar imports + calls so autogenerate sees all new tables (no spurious drops):
```python
from itrader.storage.system_store import build_system_store_table
from itrader.storage.venue_store import build_venue_store_table
from itrader.storage.strategy_registry_store import build_strategy_registry_tables
# … after existing build_* calls:
build_system_store_table(target_metadata)
build_venue_store_table(target_metadata)
build_strategy_registry_tables(target_metadata)   # registers BOTH tables (D-04)
```

---

### Gate tests (extend existing)

**`tests/integration/storage/test_migrations.py`** — analog is itself. Fix `:31` path (Pitfall 1); add:
single-head assertion (`ScriptDirectory.from_config(...).get_heads() == ("strategy_registry",)`); full-chain
`upgrade head` on fresh SQLite asserting the 4 new tables present + `alembic_version` = head; create_all-vs-
migration parity (build MetaData via all `build_*` on engine A, `upgrade head` on engine B, compare
`inspect().get_table_names()` + column/constraint sets). File-backed SQLite fixture precedent at `:73-74`
(`db_path = tmp_path / "x.db"; url = f"sqlite+pysqlite:///{db_path}"`). Postgres arm `pytest.skip`s cleanly
(`:92-93`).

**`tests/integration/test_okx_inertness.py`** — analog is itself (register-vs-build discipline `env.py:55-58`).
Extend BOTH ways (RESEARCH Open Q3): add the 3 new store modules to `_FORBIDDEN` (never on backtest hot path)
AND assert the 3 new registrars build only `Table` objects on a fresh MetaData (no Engine, no `Settings()`).

**`tests/unit/storage/test_{system,venue,strategy_registry}_store.py`** (NEW) — analog
`tests/integration/test_durable_halt.py` (SQLite `SqlEngine` fixture). Two flavors:
- **Round-trip / CRUD / list_enabled / secret-denylist:** in-memory `:memory:` SQLite `SqlEngine` (D-01 —
  real store over SQLite, no in-memory twin scaffold).
- **Restart-survival (STORE-04/D-02):** **file-backed** `tmp_path` SQLite (NOT `:memory:` — Pitfall 4:
  disposing `:memory:` destroys the DB). Construct `SqlEngine(SqlSettings(driver=SqlDriver.SQLITE_PYSQLITE,
  database=str(db_path)))`, write, `store.dispose()`, construct a NEW store over the same path, read-back
  assert equal. Wrap in `try/finally: store.dispose()` (`filterwarnings=["error"]` turns an unclosed-sqlite
  `ResourceWarning` into a failure). Pass a **fixed** `at` timestamp (D-07 determinism).

## Shared Patterns

### Column types (D-07/D-08)
**Source:** `itrader/storage/types.py` — `Uuid` (`:34`, re-exported; NOT used as PK here per D-06),
`UtcIsoText` (`:37-64`, rejects naive datetimes, deterministic UTC-isoformat), `json_variant()`
(`:67-69`, `JSON().with_variant(JSONB(), "postgresql")`).
**Apply to:** all three stores — `config_json`/`value_json` = `json_variant()`; `updated_at` = `UtcIsoText`.
Imported via the barrel `from itrader.storage import SqlEngine, UtcIsoText, Uuid, json_variant`.

### Registrar = single source of truth (T-03-19)
**Source:** `halt_record_store.py:49-71` (single) / `order_handler/storage/models.py:37-52` (multi).
**Apply to:** all 3 registrars — the same `build_*_table` feeds both the store's `create_all` (test path)
and `migrations/env.py` `target_metadata` (deploy path). Makes the SQL-02 parity gate meaningful. Keep
import-inert: construct only `Table` on a fresh `MetaData` — no Engine, no `Settings()`, no connection (GATE-01).

### Portable upsert (delete-then-insert, one transaction)
**Source:** `portfolio_handler/storage/sql_storage.py:275-293`.
**Apply to:** every store's `upsert` — NOT dialect `ON CONFLICT` (forks the code path for no benefit).
Parameterized Core against the constant `Table` object; `with self.engine.begin()` = atomic replace,
dialect-agnostic (SQLite `:memory:`/file, Postgres identical).

### `dispose()` delegation (WR-03)
**Source:** `halt_record_store.py:94-96`.
**Apply to:** all 3 stores — `self.backend.dispose()`, never `self.engine.dispose()`.

### Secret-scrub ethos (D-05 / V7)
**Source:** `halt_record_store.py:10-14` (no-payload-column discipline); connector-owned credentials
(`itrader/connectors/okx.py` + `OkxSettings` `SecretStr`).
**Apply to:** `VenueStore` — structural (secrets never passed in) + defensive write-time denylist guard.

## No Analog Found

None. Every new file clones a shipped, tested asset. The only net-new *logic* with no direct analog is
the `VenueStore` recursive secret-denylist guard (D-05) — modeled on the project's secret-scrub ethos and
the accepted defense-in-depth precedent (D-03a dual-layer validator), but there is no existing denylist to
copy line-for-line. Planner pins the exact key set + recursion depth (Claude's discretion).

## Metadata

**Analog search scope:** `itrader/storage/`, `itrader/order_handler/storage/`,
`itrader/portfolio_handler/storage/`, `itrader/storage/migrations/versions/`, `tests/integration/storage/`,
`tests/integration/`.
**Files scanned (read this session):** `halt_record_store.py`, `types.py`, `order_handler/storage/models.py`,
`portfolio_handler/storage/sql_storage.py` (+ all line refs grounded in 04-RESEARCH.md, HIGH confidence).
**Pattern extraction date:** 2026-07-09
```
