---
phase: 03-operational-sql-backends-2-store-layer
reviewed: 2026-06-29T00:00:00Z
depth: standard
files_reviewed: 20
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
  - pyproject.toml
  - tests/integration/storage/conftest.py
  - tests/integration/storage/test_migrations.py
  - tests/integration/storage/test_sql_order_storage.py
  - tests/integration/storage/test_sql_portfolio_storage.py
  - tests/integration/storage/test_sql_signal_storage.py
  - tests/unit/order/test_order_storage.py
findings:
  critical: 1
  warning: 4
  info: 4
  total: 9
status: issues_found
---

# Phase 3: Code Review Report

**Reviewed:** 2026-06-29
**Depth:** standard
**Files Reviewed:** 20
**Status:** issues_found

## Summary

The store layer is well-structured: SQLAlchemy Core throughout (no f-string SQL — SEC-01 holds),
`bindparam`-parameterized reads, idempotent `build_*_tables` registrars, a clean composition-over-
inheritance spine, and a deterministic UUIDv7/`UtcIsoText` type vocabulary. I verified GATE-01
inertness empirically — importing all three storage factories does **not** pull SQLAlchemy
(`sqlalchemy loaded: False`), and the lazy-import quarantine in the `'live'` arms is correct.
Round-trip equality for `Order`/`SignalRecord`/`Transaction`/`CashOperation`/`PortfolioSnapshot`
is sound (constructors do not duplicate `state_changes` or override supplied timestamps).

The dominant problem is **not** in the SQL codecs but in backend selection: the `'live'` factory
arm and `LiveTradingSystem` default to `SqlSettings.default()`, which is SQLite `:memory:`. That
backend (a) decays Decimal money columns to float — the exact OPS-04/Pitfall-2 hazard the design
gates its money tests against — and (b) is ephemeral, so the "persistent audit trail" live store
silently persists nothing. The operator's `SYSTEM_DB_URL` value is read only as a boolean and then
discarded. Secondary issues: the self-referential bracket FK has no delete handling (Postgres
`IntegrityError` on parent removal), and the `orders`/`signals` schema omits `NOT NULL` on
logically-required columns.

## Critical Issues

### CR-01: `'live'` storage factories default to SQLite `:memory:` — money decays to float, nothing persists, `SYSTEM_DB_URL` value is ignored

**File:** `itrader/order_handler/storage/storage_factory.py:60`, `itrader/strategy_handler/storage/storage_factory.py:77-79`, `itrader/portfolio_handler/storage/storage_factory.py:83-87`, `itrader/trading_system/live_trading_system.py:126-144`

**Issue:**
All three `'live'` arms build a default backend from `SqlSettings.default()` when no `backend` is
injected:
```python
resolved = backend if backend is not None else SqlBackend(SqlSettings.default())
```
`SqlSettings.default()` is hard-pinned to SQLite `:memory:` (`itrader/config/sql.py:109-116` —
`driver=SQLITE_PYSQLITE, database=":memory:"`). Three concrete consequences:

1. **Money decays to float (locked-defect violation).** Order `price`/`quantity`/`leverage`,
   reservation/locked-margin amounts, and signal money are `sqlalchemy.Numeric`. On a SQLite
   backend `Numeric` rides REAL affinity and loses precision (e.g. the
   `Decimal("1234.567890123456789")` reservation in `test_reservation_money_exact_full_precision`).
   The test suite **gates every money assertion to the `pg_backend` Postgres arm precisely because
   SQLite decays it** — yet the production default backend is SQLite. This contradicts the
   project's locked "Decimal end-to-end; float-for-money is a correctness defect" rule.

2. **No durability.** `:memory:` SQLite vanishes when the engine is disposed / the process exits.
   The `'live'` arm is documented as "persistent, audit trail" (storage_factory docstrings), but a
   live run stores orders/positions/signals into an in-process database that is lost on restart —
   the opposite of the contract.

3. **`SYSTEM_DB_URL` is silently discarded.** `LiveTradingSystem.__init__` reads
   `_SYSTEM_DB_URL = os.getenv("SYSTEM_DB_URL", "")` and uses it only as a truthiness switch
   (line 126), then calls `OrderStorageFactory.create('live')` with **no backend** (line 140). The
   actual connection string the operator configured is never passed to the factory (the legacy
   `db_url` arg was removed), so setting `SYSTEM_DB_URL=postgresql://…` produces a SQLite `:memory:`
   store, not the requested Postgres. The `except NotImplementedError` fallback (lines 141-144) is
   dead code — the factory no longer raises it — so the misconfiguration is completely silent.

**Fix:**
Make the `'live'` arm fail loud instead of silently materializing a SQLite store (consistent with
the config layer's "no working secret defaults" philosophy), and thread the real backend/URL:
```python
# storage_factory.py (all three) — require an operational backend, do not invent a sqlite default
elif environment == 'live':
    if backend is None:
        raise ConfigurationError(
            "backend", None,
            "the 'live' storage arm requires an injected operational SqlBackend "
            "(Postgres); refusing to default to SQLite :memory: (money decay + no durability)",
        )
    from .sql_storage import SqlOrderStorage
    return SqlOrderStorage(backend)
```
```python
# live_trading_system.py — build the Postgres backend from the configured URL and inject it
from itrader.config.sql import SqlSettings, SqlDriver
from itrader.storage import SqlBackend
from pydantic import SecretStr
backend = SqlBackend(SqlSettings(driver=SqlDriver.POSTGRESQL_PSYCOPG2, url=SecretStr(_SYSTEM_DB_URL)))
order_storage = OrderStorageFactory.create('live', backend=backend)
```
If Phase 4 truly owns the wiring, the interim default must still be Postgres-or-raise, never SQLite.

## Warnings

### WR-01: Bracket parent deletion can raise `IntegrityError` on Postgres (self-ref FK, no `ON DELETE`)

**File:** `itrader/order_handler/storage/models.py:84-90`, `itrader/order_handler/storage/sql_storage.py:299-347`

**Issue:**
`orders.parent_order_id` is `ForeignKey("orders.id")` with no `ondelete=` and no `child_order_ids`
column. The delete paths (`remove_order`, `_delete_active` → `remove_orders_by_ticker` /
`clear_portfolio_orders`) delete a matched order without nulling or cascading its children. On
Postgres, deleting a bracket **parent** while a child row still references it raises
`IntegrityError` (FK RESTRICT). This is reachable: `_delete_active` filters to ACTIVE orders only,
so an active parent whose child has already gone terminal (FILLED/CANCELLED) is deleted while the
terminal child still points at it. The in-memory backend has no FK and removes freely, so this is
also a behavioral divergence the parity tests do not cover (the round-trip tests never delete a
bracket).

**Fix:** Either declare `ForeignKey("orders.id", ondelete="SET NULL")` (and reflect it in the
migration) so children are orphaned cleanly, or in the delete paths null the children's
`parent_order_id` (or delete the whole bracket) before deleting the parent. Add a deletion test
over a parent+child bracket on the `pg_backend` arm.

### WR-02: `orders` / `signals` / `order_state_changes` schema allows NULL on logically-required columns

**File:** `itrader/order_handler/storage/models.py:64-96`, `itrader/strategy_handler/storage/models.py:58-69`, migration `…operational_baseline.py:73-101,129-176`

**Issue:**
The `positions`/`transactions`/`cash_operations`/`equity_snapshots` tables correctly mark required
columns `nullable=False`, but the `orders` table leaves `time`, `type`, `status`, `ticker`,
`action`, `price`, `quantity`, `exchange`, `strategy_id`, `portfolio_id`, `filled_quantity`,
`created_at`, `updated_at`, `modification_count`, and `leverage` at the implicit `nullable=True`
default — likewise `signals` and `order_state_changes`. The `Order`/`SignalRecord` entities treat
these as non-null, so the database silently fails to enforce an invariant the rest of the system
relies on (defense-in-depth gap; a partial write or a future buggy caller can persist a NULL where
`_row_to_order` will then crash on `OrderType(None)`).

**Fix:** Add `nullable=False` to the logically-required columns in `build_order_tables` /
`build_signal_tables`, regenerate the Alembic baseline so DDL matches, and keep the model the single
source of truth.

### WR-03: `get_orders_by_time_range` raises mid-query on naive datetimes; range relies on text ordering

**File:** `itrader/order_handler/storage/sql_storage.py:407-420`

**Issue:**
`created_at` is `UtcIsoText` (a `String`-backed `TypeDecorator`). The clauses
`created_at >= start_time` / `<= end_time` bind the bounds through
`UtcIsoText.process_bind_param`, which **raises `ValueError` on any timezone-naive datetime**
(types.py:52-58). A caller passing a naive `datetime` (a common default) gets an exception thrown
from inside the query method rather than a clean empty/filtered result. Additionally the predicate
is a lexicographic comparison over ISO text; it is correct only while every row is UTC isoformat —
a latent fragility if the encoding ever admits a non-UTC offset.

**Fix:** Validate/normalize the bounds at the method boundary (raise a typed domain error, or
coerce naive→UTC explicitly) so the failure mode is documented and not a raw `ValueError` from the
codec; add a test covering naive and tz-aware bounds.

### WR-04: `PortfolioStateStorageFactory` raises plain `ValueError`, diverging from the typed-exception convention

**File:** `itrader/portfolio_handler/storage/storage_factory.py:73-75,88-92`

**Issue:**
`OrderStorageFactory` and `SignalStorageFactory` raise `ConfigurationError` for an unknown
environment, but `PortfolioStateStorageFactory` raises a bare `ValueError` both for an unknown
environment and for a missing `portfolio_id`. The project convention (CLAUDE.md error-handling
section) is "raise typed exceptions, not bare `Exception`." This inconsistency means callers cannot
catch storage-construction failures uniformly across the three factories.

**Fix:** Raise `ConfigurationError("environment", environment, …)` and
`ConfigurationError("portfolio_id", None, …)` to match the sibling factories.

## Info

### IN-01: Unused `import json` in `live_trading_system.py`

**File:** `itrader/trading_system/live_trading_system.py:6`

**Issue:** `json` is imported but never referenced in the module.
**Fix:** Remove the import.

### IN-02: Stale docstring in `PortfolioStateStorageFactory`

**File:** `itrader/portfolio_handler/storage/storage_factory.py:26`

**Issue:** The class docstring still reads "PostgreSQL backend for live trading (deferred to
D-sql)", but the `'live'` arm is now implemented (`SqlPortfolioStateStorage`).
**Fix:** Update the docstring to describe the implemented SQL spine backend.

### IN-03: `get_pending_orders(portfolio_id)` keys the nested dict by the argument, not `order.portfolio_id`

**File:** `itrader/order_handler/storage/sql_storage.py:371-375`

**Issue:** The filtered path returns `{portfolio_id: {...}}` using the literal argument, while the
`None` path keys by the rebuilt `order.portfolio_id`. If a caller ever passes a non-UUID `IdLike`
(`str`/`int`) the key type diverges from the unfiltered path.
**Fix:** Key by `order.portfolio_id` in both branches for parity.

### IN-04: SQL stores silently no-op for non-UUID `IdLike` order ids

**File:** `itrader/order_handler/storage/sql_storage.py:299-302,350-355,422-425`

**Issue:** `IdLike = Union[str, int, uuid.UUID]`, but `remove_order` / `get_order_by_id` /
`get_order_history` early-return `False`/`None`/`[]` for any non-`uuid.UUID`. A caller passing a
string UUID gets a silent miss rather than a coercion or error — a quiet divergence from the ABC's
declared `IdLike` contract.
**Fix:** Either narrow the SQL-store signatures to `uuid.UUID`, or coerce string/int inputs via
`uuid.UUID(...)` before querying.

---

_Reviewed: 2026-06-29_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
