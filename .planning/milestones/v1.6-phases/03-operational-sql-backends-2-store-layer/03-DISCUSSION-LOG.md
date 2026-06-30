# Phase 3: Operational SQL Backends (#2 — store layer) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-29
**Phase:** 3-Operational SQL Backends (#2 — store layer)
**Areas discussed:** Record schema shape, Portfolio-state layout, Object↔row mapping, Factory + file wiring, Phase-4 forward-coupling, Schema authority (Alembic vs create_all), Enum encoding, Round-trip test strictness

---

## Record schema shape

| Option | Description | Selected |
|--------|-------------|----------|
| Fully typed columns | Every field a typed column (Numeric/Uuid/text/enum); maximally queryable | ✓ |
| Hybrid: key cols + JSON | Promote queried/money columns; rest as JSON(B) payload | |
| JSON doc + money cols | Minimal columns + whole object as JSON document | |

**User's choice:** Fully typed columns
**Notes:** Driven by the FastAPI app needing to query the store directly. Money stays native `Numeric` in all options (OPS-04).

### Brackets (follow-up, forced by columnar choice)

| Option | Description | Selected |
|--------|-------------|----------|
| Self-referential parent_id | Child rows carry nullable parent_order_id FK (indexed); whole bracket in one query | ✓ |
| child_ids array column | Parent stores ARRAY(Uuid)/JSONB; needs read-modify-write + array-containment | |
| Both directions | Redundant parent_id + child_ids | |

**User's choice:** Self-referential parent_id (after clarifying)
**Notes:** User asked which is cleaner for fetching an order + its children from a web app. Recommended self-referential parent_id: one indexed query for the whole bracket (`WHERE order_id = :id OR parent_id = :id`), single-INSERT to add a child (no race-prone read-modify-write), FK integrity, standard REST shape. Array column only wins for object-shape fidelity, which isn't the goal of a queryable store.

---

## Portfolio-state layout

| Option | Description | Selected |
|--------|-------------|----------|
| Table per collection | Normalized: positions/transactions/cash_reservations/locked_margin/cash_operations/equity_snapshots keyed by portfolio_id | ✓ |
| Entity tables + JSON ledger | Normalize positions/snapshots; bookkeeping maps as per-portfolio JSON | |
| Consolidated snapshot | One portfolio_snapshots table, point-in-time full state | |

**User's choice:** Table per collection
**Notes:** Every sub-collection stays a direct SELECT — best fit for web-app drill-down and Phase-4 "load open positions" rehydration.

---

## Object↔row mapping

| Option | Description | Selected |
|--------|-------------|----------|
| Core + converters | Core Tables on shared MetaData + explicit to_row/from_row; dataclasses persistence-ignorant | ✓ |
| ORM models layer | Declarative mapped classes + Session | |

**User's choice:** Core + converters (after clarifying)
**Notes:** User asked the difference between the two ("define tables and models" = the ORM pattern they'd used before). Clarified: both are SQLAlchemy, different layers. In THIS codebase the domain objects are frozen dataclasses that must stay persistence-ignorant (no SQLAlchemy in `core`), and Phase 1 built the spine in Core — so ORM would need a separate `*Row` class + converter anyway, adding a second paradigm without removing the converter. Core chosen for one consistent stack.

---

## Factory + file wiring

| Option | Description | Selected |
|--------|-------------|----------|
| SqlOrderStorage in sql_storage.py | New sql_storage.py per domain; Sql<Concern>Storage; retire PG stub | ✓ |
| Fill PostgreSQLOrderStorage stub in place | Implement existing stub; PostgreSQL* naming | |

**User's choice:** SqlOrderStorage in sql_storage.py
**Notes:** Name matches roadmap (OPS-01) and the dialect-agnostic spine; consistent across all three seams.

### Factory selector string

| Option | Description | Selected |
|--------|-------------|----------|
| Accept both 'live' and 'postgresql' | Aliases for the same SQL backend | |
| Rename to 'postgresql' only | Replace the 'live' arm | |
| Keep 'live' only | Implement behind existing 'live' arm; no new arm | ✓ |

**User's choice:** Keep 'live' only
**Notes:** ⚠️ Deliberate divergence from ROADMAP Phase 3 SC1 ("postgresql/live arm"). Recorded as an owner override (CONTEXT D-06) so the planner does not re-add `postgresql`.

---

## Phase-4 forward-coupling

| Option | Description | Selected |
|--------|-------------|----------|
| Bake in query support now | Add status/is_open/parent_id indexes Phase 4 will query on; no Phase-4 behavior | ✓ |
| Minimal schema, migrate later | Only what Phase 3's own tests need; Phase 4 ALTERs via Alembic | |

**User's choice:** Bake in query support now
**Notes:** Indexes: `(portfolio_id, status)` on orders, `(portfolio_id, is_open)` on positions, `parent_order_id`. Avoids a day-one Phase-4 migration. No write-through/cache/rehydration logic built (that's Phase 4).

---

## Schema authority (Alembic vs create_all)

| Option | Description | Selected |
|--------|-------------|----------|
| Framework owns chain, baseline in Phase 3 | Autogen first migration from MetaData into Phase-1 skeleton; tests use create_all() | ✓ |
| Framework MetaData only, app owns Alembic | Ship MetaData + create_all(); FastAPI app generates the unified chain | |
| create_all() everywhere, defer Alembic | No baseline until Phase 4/app integration | |

**User's choice:** Framework owns chain, baseline in Phase 3 (after clarifying)
**Notes:** User confirmed they'll use Alembic at the FastAPI application level and asked whether to also use it here. Clarified the split: MetaData is the single source of truth; tests/dev use `create_all()` (fast, no per-test migration); deploy uses Alembic. Key architectural point relayed — don't run two Alembic chains over the same tables. Framework owns its operational-table chain; the FastAPI app runs itrader's chain on deploy + keeps app tables in its own chain. Forward-coupling (D-08) stabilized the schema, making a Phase-3 baseline low-risk.

---

## Enum encoding

| Option | Description | Selected |
|--------|-------------|----------|
| Plain text + app validation | Store .value as String; validate on read via order_*_map | ✓ |
| Postgres-native ENUM | DB-level validation; ALTER TYPE friction; Postgres-only | |
| Text + CHECK constraint | Text + CHECK(... IN ...); migration to extend | |

**User's choice:** Plain text + app validation
**Notes:** Matches the dialect-agnostic spine; adding an enum member is a zero-schema-change op; existing string↔enum maps already validate.

---

## Round-trip test strictness

| Option | Description | Selected |
|--------|-------------|----------|
| Object equality + Decimal/Numeric exactness | obj2 == obj + exact Decimal money + UUIDv7 value-equal + two-run determinism | ✓ |
| Column-value assertions | Per-column SQL-layer assertions only | |
| Both (object equality + per-column) | Belt-and-suspenders | |

**User's choice:** Object equality + Decimal/Numeric exactness
**Notes:** Proves the full to_row/from_row contract end-to-end, not just storage. Gate (b) on testcontainers Postgres.

---

## Claude's Discretion

- Exact column lists/types per Table (beyond money/id/enum/time rules); index names.
- Whether `SqlPortfolioStateStorage` needs a `portfolios` parent table or keys directly off `portfolio_id`.
- Alembic `env.py` autogenerate wiring; exact migration content (autogen from MetaData).
- Whether reworked SQL modules enter `mypy --strict` scope now (cf. Phase 1 D-09).
- Handling of the retired `postgresql_storage.py` stub (delete vs deprecate-and-re-export).

## Deferred Ideas

- Live write-through / working-set cache / purge / read-through / rehydration — Phase 4.
- `postgresql` factory arm — explicitly NOT added (owner override).
- FastAPI application layer + app-specific Alembic chain — downstream application concern (captured as forward context for the D-09 ownership split).
