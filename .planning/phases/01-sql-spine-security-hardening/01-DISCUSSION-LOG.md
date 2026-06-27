# Phase 1: SQL Spine + Security Hardening - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-27
**Phase:** 1-SQL Spine + Security Hardening
**Areas discussed:** Spine package home, ID + time encoding, FL-06 rework depth, Postgres test substrate

---

## Spine package home

| Option | Description | Selected |
|--------|-------------|----------|
| New `itrader/storage/` | New top-level package (backend.py, types.py, migrations/), 4-space; SqlSettings in config/sql.py | ✓ |
| Under `itrader/core/` | Co-locate with money/ids/clock — but breaks core's no-internal-deps purity by importing SQLAlchemy | |
| Extend `price_handler/store/` | Reuse existing store/ — but price-data-specific, tab-indented, single-consumer coupling | |

**User's choice:** New top-level `itrader/storage/` (Recommended)
**Notes:** New package + config/sql.py → 4-space indentation. Neutral home all concerns compose.

---

## ID + time encoding

| Option | Description | Selected |
|--------|-------------|----------|
| `sqlalchemy.Uuid` + uniform time | Uuid type for ids (PG-native / SQLite CHAR(32), uniform uuid.UUID); time as uniform ISO-8601 text | ✓ |
| TEXT canonical, both | str(uuid) 36-char + ISO text on both — literally one on-disk encoding | |
| Native-per-dialect (hand-rolled) | with_variant(postgresql.UUID) + timestamptz; more code, normalization in equality test | |

**User's choice:** `sqlalchemy.Uuid(as_uuid=True)` for ids + uniform ISO-8601 UTC text for business-time
**Notes:** User asked to clarify the difference between TEXT-canonical and native-per-dialect, and
specifically about a UUID type column. Clarified: the SQLAlchemy 2.0 `Uuid` type dominates hand-rolled
native-per-dialect (one declaration, auto dialect mapping, uniform `uuid.UUID` Python contract); the
SPINE-03 test asserts Python-value equality, which `Uuid` passes; on-disk representation differs across
backends. Time kept uniform (text/int64) to avoid PG microsecond truncation of any nanosecond
business-time. Plan-time precision check flagged (daily bars → micro almost certainly sufficient).

---

## FL-06 rework depth

| Option | Description | Selected |
|--------|-------------|----------|
| Minimal in-place hardening | Fix creds/f-string/identifiers in place, keep SqlHandler standalone | |
| Full migration onto SqlBackend | Rewrite SqlHandler to compose the new spine — one SQL stack | ✓ |
| Harden + deprecate dangerous methods | Minimal + gate/deprecate destructive DROP/replace paths | |

**Follow-up — FL-06 schema (symbol-as-table-name fix):**

| Option | Description | Selected |
|--------|-------------|----------|
| Single `prices` table, `symbol` column | Collapse table-per-symbol; eliminate dynamic identifiers entirely | ✓ |
| Keep table-per-symbol, safe identifiers | Whitelist + quote identifiers; dynamic table names mitigated not eliminated | |
| You decide at plan time | Defer schema-shape to planner | |

**User's choice:** Full migration onto `SqlBackend` + single `prices` table with a `symbol` value column
**Notes:** More ambitious than the recommended minimal path; aligns with the research's FL-06 framing.
Schema change implies a one-time re-ingest for any external reader of the old per-symbol tables
(plan-time concern). Likely lifts `sql_store.py` out of its D-sql mypy deferral (GATE-02).

---

## Postgres test substrate

| Option | Description | Selected |
|--------|-------------|----------|
| testcontainers Postgres now | Add testcontainers dev-dep; ephemeral PG container; Docker-gated skip; reused by Phase 3 | ✓ |
| Local/env Postgres service | Read PG URL from env, skip when unset; no Docker-in-test but manual setup | |
| SQLite-only in P1, defer PG to P3 | Lightest P1 but leaves PG half of SPINE-03/GATE-02 unproven until P3 | |

**User's choice:** testcontainers Postgres in Phase 1 (Recommended)
**Notes:** SPINE-03 needs the round-trip proven on Postgres; GATE-02 binds the harness here. PG-backed
tests skip/xfail gracefully when Docker is absent (no CI exists yet).

---

## Claude's Discretion

- ISO-8601-text vs int64-epoch for business-time (after the precision check).
- `types.py` helper shapes; `prices` table schema/index shape; Alembic `env.py` boilerplate.
- Whether/how the reworked `sql_store.py` enters `mypy --strict` scope.

## Deferred Ideas

- Async / buffered write-through — N+4 / profile-gated.
- libSQL/Turso as a real backend — v2 TURSO-01 (interface stays ready, driver not added).
- `prices` table one-time migration tooling for any external readers of old per-symbol tables.
- `single-pass-portfolio-valuation.md` todo — perf, orthogonal to the SQL spine; reviewed, not folded.
