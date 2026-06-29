# Phase 3: Operational SQL Backends (#2 — store layer) - Context

**Gathered:** 2026-06-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Give each of the three existing **operational seams** one concrete SQL backend on the Phase-1
`SqlBackend` spine, validated by DB round-trip tests on **testcontainers Postgres**:

- **Order mirror** — `SqlOrderStorage` implements the `OrderStorage` ABC (fills the
  `PostgreSQLOrderStorage` `NotImplementedError` stub).
- **Portfolio state** — `SqlPortfolioStateStorage` implements `PortfolioStateStorage`
  (cash / position / transaction / metrics / reservations / margin / snapshots).
- **Signal store** — `SqlSignalStorage` implements the `SignalStore` ABC (signal records + config).

Operational money persists as Postgres-native `Numeric` (exact `Decimal` round-trip — OPS-04). This
is the **store layer only**: wiring these backends into the live write-through / retention / cache /
rehydration path is **Phase 4**. The backtest in-memory backends are **UNCHANGED** and import no
SQLAlchemy/serialization symbol.

**Requirements (from REQUIREMENTS.md):** OPS-01, OPS-02, OPS-03, OPS-04 (+ recurring GATE-01/GATE-02).

**In scope:** the three `Sql<Concern>Storage` classes (one `sql_storage.py` per domain's `storage/`);
the Core `Table` definitions + `to_row`/`from_row` converters; the first operational Alembic baseline
migration in the framework chain; testcontainers Postgres round-trip tests per concern.

**Out of scope (other phases / locked):** live write-through, working-set cache, purge-on-terminalize,
read-through, restart rehydration (Phase 4); cache classification (Phase 5); the results store (Phase
2); any change to the backtest in-memory backends or the hot path; `DecimalAsText` (locked OUT — money
is native `Numeric`); the `postgresql` factory arm (owner chose `live`-only — see D-04).

**⚠ Build-order note:** STATE has Phase 2 (Results Store) as *not yet started*, and Phase 3 depends on
Phase 2 in the roadmap. These decisions are captured ahead of build; the Phase 3 *implementation*
should not land before Phase 2 validates the spine oracle-dark.

</domain>

<decisions>
## Implementation Decisions

### Record schema shape (OPS-01/03)
- **D-01:** **Fully typed relational columns** per domain object — every field of `Order` /
  `SignalRecord` (and the portfolio sub-objects) becomes a typed column (money → `Numeric`, ids →
  `sqlalchemy.Uuid`, business-time → uniform ISO/text per Phase-1 D-04, enums → text per D-07). NO
  JSON-document or blob-per-record rows. Rationale: maximal queryability for the planned FastAPI app,
  real indexes/constraints, no opaque payloads to deserialize for relationship navigation.
- **D-02:** Order **brackets** are modeled with a **self-referential, nullable, indexed
  `parent_order_id` FK** on child rows (children point at the parent). The whole bracket is fetched in
  one indexed query (`WHERE order_id = :id OR parent_order_id = :id`); adding a child is a single
  `INSERT`; FK integrity prevents orphans/drift. NOT a `child_ids` array column (would need
  read-modify-write to add a child — race-prone on the live path — and array-containment queries).
  This shape also serves the Phase-4 "bracket parent stays resident until children terminalize"
  invariant as a clean status query.

### Portfolio-state layout (OPS-02)
- **D-03:** **Normalized table-per-collection**, all keyed by `portfolio_id`:
  `positions` (with an `is_open` flag covering open + closed), `transactions`, `cash_reservations`
  (`reference_id → amount`), `locked_margin` (`position_id → amount`), `cash_operations`,
  `equity_snapshots`. NOT a consolidated per-portfolio snapshot blob and NOT a JSON ledger for the
  bookkeeping maps — every sub-collection stays a direct, queryable SELECT (web-app drill-down +
  Phase-4 "load open positions" rehydration are plain `WHERE` queries). Money is `Numeric` throughout.

### Object ↔ row mapping (pattern for all three backends)
- **D-04 (mapping):** **SQLAlchemy Core** `Table` definitions on the shared `MetaData` + **explicit
  hand-written `to_row` / `from_row` converters** per concern. NOT the ORM declarative/`Session` layer.
  Rationale: one SQL stack across the whole spine (Phase 1 built `SqlBackend` as Core, no Session); the
  domain objects are **frozen dataclasses that stay persistence-ignorant** (no `Mapped[...]`
  annotations leaking SQLAlchemy into `core`); no identity-map/lazy-load semantics. (An ORM path would
  need a separate `*Row` mapped class + converter anyway, since the real domain objects can't carry ORM
  mappings — so it adds a second paradigm without removing the converter.)

### Factory + file wiring (OPS-01/02/03)
- **D-05:** New `sql_storage.py` per domain `storage/` package, one class each:
  `SqlOrderStorage` (`order_handler/storage/sql_storage.py`),
  `SqlPortfolioStateStorage` (`portfolio_handler/storage/sql_storage.py`),
  `SqlSignalStorage` (`strategy_handler/storage/sql_storage.py`). Name matches the roadmap (OPS-01) and
  the spine's dialect-agnostic reality. **Retire** the `PostgreSQLOrderStorage` /
  `postgresql_storage.py` stub (the in-place fill option was rejected — name pinned to Postgres,
  diverged from `Sql*`).
- **D-06 (factory arm — owner override):** Each factory routes its existing **`'live'`** arm to the new
  SQL backend; `'backtest'`/`'test'` stay on the in-memory backend, untouched. The owner chose
  **`'live'`-only** — **do NOT add a `'postgresql'` arm**. ⚠️ This **diverges from the ROADMAP Phase 3
  SC1 wording** ("selectable via its factory's `postgresql`/`live` arm"); the divergence is deliberate
  and the planner should not re-introduce `postgresql`.
- **D-07 (enums):** Enum fields (`OrderStatus`, `Side`, `OrderType`, `TimeInForce`, …) stored as
  **plain text (`String`) = the enum's `.value`**, validated on read via the existing `order_*_map`
  string→enum converters. NOT Postgres-native `ENUM` (ALTER-TYPE friction + Postgres-only, diverges
  from the SQLite-capable spine) and NOT a `CHECK` constraint (still needs a migration to extend).
  Adding an enum member is then a zero-schema-change operation.

### Phase-4 forward-coupling (schema readiness, no Phase-4 behavior)
- **D-08:** Phase 3 **bakes in the indexes Phase 4's rehydration/purge will query on** — but builds
  **none** of the write-through/cache/rehydration logic. Concretely: `is_open` (positions) and `status`
  (orders) columns exist (D-01/D-03), plus indexes `(portfolio_id, status)` on orders,
  `(portfolio_id, is_open)` on positions, and the `parent_order_id` index (D-02). Goal: "load open
  positions + working orders + brackets" is a clean indexed query in Phase 4 with no day-one migration.

### Schema authority / migrations (MIG-01 continuation)
- **D-09:** The SQLAlchemy **`MetaData` is the single source of truth.** Both application paths derive
  from it:
  - **Tests / dev (testcontainers + SQLite):** `backend.metadata.create_all(engine)` — fast,
    deterministic, no migration overhead in the suite.
  - **Deploy / live Postgres:** Alembic. Phase 3 **autogenerates the first operational baseline
    migration** from the MetaData into the **framework's** Phase-1 Alembic skeleton
    (`itrader/storage/migrations/`, `render_as_batch=True`). The framework **owns the operational-table
    migration chain** (it defines those tables); the planned FastAPI app runs `alembic upgrade head` on
    itrader's chain at deploy and keeps any app-specific tables in its **own separate** chain — one
    chain per concern, never two chains over the same tables.
  - Do NOT run migrations inside tests; do NOT author a second Alembic chain for these tables.

### Round-trip / parity tests (GATE-02, gate (b))
- **D-10:** Per concern, on testcontainers Postgres: write the domain object → read it back → assert
  **reconstructed object equality** (`obj2 == obj`), with money asserted as **exact `Decimal`**
  (`obj2.price == obj.price` and `isinstance(..., Decimal)` — `Numeric` round-trips without float drift,
  OPS-04) and **UUIDv7 ids value-equal** (`obj2.id == obj.id`, SPINE-03). Plus a **determinism** check
  (two runs encode identical bytes — business `time` not wall-clock, stable `ORDER BY`). Proves the full
  `to_row`/`from_row` contract end-to-end, not just per-column storage.

### Carried forward from Phase 1 (locked — restated)
- Composition not inheritance: each `Sql<Concern>Storage` **composes** the shared `SqlBackend`.
- Ids via `sqlalchemy.Uuid(as_uuid=True)`; business-time via uniform ISO/text (D-04 Phase 1); no
  wall-clock writes; single UUIDv7 scheme; no DB autoincrement / second ID scheme.
- Money on the operational path = Postgres-native `Numeric`, no float-for-money, no `DecimalAsText`.
- Backend selection at **wiring** (factory string-arm), not a hot-path `write_through` flag.
- Recurring gates (D-16 Phase 1): SMA_MACD oracle byte-exact **134 / `46189.87730727451`**, no W1/W2
  regression vs the v1.5 baseline (**15.7 s / 152.8 MB**); `mypy --strict` clean; full suite green under
  `filterwarnings=["error"]` with no new broad ignore.

### Claude's Discretion (planner/researcher to settle)
- Exact column lists/types per `Table` (beyond the money/id/enum/time rules above); precise index names.
- Whether `SqlPortfolioStateStorage` needs a `portfolios` parent table or keys directly off
  `portfolio_id` (D-03 keying is fixed; the parent-row question is open).
- Alembic `env.py` autogenerate wiring details; the exact migration file content (autogen from MetaData).
- Whether the reworked SQL storage modules enter `mypy --strict` scope now or stay deferred (cf.
  Phase 1 D-09 for `sql_store.py`) — planner's call under GATE-02.
- The one-time handling of the retired `postgresql_storage.py` stub (delete vs deprecate-and-re-export).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### ⚠️ Precedence (read FIRST)
- `.planning/PROJECT.md` → "Owner Decisions" + "Current Milestone" — authoritative locked scope. Owner
  Decisions supersede the research where they differ (no `DecimalAsText`; money native `Numeric`).
- This CONTEXT's **D-06** (factory `'live'`-only) deliberately **overrides** ROADMAP Phase 3 SC1's
  `postgresql`/`live` wording — do not re-add `postgresql`.

### Requirements & scope
- `.planning/REQUIREMENTS.md` — OPS-01/02/03/04 (full text + Out-of-Scope table); GATE-01/GATE-02.
- `.planning/ROADMAP.md` → "Phase 3: Operational SQL Backends (#2 — store layer)" — the four Success
  Criteria (apply with the D-06 divergence note).
- `.planning/STATE.md` → "Milestone Gate (v1.6 — DB-gated)" — the two-part gate restated.

### Phase 1 spine (the foundation Phase 3 composes — read before designing tables)
- `.planning/phases/01-sql-spine-security-hardening/01-CONTEXT.md` — D-01..D-16: the
  `itrader/storage/` package, `SqlBackend` (Core/MetaData), `types.py` (`Uuid`, `JSON.with_variant`,
  NO money TypeDecorator), `config/sql.py` `SqlSettings`, Alembic skeleton (`render_as_batch=True`,
  empty `versions/`), testcontainers harness (D-10/D-11), composition-not-inheritance.

### Research (HIGH-confidence; PREDATES Owner Decisions — apply with the precedence note)
- `.planning/research/SUMMARY.md` §"Phase 3" + §Research Flags — operational backend deliverables.
- `.planning/research/ARCHITECTURE.md` — the three existing ABCs + composition spine design.
- `.planning/research/PITFALLS.md` — Pitfall 4 (cross-backend divergence — Core + portable types),
  10/11 (UUIDv7/JSON determinism), 13 (FL-06 injection/creds, context).
- `.planning/research/STACK.md` — SQLAlchemy 2.0 Core as unifier; Postgres `Numeric` for money.

### Code to read (the ABCs + factories + objects Phase 3 implements/maps)
- `itrader/order_handler/base.py` — `OrderStorage` ABC (~15 methods, bracket parent/child surface).
  `itrader/order_handler/storage/storage_factory.py` — `'backtest'/'test'` vs `'live'` arms (today
  `'live'` → `PostgreSQLOrderStorage` stub).
  `itrader/order_handler/storage/postgresql_storage.py:14` — the `NotImplementedError` stub to retire.
  `itrader/order_handler/storage/in_memory_storage.py` — flat dict + v1.5 secondary indexes (the
  indexes that become SQL `WHERE` + indexes). `itrader/order_handler/order.py` — the `Order` object.
- `itrader/portfolio_handler/base.py` — `PortfolioStateStorage` ABC (~21 methods: positions/closed/
  transactions/reservations/locked-margin/cash-ops/snapshots). `…/storage/storage_factory.py:61` —
  factory `NotImplementedError` ("deferred to D-sql"). `…/storage/in_memory_storage.py`.
- `itrader/strategy_handler/storage/base.py` — `SignalStore` ABC (4 methods). `…/storage_factory.py:59`
  — factory `NotImplementedError`. `itrader/strategy_handler/signal_record.py` — `SignalRecord`.
- `itrader/core/enums/` — `order_status_map`, `order_type_map`, `Side`, etc. (the string↔enum maps for
  D-07 text encoding). `itrader/core/money.py` — `Decimal` / `quantize` contract.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **Phase-1 `SqlBackend` spine** (`itrader/storage/`): Engine + shared `MetaData` + Core constructs +
  `types.py` (`Uuid`, `JSON.with_variant(JSONB, "postgresql")`). Each new `Sql<Concern>Storage`
  composes it — define `Table`s on its `MetaData`.
- **Phase-1 Alembic skeleton** (`itrader/storage/migrations/`, `render_as_batch=True`, empty
  `versions/`): Phase 3 writes the first real operational migration into it (D-09).
- **Testcontainers Postgres fixture** (Phase 1 D-10, session-scoped; skips gracefully without Docker,
  D-11): the gate-(b) substrate for the D-10 round-trip tests.
- **Factory string-arm idiom** (every domain `storage_factory.py`): the established backend-selection
  seam — Phase 3 fills the `'live'` arm (D-06).
- **`order_*_map` string↔enum converters** (`core/enums/`): the read-side validators for D-07.

### Established Patterns
- **Composition not inheritance** (Phase 1 D-01): no cross-concern god base; one `Sql<Concern>Storage`
  per ABC, each composing the shared spine.
- **Core + explicit converters** (D-04): no ORM/Session; domain frozen-dataclasses stay
  persistence-ignorant.
- **Backend selection at wiring** (not a hot-path flag): the backtest backend imports no SQLAlchemy
  symbol; the no-serialization-in-backtest rule holds structurally.

### Integration Points
- New files: `order_handler/storage/sql_storage.py`, `portfolio_handler/storage/sql_storage.py`,
  `strategy_handler/storage/sql_storage.py`; the first migration under `itrader/storage/migrations/`.
- Edited: the three `storage_factory.py` files (`'live'` arm → new `Sql*Storage`); retire
  `order_handler/storage/postgresql_storage.py`.
- Tests: new per-concern round-trip tests on the testcontainers Postgres fixture.

### Indentation map (DO NOT normalize — match the file)
- `order_handler/storage/`, `portfolio_handler/storage/`, `strategy_handler/storage/`, `config/`,
  `itrader/storage/` → **4 spaces** (per Phase-1 indentation map). `portfolio_handler/base.py` has a
  TAB-import / 4-space-class mix — match the surrounding lines exactly.

</code_context>

<specifics>
## Specific Ideas

- **The framework will be wrapped in a FastAPI app at the application layer** (owner, this session).
  This is the lens behind several decisions: fully-typed queryable columns (D-01), self-referential
  bracket FK for clean parent+children fetch (D-02), normalized portfolio tables (D-03), and the
  Alembic ownership split (D-09 — the app uses Alembic at the application level; itrader owns its own
  operational-table chain and the app consumes it).
- Owner explicitly values **web-app read ergonomics** over object-shape fidelity in the store
  (rejected JSON-blob and `child_ids`-array options because they hurt querying / require
  read-modify-write).

</specifics>

<deferred>
## Deferred Ideas

- **Live write-through / working-set cache / purge-on-terminalize / read-through / restart
  rehydration** — Phase 4 (RETAIN-01/02/03, GATE-01). Phase 3 only shapes the schema/indexes for it
  (D-08), builds none of the behavior.
- **`postgresql` factory arm** — explicitly NOT added (D-06, owner override); revisit only if a future
  need to distinguish `live` from `postgresql` arises.
- **FastAPI application layer + app-specific Alembic chain** — a downstream application concern (N+4 /
  separate app repo), not this milestone. Captured so the framework's migration-ownership split (D-09)
  is intentional.

None — discussion stayed within phase scope (the FastAPI app is captured as forward context, not added
as Phase 3 work).

</deferred>

---

*Phase: 3-Operational SQL Backends (#2 — store layer)*
*Context gathered: 2026-06-29*
