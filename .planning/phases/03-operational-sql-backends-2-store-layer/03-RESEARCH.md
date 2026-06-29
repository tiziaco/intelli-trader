# Phase 3: Operational SQL Backends (#2 — store layer) - Research

**Researched:** 2026-06-29
**Domain:** SQLAlchemy 2.0 Core persistence backends on a shared spine (Postgres operational store)
**Confidence:** HIGH (all findings verified by direct codebase read of the ABCs, domain objects, the
Phase-1 spine, and the Phase-2 results-store precedent; library versions confirmed via Poetry)

## Summary

This phase fills three already-stubbed storage seams (`OrderStorage`, `PortfolioStateStorage`,
`SignalStore`) with one concrete `Sql<Concern>Storage` class each, on the Phase-1 `SqlBackend`
spine, validated on testcontainers Postgres. The work is almost entirely **pattern replication**:
Phase 2 already shipped `SqlResultsStore` (`itrader/results/sql_storage.py` + `models.py`), which is
the exact, in-repo, strict-clean precedent for everything this phase needs — Core `Table` definitions
on the shared `MetaData`, a `build_*_tables(metadata)` idempotent registrar, hand-written
`to_row`/`from_row` converters, `create_all(checkfirst=True)` in tests, parameterized Core
`insert`/`select`, and a deterministic round-trip test. The planner should treat
`itrader/results/sql_storage.py` and `itrader/results/models.py` as the reference implementation and
mirror their structure per concern.

The real engineering content (the "Claude's Discretion" items) is in five places that the results
store did **not** have to solve: (1) the exact column-per-field mapping for three richer domain
objects — including the `Order` self-referential bracket FK and the normalized portfolio
sub-collection tables; (2) wiring `env.py`'s `target_metadata` from the bare `MetaData()` it ships
today to a fully-registered operational MetaData so `--autogenerate` produces the first baseline
migration deterministically; (3) a round-trip test whose **object-equality assertion differs per
domain object** because `Order`/`Transaction`/`SignalRecord` carry field-wise `__eq__` while
`Position` does not; (4) the **`PortfolioStateStorage` ABC has no `portfolio_id` parameter on any
method** — the in-memory backend is one-instance-per-portfolio, so the SQL backend must bind a
`portfolio_id` at construction and scope every query to it; and (5) keeping the new modules in
`mypy --strict` from day one (the results store and the lifted `sql_store.py` both prove this is the
house standard).

**Primary recommendation:** Mirror `itrader/results/{models,sql_storage}.py` three times (one
`models.py`-style table builder + one `sql_storage.py` per concern), bind `SqlPortfolioStateStorage`
to a `portfolio_id` at construction, persist `Order` brackets via a nullable self-referential
`parent_order_id` FK (deriving `child_order_ids` by query), run money round-trip tests on the
**Postgres arm only** (SQLite `Numeric` decays to float), and register all operational tables on a
naming-conventioned MetaData that `env.py` imports for autogenerate.

## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01 — Fully typed relational columns** per domain object: every field becomes a typed column
  (money → `Numeric`, ids → `sqlalchemy.Uuid`, business-time → uniform ISO/text per Phase-1 D-04,
  enums → text per D-07). NO JSON-document/blob-per-record rows. (A single ancillary `config`/params
  dict column as `json_variant()` is NOT a "document row" — see Architecture note; the results store
  set the precedent with `runs.settings`/`run_portfolios.params`.)
- **D-02 — Order brackets via a self-referential, nullable, indexed `parent_order_id` FK** on child
  rows (children point at parent). Whole bracket fetched in one indexed query
  (`WHERE id = :id OR parent_order_id = :id`); adding a child is a single `INSERT`; FK prevents
  orphans. NOT a `child_ids` array column.
- **D-03 — Normalized table-per-collection**, all keyed by `portfolio_id`: `positions` (with an
  `is_open` flag covering open + closed), `transactions`, `cash_reservations`
  (`reference_id → amount`), `locked_margin` (`position_id → amount`), `cash_operations`,
  `equity_snapshots`. NOT a consolidated snapshot blob, NOT a JSON ledger. Money is `Numeric`
  throughout.
- **D-04 (mapping) — SQLAlchemy Core** `Table` on the shared `MetaData` + explicit hand-written
  `to_row`/`from_row` per concern. NOT the ORM declarative/`Session` layer. Domain objects stay
  frozen/persistence-ignorant (no `Mapped[...]`).
- **D-05 — New `sql_storage.py` per domain `storage/` package**, one class each: `SqlOrderStorage`,
  `SqlPortfolioStateStorage`, `SqlSignalStorage`. **Retire** `PostgreSQLOrderStorage` /
  `postgresql_storage.py`.
- **D-06 (factory arm — OWNER OVERRIDE) — route the existing `'live'` arm only** to the SQL backend;
  `'backtest'`/`'test'` stay on the in-memory backend, untouched. **Do NOT add a `'postgresql'`
  arm.** This deliberately diverges from ROADMAP Phase 3 SC1's `postgresql`/`live` wording.
- **D-07 (enums) — stored as plain text (`String`) = the enum's `.value`**, validated on read via the
  existing `order_*_map` string→enum converters (and the enums' own `_missing_`). NOT Postgres-native
  `ENUM`, NOT a `CHECK` constraint.
- **D-08 — bake in Phase-4 indexes only** (no Phase-4 behavior): `is_open` (positions) + `status`
  (orders) columns exist, plus indexes `(portfolio_id, status)` on orders, `(portfolio_id, is_open)`
  on positions, and a `parent_order_id` index.
- **D-09 — the `MetaData` is the single source of truth.** Tests/dev: `metadata.create_all(engine)`.
  Deploy/live: Alembic — Phase 3 **autogenerates the first operational baseline migration** from the
  MetaData into the framework's Phase-1 Alembic skeleton (`itrader/storage/migrations/`,
  `render_as_batch=True`). The framework owns the operational-table chain; do NOT run migrations
  inside tests; do NOT author a second chain.
- **D-10 — round-trip tests** per concern on testcontainers Postgres: write → read → assert
  reconstructed object equality (`obj2 == obj`), money asserted as exact `Decimal`, UUIDv7 ids
  value-equal, plus a determinism check (two runs encode identical bytes).
- **Carried from Phase 1 (locked):** composition not inheritance (each `Sql<Concern>Storage`
  *composes* the shared `SqlBackend`); ids via `sqlalchemy.Uuid(as_uuid=True)`; business-time via
  uniform ISO/text (`UtcIsoText`); no wall-clock writes; single UUIDv7 scheme; no DB autoincrement /
  second ID scheme; money = Postgres-native `Numeric`, no float-for-money, no `DecimalAsText`;
  backend selection at wiring. Recurring gates: SMA_MACD oracle byte-exact **134 /
  `46189.87730727451`**, no W1/W2 regression vs v1.5 baseline (**15.7 s / 152.8 MB**),
  `mypy --strict` clean, full suite green under `filterwarnings=["error"]` with no new broad ignore.

### Claude's Discretion (settled in this research — see body)

- Exact column lists/types per `Table` (beyond the money/id/enum/time rules) → **§Standard Stack /
  §Architecture (Table Maps)**. Settled with one open item flagged per object.
- Whether `SqlPortfolioStateStorage` needs a `portfolios` parent table or keys off `portfolio_id` →
  **keys off a `portfolio_id` bound at construction; no parent table required** (§Pitfall 1). A
  parent table is optional FK hygiene, not required by the ABC.
- Alembic `env.py` autogenerate wiring + migration content → **§Architecture (Autogenerate Wiring)**.
- Whether the new modules enter `mypy --strict` now → **YES, now** (§State of the Art; results store
  + lifted `sql_store.py` are the precedent).
- Retired `postgresql_storage.py` handling → **delete** (§Don't Hand-Roll / §Runtime State
  Inventory; no symbol importer exists outside the factory).

### Deferred Ideas (OUT OF SCOPE)

- Live write-through / working-set cache / purge-on-terminalize / read-through / restart rehydration
  → Phase 4. Phase 3 only shapes schema/indexes (D-08), builds none of the behavior.
- A `'postgresql'` factory arm → explicitly NOT added (D-06).
- FastAPI application layer + app-specific Alembic chain → downstream app concern (captured only as
  the lens behind D-01/D-02/D-03/D-09).

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| OPS-01 | `SqlOrderStorage` implements `OrderStorage` on Postgres; fills the `PostgreSQLOrderStorage` stub; selectable via `OrderStorageFactory` (`'live'` arm, D-06) | §Architecture: `orders` table map (incl. bracket FK D-02 + `order_state_changes` child); ~15-method ABC mapped to Core SELECT/WHERE; §Don't Hand-Roll: stub deletion |
| OPS-02 | `SqlPortfolioStateStorage` implements `PortfolioStateStorage` on Postgres | §Architecture: six normalized tables (D-03); §Pitfall 1: ABC has no `portfolio_id` param → bind at construction; equality nuance for `Position` (§Pitfall 3) |
| OPS-03 | `SqlSignalStorage` implements `SignalStore` on Postgres | §Architecture: `signals` table map (4-method ABC); `config` dict → `json_variant()` |
| OPS-04 | Operational money persists as Postgres-native `Numeric`, exact `Decimal` round-trip; testcontainers-validated | §Standard Stack: `Numeric(asdecimal=True)` unbounded; §Pitfall 2: SQLite `Numeric`→float → money tests Postgres-only; §Validation Architecture |
| GATE-01 (recurring) | Oracle byte-exact + no W1/W2 regression — persistence inert on hot path | §Architecture: backtest arm imports no SQLAlchemy symbol (factory `'backtest'` untouched); new `sql_storage.py` NOT re-exported from package `__init__` |
| GATE-02 (recurring) | DB round-trip tests on testcontainers Postgres; `mypy --strict` clean; `filterwarnings=["error"]` green | §Validation Architecture; §Pitfall 4 (ResourceWarning under `filterwarnings=["error"]`) |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Order mirror persistence | Storage backend (`order_handler/storage/sql_storage.py`) | Spine (`itrader/storage`) | The ABC seam already exists; SQL backend composes the spine, owns `orders` + `order_state_changes` tables |
| Portfolio-state persistence | Storage backend (`portfolio_handler/storage/sql_storage.py`) | Spine | Six normalized tables, all bound to one `portfolio_id` per backend instance |
| Signal-record persistence | Storage backend (`strategy_handler/storage/sql_storage.py`) | Spine | Single `signals` table; `config` dict in a `json_variant` column |
| Schema source of truth | Shared `MetaData` (`SqlBackend.metadata`) | — | D-09: both `create_all` (tests) and Alembic (deploy) derive from it |
| Deploy migrations | Alembic chain (`itrader/storage/migrations/`) | env.py `target_metadata` | Framework owns the operational-table chain; one chain (MIG-01) |
| Backend selection | The three `storage_factory.py` files (`'live'` arm) | Composition root (Phase 4) | Wiring-time string-arm; Phase 3 fills the arm, Phase 4 wires it onto the live path |
| Money fidelity | Postgres `Numeric` column type | — | Exact `Decimal` round-trip; money never touches SQLite (OPS-04) |

## Standard Stack

All required libraries were installed in Phase 1 behind the supply-chain gate. **No new packages.**

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy (Core) | 2.0.50 `[VERIFIED: poetry run python -c import]` | `Table`/`MetaData`/`insert`/`select`, `Numeric`, `Uuid`, `ForeignKey`, `Index` | The whole spine is Core (no Session); D-04 mandates Core; results store + `sql_store.py` both use it |
| Alembic | 1.18.5 `[VERIFIED: poetry]` | Autogenerate the operational baseline migration into the Phase-1 skeleton | The chain + `env.py` + `render_as_batch=True` already exist (MIG-01) |
| testcontainers[postgresql] | 4.14.2 `[CITED: STATE 01-01]` | Session-scoped Postgres `Engine` fixture (`pg_engine`) | Gate-(b) substrate; already wired in `tests/integration/storage/conftest.py` (D-10/D-11) |
| psycopg2-binary | ^2.9.12 `[CITED: pyproject]` | `postgresql+psycopg2` driver (the `SqlSettings` Postgres arm) | Already the operational driver token in `config/sql.py` |

### Supporting (spine helpers — import from `itrader.storage`)
| Symbol | Purpose | When to Use |
|--------|---------|-------------|
| `Uuid` (re-exported `sqlalchemy.Uuid`) | `Uuid(as_uuid=True)` → native `UUID` on Postgres, value-equal both dialects (D-03) | EVERY id column (`id`, `portfolio_id`, `strategy_id`, `fill_id`, `parent_order_id`, …) |
| `UtcIsoText` | Business-time as ISO-8601 UTC TEXT, deterministic bytes, rejects naive datetimes | EVERY datetime column (`time`, `created_at`, `entry_date`, `timestamp`, …) |
| `json_variant()` | `JSON` on SQLite / `JSONB` on Postgres | The ONE ancillary dict column: `signals.config` (mirrors `runs.settings`) |
| `SqlBackend` | Engine + shared `MetaData`; composed by each backend | Constructor arg of each `Sql<Concern>Storage` |

### Money column type (OPS-04)
Use `sqlalchemy.Numeric` with **no precision/scale** (unbounded `NUMERIC` on Postgres) and the
default `asdecimal=True`, which returns exact `Decimal` on read. `[CITED: docs.sqlalchemy.org —
Numeric type, asdecimal default True]` `[ASSUMED]` that unbounded NUMERIC is preferred over a fixed
`Numeric(38, 18)` — both round-trip exactly on Postgres; unbounded avoids ever clipping a 28-digit
`Decimal` from `core/money.py`. The planner may pin a precision if a column constraint is desired;
flagged in §Assumptions Log (A1). There is **no money `TypeDecorator`** on the spine by design
(`types.py` D-13) — money lands only on Postgres-native `Numeric`, never on SQLite.

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Core `Table` + hand converters | ORM declarative + `Session` | LOCKED OUT (D-04): would need a separate `*Row` mapped class anyway (domain objects can't carry `Mapped[...]`), adding a paradigm without removing the converter |
| `Numeric` for money | `DecimalAsText` TypeDecorator | LOCKED OUT: unneeded — money is Postgres-only, native `Numeric` is exact |
| `String` enum `.value` | Postgres `ENUM` / `CHECK` | LOCKED OUT (D-07): ALTER-TYPE friction, Postgres-only, breaks the SQLite-capable spine |
| Self-ref `parent_order_id` FK | `child_order_ids` array column | LOCKED OUT (D-02): array needs read-modify-write to add a child (race-prone on the live path) |

**Installation:** none — all dependencies present since Phase 1.

## Package Legitimacy Audit

**Not applicable — this phase installs no external packages.** Every library it uses (SQLAlchemy,
Alembic, testcontainers, psycopg2-binary) was added and gated in Phase 1 and is already in
`poetry.lock`. slopcheck was therefore not run (nothing to verify). If the planner discovers a need
for a new dependency, the Package Legitimacy Gate must be run before adding it.

## Architecture Patterns

### System Architecture Diagram

```
                       WIRING (composition root)
                              │
              SqlSettings(driver=POSTGRESQL_PSYCOPG2)        ← config/sql.py (port 5544)
                              │  .engine_url()
                              ▼
                        SqlBackend  ──────────────► Engine (psycopg2 pool)
                         │  .metadata (shared MetaData, naming_convention)
                         │
        ┌────────────────┼─────────────────────────┬───────────────────────┐
        ▼                ▼                          ▼                       ▼
 SqlOrderStorage  SqlPortfolioStateStorage    SqlSignalStorage      (SqlResultsStore — Phase 2)
  composes backend  composes backend +          composes backend
  build_order_*     bound portfolio_id          build_signal_*
        │           build_portfolio_*                 │
        ▼                ▼                            ▼
   orders                positions                  signals
   order_state_changes   transactions                 │
        │  parent_order_id FK   cash_reservations      │ config → json_variant
        └──self-ref            locked_margin
                               cash_operations
                               equity_snapshots
                              (all WHERE portfolio_id = bound id)

  ── runtime write/read: Core insert()/select() with bindparam, engine.begin() txn
  ── tests:  metadata.create_all(engine)            [no Alembic]   ← testcontainers Postgres
  ── deploy: env.py target_metadata = build_*_tables(MetaData) → alembic --autogenerate → upgrade head

  BACKTEST PATH (unchanged): factory 'backtest' → InMemory*Storage → imports NO SQLAlchemy symbol
                             (GATE-01 hot-path inertness is structural, not flagged)
```

### Recommended file structure (mirrors the Phase-2 results store)
```
itrader/
├── storage/
│   ├── backend.py            # SqlBackend (consider adding MetaData naming_convention — see Pitfall 5)
│   └── migrations/
│       ├── env.py            # EDIT: target_metadata = registered operational MetaData (autogenerate)
│       └── versions/
│           └── <rev>_operational_baseline.py   # NEW: autogenerated, then reviewed
├── order_handler/storage/
│   ├── models.py             # NEW: build_order_tables(metadata) -> {"orders", "order_state_changes"}
│   ├── sql_storage.py        # NEW: SqlOrderStorage(OrderStorage) — to_row/from_row
│   ├── storage_factory.py    # EDIT: 'live' arm -> SqlOrderStorage (D-06); drop postgresql import
│   └── postgresql_storage.py # DELETE (D-05)
├── portfolio_handler/storage/
│   ├── models.py             # NEW: build_portfolio_tables(metadata) -> 6 tables (D-03)
│   ├── sql_storage.py        # NEW: SqlPortfolioStateStorage(PortfolioStateStorage), bound portfolio_id
│   └── storage_factory.py    # EDIT: 'live' arm -> SqlPortfolioStateStorage
└── strategy_handler/storage/
    ├── models.py             # NEW: build_signal_tables(metadata) -> {"signals"}
    ├── sql_storage.py        # NEW: SqlSignalStorage(SignalStore)
    └── storage_factory.py    # EDIT: 'live' arm -> SqlSignalStorage
```
**Indentation:** all of `*/storage/`, `config/`, `itrader/storage/` are **4 spaces** (results store +
spine confirm it). `portfolio_handler/base.py` has a tab-import / 4-space-class mix — match
surrounding lines exactly. NEW files: 4 spaces throughout (match the results-store house style).

### Pattern 1: `build_*_tables(metadata)` idempotent registrar
**What:** a module-level function that registers the concern's `Table`s on the injected
`backend.metadata`, reusing an already-registered table by name (shared-backend safety).
**When:** every concern (mirror `itrader/results/models.py::build_results_tables`).
```python
# Source: itrader/results/models.py (in-repo precedent, verified)
def build_order_tables(metadata: MetaData) -> dict[str, Table]:
    tables: dict[str, Table] = {}
    if "orders" in metadata.tables:
        tables["orders"] = metadata.tables["orders"]
    else:
        tables["orders"] = Table("orders", metadata, ...columns...)
    # ... order_state_changes similarly
    return tables
```

### Pattern 2: `Sql<Concern>Storage` composition + `create_all(checkfirst=True)`
**What:** constructor takes the `SqlBackend`, registers tables, idempotently creates schema.
```python
# Source: itrader/results/sql_storage.py (verified)
class SqlOrderStorage(OrderStorage):
    def __init__(self, backend: SqlBackend) -> None:
        self.backend = backend
        self.engine = backend.engine
        tables = build_order_tables(backend.metadata)
        self.orders = tables["orders"]
        self.state_changes = tables["order_state_changes"]
        backend.metadata.create_all(self.engine, checkfirst=True)   # tests; deploy uses Alembic
        self.logger = get_itrader_logger().bind(component="SqlOrderStorage")
    def dispose(self) -> None:
        self.backend.dispose()   # WR-03: delegate, never engine.dispose() directly
```
**Note:** `create_all(checkfirst=True)` is the test/dev path (D-09). It is harmless against a
migration-managed Postgres schema (checkfirst skips existing tables), but the **deploy** schema comes
from `alembic upgrade head`, not from `create_all`.

### Pattern 3: parameterized Core read/write (NEVER f-string SQL)
```python
# Source: itrader/results/sql_storage.py (verified) — bindparam + constant Table objects
stmt = select(self.orders).where(self.orders.c.id == bindparam("id"))
with self.engine.connect() as conn:
    row = conn.execute(stmt, {"id": order_id}).mappings().first()
```

### Table Maps (Claude's Discretion — settled)

Legend: `Uuid` = `Uuid(as_uuid=True)`; `Time` = `UtcIsoText`; `Num` = `Numeric` (asdecimal,
unbounded); `Str` = `String`; enums stored as `.value` text (D-07).

#### `orders` (OPS-01, from `order_handler/order.py::Order`)
| Column | Type | Notes |
|--------|------|-------|
| `id` | Uuid PK | `Order.id` (OrderId) |
| `time` | Time | business time |
| `type` | Str | `OrderType.value` (read back via `OrderType(value)` / `order_type_map`) |
| `status` | Str | `OrderStatus.value` |
| `ticker` | Str | indexed component of D-08 `(portfolio_id, status)` is on status, not ticker |
| `action` | Str | `Side.value` |
| `price` | Num | Decimal |
| `quantity` | Num | Decimal |
| `exchange` | Str | |
| `strategy_id` | Uuid | |
| `portfolio_id` | Uuid | indexed; composite index `(portfolio_id, status)` (D-08) |
| `filled_quantity` | Num | Decimal |
| `created_at` | Time | event-derived |
| `updated_at` | Time | |
| `filled_at` | Time NULL | |
| `cancelled_at` | Time NULL | |
| `expired_at` | Time NULL | |
| `expiry_time` | Time NULL | |
| `parent_order_id` | Uuid NULL, FK `orders.id`, **index** | D-02 self-referential bracket |
| `rejection_reason` | Str NULL | |
| `modification_count` | Integer | |
| `last_modification_time` | Time NULL | |
| `leverage` | Num | Decimal (default `1`) |
| `trail_type` | Str NULL | `TrailType.value` |
| `trail_value` | Num NULL | Decimal |

- **`child_order_ids`** (a `List[OrderId]` field): **NOT a column** (D-02). On read, `from_row`
  populates it by querying `SELECT id FROM orders WHERE parent_order_id = :id`. So
  `get_order_by_id` issues a second (indexed) query to rebuild the children list, OR leaves it `[]`
  and exposes a dedicated bracket fetch — see Pitfall 6.
- **`state_changes`** (a `List[OrderStateChange]`): the `OrderStorage` ABC's `get_order_history`
  implies a child table. **Recommend a `order_state_changes` child table** (D-01 "fully typed",
  matches the in-memory seam-audit comment "get_order_history implies a state-change child table").
  Columns: `order_id` Uuid FK, `seq` Integer (ordering), `from_status` Str NULL, `to_status` Str,
  `timestamp` Time, `reason` Str, `triggered_by` Str (`OrderTriggerSource.value`),
  `additional_data` `json_variant()` NULL. PK `(order_id, seq)`. **This is load-bearing for D-10
  equality** — see Pitfall 3 (`Order.__eq__` is field-wise and includes `state_changes`).

#### `positions` (OPS-02, from `portfolio_handler/position/position.py::Position`)
Holds open + closed (D-03 `is_open` flag). Keyed by `portfolio_id` (bound) — see Pitfall 1.
| Column | Type | Notes |
|--------|------|-------|
| `id` | Uuid PK | `Position.id` (PositionId) |
| `portfolio_id` | Uuid | indexed; composite `(portfolio_id, is_open)` (D-08) |
| `ticker` | Str | open-position lookup: `WHERE portfolio_id=? AND ticker=? AND is_open=true` |
| `side` | Str | `PositionSide.value` |
| `leverage` | Num | Decimal |
| `current_price` | Num | |
| `current_time` | Time | |
| `buy_quantity` `sell_quantity` `avg_bought` `avg_sold` `buy_commission` `sell_commission` | Num | Decimal |
| `entry_date` | Time | |
| `exit_date` | Time NULL | |
| `is_open` | Boolean | indexed (D-08) |
| `_last_accrual_time` | Time NULL | CARRY-01 marker; persist for fidelity |
- `_net_quantity_cache` / `_avg_price_cache`: **NOT persisted** (derived caches, reset on read by
  reconstructing the object via the normal constructor; both default `None`).
- **Equality nuance:** `Position` is a plain `object` with NO `__eq__` → `obj2 == obj` is identity
  (always False). The round-trip test MUST compare a projection (`to_dict()` + `id` + `leverage` +
  `_last_accrual_time`), not `==`. See Pitfall 3.

#### `transactions` (OPS-02, from `portfolio_handler/transaction/transaction.py::Transaction`)
| Column | Type | Notes |
|--------|------|-------|
| `id` | Uuid PK | TransactionId |
| `portfolio_id` | Uuid | indexed (bound) |
| `fill_id` | Uuid | |
| `position_id` | Uuid NULL | |
| `time` | Time | |
| `type` | Str | `TransactionType.value` (lowercase `"buy"`/`"sell"`) |
| `ticker` | Str | |
| `price` `quantity` `commission` | Num | Decimal |
| `leverage` | Num | Decimal |
- `Transaction` is a `msgspec.Struct` → field-wise `==`; round-trip `obj2 == obj` works directly.

#### `cash_reservations` (OPS-02, D-03 `reference_id → amount`)
| Column | Type | Notes |
|--------|------|-------|
| `portfolio_id` | Uuid PK-part | bound |
| `reference_id` | Str PK-part | ABC types it `str` |
| `amount` | Num | FULL precision (no quantize) |
Composite PK `(portfolio_id, reference_id)`.

#### `locked_margin` (OPS-02, D-03 `position_id → amount`)
| Column | Type | Notes |
|--------|------|-------|
| `portfolio_id` | Uuid PK-part | bound |
| `position_id` | Str PK-part | **ABC types `position_id: str`** (not Uuid) — store `String` to honor the exact key the caller passes (`add_locked_margin(position_id: str, ...)`). Flag A2. |
| `amount` | Num | FULL precision |
Composite PK `(portfolio_id, position_id)`.

#### `cash_operations` (OPS-02, from `cash/cash_manager.py::CashOperation`)
| Column | Type | Notes |
|--------|------|-------|
| `operation_id` | Uuid PK | |
| `portfolio_id` | Uuid | indexed — **NOT on the object**; supplied by the bound backend (Pitfall 1) |
| `operation_type` | Str | `CashOperationType.value` |
| `amount` | Num | Decimal |
| `timestamp` | Time | event-derived |
| `description` | Str | |
| `fee` | Num | Decimal |
| `reference_id` | Str NULL | |
| `balance_before` | Num NULL | |
| `balance_after` | Num NULL | |
- `CashOperation` is a `@dataclass` → field-wise `==`; round-trip works (the persisted+rebuilt object
  must omit the injected `portfolio_id`, which is not a `CashOperation` field).

#### `equity_snapshots` (OPS-02, from `metrics/metrics_manager.py::PortfolioSnapshot`)
| Column | Type | Notes |
|--------|------|-------|
| `portfolio_id` | Uuid | indexed (bound) |
| `seq` | Integer PK-part | **insertion-order tiebreak** — PortfolioSnapshot has NO id and timestamps can tie; do NOT use Integer autoincrement (single-UUID rule) — write an explicit monotonic `seq` per portfolio. See Pitfall 7 / A3. |
| `timestamp` | Time | |
| `total_equity` `cash_balance` `positions_value` `unrealized_pnl` `realized_pnl` `total_pnl` `portfolio_return` | Num | Decimal |
| `open_positions_count` | Integer | |
| `benchmark_return` | Num NULL | |
PK `(portfolio_id, seq)`. `get_snapshots()` reads `ORDER BY portfolio_id, seq`.
- `PortfolioSnapshot` is a `@dataclass` → field-wise `==`; round-trip works.

#### `signals` (OPS-03, from `strategy_handler/signal_record.py::SignalRecord`)
| Column | Type | Notes |
|--------|------|-------|
| `signal_id` | Uuid PK | |
| `strategy_id` | Uuid | indexed (`by_strategy`) |
| `ticker` | Str | indexed (`by_ticker`) |
| `time` | Time | |
| `action` | Str | `Side.value` |
| `order_type` | Str | `OrderType.value` |
| `stop_loss` | Num NULL | Decimal (money on Postgres) |
| `take_profit` | Num NULL | Decimal |
| `exit_fraction` | Num | Decimal |
| `quantity` | Num NULL | Decimal |
| `entry_price` | Num NULL | Decimal |
| `config` | `json_variant()` | plain params dict snapshot (strategy.to_dict()) — the ONE allowed dict column (mirrors `runs.settings`) |
- `SignalRecord` is a frozen `msgspec.Struct` → field-wise `==`; `config` dict equality is
  order-independent so round-trip `==` works. For the **byte-determinism** check, JSON key ordering
  matters — see Pitfall 8.

### Autogenerate Wiring (Claude's Discretion — settled)

`env.py` today sets `target_metadata = MetaData()` (a deliberately bare, empty MetaData so no tables
existed in the Phase-1 chain). Phase 3 must point it at a MetaData with all operational tables
registered:

```python
# Source: env.py current shape + results-store build_*_tables pattern
from sqlalchemy import MetaData
from itrader.order_handler.storage.models import build_order_tables
from itrader.portfolio_handler.storage.models import build_portfolio_tables
from itrader.strategy_handler.storage.models import build_signal_tables

target_metadata = MetaData(naming_convention=NAMING_CONVENTION)   # see Pitfall 5
build_order_tables(target_metadata)
build_portfolio_tables(target_metadata)
build_signal_tables(target_metadata)
```
Then generate:
```bash
poetry run alembic -c itrader/storage/migrations/alembic.ini revision \
  --autogenerate -m "operational baseline"
# (alembic.ini path per Phase-1 skeleton; sqlalchemy.url is BLANK there — env.py resolves it lazily)
```
- Autogenerate needs a **live Postgres connection** (it reflects the empty DB to diff). Use the
  testcontainers Postgres or a local Postgres on port 5544; pass the URL via the Alembic `Config`
  override (`-x` / `sqlalchemy.url`) so no credential lands in `alembic.ini` (SEC-01). Review the
  emitted migration by hand (autogenerate is a draft, not gospel — confirm self-ref FK, indexes,
  `Numeric`, `UtcIsoText` rendered as the right type).
- **Determinism:** a `naming_convention` on the MetaData makes index/constraint names stable across
  regenerations (Pitfall 5). Without it, autogenerate emits provider-default names that can churn.
- `render_as_batch=True` is already set in both env.py configure paths.
- **Do NOT run migrations in tests** (D-09): the round-trip tests use `create_all`. Optionally add a
  drift guard test that asserts `--autogenerate` against the migrated schema yields an empty diff
  (extend the existing `test_migrations.py`); flag as nice-to-have, not required by D-09.

### Round-Trip Test Pattern (Claude's Discretion — settled)

Reuse the Phase-1 `tests/integration/storage/conftest.py` `engine` indirect fixture. **Money tests
run on the `"postgres"` arm only** (SQLite `Numeric` decays to float — Pitfall 2). UUID/time/enum
round-trip may also run on `"sqlite"`.

Build a `SqlBackend` whose engine is the testcontainers DB. Two options:
1. **Add a `pg_backend` fixture** (recommended): wrap the container connection URL into
   `SqlSettings(driver=POSTGRESQL_PSYCOPG2, url=SecretStr(container_url))` → `SqlBackend(settings)`.
   The verbatim-URL escape hatch (`config/sql.py::engine_url` returns `url` as-is) makes this clean
   and avoids needing a password. (The session `pg_engine` fixture currently yields an `Engine`, not
   a URL — either expose the URL or construct a parallel backend to the same container DB.)
2. Construct `SqlBackend` directly and monkey-set `.engine = pg_engine` — simpler but bypasses the
   settings path; acceptable for a test.

Assertion contract **per object** (this is the subtle part — see Pitfall 3):
| Object | `__eq__`? | Round-trip assertion |
|--------|-----------|----------------------|
| `Order` (dataclass) | field-wise | `obj2 == obj` works ONLY if `state_changes`, all `*_at`, `child_order_ids`, `modification_count` round-trip. Persist the state-change child table; rebuild `child_order_ids` by query. |
| `OrderStateChange` (dataclass) | field-wise | compared transitively inside `Order.__eq__` |
| `Transaction` (msgspec) | field-wise | `obj2 == obj` direct |
| `SignalRecord` (frozen msgspec) | field-wise | `obj2 == obj` direct (config dict eq is order-independent) |
| `Position` (plain object) | **identity only** | `obj2 == obj` is ALWAYS False — assert on a projection: `obj2.to_dict() == obj.to_dict()` plus `obj2.leverage == obj.leverage`, `obj2.id == obj.id`, `obj2._last_accrual_time == obj._last_accrual_time` |
| `CashOperation` (dataclass) | field-wise | `obj2 == obj` (injected `portfolio_id` is not a field) |
| `PortfolioSnapshot` (dataclass) | field-wise | `obj2 == obj` |

Money exactness: `assert obj2.price == obj.price and isinstance(obj2.price, Decimal)` (OPS-04).
Ids: `assert obj2.id == obj.id and isinstance(obj2.id, uuid.UUID)` (SPINE-03).
Determinism: mirror Phase-1's two-bind `UtcIsoText` test; for `Numeric` an identical `Decimal`
encodes identically; for `signals.config` assert deterministic JSON (Pitfall 8).

### Factory wiring (`'live'` arm — D-06)

The three `storage_factory.py` files currently route `'live'` to a stub / `NotImplementedError`.
After Phase 3 they route `'live'` to the new `Sql<Concern>Storage`. **The backends need a
`SqlBackend`, not a raw `db_url`** (the Phase-1 `db_url` parameter predates `SqlSettings`).
Recommended signature change: the factory `'live'` arm accepts/constructs a shared `SqlBackend`
(e.g. `create('live', backend=...)` or builds `SqlBackend(SqlSettings(driver=POSTGRESQL_PSYCOPG2))`).
A **single shared `SqlBackend`** injected into all three factories is correct — one engine/pool and
one `MetaData` on which all operational tables co-register (which `create_all`/autogenerate both
want). `SqlPortfolioStateStorage` additionally needs the bound `portfolio_id` (Pitfall 1), so its
factory arm takes `portfolio_id` too. **Phase 3 builds the classes + arms; Phase 4 wires the live
composition root** — Phase 3 does not change the hardcoded `'backtest'` call sites in
`portfolio.py` / `backtest_trading_system.py` / `live_trading_system.py`.

### Anti-Patterns to Avoid
- **Re-exporting `Sql<Concern>Storage` from the package `__init__`.** The results store is
  deliberately quarantined (NOT in `itrader/results/__init__.py`) so the backtest import path stays
  SQL-free (GATE-01). Keep the new modules import-quarantined the same way.
- **Touching the `'backtest'`/`'test'` factory arm or the in-memory backends.** They must remain
  byte-identical (oracle inertness). The in-memory backend imports no SQLAlchemy symbol — keep it so.
- **Integer autoincrement PKs** (e.g. for `equity_snapshots`) — violates the single-UUID / no-second-
  ID-scheme rule. Use a UUID PK or an explicit per-portfolio `seq` written by the backend.
- **f-string / string-built SQL** — always parameterized Core (`bindparam`, constant `Table`
  objects). SEC-01 precedent.
- **`Decimal(float)`** anywhere — money enters via the domain objects' `to_money` already; the
  backend only moves `Decimal` ↔ `Numeric`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cross-dialect UUID storage | per-dialect TEXT/BLOB switch | `itrader.storage.Uuid` (`Uuid(as_uuid=True)`) | Already round-trips value-equal both dialects (D-03); hand-rolling reintroduces the encoding bug |
| Business-time storage | raw `String` + manual isoformat | `itrader.storage.UtcIsoText` | Deterministic bytes, rejects naive datetimes, instant-preserving (D-04/D-05) |
| Portable JSON column | `JSON` vs `JSONB` branching | `itrader.storage.json_variant()` | One call handles both dialects |
| Table registrar | ad-hoc `Table(...)` at import | `build_*_tables(metadata)` idempotent fn | Matches results store; safe on a shared backend; importable by env.py for autogenerate |
| Schema migration authoring | hand-written `op.create_table(...)` | `alembic revision --autogenerate` from the MetaData | D-09: MetaData is the single source of truth |
| Round-trip Postgres fixture | new container setup | `pg_engine` / `engine` fixtures (conftest.py) | Already session-scoped, Dockerless-skip (D-10/D-11) |
| Retired stub | deprecate-and-re-export `PostgreSQLOrderStorage` | **delete it** | No code imports the symbol (only the factory `'live'` arm references it, which is being rewritten) — a re-export would keep a dead, mypy-overridden module alive |

**Key insight:** Phase 2 already solved every cross-cutting concern (codec determinism, Core
composition, idempotent table build, quarantine, strict typing). The novel work is purely the
domain-object → column mapping and the four object-specific equality contracts.

## Runtime State Inventory

This is a code/schema-addition phase (new tables, new classes, deleting an unused stub) — not a
rename/migration of existing live data. The five categories:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | **None** — no existing operational rows exist (the Postgres operational store has never been written to; the `'live'` arms are stubs/`NotImplementedError`). The new tables are created empty. | None — new schema |
| Live service config | **None** — no deployed Postgres operational instance yet (Phase 4 wires the live path). The DB connection surface is `SqlSettings` (port 5544), already in place. | None for Phase 3 |
| OS-registered state | **None** — no scheduled jobs / daemons reference these tables. | None |
| Secrets/env vars | `ITRADER_DATABASE_*` (host/port/user/name/password) already defined for the Postgres arm (quick-task 260629-l0q). Autogenerate + Postgres round-trip tests consume them / a testcontainers URL. No new secret. | None — reuse existing |
| Build artifacts / installed packages | Deleting `postgresql_storage.py` leaves a stale `.pyc` in `__pycache__` and the mypy override line in `pyproject.toml`. | Remove the `pyproject.toml` override entry for `itrader.order_handler.storage.postgresql_storage`; stale `.pyc` is harmless (regenerated) |

**The canonical question — after every file is updated, what runtime systems still hold old state?**
Nothing: there is no pre-existing operational data, no deployed service, no registered job. This is
additive schema + new code.

## Common Pitfalls

### Pitfall 1: `PortfolioStateStorage` ABC has NO `portfolio_id` parameter — bind it at construction
**What goes wrong:** A naive `SqlPortfolioStateStorage` shared across all portfolios returns every
portfolio's positions from `get_positions()`, corrupting state.
**Why:** Every ABC method (`get_positions()`, `get_transaction_history()`, `get_reserved_cash()`,
`get_snapshots()`, …) takes NO `portfolio_id` — the in-memory backend is **one instance per
`Portfolio`** (`portfolio.py` constructs its own `PortfolioStateStorageFactory.create(...)`). The SQL
backend must replicate that scoping: bind a `portfolio_id` in `__init__` and add
`WHERE portfolio_id = self._portfolio_id` to every query, and inject it into every INSERT (including
`CashOperation` and `PortfolioSnapshot`, which carry NO `portfolio_id` field).
**How to avoid:** `SqlPortfolioStateStorage(backend, portfolio_id)`; the factory `'live'` arm passes
`portfolio_id`. This also answers the discretion item: **no `portfolios` parent table is required**
(an FK-target parent table is optional hygiene, not mandated by the ABC). Flag A4 if the planner
wants a parent table for FK integrity.
**Warning sign:** any SQL method without a `portfolio_id` filter.

### Pitfall 2: Money on SQLite `Numeric` decays to float — run money round-trips on Postgres only
**What goes wrong:** A round-trip parametrized on `"sqlite"` shows `Decimal("0.1")` reading back as
`Decimal('0.1000000000000000055...')` (float drift), failing exactness.
**Why:** SQLite has no native NUMERIC affinity; SQLAlchemy stores `Numeric` as float there. The whole
point of OPS-04 is that money is **Postgres-native `Numeric`** and never touches SQLite.
**How to avoid:** money-exactness assertions run on the `"postgres"` arm (skips Dockerless, D-11).
UUID/time/enum round-trips may also run on sqlite. Mirror the spine's parametrize-by-dialect but gate
money to Postgres.
**Warning sign:** a `Decimal == Decimal` money assert under the sqlite param.

### Pitfall 3: D-10 `obj2 == obj` is field-wise for dataclass/msgspec but IDENTITY for `Position`
**What goes wrong:** The `Position` round-trip test passes a reconstructed object to `==` and it is
always False; or the `Order` test passes because price matched but silently never checked
`state_changes`.
**Why:** `Order`, `OrderStateChange`, `CashOperation`, `PortfolioSnapshot` are `@dataclass` (field-
wise `__eq__`); `Transaction`, `SignalRecord` are `msgspec.Struct` (field-wise). But `Position`
(`position/position.py`) is a plain `class Position(object)` with **no `__eq__`** → identity. AND the
dataclass `Order.__eq__` includes `state_changes` and `child_order_ids`, so a faithful `obj2 == obj`
forces those to round-trip too (hence the `order_state_changes` child table + child-id query).
**How to avoid:** use the per-object assertion table in §Round-Trip Test Pattern — `==` for the
field-wise objects (persisting EVERY field), a `to_dict()`-plus-extras projection for `Position`.
**Warning sign:** a `Position` round-trip that asserts `==` (will be a false-passing identity check
only if comparing the same object).

### Pitfall 4: ResourceWarning under `filterwarnings=["error"]` from undisposed engines
**What goes wrong:** A test or autogen path that builds a `SqlBackend`/engine and never disposes it
trips a GC-finalized `ResourceWarning`, which `filterwarnings=["error"]` turns into a failure.
**Why:** the Phase-1 env.py comment explicitly avoided building a transient `SqlBackend` for exactly
this reason. SQLite `SingletonThreadPool` and psycopg2 pools warn on GC.
**How to avoid:** always `dispose()` in fixtures (the conftest fixtures already do); have
`Sql<Concern>Storage.dispose()` delegate to `backend.dispose()` (WR-03).
**Warning sign:** an engine created in a test body without a `finally: engine.dispose()`.

### Pitfall 5: Non-deterministic autogenerate without a MetaData naming_convention
**What goes wrong:** Re-running `--autogenerate` (or a drift-guard test) emits spurious
constraint/index renames because SQLAlchemy auto-named them differently.
**Why:** unnamed `Index`/`ForeignKey`/`UniqueConstraint` get provider-default names that aren't
stable across MetaData instances.
**How to avoid:** set a `naming_convention` on the MetaData the operational tables register on. The
SQLAlchemy-standard dict `{"ix": "ix_%(column_0_label)s", "uq": "uq_%(table_name)s_%(column_0_name)s",
"fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s", "pk": "pk_%(table_name)s", ...}`
is the convention. Decide whether to put it on `SqlBackend.metadata` (affects results store's
create_all too — harmless, names just become explicit) or only on the env.py autogen MetaData; for
consistency, prefer `SqlBackend.metadata`. `[ASSUMED]` standard convention is acceptable — A5.
**Warning sign:** a second `--autogenerate` produces a non-empty diff against an unchanged schema.

### Pitfall 6: Self-referential bracket FK insert ordering + child reconstruction
**What goes wrong:** Inserting a child order before its parent violates the `parent_order_id` FK on
Postgres; or `get_order_by_id` returns an `Order` with an empty `child_order_ids`, failing the
`Order.__eq__` round-trip.
**Why:** children point at the parent (D-02); the parent row must exist first. And `child_order_ids`
is derived, not stored.
**How to avoid:** the order handler already creates the parent before children (bracket declaration).
On `add_order`, insert in dependency order. On read, populate `child_order_ids` via
`SELECT id FROM orders WHERE parent_order_id = :id` (the `parent_order_id` index makes this O(log n)).
The one-query bracket fetch is `WHERE id = :id OR parent_order_id = :id`.
**Warning sign:** an FK violation on a child insert, or a round-trip `Order` with `child_order_ids ==
[]` when children exist.

### Pitfall 7: `equity_snapshots` / append-only history needs a stable, non-autoincrement ordering key
**What goes wrong:** `get_snapshots()` / `get_transaction_history()` return rows in a non-
deterministic order (Postgres has no implicit insertion order), breaking the in-memory-equivalent
"insertion order" contract; or a developer reaches for an Integer autoincrement PK (forbidden).
**Why:** `PortfolioSnapshot` has no id and timestamps can tie; the single-UUID rule forbids
autoincrement.
**How to avoid:** add an explicit per-portfolio monotonic `seq` column written by the backend (or use
`(portfolio_id, timestamp)` composite + a deterministic tiebreak), and always `ORDER BY` it. Same
discipline for any append-only read that must preserve order. A3.
**Warning sign:** a `select(...)` over a history table with no `order_by`.

### Pitfall 8: JSON `config` byte-determinism needs sorted keys
**What goes wrong:** the D-10 determinism check ("two runs encode identical bytes") fails for
`signals.config` because Python dict iteration order (preserved by `json.dumps`) differed between the
two construction paths.
**Why:** `json_variant()` serializes via the dialect's JSON serializer; without `sort_keys`, byte
output depends on insertion order.
**How to avoid:** for the determinism assertion, compare the **decoded value** (dict `==`, order-
independent — sufficient for `SignalRecord.__eq__`), OR configure a `sort_keys` JSON serializer on
the engine if byte-identity of the stored JSON is required. The results store did NOT need sort_keys
because its determinism contract was the gzip blob, not the JSON column. Recommend asserting value-
equality for round-trip and noting JSON byte-identity is not part of `SignalRecord` equality. A6.
**Warning sign:** a determinism test that compares raw stored JSON text rather than the decoded dict.

## Code Examples

### Self-referential bracket FK + D-08 indexes (orders table)
```python
# Source: synthesized from itrader/results/models.py pattern + D-02/D-08
from sqlalchemy import Boolean, Column, ForeignKey, Index, Integer, Numeric, String, Table
from itrader.storage import Uuid, UtcIsoText

tables["orders"] = Table(
    "orders", metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("time", UtcIsoText),
    Column("type", String), Column("status", String),
    Column("ticker", String), Column("action", String),
    Column("price", Numeric), Column("quantity", Numeric),
    Column("exchange", String),
    Column("strategy_id", Uuid(as_uuid=True)),
    Column("portfolio_id", Uuid(as_uuid=True)),
    Column("filled_quantity", Numeric),
    Column("created_at", UtcIsoText), Column("updated_at", UtcIsoText),
    Column("filled_at", UtcIsoText, nullable=True),
    Column("cancelled_at", UtcIsoText, nullable=True),
    Column("expired_at", UtcIsoText, nullable=True),
    Column("expiry_time", UtcIsoText, nullable=True),
    Column("parent_order_id", Uuid(as_uuid=True),
           ForeignKey("orders.id"), nullable=True, index=True),   # D-02 self-ref
    Column("rejection_reason", String, nullable=True),
    Column("modification_count", Integer),
    Column("last_modification_time", UtcIsoText, nullable=True),
    Column("leverage", Numeric),
    Column("trail_type", String, nullable=True),
    Column("trail_value", Numeric, nullable=True),
    Index("ix_orders_portfolio_status", "portfolio_id", "status"),  # D-08
)
```

### Enum text round-trip (D-07)
```python
# write:  store the .value
row["status"] = order.status.value          # "PENDING"
# read:   validate back via the enum (case-insensitive _missing_) or the map
from itrader.core.enums import OrderStatus, order_status_map
status = OrderStatus(row["status"])         # or order_status_map[row["status"]]
```

### Money exact round-trip assertion (OPS-04)
```python
got = conn.execute(select(orders.c.price).where(orders.c.id == oid)).scalar_one()
assert got == order.price and isinstance(got, Decimal)   # Numeric → exact Decimal on Postgres
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `PostgreSQLOrderStorage` stub raising `NotImplementedError` | `SqlOrderStorage` on the shared spine | Phase 3 (this) | Fills OPS-01; stub deleted (D-05) |
| Per-concern bespoke SQL | Compose one `SqlBackend`, Core `Table` on shared `MetaData` | Phase 1–2 | Single SQL stack; results store proved it |
| New `sql_storage.py` deferred from `mypy --strict` (old D-sql override) | Strict from day one | Phase 1 (`sql_store.py` lifted, 01-05) + Phase 2 (results sql_storage is strict) | The new modules enter strict scope NOW; only `postgresql_storage` override remains (and is being deleted) |
| `Settings.database_url: SecretStr` (Phase-1 D-02/D-08) | unified `SqlSettings(BaseSettings)` (`env_prefix=ITRADER_DATABASE_`, port 5544) | quick-tasks 260629-jh2 / l0q | Backends source the engine from `SqlSettings`, NOT `Settings`; no `database_url` field exists anymore |

**Deprecated/outdated:**
- `postgresql_storage.py` / `PostgreSQLOrderStorage`: delete (no symbol importer). Remove its
  `pyproject.toml` mypy override.
- The `db_url: Optional[str]` factory parameter: superseded by `SqlSettings`/`SqlBackend` injection.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Unbounded `Numeric` (no precision/scale) is preferred over a fixed `Numeric(p, s)` for money | Standard Stack | Low — both exact on Postgres; a pinned precision could clip a 28-digit Decimal if too small. Planner may pin a generous precision. |
| A2 | `locked_margin.position_id` stored as `String` (ABC types it `str`) not `Uuid` | Table Maps | Low — match the ABC's exact key type; if callers always pass `str(uuid)`, String preserves it; a Uuid column would coerce |
| A3 | `equity_snapshots` needs an explicit per-portfolio `seq` (no autoincrement) for stable ordering | Table Maps / Pitfall 7 | Medium — if timestamps are guaranteed unique per portfolio, `(portfolio_id, timestamp)` PK suffices and `seq` is unneeded |
| A4 | No `portfolios` parent table is required (bind `portfolio_id`, no FK target) | Pitfall 1 | Low — a parent table adds FK integrity but isn't mandated; planner may add one |
| A5 | The SQLAlchemy-standard `naming_convention` dict is acceptable for deterministic autogenerate | Pitfall 5 | Low — convention choice is cosmetic but must be fixed once; changing it later rewrites constraint names |
| A6 | `signals.config` round-trip asserts decoded-dict equality (not stored-JSON byte identity) | Pitfall 8 | Low — `SignalRecord.__eq__` is dict-value-equal; byte identity of JSON is not part of the equality contract |
| A7 | A single shared `SqlBackend` injected into all three factory `'live'` arms is the intended wiring | Factory wiring | Medium — Phase 4 owns the live composition root; if Phase 4 wants per-concern engines this changes. Phase 3 only needs the classes to accept a `SqlBackend`. |

## Open Questions

1. **State-change persistence shape for `Order`.**
   - What we know: `Order.__eq__` (dataclass) includes `state_changes`; the ABC's `get_order_history`
     implies a child table; D-01 says fully-typed (no blob).
   - What's unclear: child table (`order_state_changes`) vs a `json_variant()` column. Recommend the
     child table (D-01-consistent, queryable, matches the in-memory seam-audit note).
   - Recommendation: child table; if the planner judges state-change history out-of-scope for the
     store layer, narrow the D-10 `Order` equality assertion to the persisted fields and document it.

2. **Round-trip `SqlBackend` over the testcontainers engine.**
   - What we know: `SqlBackend` builds its own engine from `SqlSettings`; the conftest yields an
     `Engine`.
   - What's unclear: add a `pg_backend` fixture (settings carry the container URL via the verbatim
     escape hatch) vs. construct `SqlBackend` and set `.engine = pg_engine`.
   - Recommendation: `pg_backend` fixture using `SqlSettings(driver=POSTGRESQL_PSYCOPG2, url=...)`.

3. **Whether to add a drift-guard test** (autogenerate yields empty diff vs the migration).
   - Recommendation: nice-to-have, extend `test_migrations.py`; not required by D-09.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| SQLAlchemy | all backends + tables | ✓ | 2.0.50 | — |
| Alembic | autogenerate the baseline migration | ✓ | 1.18.5 | — |
| testcontainers[postgresql] | gate-(b) Postgres round-trip | ✓ | 4.14.2 | conftest skips PG arm if Dockerless (D-11) |
| psycopg2-binary | Postgres driver | ✓ | ^2.9.12 | — |
| Docker daemon | run the Postgres container for money/round-trip tests + autogenerate-against-Postgres | ✗ (must be running locally) | — | round-trip PG arm `pytest.skip`s (D-11); UUID/time/enum still run on sqlite. **Autogenerate needs a real Postgres** (local on 5544 or a container) — no fallback for generating the migration |

**Missing dependencies with no fallback:** Generating the baseline migration requires a reachable
Postgres (the autogenerate reflection step). Running money round-trip tests requires Docker. Both are
the documented gate-(b) substrate; CI/dev without Docker skips the PG tests but **cannot author the
migration** — the planner should ensure a Postgres is available for the migration task (testcontainers
or local 5544).

## Validation Architecture

`workflow.nyquist_validation` is `true` (config.json) — section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 (+ pytest-cov 7.1.0) |
| Config file | `pyproject.toml [tool.pytest.ini_options]` (`testpaths=["tests"]`, `filterwarnings=["error",...]`, `--strict-markers`, `--strict-config`) |
| Quick run command | `poetry run pytest tests/unit/<domain>/test_sql_<concern>_storage.py -x` |
| Full suite command | `make test` (or `poetry run pytest tests` in a worktree — see MEMORY: make-test `.env` aborts) |
| Markers | only `unit`, `integration`, `slow`, `e2e` declared; folder-derived via `tests/conftest.py` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| OPS-01 | `SqlOrderStorage` add/get/update/status/active/bracket round-trip on Postgres; `obj2 == order` incl. state_changes + child_order_ids | integration | `poetry run pytest tests/integration/storage/test_sql_order_storage.py -x` | ❌ Wave 0 |
| OPS-02 | Six portfolio tables round-trip; bound `portfolio_id` isolation; `Position` projection-equality; reservations/locked-margin full precision | integration | `poetry run pytest tests/integration/storage/test_sql_portfolio_storage.py -x` | ❌ Wave 0 |
| OPS-03 | `SqlSignalStorage` add/get_all/by_strategy/by_ticker; `SignalRecord == ` incl. config dict | integration | `poetry run pytest tests/integration/storage/test_sql_signal_storage.py -x` | ❌ Wave 0 |
| OPS-04 | Money columns persist as `Numeric`, read back exact `Decimal` (Postgres arm only) | integration | same files, Postgres-parametrized cases | ❌ Wave 0 |
| OPS-01/02/03 | Determinism: two writes encode identical bytes (UtcIsoText) / equal Decimal / value-equal UUIDs | integration | included in each file | ❌ Wave 0 |
| MIG-01 cont. | Autogenerated baseline migration applies on Postgres; (optional) empty-diff drift guard | integration | extend `tests/integration/storage/test_migrations.py` | ⚠️ exists (extend) |
| GATE-01 | Oracle byte-exact 134 / 46189.87730727451; backtest imports no SQL symbol | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ exists |
| GATE-02 | `mypy --strict` clean; suite green under `filterwarnings=["error"]` | static + suite | `poetry run mypy itrader` + `make test` | ✅ infra exists |

### Sampling Rate
- **Per task commit:** the concern's quick `pytest ... -x` + `poetry run mypy itrader`.
- **Per wave merge:** `poetry run pytest tests/integration/storage -x` + oracle test.
- **Phase gate:** full suite green + `mypy --strict` clean + oracle byte-exact + W1/W2 no-regression
  before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `tests/integration/storage/test_sql_order_storage.py` — covers OPS-01/04
- [ ] `tests/integration/storage/test_sql_portfolio_storage.py` — covers OPS-02/04
- [ ] `tests/integration/storage/test_sql_signal_storage.py` — covers OPS-03/04
- [ ] `pg_backend` fixture (or reuse/extend the `engine`/`pg_engine` fixtures) in
      `tests/integration/storage/conftest.py` — wraps the container into a `SqlBackend`
- [ ] (optional) extend `test_migrations.py` with the operational-baseline apply + drift guard
- [ ] NO new test framework install — pytest + testcontainers already present
- Tests live under `tests/integration/storage/` (package-less dir — do NOT add `__init__.py`, per
  MEMORY test-dir collision note).

## Security Domain

`security_enforcement` is not set to `false` — section included (the relevant control is SEC-01's
continuation).

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V5 Input Validation | yes | Enum values validated on read via `OrderStatus(...)`/`order_*_map` (D-07); ids are `Uuid` typed |
| V5.3 Injection | yes | Parameterized Core (`bindparam`, constant `Table` objects) — NEVER f-string SQL (SEC-01 precedent in `sql_store.py`) |
| V6 Cryptography | no | No crypto in scope |
| V2/V3/V4 Auth/Session/Access | no | No auth surface in the store layer |
| V7 Secrets | yes | DB credentials sourced from `SqlSettings` (`ITRADER_DATABASE_*` / verbatim URL), never hardcoded; no credential written into `alembic.ini` (SEC-01); never log the resolved secret URL |

### Known Threat Patterns for SQLAlchemy-Core + Postgres
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via dynamic column/table names | Tampering | Constant `Table`/`Column` objects + `bindparam`; no string interpolation (the SEC-01 fix removed exactly this) |
| Credential leak in migration config / logs | Info Disclosure | Lazy URL resolution in env.py (already), blank `sqlalchemy.url` in `alembic.ini`, `SecretStr` creds |
| FK orphan / bracket drift | Tampering | `parent_order_id` FK integrity (D-02) prevents orphaned children |
| Cross-portfolio data bleed | Information Disclosure / Tampering | bound `portfolio_id` filter on every portfolio-state query (Pitfall 1) |

## Sources

### Primary (HIGH confidence — direct codebase read this session)
- `itrader/results/{models,sql_storage}.py` + `tests/unit/results/test_sql_results_store.py` — the
  reference implementation pattern (table builder, composition, create_all, round-trip)
- `itrader/order_handler/{order.py, base.py, storage/{in_memory_storage,storage_factory,postgresql_storage}.py}`
- `itrader/portfolio_handler/{base.py, position/position.py, transaction/transaction.py,
  cash/cash_manager.py, metrics/metrics_manager.py, storage/{in_memory_storage,storage_factory}.py}`
- `itrader/strategy_handler/{signal_record.py, storage/{base,storage_factory,in_memory_storage}.py}`
- `itrader/storage/{backend.py, types.py, migrations/env.py}`, `itrader/config/sql.py`
- `itrader/core/{ids.py, enums/{order,event,portfolio}.py}`
- `tests/integration/storage/{conftest.py, test_spine_roundtrip.py}`
- `pyproject.toml` (mypy overrides, pytest config) — versions via `poetry run python -c import`
  (SQLAlchemy 2.0.50, Alembic 1.18.5)
- `.planning/phases/03-.../03-CONTEXT.md`, `.planning/REQUIREMENTS.md`, `.planning/STATE.md`

### Secondary (MEDIUM)
- SQLAlchemy 2.0 `Numeric.asdecimal` default-True behavior `[CITED: docs.sqlalchemy.org]` — exact
  Decimal on Postgres NUMERIC (consistent with the in-repo money policy and OPS-04 intent)

### Tertiary (LOW)
- Standard `naming_convention` dict for deterministic Alembic autogenerate `[ASSUMED]` — common
  SQLAlchemy/Alembic practice; pin once (A5)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries present and version-verified; results store is a working
  in-repo precedent for every construct
- Architecture / Table maps: HIGH for column lists (read every domain object); MEDIUM on three
  discretion edges flagged in §Assumptions Log (Numeric precision, snapshot `seq`, naming convention)
- Pitfalls: HIGH — each derived from a concrete code fact (ABC signatures, `__eq__` semantics, SQLite
  Numeric, `filterwarnings=["error"]`, self-ref FK)

**Research date:** 2026-06-29
**Valid until:** 2026-07-29 (stable internal stack; re-verify only if SQLAlchemy/Alembic majors bump
or the spine `MetaData`/`SqlSettings` surface changes)
