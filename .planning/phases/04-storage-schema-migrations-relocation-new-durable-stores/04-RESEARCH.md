# Phase 4: Storage Schema: Migrations Relocation + New Durable Stores - Research

**Researched:** 2026-07-09
**Domain:** Alembic migration relocation + SQLAlchemy Core durable stores on the `SqlEngine` spine
**Confidence:** HIGH (every finding grounded in files read directly from this repo)

## Summary

This phase is two ordered movements over infrastructure that **already exists and is proven**: (A) a
mechanical `git mv` of `itrader/storage/migrations/` → project-root `migrations/` with a single
`alembic.ini` edit, and (B) three new durable SQL stores cloned verbatim from
`itrader/storage/halt_record_store.py`, each with its own `build_*_table` registrar, three new
hand-authored chained Alembic revisions, and file-backed restart round-trip tests. There is **no new
machinery to invent** — the `HaltRecordStore` template, the `env.py` registrar-as-single-source-of-truth
pattern, the `json_variant`/`UtcIsoText`/`Uuid` type helpers, the multi-table `dict[str, Table]` registrar
precedent, and the create_all-vs-Alembic parity gate all already ship. The genuine work is disciplined
cloning plus catching the handful of hardcoded-path and custom-type-import gotchas.

The relocation is verifiably sufficient with one `alembic.ini` line change: `env.py` uses only absolute
`itrader.*` imports resolved via `prepend_sys_path = .` (repo root), and `packages = [{include = "itrader"}]`
means physically moving `migrations/` outside the `itrader/` tree automatically excludes it from the wheel.
The **one required edit the planner must not miss** is the hardcoded `_MIGRATIONS_DIR` in
`tests/integration/storage/test_migrations.py:31`.

**Primary recommendation:** Clone `HaltRecordStore` three times (natural name PK, not UUIDv7 — D-06);
author three explicit revision files off the `d10_halt_records` head using `d10_halt_records.py` as the
literal template; use the codebase's **delete-then-insert-in-one-transaction** portable upsert (NOT dialect
`ON CONFLICT`); test restart-survival with **file-backed** SQLite in `tmp_path` (NOT `:memory:`).

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01** No in-memory store classes — STORE-05 "in-memory fallback" is satisfied structurally via the
  `HaltRecordStore` `None`-degrade template, NOT a `Protocol` + `InMemory*Store` + `*StorageFactory` scaffold.
  Test the real store over an in-memory **SQLite** `SqlEngine`. **Do NOT build a twin scaffold.**
- **D-02** Standalone + migration-registered; NOT constructed in `LiveTradingSystem.__init__`. In P4: store
  classes, `build_*_table` registrars, 3 chained migrations, `env.py` `target_metadata` additions, SQL-02
  gate, CRUD + rehydrate reads, restart-survival unit tests. Construction into the live composition root is
  deferred to P6/P9/P10.
- **D-03** Hybrid schema — type identity/flags/timestamp columns (queryable), JSON for heterogeneous config.
  `SystemStore(key, value_json, updated_at)`; `VenueStore(venue_name PK, enabled bool, config_json, updated_at)`;
  `StrategyRegistryStore(strategy_name PK, enabled bool, config_json, updated_at)`.
- **D-04** `StrategyRegistryStore` is **two tables**: registry + normalized
  `strategy_subscriptions(strategy_name FK, venue, symbol, timeframe)`. Its registrar builds both (precedent:
  `dict[str, Table]`), its migration creates both, rehydrate joins both.
- **D-05** `VenueStore` never stores secrets — enforced two ways: (1) structural (credentials owned by the
  connector/`OkxSettings` `SecretStr`, never passed in); (2) defensive write-time denylist guard rejecting
  known-secret key names (`api_key`/`secret`/`password`/`passphrase`/`token`/…) in `config_json` with a
  `ValidationError`.
- **D-06** Natural name-based PKs; the ephemeral runtime `strategy_id` UUIDv7 is NEVER the durable key.
  `SystemStore` PK=`key`; `VenueStore` PK=`venue_name`; `StrategyRegistryStore` PK=`strategy_name`. Names are
  not a second ID scheme — fully compliant with single-UUIDv7. No surrogate UUIDv7 PK, no DB autoincrement.
- **D-07** Caller-supplied `at: datetime` param stored via `UtcIsoText`. Store stays clock-free; tests pass a
  fixed timestamp; live call sites pass `datetime.now(UTC)`.
- **D-08** `value_json`/`config_json` use `json_variant()` (`itrader/storage/types.py:67`), not plain String.
- **D-09** Method surface: CRUD (upsert/get/delete/read-all-rehydrate) + column-justified queries
  (`list_enabled`/`list_active`, set-subscriptions) only. NO consumer-domain methods now. Finalize in P9/P10.
- **D-10** Preserve all 5 existing migrations via `git mv` UNCHANGED (revision IDs preserved). Do NOT squash.
  Chain: `2cbf0bf6b0b6 → 47f2b41f3ffe → p05_venue_order_id → hl5_transaction_venue_trade_id → d10_halt_records`.
- **D-11** Hand-author the 3 new chained revisions (`system_store` / `venue_config` / `strategy_registry`) in
  the `d10_`/`p05_` slug style, chained via `down_revision` from `d10_halt_records`. `alembic revision
  --autogenerate` may be used **once, as a DDL drafting aid only**, then split/renamed into the 3 links.

### Claude's Discretion
- Plan/commit granularity and step ordering within the relocation (subject to mechanical-relocation + the
  byte-exact/inertness gates).
- Precise store method names, column nullability/index choices beyond the typed-column decision, and the exact
  denylisted secret-key-name set (D-05).
- Whether `env.py` builds `strategy_subscriptions` via the same `dict[str, Table]` registrar or a companion
  registrar — as long as autogenerate/`target_metadata` sees both new tables (no spurious drops).

### Deferred Ideas (OUT OF SCOPE)
- Migration baseline reset / squash (milestone-level decision, not P4).
- Finalize store method surface in P9/P10 against real consumers.
- Constructing the stores in the live composition root + applying rehydrated state to live handlers (P6/P9/P10).
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SQL-01 | Relocate `migrations/` to project root; update `alembic.ini`; keep `env.py` registrar imports from `itrader.storage`; out of the wheel | One-line `script_location` edit sufficient (env.py uses absolute imports via `prepend_sys_path=.`); wheel exclusion automatic via `packages=[{include="itrader"}]`; MUST also fix `test_migrations.py:31` hardcoded path |
| SQL-02 | Alembic gate: `upgrade head` clean, `heads == 1`, create_all/migration parity | Extend `tests/integration/storage/test_migrations.py`; use `ScriptDirectory.from_config().get_heads()` for single-head; table/column-set comparison for parity |
| STORE-01 | `SystemStore` cardinality-1 `(key, value_json, updated_at)` namespaced upsert | Clone `HaltRecordStore`; natural `key` PK (D-06); `json_variant` value (D-08); delete-then-insert upsert |
| STORE-02 | `VenueStore` cardinality-N per-venue config + enabled; never secrets | Hybrid schema (D-03); write-time secret denylist guard (D-05); `list_enabled` typed-column query |
| STORE-03 | `StrategyRegistryStore` cardinality-N strategies + config + subscriptions | Two-table registrar (D-04); natural `strategy_name` PK (D-06); FK'd `strategy_subscriptions` child |
| STORE-04 | Follows `HaltRecordStore` template; chained migration; rehydrates on restart | Template extracted below; 3 hand-authored revisions off `d10_halt_records`; file-backed restart round-trip test |
| STORE-05 | In-memory fallback keeps backtest path untouched (live-only) | D-01 `None`-degrade (no twin scaffold); oracle byte-exact + inertness gates prove untouched |
</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Durable schema evolution | Migrations tree (`migrations/`) | Alembic env.py | Deploy-path schema; out of the wheel, off the hot loop |
| Schema single-source-of-truth | `build_*_table` registrars (`itrader/storage/…`) | — | Feed BOTH `create_all` (test) and Alembic `target_metadata` (deploy) — makes parity meaningful |
| Durable read/write | Store classes (`itrader/storage/*_store.py`) | `SqlEngine` spine | Compose the Engine+MetaData by reference; parameterized Core only |
| Cross-dialect encoding | `itrader/storage/types.py` | — | `Uuid`/`UtcIsoText`/`json_variant` — SQLite⇄Postgres value-equal |
| Restart rehydrate | Store read-all methods | file-backed SQLite | State survives dispose→re-open; consumer applies it in P6/P9/P10 |
| Secret exclusion | Connector/`OkxSettings` (structural) | `VenueStore` write-time denylist (defensive) | Credentials never reach persistence (D-05) |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy | ^2.0.50 (already pinned, `pyproject.toml:*`) | Core `Table`/`insert`/`select`/`delete`/`update`; `TypeDecorator` | The spine's existing engine; `[VERIFIED: pyproject.toml]` |
| Alembic | ^1.18.5 (already pinned, `pyproject.toml:43`) | Migration chain, `op.create_table`, `command.upgrade`, `ScriptDirectory` | Already drives the 5-revision chain; `[VERIFIED: pyproject.toml]` |

**Zero new dependencies.** Milestone-wide gate (`REQUIREMENTS.md:24-25`, `:349`): "Zero new third-party
dependency, no poetry change anywhere in P1–P12." Everything this phase needs is already installed.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| delete-then-insert upsert | `sqlite_insert().on_conflict_do_update()` / `pg_insert().on_conflict_do_update()` | Dialect fork = two code paths + import of dialect-specific `insert`. The codebase already rejects this (see Don't Hand-Roll). |
| Natural name PK | UUIDv7 surrogate PK + unique natural key | Extra indirection, no consumer, and the ephemeral `strategy_id` is explicitly not restart-stable (D-06) |

## Package Legitimacy Audit

**No external packages are installed in this phase.** Both dependencies (`sqlalchemy ^2.0.50`,
`alembic ^1.18.5`) are already pinned in `pyproject.toml` and the milestone gate forbids any poetry change.
Package Legitimacy Gate: **N/A — no install step**.

## Architecture Patterns

### System Architecture Diagram

```
                     build_*_table(metadata)  ──────────────┐  (SINGLE SOURCE OF TRUTH)
                            │                                │
              ┌─────────────┴──────────────┐                │
              ▼                             ▼                ▼
   Store.__init__                  migrations/env.py    (deploy-path)
   metadata.create_all(           target_metadata =    alembic upgrade head
     checkfirst=True)               MetaData(NAMING_    → op.create_table per
   (test / no-op path)              CONVENTION)+build_*   hand-authored revision
              │                             │                │
              ▼                             ▼                ▼
   ┌──────────────────────────────────────────────────────────────┐
   │  SqlEngine (Engine + MetaData(naming_convention))             │
   │  SQLite :memory:/file  (tests)   |   Postgres (live, deferred)│
   └──────────────────────────────────────────────────────────────┘
              ▲
   caller supplies  at: datetime  →  UtcIsoText column (D-07)
   parameterized Core:  insert / select / delete / update  (SEC-01, no f-string)

   RELOCATION (movement A):
   itrader/storage/migrations/  ── git mv ──▶  migrations/   (out of wheel)
   alembic.ini: script_location = itrader/storage/migrations ─▶ migrations
   env.py imports stay `from itrader.storage… import …`  (prepend_sys_path=.)

   NEW CHAIN (movement B):
   … → hl5_transaction_venue_trade_id → d10_halt_records (current head)
        → system_store → venue_config → strategy_registry (NEW head; heads==1)
```

### Recommended Project Structure
```
migrations/                         # RELOCATED (was itrader/storage/migrations/), out of wheel
├── env.py                          # + 3 new build_* imports + target_metadata calls
├── script.py.mako                  # moves as-is
└── versions/
    ├── 2cbf0bf6b0b6_…  47f2b41f3ffe_…  p05_…  hl5_…  d10_halt_records.py   # git mv UNCHANGED
    ├── system_store.py             # NEW  down_revision="d10_halt_records"
    ├── venue_config.py             # NEW  down_revision="system_store"
    └── strategy_registry.py        # NEW  down_revision="venue_config" (creates BOTH tables)

itrader/storage/
├── engine.py  types.py  __init__.py  halt_record_store.py   # existing spine (unchanged)
├── system_store.py                 # NEW  build_system_store_table + SystemStore
├── venue_store.py                  # NEW  build_venue_store_table + VenueStore (secret guard)
└── strategy_registry_store.py      # NEW  build_strategy_registry_tables (dict[str,Table]) + store
```
Store-module placement mirrors `halt_record_store.py` living directly under `itrader/storage/`.
**Indentation: 4 spaces** for every new `itrader/storage/` file and `migrations/` file (verified
convention — `halt_record_store.py`, `types.py`, `env.py`, all 4-space).

### Pattern 1: The Store (clone of `HaltRecordStore`)
**What:** compose `SqlEngine`, own registrar, idempotent `create_all`, parameterized Core, `dispose()`
delegates. **When:** all three new stores.
```python
# Source: itrader/storage/halt_record_store.py:74-96 (the literal template)
class SystemStore:
    def __init__(self, sql_engine: SqlEngine) -> None:
        self.backend = sql_engine
        self.engine: Engine = sql_engine.engine
        self.system_store = build_system_store_table(sql_engine.metadata)
        sql_engine.metadata.create_all(self.engine, checkfirst=True)  # idempotent test/no-op path
        self.logger = get_itrader_logger().bind(component="SystemStore")

    def dispose(self) -> None:
        self.backend.dispose()   # WR-03 — delegate, never self.engine.dispose()
```
**Deliberate divergence from the template (D-06):** the PK is a **natural name column** (`key` /
`venue_name` / `strategy_name`), NOT a UUIDv7 from `idgen`. Do NOT call `idgen.generate_*_id()` for the PK.
`HaltRecordStore`'s `id = idgen.generate_halt_record_id()` (`:109`) is the ONE line you do not copy.

### Pattern 2: The registrar (single source of truth)
**What:** idempotent `build_*_table(metadata) -> Table` (or `dict[str, Table]` for two tables). **When:**
one per store; imported by BOTH the store's `create_all` and `migrations/env.py`.
```python
# Source: itrader/storage/halt_record_store.py:49-71  (single-table)
def build_system_store_table(metadata: MetaData) -> Table:
    if "system_store" in metadata.tables:            # idempotent shared-backend guard
        return metadata.tables["system_store"]
    return Table(
        "system_store", metadata,
        Column("key", String, primary_key=True),                # natural PK (D-06)
        Column("value_json", json_variant(), nullable=False),   # D-08
        Column("updated_at", UtcIsoText, nullable=False),       # D-07
    )
```
```python
# Source: itrader/order_handler/storage/models.py:37-52  (dict[str, Table] precedent for D-04)
def build_strategy_registry_tables(metadata: MetaData) -> dict[str, Table]:
    tables: dict[str, Table] = {}
    if "strategy_registry" in metadata.tables:
        tables["strategy_registry"] = metadata.tables["strategy_registry"]
    else:
        tables["strategy_registry"] = Table(
            "strategy_registry", metadata,
            Column("strategy_name", String, primary_key=True),
            Column("enabled", Boolean, nullable=False),
            Column("config_json", json_variant(), nullable=False),
            Column("updated_at", UtcIsoText, nullable=False),
        )
    if "strategy_subscriptions" in metadata.tables:
        tables["strategy_subscriptions"] = metadata.tables["strategy_subscriptions"]
    else:
        tables["strategy_subscriptions"] = Table(
            "strategy_subscriptions", metadata,
            Column("strategy_name", String, ForeignKey("strategy_registry.strategy_name"),
                   nullable=False),
            Column("venue", String, nullable=False),
            Column("symbol", String, nullable=False),
            Column("timeframe", String, nullable=False),
            # composite PK or surrogate: planner's call (D-09 discretion); natural composite avoids autoincr
        )
    return tables
```

### Pattern 3: Portable namespaced upsert (delete-then-insert in one txn)
**What:** the codebase's established portable upsert — NOT dialect `ON CONFLICT`.
```python
# Source: itrader/portfolio_handler/storage/sql_storage.py:276-293 (cash_reservations upsert)
def upsert(self, key: str, value: dict, at: datetime) -> None:
    with self.engine.begin() as connection:
        connection.execute(delete(self.system_store).where(self.system_store.c.key == key))
        connection.execute(insert(self.system_store),
                           [{"key": key, "value_json": value, "updated_at": at}])
```
One transaction = atomic replace, dialect-agnostic (works identically on SQLite `:memory:`, file, Postgres).

### Anti-Patterns to Avoid
- **Dialect-forked `ON CONFLICT` upsert:** the codebase deliberately uses delete-then-insert (see above).
  Introducing `sqlite_insert`/`pg_insert` on_conflict variants forks the code path for no benefit.
- **UUIDv7 surrogate PK on the new stores:** violates D-06; the durable identity is the name.
- **`:memory:` for a restart-survival test:** disposing a `:memory:` engine destroys the DB — it cannot
  prove restart survival. Use file-backed SQLite in `tmp_path` (see Pitfall 4).
- **Normalizing indentation:** `itrader/storage/` and `migrations/` are 4-space; a tab/space mixed diff
  raises `TabError` at import and breaks the oracle/inertness gates.
- **f-string SQL:** SEC-01 / T-05.2-19 — always parameterized Core against the constant `Table` object.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| SQLite⇄Postgres JSON column | per-dialect String/JSON switch | `json_variant()` (`types.py:67`) | Already `JSON`/`JSONB` variant, value-equal |
| UTC timestamp persistence | manual isoformat + naive-tz handling | `UtcIsoText` (`types.py:37`) | Deterministic bytes; rejects naive datetimes |
| Cross-dialect UUID | TEXT/BLOB per-dialect switch | `Uuid(as_uuid=True)` (`types.py:34`) | CHAR(32)/native UUID, round-trips equal |
| Portable upsert | `ON CONFLICT` dialect branches | delete-then-insert in one `engine.begin()` | `sql_storage.py:276` precedent, dialect-free |
| Constraint/index naming | ad-hoc names | `NAMING_CONVENTION` on the MetaData (`engine.py:26`) | Makes autogenerate deterministic ⇒ parity holds |
| In-memory store twin | `Protocol`+`InMemory*Store`+factory | `None`-degrade at call site (D-01) | Zero backtest consumers; twin diverges from the cited template |

**Key insight:** every column type, the upsert shape, the naming convention, and the registrar/create_all
parity mechanism already exist and are battle-tested. The failure mode in this phase is *re-inventing* one of
them (especially a dialect-forked upsert or a hand-rolled JSON/timestamp type), not lacking a tool.

## Common Pitfalls

### Pitfall 1: Hardcoded migrations path in the gate test
**What goes wrong:** `alembic upgrade head` still works after the move, but
`tests/integration/storage/test_migrations.py` fails.
**Why:** line 31 hardcodes `_MIGRATIONS_DIR = _REPO_ROOT / "itrader" / "storage" / "migrations"` and pins it
onto the Config (`cfg.set_main_option("script_location", str(_MIGRATIONS_DIR))`, `:42`). The comment at
`:26-32` explains Alembic resolves a *relative* `script_location` against cwd, so the test deliberately pins
the absolute dir.
**How to avoid:** update `:31` to `_REPO_ROOT / "migrations"` in the same commit as the `git mv` + `alembic.ini` edit.
**Warning signs:** `test_migrations.py` errors with "No such file or directory" / "Path doesn't exist".

### Pitfall 2: Custom-type import not emitted in hand-authored revisions
**What goes wrong:** `alembic upgrade head` raises `NameError: name 'itrader' is not defined` (or on
`UtcIsoText`).
**Why:** autogenerate renders the custom `UtcIsoText` TypeDecorator by its fully-qualified name
`itrader.storage.types.UtcIsoText()` but does NOT emit the `import` — the standard custom-type gotcha.
Both `47f2b41f3ffe_portfolio_account_state.py:18` and `2cbf0bf6b0b6_operational_baseline.py:18` add
`import itrader.storage.types` by hand for exactly this.
**How to avoid:** in each new revision that uses `UtcIsoText`, add `import itrader.storage.types` and
reference `itrader.storage.types.UtcIsoText()`. For `json_variant`, render the variant explicitly:
`sa.JSON().with_variant(postgresql.JSONB(), "postgresql")` with `from sqlalchemy.dialects import postgresql`
(baseline `:12` already imports this). Note `d10_halt_records.py` needed neither — it uses only
`sa.Uuid`/`sa.String`/`sa.Boolean`, which is why it's the cleanest template *shape* but not the type-import
template.
**Warning signs:** upgrade head raises `NameError`; the parity test then can't even build the schema.

### Pitfall 3: `op.f()` naming must match `NAMING_CONVENTION` or parity churns
**What goes wrong:** create_all emits `pk_strategy_registry` / `fk_strategy_subscriptions_strategy_name_strategy_registry`
(from `NAMING_CONVENTION`, `engine.py:26-32`) but the migration emits a different/implicit name — parity
comparison or a re-autogenerate reports a spurious diff.
**Why:** the MetaData carries `NAMING_CONVENTION`; the migration must reproduce the same names via `op.f(...)`.
Precedent: baseline `:99` `sa.ForeignKeyConstraint([...], name=op.f('fk_orders_parent_order_id_orders'))`,
`:41` `sa.PrimaryKeyConstraint('operation_id', name=op.f('pk_cash_operations'))`.
**How to avoid:** wrap every PK/FK/index name in `op.f("pk_<table>")` /
`op.f("fk_<table>_<col>_<referred>")` / `op.f("ix_<table>_<col>")` matching the convention templates.
Drafting via autogenerate once (D-11) produces these names automatically — copy them verbatim into the split.
**Warning signs:** `alembic revision --autogenerate` after the migrations land emits a non-empty diff; the
parity test's constraint-name comparison fails.

### Pitfall 4: `:memory:` cannot prove restart survival
**What goes wrong:** a "restart" test on `:memory:` SQLite either loses all data on dispose (if you actually
dispose+reopen) or silently proves nothing (if the `SingletonThreadPool` keeps one engine alive — the
`HaltRecordStore` `:memory:` trick at `test_durable_halt.py:40-48` is a *round-trip within one engine*, not a
restart).
**Why:** STORE-04/D-02 require "write → dispose → re-open over the same DB → read back" — that is only
observable on a **file-backed** DB.
**How to avoid:** use `tmp_path` file-backed SQLite exactly like
`test_migrations.py:73-74` (`db_path = tmp_path / "x.db"; url = f"sqlite+pysqlite:///{db_path}"`), construct
`SqlEngine(SqlSettings(driver=SqlDriver.SQLITE_PYSQLITE, database=str(db_path)))`, write, `store.dispose()`,
construct a NEW store over the same path, read back and assert equality. Keep `:memory:` for the pure
round-trip/CRUD tests. Wrap in `try/finally: store.dispose()` — `filterwarnings=["error"]` turns an
unclosed-sqlite `ResourceWarning` into a failure.
**Warning signs:** restart test passes even when you delete the read-back logic (proves nothing), or errors
with "no such table" after re-open (data was in `:memory:`).

### Pitfall 5: Revision slug ≠ table name
**What goes wrong:** the parity/`upgrade head` assertions look for tables named `system_store` etc., but the
registrar named the table differently (or vice-versa).
**Why:** the migration *revision IDs* are `system_store`/`venue_config`/`strategy_registry` (D-11 chain
names). The physical *table names* are chosen by the registrars (D-03/D-09 discretion). They may coincide but
are conceptually distinct.
**How to avoid:** decide table names once and use them consistently in the registrar, the migration
`op.create_table(...)`, and the gate assertions. Recommended: table names `system_store`, `venue_store`,
`strategy_registry`, `strategy_subscriptions` — revision slugs `system_store`, `venue_config`,
`strategy_registry` per the locked chain (note `venue_config` slug builds the `venue_store` table).

### Pitfall 6: Secret guard must fire on nested keys too
**What goes wrong:** a caller passes `{"nested": {"api_key": "…"}}` and the denylist only scans top-level keys.
**Why:** `config_json` is an open blob (D-05 rationale).
**How to avoid:** the denylist guard should walk the JSON recursively (or at minimum document top-level-only
as the accepted boundary). This is Claude's-discretion (exact key set + depth) per D-05/CONTEXT discretion —
the planner should pin the depth decision. Reject with `ValidationError` (`itrader/core/exceptions/base.py`).

## Code Examples

### Relocation edit (the only two required source changes for movement A)
```bash
# Source: alembic.ini:8  +  git history preservation (D-10)
git mv itrader/storage/migrations migrations
# alembic.ini:8 :  script_location = itrader/storage/migrations  →  script_location = migrations
# env.py imports UNCHANGED — they are absolute `from itrader.storage… import …`, resolved by
#   alembic.ini:21  prepend_sys_path = .   (repo root on sys.path)
# alembic.ini:90  sqlalchemy.url =        (stays blank — SEC-01, no change)
# NO version_locations key set → defaults to <script_location>/versions → follows automatically
```
Then update `tests/integration/storage/test_migrations.py:31` → `_REPO_ROOT / "migrations"` (Pitfall 1).

### Hand-authored revision (clone of d10_halt_records.py)
```python
# Source: itrader/storage/migrations/versions/d10_halt_records.py:27-48  (the literal shape)
revision: str = "system_store"
down_revision: Union[str, Sequence[str], None] = "d10_halt_records"   # chains off current head
branch_labels = None
depends_on = None

import itrader.storage.types                       # Pitfall 2 — hand-added for UtcIsoText
from sqlalchemy.dialects import postgresql          # Pitfall 2 — for json_variant render

def upgrade() -> None:
    op.create_table(
        "system_store",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("value_json", sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
                  nullable=False),
        sa.Column("updated_at", itrader.storage.types.UtcIsoText(), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_system_store")),   # Pitfall 3
    )

def downgrade() -> None:
    op.drop_table("system_store")
```
`venue_config` revision: `down_revision="system_store"`; `strategy_registry` revision:
`down_revision="venue_config"` and its `upgrade()` calls `op.create_table` **twice** (registry then
`strategy_subscriptions` with `sa.ForeignKeyConstraint(["strategy_name"], ["strategy_registry.strategy_name"],
name=op.f("fk_strategy_subscriptions_strategy_name_strategy_registry"))`); its `downgrade()` drops
`strategy_subscriptions` **first** (FK child), then `strategy_registry`.

### env.py extension (D-02 migration-target wiring)
```python
# Source: itrader/storage/migrations/env.py:30-66  (append after build_halt_records_table)
from itrader.storage.system_store import build_system_store_table
from itrader.storage.venue_store import build_venue_store_table
from itrader.storage.strategy_registry_store import build_strategy_registry_tables
# … after line 66:
build_system_store_table(target_metadata)
build_venue_store_table(target_metadata)
build_strategy_registry_tables(target_metadata)   # registers BOTH tables (D-04)
```

### Single-head assertion (SQL-02)
```python
# Alembic API — assert the chain has exactly one head after the 3 new revisions
from alembic.script import ScriptDirectory
heads = ScriptDirectory.from_config(_alembic_config(url)).get_heads()
assert heads == ("strategy_registry",)   # single linear head, no branch
```

## Runtime State Inventory

> This is an additive schema phase, not a rename/migration of existing runtime state. No stored data is
> renamed, no live service config or OS-registered state changes. The one physical relocation is the
> migrations *tree*, addressed below.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | New tables only; no existing rows renamed/migrated. Existing 5-revision chain preserved by `git mv` (revision IDs unchanged) | None — additive |
| Live service config | `alembic.ini:8` `script_location` (the one path reference to the old location) | Update to `migrations` |
| OS-registered state | None — no scheduled tasks / services reference the migrations path | None ("None — verified: only `alembic.ini` + `test_migrations.py:31` reference the path") |
| Secrets/env vars | `sqlalchemy.url` stays blank (SEC-01); DB creds resolved lazily in `env.py:69-81` from `ITRADER_DATABASE_*` — unchanged by the move | None |
| Build artifacts | `migrations/__pycache__` and `versions/__pycache__` should NOT be committed; `.gitkeep` in versions/ moves with the tree | Ensure `git mv` excludes `__pycache__` |

**Only two files reference the old path:** `alembic.ini:8` and `tests/integration/storage/test_migrations.py:31`
(verified by grep). `env.py` uses absolute `itrader.*` imports (no path dependency) and
`pyproject.toml` `packages` names only `itrader` (no migrations path entry to remove).

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 (`minversion = "8.0"`, `testpaths = ["tests"]`) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` (`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`) |
| Quick run command | `poetry run pytest tests/integration/storage/test_migrations.py tests/unit/storage -x` |
| Full suite command | `make test` (note: aborts in worktrees on missing `.env`; use `poetry run pytest tests` there — auto-memory) |

### Phase Requirements → Test Map (observable edges the tests MUST sample — Nyquist Dim 8)
| Req ID | Behavior (observable property/edge) | Test Type | Automated Command | File Exists? |
|--------|-------------------------------------|-----------|-------------------|-------------|
| SQL-01 | `alembic upgrade head` resolves from `migrations/`; migrations absent from built wheel | integration | `poetry run pytest tests/integration/storage/test_migrations.py -x` | ⚠️ needs `:31` path fix |
| SQL-01 | wheel excludes `migrations/` | integration | `poetry build` then assert no `migrations/` entry in the wheel (optional gate) | ❌ Wave 0 (optional) |
| SQL-02 | `heads == ("strategy_registry",)` — single linear head | integration | `ScriptDirectory.from_config().get_heads()` assertion | ❌ Wave 0 |
| SQL-02 | full chain applies clean on fresh SQLite; new 4 tables present; `alembic_version` has 1 row = head | integration | extend `test_alembic_chain_stamps_operational_baseline_sqlite` | ⚠️ extend |
| SQL-02 | create_all vs migration parity (same table+column set) | integration | build MetaData via all `build_*` on engine A + `upgrade head` on engine B; compare `inspect().get_table_names()`/columns | ❌ Wave 0 |
| STORE-01/02/03 | upsert→get round-trip; upsert twice = one row (namespaced idempotency) | unit | `poetry run pytest tests/unit/storage -x` | ❌ Wave 0 |
| STORE-02 | `list_enabled` returns only `enabled=True` venues (typed-column query) | unit | dedicated test | ❌ Wave 0 |
| STORE-02 | secret denylist: `config_json` with `api_key` → `ValidationError` (rejection edge) | unit | `pytest.raises(ValidationError)` | ❌ Wave 0 |
| STORE-03 | subscriptions FK join answers "which strategies subscribe to symbol X" | unit | insert registry+subs, query by symbol | ❌ Wave 0 |
| STORE-04 | restart survival: write → dispose → re-open (file-backed) → read equal | unit | `tmp_path` file SQLite round-trip | ❌ Wave 0 |
| STORE-05 | backtest oracle byte-exact `46189.87730727451`; determinism double-run identical | integration | `poetry run pytest tests/integration/test_backtest_oracle.py` | ✅ exists |
| STORE-05 | inertness: backtest import pulls no new store module; `sql` cached_property unresolved | integration | `poetry run pytest tests/integration/test_okx_inertness.py` | ✅ exists (extend) |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit/storage tests/integration/storage/test_migrations.py -x`
- **Per wave merge:** `poetry run pytest tests/integration/test_backtest_oracle.py tests/integration/test_okx_inertness.py tests/unit/storage tests/integration/storage -x`
- **Phase gate:** full suite green before `/gsd-verify-work`; oracle byte-exact is a per-PLAN gate.

### Wave 0 Gaps
- [ ] `tests/unit/storage/test_system_store.py` — round-trip, namespaced-upsert idempotency (STORE-01)
- [ ] `tests/unit/storage/test_venue_store.py` — round-trip, `list_enabled`, secret-denylist rejection (STORE-02, D-05)
- [ ] `tests/unit/storage/test_strategy_registry_store.py` — registry+subscriptions FK join, restart survival (STORE-03/04, D-04)
- [ ] Extend `tests/integration/storage/test_migrations.py` — fix `:31` path; add single-head + full-chain + parity assertions (SQL-01/02)
- [ ] Extend `tests/integration/test_okx_inertness.py` — register-vs-build for the 3 new registrars + new store modules off the backtest path (success criterion #4)
- [ ] (Optional) wheel-exclusion gate via `poetry build` inspection (SQL-01)

*Existing `test_backtest_oracle.py` and the store `create_all` template (`test_durable_halt.py`) cover the
byte-exact + template mechanics; the gaps above are net-new store + gate coverage.*

## Security Domain

> `security_enforcement` is not disabled in `.planning/config.json` (defaults to enabled). This phase is
> storage infrastructure; the relevant controls are secret-exclusion (D-05) and injection-safe SQL (SEC-01).

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | yes | Write-time secret-key denylist in `VenueStore.config_json` → `ValidationError` (D-05) |
| V6/V7 Cryptography / Secret Management | yes | Credentials owned solely by connector/`OkxSettings` (`SecretStr`); never passed to any store; schema carries no payload/secret column (mirrors `HaltRecordStore` no-payload discipline, `halt_record_store.py:10-14`) |
| V4 Access Control | no | No auth surface in this phase |
| V2/V3 AuthN/Session | no | N/A |

### Known Threat Patterns
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Secret leaked into `config_json` blob | Information Disclosure | Structural (never passed) + defensive write-time denylist guard (D-05, defense-in-depth) |
| SQL injection via store inputs | Tampering | Parameterized SQLAlchemy Core against the constant `Table` object — never f-string SQL (SEC-01 / T-05.2-19) |
| Credential in `alembic.ini`/migrations | Information Disclosure | `sqlalchemy.url` stays blank; URL resolved lazily at runtime in `env.py:69-81` (SEC-01 / T-01-09) |

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Migrations inside the shipped package (`itrader/storage/migrations/`) | Project-root `migrations/`, out of the wheel | This phase (SQL-01/LR-18) | Migrations ship with the repo, not the installed package |
| N/A (SqlBackend) | `SqlEngine` (renamed in P3) | P3 (CTX-04) | New stores compose `sql_engine`, field/param named `sql_engine` |

**Deprecated/outdated:** the module docstrings and comments in `env.py`/`engine.py` still say "Plan 05" /
"Plan-05 Alembic" and reference `itrader/storage/migrations/env.py` by path — cosmetic; update the path
references in `engine.py:23` comment and `env.py` docstring during the move (Claude's discretion, no separate
decision).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Moving `migrations/` outside `itrader/` fully excludes it from the wheel given `packages=[{include="itrader"}]` with no other include/exclude rules | SQL-01 / Relocation | LOW — verified `packages` is the only relevant key (grep); if a future `include`/`exclude`/`MANIFEST` rule existed it could re-add it. Recommend the optional `poetry build` wheel-inspection gate to make it observable. |
| A2 | `alembic revision --autogenerate` renders `json_variant()` columns as `sa.JSON().with_variant(postgresql.JSONB(), "postgresql")` requiring the `postgresql` import | Pitfall 2 | LOW — inferred from the `types.py:67` definition + the baseline's custom-type-import precedent; the autogenerate-once draft (D-11) will show the exact render. Verify from the draft before splitting. |
| A3 | The `strategy_subscriptions` composite/surrogate PK choice is unconstrained by locked decisions | Pattern 2 / D-09 | LOW — D-09 leaves column choices to the planner; a natural composite PK `(strategy_name, venue, symbol, timeframe)` avoids autoincrement (single-UUIDv7 rule) but the planner should confirm. |

**All three are LOW-risk implementation-detail assumptions; every locked decision (D-01..D-11) is technically
feasible as written — no infeasibility flagged.**

## Open Questions

1. **Wheel-exclusion observability**
   - What we know: `packages=[{include="itrader"}]` + physical move outside `itrader/` excludes migrations.
   - What's unclear: whether the phase should add a build-inspection gate or trust the packaging config.
   - Recommendation: add a lightweight `poetry build` + wheel-listing assertion as an optional SQL-01 gate so
     "out of the wheel" is *observed*, not assumed (Nyquist — make the property samplable).

2. **`strategy_subscriptions` PK shape**
   - What we know: D-04 mandates the child table + FK; D-09 leaves column details to the planner.
   - What's unclear: composite natural PK vs a surrogate. A surrogate would need a UUIDv7 (single-ID rule) or
     autoincrement (rejected by D-06 spirit).
   - Recommendation: natural composite PK `(strategy_name, venue, symbol, timeframe)` — no new ID scheme, no
     autoincrement, directly indexable for the "who subscribes to X" query.

3. **Inertness gate extension shape (success criterion #4)**
   - What we know: `test_okx_inertness.py` forbids specific live modules on the backtest import path and does
     a register-vs-build assertion on `env.py`-style registrars.
   - What's unclear: whether the new store modules should be added to `_FORBIDDEN` (they pull SQLAlchemy) or
     whether only the register-vs-build (registrars stay Engine/Settings-free) is asserted.
   - Recommendation: do BOTH — add the 3 new store modules to `_FORBIDDEN` (they must not touch the backtest
     hot path) AND assert the 3 new registrars build only `Table` objects on a fresh MetaData (no Engine, no
     `Settings()`), matching the `env.py:55-58` register-vs-build discipline.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| SQLAlchemy | stores, types, parity gate | ✓ (pinned) | ^2.0.50 | — |
| Alembic | migration chain, gate | ✓ (pinned) | ^1.18.5 | — |
| SQLite (stdlib pysqlite) | all store tests (`:memory:` + file) | ✓ | CPython 3.13.1 | — |
| Docker/testcontainers Postgres | the Postgres parity arm | optional | — | Tests `pytest.skip` cleanly when Docker absent (`test_migrations.py:92-93`, D-11) — SQLite arm is the required gate |

No blocking missing dependencies. The Postgres arm is skip-clean by design; the SQLite arms are the
authoritative offline gates.

## Sources

### Primary (HIGH confidence — read directly from this repo)
- `itrader/storage/halt_record_store.py` (1-150) — the store template + registrar + secret-scrub discipline
- `itrader/storage/engine.py` (1-65) — `SqlEngine`, `NAMING_CONVENTION`
- `itrader/storage/types.py` (1-69) — `Uuid`, `UtcIsoText`, `json_variant()`
- `itrader/storage/__init__.py` (1-19) — spine barrel exports
- `itrader/storage/migrations/env.py` (1-123) — registrar `target_metadata`, lazy URL, extension point
- `alembic.ini` (1-90) — `script_location:8`, `prepend_sys_path:21`, blank `sqlalchemy.url:90`
- `itrader/storage/migrations/versions/d10_halt_records.py` — the authoring shape template
- `.../2cbf0bf6b0b6_operational_baseline.py` + `.../47f2b41f3ffe_portfolio_account_state.py` — custom-type import + `op.f()` naming + FK precedent
- `itrader/order_handler/storage/models.py` (1-80) — `dict[str, Table]` multi-table registrar precedent (D-04)
- `itrader/portfolio_handler/storage/sql_storage.py` (276-313) — delete-then-insert portable upsert
- `tests/integration/storage/test_migrations.py` (1-132) — the parity/single-head gate to extend; hardcoded `:31`
- `tests/integration/test_okx_inertness.py` (1-191) — register-vs-build inertness gate to extend
- `tests/integration/test_durable_halt.py` (1-176) — restart round-trip test pattern (`:memory:` caveat)
- `itrader/config/sql.py` (54-143) — `SqlSettings.default()` `:memory:` / file-backed drivers
- `itrader/strategy_handler/base.py:~191`, `:~631`; `strategies_handler.py:474` — D-06 identity (strategy_id ephemeral; addressed by name)
- `.planning/REQUIREMENTS.md`, `.planning/phases/04-…/04-CONTEXT.md`, `.planning/phases/03-…/03-CONTEXT.md`

### Secondary / Tertiary
- None required — every claim is grounded in repository source read this session.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — both deps already pinned; zero-new-dependency gate confirmed
- Relocation mechanics: HIGH — verified the only two path references (`alembic.ini:8`, `test_migrations.py:31`) and absolute-import inertness of `env.py`
- Store template + registrar: HIGH — literal clone of a shipped, tested store
- Migration authoring: HIGH — three shipped revisions read as templates incl. FK + custom-type gotchas
- Parity/gate extension: HIGH — the existing gate test structure read end-to-end
- Wheel-exclusion: MEDIUM — packaging config verified but not observed via a build (A1)

**Research date:** 2026-07-09
**Valid until:** ~2026-08-09 (stable internal infra; re-verify only if `storage/` or `alembic.ini` change)
