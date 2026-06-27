# Phase 1: SQL Spine + Security Hardening - Research

**Researched:** 2026-06-27
**Domain:** Swappable SQLAlchemy-Core SQL spine (SQLite research store + Postgres operational store), cross-dialect UUIDv7/business-time encoding, FL-06 security hardening, Alembic skeleton, testcontainers harness — for a Decimal-end-to-end, deterministic, oracle-gated event-driven trading engine
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** The spine lives in a **NEW top-level `itrader/storage/` package** — `backend.py`
  (`SqlBackend` = Engine + MetaData + Core SQL constructs, no business logic), `types.py`
  (cross-dialect type helpers), `migrations/` (Alembic, live Postgres only). A neutral home that all
  storage concerns *compose*, independent of any one domain (analogous to `core/`). NOT under `core/`
  (would pull SQLAlchemy into the no-internal-deps purity rule) and NOT nested in
  `price_handler/store/` (price-data-specific, tab-indented, single-consumer coupling).
- **D-02:** `SqlSettings` lives in **`config/sql.py`** (Pydantic, consumes `Settings.database_url:
  SecretStr`). New package + new config module → **4-space indentation** (matches `config/`, `core/`).
- **D-03:** Ids use **SQLAlchemy 2.0's `sqlalchemy.Uuid(as_uuid=True)`** column type — one declaration
  that maps to Postgres-native `uuid` and SQLite `CHAR(32)` automatically; Python contract is uniform
  `uuid.UUID` on both. The SPINE-03 cross-backend round-trip test asserts **Python-value equality**,
  satisfied even though on-disk representations differ. Single UUIDv7 scheme preserved (no second ID
  scheme, no DB autoincrement).
- **D-04:** Business-time timestamps stored **uniformly as ISO-8601 UTC text** (or int64 epoch —
  planner's call) on **both** dialects — NOT a native `timestamp`/`timestamptz` column. Rationale:
  Postgres `timestamp` is microsecond-precision and would silently **truncate** nanosecond pandas
  `Timestamp` precision → not lossless. A uniform text/int64 encoding dodges that. No wall-clock writes
  (business `time` only).
- **D-05 (plan-time check):** Confirm the actual precision of the engine's business-time (golden data
  is **daily** bars → microsecond almost certainly sufficient) and pin the chosen text/int64 format so
  two runs encode identical bytes.
- **D-06:** **Full migration** of `SqlHandler` onto the new `SqlBackend` spine (over minimal in-place
  hardening). `SqlHandler` is a price-data store, NOT one of the four composing *domain* storage ABCs —
  it composes the spine as an additional (5th) consumer.
- **D-07:** Resolve the symbol-as-table-name vuln by **collapsing table-per-symbol into a single
  `prices` table with a `symbol` VALUE column** — dynamic identifiers/DDL eliminated; everything
  becomes parameterized values. Schema change: any external reader of the old per-symbol tables needs a
  **one-time re-ingest** (researcher/planner checks for external consumers).
- **D-08:** Credentials sourced from `Settings.database_url.get_secret_value()` (kills hardcoded creds
  L17); f-string `DROP TABLE` (L35) replaced by SQLAlchemy Core / parameterized constructs. Acceptance
  grep gates: no `user:pass@` in any source file; no f-string inside `text()`.
- **D-09 (plan-time note):** Reworking `SqlHandler` onto the spine likely lifts it out of its current
  `D-sql` mypy deferral. GATE-02 requires new spine code `mypy --strict` clean — planner decides
  whether/how the reworked `sql_store.py` enters strict scope.
- **D-10:** Add the **`testcontainers`** dev-dependency and stand up an **ephemeral Postgres container**
  (session-scoped fixture). SPINE-03 needs the round-trip proven on Postgres, not just SQLite, and
  Phase 3 reuses this harness. The spine's own round-trip uses **in-process SQLite**; cross-backend
  parity runs on SQLite **and** testcontainers Postgres.
- **D-11:** PG-backed tests **skip/xfail gracefully when Docker is absent** (no CI exists yet — local
  Docker dependency, must not hard-fail a Dockerless `make test`/`poetry run pytest`).
- **D-12:** `SqlSettings` surface is **minimal now** — driver enum (with a libsql slot, Turso-ready) +
  engine-URL builder consuming `Settings.database_url`. Write-through / retention knobs **deferred to
  Phase 4** where they are consumed.
- **D-13:** **`DecimalAsText` is OMITTED** (Owner Decision) — money never lands on a SQLite-family
  backend (results store = all-`Float`; operational money = Postgres-native `Numeric` in Phase 3).
  `types.py` carries the `Uuid` handling + a `JSON().with_variant(JSONB, "postgresql")` helper, **not** a
  money TypeDecorator. ⚠️ **OVERRIDES** the research, which insists DecimalAsText "must land in Phase 1".
- **D-14:** Alembic skeleton = `env.py` with `render_as_batch=True` + an **empty `versions/`** (no
  operational tables exist until Phase 3); the research/results DB uses `create_all()` (no
  `alembic_version` table). One migration chain, live Postgres only (MIG-01).
- **D-15:** Interface kept **Turso-ready** (driver enum includes a libsql slot) but `sqlalchemy-libsql`
  is **NOT added** to dependencies this milestone (escape path is one engine-URL change, zero code
  change).
- **D-16:** GATE-01 (recurs): SMA_MACD oracle byte-exact **134 / `46189.87730727451`**, no W1/W2
  regression vs the v1.5 frozen baseline (**15.7 s / 152.8 MB**) — the spine is inert on the hot path
  (Phase 1 adds no per-tick code). GATE-02 (bound here): new spine code `mypy --strict` clean, full
  suite green under `filterwarnings=["error"]` with no new broad ignore.

### Claude's Discretion

- Exact `types.py` helper shapes; ISO-8601-text vs int64-epoch for business-time (D-04, pick at plan
  time after the D-05 precision check); the precise `prices`-table schema/index shape (D-07); Alembic
  `env.py` boilerplate.

### Deferred Ideas (OUT OF SCOPE)

- Async / buffered write-through — N+4 / only if profiling justifies.
- libSQL/Turso as a real backend — v2 TURSO-01; interface stays ready, driver not added (D-15).
- `prices` table migration tooling for any external readers of old per-symbol tables (D-07) — a
  one-time concern the planner scopes; not new capability.
- The `ResultsStore` *implementation* (Phase 2); the three operational SQL backends (Phase 3);
  write-through + retention + working-set cache + rehydration (Phase 4); cache classification (Phase 5);
  the Optuna sweep loop (v2); `pyarrow`/Parquet (locked OUT); `DecimalAsText` (locked OUT).
- `single-pass-portfolio-valuation.md` — a perf optimization, orthogonal to the spine, reviewed and NOT
  folded.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SPINE-01 | A single `SqlBackend` + `SqlSettings` selects the SQL driver by config, not code (SQLite research / Postgres operational); Turso-ready, driver NOT added | Standard Stack (SQLAlchemy 2.0 Core, one `create_engine` per URL); Pattern 1 (composition spine); Pattern 5 (driver enum + URL builder). `[VERIFIED: local SQLAlchemy 2.0.50]` |
| SPINE-02 | Three existing ABCs (`OrderStorage`, `PortfolioStateStorage`, `SignalStore`) + new `ResultsStore` ABC each composed by exactly one `Sql<Concern>Storage`; no cross-concern god base | Pattern 1 (compose, not inherit); Architecture map; the three ABCs read from source (`order_handler/base.py` 14 methods, `portfolio_handler/base.py` ~21 methods, `strategy_handler/storage/base.py` 4 methods). Phase 1 ships the spine + (optionally) the `ResultsStore` ABC seam; impls land Phases 2–3 |
| SPINE-03 | UUIDv7 ids + business-time round-trip **losslessly + EQUAL** on SQLite and Postgres; single UUIDv7, no wall-clock, no second ID scheme | D-03 (`Uuid(as_uuid=True)`) VERIFIED CHAR(32)/native-UUID + value-equal; D-04/D-05 (`UtcIsoText` TypeDecorator) VERIFIED round-trips instant-equal. `[VERIFIED: local SQLAlchemy 2.0.50]` |
| SEC-01 (FL-06) | `SqlHandler` parameterized + safe identifiers + creds from secrets — no hardcoded creds (L17), no f-string DDL (L35), no symbol-as-table-name (L56/58/69) | Pattern 4 (single `prices` table + bound params); D-08 cred source confirmed (`Settings.database_url` present, `config/settings.py:39`). No internal/script/test reader of the old per-symbol tables (grep) |
| MIG-01 | Live Postgres store has Alembic migrations (one chain, `render_as_batch=True`); ephemeral research store uses `create_all()` — no `alembic_version` table | Pattern 6 (Alembic scoped to live PG); D-14 skeleton shape; alembic 1.18.5 verified on PyPI |
| GATE-02 (bound here) | New spine code `mypy --strict` clean; full suite green under `filterwarnings=["error"]` no new broad ignore; (GATE-01 recurs) oracle byte-exact + no W1/W2 regression | Validation Architecture section; D-09 mypy-scope resolution; spine is structurally off the hot path (no per-tick code) |
</phase_requirements>

## Summary

Phase 1 builds the **hard dependency root** of v1.6: a single `itrader/storage/` spine package
(`SqlBackend` = Engine + MetaData + Core SQL; `types.py` = cross-dialect type helpers; `migrations/` =
Alembic) plus `config/sql.py::SqlSettings`, composed (never inherited) by every storage concern. The
stack is **already in the tree** — SQLAlchemy 2.0 Core (installed 2.0.50, constraint `^2.0.50` admits
the current 2.0.51) and `psycopg2-binary 2.9.12` need no changes; only two dev-time additions are
required: **`alembic 1.18.5`** (live-PG migration chain) and **`testcontainers 4.14.2`** (ephemeral
Postgres for the SPINE-03 cross-backend round-trip). No `pyarrow`, no `DecimalAsText`, no
`sqlalchemy-libsql` this milestone (all locked OUT / deferred by Owner Decision).

The two SPINE-03 encoding decisions are now **empirically resolved** against the installed SQLAlchemy.
**Ids:** `sqlalchemy.Uuid(as_uuid=True)` compiles to `CHAR(32)` on SQLite and native `UUID` on
Postgres, and a UUIDv7 from the existing `idgen`/`uuid_utils.compat.uuid7()` round-trips back as a
native `uuid.UUID` that compares **equal** — D-03 confirmed, zero custom code. **Business-time:** the
engine's business time is a tz-aware Python `datetime` (microsecond max precision; golden bars are
daily at 00:00 UTC), so a `UtcIsoText` `TypeDecorator` that normalizes to UTC and stores
`datetime.isoformat()` round-trips instant-equal and encodes identical bytes across runs — D-05
resolved in favor of **ISO-8601-UTC-text** over int64-epoch. FL-06 is closed by collapsing
table-per-symbol into one parameterized `prices` table and sourcing creds from the
already-present `Settings.database_url: SecretStr` — and a grep confirms **no internal, script, or test
code reads the old per-symbol tables** (`SqlHandler` is fully quarantined), so D-07's external-reader
risk is effectively nil at the code level.

The dominant risk is **not technical** — it is a precedence one. The milestone research (STACK /
PITFALLS / ARCHITECTURE) makes `DecimalAsText` its #1 load-bearing primitive and says it "must land in
Phase 1." Owner Decision D-13 **omits it** because money never touches a SQLite-family backend this
milestone. This research honors D-13: do **not** build `DecimalAsText`; `types.py` carries only the
`Uuid` handling, the `UtcIsoText` business-time decorator, and a `JSON().with_variant(JSONB,
"postgresql")` helper. The latent Pitfall-1 (Decimal→float on SQLite) is therefore **out of Phase 1
scope** and becomes a Phase 2/3 verification (results store is all-`Float`; operational money is
Postgres-native `Numeric`).

**Primary recommendation:** Build `storage/types.py` first (`Uuid(as_uuid=True)` used directly +
`UtcIsoText` TypeDecorator + `json_variant()` helper, **no DecimalAsText**), then `storage/backend.py`
(`SqlBackend`), then `config/sql.py` (minimal driver-enum + URL-builder `SqlSettings`), then the
Alembic skeleton (`render_as_batch=True`, empty `versions/`), then the FL-06 `SqlHandler` rework onto
the spine (single `prices` table, creds from `SecretStr`), gated by the cross-backend SPINE-03
round-trip on in-process SQLite **and** testcontainers Postgres (Docker-absent → skip).

## Architectural Responsibility Map

This is a backend/storage-infrastructure phase — the "tiers" are internal layers, not web tiers.

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| SQL backend abstraction (Engine/MetaData/Core SQL) | `itrader/storage/` spine (NEW) | — | Domain-neutral home all concerns compose; can't be `core/` (pulls SQLAlchemy past the no-internal-deps rule) |
| Cross-dialect type encoding (UUIDv7, business-time, JSON) | `itrader/storage/types.py` (NEW) | — | One canonical encoding per type, applied uniformly; the SPINE-03 lossless+equal guarantee lives here |
| Backend selection (driver/URL from config) | `config/sql.py::SqlSettings` (NEW, 4-space) | `config/settings.py::Settings.database_url` (secret source) | Config-not-code swap; consumes the existing `SecretStr` (FL-06 cred source) |
| Schema lifecycle — live Postgres | `itrader/storage/migrations/` (Alembic) | `SqlBackend.metadata` | Durable system of record evolves under controlled ALTERs (MIG-01) |
| Schema lifecycle — ephemeral research store | `MetaData.create_all()` | — | Disposable/re-runnable; migration tooling is pure ceremony here (no `alembic_version` table) |
| Price-data persistence (FL-06 target) | `price_handler/store/sql_store.py` (REWORK) | `itrader/storage/` (composes spine as 5th consumer) | `SqlHandler` is a price store, not a domain ABC; D-06 migrates it onto the spine |
| Domain-storage SQL adapters | each domain's `storage/` package | `itrader/storage/SqlBackend` | One `Sql<Concern>Storage` per concern (Phases 2–3); Phase 1 only shapes the spine they will compose |
| Cross-backend test substrate | `tests/` (SQLite in-process + testcontainers PG) | `pyproject.toml` dev-deps | GATE-02 bound here; Phase 3 reuses the PG harness (D-10/D-11) |

**Tier-assignment sanity check:** No capability in this phase belongs on the per-tick hot path — the
spine is structurally inert on the backtest loop (Phase 1 adds zero per-tick code). Any task that wires
SQL into `events_handler`, `bar_feed`, indicator state, or the matching engine is mis-assigned and
violates D-16/GATE-01.

## Standard Stack

### Core (already present — no change)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| SQLAlchemy (Core) | 2.0.50 installed (`^2.0.50`; current 2.0.51) | The single spine — Engine/MetaData/Table/Core SQL that swaps SQLite⇄Postgres by engine-URL alone | Already a dep; one dialect-aware abstraction for all backends; the only current live-path SQLAlchemy importer is `sql_store.py`. `[VERIFIED: local import + PyPI]` |
| psycopg2-binary | 2.9.12 installed | Postgres driver (`postgresql+psycopg2://`) for the operational store + testcontainers connection | Already a dep; SQLAlchemy 2.0 fully supports it; no re-validation needed. `[VERIFIED: local import]` |
| pydantic / pydantic-settings | 2.13.4 / present | `SqlSettings` model + `Settings.database_url: SecretStr` (FL-06 cred source) | Established config system; `SecretStr` masks `repr`/`str`/`model_dump`, reachable only via `.get_secret_value()`. `[VERIFIED: codebase config/settings.py:39]` |
| uuid-utils | 0.16.0 installed | `idgen`/`uuid_utils.compat.uuid7()` → native `uuid.UUID` (single UUIDv7 scheme) | Locked ID scheme; `compat.uuid7()` returns stdlib `uuid.UUID` (interoperates with `sqlalchemy.Uuid`). `[VERIFIED: local import + outils/id_generator.py]` |

### Supporting (ADD as dev-dependencies this phase)

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| alembic | 1.18.5 (2026-06-25, Stable) | Live-Postgres migration chain (one chain, `render_as_batch=True`); ephemeral research DB uses `create_all()` | MIG-01 / D-14. By the SQLAlchemy authors; emits dialect-aware DDL. `[VERIFIED: PyPI]` — NOT currently installed |
| testcontainers | 4.14.2 (2026-03-18) | Ephemeral Postgres container (session-scoped) for the SPINE-03 cross-backend round-trip; reused by Phase 3 | D-10. Use the `[postgresql]` extra (`PostgresContainer`). Docker-absent → skip (D-11). `[VERIFIED: PyPI]` — NOT currently installed |

### Alternatives Considered / Explicitly NOT Added

| Instead of | Could Use | Decision |
|------------|-----------|----------|
| ISO-8601-UTC-text business-time | int64-epoch-micros | **Pick ISO-8601-UTC-text** (D-04/D-05) — legible, sortable as TEXT, no unit-mismatch risk; round-trip VERIFIED. int64 is an equally-lossless alternative if a future numeric-range query wants it |
| `sqlalchemy.Uuid(as_uuid=True)` used directly | A custom `Uuid` TypeDecorator (TEXT-canonical) | **Use the built-in directly** (D-03) — keeps PG-native indexing, least custom code; VERIFIED equal round-trip |
| (no money type) | `DecimalAsText` TypeDecorator | **OMITTED** (D-13) — money never lands on SQLite this milestone. SUPERSEDES the research |
| (no frame codec) | `pyarrow` / Parquet | **OUT** (locked) — results store is all-`Float`, JSON/gzip'd-text in Phase 2 |
| (no extra driver) | `sqlalchemy-libsql` (libSQL/Turso) | **NOT added** (D-15) — driver enum carries a libsql *slot*; escape path is one URL change. Beta, stale (2025-05-30), Linux/macOS-only |
| psycopg2-binary | psycopg (psycopg3) | Stay on psycopg2 — already present, no driver to re-validate |

**Installation:**
```bash
poetry add --group dev alembic@^1.18.5
poetry add --group dev "testcontainers[postgresql]@^4.14.2"
# NOT added this milestone: pyarrow, sqlalchemy-libsql, optuna
```

> **Note on dev vs. runtime grouping (planner's call):** `alembic` is operational tooling and `testcontainers`
> is test-only — both fit the `dev` group. If a future live deploy invokes `alembic upgrade head` from
> the runtime path, alembic may need to move to the main group then; not this phase.

## Package Legitimacy Audit

> slopcheck was **not installable** in this environment. Per protocol, the two NEW packages are tagged
> `[ASSUMED]` and the planner should gate each install behind a `checkpoint:human-verify` task. Both are
> canonical, long-established packages with authoritative source repos (alembic is authored by the
> SQLAlchemy maintainers; testcontainers-python is the official Testcontainers org), and versions were
> confirmed on the PyPI JSON API.

| Package | Registry | Age / Release | Source Repo | slopcheck | Disposition |
|---------|----------|---------------|-------------|-----------|-------------|
| SQLAlchemy | PyPI | mature; 2.0.51 (2026-06-15) | github.com/sqlalchemy/sqlalchemy | unavailable | Already present — Approved |
| psycopg2-binary | PyPI | mature; 2.9.12 | github.com/psycopg/psycopg2 | unavailable | Already present — Approved |
| alembic | PyPI | mature; 1.18.5 (2026-06-25) | github.com/sqlalchemy/alembic | unavailable | ADD — `[ASSUMED]`, planner gate before install |
| testcontainers | PyPI | mature; 4.14.2 (2026-03-18) | github.com/testcontainers/testcontainers-python | unavailable | ADD — `[ASSUMED]`, planner gate before install |

**Packages removed due to slopcheck [SLOP] verdict:** none.
**Packages flagged [SUS]:** none. *(slopcheck unavailable — verification deferred to a planner checkpoint per protocol.)*

## Architecture Patterns

### System Architecture Diagram

```
                       config/settings.py
                       Settings.database_url: SecretStr  ──(get_secret_value)──┐
                                                                               │
   ┌───────────────────────────────────────────────────────────────────┐     │
   │  config/sql.py  (NEW, 4-space)                                      │     │
   │  SqlSettings:  driver ∈ {sqlite_pysqlite, postgresql_psycopg2,      │◄────┘
   │                          sqlite_libsql (SLOT — not wired, D-15)}    │
   │                .engine_url()  → one create_engine() call            │
   └─────────────────────────────────┬─────────────────────────────────┘
                                      │ builds
   ┌──────────────────────────────────▼────────────────────────────────┐
   │  itrader/storage/  (NEW)                                            │
   │  ┌──────────────┐   ┌──────────────────────────────────────────┐   │
   │  │ backend.py   │   │ types.py                                  │   │
   │  │ SqlBackend:  │◄──┤  • Uuid(as_uuid=True)   (used directly)   │   │
   │  │  Engine      │   │  • UtcIsoText(TypeDecorator) business-time │   │
   │  │  MetaData    │   │  • json_variant() → JSON.with_variant(    │   │
   │  │  Core SQL    │   │       JSONB,'postgresql')                 │   │
   │  │  (no biz     │   │  • NO DecimalAsText (D-13)                 │   │
   │  │   logic)     │   └──────────────────────────────────────────┘   │
   │  └──────┬───────┘   migrations/ (Alembic, render_as_batch=True,    │
   │         │            empty versions/ — live PG only; MIG-01/D-14)   │
   └─────────┼──────────────────────────────────────────────────────────┘
             │ COMPOSED (has-a) by — impls land Phases 2–3, ABCs unchanged
   ┌─────────┴───────────────────────────────────────────────────────────┐
   │  OrderStorage   PortfolioStateStorage   SignalStore   ResultsStore    │
   │  (ABC, exists)  (ABC, exists)           (ABC, exists) (NEW ABC seam)   │
   │       ▲                ▲                     ▲              ▲          │
   │  SqlOrderStorage  SqlPortfolioState…    SqlSignal…    SqlResultsStore  │
   │  (Phase 3)        (Phase 3)             (Phase 3)     (Phase 2)        │
   └───────────────────────────────────────────────────────────────────────┘
   ┌───────────────────────────────────────────────────────────────────────┐
   │  price_handler/store/sql_store.py  (REWORK — FL-06)                    │
   │  SqlHandler composes SqlBackend (5th consumer);                        │
   │  table-per-symbol → single `prices` table (symbol = VALUE column);     │
   │  creds from SecretStr; no f-string DDL                                 │
   └───────────────────────────────────────────────────────────────────────┘

   Backtest hot loop (TIME→BAR→SIGNAL→ORDER→FILL): touches NONE of the above.
   Spine is post-loop / live-only. GATE-01 inertness is structural.
```

### Recommended Project Structure (Phase 1 deliverables)

```
itrader/
├── storage/                    # NEW — the shared spine (4-space)
│   ├── __init__.py             #   re-export SqlBackend, the type helpers
│   ├── backend.py              #   SqlBackend: Engine + MetaData + create_engine(SqlSettings.engine_url())
│   ├── types.py                #   Uuid usage + UtcIsoText TypeDecorator + json_variant(); NO DecimalAsText
│   └── migrations/             #   Alembic (live Postgres ONLY)
│       ├── env.py              #     render_as_batch=True; portable types
│       ├── script.py.mako
│       └── versions/           #     EMPTY (no operational tables until Phase 3)
├── config/
│   ├── settings.py             # EXISTS — Settings.database_url: SecretStr (cred source)
│   └── sql.py                  # NEW (4-space) — SqlSettings(driver enum + engine_url builder); minimal (D-12)
├── results/                    # OPTIONAL this phase — ResultsStore ABC seam only (impl = Phase 2)
│   └── base.py                 #   ResultsStore(ABC) if added now; else defer the whole package to Phase 2
└── price_handler/store/
    └── sql_store.py            # REWORK — SqlHandler onto the spine; single `prices` table; SecretStr creds
alembic.ini                     # NEW (repo root or under storage/migrations/) — script_location → storage/migrations
tests/
└── integration/storage/        # NEW — cross-backend SPINE-03 round-trip (SQLite + testcontainers PG)
    ├── conftest.py             #   session-scoped pg_engine fixture; skip on Docker-absent (D-11)
    └── test_spine_roundtrip.py #   UUIDv7 + business-time lossless+equal on both dialects
```

### Pattern 1: The spine via composition — domain ABC ← concrete SQL class ← shared `SqlBackend`

**What:** Each concern keeps its narrow domain ABC. A concrete `Sql<Concern>Storage` *implements that
ABC* and *composes* a shared `SqlBackend` (Engine + MetaData + the `types.py` helpers + dialect-aware
Core SQL). There is deliberately **no** `SqlStorageBase` all four inherit — that re-introduces the
cross-concern god class the seed rejects.
**When to use:** All four stores. Phase 1 only ships the `SqlBackend` they compose (and optionally the
`ResultsStore` ABC seam); the SQL impls land Phases 2–3.
**Source:** `[CITED: research/ARCHITECTURE.md Pattern 1 / Q1-arch]`

```python
# itrader/storage/backend.py  (4-space)
from sqlalchemy import create_engine, MetaData
from sqlalchemy.engine import Engine
from itrader.config.sql import SqlSettings

class SqlBackend:
    """Shared SQL spine: Engine + MetaData + Core SQL. NO business logic."""
    def __init__(self, settings: SqlSettings) -> None:
        self.engine: Engine = create_engine(settings.engine_url())  # driver from config, not code
        self.metadata = MetaData()
```

### Pattern 2: `types.py` cross-dialect helpers (D-13 shape — NO money type)

**What:** One canonical encoding per type, applied uniformly. The SPINE-03 lossless+equal guarantee
lives entirely here. Both encodings below are **VERIFIED** against the installed SQLAlchemy 2.0.50.
**Source:** `[VERIFIED: local SQLAlchemy 2.0.50]` (see Code Examples for the test transcript)

```python
# itrader/storage/types.py  (4-space)
from datetime import datetime, timezone
from sqlalchemy import JSON, String, TypeDecorator, Uuid
from sqlalchemy.dialects.postgresql import JSONB

# Ids: use the built-in directly — CHAR(32) on SQLite, native UUID on PG, value-equal both ways.
UuidType = Uuid(as_uuid=True)            # alias for documentation; or use Uuid(as_uuid=True) at the column

class UtcIsoText(TypeDecorator[datetime]):
    """Business-time as ISO-8601 UTC TEXT — uniform on both dialects (D-04/D-05).
    Normalizes to UTC then isoformat() → identical bytes across runs (determinism);
    fromisoformat() reconstructs the instant (lossless, microsecond precision)."""
    impl = String
    cache_ok = True                       # REQUIRED for mypy --strict + SQLAlchemy caching

    def process_bind_param(self, value: datetime | None, dialect: object) -> str | None:
        if value is None:
            return None
        return value.astimezone(timezone.utc).isoformat()

    def process_result_value(self, value: str | None, dialect: object) -> datetime | None:
        if value is None:
            return None
        return datetime.fromisoformat(value)

def json_variant() -> JSON:
    """Portable JSON column — JSONB on Postgres, JSON(TEXT) on SQLite."""
    return JSON().with_variant(JSONB(), "postgresql")
```

> **Determinism nuance (call out in the plan):** the round-trip is **instant-preserving, UTC-normalized**.
> A business time of `2018-01-01T01:00:00+01:00` (Europe/Paris) is stored as `2018-01-01T00:00:00+00:00`
> and reads back as tz-aware UTC. Aware-datetime `==` compares the UTC instant, so read==original holds,
> and SQLite-read == Postgres-read holds byte-for-byte (identical TEXT). The persisted system-of-record
> form is UTC; recovering the original display tz is a presentation concern, not a fidelity one.

### Pattern 3: Minimal `SqlSettings` — driver enum + URL builder (D-12)

**What:** A Pydantic model that selects the driver and builds the engine URL from
`Settings.database_url`. **Minimal now** — no write-through/retention knobs (deferred to Phase 4). The
driver enum carries a `sqlite_libsql` slot that is NOT wired (D-15 Turso-ready).
**Source:** `[CITED: research/ARCHITECTURE.md Q1/Q2]` + `[VERIFIED: codebase config/settings.py:39]`

```python
# itrader/config/sql.py  (4-space)
from enum import Enum
from pydantic import BaseModel
from itrader.config.settings import Settings

class SqlDriver(str, Enum):
    SQLITE_PYSQLITE = "sqlite+pysqlite"
    POSTGRESQL_PSYCOPG2 = "postgresql+psycopg2"
    SQLITE_LIBSQL = "sqlite+libsql"        # SLOT only — driver NOT added (D-15); escape = one URL change

class SqlSettings(BaseModel):
    driver: SqlDriver = SqlDriver.SQLITE_PYSQLITE   # SQLite = research-store default
    database: str = ":memory:"                       # path / db-name; ignored when a full URL is supplied

    def engine_url(self, settings: Settings | None = None) -> str:
        if self.driver is SqlDriver.POSTGRESQL_PSYCOPG2:
            # creds from the existing SecretStr — FL-06, no hardcoded user:pass@
            return (settings or Settings()).database_url.get_secret_value()
        return f"{self.driver.value}:///{self.database}"
```

> **Note — the `Settings()` import-side-effect trap (Pitfall 8 in research):** `Settings.database_url`
> is required-no-default, so `Settings()` raises `ValidationError` if `ITRADER_DATABASE_URL` is unset.
> Do NOT instantiate `Settings()` at import time in `config/sql.py` or `storage/`; resolve it lazily
> inside `engine_url()` only on the Postgres arm (the SQLite/backtest path stays env-free, mirroring the
> existing logger discipline). `[CITED: config/settings.py docstring]`

### Pattern 4: FL-06 — single `prices` table, parameterized, creds from SecretStr (SEC-01)

**What:** Replace symbol-as-table-name with one `prices` table carrying a `symbol` VALUE column;
replace the f-string `DROP TABLE` with parameterized Core/`text()` bound params; source creds from
`Settings.database_url.get_secret_value()`.
**Source:** `[VERIFIED: codebase sql_store.py L17/L35/L56/L58/L69]` + `[CITED: research/PITFALLS.md Pitfall 13]`

```python
# price_handler/store/sql_store.py (REWORK onto the spine; match the destination package's indentation)
# OHLCV is analytical market data (pandas float64 today) — Float columns, NOT money-policy Decimal.
prices = Table(
    "prices", backend.metadata,
    Column("symbol", String, primary_key=True),
    Column("date",   UtcIsoText, primary_key=True),   # business-time, uniform encoding
    Column("open", Float), Column("high", Float), Column("low", Float),
    Column("close", Float), Column("volume", Float),
)
# write:  df.to_sql("prices", engine, if_exists="append", index=False)  # literal table name = injection-safe
# read:   select(prices).where(prices.c.symbol == bindparam("symbol"))  # bound param, never f-string
# purge:  prices.delete().where(prices.c.symbol == bindparam("symbol")) # or DROP TABLE prices (constant)
```

### Pattern 5: Alembic scoped to live Postgres; `create_all()` for the ephemeral store (MIG-01)

**What:** One Alembic chain, `env.py` with `render_as_batch=True` (SQLite/libSQL ALTER limits) and
portable types; **empty `versions/`** (no operational tables until Phase 3). The research/results DB is
built by `MetaData.create_all()` and has **no** `alembic_version` table.
**Source:** `[CITED: research/STACK.md Q4 / PITFALLS.md Pitfall 6]` + D-14

### Anti-Patterns to Avoid

- **One god `SqlStorage` spanning all concerns** — collapses the three-ABC boundary; compose a shared
  `SqlBackend` instead. `[CITED: ARCHITECTURE Anti-Pattern 2]`
- **A `write_through` flag on a per-tick storage method** — puts serialize code on the byte-exact loop.
  Not in scope here (Phase 4), but do NOT introduce the seam now. `[CITED: ARCHITECTURE Anti-Pattern 3]`
- **Routing the backtest hot loop through SQL** — obliterates v1.5 wins. The spine is post-loop /
  live-only. `[CITED: ARCHITECTURE Anti-Pattern 4]`
- **A DB autoincrement / `Integer primary_key=True`** — a second ID scheme; violates the single-UUIDv7
  lock. UUIDv7 from `idgen` is the PK for every persisted domain row. `[CITED: PITFALLS Pitfall 11]`
- **Re-hardcoding creds or f-string DDL in the FL-06 rework** — the exact defect being removed.
- **Building `DecimalAsText` "to be safe"** — explicitly OUT (D-13); adds an unused primitive and
  re-litigates a locked decision.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| UUID column that works on SQLite + PG | A per-dialect TEXT/BLOB/native switch | `sqlalchemy.Uuid(as_uuid=True)` | Built-in; CHAR(32) on SQLite, native UUID on PG, value-equal — VERIFIED. Hand-rolling risks the Pitfall-11 inconsistent-encoding bug |
| Portable JSON column | `if dialect=='postgresql': JSONB else JSON` branches | `JSON().with_variant(JSONB, "postgresql")` | One declaration; SQLAlchemy renders per-dialect. VERIFIED → `JSON`/`JSONB` |
| Cross-dialect DDL / ALTER | Raw `text()` DDL strings per backend | SQLAlchemy Core `Table` + Alembic `render_as_batch=True` | Core constructs are dialect-aware; raw strings are the FL-06 anti-pattern |
| Migration tooling | A bespoke version table / SQL-file runner | Alembic (by the SQLAlchemy authors) | Dialect-aware autogen; one chain targets PG (and SQLite via batch mode) |
| Ephemeral Postgres for tests | A locally-installed PG + manual setup/teardown | `testcontainers[postgresql]` `PostgresContainer` | Reproducible, isolated, CI-ready; reused by Phase 3 (D-10) |
| Connecting creds from secrets | Re-reading env vars / hardcoding | `Settings.database_url.get_secret_value()` | Already present (M2-06); masks `repr`/`logs`; the FL-06 fix is wiring, not new code |
| Business-time serialization | `str(datetime)` / `datetime.now()` / native `timestamp` column | `UtcIsoText` TypeDecorator (UTC isoformat) | Native PG `timestamp` truncates ns (D-04); wall-clock breaks determinism; explicit format = identical bytes |

**Key insight:** Phase 1 is almost entirely *assembly of well-documented SQLAlchemy 2.0 primitives*.
The two empirically-verified encodings (`Uuid`, `UtcIsoText`) plus `json_variant()` are the whole of
`types.py`. The danger is not building too little — it is building too much (a `DecimalAsText` that D-13
forbids, a `write_through` knob that belongs to Phase 4, a god base class the seed rejects).

## Runtime State Inventory

> This phase has a rename/refactor component (D-07 symbol-as-table-name collapse + FL-06 rework). The
> grep audit below answers "what runtime state survives a source-only change?"

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | Possible pre-existing Postgres DB `trading_system_prices` with one table **per symbol** (created historically by the hardcoded-cred `SqlHandler`). **No in-repo code, script, or test reads these tables** (grep of `read_prices`/`to_database`/`get_symbols_SQL`/`trading_system_prices` across `itrader/` + `scripts/` returns only `sql_store.py` itself — `SqlHandler` is quarantined, not imported at package level). | **None blocking.** If the dev's local `trading_system_prices` data is wanted under the new single-`prices`-table schema, it is **re-creatable from source CSVs** via the providers (one-time re-ingest, D-07). No code migration needed because no code reads the old tables. Document the re-ingest as an optional ops note |
| Live service config | None — no n8n/Datadog/Tailscale/Cloudflare. The only "service" is a local Postgres reachable via the hardcoded URL. | None |
| OS-registered state | None — no Task Scheduler / pm2 / launchd / systemd units reference the renamed tables. | None |
| Secrets / env vars | Two cred seams diverge: `Settings.database_url` (`ITRADER_DATABASE_URL`, SecretStr, the canonical source) and `live_trading_system.py:34` `_SYSTEM_DB_URL = os.getenv("SYSTEM_DB_URL", "")` (a **different** env var, D-live legacy). Plus the **hardcoded `tizianoiacovelli:1234@localhost`** in `sql_store.py:17` (in VCS history). | (1) `SqlSettings.engine_url()` consumes `Settings.database_url` — do NOT add a third source. (2) Reconcile/document `SYSTEM_DB_URL`: it is mypy-deferred D-live code; either point its derivation at `Settings` now (low-risk) or document-and-defer to the live-wiring phase. (3) **Rotate the `:1234` credential** if it was ever real, and scrub from history (FL-06 recovery) |
| Build artifacts / installed packages | None stale from a rename. The new deps (`alembic`, `testcontainers`) require `poetry install` after `pyproject.toml`/`poetry.lock` update. `sql_store.py` exits the `D-sql` mypy-override block (D-09) — a `pyproject.toml` edit, not an artifact. | Run `poetry lock` + `poetry install` after adding deps; update the mypy override list (see D-09 resolution) |

**The canonical question — after every file is updated, what runtime systems still hold the old
string?** Only a possibly-existing local Postgres DB whose per-symbol tables nothing reads. There is no
hidden runtime coupling; the rename is genuinely source-local plus an optional one-time re-ingest.

## Common Pitfalls

### Pitfall 1: `DecimalAsText` re-introduced against D-13 (precedence inversion)

**What goes wrong:** A planner/implementer reads the milestone research (STACK/PITFALLS make
`DecimalAsText` the #1 "must land in Phase 1" primitive) and builds it, re-litigating the locked Owner
Decision. **Why it happens:** The research PREDATES D-13 and is emphatic. **How to avoid:** Honor
D-13 — money never touches SQLite this milestone (results = all-`Float`, operational = PG-native
`Numeric`), so `types.py` has **no** money type. **Warning signs:** a `DecimalAsText`/`Numeric` money
column anywhere in Phase 1; a Decimal value being bound to a SQLite engine. `[CITED: CONTEXT.md D-13 / PROJECT.md Owner Decisions]`

### Pitfall 2: `filterwarnings=["error"]` detonates on a new-dependency warning

**What goes wrong:** alembic / testcontainers / deeper SQLAlchemy 2.0 usage emits a warning the strict
suite turns into a failure. **Why it happens:** `pyproject.toml` sets `filterwarnings = ["error",
"ignore::UserWarning", "ignore::DeprecationWarning"]` — note `UserWarning`/`DeprecationWarning` are
already broadly ignored, but `SAWarning` and others are not. **How to avoid:** Fix the code (e.g. the
correct encoding) rather than broaden the ignore list; if a targeted ignore is unavoidable, use the
narrowest message/category with written justification. **Warning signs:** a green PG run that fails the
moment SQLite or testcontainers runs; a PR adding a broad `filterwarnings` entry. `[VERIFIED: pyproject.toml:74-78]`

### Pitfall 3: A serialize/SQL call leaks onto the byte-exact hot loop (GATE-01)

**What goes wrong:** SQL imports/serialization reachable from the per-tick path → W1/W2 regression even
if the oracle stays byte-exact. **Why it happens:** "wire it in for consistency." **How to avoid:**
Phase 1 adds **zero per-tick code** — the spine is post-loop/live-only and the backtest backends are
untouched. Verify the in-memory backends import no new SQL symbol; oracle byte-exact + W1/W2 within the
v1.5 ±5% gate. **Warning signs:** `import sqlalchemy` reachable from a hot method; W1 >5% over 15.7 s.
`[CITED: research/PITFALLS.md Pitfall 3]` + D-16

### Pitfall 4: Cross-backend divergence (SQLite-only testing)

**What goes wrong:** SPINE-03 "works" on SQLite and breaks on Postgres (type affinity, DDL, JSON).
**How to avoid:** Run the round-trip suite against **both** in-process SQLite **and** testcontainers
Postgres (D-10); stay on Core constructs + portable types (`Uuid`, `json_variant()`, `UtcIsoText`).
**Warning signs:** the test module only ever spins up SQLite; a raw dialect SQL string. `[CITED: research/PITFALLS.md Pitfall 4]`

### Pitfall 5: Tabs-vs-4-spaces breaks a reworked file (`TabError`)

**What goes wrong:** `sql_store.py` is **tab-indented** today; the new `storage/`, `config/sql.py`,
`results/` packages are **4-space**. Mixing in one file fails to parse. **How to avoid:** New packages
= 4 spaces. For the FL-06 rework, D-06 (full migration) suggests relocating the logic into the 4-space
spine consumer — if any code stays in `sql_store.py`, keep it tab-indented; never mix. **Warning
signs:** `TabError`/`IndentationError` on import; a diff mixing tabs and spaces. `[VERIFIED: codebase + CLAUDE.md indentation map]`

### Pitfall 6: Non-determinism at the persistence edge

**What goes wrong:** `datetime.now()` for a timestamp, unordered dict in a JSON dump, no `ORDER BY` on
a query feeding a comparison. **How to avoid:** business `time` only (never wall clock — the
`BacktestClock` raises if not advanced); `sort_keys=True` on JSON dumps; stable `ORDER BY`; the
`UtcIsoText` explicit format. **Warning signs:** `datetime.now`/`time.time` reachable from storage;
`json.dumps` without `sort_keys`. `[CITED: research/PITFALLS.md Pitfall 10]`

### Pitfall 7: `SqlHandler` rework lifts it into `mypy --strict` un-cleanly (D-09 / GATE-02)

**What goes wrong:** Removing `sql_store` from the `D-sql` mypy override exposes untyped legacy code to
`--strict`, breaking GATE-02. **How to avoid:** see the D-09 resolution in Open Questions — make the
reworked file fully typed (it is ~84 lines), or move the logic into the auto-strict `storage/` package
and leave a thin typed shim. `TypeDecorator` subclasses need `cache_ok = True` + typed
`process_*` signatures. **Warning signs:** `mypy --strict` errors in `sql_store` after the override is
removed. `[VERIFIED: pyproject.toml:88-99]`

## Code Examples

Verified against the **installed** stack (SQLAlchemy 2.0.50, Python 3.13.1) — these are not training
recall.

### UUIDv7 cross-dialect column (D-03 — SPINE-03 id half)
```python
# VERIFIED transcript:
#   Uuid(as_uuid=True) -> sqlite: CHAR(32) | postgresql: UUID
#   write uuid_utils.compat.uuid7() into SQLite, read back -> uuid.UUID, EQUAL: True
from sqlalchemy import Uuid, Column
Column("run_id", Uuid(as_uuid=True), primary_key=True)   # value-equal across dialects
# Source: local SQLAlchemy 2.0.50 (this session)
```

### Business-time round-trip (D-04/D-05 — SPINE-03 timestamp half)
```python
# VERIFIED transcript (UtcIsoText TypeDecorator on in-process SQLite):
#   input : 2018-01-01T01:00:00+01:00  (tz-aware Europe/Paris, daily golden bar)
#   stored: "2018-01-01T00:00:00+00:00"
#   read  : datetime(2018,1,1,0,0, tzinfo=timezone.utc)  | instant-equal: True
# Two runs encode identical bytes (explicit UTC isoformat, microsecond max precision).
# Source: local SQLAlchemy 2.0.50 (this session)
```

### Portable JSON column
```python
# VERIFIED: JSON().with_variant(JSONB(), "postgresql")
#   -> sqlite: JSON  | postgresql: JSONB
# Source: local SQLAlchemy 2.0.50 (this session)
```

### SPINE-03 cross-backend round-trip test shape (the load-bearing verification)
```python
# tests/integration/storage/test_spine_roundtrip.py
import pytest, uuid_utils.compat as uc
from datetime import datetime, timezone

@pytest.mark.parametrize("engine", ["sqlite", "postgres"], indirect=True)  # postgres = testcontainers fixture
def test_uuid_and_business_time_lossless_and_equal(engine):
    run_id = uc.uuid7()                                   # native uuid.UUID, single UUIDv7 scheme
    bt = datetime(2018, 1, 1, tzinfo=timezone.utc)        # business time, never wall clock
    # write via SqlBackend table, read back
    got_id, got_bt = roundtrip(engine, run_id, bt)
    assert got_id == run_id          # SPINE-03 value equality (D-03)
    assert got_bt == bt              # instant equality (D-04/D-05)
    assert isinstance(got_id, type(run_id))
# The SAME assertions must pass on SQLite AND testcontainers Postgres (D-10);
# Postgres parametrization skips when Docker is absent (D-11).
```

## State of the Art

| Old Approach (in tree today) | Current Approach (Phase 1) | Impact |
|------------------------------|----------------------------|--------|
| `create_engine('postgresql+psycopg2://tizianoiacovelli:1234@localhost…')` hardcoded | `SqlSettings.engine_url()` from `Settings.database_url.get_secret_value()` | FL-06 cred leak closed |
| `text(f'DROP TABLE IF EXISTS {sym}')` f-string DDL | Parameterized Core / single `prices` table | FL-06 injection closed |
| One table **per symbol** (`to_sql(symbol)`, `read_sql(symbol)`) | One `prices` table, `symbol` VALUE column, bound params | Injection + schema-sprawl eliminated; no external reader breaks (grep-verified) |
| Hand-rolled per-dialect UUID/timestamp encodings (hypothetical) | `Uuid(as_uuid=True)` + `UtcIsoText` + `json_variant()` | Least custom code; cross-backend value-equal, verified |
| `sql_store` in the `D-sql` mypy `ignore_errors` block | Reworked file enters `mypy --strict` (D-09) | GATE-02 coverage |

**Deprecated/outdated (do NOT act on):**
- The seed's **"Turso native DECIMAL preserves the money policy"** — RETRACTED as false (libSQL has no
  lossless DECIMAL). Moot for Phase 1 anyway (no money on SQLite, D-13).
- The research's **DecimalAsText / pyarrow / sqlalchemy-libsql-as-extra** guidance — SUPERSEDED by Owner
  Decisions (D-13 / locked-OUT / D-15). Do not add any of the three.

## Project Constraints (from CLAUDE.md)

- **Money is Decimal end-to-end** — but money never lands on SQLite this milestone (D-13); OHLCV price
  data in `prices` is analytical `Float` (pandas float64 today), distinct from the money ledger.
- **Single UUIDv7 scheme** via `idgen`/`uuid_utils.compat.uuid7()` — no second ID scheme, no DB
  autoincrement PK.
- **Determinism** — business `time` only, never wall clock; `sort_keys` JSON; stable `ORDER BY`.
- **Test strictness** — `filterwarnings=["error"]` (+ `ignore::UserWarning`/`ignore::DeprecationWarning`),
  `--strict-markers`, `--strict-config`; only `unit`/`integration`/`slow`/`e2e` markers exist (folder-derived).
  The PG round-trip tests live under `tests/integration/` → `integration` marker.
- **Indentation** — `storage/`, `config/sql.py`, `results/`, `strategy_handler/storage/` = **4 spaces**;
  `order_handler/storage/`, `portfolio_handler/storage/` = **tabs**; `sql_store.py` = **tabs** today.
  Match the file; never normalize.
- **Import side effects** — `itrader/__init__.py` initializes `config`/`logger`/`idgen` at import; do
  NOT instantiate `Settings()` at import in spine/config modules (`database_url` is required-no-default).
- **mypy `--strict`** over `itrader` — new `storage/`, `config/sql.py`, `results/` are auto-in-scope
  (not in any override block); `sql_store.py` is currently deferred (D-09 resolves how it enters scope).
- **GSD workflow enforcement** — file edits go through a GSD command (this is the research step for the
  planned phase).
- **No project skills** — `.claude/skills/` / `.agents/skills/` absent (confirmed: "No project skills found").

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `alembic` + `testcontainers` are legitimate (slopcheck unavailable; verified on PyPI + known authoritative source repos) | Package Legitimacy Audit | LOW — both are canonical (alembic by SQLAlchemy authors; testcontainers official org). Planner should still gate installs behind a `checkpoint:human-verify` per protocol |
| A2 | ISO-8601-UTC-text is the better business-time encoding vs int64-epoch | D-05 resolution | LOW — both are lossless; int64 is a valid alternative if a numeric-range query later wants it. Round-trip VERIFIED for ISO text |
| A3 | The reworked `sql_store.py` can reach `mypy --strict` clean as a small typed file | D-09 / Pitfall 7 | MEDIUM — pandas `.to_sql`/`read_sql` are partly untyped; may need `# type: ignore[no-untyped-call]` at the pandas boundary or a typed wrapper. Planner verifies during implementation |
| A4 | No external (non-code) consumer depends on the old per-symbol price tables | Runtime State Inventory / D-07 | LOW-MEDIUM — grep proves no in-repo reader, but the developer's local `trading_system_prices` DB content (if any) would need a one-time re-ingest. Confirm with owner whether that data must be preserved |
| A5 | testcontainers `PostgresContainer` API + Docker-absent skip pattern works as expected on this macOS box | Validation Architecture / D-10/D-11 | MEDIUM — not run in this session (testcontainers not installed). Standard usage, but the exact skip-on-`DockerException` wiring is a plan-time implementation detail to validate |
| A6 | The Pitfall-1 `SAWarning` (Decimal→float on SQLite) is a hard failure under `filterwarnings` | (noted, out of Phase-1 scope) | LOW for Phase 1 — could NOT reproduce the SAWarning on SQLAlchemy 2.0.50 with a fractional Decimal this session; irrelevant here (no money on SQLite, D-13) but Phase 2/3 planners should re-verify rather than assume |

## Open Questions

1. **D-05 — business-time format (RESOLVED, planner confirms):**
   - What we know: business `time` is a **tz-aware Python `datetime`** (microsecond max precision);
     golden bars are **daily at 00:00 UTC**; the engine already has a UTC alignment seam
     (`_aligned`, daily-UTC byte-exact). A pandas `Timestamp` (nanosecond) *could* technically subclass
     in, but daily bars carry zero sub-second.
   - Recommendation: **ISO-8601-UTC-text** via `UtcIsoText` (normalize to UTC → `isoformat()`).
     Lossless (microsecond), deterministic (explicit format, identical bytes), value-equal cross-backend
     — all VERIFIED this session. Pin the format as "UTC-normalized `datetime.isoformat()`". int64-epoch-
     micros is an acceptable alternative; pick one and assert byte-identical encoding in the test.

2. **D-07 — external readers of the per-symbol price tables (RESOLVED):**
   - What we know: **no in-repo code, script, or test** reads `read_prices`/`to_database`/the old
     per-symbol tables (`SqlHandler` is quarantined, not imported at package level). The only possible
     consumer is the developer's local `trading_system_prices` Postgres DB.
   - Recommendation: collapse to the single `prices` table freely; scope a **one-time re-ingest** (re-
     download via providers into the new schema) as an optional ops note only if that local data must be
     preserved. Confirm with owner (A4).

3. **D-09 — how the reworked `sql_store.py` enters `mypy --strict` (RESOLVED, planner picks):**
   - What we know: `itrader.price_handler.store.sql_store` sits in the `ignore_errors=true` D-sql
     override (`pyproject.toml:92`). The new `storage/`/`config/sql.py` are auto-strict (no override).
     `postgresql_storage.py` stays deferred (Phase 3 owns it).
   - Recommendation (two viable paths): **(a)** remove `sql_store` from the override block and make the
     ~84-line reworked file fully typed (`TypeDecorator` needs `cache_ok=True` + typed `process_*`;
     pandas `.to_sql`/`read_sql` may need a narrow `# type: ignore` at that boundary); or **(b)** move
     the SQL logic into the strict `storage/` consumer and leave `sql_store.py` a thin typed facade.
     Prefer (a) for a clean single SQL pattern (matches D-06's "do the rework properly"). Either way,
     GATE-02 requires the reworked code strict-clean.

4. **`SYSTEM_DB_URL` reconciliation (planner scopes):**
   - What we know: `live_trading_system.py:34` reads a *different* env var (`SYSTEM_DB_URL`) than the
     canonical `ITRADER_DATABASE_URL`/`Settings.database_url`. `live_trading_system` is D-live, mypy-
     deferred, out of Phase-1 scope.
   - Recommendation: `SqlSettings` consumes `Settings.database_url` only — do NOT add a third source.
     Either point `_SYSTEM_DB_URL` derivation at `Settings` now (small, low-risk) or document-and-defer
     to the live-wiring phase. Pick one and record it so the inconsistency is not silently carried.

5. **Does Phase 1 add the `ResultsStore` ABC seam now, or defer the whole `results/` package to Phase 2?**
   - What we know: CONTEXT.md scope says "only the new ABC seam, if any, is touched here." SPINE-02's
     "four concerns compose the spine" is realized incrementally (impls Phases 2–3).
   - Recommendation: adding just `results/base.py::ResultsStore(ABC)` (no impl) is cheap and makes the
     "all four compose" shape concrete; but it is optional — deferring the entire `results/` package to
     Phase 2 is equally valid. Planner's call; not load-bearing for SPINE-03.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.13 | All code | ✓ | 3.13.1 | — |
| SQLAlchemy 2.0 | The spine | ✓ | 2.0.50 (`^2.0.50` admits 2.0.51) | — |
| psycopg2-binary | Postgres / testcontainers conn | ✓ | 2.9.12 | — |
| uuid-utils | UUIDv7 (`idgen`) | ✓ | 0.16.0 | — |
| pydantic / pydantic-settings | `SqlSettings` / `SecretStr` | ✓ | 2.13.4 | — |
| alembic | MIG-01 migration chain | ✗ | — | `poetry add --group dev alembic@^1.18.5` (no viable fallback — MIG-01 needs it) |
| testcontainers[postgresql] | SPINE-03 PG round-trip (D-10) | ✗ | — | `poetry add --group dev "testcontainers[postgresql]@^4.14.2"` |
| Docker daemon | testcontainers Postgres at test time | ⚠ unverified | — | **D-11 fallback exists:** PG tests skip/xfail when Docker absent; SQLite round-trip still runs |

**Missing dependencies with no fallback:** `alembic` (MIG-01 requires it — must be installed).
**Missing dependencies with fallback:** `testcontainers` install is required, but its *runtime* Docker
dependency degrades gracefully (D-11): a Dockerless `make test`/`poetry run pytest` skips the PG arm and
still runs the SQLite half of SPINE-03 — must not hard-fail.

> **`make test` caveat (from memory):** `make test` exports `ITRADER_DISABLE_LOGS=true` and aborts in
> worktrees on a missing `.env`; the reliable local gate is `poetry run pytest tests`. The current
> branch is a worktree (`v1.6/phase-1-sql-spine`) — plan verification commands accordingly.

## Validation Architecture

> `workflow.nyquist_validation` is `true` (config.json) — this section is REQUIRED.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 (+ pytest-cov, pytest-html), `filterwarnings=["error", ignore::UserWarning, ignore::DeprecationWarning]`, `--strict-markers`, `--strict-config` |
| Config file | `pyproject.toml [tool.pytest.ini_options]`; markers folder-derived in `tests/conftest.py` |
| New fixtures | `tests/integration/storage/conftest.py` — session-scoped `pg_engine` (testcontainers `PostgresContainer`), skip on Docker-absent (D-11) |
| Quick run command | `poetry run pytest tests/integration/storage -q` (spine round-trip) |
| Full suite command | `poetry run pytest tests` (the gate; avoid `make test` in this worktree) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SPINE-03 | UUIDv7 id round-trips value-equal on SQLite | unit/integration | `pytest tests/integration/storage/test_spine_roundtrip.py -k sqlite -x` | ❌ Wave 0 |
| SPINE-03 | UUIDv7 + business-time round-trip value-equal on **Postgres** | integration | `pytest tests/integration/storage/test_spine_roundtrip.py -k postgres -x` | ❌ Wave 0 (testcontainers) |
| SPINE-03 | business-time lossless + identical bytes across two runs (determinism) | unit | `pytest tests/integration/storage/test_spine_roundtrip.py -k determinism -x` | ❌ Wave 0 |
| SPINE-01 | backend selected by `SqlSettings` alone (SQLite vs PG URL) | unit | `pytest tests/unit/storage/test_sql_settings.py -x` | ❌ Wave 0 |
| SEC-01 | no `user:pass@` in any source file | grep gate | `! grep -rIn 'user:pass@\|:1234@' itrader/` | ❌ Wave 0 |
| SEC-01 | no f-string inside `text()` | grep gate | `! grep -rIn "text(f'" itrader/` (+ review `text(f"`) | ❌ Wave 0 |
| SEC-01 | reworked `SqlHandler` reads/writes the single `prices` table parameterized | unit | `pytest tests/unit/price_handler/test_sql_handler.py -x` | ❌ Wave 0 |
| MIG-01 | results/research DB has no `alembic_version` table; live chain applies | integration | `pytest tests/integration/storage/test_migrations.py -x` | ❌ Wave 0 |
| GATE-02 | new spine code `mypy --strict` clean | static | `poetry run mypy itrader` | ✓ (gate exists) |
| GATE-02 | full suite green under `filterwarnings=["error"]` | suite | `poetry run pytest tests` | ✓ |
| GATE-01 | oracle byte-exact 134 / `46189.87730727451` | integration | `poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✓ (oracle exists) |
| GATE-01 | no W1/W2 regression vs 15.7 s / 152.8 MB | perf | `make perf-*` benchmark (same-machine A/B) | ✓ (v1.5 harness) |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/integration/storage -q` + `poetry run mypy itrader`
- **Per wave merge:** `poetry run pytest tests` (full suite, strict)
- **Phase gate:** full suite green + oracle byte-exact + W1/W2 within v1.5 ±5% + FL-06 grep gates clean
  before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/integration/storage/conftest.py` — session-scoped `pg_engine` testcontainers fixture + Docker-absent skip (D-11)
- [ ] `tests/integration/storage/test_spine_roundtrip.py` — SPINE-03 (UUIDv7 + business-time, SQLite + PG, determinism bytes)
- [ ] `tests/unit/storage/test_sql_settings.py` — SPINE-01 driver/URL selection
- [ ] `tests/unit/price_handler/test_sql_handler.py` — SEC-01 reworked handler behavior
- [ ] `tests/integration/storage/test_migrations.py` — MIG-01 (create_all vs Alembic, no alembic_version on results DB)
- [ ] Framework install: `poetry add --group dev alembic@^1.18.5 "testcontainers[postgresql]@^4.14.2"`
- [ ] FL-06 grep gates wired as a test or a Makefile check

## Security Domain

> `security_enforcement` is not set to `false` — section included. This phase is **the** security
> phase (FL-06 / SEC-01).

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | No user auth surface in the spine |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | **yes** | Symbol/identifier never interpolated into SQL — single `prices` table + bound params (Core / `bindparam`); never f-string/`%`/`.format` inside `text()` |
| V6 Cryptography / Secrets | **yes** | DB creds from `Settings.database_url: SecretStr` (`get_secret_value()`); SecretStr masks `repr`/`str`/`model_dump`/logs; remove the hardcoded `:1234@localhost`; rotate if ever real |
| V7 Error/Logging | **yes** | Never log the resolved secret URL; log at the existing `float()`/edge discipline; structlog component binding |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL injection via symbol-as-table-name (`to_sql(symbol)`, `read_sql(symbol)`, L56/58/69) | Tampering | Single `prices` table, `symbol` VALUE column, parameterized reads/writes (literal table name = injection-safe) |
| SQL injection via f-string DDL (`text(f'DROP TABLE … {sym}')`, L35) | Tampering | Parameterized Core constructs / constant DDL (`DROP TABLE prices`); never string-built identifiers |
| Hardcoded credential in source/VCS (`tizianoiacovelli:1234@localhost`, L17) | Information Disclosure | `Settings.database_url.get_secret_value()`; scrub from history; rotate the credential |
| Secret leak into logs at the serialization edge | Information Disclosure | SecretStr masking; never log the engine URL; bound-context structlog |
| Second cred source drift (`SYSTEM_DB_URL` vs `ITRADER_DATABASE_URL`) | Spoofing/Repudiation | One canonical secret source (`Settings.database_url`); reconcile/document the legacy `SYSTEM_DB_URL` seam |

## Sources

### Primary (HIGH confidence)
- **Local SQLAlchemy 2.0.50 (this session)** — empirically verified: `Uuid(as_uuid=True)` → CHAR(32)/UUID + value-equal round-trip; `UtcIsoText` TypeDecorator instant-equal round-trip; `JSON().with_variant(JSONB,"postgresql")` → JSON/JSONB
- **PyPI JSON API** — verified current versions: alembic 1.18.5 (2026-06-25), testcontainers 4.14.2 (2026-03-18), SQLAlchemy 2.0.51 (2026-06-15)
- **Codebase (grep + read)** — `sql_store.py` (FL-06 targets L17/35/56/58/69; quarantined, no readers); `config/settings.py:39` (`database_url: SecretStr`); the three storage ABCs; `pyproject.toml` (mypy D-sql override L88-99, `filterwarnings` L74-78, markers L63-68); `live_trading_system.py:34` (`SYSTEM_DB_URL`); the three storage factories; `core/clock.py`/`core/ids.py`/`outils/id_generator.py`/`events/base.py` (business-time = tz-aware datetime, single UUIDv7)
- **`.planning/PROJECT.md` Owner Decisions + CONTEXT.md D-01..D-16** — the authoritative locked scope (supersede the research)

### Secondary (MEDIUM-HIGH confidence)
- `.planning/research/STACK.md` / `ARCHITECTURE.md` / `PITFALLS.md` / `SUMMARY.md` — HIGH-confidence milestone research, but PREDATES the Owner Decisions; DecimalAsText/pyarrow/sqlalchemy-libsql guidance is SUPERSEDED (applied with the precedence note)

### Tertiary (project, authoritative for this codebase)
- `CLAUDE.md` — money/IDs/determinism locks, indentation map, test strictness, v1.5 baseline + oracle
- MEMORY.md — `make test` worktree/.env caveats; oracle test location (`tests/integration/test_backtest_oracle.py`)

## Metadata

**Confidence breakdown:**
- Standard stack: **HIGH** — all core libs already installed; the two adds verified on PyPI; the two SPINE-03 encodings verified empirically against the installed SQLAlchemy
- Architecture: **HIGH** — composition spine grounded in the three real ABCs + the existing factory pattern; FL-06 targets + no-external-reader confirmed by grep
- Pitfalls: **HIGH** — grounded in code (FL-06 lines, mypy override, filterwarnings, indentation) + the milestone PITFALLS research; the one MEDIUM is A6 (the SAWarning, out of Phase-1 scope per D-13)

**Research date:** 2026-06-27
**Valid until:** ~2026-07-27 (stable stack; SQLAlchemy/alembic move slowly. Re-check alembic/testcontainers
versions if the phase is planned later than that.)
