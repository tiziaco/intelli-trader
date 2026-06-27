# Pitfalls Research

**Domain:** Bolting a swappable SQL persistence layer + a working-set cache onto a Decimal-end-to-end, deterministic, oracle-gated, event-driven backtest/live trading engine (v1.6 — N+3b Persistence Foundation)
**Researched:** 2026-06-27
**Confidence:** HIGH on the money/serialization/hot-path landmines (grounded in STACK's load-bearing Decimal correction + ARCHITECTURE's anti-patterns + v1.5 code); HIGH on retention/rehydration (Nautilus-precedented, FEATURES Q10); MEDIUM-HIGH on the libSQL beta-driver and cross-backend-parity failure modes (the live path is unbuilt, so these are reasoned-from-design not yet observed).

> **Scope discipline.** These are the failure modes *specific to this milestone* — the ways adding SQL + a cache to THIS engine goes wrong. Generic web-security and generic-database mistakes are deliberately excluded. The single most important fact threaded through every pitfall: the design seed's claim *"Turso native DECIMAL preserves the money policy"* is **FALSE** (STACK correction). That one falsehood is the root of the #1 critical pitfall and colors three others.
>
> **Build-order stages referenced** (from ARCHITECTURE "Build-Order Dependencies"): **Stage 1 — The Spine** (`storage/types.py`, `storage/backend.py`, `config/sql.py`, FL-06 `SqlHandler` rework, Alembic skeleton) · **Stage 2 — Results Store** (`runs` + `run_artifacts`, `frame_codec.py`) · **Stage 3 — Three Operational SQL Backends** (order / portfolio-state / signal) · **Stage 4 — Retention Model + Live Write-Through** (working-set cache, purge-on-terminalize, read-through, rehydration). **Cross-cutting:** Cache Classification (#3) and Migrations run alongside.

---

## Critical Pitfalls

### Pitfall 1: Decimal money silently round-tripped through float on SQLite/libSQL (`Numeric` column)

**What goes wrong:**
A money column is declared as SQLAlchemy `Numeric`/`DECIMAL(asdecimal=True)` — the natural choice, and correct on Postgres. On `sqlite+pysqlite` and `sqlite+libsql`, SQLAlchemy emits `SAWarning: Dialect sqlite+pysqlite does *not* support Decimal objects natively, and SQLAlchemy must convert from floating point - rounding errors and other issues may occur.` and coerces the value through a Python float on write. Two failures at once: (a) under this project's `filterwarnings=["error"]` the `SAWarning` is a **hard test failure** — the suite goes red; (b) even if you suppressed the warning, money is now a float round-trip — a **locked-decision violation** of Decimal-end-to-end, the exact correctness defect this whole program exists to prevent. `46189.87730727451` does not survive the trip.

**Why it happens:**
The design seed asserts "Turso native DECIMAL preserves the money policy." It does not. libSQL is a byte-compatible SQLite fork with the *same* type system — NUMERIC affinity, no lossless DECIMAL storage class. Postgres habits (`Numeric` just works) + the seed's false premise lead straight to the trap. It is invisible on a Postgres-only test run and only detonates when the SQLite/libSQL backend is exercised.

**How to avoid:**
A single `DecimalAsText` `TypeDecorator` (store `Decimal` as TEXT via `str()`, load via `Decimal()`) in `storage/types.py`, applied **uniformly to every money column on all three dialects** — not just SQLite. `Numeric` is acceptable only on the Postgres-only live path, but using the decorator everywhere gives byte-exact cross-backend parity and silences the warning structurally. Enter the Decimal domain only via the money-policy seam (never `Decimal(float)`).

**Warning signs:**
`SAWarning` text mentioning "does not support Decimal objects natively" anywhere in test output (it will surface as a test *error*, not a warning); a money value read back as `46189.877307274513` (float artifact) instead of the exact string; `isinstance(value, float)` true after a load; the suite passing on a Postgres dev DB but failing the moment a `:memory:` SQLite test runs.

**Phase to address:** Stage 1 (The Spine — `storage/types.py` is where `DecimalAsText` lives; it gates every downstream SQL class). Verified again at Stage 2 (results store money columns) and Stage 3 (portfolio-state reservations/locked-margin, signal stop/take/qty/entry — every one a `DecimalAsText` column).

---

### Pitfall 2: pyarrow infers `decimal128` precision/scale → non-deterministic frame-blob bytes

**What goes wrong:**
The `run_artifacts` equity-curve / trade-log DataFrame is serialized to Parquet bytes by letting pyarrow *infer* the schema from the object-dtype `Decimal` columns. pyarrow derives `decimal128(precision, scale)` from the data it sees — so two runs whose frames contain different-magnitude Decimals (or the same values formatted differently) produce **different precision/scale, hence different bytes**. The blob is value-correct but byte-unstable, which breaks the determinism discipline (double-run byte-identical) the engine has held since v1.0 — now extended to the persisted artifact.

**Why it happens:**
Inference is the path of least resistance (`pa.Table.from_pandas(df)` "just works"). The drift is silent — values round-trip losslessly, so a naive round-trip test passes; only a *byte-equality* test across two runs catches it.

**How to avoid:**
Pin an **explicit pyarrow schema** in `frame_codec.py` with per-money-column `decimal128(precision, scale)` matched to `core/money.py` instrument scales — never inference. Round-trip is then lossless AND deterministic. (STACK Q5, explicitly flagged.)

**Warning signs:**
Determinism double-run fails only on the artifact bytes (metrics/trade-log identical, blob differs); the encoded byte length varies run-to-run for an identical-values frame; `frame_codec` has no explicit `pa.schema(...)` and calls `from_pandas` with no schema arg.

**Phase to address:** Stage 2 (Results Store — `results/frame_codec.py`). Verification: encode the same frame twice → identical bytes; decode → identical `Decimal` objects; assert the schema is explicit (grep for an explicit `decimal128` per money column).

---

### Pitfall 3: A serialize/write call lands on the per-tick hot path (backtest perf + oracle regression)

**What goes wrong:**
Once SQL backends exist, a `write_through` flag gets checked *inside* `add_order`/`update_order`/`add_transaction` (`if self.write_through: self._serialize(...)`), or the backtest is pointed at a SQL backend "for consistency." Either way the per-tick path now *contains* serialization code. Even with the flag off, the branch and the import sit on the byte-exact hot loop; with it accidentally on, every bar serializes. Result: the v1.5 W1/W2 wins (frozen **15.7 s / 152.8 MB** baseline) regress, and the SMA_MACD oracle (`134 / 46189.87730727451`) is put at risk by any float/format drift in the serialize path.

**Why it happens:**
A single flagged class feels simpler than two backend classes. "Symmetry — persist everything always" is a seductive but wrong instinct (FEATURES lists per-bar synchronous write-through in backtest as an explicit anti-feature). The regression is invisible to a correctness-only test; only the perf gate catches it.

**How to avoid:**
**Backend-selection at wiring, not a runtime flag** (ARCHITECTURE Pattern 2 / Anti-Pattern 3). The backtest backend (`InMemoryOrderStorage` et al.) must contain **no serialization code at all** — no `Table`, no `Session`, no `.serialize`, no SQLAlchemy import on its call path. Write-through is a *different class* the factory returns for `environment='live'`. Cost-when-off is provably zero because the code path does not exist. Backtest persistence is a single end-of-run batch dump (Pattern 3), off the loop.

**Warning signs:**
W1 wall-clock drifts >5% above the frozen 15.7 s baseline; `import sqlalchemy` reachable from the in-memory backend's hot methods; an `if write_through` branch inside any per-tick storage method; the oracle still byte-exact but the run measurably slower (the tell-tale of work added to the loop without changing numbers).

**Phase to address:** Stage 3 (operational backends — enforce the no-serialization-in-backtest-backend rule as the backends land) and Stage 4 (live write-through wiring). Verification: oracle byte-exact (`134 / 46189.87730727451`); W1/W2 within the v1.5 ±5% gate vs the frozen baseline; static check that the backtest backend's module imports no SQL/serialization symbol.

---

### Pitfall 4: Cross-backend divergence — code that passes on SQLite but breaks on Postgres (or vice-versa)

**What goes wrong:**
The "config not code" backend-swap promise quietly fails because the SQL only behaves identically on the *one* backend you tested. Three concrete divergence sources: (1) **JSON filtering** — `WHERE settings->>'lookback' > 20` returns text on PG needing a cast, uses `json_extract(settings,'$.lookback')` with different numeric-vs-text comparison semantics and no index on SQLite/libSQL → *different result rows* per backend; (2) **dialect DDL/ALTER** — a `JSONB` column or an `ALTER TABLE … ADD CONSTRAINT` that works on PG fails on SQLite/libSQL's limited ALTER; (3) **type affinity** — SQLite's loose affinity accepts a wrong-typed write that PG's strict typing rejects. The swap "works" in dev (SQLite) and breaks in prod (Postgres), or the reverse.

**Why it happens:**
Parity is only as good as the parity *tests*, and the cheap default is to develop+test against one backend (usually the zero-setup SQLite). Raw dialect SQL strings (the FL-06 f-string DDL is the archetype) and JSON-path filtering bake in dialect assumptions.

**How to avoid:**
Stay on SQLAlchemy **Core constructs** (`insert().on_conflict_*`, portable types, `JSON().with_variant(JSONB,'postgresql')`) — never raw dialect SQL strings. **Scalar-promote** the handful of filterable/sweepable params (`lookback`, `fast_window`, `slow_window`) into real typed indexed columns on `runs`, keep the full heterogeneous dict in an archival `settings` JSON column **never filtered in cross-sweep queries** (STACK/FEATURES Q3) — this dissolves the JSON-portability problem rather than papering over it. Run the persistence test suite against **at least SQLite + Postgres** (ideally also `sqlite+libsql`), not one backend.

**Warning signs:**
The same `runs` query returns different rows on PG vs SQLite; `alembic upgrade head` or `create_all()` succeeds on one dialect and fails on another; CI only spins up SQLite; any `WHERE settings ->> …` in a hot cross-sweep query; raw f-string/`text()` SQL with a dialect-specific keyword.

**Phase to address:** Stage 1 (the spine's portable-type decisions: `DecimalAsText`, JSON-variant, UUIDv7 type) and Stage 2/3 (parity tests as the backends land). Verification: the identical test module runs green on `sqlite+pysqlite` AND `postgresql+psycopg2`; all `runs` filtering hits promoted scalar columns (grep: no JSON-path operator in a `WHERE`).

---

## Moderate Pitfalls

### Pitfall 5: Treating libSQL/Turso as a drop-in equal (beta-driver gotchas)

**What goes wrong:**
`sqlalchemy-libsql 0.2.0` is made a hard core dependency and treated as interchangeable with SQLite/Postgres. It is **Beta, last released 2025-05-30 (~13 mo stale)**, pins the `libsql-experimental 0.0.55` Rust binding (sub-0.1, explicitly *"not production grade"*, **Linux + macOS only — no Windows wheels**), and does *not* track the newer `libsql 0.1.x`. Embedded-replica mode (local file + `sync_url`/`auth_token`) has only beta Python support and different durability/consistency semantics than a local file or remote-only. Making it core risks: install failures on a Windows CI matrix, a dialect that silently lags if `libsql-experimental` is retired in favor of `libsql`, and embedded-replica sync-lag surprises where a write isn't yet visible after a "successful" commit.

**Why it happens:**
The seed names "Turso (research/optimization default)" first, which reads as "make it the primary backend." STACK's honest Q2 verdict reverses that: the perf premise does **not** hold for our single-process batch-dump + occasional-read pattern — plain stdlib SQLite is as fast or faster, with none of the beta risk. libSQL's value here is *operational* (managed remote DB, shared cross-machine sweeps), not throughput.

**How to avoid:**
Make `sqlalchemy-libsql` an **optional Poetry extra**, keep **SQLite the proven default** for results/backtest. Because SQLite and libSQL are **dialect siblings**, the entire libSQL risk is escapable by reverting one engine URL to `sqlite+pysqlite://` with **zero code change** — bank that escape hatch explicitly. Validate the `libsql-experimental` pin on install; do not target the from-scratch "Turso Database" Rust rewrite (formerly Limbo, not production-ready — a branding trap).

**Warning signs:**
`poetry install` fails on a non-Linux/macOS runner; a libSQL `*Warning` slips into the strict suite; an embedded-replica read returns stale state right after a write; the dependency tree shows `libsql-experimental` as a *required* (not optional-extra) dep.

**Phase to address:** Stage 1 (driver/dependency wiring in `config/sql.py` + `pyproject.toml` extras). Verification: libSQL is in `[tool.poetry.extras]`, not the core dep set; a "revert URL to `sqlite+pysqlite`" smoke proves the swap is code-free; SQLite is the default `SqlSettings` driver.

---

### Pitfall 6: One Alembic chain that diverges between embedded (SQLite/libSQL) and server (Postgres)

**What goes wrong:**
A single autogenerated migration chain emits Postgres-shaped DDL — a `JSONB` column, an `ALTER TABLE … ALTER COLUMN`, an added constraint — that SQLite/libSQL's limited `ALTER TABLE` cannot apply, so `alembic upgrade head` succeeds on Postgres and **fails on SQLite/libSQL** (or silently no-ops). Conversely, gating the *ephemeral backtest/results DB* on migrations adds ceremony to the byte-exact backtest path for a schema you throw away and re-create every run.

**Why it happens:**
Alembic `--autogenerate` reflects against whichever DB you point it at and renders that dialect's DDL; without `render_as_batch=True` it assumes server-grade ALTER. And "migrations everywhere for consistency" over-applies the tool to a disposable DB.

**How to avoid:**
Scope Alembic to the **live Postgres store only**; use `MetaData.create_all()` for the ephemeral results/backtest DB (STACK/ARCHITECTURE Q4). Set `render_as_batch=True` in `env.py` so SQLite/libSQL ALTERs run via move-and-copy. Use portable types in migrations (`JSON().with_variant(JSONB,'postgresql')`) so a column is not PG-only. One chain *can* target all three — but only with those two accommodations.

**Warning signs:**
`alembic upgrade head` errors on a SQLite ALTER; a migration script contains a bare `JSONB` or a server-only DDL keyword; the backtest path imports Alembic; the results DB has a `alembic_version` table.

**Phase to address:** Stage 1 (Alembic skeleton + `env.py` batch mode), enforced wherever a live-store schema change lands. Verification: migration chain applies clean on Postgres AND (via batch mode) on SQLite; results DB built by `create_all()` with no `alembic_version` table.

---

### Pitfall 7: Live retention bugs — evict-then-need, unbounded growth, rehydration loading terminal history, rehydration breaking determinism

**What goes wrong:**
The working-set cache (the second knob — cache ≠ store) is mis-implemented in one of four ways: (a) **evict-then-need** — a record is purged on terminalize but a later status/recon query has **no read-through fallback** to the store → `KeyError`/`None` for a record that genuinely exists; (b) **unbounded growth** — terminal orders/closed positions are kept resident "for status queries," so memory tracks *run length* not active trading — the exact leak the two-knob model exists to prevent; (c) **rehydration loads terminal history** — restart replays the *full* transaction/closed-position history into the working set instead of just the open working set, ballooning boot memory and time; (d) **rehydration breaks determinism / bracket safety** — replaying history in unordered fashion, or evicting a bracket *parent* while its children are still open (the OCO contract breaks).

**Why it happens:**
Pure age/count eviction without a terminal-state gate is the "simplest bound" (FEATURES anti-feature) and can evict a still-open position. Read-through is easy to forget because backtest (retain-all) never needs it, so it's untested until live. Rehydration "load everything" feels safe but is wrong.

**How to avoid:**
**Purge-on-terminalize (event-driven, primary) + age/count sweep (safety net)**, gated to **skip open orders/positions** and **keep a bracket parent resident until all children terminal** (direct port of Nautilus's contingency rule onto `parent_order_id`/`child_order_ids`). **Read-through to the store for cold/terminal records, off the hot path** (an open position is *always* resident, so the hot path never read-throughs). **Restart rehydration loads only open positions + working orders (+ brackets)** and rebuilds the snapshot + running accumulators from the *last persisted snapshot row* — never a full-history replay. Backtest stays retain-all (finite run, no eviction). (FEATURES Q10.)

**Warning signs:**
A terminal-record query returns `None`/raises after a purge; live RSS grows monotonically with uptime independent of position count; restart boot loads thousands of closed positions; a rehydrated live session's working set differs from the pre-restart working set; a bracket child fires after its parent was evicted.

**Phase to address:** Stage 4 (Retention Model + Live Write-Through — design the two-knob retention *before* wiring write-through). Verification: an evict-then-read test (purge a terminal order, query it, assert it reads through from the store); a long-run memory-bound test (RSS flat as terminal count grows); a restart-rehydration test that asserts only the open working set loads; a bracket-parent-resident test.

---

### Pitfall 8: Write-through durability/ordering — store committed *after* the engine moved on

**What goes wrong:**
In live mode the cache is mutated and the FillEvent emitted (the engine acknowledges the state change) **before** the write-through actually commits — or the write fails silently. On restart, the rehydrated working set (rebuilt from the store) is *behind* what the engine believed, so the order mirror reconciles against a store that never recorded the fill. A multi-row write (e.g. a bracket parent + children, or a transaction + position + snapshot) that is not atomic can also leave a *partial* state in the store after a crash.

**Why it happens:**
Async/fire-and-forget write-through is tempting for latency, and ordering ("emit then persist") feels natural because the event queue is the engine's spine. But durability requires persist-then-acknowledge.

**How to avoid:**
**Synchronous write-through inside a transaction for create/terminalize** — commit before the engine acknowledges the state change (ARCHITECTURE Q9). Mutate cache and store atomically (store write in the same transaction, or store-first). Defer async batching to *only* the append-heavy, non-durability-critical writes (transactions, snapshots) and *only if profiling justifies it* (keep-only-measured — do not pre-build the async path). The store is the system of record; the cache must never be ahead of it for create/terminalize.

**Warning signs:**
Restart finds an order in a cache-derived state the store never recorded; a partial bracket (parent without children) persisted after a crash; reconcile reports a cache↔store mismatch; write-through code emits the event before the commit.

**Phase to address:** Stage 4 (Live Write-Through). Verification: a crash-after-emit / restart test proving the rehydrated working set equals the pre-crash state; an atomic-multi-row test (kill mid-bracket-write → store has all-or-nothing).

---

## Minor / Project-Specific Landmines

### Pitfall 9: `filterwarnings=["error"]` detonates on any new dependency warning

**What goes wrong:**
The new deps (pyarrow, alembic, sqlalchemy-libsql, deeper SQLAlchemy 2.0 usage) emit warnings the strict suite turns into **failures** — the `SAWarning` of Pitfall 1, plus pandas↔pyarrow dtype-conversion `DeprecationWarning`s, SQLAlchemy 2.0 legacy-API deprecations, and libsql-experimental beta warnings.

**Why it happens:** `pyproject.toml` sets `filterwarnings = ["error", ...]` (+ `--strict-markers`, `--strict-config`). Any unexpected warning, anywhere in the call graph, fails the test. New libraries are warning-chatty.

**How to avoid:** Treat the first warning as a signal to *fix the code* (e.g. `DecimalAsText` instead of `Numeric`), not to broaden the ignore list. Add a targeted `filterwarnings` ignore only with a written justification and the narrowest possible message/category match. Never add a blanket `ignore`.

**Warning signs:** A green Postgres run that fails the moment a SQLite/pyarrow path runs; a PR that adds a broad `filterwarnings` ignore entry.

**Phase to address:** Every stage (it is the gate). Verification: full suite green under the existing strict config with no new broad ignore.

---

### Pitfall 10: Nondeterminism introduced at the persistence edge

**What goes wrong:**
Persistence code naturally reaches for nondeterministic primitives: `datetime.now()`/`time.time()` for a `created_at`, unordered `dict` iteration in a JSON/settings `dumps`, no `ORDER BY` on a query whose rows later feed a comparison, or connection-pool/row-arrival ordering. Any of these breaks the determinism discipline (double-run byte-identical) the engine has held since v1.0 — now extended to persisted rows/artifacts.

**Why it happens:** Wall-clock and dict-order are the obvious defaults; the determinism contract lives in the engine's business-time + seeded-RNG seam, which persistence code is easy to write *outside* of.

**How to avoid:** Use **business `time` from the event / injected `BacktestClock`**, never wall clock, for persisted timestamps. **`sort_keys=True`** (or a canonical encoder) on every settings/JSON dump. **`ORDER BY` a stable key** on every query feeding a comparison or rehydration. UUIDv7 stored in a single canonical form (see Pitfall 11). (Pitfall 2's pyarrow scale-pinning is the columnar instance of this same rule.)

**Warning signs:** Determinism double-run differs only on a persisted timestamp/JSON column; `datetime.now()`/`time.time()` reachable from storage code; a `json.dumps` without `sort_keys`; a rehydration query with no `ORDER BY`.

**Phase to address:** Stage 1 (UUIDv7/JSON types) + Stage 2/3 (dumps, queries). Verification: grep storage modules for `datetime.now`/`time.time` (none); all settings dumps `sort_keys`; determinism double-run byte-identical including persisted artifacts.

---

### Pitfall 11: UUIDv7 stored as the wrong type / a second ID scheme creeping in

**What goes wrong:**
Either (a) the relational habit introduces a DB **autoincrement INTEGER** primary key "because it's simpler" — a *second ID scheme*, violating the locked single-UUIDv7 decision; or (b) UUIDv7 is stored as native `uuid` on Postgres but inconsistently as `TEXT` on one SQLite path and a 16-byte `BLOB` on another, so a `run_id` written under SQLite does **not** compare/join equal when read under Postgres — cross-backend equality silently breaks.

**Why it happens:** ORMs default to surrogate auto-PKs; UUID storage has three plausible encodings (native uuid / canonical TEXT / 16-byte BLOB) and picking different ones per dialect is an easy inconsistency.

**How to avoid:** A **single UUIDv7 column type** in `storage/types.py`, applied uniformly across all dialects (one canonical encoding — TEXT canonical form is the safe cross-backend default; native `uuid` on PG only if the same canonical string round-trips). UUIDv7 from the `idgen` singleton is the PK for every persisted domain row (`run_id`, order/position/signal keys) — **never** a DB-generated surrogate.

**Warning signs:** An `autoincrement=True` / `Integer, primary_key=True` on a persisted domain table; a `run_id` written under SQLite that fails an equality read under Postgres; two different UUID encodings across dialect code paths.

**Phase to address:** Stage 1 (the UUIDv7 type in `storage/types.py`). Verification: no autoincrement PK on persisted domain rows; a cross-backend round-trip test (write `run_id` under SQLite, read equal under Postgres).

---

### Pitfall 12: Tabs-vs-4-spaces indentation hazard breaks a handler-storage file

**What goes wrong:**
The new `Sql<Concern>Storage` files are placed beside existing in-memory siblings whose indentation differs by domain: `order_handler/storage/` and `portfolio_handler/storage/` use **tabs**; `strategy_handler/storage/`, `config/`, the new `storage/` and `results/` packages use **4 spaces**. Copy-pasting 4-space SQL code into a tab-indented `order_handler` module produces a **mixed-indentation file that fails to parse** (`TabError`) — a self-inflicted breakage the engine's own CLAUDE.md flags as a standing hazard.

**Why it happens:** No autoformatter is configured; indentation is matched by hand. Pasting from a 4-space reference (the ARCHITECTURE examples, or `strategy_handler`) into a tab module is the obvious mistake.

**How to avoid:** Match the **existing sibling file's** indentation exactly (ARCHITECTURE spells out which is which, per directory). Never normalize. When in doubt, open the sibling and copy its leading whitespace.

**Warning signs:** `TabError`/`IndentationError` on import; a diff that mixes tabs and spaces in one function; mypy failing to even parse a new storage module.

**Phase to address:** Stage 3 (operational backends beside the tab-indented siblings — highest exposure). Verification: each new file imports clean; per-file indentation matches its sibling (a mixed-indent tab file fails import, so a green import is the gate).

---

### Pitfall 13: FL-06 — SQL injection via symbol-as-identifier + hardcoded credentials in `SqlHandler`

**What goes wrong:**
`price_handler/store/sql_store.py` ships the FL-06 defect today: a **hardcoded credential** URL `postgresql+psycopg2://tizianoiacovelli:1234@localhost:5432/...` (L17); an **injectable DDL** `text(f'DROP TABLE IF EXISTS {…}'%sym)` that interpolates a symbol straight into a `DROP TABLE` (L35); and **symbol-as-table-name** in `prices.to_sql(symbol.lower(), …)` (L56/L58) and `pd.read_sql(symbol, …)` (L69). A crafted symbol name is an injection vector, and the credential is in source control.

**Why it happens:** Pre-existing code from before the refactor's hardening discipline; it predates the `SecretStr database_url` scaffolding (already present in `config/settings.py` from M2-06).

**How to avoid:** Rework `SqlHandler` onto the spine — creds from `Settings.database_url.get_secret_value()` (the `SecretStr` is already there, FL-06 fix is wiring); SQLAlchemy Core constructs + bound params + quoted identifiers, or the single-table-with-a-`symbol`-column pattern instead of symbol-as-table-name; never f-string/`%`-interpolated DDL.

**Warning signs:** A hardcoded `user:pass@host` in any source file; an f-string/`%`/`.format` inside a `text()` SQL or DDL string; a table name sourced from external input (a symbol).

**Phase to address:** Stage 1 (FL-06 `SqlHandler` rework is part of standing up the spine). Verification: grep the repo for hardcoded `:1234@` / `user:pass@` (none); no f-string/`%` inside `text()`; creds resolve from `SecretStr`.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems specific to this milestone.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| `Numeric` money column ("works on my Postgres dev DB") | No `TypeDecorator` to write | Hard test failure on SQLite/libSQL + silent float money-policy violation | **Never** — `DecimalAsText` from day one |
| Single flagged storage class (`if self.write_through:`) instead of two backend classes | One class, less code | Serialize code sits on the byte-exact hot loop → W1/W2 regression risk, oracle risk | **Never** — backend-selection is the locked pattern |
| Test persistence on SQLite only (zero setup) | Fast local TDD | Cross-backend divergence (Pitfall 4) ships undetected to the Postgres live path | MVP-only, *if* a Postgres parity run is a tracked must-before-live gate |
| Let pyarrow infer the frame schema | `from_pandas(df)` one-liner | Non-deterministic blob bytes break the determinism discipline | **Never** — explicit `decimal128` schema |
| Pure age/count cache eviction, no terminal gate | Simplest memory bound | Can evict a still-open position; bracket-parent safety lost | **Never** — purge-on-terminalize gate is mandatory |
| Async fire-and-forget write-through for create/terminalize | Lower live latency | Store behind engine → restart rehydrates stale state, reconcile mismatch | **Never** for create/terminalize; OK for append-only writes *if measured* |
| Skip the read-through fallback (backtest never needs it) | Less code now | Live status/recon query of a purged record → `None`/`KeyError` | **Never** — read-through is the other half of purge |
| Alembic migrations for the ephemeral results DB | "Consistent tooling" | Ceremony on a disposable DB; backtest path imports Alembic | **Never** — `create_all()` for ephemeral, Alembic for live PG only |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| **SQLite/libSQL money** | `Numeric`/`DECIMAL` column → `SAWarning` + float round-trip | `DecimalAsText` `TypeDecorator` (Decimal↔TEXT) uniformly on all dialects |
| **libSQL/Turso driver** | Hard core dep; treat as drop-in for SQLite | Optional Poetry extra; SQLite default; revert-URL escape hatch (dialect siblings) |
| **pyarrow Parquet blob** | Inferred `decimal128` scale | Explicit pinned schema from `core/money.py` scales |
| **Postgres JSONB vs SQLite JSON-as-text** | Filter on `settings->>'x'` cross-backend | Scalar-promote filterable params to indexed columns; JSON archival-only |
| **Alembic across 3 dialects** | Autogenerated PG DDL fails SQLite ALTER | `render_as_batch=True` + `JSON().with_variant(JSONB,'postgresql')`; scope to live PG |
| **`Settings.database_url` (SecretStr)** | Re-hardcode creds in `SqlHandler` | `database_url.get_secret_value()` — scaffolding already exists |
| **Injected store (not the queue)** | Emit a "persist" event onto `global_queue` | Write-through *inside* the handler's own injected store — off the queue (queue-only governs handler↔handler, not a handler's own store) |

## Performance Traps

Patterns that pass the correctness gate but fail the perf gate — or fail only at scale.

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Serialize/SQL on the per-tick backtest path | W1 >5% over the 15.7 s baseline, oracle still byte-exact but slower | Backtest backend has zero serialization code; end-of-run batch dump only | Immediately, on the first backtest run after wiring SQL |
| Arrow/pyarrow on the bar-window / indicator hot path | Per-tick array↔scalar conversion overhead; regresses PERF-05/06 | pyarrow only at the `run_artifacts` serialization boundary, never the loop | Immediately — the hot path is O(1) incremental, not bulk-columnar |
| Exploding equity/trade frames into per-bar SQL rows | 20M-row bloat at large sweeps; slow `runs` queries | One serialized blob per run (`run_artifacts`); blob is TOASTed/overflow-paged | At large sweeps (1000s of runs × 1000s of bars) |
| JSON-filtering the `runs` query surface | `WHERE settings->>'sharpe'` slow + non-indexable on SQLite | Scalar-promote filter params to indexed columns | As the sweep `runs` table grows past a few hundred rows |
| Unbounded live working-set cache | Live RSS grows with uptime, not active position count | Purge-on-terminalize + age sweep + read-through | In a long-running live process (days/weeks uptime) |
| Synchronous write-through stalling the daemon queue drain | Event-processing latency climbs under live event bursts | Keep create/terminalize sync; batch append-only writes behind an async writer *if measured* | Only at high live event rates — do not pre-optimize |

## Security Mistakes

Domain-specific (FL-06 + persistence-edge), beyond generic web security.

| Mistake | Risk | Prevention |
|---------|------|------------|
| Hardcoded DB credentials in `SqlHandler` (`:1234@localhost`, L17) | Credential in source control / VCS history | `Settings.database_url.get_secret_value()` (`SecretStr` already present) |
| f-string/`%` symbol interpolated into DDL (`DROP TABLE {sym}`, L35) | SQL injection via crafted symbol names | Core constructs + bound params + quoted identifiers; never string-built SQL |
| Symbol-as-table-name (`to_sql(symbol)`, `read_sql(symbol)`, L56/L69) | Injection + uncontrolled schema sprawl | Single table with a `symbol` *column*, parameterized |
| Logging money/credentials at the serialization edge | Secret/PII leak into structured logs | Log at existing `float()`-edge discipline; never log the resolved secret URL |

## "Looks Done But Isn't" Checklist

Things that appear complete in a demo but are missing a critical piece this milestone must prove.

- [ ] **SQL backend "works":** Often tested on SQLite only — verify the *same* test suite runs green on **Postgres** (and ideally `sqlite+libsql`); a one-backend pass does not prove the config-not-code swap.
- [ ] **Money persists:** Often round-trips a value without checking *type/precision* — verify the loaded value `isinstance(_, Decimal)` and `== Decimal("46189.87730727451")` exactly, run under `filterwarnings=["error"]` (no `SAWarning`).
- [ ] **Write-through off costs nothing:** Often a flag is off but a `serialize`/SQL import still sits on the hot path — verify the backtest backend module imports **no** SQLAlchemy/serialization symbol, and the oracle is byte-exact AND W1/W2 within the v1.5 ±5% gate.
- [ ] **Frame blob round-trips:** Often value-correct but byte-unstable — verify encoding the same frame twice yields **identical bytes** (explicit `decimal128` schema), not just equal DataFrames.
- [ ] **Restart rehydration tested:** Often loads state but never re-checks **determinism** and **scope** — verify only the *open* working set loads (not full terminal history) AND a rehydrated run is byte-identical to the pre-restart working set.
- [ ] **Purge-on-terminalize works:** Often evicts but has **no read-through** — verify a purged terminal record is still retrievable via read-through from the store, and an *open* position/bracket-parent is **never** evicted.
- [ ] **FL-06 closed:** Often the injection is fixed but creds still hardcoded (or vice-versa) — verify both: no hardcoded `user:pass@`, and no f-string/`%` inside any `text()`/DDL.
- [ ] **Cache "classified":** Often a doc with no routing decision — verify the (a)/(b)/(c) map is written AND each `lru_cache`/index is left/routed per the classification, with the "do NOT unify into one Arrow object" decision recorded.
- [ ] **Migrations apply:** Often green on Postgres only — verify `alembic upgrade head` also applies on SQLite via `render_as_batch=True`, and the ephemeral results DB uses `create_all()` (no `alembic_version` table).
- [ ] **UUIDv7 keys:** Often a DB autoincrement crept in — verify no `autoincrement` PK on persisted domain rows, and a `run_id` written under SQLite reads back *equal* under Postgres.

## Recovery Strategies

When a pitfall slips through despite prevention.

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| `Numeric` money on SQLite (Pitfall 1) | LOW (if caught early) | Swap the column type to `DecimalAsText`; re-run; any persisted float-tainted rows in an *ephemeral* DB are discarded by re-run. HIGH if it reached a live PG store with float-tainted history. |
| Non-deterministic blob bytes (Pitfall 2) | LOW | Pin the explicit `decimal128` schema; re-encode; ephemeral artifacts re-generate on re-run. |
| Serialize on the hot path (Pitfall 3) | LOW-MEDIUM | Move to backend-selection; delete serialization from the in-memory backend; re-run the perf gate to confirm W1 restored. |
| Cross-backend divergence (Pitfall 4) | MEDIUM | Replace dialect SQL with Core constructs; scalar-promote the offending filter param; add the missing-backend parity test that should have caught it. |
| Unbounded / mis-gated cache (Pitfall 7) | MEDIUM | Add the terminal-state gate + read-through; add the long-run memory test; for a live leak, restart rehydrates a clean bounded working set. |
| Write-through ordering (Pitfall 8) | HIGH (live) | Make create/terminalize synchronous-in-txn; reconcile cache↔store on next boot; replay missing events from venue (N+4 reconciliation). |
| FL-06 leak (Pitfall 13) | MEDIUM | Rotate the exposed credential, scrub from VCS history, rework onto `SecretStr` + parameterized SQL. |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Stage | Verification |
|---------|------------------|--------------|
| 1. Decimal float round-trip on SQLite/libSQL | **Stage 1** (`storage/types.py`) | Round-trip test asserts `Decimal` type + exact value under `filterwarnings=["error"]`; no `SAWarning` |
| 2. pyarrow inferred decimal128 scale | **Stage 2** (`frame_codec.py`) | Encode-twice → identical bytes; explicit `decimal128` schema asserted |
| 3. Serialize on the hot path | **Stage 3 / 4** (backend-selection) | Oracle byte-exact `134 / 46189.87730727451`; W1/W2 within v1.5 ±5%; in-memory backend imports no SQL symbol |
| 4. Cross-backend divergence | **Stage 1** (portable types) + **2/3** (parity tests) | Same suite green on SQLite + Postgres; all `runs` filters hit promoted scalar columns |
| 5. libSQL beta-driver | **Stage 1** (deps/`config/sql.py`) | libSQL is an optional extra; SQLite default; revert-URL smoke is code-free |
| 6. Alembic dialect drift | **Stage 1** (Alembic skeleton) | `upgrade head` applies on PG + SQLite (batch mode); results DB on `create_all()` |
| 7. Live retention bugs | **Stage 4** (retention model) | Evict-then-read-through test; flat-RSS long-run test; open-only rehydration test; bracket-parent-resident test |
| 8. Write-through durability/ordering | **Stage 4** (write-through) | Crash-after-emit / restart equals pre-crash working set; atomic multi-row write |
| 9. `filterwarnings=["error"]` failures | **All stages** (the gate) | Full suite green, no new broad `filterwarnings` ignore |
| 10. Persistence-edge nondeterminism | **Stage 1** + **2/3** | No `datetime.now`/`time.time` in storage; `sort_keys` dumps; double-run byte-identical incl. artifacts |
| 11. UUIDv7 wrong type / 2nd ID scheme | **Stage 1** (`storage/types.py`) | No autoincrement PK; cross-backend `run_id` equality round-trip |
| 12. Tabs-vs-spaces breakage | **Stage 3** (handler-storage siblings) | New files import clean; per-file indentation matches sibling |
| 13. FL-06 injection / hardcoded creds | **Stage 1** (`SqlHandler` rework) | No hardcoded `user:pass@`; no f-string in `text()`; creds from `SecretStr` |

## Sources

- `.planning/research/STACK.md` — the load-bearing Decimal-on-SQLite correction (Pitfall 1), libSQL beta verdict (Pitfall 5), pyarrow explicit-schema requirement (Pitfall 2), Alembic batch-mode scoping (Pitfall 6), FL-06 line refs (Pitfall 13). `[HIGH]`
- `.planning/research/ARCHITECTURE.md` — the 8 anti-patterns (Pitfalls 1, 2, 3, 4, 8, 13), backend-selection write-through (Pitfall 3), retention model (Pitfall 7), cache classification (concern #3), build-order stages. `[HIGH]`
- `.planning/research/FEATURES.md` — Q10 retention/rehydration mechanics + anti-features (Pitfall 7), Nautilus purge/bracket-safety precedent. `[HIGH]`
- `.planning/notes/persistence-milestone-design.md` — the converged seed; the *false* "Turso native DECIMAL" claim (root of Pitfall 1); the two-knob model. `[project]`
- `itrader/price_handler/store/sql_store.py` (read) — FL-06 targets confirmed: hardcoded creds L17, f-string `DROP TABLE` L35, symbol-as-table-name L56/L58/L69 (Pitfall 13). `[HIGH]`
- `CLAUDE.md` / project conventions — `filterwarnings=["error"]` strictness (Pitfall 9), Decimal-end-to-end + determinism + single-UUIDv7 locked decisions (Pitfalls 1, 10, 11), tab/space indentation hazard (Pitfall 12), v1.5 frozen baseline 15.7 s / 152.8 MB + oracle `134 / 46189.87730727451` (Pitfall 3). `[HIGH]`
- NautilusTrader Cache concepts (purge APIs, bracket-parent safety, restart rehydration) — via FEATURES survey. `[HIGH]`

---
*Pitfalls research for: v1.6 N+3b Persistence Foundation (swappable SQL spine + working-set cache on a Decimal/deterministic/oracle-gated engine)*
*Researched: 2026-06-27*
