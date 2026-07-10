# Phase 4 — Gap Plan Decisions (review remediation)

**Source:** `04-REVIEW.md` (6 findings: 0 critical, 3 warning, 3 info)
**Decided:** 2026-07-10 (interactive session)
**Outcome:** one remediation plan (**04-04**) — 3 fixes to build, 2 deferred, 1 skipped.

The phase's hard gates all passed (SEC-01, D-05, D-06, migrations, inertness). Every
finding is robustness/portability hardening, latent today because the deploy target is
Postgres and the primary protections are structural. Nothing here is a live bug.

---

## Decision table

| Finding | Verdict | What & why |
|---|---|---|
| **WR-01** — secret denylist uses exact-key membership; `client_secret`/`secretKey`/`api_secret`/`auth_token` slip past | **DEFER** | Owner = upcoming **secret-manager milestone**. Not dropped — a conscious deferral. Rationale below. |
| **WR-02** — SQLite FK on `strategy_subscriptions` never enforced (no `PRAGMA foreign_keys=ON`) | **FIX (04-04)** | Enable PRAGMA at the **backend** (`SqlEngine`), dialect-guarded, + orphan-insert-raises test. |
| **WR-03** — `create_all(checkfirst=True)` runs unconditionally in store `__init__` → can create un-migrated tables on live Postgres | **FIX (04-04)** | **Option-1 (light), template-wide across all 7 DURABLE stores** (see surface below; the count was corrected from 5 → 7 after a full-tree grep). Remove `create_all` from constructors; a shared test fixture provisions schema via `metadata.create_all()`; production is Alembic-only. The **ephemeral `results/sql_storage.py` store is EXCLUDED** — per D-14 it is intentionally `create_all`-owned, not Alembic-owned. |
| **IN-01** — `StrategyRegistryStore.read_all` has no `ORDER BY` (nondeterministic order) | **FIX (04-04)** | Add deterministic `.order_by(strategy_name, venue, symbol, timeframe)`. |
| **IN-02** — `SystemStore`/`StrategyRegistryStore` have no secret-scrub guard | **DEFER** | Folded into the WR-01 secret-manager milestone (same layer, same policy decision). |
| **IN-03** — three near-identical store clones (duplication) | **SKIP** | Documented deliberate decision ("per-concern clone over shared base"); finding itself says no change required. |

**Build scope for 04-04:** WR-03 (largest — 5 stores + their unit-test fixtures), WR-02, IN-01.

---

## Rationale (the non-obvious calls)

### WR-01 / IN-02 — defer to the secret-manager milestone
A secret manager does **not** replace this guard (they're different layers: the manager is
the vault + retrieval; the guard is a *write-time tripwire* against a credential accidentally
landing in a persisted config blob). But:
- Exposure today is near-zero — the structural arm holds (credentials are connector-owned
  `SecretStr`, never passed to these stores).
- The substring fix has a real false-positive tail (a legit key like `rate_limit_token_bucket`
  contains `token` and would be rejected).
- The secret-manager work is the natural home to set the matching policy holistically and
  extend it to all three stores at once, instead of a throwaway substring tweak now.

Action: record as conscious deferral so the review finding closes with a rationale, owner =
secret-manager milestone. **Not** silently dropped.

### WR-03 — Option-1 (light), template-wide (all 5 stores)
**The problem:** `create_all` and Alembic are two schema authorities over the same DB.
`create_all` builds tables but never stamps `alembic_version`. On a live Postgres where the
app boots before migrations run, `create_all` creates the tables un-stamped → the subsequent
`alembic upgrade head` hits `op.create_table` on an existing table (**DuplicateTable**), or
you get silent **schema drift** (DB schema exists, Alembic thinks it's at revision zero). On a
*durable* operational store that's the exact failure migrations exist to prevent. The
`test_create_all_vs_migration_parity` test proves both paths build byte-identical schema —
which is *why* the drift is dangerous: the only missing piece is the `alembic_version` stamp.

**Why Option-1 over the dialect-gate band-aid:** the root cause is a separation-of-concerns
violation — schema lifecycle is a deployment/ops concern, and a runtime store object should
not own it. The codebase **already documents this exact split as D-14 / MIG-01** ("the durable
operational store evolves under Alembic; the ephemeral research/results store uses
`create_all`"). Today the durable store constructors *contradict* their own stated decision by
calling `create_all` at runtime. Option-1 makes the runtime code finally match D-14.

**Why "light" not "full-fidelity":** the store *unit* tests currently lean on the
constructor's `create_all` (they build over in-memory SQLite via `SqlEngine(SqlSettings.default())`
with no Alembic). Removing `create_all` from the constructor means each store unit test needs a
fixture that provisions schema. The **light** variant = fixture calls `metadata.create_all(engine)`
(fast, Dockerless, store becomes schema-pure). The full-fidelity variant (fixture runs
`command.upgrade(head)`) is overkill for unit tests — `test_migrations.py` already exercises the
real chain on both SQLite and testcontainers Postgres.

**Why template-wide (all 5):** the pattern is a shared idiom across `system_store`, `venue_store`,
`strategy_registry_store`, **plus** `halt_record_store.py:91` and
`order_handler/storage/sql_storage.py:85`. Fixing it once, consistently, everywhere gives one
coherent "durable stores never self-create schema" rule that matches D-14's intent uniformly.

### WR-02 — PRAGMA at the backend (`SqlEngine`), NOT a test fixture
**The problem:** SQLite ignores `FOREIGN KEY` unless `PRAGMA foreign_keys=ON` is set per
connection; Postgres always enforces. So `set_subscriptions("ghost", ...)` for an unregistered
strategy **raises `ForeignKeyViolation` on Postgres but silently inserts an orphan on SQLite** —
the backends diverge, and since every unit test runs on SQLite the FK integrity the schema
declares is *never actually exercised* (`delete()`'s "FK child order" is a no-op on the test double).

**Why backend, not fixture** (the sharp question raised in session): SQLite is **not** test-only
here — `SqlSettings.results_default()` ships a file-backed SQLite results store at
`output/results.db` (runtime), and there's a `SQLITE_LIBSQL`/Turso runtime slot (D-15). So:
- The PRAGMA hook is **dialect-guarded** → a **no-op on production Postgres** (zero cost there).
- Enabling it only in a fixture would make *test-SQLite* faithful while leaving *runtime-SQLite*
  (results store, Turso slot) still silently non-enforcing — relocating the exact WR-02 divergence
  rather than fixing it, and making the tests lie about real runtime behavior.

**Rule of thumb that separates WR-02 from WR-03:** *provisioning* differs per environment (→
fixture, so WR-03's `create_all` moves to a fixture); *correctness semantics of the engine*
(honoring declared constraints) should be identical everywhere the engine runs (→ backend, so
WR-02's PRAGMA lives on `SqlEngine`).

### IN-01 — include
One-liner (`.order_by(...)`), directly serves the project's locked determinism value, and
guards any future golden/byte-exact caller from flaking. Cheap insurance.

### IN-03 — skip
Deliberate, documented design choice (per-concern clone over a shared base). The finding itself
says "no change required." Refactoring would fight an intentional decision for marginal gain.

---

## Affected surface (for the planner)

- **WR-03:** remove `create_all` from constructors in the **7 durable stores** —
  `itrader/storage/system_store.py:74`, `itrader/storage/venue_store.py:117`,
  `itrader/storage/strategy_registry_store.py:110`, `itrader/storage/halt_record_store.py:91`,
  `itrader/order_handler/storage/sql_storage.py:85`,
  `itrader/portfolio_handler/storage/sql_storage.py:80`,
  `itrader/strategy_handler/storage/sql_storage.py:63`.
  **EXCLUDE** `itrader/results/sql_storage.py:94` (ephemeral results store — D-14 keeps its
  `create_all`; removing it would break the ephemeral provisioning path).
  Add shared schema-provisioning test fixture(s); update every test that relied on the
  constructor `create_all` — the store unit tests (`tests/unit/storage/test_system_store.py`,
  `test_venue_store.py`, `test_strategy_registry_store.py`) AND the integration round-trip
  tests that build the order / portfolio / signal SQL storage over sqlite + `pg_backend`
  (`tests/integration/storage/test_sql_order_storage.py`, `test_sql_portfolio_storage.py`,
  `test_sql_signal_storage.py`, their `test_cached_sql_*` siblings, and halt-record coverage).
  A shared fixture (e.g. `provision_schema(engine)` calling `metadata.create_all`) is the
  natural home so no test re-implements provisioning.
- **WR-02:** add a dialect-guarded `event.listens_for(engine, "connect")` PRAGMA hook in
  `itrader/storage/engine.py` (`SqlEngine`); add an orphan-insert-raises test.
- **IN-01:** add `.order_by(...)` to `StrategyRegistryStore.read_all`
  (`itrader/storage/strategy_registry_store.py:245`).

## Guardrails
- Keep `filterwarnings=["error"]` clean (dispose discipline).
- Preserve `test_create_all_vs_migration_parity` — registrars remain the single source of truth
  for both paths; only the *caller* of `create_all` moves (store → fixture).
- Backtest byte-exactness (oracle 134 / `46189.87730727451`) and OKX inertness must stay intact.
- Match per-file indentation (storage spine = 4 spaces).
