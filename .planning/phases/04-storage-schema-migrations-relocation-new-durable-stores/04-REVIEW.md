---
phase: 04-storage-schema-migrations-relocation-new-durable-stores
reviewed: 2026-07-10T00:00:00Z
depth: standard
files_reviewed: 24
files_reviewed_list:
  - itrader/order_handler/storage/sql_storage.py
  - itrader/portfolio_handler/storage/sql_storage.py
  - itrader/storage/engine.py
  - itrader/storage/halt_record_store.py
  - itrader/storage/strategy_registry_store.py
  - itrader/storage/system_store.py
  - itrader/storage/venue_store.py
  - itrader/strategy_handler/storage/sql_storage.py
  - migrations/env.py
  - migrations/versions/strategy_registry.py
  - migrations/versions/system_store.py
  - migrations/versions/venue_config.py
  - tests/integration/storage/test_cached_sql_portfolio_storage.py
  - tests/integration/storage/test_migrations.py
  - tests/integration/storage/test_sql_order_storage.py
  - tests/integration/storage/test_sql_portfolio_storage.py
  - tests/integration/storage/test_sql_signal_storage.py
  - tests/integration/test_durable_halt.py
  - tests/integration/test_okx_inertness.py
  - tests/support/schema.py
  - tests/unit/storage/test_strategy_registry_store.py
  - tests/unit/storage/test_system_store.py
  - tests/unit/storage/test_venue_store.py
findings:
  critical: 1
  warning: 3
  info: 2
  total: 6
status: partially_remediated
remediation:
  resolved: [CR-01, IN-01, IN-02]
  resolved_commits: [53a90b07, 6b623549]
  deferred: [WR-01, WR-02, WR-03]
  deferred_tracking: .planning/todos/pending/04-storage-review-warnings.md
---

# Phase 4: Code Review Report

**Reviewed:** 2026-07-10T00:00:00Z
**Depth:** standard
**Files Reviewed:** 24 (supporting `itrader/storage/types.py`, `itrader/config/sql.py`,
and both `storage/models.py` registrars read as cross-reference context)
**Status:** issues_found

> Note: this supersedes the earlier pre-remediation review pass. The prior WR-02 (PRAGMA)
> and WR-03 (`create_all` in `__init__`) are now REMEDIATED — the `SqlEngine` sets
> `PRAGMA foreign_keys=ON` on SQLite and the seven durable stores are schema-pure with a
> shared `provision_schema` test seam. Prior WR-01/IN-02/IN-03 are DEFERRED by
> `04-GAP-DECISIONS.md` and are not re-raised as new findings. This is a fresh adversarial
> pass over the completed code.

## Remediation Status (2026-07-10)

Applied in the same execution run that produced this review (phase-04 code-review gate):

- ✅ **CR-01 (BLOCKER) — RESOLVED** (`53a90b07`): `StrategyRegistryStore.upsert` now updates the
  registry row in place (update-in-place-or-insert), never deleting the FK-parent row. The live
  re-config path (`upsert → set_subscriptions → upsert`) no longer raises `IntegrityError`.
  Reproduced before the fix / confirmed fixed after; regression test
  `test_upsert_of_subscribed_strategy_preserves_children` added; full suite **2049 passed**.
- ✅ **IN-01 — RESOLVED** (`6b623549`): dead `import uuid` removed from `halt_record_store.py`.
- ✅ **IN-02 — RESOLVED** (`6b623549`): `Decimal("0")` sum seed aligned across both accessors.
- ⏭ **WR-01 / WR-02 / WR-03 — DEFERRED** to a tracked follow-up
  (`.planning/todos/pending/04-storage-review-warnings.md`): migration↔registrar constraint-parity
  coverage, cross-file Postgres-cleanup ordering, and durable-store naive-datetime boundary guard.
  Owner-approved to handle separately — these are hardening improvements with judgment calls
  (WR-01 in particular may surface further latent schema drift once it inspects FKs).

## Summary

Reviewed the Phase-4 storage relocation: the 3 new durable stores (`system_store`,
`venue_store`, `strategy_registry_store`), the relocated Alembic chain + its 3 new
revisions, the shared `provision_schema` test seam, and the pre-existing operational
stores (order / portfolio / signal / halt) whose FK behavior is newly affected by the
`SqlEngine` `PRAGMA foreign_keys=ON` connect hook.

Headline: the FK enforcement that the WR-02 remediation newly turned on for SQLite exposes
one genuine, reachable correctness bug in the strategy registry — the documented "overwrite"
operation (`StrategyRegistryStore.upsert`) deletes the FK-parent row while child subscription
rows still reference it, which now raises `IntegrityError` on *both* dialects. No existing
test covers it (none re-upserts a strategy that already has subscriptions).

The other findings are a test-parity coverage gap, a brittle cross-file DB-cleanup ordering
dependency, an input-validation asymmetry between the durable stores and the order store, and
two cosmetic items. The in-scope locked decisions (schema-pure durable stores / no runtime
`create_all`; the SQLite-only PRAGMA guard; Decimal-money; 4-space indentation;
import-inertness; deferred WR-01/IN-02/IN-03) were respected and are not re-flagged.

## Narrative Findings (AI reviewer)

### Critical Issues

#### CR-01: `StrategyRegistryStore.upsert()` violates the subscriptions FK when overwriting a subscribed strategy

**File:** `itrader/storage/strategy_registry_store.py:120-144`
**Issue:**
`upsert` is a delete-then-insert on the **parent** `strategy_registry` table:

```python
with self.engine.begin() as connection:
    connection.execute(
        delete(self.strategy_registry).where(
            self.strategy_registry.c.strategy_name == strategy_name
        )
    )
    connection.execute(insert(self.strategy_registry), [ ... ])
```

`strategy_subscriptions.strategy_name` is a FK onto `strategy_registry.strategy_name` with
**no `ON DELETE` action** — verified in both the registrar (line 82,
`ForeignKey("strategy_registry.strategy_name")`) and the migration
(`migrations/versions/strategy_registry.py:65`, `sa.ForeignKeyConstraint(...)` with no
`ondelete=`). Default is RESTRICT / NO ACTION.

The docstring calls this method "Persist (or **overwrite**) a strategy's config", with
subscriptions "managed separately". The normal lifecycle is therefore:

1. `upsert("sma_macd", cfg, True, at)` → registry row created
2. `set_subscriptions("sma_macd", [...], at)` → child rows created
3. `upsert("sma_macd", new_cfg, True, at2)` → **config change**

At step 3, `DELETE FROM strategy_registry WHERE strategy_name='sma_macd'` fires while child
subscription rows still reference that name. FK checks are immediate on both backends
(Postgres always; SQLite now, via the shared-`SqlEngine` `PRAGMA foreign_keys=ON` connect
hook), so the DELETE raises `IntegrityError` *before* the re-INSERT and aborts the whole
transaction. A subscribed strategy's config can never be updated. This is exactly the bug
class the PRAGMA change was meant to surface — but the store's own write path trips it.

`SystemStore.upsert` / `VenueStore.upsert` use the same delete-then-insert idiom safely
**only because they have no child tables**; the strategy registry is the one store with a
dependent FK child, so the pattern is unsafe there.

Not covered by tests: `test_set_subscriptions_replaces_all` re-calls `set_subscriptions`
(deletes *children* — safe), but no test re-`upsert`s a strategy that already has
subscriptions.

**Fix:** Do not delete the parent row on overwrite — update-if-exists / insert-if-not:

```python
def upsert(self, strategy_name, config, enabled, at):
    with self.engine.begin() as connection:
        updated = connection.execute(
            update(self.strategy_registry)
            .where(self.strategy_registry.c.strategy_name == strategy_name)
            .values(enabled=enabled, config_json=config, updated_at=at)
        )
        if updated.rowcount == 0:
            connection.execute(
                insert(self.strategy_registry),
                [{"strategy_name": strategy_name, "enabled": enabled,
                  "config_json": config, "updated_at": at}],
            )
```

Add a regression test: `upsert` → `set_subscriptions` → `upsert` (config change) → assert
the new config persisted AND the subscriptions survived.

### Warnings

#### WR-01: Migration↔registrar parity test compares only column-name sets — FK/constraint/nullability drift is invisible

**File:** `tests/integration/storage/test_migrations.py:211-257`
**Issue:** `test_create_all_vs_migration_parity` asserts equal table sets and, per table,
equal **column-name** sets (`{c["name"] for c in inspector.get_columns(table)}`). It does
not compare FK definitions (including `ondelete`), PK composition, nullability, or indexes.
A migration that diverges from its registrar on any of those dimensions — precisely the kind
of drift behind subtle runtime FK failures like CR-01 — passes this "parity" gate green. The
docstring's claim that it proves "the migrations reproduce the registrars" overstates what
column-name equality guarantees.
**Fix:** Also compare, per new table, the FK set (`inspector.get_foreign_keys` incl.
`options.ondelete`), the PK constraint (`inspector.get_pk_constraint`), and per-column
`nullable`, so a registrar/migration divergence in constraints is caught, not just columns.

#### WR-02: Cross-file Postgres cleanup depends on alphabetical test-collection order

**File:** `tests/integration/storage/test_cached_sql_portfolio_storage.py:63-78`
**Issue:** The autouse `_drop_operational_portfolio_tables` fixture exists solely so that
`test_migrations.py`'s `alembic upgrade head` (which `op.create_table`s the same portfolio
tables) does not collide with tables this file created on the shared session Postgres
container. Correctness relies entirely on `test_cached_sql_portfolio_storage.py` sorting
alphabetically **before** `test_migrations.py` (stated in the fixture comment). That is
brittle: a file rename, a `pytest-randomly` run, or running `test_migrations.py` in a
different collection order reintroduces the `ProgrammingError` the fixture was written to
prevent. The cleanup is a teardown side-effect of an unrelated file rather than an explicit
ordering contract.
**Fix:** Have each Postgres-touching storage test self-clean its own tables in teardown (the
`test_migrations.py` `downgrade base` pattern), or use a function-scoped
"drop-all-registered-tables" fixture that does not depend on inter-file order.

#### WR-03: New durable stores bind caller `at` straight into `UtcIsoText`, which hard-raises on a naive datetime — no boundary guard

**File:** `itrader/storage/halt_record_store.py:98-115`, `itrader/storage/system_store.py:82-97`, `itrader/storage/venue_store.py:127-153`, `itrader/storage/strategy_registry_store.py:120-144`
**Issue:** `UtcIsoText.process_bind_param` raises `ValueError` on a timezone-naive datetime
(`itrader/storage/types.py:52-58`). The durable stores bind caller-supplied `at`/`created_at`
directly with no normalization, so a naive datetime yields an uncaught `ValueError`
mid-transaction. `SqlOrderStorage` deliberately guards this exact hazard at its method
boundary (`_ensure_utc`, `sql_storage.py:478-488`, tagged WR-03) so a naive bound "does not
escape as a raw codec error"; the durable stores — one of which is the safety-critical halt
latch invoked from `halt()` — lack that guard. Confidence is moderate: the documented D-07
contract is "caller supplies tz-aware `at`" and every current test honors it, so this is a
robustness/consistency gap rather than a proven live failure.
**Fix:** Either apply the same `_ensure_utc`-style normalization at each store boundary for
consistency with `SqlOrderStorage`, or assert the tz-aware precondition with a typed domain
error at `upsert`/`record_halt` entry so the failure is a clear precondition violation rather
than a raw codec `ValueError`.

### Info

#### IN-01: Unused `import uuid` in the halt-record store

**File:** `itrader/storage/halt_record_store.py:26`
**Issue:** `import uuid` (line 26) is never referenced — the table uses the capitalized
`Uuid` type imported from `itrader.storage` (line 67) and ids come from `idgen`. The bare
`uuid` module is dead.
**Fix:** Remove the `import uuid` line.

#### IN-02: Inconsistent Decimal-zero seed across the two full-precision sum accessors

**File:** `itrader/portfolio_handler/storage/sql_storage.py:273` vs `:323`
**Issue:** `get_reserved_cash` seeds `sum(amounts, Decimal("0.00"))` while `get_locked_margin`
seeds `sum(amounts, Decimal("0"))`. Both are numerically correct (Decimal addition adopts the
operands' max scale; the empty case differs only in trailing-zero exponent, which compares
equal). Purely a readability/consistency nit.
**Fix:** Use one consistent zero seed (`Decimal("0")`) in both accessors.

---

_Reviewed: 2026-07-10T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
