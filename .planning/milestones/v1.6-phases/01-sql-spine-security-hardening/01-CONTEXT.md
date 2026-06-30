# Phase 1: SQL Spine + Security Hardening - Context

**Gathered:** 2026-06-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the **SQL spine** — the hard dependency root nothing else in v1.6 compiles without.
Delivers a single config-selected `SqlBackend` + `SqlSettings` (SQLite research store + Postgres
operational store, interface shaped Turso-ready but the `sqlalchemy-libsql` driver NOT added),
**composed** (never inherited) by every storage concern; lossless, value-equal UUIDv7-id and
business-time round-trip across both dialects (SPINE-03); FL-06 security hardening of `SqlHandler`;
and an Alembic migration skeleton (live Postgres only) alongside `create_all()` for the ephemeral
research store.

**Requirements (from REQUIREMENTS.md):** SPINE-01, SPINE-02, SPINE-03, SEC-01, MIG-01, GATE-02
(GATE-02 *bound* here = the test harness/substrate is established this phase; GATE-01 *recurs*).

**In scope:** `itrader/storage/` spine package; `config/sql.py` `SqlSettings`; cross-dialect type
helpers; Alembic skeleton; FL-06 rework of `sql_store.py`; the SQLite + testcontainers-Postgres test
harness.

**Out of scope (other phases / locked OUT):** the `ResultsStore` *implementation* (Phase 2 — only the
new ABC seam, if any, is touched here); the three operational SQL backends (Phase 3); write-through +
retention + working-set cache + rehydration (Phase 4); cache classification (Phase 5); the
optimization/Optuna sweep loop (v2 OUT); `pyarrow`/Parquet (locked OUT); `DecimalAsText` (locked OUT);
the `sqlalchemy-libsql` driver (deferred — interface stays Turso-ready).

</domain>

<decisions>
## Implementation Decisions

### Spine package layout
- **D-01:** The spine lives in a **NEW top-level `itrader/storage/` package** — `backend.py`
  (`SqlBackend` = Engine + MetaData + Core SQL constructs, no business logic), `types.py`
  (cross-dialect type helpers), `migrations/` (Alembic, live Postgres only). It is a neutral home
  that all storage concerns *compose*, independent of any one domain (analogous to `core/`).
  NOT under `core/` (would pull SQLAlchemy into the no-internal-deps purity rule) and NOT nested in
  `price_handler/store/` (price-data-specific, tab-indented, single-consumer coupling).
- **D-02:** `SqlSettings` lives in **`config/sql.py`** (Pydantic, consumes `Settings.database_url:
  SecretStr`). New package + new config module → **4-space indentation** (matches `config/`, `core/`).

### ID + business-time encoding (SPINE-03)
- **D-03:** Ids use **SQLAlchemy 2.0's `sqlalchemy.Uuid(as_uuid=True)`** column type — one declaration
  that maps to Postgres-native `uuid` and SQLite `CHAR(32)` automatically; Python contract is uniform
  `uuid.UUID` on both backends. The SPINE-03 cross-backend round-trip test asserts **Python-value
  equality** (`uuid.UUID == uuid.UUID`), which this satisfies even though on-disk representations
  differ across dialects. Least custom code; keeps PG-native indexing. Single UUIDv7 scheme preserved
  (no second ID scheme, no DB autoincrement).
- **D-04:** Business-time timestamps are stored **uniformly as ISO-8601 UTC text** (or int64 epoch —
  planner's call) on **both** dialects — NOT a native `timestamp`/`timestamptz` column. Rationale:
  Postgres `timestamp` is microsecond-precision and would silently **truncate** if business-time ever
  carries nanosecond pandas `Timestamp` precision → not lossless. A uniform text/int64 encoding dodges
  that and guarantees the lossless+equal requirement on both backends. No wall-clock writes
  (business `time` only).
- **D-05 (plan-time check):** Confirm the actual precision of the engine's business-time
  (golden data is **daily** bars, so microsecond is almost certainly sufficient) and pin the chosen
  text/int64 format so two runs encode identical bytes (determinism: explicit format, UTC, stable).

### FL-06 security hardening (`sql_store.py` / `SqlHandler`)
- **D-06:** **Full migration** of `SqlHandler` onto the new `SqlBackend` spine (chosen over minimal
  in-place hardening) — one SQL stack, eliminates the injection vector, and matches the research's
  stated FL-06 framing. NOTE: `SqlHandler` is a price-data store, NOT one of the four composing
  *domain* storage ABCs — it composes the spine as an additional (5th) consumer.
- **D-07:** Resolve the symbol-as-table-name vuln (L56/58/69) by **collapsing table-per-symbol into a
  single `prices` table with a `symbol` VALUE column** — dynamic identifiers/DDL are eliminated
  entirely; everything becomes parameterized values (`... WHERE symbol = :symbol`). This is a
  schema change: any external reader of the old per-symbol tables needs a **one-time re-ingest**
  (plan-time concern — researcher/planner should check for external consumers).
- **D-08:** Credentials sourced from `Settings.database_url.get_secret_value()` (kills hardcoded creds
  L17); f-string `DROP TABLE` (L35) replaced by SQLAlchemy Core / parameterized constructs.
  Acceptance grep gates: no `user:pass@` in any source file; no f-string inside `text()`.
- **D-09 (plan-time note):** Reworking `SqlHandler` onto the spine likely lifts it out of its current
  `D-sql` mypy deferral. GATE-02 requires the new spine code to be `mypy --strict` clean — planner
  decides whether/how the reworked `sql_store.py` enters strict scope.

### Test substrate (GATE-02 bound here)
- **D-10:** Add the **`testcontainers`** dev-dependency and stand up an **ephemeral Postgres
  container** (session-scoped fixture) in Phase 1 — SPINE-03 needs the round-trip proven on Postgres,
  not just SQLite, and Phase 3 reuses this harness. The spine's own round-trip uses **in-process
  SQLite**; cross-backend parity runs on SQLite **and** testcontainers Postgres.
- **D-11:** PG-backed tests **skip/xfail gracefully when Docker is absent** (no CI exists yet, so this
  is a local Docker dependency — must not hard-fail a Dockerless `make test`/`poetry run pytest`).

### Smaller decisions (captured as defaults — not separately discussed)
- **D-12:** `SqlSettings` surface is **minimal now** — driver enum (with a libsql slot, Turso-ready) +
  engine-URL builder consuming `Settings.database_url`. The write-through / retention knobs are
  **deferred to Phase 4** where they are consumed (avoids forward-declaring unused config).
- **D-13:** **`DecimalAsText` is OMITTED** (Owner Decision) — money never lands on a SQLite-family
  backend (results store = all-`Float`; operational money = Postgres-native `Numeric` in Phase 3).
  `types.py` carries the `Uuid` handling + a `JSON().with_variant(JSONB, "postgresql")` helper, **not**
  a money TypeDecorator. ⚠️ This **overrides** the research, which insists DecimalAsText "must land in
  Phase 1" — see the conflict note in Canonical References.
- **D-14:** Alembic skeleton = `env.py` with `render_as_batch=True` + an **empty `versions/`**
  (no operational tables exist until Phase 3); the research/results DB uses `create_all()` (no
  `alembic_version` table). One migration chain, live Postgres only (MIG-01).
- **D-15:** Interface kept **Turso-ready** (driver enum includes a libsql slot) but
  `sqlalchemy-libsql` is **NOT added** to dependencies this milestone (Owner Decision; the escape path
  is one engine-URL change with zero code change).

### Recurring gates (every phase, restated here)
- **D-16:** GATE-01 (recurs): SMA_MACD oracle byte-exact **134 / `46189.87730727451`**, no W1/W2
  regression vs the v1.5 frozen baseline (**15.7 s / 152.8 MB**) — the spine is inert on the hot path
  (Phase 1 adds no per-tick code at all). GATE-02 (bound here): new spine code `mypy --strict` clean,
  full suite green under `filterwarnings=["error"]` with no new broad ignore.

### Claude's Discretion
- Exact `types.py` helper shapes; ISO-8601-text vs int64-epoch for business-time (D-04, pick at plan
  time after the D-05 precision check); the precise `prices`-table schema/index shape (D-07);
  Alembic `env.py` boilerplate.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### ⚠️ Precedence conflict (read FIRST)
- `.planning/PROJECT.md` → "Owner Decisions (research-time, supersede the seed)" and "Current
  Milestone" — the **authoritative locked scope**. Where it differs from the research docs below,
  **the Owner Decisions win.** Specifically the research's `DecimalAsText` ("must land in Phase 1")
  and `pyarrow`/Parquet guidance is **SUPERSEDED** (results store = all-`Float`, no pyarrow; no
  DecimalAsText — money never touches SQLite).

### Requirements & scope
- `.planning/REQUIREMENTS.md` — SPINE-01/02/03, SEC-01, MIG-01, GATE-01/02 (full requirement text +
  the Out-of-Scope table).
- `.planning/ROADMAP.md` → "Phase 1: SQL Spine + Security Hardening" — the five Success Criteria.
- `.planning/STATE.md` → "Milestone Gate (v1.6 — DB-gated)" — the two-part gate restated.

### Research (HIGH-confidence, but PREDATE the Owner Decisions — apply with the precedence note above)
- `.planning/research/SUMMARY.md` §"Phase 1: SQL Spine + FL-06" — build-order rationale, deliverables,
  pitfalls-prevented mapping. (Ignore its DecimalAsText/pyarrow emphasis per D-13.)
- `.planning/research/ARCHITECTURE.md` — composition-not-inheritance spine design; the three existing
  ABCs + new `ResultsStore` ABC; `SqlSettings` shape.
- `.planning/research/PITFALLS.md` — Pitfall 4 (cross-backend divergence — Core constructs + portable
  types), 5 (libSQL beta → optional extra), 6 (Alembic `render_as_batch=True`), 10/11 (UUIDv7/JSON
  determinism + uniform id type), 13 (FL-06 injection/creds). Pitfall 1 (DecimalAsText) is moot for
  Phase 1 per D-13.
- `.planning/research/STACK.md` — SQLAlchemy 2.0 Core as the unifier; version pins; the SQLite-no-native-
  DECIMAL finding (context for *why* money stays off SQLite).
- `.planning/notes/persistence-milestone-design.md` — the converged design seed (historical; the
  "Turso native DECIMAL" claim in it is RETRACTED as false — do not act on it).

### FL-06 target & config (read the code)
- `itrader/price_handler/store/sql_store.py` — the FL-06 rework target. Vulns: hardcoded creds **L17**,
  f-string `DROP TABLE` **L35**, symbol-as-table-name **L56/L58/L69**. Currently tab-indented;
  mypy-deferred (`D-sql`, `pyproject.toml`).
- `itrader/config/settings.py` — `Settings(BaseSettings)`, `env_prefix="ITRADER_"`,
  `database_url: SecretStr` (required, no default), **L39**. Note: `live_trading_system.py` L34 reads a
  *different* env var (`SYSTEM_DB_URL`) — an inconsistency the spine wiring should reconcile.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable assets
- **Three existing domain storage ABCs the spine must serve (composition targets):**
  - `OrderStorage` — `itrader/order_handler/base.py` (~15 abstract methods). In-memory:
    `order_handler/storage/in_memory_storage.py` (flat `{id: Order}` dict + v1.5 derived secondary
    indexes). PG stub raising `NotImplementedError`: `order_handler/storage/postgresql_storage.py:14`.
    Factory: `order_handler/storage/storage_factory.py` (`backtest`/`test` vs `live`). **4-space.**
  - `PortfolioStateStorage` — `itrader/portfolio_handler/base.py` (~21 methods, cash/position/
    transaction/metrics/snapshots). In-memory: `portfolio_handler/storage/in_memory_storage.py`.
    Factory raises `NotImplementedError` ("deferred to D-sql") at `portfolio_handler/storage/
    storage_factory.py:61`. **storage/ = 4-space; `base.py` has a TAB-import / 4-space-class mix.**
  - `SignalStore` — `itrader/strategy_handler/storage/base.py` (4 methods). In-memory:
    `strategy_handler/storage/in_memory_storage.py`. Factory raises `NotImplementedError` at
    `strategy_handler/storage/storage_factory.py:59`. **4-space.**
- **`Settings.database_url: SecretStr`** already exists (`config/settings.py:39`) — the FL-06 cred
  source. No `SqlSettings`/`SqlBackend` type exists yet.

### Established patterns
- **Factory string-arm selection** (`in_memory`/`backtest`/`test` vs `live`/`postgresql`) is the
  established backend-selection idiom — Phase 1 establishes the spine; Phase 3 adds the SQL arm.
- **SQLAlchemy 2.0** already present (`^2.0.50`) + `psycopg2-binary` + `sqlalchemy-utils`. The ONLY
  current live-path SQLAlchemy import is `sql_store.py` (`create_engine`, `inspect`, `text`). No
  declarative Base / Session / engine factory / Alembic exists yet — all green-field.

### Integration points
- New `itrader/storage/` package; new `config/sql.py`; reworked `price_handler/store/sql_store.py`.
- Test harness: `tests/` (in-process SQLite + new testcontainers-Postgres fixture). `pyproject.toml`
  dev-deps gain `testcontainers` + `alembic`.

### Indentation map (DO NOT normalize — match the file)
- `itrader/storage/` (NEW), `config/`, `order_handler/storage/`, `portfolio_handler/storage/`,
  `strategy_handler/storage/` → **4 spaces**.
- `price_handler/store/sql_store.py` → **tabs** (preserve when reworking, or move to the spine's
  4-space package — planner's call given D-06 full migration).

</code_context>

<specifics>
## Specific Ideas

- Owner explicitly preferred the **`sqlalchemy.Uuid` type column** over both a hand-rolled
  native-per-dialect approach and plain TEXT-canonical — values the idiomatic SQLAlchemy 2.0 path with
  the least custom code, accepting that on-disk id representation differs across backends while Python
  values compare equal.
- Owner chose the **more ambitious FL-06 path** (full spine migration + symbol-as-column collapse)
  over minimal in-place hardening — signals a preference for doing the rework properly now rather than
  leaving a second SQL pattern around.

</specifics>

<deferred>
## Deferred Ideas

- **Async / buffered write-through** — N+4 / only if profiling justifies (research "Defer").
- **libSQL/Turso as a real backend** — v2 TURSO-01; interface stays ready, driver not added (D-15).
- **`prices` table migration tooling** for any external readers of old per-symbol tables (D-07) — a
  one-time concern the planner scopes; not new capability.

### Reviewed Todos (not folded)
- **`single-pass-portfolio-valuation.md`** (matched at score 0.6) — a **performance** optimization
  (per-bar portfolio valuation), matched only on generic keywords (phase/gate/regression/byte/exact)
  shared by every v1.6 phase. **Orthogonal to the SQL spine** — belongs to a future perf pass, profile-
  first gated. Reviewed and **NOT folded** into Phase 1.

</deferred>

---

*Phase: 1-SQL Spine + Security Hardening*
*Context gathered: 2026-06-27*
