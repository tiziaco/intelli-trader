# Phase 4: Storage Schema: Migrations Relocation + New Durable Stores - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-09
**Phase:** 4-Storage Schema: Migrations Relocation + New Durable Stores
**Areas discussed:** In-memory fallback shape, P4 wiring/rehydrate scope, Schema granularity, Migration authoring method, VenueStore secret-scrub enforcement, Identity/PK scheme, updated_at clock source, JSON column type + method surface

---

## In-memory fallback shape

| Option | Description | Selected |
|--------|-------------|----------|
| Real InMemory*Store + factory | Protocol + InMemory*Store + *StorageFactory keyed on environment (order/portfolio-storage pattern) | |
| None-degrade (HaltRecordStore copy) | Store is `None` when no SQL spine; guard at call sites; real store over in-memory SQLite in tests | ✓ |
| You decide | Defer to research/planning | |

**User's choice:** None-degrade — "Yes, lock it in — no in-memory store classes."
**Notes:** User proactively questioned whether an in-memory store was needed at all. Agreed: these three stores have zero backtest consumers, so backtest-untouched comes from live-only construction + lazy SQL import, not from an in-memory twin. A twin scaffold would diverge from the HaltRecordStore template STORE-04 cites. Tests use the real store over `sqlite://`.

---

## P4 wiring / rehydrate scope

| Option | Description | Selected |
|--------|-------------|----------|
| Standalone + migration-registered | Store classes + registrars + 3 migrations + env.py additions + parity gate + CRUD + rehydrate + round-trip tests; NOT constructed in live_trading_system | ✓ |
| Also construct (dark) in live boot | Above + construct in live __init__ alongside HaltRecordStore, no consumer reads yet | |
| You decide | Defer to planning | |

**User's choice:** Standalone + migration-registered.
**Notes:** Consumers (P6/P9/P10) own construction + applying rehydrated state. Rehydrate-on-restart proven at store level via round-trip test. env.py/target_metadata additions are migration-target wiring (required for SQL-02), not live-system wiring.

---

## Schema granularity

| Option | Description | Selected |
|--------|-------------|----------|
| Hybrid: typed identity+flags, JSON config | Type identity/enabled/updated_at columns; heterogeneous config as JSON | ✓ |
| Maximal typing | Break known config fields into columns | |
| All-JSON per row | One JSON blob per row incl. enabled | |

**User's choice:** Hybrid.
**Notes:** SystemStore locked to (key, value_json, updated_at). VenueStore: venue_name PK, enabled, config_json, updated_at. StrategyRegistryStore registry row: strategy_name PK, enabled, config_json, updated_at. FastAPI-queryability is the north star behind typing the filterable columns.

### Sub-decision: subscriptions

| Option | Description | Selected |
|--------|-------------|----------|
| JSON array on the strategy row | subscriptions as JSON array; additive child table later if needed | |
| Normalized child table now | strategy_subscriptions(strategy_name FK, venue, symbol, timeframe) | ✓ |
| You decide | Defer to planning | |

**User's choice:** Normalized child table now (override of Claude's YAGNI recommendation).
**Notes:** StrategyRegistryStore becomes two tables; registrar builds both (dict[str, Table] precedent); rehydrate joins both.

---

## Migration authoring method

| Option | Description | Selected |
|--------|-------------|----------|
| Hand-author 3 chained revisions | Explicit named revisions in existing slug style; autogenerate as drafting aid only | ✓ |
| Pure autogenerate then hand-split | Autogenerate one blob then split | |
| You decide | Defer to planning | |

**User's choice:** Hand-author 3 chained revisions.
**Notes:** User first raised whether to delete all migrations and start from a fresh baseline (nothing in production). Discussed and rejected for this phase — see the existing-migrations sub-decision below.

### Sub-decision: existing 5 migrations during relocation

| Option | Description | Selected |
|--------|-------------|----------|
| Preserve all 5 via git mv | Move unchanged, revision IDs intact, add 3 new links on top | ✓ |
| Squash pre-d10 into one baseline | Collapse 4 pre-halt migrations into a baseline | |
| Defer baseline-reset decision | Relocate as-is, note squash as a milestone-level decision | |

**User's choice:** Preserve all 5 via git mv.
**Notes:** Squash rejected because SQL-01 is a mechanical relocation, STORE-04 hard-names a chain rooted at d10_halt_records (full clean-slate impossible), it rewrites order/portfolio/signal lineage, and forces re-stamp on dev/sandbox DBs. Baseline reset noted as a deferred, milestone-level decision.

---

## VenueStore secret-scrub enforcement

| Option | Description | Selected |
|--------|-------------|----------|
| Structural + write-time denylist guard | Creds connector-owned (never passed to store) + reject known-secret key names at write | ✓ |
| Structural only | Rely on connector-owned creds + documented keyspace | |
| Typed non-secret config model | Pydantic model with no secret fields | |

**User's choice:** Structural + write-time denylist guard (defense-in-depth).
**Notes:** config_json is open JSON, so structural-only can't stop a careless caller; denylist is the belt-and-suspenders matching the V7 secret-scrub ethos and D-03a defense-in-depth precedent.

---

## Identity / PK scheme

| Option | Description | Selected |
|--------|-------------|----------|
| Natural keys (name-based PKs) | SystemStore key; VenueStore venue_name; StrategyRegistryStore strategy_name | ✓ |
| UUIDv7 surrogate PKs + unique natural key | idgen UUIDv7 surrogate + unique(name) | |
| You decide | Defer, restart-stable identity required | |

**User's choice:** Natural keys (name-based PKs).
**Notes:** Codebase finding drove this: runtime strategy_id is a per-construction UUIDv7 NOT stable across runs (base.py:191/631); STRATEGY_COMMAND addresses by name. Persisting the ephemeral UUID as durable key would break rehydrate. Natural keys (names) are not a second ID scheme.

---

## updated_at clock source

| Option | Description | Selected |
|--------|-------------|----------|
| Caller-supplied at: datetime | at: datetime param, UtcIsoText (HaltRecordStore pattern) | ✓ |
| Store-internal datetime.now(UTC) | Store stamps its own time | |
| DB server-side default/onupdate | In-DB timestamp | |

**User's choice:** Caller-supplied at: datetime.
**Notes:** Keeps store pure/clock-free; deterministic test timestamps; live sites pass datetime.now(UTC).

---

## JSON column type + method surface

| Option | Description | Selected |
|--------|-------------|----------|
| json_variant helper | Postgres JSONB / SQLite JSON via storage/types.py | ✓ |
| Plain String (serialize in app) | TEXT + json.dumps/loads | |
| You decide | Confirm against types.py | |

**User's choice (JSON type):** json_variant helper.

| Option | Description | Selected |
|--------|-------------|----------|
| CRUD + column-justified queries only | upsert/get/delete/read-all + list_enabled/list_active/set-subscriptions; no consumer-domain methods | ✓ |
| Anticipatory consumer surface | Add P9/P10-shaped methods now | |
| Bare primitives only | upsert + read-all only | |

**User's choice (method surface):** CRUD + column-justified queries only — "but let's remember to finalise it in phases P9/P10 if it's not already noted somewhere."
**Notes:** Forward-note recorded in CONTEXT.md D-09: finalize the store method surface in P9 (RuntimeConfig) / P10 (StrategyRegistry) against real consumers.

---

## Claude's Discretion

- Plan/commit granularity and step ordering within the relocation (subject to mechanical-relocation + byte-exact/inertness gates).
- Precise store method names, column nullability/index choices, and the exact denylisted secret-key-name set.
- Whether strategy_subscriptions is built via the same dict[str, Table] registrar or a companion registrar.

## Deferred Ideas

- Migration baseline reset / squash — a milestone-level decision, not P4.
- Finalize store method surface in P9/P10 against real consumers (explicit user request).
- Applying rehydrated state to live handlers — owned by consumer phases (P6/P9/P10).
