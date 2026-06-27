# Project Research Summary

**Project:** iTrader v1.6 — N+3b Persistence Foundation
**Domain:** Durable storage + caching substrate for an event-driven backtest/live trading engine (swappable SQL spine, all-SQL results store, three live operational backends, classified cache)
**Researched:** 2026-06-27
**Confidence:** HIGH

---

## Executive Summary

v1.6 adds the durable-storage + caching foundation to an already oracle-locked, `mypy --strict`-clean, Decimal-end-to-end engine. The approach is the NautilusTrader model: cache != store, two independently-controlled retention knobs (write-through x retention), and one shared SQL spine that makes the SQLite / libSQL / Postgres swap a config-not-code change. Three concerns are in scope: (#1) an all-SQL results store for every backtest/optimization run; (#2) concrete SQL backends for the three existing live operational seams (order mirror, portfolio state, strategy/signal); and (#3) a cache inventory + classification that preserves the v1.5 performance wins. The milestone is DB-gated, not oracle-gated: the byte-exact oracle (134 / 46189.87730727451) and the v1.5 frozen baseline (15.7 s / 152.8 MB) prove the persistence layer adds zero hot-path cost when write-through is off, while new DB round-trip / restart-rehydration / cross-backend parity tests cover the genuinely new persistence code.

The single most load-bearing finding of this research is a correction to the design seed. The seed asserts "Turso native DECIMAL preserves the money policy" -- this is false. libSQL is a byte-compatible SQLite fork with the same type system: it has no lossless DECIMAL storage class. Numeric(asdecimal=True) on SQLite/libSQL emits SAWarning: Dialect ... does not support Decimal objects natively, which under this project's filterwarnings=["error"] is a hard test failure. Money on every SQLite-family backend must be stored via a DecimalAsText TypeDecorator in storage/types.py, never Numeric. This single primitive gates every downstream SQL class; it must land first in Phase 1 or the entire test suite goes red the moment a SQLite/libSQL path runs.

Backend decision requires owner confirmation. STACK research finds that Turso/libSQL's perf edge does NOT hold for this project's single-process batch-dump + occasional-read workload. Plain stdlib SQLite is as fast or faster with none of the beta risk (sqlalchemy-libsql 0.2.0 is Beta, last released 2025-05-30, pins a sub-0.1 Rust binding, Linux/macOS only). The recommendation is to make SQLite the proven results-store default and treat libSQL as an optional, config-selected extra -- a safe choice because the two are dialect siblings and the entire libSQL risk is escapable by reverting one engine URL with zero code change. This contradicts the PROJECT.md "Turso (research/optimization default)" language. The owner must decide at requirements time; the research does not silently override that choice.

---

## Key Findings

### Recommended Stack

SQLAlchemy 2.0 Core (already present at ^2.0.50) is the correct single unifier. All three backends are SQLAlchemy dialects (sqlite+pysqlite, sqlite+libsql, postgresql+psycopg2); SqlSettings builds the engine URL and a single create_engine() call selects the backend -- config, not code. Two new libraries must be added to pyproject.toml: pyarrow 24.0.0 for the run_artifacts Parquet-bytes blob, and alembic 1.18.5 for the live Postgres migration chain. sqlalchemy-libsql 0.2.0 is added as an optional Poetry extra (not a hard dep). No other additions. Optuna is explicitly deferred -- the sweep loop is a later milestone; the runs schema is built Optuna-FK-ready from day one (nullable study_id / trial_id / objective_value columns).

**Core technologies:**
- SQLAlchemy 2.0 Core (2.0.51, already present): the shared SQL spine -- Engine + MetaData + Core SQL constructs that swap SQLite/libSQL/Postgres by engine URL alone
- pyarrow 24.0.0 (ADD): Parquet-bytes encoding for the run_artifacts blob column; explicit decimal128(p,s) schema pinned to core/money.py instrument scales -- never inferred
- alembic 1.18.5 (ADD): live Postgres migration chain only; render_as_batch=True for SQLite/libSQL ALTER limits; create_all() for the ephemeral results/backtest DB
- sqlalchemy-libsql 0.2.0 (ADD as optional extra): sqlite+libsql:// dialect for the Turso/libSQL backend slot; beta / stale / Linux+macOS only -- SQLite is the zero-cost escape path (revert one URL)
- DecimalAsText TypeDecorator (NEW, in storage/types.py): the money-fidelity primitive -- stores Decimal as TEXT via str(), loads via Decimal(); applied uniformly on all three dialects; Numeric is acceptable only on the Postgres-only path, but the decorator is preferred everywhere for byte-exact cross-backend parity
- psycopg2-binary 2.9.12, pydantic-settings SecretStr, msgspec (all already present): no version changes needed

**DO NOT ADD this milestone:** optuna (sweep loop deferred); the libsql 0.1.x package directly (the dialect pins libsql-experimental, not libsql).

### Expected Features

Three concerns are in scope; the optimization/sweep loop is explicitly OUT.

**Must have (table stakes):**
- Swappable SQL interface (the spine) -- gates every other feature; backend selected by SqlSettings
- Results store: runs (indexed summary metrics + scalar-promoted sweepable params + JSONB settings archival + Optuna FK columns) and run_artifacts (one Parquet-bytes blob per run, no per-bar row explosion)
- Three concrete SQL operational backends on the shared spine: fill PostgreSQLOrderStorage stub, new SqlPortfolioStateStorage, new SqlSignalStorage
- Two-knob mode-awareness on all three seams: write-through x retention (backtest = off + retain-all; live = on + working-set + purge-on-terminalize)
- Restart rehydration: load only open positions + working orders from the store; rebuild snapshot + running accumulators from the last persisted snapshot row -- not a full-history replay
- Zero hot-path cost when write-through is off (oracle + W1/W2 gate)
- Purge-on-terminalize (event-driven, primary) + age/count sweep (safety net) with bracket-parent safety invariant (never evict a bracket parent while children are open)
- Read-through fallback for evicted terminal records (off hot path -- an open position is always resident)
- Migration / schema-versioning story for the live Postgres store (Alembic); create_all() for the ephemeral results DB
- FL-06 SQL-injection + hardcoded-creds hardening in SqlHandler
- Cache inventory + classification (the deliverable is the map + routing, not a rewrite)

**Should have (competitive / Nautilus-grade design):**
- Cross-backend parity test suite (same suite runs green on SQLite AND Postgres)
- Bracket-aware purge safety formally verified
- runs schema Optuna-FK-ready from day one (nullable FK columns, no future migration needed)
- Vestigial config knobs removed (PerformanceSettings.enable_caching/cache_size_mb -- no consumer)

**Defer (N+4 / v2+):**
- Optimization / parameter-sweep loop (Optuna sampler writing to the substrate)
- Venue reconciliation on restart (cache <-> broker) -- needs a live broker adapter (N+4)
- Async / buffered write-through for append-heavy live writes -- only if profiling justifies it (keep-only-measured)
- Redis cache backend -- only if live engine goes multi-process
- DuckDB cross-run analytical queries over exported frames

**Anti-features (explicitly rejected):**
- Collapsing all three caches into one Arrow-backed object -- three different lifetimes/owners, not one cache
- Per-bar synchronous write-through in backtest -- regresses the v1.5 baseline; backtest backend must contain zero serialization code
- Exploding equity/trade frames into per-bar SQL rows -- 20M-row bloat at large sweeps; one Parquet blob per run
- Reusing Optuna's storage schema as our results warehouse -- float-only schema, couples us to Optuna migration schedule
- Pure age/count eviction without a terminal-state gate -- can evict a still-open position
- Second ID scheme (DB autoincrement PKs) -- violates single-UUIDv7 locked decision
- Arrow/pyarrow on the per-tick hot path -- adds array<->scalar overhead every tick, risks Decimal drift against the oracle

### Architecture Approach

The spine is SqlBackend (a new itrader/storage/ package), shared via composition -- not inheritance -- across four concrete Sql<Concern>Storage classes. The three existing domain ABCs (OrderStorage, PortfolioStateStorage, SignalStore) are unchanged; a fourth ResultsStore ABC is added for concern #1. Each SQL class composes SqlBackend (Engine + MetaData + DecimalAsText + JSON-variant + UUIDv7 type + Core SQL constructs) and implements its own Table definitions. SqlSettings (new, config/sql.py, 4-space) carries the driver/URL, write-through toggle, and retention knobs; factories read it and return the matching backend class. This is backend-selection at wiring -- the backtest backend contains no serialization code at all, making zero hot-path cost a structural guarantee, not a discipline.

The live working-set cache (Q9/Q10) is a separate construct composing an in-memory working set + SqlBackend; it is only built on the live path. The existing InMemoryOrderStorage IS the correct backtest retain-all store; it does not change. The results/ package is its own top-level concern (write-once analytical store with no event-loop caller) separate from the handler storage/ packages.

**Major components:**
1. itrader/storage/ (NEW) -- backend.py (SqlBackend), types.py (DecimalAsText, UUIDv7 type, JSON-variant helper), migrations/ (Alembic chain, live Postgres only)
2. config/sql.py (NEW, 4-space) -- SqlSettings(driver, url, write_through, retention knobs); consumes Settings.database_url: SecretStr (FL-06)
3. Sql{Order,PortfolioState,Signal}Storage (NEW x3) -- one per concern, each composing SqlBackend, each beside its in-memory sibling in the domain's storage/ package
4. itrader/results/ (NEW) -- base.py (ResultsStore ABC), sql_storage.py (runs + run_artifacts), frame_codec.py (pyarrow Parquet-bytes encode/decode with explicit decimal128 schema)
5. Live working-set cache (NEW) -- working-set in-memory layer + write-through + purge-on-terminalize + read-through; only on the live factory arm
6. price_handler/store/sql_store.py (REWORK) -- FL-06: creds from SecretStr, Core constructs replace f-string DDL, symbol-as-table-name eliminated

### Critical Pitfalls

1. **Decimal money silently round-tripped through float on SQLite/libSQL (Numeric column)** -- the #1 landmine; Numeric(asdecimal=True) on SQLite/libSQL emits SAWarning (= hard test failure under filterwarnings=["error"]) and coerces money through a float. Prevention: DecimalAsText TypeDecorator in storage/types.py, applied uniformly. Address in Stage 1 before any downstream SQL class exists.

2. **pyarrow infers decimal128 precision/scale -> non-deterministic blob bytes** -- two runs with the same frame values can produce different blob bytes if pyarrow infers different precision/scale. Prevention: explicit pa.schema(...) with decimal128(p,s) matching core/money.py instrument scales in frame_codec.py. Verify: encode same frame twice -> identical bytes.

3. **A serialize/write call lands on the per-tick hot path** -- a write_through flag checked inside add_order/update_order (even when False) puts serialization code on the byte-exact backtest loop, risking W1/W2 regression. Prevention: backend-selection at wiring (two classes, not one flagged class); the backtest backend must import no SQLAlchemy/serialization symbol. Verify: oracle byte-exact + W1/W2 within v1.5 +-5% gate.

4. **Cross-backend divergence (SQLite-only tests)** -- code that uses JSON-path filtering (settings->>'x'), bare JSONB DDL, or raw f-string SQL passes on SQLite and breaks on Postgres (or vice versa). Prevention: SQLAlchemy Core constructs + portable types + scalar-promoted filter params; run the persistence suite against both backends.

5. **libSQL beta-driver gotchas** -- sqlalchemy-libsql 0.2.0 is Beta, stale (2025-05-30), pins a sub-0.1 Rust binding, Linux+macOS only. Making it a hard core dep breaks CI on Windows and locks the project to a stale driver. Prevention: optional Poetry extra; SQLite is the proven default; the escape path is reverting one engine URL with zero code change.

6. **Live retention bugs (evict-then-need, unbounded growth, over-loaded rehydration, bracket-parent eviction)** -- four ways the two-knob model is mis-implemented. Prevention: purge-on-terminalize (primary) + age/count sweep (safety net) + bracket-parent safety invariant; read-through fallback; rehydrate open working set only (not full terminal history). Verify: evict-then-read-through test; flat-RSS long-run test; open-only rehydration test.

7. **Write-through durability ordering** -- cache mutated and event emitted before the write commits; restart rehydrates stale state. Prevention: synchronous write-through inside a transaction for create/terminalize -- store commits before the engine acknowledges the state change. Defer async batching to append-only writes only if profiling justifies it.

---

## Implications for Roadmap

The ARCHITECTURE build-order constraint is absolute: the spine before any backend; the results store validates the spine before any live path touches it; the retention model is specified before live write-through is wired. The five-phase structure below is the direct read-out of that ordering constraint cross-referenced with the PITFALLS prevention-stage mapping.

### Phase 1: SQL Spine + FL-06

**Rationale:** The hard dependency root. Nothing else compiles without the DecimalAsText TypeDecorator, UUIDv7 column type, JSON-variant helper, SqlBackend, and SqlSettings. FL-06 reworks the only existing SQL file (SqlHandler) onto the spine -- it costs almost nothing to bundle here and eliminates an injection vector before any new SQL code lands. Alembic skeleton also goes here (scoped to live Postgres only; render_as_batch=True; results DB is create_all()).

**Delivers:**
- itrader/storage/types.py -- DecimalAsText TypeDecorator (the money-fidelity primitive), UUIDv7 column type (TEXT canonical, uniform across dialects), JSON().with_variant(JSONB,'postgresql') helper
- itrader/storage/backend.py -- SqlBackend (Engine + MetaData + Core SQL; no business logic)
- itrader/config/sql.py -- SqlSettings (driver enum, URL builder, write_through bool, retention knobs; consumes Settings.database_url: SecretStr)
- itrader/storage/migrations/ -- Alembic env.py skeleton with render_as_batch=True; empty versions/
- price_handler/store/sql_store.py -- FL-06 rework: creds from database_url.get_secret_value(), parameterized Core constructs replacing f-string DDL, symbol-as-column pattern

**Features addressed:** Swappable SQL interface (spine), FL-06 hardening, migration story skeleton
**Pitfalls prevented:** 1 (DecimalAsText), 4 (portable types), 5 (libSQL as optional extra), 6 (Alembic batch mode), 9 (filterwarnings gate), 10 (UUIDv7/JSON determinism), 11 (UUIDv7 uniform type), 13 (FL-06 injection/creds)

**Verification:** Decimal round-trip test on SQLite asserts isinstance(value, Decimal) and exact value under filterwarnings=["error"], no SAWarning; libSQL optional extra in pyproject.toml; no hardcoded user:pass@ in any source file.

**Research flag:** STANDARD patterns (SQLAlchemy Core TypeDecorator, Alembic batch mode, UUIDv7-as-TEXT). Plan-time research is optional; this phase is primarily implementation of well-documented primitives.

---

### Phase 2: Results Store (#1)

**Rationale:** The simplest consumer of the spine; validates it end-to-end on an ephemeral SQLite DB before any live path touches it (oracle-dark -- no hot-loop risk). The results store is write-once-read-later, has no retention model complexity, and exercises DecimalAsText + the Parquet-blob format + Q3 scalar-promotion in isolation. A cross-backend parity test here proves the spine is actually portable before the three operational backends depend on it.

**Delivers:**
- itrader/results/base.py -- ResultsStore ABC (add_run, add_artifact, query methods)
- itrader/results/frame_codec.py -- pyarrow Parquet-bytes encode/decode with EXPLICIT decimal128(p,s) schema matched to core/money.py instrument scales; never inferred
- itrader/results/sql_storage.py -- SqlResultsStore: runs table (run_id UUIDv7, strategy, scalar-promoted indexed params, summary metrics, settings JSON archival column, Optuna FK columns study_id/trial_id/objective_value, kind discriminator) + run_artifacts table (run_id FK, Parquet-bytes BLOB)
- End-of-run batch dump wired in backtest_trading_system.py (post-loop, single transaction, optional, alongside the existing run-end EXPIRE sweep)

**Features addressed:** Results store (every run persisted), Optuna-FK-ready schema, frame-blob format, scalar-promoted filter params (Q3)
**Stack used:** pyarrow 24.0.0 (first use), alembic create_all() for ephemeral DB
**Pitfalls prevented:** 2 (explicit pyarrow schema), 10 (no datetime.now in storage; sort_keys; explicit schema = deterministic bytes)

**Verification:** Encode the same frame twice -> identical bytes; decode -> identical Decimal objects; a runs row filtered by promoted scalar column returns identically on SQLite AND Postgres (cross-backend parity test); results DB has no alembic_version table.

**Research flag:** STANDARD -- pyarrow Parquet-bytes with explicit schema is well-documented. Cross-backend parity test setup is the only novel element; plan-time research not needed.

---

### Phase 3: Operational SQL Backends (#2 -- store layer)

**Rationale:** The spine and results store are now proven. Each of the three existing seams gets one SQL implementation on the shared spine. The v1.5 secondary indexes (_active_by_portfolio, _by_status, _last_indexed_status) translate directly to SQL WHERE + indexes -- the OrderStorage ABC docstring already audited this. The no-serialization-in-backtest-backend rule is enforced structurally here: each new SQL class lives in the factory's 'live'/'sql' arm only; the backtest arm continues to return the existing in-memory class unchanged.

**Delivers:**
- order_handler/storage/sql_storage.py -- SqlOrderStorage implementing OrderStorage; fills the PostgreSQLOrderStorage NotImplementedError stub; v1.5 index queries become WHERE status IN (...) + WHERE portfolio_id=?
- portfolio_handler/storage/sql_storage.py -- SqlPortfolioStateStorage implementing PortfolioStateStorage; ~20 methods; every money column is DecimalAsText (reservations, locked margin, cash operations, metrics)
- strategy_handler/storage/sql_storage.py -- SqlSignalStorage implementing SignalStore; append-heavy; DecimalAsText for stop/take/qty/entry; JSON-variant for the config dict
- Factory extensions: OrderStorageFactory, PortfolioStateStorageFactory, SignalStorageFactory each gain a 'live'/'sql' arm returning the SQL class; 'backtest' arm unchanged

**Features addressed:** Three live operational SQL backends, zero hot-path cost (backtest backend unchanged, no serialization code path)
**Pitfalls prevented:** 3 (no serialize in backtest backend), 12 (tab/space indentation -- handler storage files match their tab-indented in-memory siblings)

**Verification:** Oracle byte-exact (134 / 46189.87730727451); W1/W2 within v1.5 +-5% gate against the frozen 15.7 s / 152.8 MB baseline; static check that in_memory_storage.py imports no SQLAlchemy symbol; cross-backend suite green on SQLite + Postgres.

**Research flag:** MODERATE -- the portfolio-state schema has the largest surface area (~20 methods, four manager domains, all Decimal). A plan-time schema design step for the portfolio_handler tables is warranted. Order and signal backends follow established patterns.

---

### Phase 4: Retention Model + Live Write-Through (#2 -- live path)

**Rationale:** The retention model MUST be fully specified before write-through is wired -- you cannot design purge-on-terminalize, read-through, or restart rehydration until "what stays vs evicts" is locked. This phase is the most architecturally novel work of the milestone and the one with the most unvalidated surface (the live path is not running in production yet). Scope write-through wiring and rehydration here; venue reconciliation (cache <-> broker) remains N+4.

**Delivers:**
- Two-knob retention model fully specified and wired: write-through x retention independently controlled; backtest stays in-memory retain-all (cost provably zero); live uses working-set cache + write-through + purge-on-terminalize
- Live working-set cache composing in-memory working set + SqlBackend: add_order() -> cache + write-through INSERT; terminalize() -> store upsert + cache evict (purge-on-terminalize); query miss -> read-through SELECT
- Bracket-parent safety invariant: never evict a bracket parent while any child order is non-terminal
- Age/count sweep safety net (periodic interval catching missed terminalize events)
- Read-through fallback for cold/terminal records (off hot path)
- Restart rehydration: get_active_orders() + get_positions(WHERE closed_at IS NULL) -> rebuild working orders, open positions, account snapshot, running accumulators from last persisted snapshot row

**Features addressed:** Two-knob mode-awareness, purge-on-terminalize, read-through, restart rehydration, bracket-aware purge safety
**Pitfalls prevented:** 7 (live retention bugs), 8 (write-through durability ordering)

**Scope note:** Synchronous write-through is the starting implementation. Async batching for append-heavy writes is deferred to N+4 unless profiling against the live loop reveals a measured stall (keep-only-measured discipline). The live path is wired and integration-tested here but not exercised in production until N+4.

**Verification:** Evict-then-read-through test (purge a terminal order, assert it reads through from the store); flat-RSS long-run test (RSS stable as terminal count grows); open-only rehydration test (restart loads only open working set, not terminal history); bracket-parent-resident test; crash-after-emit / restart test (rehydrated working set equals pre-crash state).

**Research flag:** NEEDS DEEPER RESEARCH at plan time. The live retention design has non-trivial complexity: bracket-parent safety + read-through + crash-safe write ordering + rehydration scope are all novel for this codebase. A plan-time research phase (/gsd:plan-phase --research-phase) is recommended to nail down the specific transaction boundary design and the rehydration query surface before implementation starts.

---

### Phase 5: Cache Classification (#3)

**Rationale:** Largely independent of the SQL stores and can run in parallel with Phases 2-3. It converges with the storage work only where concern #3(b) -- order/position state lookups -- turns out to be already solved by the v1.5 secondary indexes (those route to the SQL storage interface, not a new Python cache). The Q8 cache inventory (14 sites, all classified in ARCHITECTURE.md) establishes that there is essentially no cache-consolidation code to write -- the deliverable is the classification + the routing, not a rewrite.

**Delivers:**
- Authoritative cache classification map (14 sites inventoried; each tagged (a) hot-path data cache, (b) already solved by v1.5 storage indexes, or (c) correct pure-function memoization)
- Routing decisions documented: class (a) and (c) explicitly LEFT ALONE; class (b) routes to the SQL storage interface's WHERE clauses/indexes in Phase 3 -- no new Python cache
- "Do NOT unify into one Arrow-backed object" decision recorded and cross-referenced to FEATURES anti-features
- Optional cleanup: remove two vestigial config knobs (PerformanceSettings.enable_caching/cache_size_mb) that have no consumer
- One genuinely new cache documented: the live working-set cache (Q9/Q10) -- a separate construct built in Phase 4, not a unification of the above

**Features addressed:** Cache classification deliverable, preserving v1.5 perf wins (no Arrow on the hot path)
**Pitfalls prevented:** Confirms no Arrow/serialize call on the per-tick path (closes Pitfall 3 as a structural fact)

**Verification:** Written classification map committed (the primary deliverable); grepping itrader/ for lru_cache/functools.cache/ad-hoc _cache fields matches the inventory exactly; ARCHITECTURE Q7/Q8 resolutions referenced.

**Research flag:** STANDARD -- the Q8 classification is already complete in ARCHITECTURE.md. Plan-time research is not needed; this phase is recording + routing decisions.

---

### Phase Ordering Rationale

The ordering is dictated by three hard constraints from the research:

1. Spine before every backend (absolute). DecimalAsText, UUIDv7 type, and SqlBackend must exist before any SQL class can be written. The filterwarnings=["error"] gate turns the absence of DecimalAsText into an immediate test failure the moment any SQLite path runs.

2. Results store validates the spine before live paths touch it. The results store is oracle-dark (no per-tick code) and exercises the spine on an ephemeral SQLite DB. It is the lowest-risk integration test for the spine before the three operational backends depend on it.

3. Retention model designed before write-through is wired. The two-knob model (what stays vs evicts; purge-on-terminalize; read-through; rehydration scope) must be fully specified as a design before any write-through code is written. Writing live write-through against an unspecified retention model produces Pitfall 7.

The cache classification (Phase 5) is independent and can shift earlier (alongside Phase 2 or 3) if it helps resolve open questions. The ordering above is conservative because the Q8 inventory is already complete.

### Recurring Verifications (apply at every phase gate)

**(a) Backtest oracle + perf:** Oracle byte-exact (134 / 46189.87730727451); W1 / W2 within v1.5 +-5% gate vs frozen 15.7 s / 152.8 MB baseline.
**(b) Cross-backend parity:** Persistence test suite runs green on sqlite+pysqlite:// AND postgresql+psycopg2://.
**(c) DB-specific domain tests:** money round-trip (Decimal type + exact value under filterwarnings=["error"]); determinism double-run byte-identical including persisted artifacts; no datetime.now/time.time in storage modules.

### Research Flags Summary

Needs deeper plan-time research:
- Phase 4 (Retention Model + Live Write-Through): novel for this codebase; bracket-parent safety + crash-safe write ordering + rehydration query scope need design-before-implementation. Recommend /gsd:plan-phase --research-phase.

Standard patterns (plan-time research optional):
- Phase 1 (SQL Spine): SQLAlchemy Core TypeDecorator + Alembic batch mode are well-documented; implementation is mostly mechanical.
- Phase 2 (Results Store): pyarrow Parquet-bytes with explicit schema is documented; cross-backend parity test setup is the only novel element.
- Phase 3 (Operational Backends): the v1.5 index queries map directly to SQL WHERE clauses; the schema surface is the main design task for portfolio-state.
- Phase 5 (Cache Classification): Q8 classification is already done; this is a documentation + routing-decision phase.

---

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Versions verified via PyPI JSON API; SQLAlchemy/SQLite/Postgres mechanics from official docs; Decimal correction from SQLAlchemy source + SQLite type-affinity spec; pyarrow decimal128 from official Arrow Python docs. The only shaky point is the libSQL beta driver -- but its risk is fully mitigated by the optional-extra design. |
| Features | HIGH | Reference-framework survey against current docs (NautilusTrader, LEAN, Optuna) with source links. Feature landscape grounded in the converged seed + Q6/Q10 resolutions. Anti-features are explicit and justified. |
| Architecture | HIGH | Grounded in code: the three existing ABCs and factory pattern read from the actual tree; the v1.5 secondary indexes read from in_memory_storage.py; the Q8 cache inventory grepped and classified against real source paths. MEDIUM-HIGH on the live write-through design (live path is unbuilt -- design is sound but unvalidated against a running live loop). |
| Pitfalls | HIGH | Critical pitfalls 1 and 3 are grounded in code (FL-06 creds/injection paths verified at sql_store.py L17/L35/L56/L69; filterwarnings=["error"] verified in pyproject.toml). Pitfall 2 grounded in pyarrow precision-inference behavior in official Arrow docs. Moderate pitfalls 7/8 are Nautilus-precedented but unvalidated against live execution. |

**Overall confidence: HIGH**

### Gaps to Address

- Backend default decision (owner-required): The "Turso (research/optimization default)" language in PROJECT.md conflicts with the STACK research recommendation (SQLite as proven default, libSQL as opt-in extra). The owner must decide at requirements time before SqlSettings.driver default is specified.

- Portfolio-state schema design (plan time): The PortfolioStateStorage ABC has ~20 methods covering cash/position/transaction/metrics -- all Decimal. The exact table shape (which snapshot rows to persist, which columns to index, what the snapshot cadence is) needs a plan-time design step in Phase 3.

- Live write-through transaction boundary (plan time): Which operations are create/terminalize (synchronous, must commit before the engine acknowledges) vs append-heavy (could be batched)? This is the core Phase 4 design question that warrants a plan-time research step.

- Working-set cache threading model (plan time): The live system runs on a single daemon thread (LiveTradingSystem). The synchronous write-through assumption must be confirmed against the actual threading model -- specifically, whether any storage call can be triggered from a second thread (e.g., TradingInterface injecting orders from the API thread).

- libSQL embedded-replica consistency semantics (if opted in): Embedded-replica mode has only beta Python support and different consistency semantics (a write may not be visible immediately after commit). If the owner elects libSQL as the results-store default, this needs validation before Phase 2 uses it as the primary test backend.

---

## Sources

### Primary (HIGH confidence)
- PyPI JSON API -- verified current versions for SQLAlchemy 2.0.51, pyarrow 24.0.0, alembic 1.18.5, optuna 4.9.0, sqlalchemy-libsql 0.2.0 (Beta, 2025-05-30), libsql-experimental 0.0.55 (sub-0.1), libsql 0.1.11
- https://docs.turso.tech/sdk/python/orm/sqlalchemy -- sqlite+libsql:// scheme, embedded-replica/remote modes
- https://docs.sqlalchemy.org/en/20/core/type_basics.html -- SQLite has no lossless DECIMAL; TypeDecorator (TEXT/scaled-int) workaround
- https://arrow.apache.org/docs/python/generated/pyarrow.decimal128.html -- pyarrow decimal128 round-trip; explicit schema required for deterministic precision/scale
- https://nautilustrader.io/docs/latest/concepts/cache/ + /concepts/live/ + /api_reference/config/ -- NautilusTrader Cache: purge APIs, bracket-parent safety, restart rehydration, purge scheduling params
- https://optuna.readthedocs.io/en/stable/reference/generated/optuna.storages.RDBStorage.html + github.com/optuna/optuna/blob/master/optuna/storages/_rdb/models.py -- Optuna RDB schema (float-only), ask-and-tell interface
- https://www.quantconnect.com/docs/v2/writing-algorithms/object-store -- LEAN ObjectStore (key-value blob persistence)
- itrader/price_handler/store/sql_store.py (read) -- FL-06 targets confirmed at L17/L35/L56/L58/L69
- itrader/config/settings.py -- database_url: SecretStr already present (M2-06)

### Secondary (MEDIUM-HIGH confidence)
- https://github.com/tursodatabase/sqlalchemy-libsql -- Beta status, Linux/macOS-only, pins libsql-experimental
- https://github.com/tursodatabase/libsql -- libSQL = backwards-compatible SQLite fork, same type system, no native DECIMAL
- https://github.com/tursodatabase/turso -- Turso DB Rust rewrite (formerly Limbo, v0.6.x, NOT production-ready)
- https://github.com/nautechsystems/nautilus_trader/issues/3176 -- real-world restart/duplicate-order reconciliation behavior

### Tertiary (project, AUTHORITATIVE for this codebase)
- .planning/notes/persistence-milestone-design.md -- converged design seed (the FALSE "Turso native DECIMAL" claim identified and corrected here)
- .planning/research/questions.md -- Q1-Q10 open questions, all resolved in the four research files
- CLAUDE.md -- filterwarnings=["error"] strictness gate, Decimal-end-to-end + determinism + single-UUIDv7 locked decisions, tab/space indentation hazard, v1.5 frozen baseline 15.7 s / 152.8 MB, oracle 134 / 46189.87730727451

---
*Research completed: 2026-06-27*
*Ready for roadmap: yes*
