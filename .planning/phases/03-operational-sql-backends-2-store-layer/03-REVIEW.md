---
phase: 03-operational-sql-backends-2-store-layer
reviewed: 2026-06-29T16:51:30Z
depth: standard
files_reviewed: 19
files_reviewed_list:
  - itrader/order_handler/storage/models.py
  - itrader/order_handler/storage/sql_storage.py
  - itrader/order_handler/storage/storage_factory.py
  - itrader/portfolio_handler/storage/models.py
  - itrader/portfolio_handler/storage/sql_storage.py
  - itrader/portfolio_handler/storage/storage_factory.py
  - itrader/storage/backend.py
  - itrader/storage/migrations/env.py
  - itrader/storage/migrations/versions/2cbf0bf6b0b6_operational_baseline.py
  - itrader/strategy_handler/storage/models.py
  - itrader/strategy_handler/storage/sql_storage.py
  - itrader/strategy_handler/storage/storage_factory.py
  - itrader/trading_system/live_trading_system.py
  - tests/integration/storage/conftest.py
  - tests/integration/storage/test_migrations.py
  - tests/integration/storage/test_sql_order_storage.py
  - tests/integration/storage/test_sql_portfolio_storage.py
  - tests/integration/storage/test_sql_signal_storage.py
  - tests/unit/order/test_order_storage.py
findings:
  critical: 0
  warning: 1
  info: 1
  total: 2
status: issues_found
---

# Phase 3: Code Review Report (iteration 2)

**Reviewed:** 2026-06-29T16:51:30Z
**Depth:** standard
**Files Reviewed:** 19
**Status:** issues_found

## Summary

Re-review of the operational SQL store layer after the 7 prior fixes (CR-01 partial,
WR-01..04, IN-01..02). I traced each applied fix against its target and against the
entities the columns persist. **No regressions were introduced by the fixes**, and the
fixes are correctly reflected in both `models.py` and the regenerated Alembic baseline:

- **WR-01 (FK `ondelete="SET NULL"`)** — present on `orders.parent_order_id` and mirrored
  verbatim in the migration (`fk_orders_parent_order_id_orders ... ondelete='SET NULL'`).
  The `_delete_active` / `remove_order` paths delete child `order_state_changes` before the
  parent and rely on SET NULL to orphan terminal children cleanly. Logic is sound.
- **WR-02 (NOT NULL columns)** — I verified every `nullable=False` column against its source
  entity's actual optionality: `Order` (price/quantity/filled_quantity forced through
  `to_money` in `__post_init__`, `leverage` default `Decimal("1")`, `modification_count`
  default 0, `created_at`/`updated_at` backfilled from `time`), `CashOperation`
  (`fee=Decimal("0")` default; only `balance_*`/`reference_id` Optional → `nullable=True`),
  `PortfolioSnapshot` (only `benchmark_return` Optional → `nullable=True`), `SignalRecord`
  (money fields stay `nullable=True`). No valid entity can produce a NULL into a
  `nullable=False` column — WR-02 is safe, no write-path regression.
- **WR-03 (naive-datetime UTC coercion)** — `_ensure_utc` correctly normalizes the
  `get_orders_by_time_range` bounds to tz-aware UTC, consistent with `UtcIsoText`'s
  naive-rejection and UTC-normalizing codec; the ISO-text range/ORDER-BY comparisons stay
  chronologically correct (Python `isoformat` emits 0-or-6 fractional digits, and the fixed
  `+00:00` offset keeps lexicographic == chronological).
- **WR-04 (typed `ConfigurationError`)** — all three factories raise `ConfigurationError`
  for unknown environments; the portfolio factory also raises it for a missing
  `portfolio_id` on the live arm. Consistent.
- **IN-01/IN-02** — `sys`/`ErrorEvent` are module-level in `live_trading_system.py` and used
  in `_publish_and_continue`; no unused import remains.

The single remaining issue is the unfixed *other half* of CR-01: the call site
(`live_trading_system`) was hardened to "Postgres-or-raise," but the factory defaults it
delegates to still silently fall back to a money-decaying SQLite backend on the `'live'`
arm. See WR-01 below.

## Deferred-by-design (NOT re-flagged)

IN-03 / IN-04 were intentionally skipped to preserve documented SQL/in-memory backend
parity. I reviewed the parity contract (e.g. `_delete_active` ACTIVE-only deletes mirroring
the in-memory `is_active` semantics; `search_orders` allow-list mirroring the in-memory
`hasattr` guard; `count_orders_by_status` returning status `.name` keys) and the skip
rationale holds — diverging the SQL backend from the in-memory contract would break the
GATE-02 cross-backend parity these stores are built against. Not actionable.

## Warnings

### WR-01: `'live'` factory arm defaults to a money-decaying SQLite backend (CR-01 remainder)

**File:** `itrader/order_handler/storage/storage_factory.py:60`
**Also:** `itrader/portfolio_handler/storage/storage_factory.py:89-92`,
`itrader/strategy_handler/storage/storage_factory.py:77-78`

**Issue:** All three `'live'` arms build `SqlBackend(SqlSettings.default())` when no
`backend` is injected, and `SqlSettings.default()` pins `driver=SQLITE_PYSQLITE,
database=":memory:"` (`itrader/config/sql.py:109-116`). The order, portfolio-state, and
signal stores persist **Decimal money** (`price`, `quantity`, `leverage`, reservation /
locked-margin / snapshot amounts, `stop_loss`, etc.) into `Numeric` columns. On a
SQLite-family backend `Numeric` decays to float storage (the project's own "Pitfall 2 —
money never lands on SQLite"; the round-trip tests gate every money assertion to the
`pg_backend` Postgres arm precisely for this reason). So `OrderStorageFactory.create('live')`
with no backend returns a store that silently loses money precision on read — the exact
defect CR-01 documented ("`create('live')` with no backend … silently materialized a SQLite
:memory: store (money decay + no durability)"). CR-01's fix patched only the
`live_trading_system` call site (Postgres-or-raise, no SQLite fallback); the factory default
it delegates to still embodies the trap. It is reachable today:
`test_create_live_storage_returns_sql_backend` constructs exactly this SQLite-backed
`SqlOrderStorage` (it just never asserts money), and any Phase-4 / direct caller invoking
`create('live')` without a backend inherits the decay.

**Fix:** Make the operational `'live'` arm fail-closed instead of defaulting to SQLite,
matching the CR-01 "Postgres-or-raise (no SQLite fallback)" decision. Either require an
injected `backend`, or default to the Postgres driver so the credential validator fires:

```python
elif environment == 'live':
    from itrader.config.sql import SqlDriver, SqlSettings
    from itrader.storage import SqlBackend
    from .sql_storage import SqlOrderStorage

    if backend is None:
        # Operational money-bearing store must never silently land on SQLite
        # (Numeric -> float decay). Default to the Postgres arm, whose
        # _require_pg_credentials validator fails loud when unconfigured.
        backend = SqlBackend(SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2))
    return SqlOrderStorage(backend)
```

Apply the same change to the portfolio-state and signal factories.

## Info

### IN-01: `get_order_history` uses truthiness instead of `is not None` for `from_status`

**File:** `itrader/order_handler/storage/sql_storage.py:447`
**Issue:** `OrderStatus(from_value).name if from_value else None` relies on every
`OrderStatus.value` being truthy. It is today (all enum values are non-empty strings), so
this is currently equivalent to `is not None`, but it is a latent fragility: if a status
with a falsy `.value` (e.g. `""`) were ever added, a present-but-falsy `from_status` would
be misreported as `None`. The sibling `_load_state_changes` (line 217) already uses the
explicit `is not None` guard.
**Fix:** `OrderStatus(from_value).name if from_value is not None else None` for consistency
with the rest of the codec.

---

_Reviewed: 2026-06-29T16:51:30Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
