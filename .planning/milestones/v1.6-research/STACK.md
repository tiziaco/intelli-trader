# Stack Research — v1.6 Persistence Foundation

**Domain:** Durable storage + caching substrate for an event-driven backtest/live trading engine (swappable SQL spine; all-SQL results store; live operational store; cache classification)
**Researched:** 2026-06-27
**Confidence:** HIGH on versions + SQLAlchemy/SQLite/Postgres mechanics (Context7-adjacent official docs + PyPI JSON API verified); MEDIUM-HIGH on Turso/libSQL maturity (web-verified, honestly a moving target); HIGH on the Decimal-fidelity correction (multiple sources + SQLite type-affinity spec).

> **Scope note.** This is a SUBSEQUENT milestone on a converged design. The backend *set* (Turso/libSQL + SQLite + Postgres), the all-SQL results store, and the cache≠store split are **locked decisions** — not relitigated here. This doc makes the concrete library/version/tooling calls and answers Q1–Q5. The optimization/sweep LOOP (Optuna sampler) is OUT of this milestone; only the storage-library angle of it is weighed.

> **CORRECTION TO DESIGN SEED (load-bearing).** The seed asserts *"Turso native DECIMAL preserves the money policy."* **This is false.** libSQL is a byte-compatible SQLite fork with the *same* type system — it has **no native lossless DECIMAL storage class**; `DECIMAL` columns get NUMERIC affinity and are coerced to REAL/INTEGER. Under SQLAlchemy `Numeric(asdecimal=True)`, SQLite/libSQL emit `SAWarning: Dialect ... does *not* support Decimal objects natively ... must convert from floating point` and round money through a float. **Given this project's `filterwarnings=["error"]`, that warning is a hard test failure — and it silently violates the Decimal-end-to-end money policy.** Money on SQLite/libSQL MUST be stored via a `Decimal`-as-TEXT `TypeDecorator` (or scaled integer), never `Numeric`. See Q5 + Version Compatibility.

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| **SQLAlchemy** (Core) | **2.0.51** (current; already `^2.0.50`) | The single storage interface — Engine/MetaData/Table/Core SQL that swaps SQLite ⇄ libSQL ⇄ Postgres by engine-URL alone | Already a dependency. Provides one dialect-aware abstraction for all three backends; libSQL plugs in *on top of* its native SQLite dialect (dialect siblings). This is THE spine. (Q1) |
| **SQLite** (stdlib `sqlite3` via `sqlite+pysqlite://`) | bundled w/ CPython 3.13 | Default/primary results-store + ephemeral backtest DB | Zero new deps, C-native synchronous, fastest path for our batch end-of-run dump, and the **dialect sibling that is the libSQL fallback** (swap URL back, no code change). (Q2) |
| **psycopg2-binary** | **2.9.12** (already present) | Postgres driver for the live operational store (`postgresql+psycopg2://`) | Already a dependency; the live system-of-record backend. No change needed. |
| **sqlalchemy-libsql** | **0.2.0** (Beta) | `sqlite+libsql://` dialect — the config-selected Turso/libSQL backend | Only supported way to reach libSQL/Turso through SQLAlchemy. **Add as an OPTIONAL extra**, not a hard core dep (beta; see Q2 maturity verdict). |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| **pyarrow** | **24.0.0** (current; Py≥3.10, 3.13 wheels ✓) | Serialize the `run_artifacts` equity-curve / trade-log DataFrame to **Parquet-bytes** for the SQL BLOB column | ADD. The recommended frame-blob format (Q5) — best compression, fast columnar round-trip, Decimal128 fidelity. |
| **libsql-experimental** | **0.0.55** (sub-0.1, "not production grade") | Native Rust binding pulled in transitively by `sqlalchemy-libsql` 0.2.0 | Only via the dialect. The dialect pins `libsql-experimental>=0.0.53`, NOT the newer `libsql` 0.1.x — a staleness flag (Q2). Linux+macOS only. |
| **alembic** | **1.18.5** (current, by the SQLAlchemy authors) | Schema migrations for the **live Postgres** store (single chain, batch-mode for SQLite/libSQL) | ADD, but scope to live. Backtest/results DB uses `create_all()` (Q4). |
| **optuna** | **4.9.0** (current) | (Future milestone) sweep sampler; its `RDBStorage` is SQLAlchemy-backed | **Do NOT add this milestone.** Noted for Q6 schema-readiness only — keep our own `runs` schema; Optuna joins later as just the sampler. |
| **pydantic-settings** `SecretStr` | already present (`Settings.database_url: SecretStr`, M2-06) | FL-06 hardcoded-creds fix — `SqlHandler`/`SqlSettings` consume `database_url.get_secret_value()` | The scaffolding already exists; wire `SqlHandler` to it (kills the line-17 hardcoded `tizianoiacovelli:1234@...`). |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| Alembic CLI | `alembic revision --autogenerate` / `upgrade head` for the live store | Set `render_as_batch=True` in `env.py` so SQLite/libSQL ALTERs work (move-and-copy). |
| SQLAlchemy `text()` + bound params / `Table` reflection | FL-06 SQL-injection fix in `SqlHandler` | Replace the f-string `DROP TABLE IF EXISTS {sym}` (line 35) and `to_sql`/`read_sql` symbol-as-table-name (lines 56/69) with quoted-identifier/whitelisted or single-table-with-`symbol`-column patterns. |
| `pytest` (`filterwarnings=["error"]`) | The strictness gate that turns the SQLite Decimal `SAWarning` into a failure | This is a *feature* here — it will catch any accidental `Numeric` money column on SQLite/libSQL at test time. Lean on it. |

## Installation

```bash
# Already present — no action: sqlalchemy ^2.0.50→pin allows 2.0.51, psycopg2-binary 2.9.12, msgspec 0.21.1, pandas 2.3.3
# ADD (core to this milestone):
poetry add pyarrow@^24.0.0          # frame-blob serialization (Q5)
poetry add alembic@^1.18.5          # live-store migrations (Q4)

# ADD as an OPTIONAL extra (Turso/libSQL backend — beta; keep out of the hard core dep set):
poetry add --optional sqlalchemy-libsql@^0.2.0   # pulls libsql-experimental transitively (Linux/macOS only)
# then expose via [tool.poetry.extras]  turso = ["sqlalchemy-libsql"]

# DO NOT ADD this milestone:
#   optuna           — sweep loop is a later milestone (substrate only)
#   the `libsql` 0.1.x package directly — the dialect wants libsql-experimental, not this
```

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| SQLAlchemy Core as the unifier | Raw per-driver code paths (sqlite3 + libsql + psycopg2 by hand) | Never for this milestone — defeats the config-not-code spine; only if a backend needs SQL SQLAlchemy can't express (none identified). |
| SQLite as results-store **default** | libSQL/Turso as default | Choose libSQL when you genuinely need *remote/shared* sweep results across machines or an embedded-replica edge story — not for single-process batch dump (no perf win there; Q2). |
| Parquet-bytes (pyarrow) for the frame blob | Compressed pickle (stdlib `pickle`+`lzma`) | Use pickle ONLY if pyarrow cannot be added — perfect Decimal fidelity + zero deps, but Python-locked + version-brittle + opaque. (Q5) |
| Scalar-promote filterable params to indexed columns | Pure JSON filtering (`settings->>'lookback'`) | Pure-JSON is fine for PG-only deployments with GIN indexes; reject for the cross-backend `runs` table (Q3). |
| Alembic scoped to live Postgres | Alembic gating the backtest/results DB too | Only if the ephemeral results schema becomes long-lived/shared; today it's disposable → `create_all()` (Q4). |
| psycopg2-binary (live) | psycopg (psycopg3) | Stay on psycopg2 — already present, SQLAlchemy 2.0 fully supports it, no driver to re-validate this milestone. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `Numeric`/`DECIMAL` SQLAlchemy column for **money on SQLite/libSQL** | No native lossless DECIMAL → float coercion → `SAWarning` (= test failure under `filterwarnings=["error"]`) + money-policy violation | `TypeDecorator` storing `Decimal` as **TEXT** (`String`), or scaled-integer; `Numeric` is fine ONLY on Postgres. |
| **Turso Database** (the Rust rewrite, formerly "Limbo", `tursodatabase/turso`, v0.6.x) | NOT production-ready as of 2026; different product from libSQL despite the shared "Turso" branding | **libSQL** (production-ready SQLite fork) via `sqlalchemy-libsql` for the "Turso" backend slot. |
| Old websocket/HTTP driver `libsql-client(-py)` | Superseded; older websocket drivers stopped working after the 2025 Fly.io→AWS migration | The Rust-binding path (`libsql-experimental`/`libsql`) via the dialect. |
| Parquet/Arrow as **separate files** alongside SQL | Cannot cheaply append for live; breaks backtest↔live symmetry (already REJECTED in the seed) | Parquet **bytes inside** the SQL `run_artifacts` BLOB column. |
| pyarrow **scale inference** from object-dtype Decimal columns | Inferred `decimal128(p,s)` varies run-to-run → non-deterministic bytes (breaks byte-exact/determinism discipline) | Pin an **explicit pyarrow schema** with per-column `decimal128(precision, scale)` matching `core/money.py` instrument scales. |
| msgspec for the frame blob | msgspec is a struct/JSON/msgpack codec, not a columnar DataFrame format; Decimal handling would be custom + uncompressed | Keep msgspec for the event chain (its v1.5 home); use pyarrow for DataFrame blobs — complementary, not competing. |

## Stack Patterns by Variant

**If results store / backtest / optimization sweep (write-once-read-later):**
- Default engine `sqlite+pysqlite:///results.db` (or `:memory:` in tests); `create_all()` schema; `run_artifacts` = Parquet-bytes BLOB; `runs` = scalar-promoted indexed params + `JSON` settings archival column.
- Optional `sqlite+libsql://...` engine selected by `SqlSettings` when remote/shared sweep storage is wanted.

**If live operational store (read-write, restart-safe, system of record):**
- Engine `postgresql+psycopg2://` from `Settings.database_url` (SecretStr); Alembic-migrated schema; `Numeric` money columns are safe here (PG native NUMERIC); write-through ON; working-set cache purge-on-terminalize.

**If money column on any SQLite-family backend:**
- Always the `DecimalAsText` `TypeDecorator`. One decorator, applied uniformly across all three dialects, gives byte-exact cross-backend money + silences the `SAWarning` + holds the money policy.

## Version Compatibility

| Package A | Compatible With | Notes |
|-----------|-----------------|-------|
| SQLAlchemy 2.0.51 | Python 3.13 | Production/Stable; current `^2.0.50` constraint already admits it. |
| sqlalchemy-libsql 0.2.0 | SQLAlchemy ≥2.0, Python 3.13 (via libsql-experimental wheels) | **Beta; last released 2025-05-30** (~13 mo stale). Pins `libsql-experimental>=0.0.53` (sub-0.1) — does NOT track the newer `libsql` 0.1.11. Pulls `greenlet>=3.0.3`. **Risk:** dialect could lag if libsql-experimental is retired for `libsql`; validate the pin on install. |
| libsql-experimental 0.0.55 | CPython 3.8–3.13 wheels | **Linux + macOS only — no Windows.** Fine for this macOS/Linux project; flag for any CI matrix. |
| pyarrow 24.0.0 | Python ≥3.10 → 3.13 ✓, pandas 2.3.3 | Decimal128 round-trip is lossless in VALUE; pandas dtype returns as `object`(Decimal) — desired for money. Decimal write ~4× slower than numeric (acceptable for per-run blob). |
| alembic 1.18.5 | Python ≥3.10, SQLAlchemy ≥1.4 (→2.0.51) | Use `render_as_batch=True` for SQLite/libSQL ALTER limits; `JSON().with_variant(JSONB,'postgresql')` for the settings column. |
| psycopg2-binary 2.9.12 | SQLAlchemy 2.0, Python 3.13 | Already present; no re-validation needed. |

**Headline compatibility risk:** the only genuinely shaky pin is **sqlalchemy-libsql 0.2.0 (beta, stale, experimental driver, no Windows)**. The mitigation is structural, not a version bump: SQLite and libSQL are **dialect siblings**, so the *entire* libSQL risk is escapable by changing one engine URL back to `sqlite+pysqlite://` with zero code change. Keep libSQL an optional extra; keep SQLite the proven default.

---

## Open-Question Resolutions (Q1–Q5)

### Q1 — Interface unifier: SQLAlchemy 2.0 Core, per-dialect engine URLs

**Recommendation: YES — SQLAlchemy 2.0 Core is the correct single abstraction. Use Core (Engine + MetaData/Table + Core SQL expression language) with a per-dialect engine URL selected by `SqlSettings`. libSQL/Turso does NOT need a driver path outside SQLAlchemy.**

Why it works cleanly:
- All three backends are SQLAlchemy dialects: `postgresql+psycopg2://` (live), `sqlite+pysqlite://` (default/fallback), `sqlite+libsql://` (Turso/libSQL via `sqlalchemy-libsql`).
- The libSQL dialect is built **on top of SQLAlchemy's native SQLite (pysqlite) dialect** — note the `sqlite+libsql` scheme. SQLite and libSQL therefore share SQL generation, type affinity, and DDL behavior. The SQLite⇄libSQL swap is literally an engine-URL change; the SQLite⇄Postgres swap is a normal cross-dialect Core swap SQLAlchemy is designed for.
- `SqlSettings` builds the URL (+ `connect_args` like libSQL `sync_url`/`auth_token`) → one `create_engine()` call → backend = config, not code. ✅ achievable.

What breaks the zero-friction swap (and the mitigation for each):
1. **Decimal/money types (the #1 friction).** SQLite/libSQL NUMERIC-affinity float-coerces money + emits a `SAWarning` (→ test failure here). **Mitigate with a single `DecimalAsText` `TypeDecorator` applied uniformly.** Postgres NUMERIC is lossless; the decorator unifies behavior so the same model is byte-exact on all three.
2. **JSON semantics** — PG JSONB (binary, indexable) vs SQLite/libSQL JSON-as-TEXT. Storage portable via `JSON().with_variant(JSONB,'postgresql')`; *filtering* is not portable → Q3.
3. **Dialect-specific DDL/SQL** — `JSONB` type, `ON CONFLICT`/upsert nuances, `RETURNING` (PG yes; SQLite 3.35+/libSQL yes), autoincrement/identity. Stay on Core's portable types + Core's `insert().on_conflict_*` constructs; avoid raw dialect SQL strings. The FL-06 f-string DDL in `SqlHandler` is exactly the anti-pattern to delete.

**Alternative considered:** raw per-driver code (sqlite3/libsql/psycopg2 by hand) — rejected; it throws away the spine and re-implements dialect handling SQLAlchemy already does.

---

### Q2 — Turso/libSQL maturity: HONEST verdict — the perf premise does NOT hold for our workload

**Recommendation: Support all three backends (locked), but make SQLite the results-store DEFAULT and treat Turso/libSQL as an OPTIONAL, config-selected backend validated opt-in. Keep SQLite as the zero-cost escape path (dialect sibling). The "Turso is faster" premise is a hypothesis that fails for our batch-dump + occasional-read pattern.**

Landscape (a branding trap to call out): **"Turso" is two products.**
- **libSQL** — production-ready, byte-compatible SQLite fork; this is what `sqlalchemy-libsql`, `libsql-experimental` (0.0.55), and the newer `libsql` (0.1.11) target. **For this milestone "Turso/libSQL" = libSQL.**
- **Turso Database** — the Rust-from-scratch rewrite (formerly "Limbo", `tursodatabase/turso`, v0.6.x, 2026-05). Adds `BEGIN CONCURRENT`/MVCC + CDC but is **NOT production-ready**. Do not target it.

Python driver status (honest):
- `libsql-experimental` **0.0.55** is explicitly *"not production grade"*, sub-0.1, **Linux+macOS only**. It has 3.13 wheels.
- A successor `libsql` **0.1.11** (Sept 2025) exists, but the SQLAlchemy dialect still pins **libsql-experimental**, not `libsql` — a coupling/staleness flag.
- The dialect `sqlalchemy-libsql` **0.2.0** is **Beta**, last released **2025-05-30**.

Modes / types / guarantees:
- **Modes:** local-file (`sqlite+libsql:///x.db`), in-memory, **embedded replica** (local file + `sync_url`+`auth_token`, syncs from remote — Python support is *beta*), remote-only. ACID + single-writer inherited from SQLite (the MVCC concurrent-writes win lives in the Rust rewrite, not libSQL).
- **Decimal:** NO native lossless DECIMAL (inherits SQLite affinity) → same float-coercion problem as SQLite → **must use the `DecimalAsText` decorator**. The seed's "native DECIMAL" claim is wrong.
- **JSON:** SQLite JSON1/`json_extract` inherited, stored as TEXT.

**Perf hypothesis verdict — NOT real for our pattern.** Turso/libSQL's headline advantages are edge replication, embedded replicas, and (in the Rust rewrite) concurrent writes — all aimed at *distributed/high-concurrency edge writes*. Our results-store pattern is a **single-process batch dump at end-of-run + occasional analytical read**. For that, plain local SQLite (stdlib `sqlite3`, C-native, synchronous, zero deps) is as fast or **faster** than the async-bridged libSQL Rust binding, with none of the beta risk. libSQL's value here is **operational** (managed remote DB, shared sweep results across machines, a future live-edge story) — not throughput.

**Fallback / escape path:** because SQLite and libSQL are dialect siblings, the entire libSQL risk is escapable by reverting one engine URL to `sqlite+pysqlite://` — no schema or code change. That makes adopting libSQL low-risk *as an option* and makes SQLite the safe default.

> This honestly answers the quality gate's "Turso maturity verdict is a perf hypothesis, not a given." It is a hypothesis, and for this workload it does not hold — so SQLite leads and libSQL rides the same spine as an opt-in.

---

### Q3 — Cross-backend JSON: scalar-promote filterable params; keep full settings in an archival JSON column

**Recommendation: Hybrid. Promote the handful of filterable/sweepable params into real typed, indexed columns on `runs` (e.g. `lookback INTEGER`, `fast_window INTEGER`, `slow_window INTEGER`). Keep the FULL heterogeneous module-settings dict in a `settings JSON` column for archival/reproduction only — never filtered in hot cross-sweep queries.**

Why:
- **Storage** of JSON is portable (SQLAlchemy `JSON` → PG `JSONB` via `.with_variant`, SQLite/libSQL TEXT). Not the problem.
- **Filtering** is NOT cleanly portable. PG: `settings->>'lookback'` returns *text* → needs a cast for `> 20`; GIN-indexable. SQLite/libSQL: `json_extract(settings,'$.lookback')` (JSON1); no index unless you build an expression index; numeric-vs-text comparison semantics differ from PG. SQLAlchemy renders JSON path access per-dialect, so a single `WHERE settings['lookback'].as_integer() > 20` does not behave identically (or index identically) across all three.
- Scalar promotion sidesteps all of it: `WHERE lookback > 20 ORDER BY sharpe DESC LIMIT 10` hits plain indexed columns → **identical + fast on all three backends**. The cross-backend JSON-filter portability problem **dissolves** rather than being papered over.
- This is the standard hybrid relational+JSON pattern: relational columns for the query surface, JSON for the long tail / exact-params reproduction.

**Alternative considered:** pure JSON filtering with PG GIN indexes — fine for a PG-only deployment, rejected for the cross-backend `runs` table. **Optuna-readiness note (Q6, FEATURES owner):** promoting params to columns is also what a future Optuna join wants (params as first-class queryable fields), so this choice is forward-compatible.

---

### Q4 — Migrations: Alembic, scoped to the live Postgres store; `create_all()` for the ephemeral results DB

**Recommendation: Adopt Alembic (1.18.5) as ONE migration chain, but apply it as the authoritative schema path only for the LIVE Postgres operational store. Use `MetaData.create_all()` (create-if-not-exists) for the ephemeral/disposable results + backtest DB. Lowest friction: don't gate backtest on migrations; gate live on them.**

Why:
- Alembic is by the SQLAlchemy authors, emits dialect-aware DDL through SQLAlchemy, and ONE chain *can* target all three dialects — with two required accommodations: (1) `render_as_batch=True` in `env.py` so SQLite/libSQL's limited `ALTER TABLE` works via move-and-copy (libSQL inherits SQLite's ALTER limits); (2) portable types via `JSON().with_variant(JSONB,'postgresql')` so a column isn't PG-only.
- The **results/backtest DB is ephemeral and re-runnable** — you don't migrate sweep data, you re-run it. Migration tooling there is overhead with no payoff; `create_all()` is faster, simpler, test-friendly (`:memory:`), and adds zero ceremony to the byte-exact backtest path.
- The **live Postgres store is a durable system of record** — schema evolves, you cannot drop-and-recreate without losing state → migrations are genuinely warranted there.

**Alternative considered:** no migration tool at all (just `create_all()` everywhere) — acceptable until the live schema first changes in production, at which point you need controlled ALTERs; cheaper to stand Alembic up now and scope it to live. Heavier alternatives (sqitch, raw SQL files) add an out-of-ecosystem tool for no benefit over Alembic.

---

### Q5 — Frame serialization for `run_artifacts`: Parquet-bytes via pyarrow (explicit Decimal schema)

**Recommendation: Parquet-encoded bytes (pyarrow 24.0.0) stored in the SQL BLOB column, with an EXPLICIT pyarrow schema pinning each money column to `decimal128(precision, scale)` matched to `core/money.py` instrument scales. Fallback: lzma-compressed pickle if pyarrow cannot be added.**

Comparison for the equity-curve / trade-log DataFrame blob:

| Format | Compression | Round-trip → pandas | Decimal fidelity | Cross-backend byte portability | Verdict |
|---|---|---|---|---|---|
| **Parquet-bytes (pyarrow)** | **Best** (columnar + dict + zstd) | Fast columnar; money returns as `object`(Decimal) | **Lossless** via decimal128 (value-exact) | Identical bytes → PG `BYTEA` / SQLite/libSQL `BLOB` | **RECOMMENDED** |
| Arrow IPC / Feather | Worse than Parquet, larger | Fastest write (no Parquet encode) | Same decimal128 support | Portable | Runner-up; pick only if write speed dominates — we dump once/run, so compression wins |
| JSONB | Worst (text) | Slow parse | Lossy unless Decimal serialized as **string** (JSON numbers are float) → bloated | Portable but huge | Reject for frames |
| Compressed pickle (stdlib) | Good | Trivial, native objects | **Perfect** (native Python Decimal) | Python-only, version-brittle, opaque | **Fallback only** (zero-dep, perfect fidelity, but not cross-language + pandas/numpy pickle-version risk) |

Rationale:
- **Compression** keeps `run_artifacts` lean so the hot `runs` metrics table stays fast (PG TOASTs the blob, SQLite/libSQL spill to overflow pages — both free). At large sweeps this is what makes all-SQL scale.
- **Decimal fidelity (critical).** pyarrow auto-maps object-dtype `Decimal` columns to Parquet decimal128 and back, value-lossless. BUT pin an **explicit schema per money column** — pyarrow's *inferred* precision/scale varies with the data, producing non-deterministic bytes that would break the byte-exact/determinism discipline. Explicit `decimal128(p, s)` from the instrument scales = lossless **and** deterministic.
- **Portability.** The Parquet bytes are self-describing and identical regardless of which SQL backend stores them → a frame written under SQLite reads back identically from Postgres. Aligns with NautilusTrader's `ParquetDataCatalog` precedent and keeps a DuckDB-over-exported-frames analytical escape hatch open (the seed's "avg equity at bar 500 across all runs" case).

The pyarrow add tradeoff: a sizable wheel, and decimal writes ~4× slower than numeric — both acceptable for a once-per-run blob, and pyarrow is the same engine any future columnar work would use. **msgspec stays in its event-chain lane; it is not a DataFrame columnar codec** — these are complementary.

---

## Sources

- PyPI JSON API (`pypi.org/pypi/<pkg>/json`) — verified current versions/dates/status: SQLAlchemy 2.0.51 (2026-06-15, Stable), pyarrow 24.0.0 (2026-04-21), alembic 1.18.5 (2026-06-25, Stable), optuna 4.9.0 (2026-06-01), sqlalchemy-libsql 0.2.0 (2025-05-30, Beta; deps `libsql-experimental>=0.0.53`, `sqlalchemy>=2.0.0`, `greenlet>=3.0.3`), libsql-experimental 0.0.55 (2025-06-09), libsql 0.1.11 (2025-09-02). **HIGH.**
- https://docs.turso.tech/sdk/python/orm/sqlalchemy — `sqlite+libsql://` scheme; embedded-replica/remote/memory/local modes. **HIGH.**
- https://github.com/tursodatabase/sqlalchemy-libsql + https://pypi.org/project/libsql-experimental/ — Beta status, "not production grade", Linux/macOS-only, CPython 3.8–3.13 wheels. **MEDIUM-HIGH.**
- https://github.com/tursodatabase/libsql + https://docs.turso.tech/libsql — libSQL = backwards-compatible SQLite fork, same file format/type system, no native DECIMAL. **HIGH.**
- https://github.com/tursodatabase/turso — Turso DB Rust rewrite (formerly Limbo) v0.6.x, NOT production-ready; BEGIN CONCURRENT/MVCC. **MEDIUM-HIGH.**
- https://docs.sqlalchemy.org/en/20/core/type_basics.html + SQLAlchemy community threads + https://www.pythontutorials.net/blog/how-should-i-handle-decimal-in-sqlalchemy-sqlite/ — SQLite has no lossless DECIMAL; `Numeric(asdecimal=True)` emits `SAWarning` + float-converts on `sqlite+pysqlite`; TypeDecorator (TEXT/scaled-int) workaround. **HIGH** (load-bearing money-policy correction).
- https://arrow.apache.org/docs/python/generated/pyarrow.decimal128.html + pandas issues #61464/#39334 + Anaconda decimals article — pyarrow object-Decimal ⇄ Parquet decimal128 round-trip lossless in value (returns object dtype), decimal write ~4× slower, explicit schema needed for deterministic precision/scale. **HIGH.**
- Existing code: `itrader/price_handler/store/sql_store.py` (FL-06 targets: hardcoded creds L17, f-string `DROP TABLE` L35, symbol-as-table-name L56/L69), `itrader/config/settings.py` (`database_url: SecretStr` already present, M2-06). **HIGH.**

---
*Stack research for: v1.6 Persistence Foundation (swappable SQL spine + all-SQL results store + live operational store + cache classification)*
*Researched: 2026-06-27*
