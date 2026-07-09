# Phase 4: Storage Schema: Migrations Relocation + New Durable Stores - Context

**Gathered:** 2026-07-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Land the full live-storage schema as one cohesive unit, in two ordered movements:

**(A) Relocate the Alembic `migrations/` tree FIRST** — move `itrader/storage/migrations/` to
project-root `migrations/` (out of the shipped wheel), update `alembic.ini` `script_location`, and keep
`env.py` importing the `build_*_table` registrars + `NAMING_CONVENTION` from `itrader.storage`. Mechanical
move; revision IDs preserved (SQL-01).

**(B) Add three durable SQL stores** on the `HaltRecordStore` template — `SystemStore` (cardinality-1
key/value), `VenueStore` (cardinality-N per-venue config + enabled), `StrategyRegistryStore` (cardinality-N
which strategies trade + config + subscriptions) — each composing `sql_engine` with its own `build_*_table`
registrar, extending the chained migration `d10_halt_records → system_store → venue_config →
strategy_registry`, and rehydrating on restart (STORE-01..05, SQL-02).

**Locked by ROADMAP success criteria + REQUIREMENTS — NOT up for discussion:**
- Relocate-FIRST ordering; `alembic.ini` `script_location` + `env.py` registrar imports from `itrader.storage`.
- Migrations stay out of the shipped wheel (`packages = [{include = "itrader"}]` in `pyproject.toml`).
- The three stores' cardinalities and `SystemStore`'s `(key, value_json, updated_at)` namespaced-upsert shape.
- The exact migration chain names `d10_halt_records → system_store → venue_config → strategy_registry`.
- SQL-02 gate: `alembic upgrade head` on a clean DB, `alembic heads == 1`, and a `create_all`/migration parity test.
- Backtest oracle stays byte-exact (`46189.87730727451`); `tests/integration/test_okx_inertness.py` stays green.

**Explicitly NOT in this phase (deferred to consumers — downstream must NOT pull forward):**
- Constructing/wiring the stores into `live_trading_system` — see D-02.
- Applying rehydrated state to a live handler (config overlay, roster re-registration, venue enablement) — P6/P9/P10.
- Any full "migration baseline reset / squash" — see D-10 / Deferred Ideas.

</domain>

<decisions>
## Implementation Decisions

### In-memory fallback shape
- **D-01 (No in-memory store classes — `HaltRecordStore` `None`-degrade template):** STORE-05's "in-memory
  fallback" is satisfied structurally, NOT by a real in-memory implementation. Do **not** build a
  `Protocol` + `InMemory*Store` + `*StorageFactory` scaffold (the order/portfolio-storage pattern).
  - Rationale: these three stores have **zero backtest consumers** — backtest composition never constructs
    or reads them, so there is nothing on the backtest path for an in-memory twin to serve. Backtest-untouched
    comes from live-only construction + lazy SQL import, not from an in-memory class. The order-storage
    factory earns its Protocol because `InMemoryOrderStorage` runs in *every backtest*; these don't.
  - STORE-04 says "follows the `HaltRecordStore` template" — and that template's fallback IS `None`-degrade
    (constructed only when a SQL spine is present, else `None`, with call-site guards). A twin scaffold would
    *diverge* from the cited template, not follow it. Consumers (P9/P10) add their own null-guards when they wire.
  - **Testing:** exercise the **real** store class over an in-memory **SQLite** `SqlEngine` (`sqlite://`),
    exactly as `HaltRecordStore`'s tests do — this covers the actual SQL path and doubles as SQL-02 parity coverage.

### P4 wiring / rehydrate scope
- **D-02 (Standalone + migration-registered; NOT constructed in `live_trading_system`):** P4 lands the stores
  as tested standalone units. It does **not** construct them in `LiveTradingSystem.__init__`.
  - **In P4:** store classes; `build_*_table` registrars; the 3 chained migrations authored in the relocated
    `migrations/` tree; `env.py` `target_metadata` additions for the new registrars; SQL-02 parity gate; CRUD +
    load/rehydrate read methods; round-trip **restart-survival** unit tests (write → dispose → re-open over the
    same DB → read back).
  - **Deferred to consumers (P6 factory / P9 RuntimeConfig / P10 StrategyRegistry):** constructing the stores in
    the live composition root and applying rehydrated state to live handlers.
  - Rationale: consumers don't exist yet; constructing dead stores nobody reads is speculative wiring. The
    "rehydrate on restart" success criterion is proven honestly at the **store level** via the round-trip test
    (there is no state-holder to rehydrate *into* until the consumer phases). Note: adding the registrars to
    `env.py`/`target_metadata` is **migration-target** wiring (required for the SQL-02 gate), not live-system wiring.

### Schema granularity (VenueStore + StrategyRegistryStore)
- **D-03 (Hybrid — typed identity/flags/timestamp, JSON for heterogeneous config):**
  - `SystemStore`: `(key, value_json, updated_at)` — locked by requirement; value is opaque JSON by design.
  - `VenueStore`: `venue_name` (PK), `enabled` (bool), `config_json`, `updated_at`. Never secrets (see D-05).
  - `StrategyRegistryStore` (registry table): `strategy_name` (PK), `enabled` (bool), `config_json`, `updated_at`.
  - Rationale: type the columns a query filters/sorts on (identity, `enabled`, `updated_at`) so "list enabled
    venues / active strategies" stays queryable (FastAPI-queryability goal — see canonical refs); keep genuinely
    heterogeneous per-venue/per-strategy config as JSON, mirroring `SystemStore`'s locked `value_json` shape.
    Rejected maximal-typing (wide sparse churny schema, speculative columns before FastAPI query patterns are pinned)
    and all-JSON (defeats queryability).
- **D-04 (Normalized `strategy_subscriptions` child table — user override of the YAGNI default):**
  `StrategyRegistryStore` is **two tables**: the registry table (D-03) **plus** a normalized
  `strategy_subscriptions(strategy_name FK, venue, symbol, timeframe)` child table — joinable, indexable,
  directly answers "which strategies subscribe to X." Its registrar builds **both** tables (precedent:
  `build_signal_tables`/`build_order_tables` already return `dict[str, Table]`), its migration creates both,
  and rehydrate **joins** both. Chosen over subscriptions-as-JSON-array despite the consumer not existing yet.

### Migrations relocation + authoring
- **D-05-mig — wait, renumbered below.** (See D-09/D-10.)

### Secret-scrub enforcement (VenueStore)
- **D-05 (Structural + write-time denylist guard — defense-in-depth):** `VenueStore` enforces "never stores
  secrets" two ways: (1) **structural** — venue credentials remain owned solely by the connector /
  `OkxSettings` (`SecretStr`) and are never passed to `VenueStore` (the composition root feeds only non-secret
  operational config); (2) **defensive** — a write-time guard rejects known-secret key names
  (`api_key`/`secret`/`password`/`passphrase`/`token`/…) in `config_json` with a `ValidationError`.
  - Rationale: `config_json` is an open JSON blob, so structural-only can't stop a careless future caller.
    Matches the project's paranoid secret-scrub ethos (V7 / `HaltRecordStore`'s no-payload-column discipline)
    and the accepted defense-in-depth precedent (D-03a dual-layer validator).

### Identity / PK scheme (N-cardinality stores)
- **D-06 (Natural name-based PKs; the ephemeral `strategy_id` UUID is NEVER the durable key):**
  - `SystemStore` PK = `key`; `VenueStore` PK = `venue_name`; `StrategyRegistryStore` PK = `strategy_name`
    (the restart-STABLE identity), with `strategy_subscriptions` FK'd on `strategy_name`.
  - **Correctness-critical:** the runtime `strategy_id` (`strategy_handler/base.py:191-192`) is a UUIDv7 minted
    fresh **per construction** and explicitly **NOT stable across runs** (`base.py:631`); `STRATEGY_COMMAND`
    addresses strategies **by name** (`strategies_handler.py:474`, `by_name.get(event.strategy_name)`). Persisting
    the ephemeral `strategy_id` as the registry key would break rehydrate on restart. The durable identity is the name.
  - Natural keys are *names*, not a second ID scheme — fully compliant with the single-UUIDv7 rule (no surrogate
    UUIDv7 PK, no DB autoincrement). Rejected UUIDv7-surrogate-PK-+-unique-natural-key (extra indirection, no consumer).

### `updated_at` clock source
- **D-07 (Caller-supplied `at: datetime`, `UtcIsoText` column):** Store methods take an `at: datetime` param
  (like `HaltRecordStore.record_halt`), stored via the `UtcIsoText` type. Store stays pure/clock-free; round-trip
  tests pass a fixed timestamp (deterministic); live call sites pass `datetime.now(UTC)`. Rejected store-internal
  `datetime.now(UTC)` (bakes wall-clock + non-determinism into persistence) and DB server-side default (dialect
  timestamp + portable-ALTER concerns, non-determinism).

### JSON column type + method surface
- **D-08 (`json_variant` column type):** `value_json` / `config_json` use the spine's existing `json_variant`
  helper (`itrader/storage/types.py:67` — Postgres JSONB / SQLite JSON), not plain String. Consistent with the
  SQL spine; preserves in-DB JSON typing/queryability.
- **D-09 (Method surface: CRUD + column-justified queries only — finalize in P9/P10):** Each store exposes
  upsert/get/delete/read-all(rehydrate) **plus** the queries the typed columns exist to serve
  (`list_enabled` venues / `list_active` strategies, set-subscriptions). NO consumer-domain methods now (no
  config-overlay assembly, no roster-application helpers — those belong to P9/P10). Enough to unit-test round-trip
  and prove the typed-column queryability.
  - **FORWARD NOTE (user request):** the store method surface is intentionally minimal and is to be **finalized in
    P9 (RuntimeConfig) / P10 (StrategyRegistry)** against the real consumers. Ensure P9/P10 CONTEXT/plans carry this.

### Migrations: existing chain + new-migration authoring
- **D-10 (Preserve all 5 existing migrations via `git mv`):** `git mv` the existing chain
  (`2cbf0bf6b0b6 → 47f2b41f3ffe → p05_venue_order_id → hl5_transaction_venue_trade_id → d10_halt_records`) to
  project-root `migrations/` **unchanged**, preserving revision IDs. Do NOT squash into a fresh baseline.
  - Rationale: SQL-01 is a *mechanical relocation* ("(Mechanical relocation)" per ROADMAP); squashing exceeds
    that scope, rewrites the **order / portfolio / signal** domains' migration lineage (not this storage-spine
    phase's to own), and would force an `alembic stamp`/recreate on any existing dev/sandbox Postgres. STORE-04
    hard-names the chain rooted at `d10_halt_records`, so a full clean-slate is impossible anyway. Baseline-reset,
    if ever wanted, is a dedicated milestone-level decision — see Deferred Ideas.
- **D-11 (Hand-author the 3 new chained revisions):** Write `system_store` / `venue_config` / `strategy_registry`
  as three explicit named revisions in the existing `d10_`/`p05_` slug style, each `op.create_table` derived from
  its `build_*_table` registrar, chained via `down_revision` from `d10_halt_records`. `alembic revision
  --autogenerate` may be used **once, as a DDL drafting aid only** (column types matching `create_all`), then
  split/renamed into the three links. Pure autogenerate emits ONE blob revision, not the required 3-link chain.
  The `create_all`-vs-migration parity gate validates the result either way.

### Claude's Discretion
- Exact plan/commit granularity and step ordering within the relocation (e.g., `alembic.ini` + `env.py` update
  vs. `git mv` ordering), subject to the mechanical-relocation constraint and the byte-exact/inertness gates.
- Precise store method names, column nullability/index choices beyond the typed-column decision, and the exact
  denylisted secret-key-name set (D-05) — planner/researcher's call within the decisions above.
- Whether `env.py` builds `strategy_subscriptions` via the same `dict[str, Table]` registrar or a companion
  registrar — planner's call, as long as autogenerate/`target_metadata` sees both new tables (no spurious drops).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase framing & locked scope
- `.planning/ROADMAP.md` § "Phase 4: Storage Schema: Migrations Relocation + New Durable Stores" — goal, the 4
  success criteria, "(Mechanical relocation)" framing, and the depends-on-P3 note.
- `.planning/REQUIREMENTS.md` §§ "SqlEngine Migrations Relocation (P4)" (SQL-01, SQL-02) and "New Durable Stores
  (P4)" (STORE-01..05) — lines ~99-125. The authoritative store shapes, cardinalities, and gate definitions.
- `.planning/phases/03-enginecontext-storage-in-handler/03-CONTEXT.md` — the `SqlBackend→SqlEngine` rename that
  P4 builds on; the indentation-hazard note; the storage-spine conventions.

### The template + spine this phase extends
- `itrader/storage/halt_record_store.py` — **the template** all three stores follow: composes `SqlEngine`,
  own `build_*_table` registrar (single source of truth), `create_all(checkfirst=True)`, `None`-degrade
  fallback, caller-supplied `at: datetime` + `UtcIsoText`, UUIDv7-from-`idgen` PK, parameterized SQLAlchemy Core.
- `itrader/storage/engine.py` — `SqlEngine` (Engine + MetaData) + `NAMING_CONVENTION` (imported by `env.py`;
  pins constraint/index names so autogenerate is deterministic).
- `itrader/storage/types.py` — `json_variant()` (D-08), `UtcIsoText` (D-07), `Uuid`.
- `itrader/storage/__init__.py` — the spine barrel (`SqlEngine`, `UtcIsoText`, `Uuid`, `json_variant`).

### Migrations (relocation target)
- `itrader/storage/migrations/env.py` — autogenerate `target_metadata` built from `build_order_tables` /
  `build_portfolio_tables` / `build_signal_tables` / `build_halt_records_table` + `NAMING_CONVENTION`; lazy URL
  resolution (import-inert). P4 adds the 3 new registrars here. Move to `migrations/env.py`.
- `alembic.ini` — `script_location = itrader/storage/migrations` → `migrations`; `sqlalchemy.url` stays blank (SEC-01).
- `itrader/storage/migrations/versions/*.py` — the 5 existing revisions (`git mv` preserve, D-10). Current head:
  `d10_halt_records` (chain `2cbf0bf6b0b6 → 47f2b41f3ffe → p05_venue_order_id → hl5_transaction_venue_trade_id → d10_halt_records`).
- `pyproject.toml` `[tool.poetry] packages = [{include = "itrader"}]` — relocation takes `migrations/` out of the wheel.

### Registrar precedent (`dict[str, Table]` multi-table — relevant to D-04)
- `itrader/strategy_handler/storage/models.py:30` `build_signal_tables` → `dict[str, Table]`.
- `itrader/order_handler/storage/models.py:37` `build_order_tables` → `dict[str, Table]`.
- `itrader/portfolio_handler/storage/models.py:54` `build_portfolio_tables` → `dict[str, Table]`.

### Identity correctness (D-06)
- `itrader/strategy_handler/base.py:191-192` (`strategy_id` minted per construction) and `:631` ("NOT stable
  across runs"); `itrader/strategy_handler/strategies_handler.py:474` (`STRATEGY_COMMAND` by name).

### Gate references
- `tests/integration/storage/test_migrations.py` — the create_all-vs-Alembic split (MIG-01/D-14); extend for the SQL-02 full-chain single-head + parity gate.
- `tests/integration/test_okx_inertness.py` — the register-vs-build / backtest-inertness gate; extend the
  register-vs-build assertion for the relocated migrations + new stores (success criterion #4).
- `tests/integration/test_backtest_oracle.py` — byte-exact oracle (`46189.87730727451`); per-PLAN gate.

### Secret-scrub / connector-owned credentials (D-05)
- `itrader/connectors/okx.py` + `OkxSettings` (`SecretStr`) — credentials owned solely by the connector; the
  structural reason `VenueStore` never receives secrets.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `HaltRecordStore` is a near-complete copyable template for all three stores (compose `SqlEngine`, registrar,
  `create_all(checkfirst=True)`, `None`-degrade, `at: datetime`, parameterized Core). Clone its structure.
- `json_variant()` / `UtcIsoText` / `Uuid` from `itrader/storage/types.py` cover every column type the new stores need.
- `env.py` already wires an autogenerate `target_metadata` from `build_*` registrars — adding the 3 new
  registrars is the established extension point (no new machinery).
- `build_*_tables → dict[str, Table]` is the precedent for `StrategyRegistryStore`'s two-table registrar (D-04).

### Established Patterns
- **Registrar = single source of truth:** the same `build_*_table` feeds both the test-path `create_all` and the
  deploy-path Alembic `target_metadata`, so the parity gate is meaningful (T-03-19). New stores must follow this.
- **Import inertness (GATE-01):** registrars construct only `Table` objects on a fresh `MetaData` — no Engine, no
  `Settings()`, no connection. Keep the new registrars import-inert; `migrations/env.py` stays off the hot-loop graph.
- **Indentation:** `itrader/storage/` is **4-space**. New store modules + registrars are 4-space. Match per file;
  never normalize (see 03-CONTEXT indentation-hazard note).
- **Parameterized Core only:** never f-string SQL (SEC-01 / T-05.2-19) — use the constant `Table` object.

### Integration Points
- `alembic.ini` `script_location` + `env.py` import paths are the only two edits the relocation itself requires;
  `env.py` keeps importing `build_*_table` + `NAMING_CONVENTION` from `itrader.storage` (unchanged import paths).
- The 3 new migrations chain off `d10_halt_records` (current head) → head becomes `strategy_registry`; `alembic
  heads == 1` after.
- Stores are **not** wired into `live_trading_system` this phase (D-02); the only "wiring" is into
  `env.py`/`target_metadata` for autogenerate + the parity gate.

</code_context>

<specifics>
## Specific Ideas

- The discussion consistently favored the decisive, non-speculative end-state: follow the `HaltRecordStore`
  template literally, don't scaffold abstractions before their consumers exist, and let the parity + oracle +
  inertness gates be the safety net. Two deliberate user overrides of that YAGNI default: the normalized
  `strategy_subscriptions` child table now (D-04) and hand-authored chained migrations (D-11) — both chosen for
  queryability/control over minimalism.
- FastAPI-queryability is the "north star" behind the hybrid typed-column schema (D-03) — see the FastAPI
  application-layer plan; the schema should trend toward web-app queryability, not opaque JSON.

</specifics>

<deferred>
## Deferred Ideas

- **Migration baseline reset / squash** — collapsing the accreted pre-`d10` migrations into a fresh baseline is a
  reasonable engineering tidy-up (nothing in production), but it exceeds this phase's *relocation* scope, rewrites
  three other domains' migration lineage, and conflicts with STORE-04's hard-named chain. If ever wanted, it
  deserves its own explicit **milestone-level** decision — not smuggled into P4. Noted so it isn't lost.
- **Finalize store method surface in P9/P10** — the P4 method surface is intentionally minimal (D-09). P9
  (RuntimeConfig) and P10 (StrategyRegistry) must finalize it against real consumers (explicit user request).
- **Applying rehydrated state to live handlers** — construction + state-application belongs to consumer phases
  (P6 factory / P9 / P10), per D-02. Not lost; owned downstream.

None else — discussion stayed within phase scope.

</deferred>

---

*Phase: 4-Storage Schema: Migrations Relocation + New Durable Stores*
*Context gathered: 2026-07-09*
