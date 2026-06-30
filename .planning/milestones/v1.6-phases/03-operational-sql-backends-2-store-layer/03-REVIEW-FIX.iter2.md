---
phase: 03-operational-sql-backends-2-store-layer
fixed_at: 2026-06-29T16:44:31Z
review_path: .planning/phases/03-operational-sql-backends-2-store-layer/03-REVIEW.md
iteration: 1
findings_in_scope: 9
fixed: 7
skipped: 2
status: partial
---

# Phase 3: Code Review Fix Report

**Fixed at:** 2026-06-29T16:44:31Z
**Source review:** .planning/phases/03-operational-sql-backends-2-store-layer/03-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 9 (1 critical, 4 warning, 4 info — fix_scope: all)
- Fixed: 7
- Skipped: 2

**Verification gates (post-fix, full repo):**
- `poetry run mypy --strict itrader` → **Success: no issues found in 206 source files**
- `poetry run pytest tests -q` → **1440 passed**
- `poetry run pytest tests/integration/storage tests/unit/order/test_order_storage.py` →
  **63 passed** (the Postgres round-trip arm ran — Docker was available — so the WR-01
  `ON DELETE SET NULL` and WR-02 `NOT NULL` migration changes were exercised against real
  Postgres, not just the SQLite `create_all` path).

## Fixed Issues

### CR-01: `'live'` storage factories default to SQLite `:memory:` (PARTIAL fix — requires human verification)

**Files modified:** `itrader/trading_system/live_trading_system.py`
**Commit:** d43a63b (also 92995fe for the IN-01 import cleanup in the same module)
**Applied fix:** When `SYSTEM_DB_URL` is set, the live composition root now builds a
`SqlBackend(SqlSettings(driver=POSTGRESQL_PSYCOPG2, url=SecretStr(_SYSTEM_DB_URL)))` and
**injects** it into `OrderStorageFactory.create('live', backend=backend)`, instead of calling
`create('live')` with no backend (which silently materialized a SQLite `:memory:` store and
discarded the operator's URL — consequence #3 in the review). The dead
`except NotImplementedError` fallback (the factory no longer raises it) was removed. SQL
imports stay lazy inside the `'live'` arm so the backtest import path remains SQLAlchemy-free
(GATE-01 inertness preserved). This directly fixes "the operator's `SYSTEM_DB_URL` value is
read only as a boolean and then discarded" and removes the silent SQLite decay on the
configured-URL path.

**Scope note / why partial (per the CR-01 nuance in the task brief):** The review's
**factory-level** suggestion (raise `ConfigurationError` when `backend is None` so the `'live'`
arm is Postgres-or-raise) was **NOT applied** to the three `storage_factory.py` files. That
change would break the locked Phase-3 contract test
`tests/unit/order/test_order_storage.py::test_create_live_storage_returns_sql_backend`, which
deliberately asserts that `OrderStorageFactory.create('live')` with no backend returns a
`SqlOrderStorage` (the documented Phase-4-injects-the-real-backend seam). The factory default
is the RETAIN-01/02/03 Phase-4 deferred live-wiring concern, not a Phase-3 goal blocker.
Forcing the factory raise here would require the Phase-4 backend-injection wiring (and a
test rewrite) that does not yet exist — so it is deferred rather than half-fixed.

**Requires human verification:** this is live-path logic in a mypy-deferred module
(`trading_system.live_trading_system`, `ignore_errors=true`) that no test constructs; confirm
the injected-backend wiring behaves as intended when Phase 4 lands the shared operational
backend.

### WR-01: Bracket parent deletion can raise `IntegrityError` on Postgres (self-ref FK, no `ON DELETE`)

**Files modified:** `itrader/order_handler/storage/models.py`,
`itrader/storage/migrations/versions/2cbf0bf6b0b6_operational_baseline.py`
**Commit:** 6fd83b2
**Applied fix:** The self-referential `parent_order_id` FK now declares
`ForeignKey("orders.id", ondelete="SET NULL")` in the model and a matching
`ondelete='SET NULL'` on the migration's `ForeignKeyConstraint`. Deleting a bracket parent
now orphans its children cleanly (children's `parent_order_id` set NULL) instead of raising a
Postgres FK-RESTRICT `IntegrityError`. The Postgres migration + round-trip tests pass with the
change applied.

### WR-02: `orders` / `signals` / `order_state_changes` schema allows NULL on logically-required columns

**Files modified:** `itrader/order_handler/storage/models.py`,
`itrader/strategy_handler/storage/models.py`,
`itrader/storage/migrations/versions/2cbf0bf6b0b6_operational_baseline.py`
**Commit:** 47c8a9d
**Applied fix:** Added `nullable=False` to the logically-required columns the entities already
guarantee non-null, keeping model and Alembic baseline in lockstep:
- `orders`: time, type, status, ticker, action, price, quantity, exchange, strategy_id,
  portfolio_id, filled_quantity, created_at, updated_at, modification_count, leverage.
  (The Optional lifecycle/bracket columns — filled_at, cancelled_at, expired_at, expiry_time,
  parent_order_id, rejection_reason, last_modification_time, trail_type, trail_value — stay
  `nullable=True`.)
- `order_state_changes`: to_status, timestamp, reason, triggered_by. (`from_status` and
  `additional_data` are genuinely Optional and stay `nullable=True`.)
- `signals`: strategy_id, ticker, time, action, order_type, exit_fraction, config. (The
  money columns stop_loss/take_profit/quantity/entry_price are genuinely Optional per
  `SignalRecord` and stay `nullable=True`.)

Verified column optionality against the `Order` (`order_handler/order.py`) and `SignalRecord`
(`strategy_handler/signal_record.py`) dataclasses before marking each column. The baseline is
`down_revision=None`, so the migration was hand-edited in place (no chain rewrite); the
SQLite and Postgres alembic-baseline tests both pass.

### WR-03: `get_orders_by_time_range` raises mid-query on naive datetimes

**Files modified:** `itrader/order_handler/storage/sql_storage.py`
**Commit:** 757ddcf
**Applied fix:** Added a `_ensure_utc` boundary helper and applied it to both bounds at the top
of `get_orders_by_time_range`. A naive bound is assumed UTC and stamped tz-aware; an aware
bound is normalized to UTC. This stops the `UtcIsoText` codec `ValueError` (naive-datetime
rejection) from escaping mid-query and makes the lexicographic ISO-text comparison a
consistent UTC compare. (Chose the review's "coerce naive→UTC explicitly" option over the
"raise a typed domain error" option — more forgiving and deterministic.)

### WR-04: `PortfolioStateStorageFactory` raises plain `ValueError`, diverging from the typed-exception convention

**Files modified:** `itrader/portfolio_handler/storage/storage_factory.py`,
`tests/unit/portfolio/test_state_storage.py`
**Commit:** 2fe3598
**Applied fix:** Both raise sites now raise `ConfigurationError` (missing `portfolio_id` on the
`'live'` arm → `ConfigurationError("portfolio_id", None, …)`; unknown environment →
`ConfigurationError("environment", environment, …)`), matching the sibling `OrderStorageFactory`
/ `SignalStorageFactory`. Because `ConfigurationError` is not a `ValueError` subclass, the two
locked tests that asserted `ValueError` were updated to assert `ConfigurationError`
(`test_factory_live_raises`, and `test_factory_unknown_environment_raises_value_error` renamed
to `…_raises_configuration_error`), plus the module docstring. The 5 factory tests pass.

### IN-01: Unused `import json` in `live_trading_system.py`

**Files modified:** `itrader/trading_system/live_trading_system.py`
**Commit:** 92995fe
**Applied fix:** Removed the unused `import json` (the module references no `json` symbol).

### IN-02: Stale docstring in `PortfolioStateStorageFactory`

**Files modified:** `itrader/portfolio_handler/storage/storage_factory.py`
**Commit:** f8a9a9f
**Applied fix:** Replaced the stale "PostgreSQL backend for live trading (deferred to D-sql)"
class-docstring line with an accurate description of the implemented
`SqlPortfolioStateStorage` SQL-spine backend (OPS-02, D-06).

## Skipped Issues

### IN-03: `get_pending_orders(portfolio_id)` keys the nested dict by the argument, not `order.portfolio_id`

**File:** `itrader/order_handler/storage/sql_storage.py:371-375`
**Reason:** skipped — code context differs from review; applying the suggested change would
break SQL/in-memory parity. The review's premise is that the SQL store should key the filtered
branch by `order.portfolio_id` "for parity" with the unfiltered branch. But the in-memory
reference backend (`in_memory_storage.py:186-191`) ALSO keys the filtered branch by the
**argument** `portfolio_id` (and always returns `{portfolio_id: {...}}`, even for an empty
result). The SQL store currently matches that exactly. Re-keying the SQL filtered branch by
`order.portfolio_id` would make the empty-result case return `{}` instead of
`{portfolio_id: {}}`, **diverging** from the in-memory backend the parity discipline pins. The
genuine residual concern (key-type divergence when a non-UUID `IdLike` is passed) is the same
latent issue as IN-04 and should be resolved by tightening the `IdLike` contract across BOTH
backends, not by a SQL-only edit. Deferred to a human decision on the ABC contract.

**Original issue:** The filtered path returns `{portfolio_id: {...}}` using the literal
argument, while the `None` path keys by the rebuilt `order.portfolio_id`; a non-UUID `IdLike`
makes the key type diverge from the unfiltered path.

### IN-04: SQL stores silently no-op for non-UUID `IdLike` order ids

**File:** `itrader/order_handler/storage/sql_storage.py:299-302,350-355,422-425`
**Reason:** skipped — fixing only the SQL store would introduce a SQL/in-memory behavioral
divergence. The review suggests coercing string/int `IdLike` to `uuid.UUID` before querying.
But the in-memory backend (`in_memory_storage.py`) deliberately keys by native `uuid.UUID`
(D-14) and returns the SAME empty/false result for a non-UUID `IdLike` — so the two backends
are currently consistent (both miss). Coercing only the SQL store would make a string-UUID
**hit** in live/SQL while it **misses** in backtest/in-memory, breaking the cross-backend
parity that is the central design discipline of this layer. The faithful fix (coerce in BOTH
backends, or narrow the ABC `IdLike` signature to `uuid.UUID`) is a larger, deliberate contract
change beyond an Info-level defense item; deferred to a human decision rather than a divergent
half-fix.

**Original issue:** `IdLike = Union[str, int, uuid.UUID]`, but `remove_order` /
`get_order_by_id` / `get_order_history` early-return `False`/`None`/`[]` for any non-`uuid.UUID`
— a quiet divergence from the ABC's declared `IdLike` contract.

---

_Fixed: 2026-06-29T16:44:31Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
