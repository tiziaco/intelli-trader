---
phase: 03-operational-sql-backends-2-store-layer
fixed_at: 2026-06-29T16:55:00Z
review_path: .planning/phases/03-operational-sql-backends-2-store-layer/03-REVIEW.md
iteration: 2
findings_in_scope: 11
fixed: 8
skipped: 3
status: partial
---

# Phase 3: Code Review Fix Report (cumulative — iterations 1–2)

**Fixed at:** 2026-06-29T16:55:00Z
**Source review:** .planning/phases/03-operational-sql-backends-2-store-layer/03-REVIEW.md
**Iteration:** 2

**Cumulative summary (both iterations):**
- Findings in scope: 11 (iter-1: 9; iter-2 re-review: 2)
- Fixed: 8
- Skipped: 3 (WR-01 iter-2 deferred to Phase 4; IN-03, IN-04 deferred by parity discipline)

> **ID-numbering note:** each review re-numbers its findings, so IDs collide across
> iterations. Iteration-1 `IN-01` (unused `import json`) is a *different* finding from
> iteration-2 `IN-01` (`from_status` truthiness guard). Entries below are labelled by
> iteration to disambiguate.

---

## Iteration 2 (post-fix re-review)

The iteration-2 re-review confirmed **no regressions** from the 7 iteration-1 fixes and
surfaced 2 findings: `WR-01` (the factory-default remainder of CR-01) and `IN-01`
(`from_status` truthiness codec). One fixed, one deferred.

**Verification gates (post iter-2 fix, full repo, run inside the isolated worktree with
`PYTHONPATH="$PWD"` to defeat editable-install shadowing):**
- `poetry run mypy --strict itrader` → **Success: no issues found in 184 source files**
- `poetry run pytest tests -q` → **1440 passed in 14.44s**

### Fixed (iteration 2)

#### IN-01 (iter-2): `get_order_history` used truthiness instead of `is not None` for `from_status`

**Files modified:** `itrader/order_handler/storage/sql_storage.py`
**Commit:** 5aec8fb
**Applied fix:** Changed `OrderStatus(from_value).name if from_value else None` →
`... if from_value is not None else None` at line 447, matching the sibling
`_load_state_changes` codec (line 217) which already uses the explicit `is not None`
guard. Currently equivalent (all `OrderStatus.value` are non-empty strings) but removes the
latent fragility where a present-but-falsy status (e.g. a `""`-valued enum) would be
misreported as `None`. Verified: Python `ast.parse` syntax-clean, mypy strict clean, full
suite 1440 passed.

### Skipped / deferred (iteration 2)

#### WR-01 (iter-2): `'live'` factory arm defaults to a money-decaying SQLite backend (CR-01 remainder)

**File:** `itrader/order_handler/storage/storage_factory.py:60`
**Also:** `itrader/portfolio_handler/storage/storage_factory.py:89-92`,
`itrader/strategy_handler/storage/storage_factory.py:77-78`
**Reason:** **skipped — deferred to Phase 4 live write-through wiring.** This is the
*factory-default* half of CR-01. The review's suggested fix (make the `'live'` arm
fail-closed — require an injected `backend`, or default to the Postgres driver so the
credential validator fires — instead of `SqlBackend(SqlSettings.default())` = SQLite
`:memory:`) **cannot be applied in Phase 3** because it breaks the LOCKED Phase-3 contract
test `tests/unit/order/test_order_storage.py::test_create_live_storage_returns_sql_backend`
(and the sibling live-arm contract tests), which deliberately assert that `create('live')`
with no backend returns a `SqlOrderStorage` — the documented "Phase-4-injects-the-real-backend"
seam. The iteration-1 fixer hardened the actual call site (`live_trading_system`:
Postgres-or-raise, no SQLite fallback) and BOTH the iteration-1 fixer and the phase verifier
explicitly deferred the factory-level Postgres-or-raise to Phase 4 (RETAIN-01/02/03). Forcing
it here would require the not-yet-existing Phase-4 backend-injection wiring plus a locked-test
rewrite. Per the no-force-a-locked-test rule, deferred — not half-fixed.

**Original issue:** All three `'live'` arms build `SqlBackend(SqlSettings.default())` when no
`backend` is injected; `SqlSettings.default()` pins `driver=SQLITE_PYSQLITE,
database=":memory:"`, on which `Numeric` money columns decay to float storage — the exact
defect CR-01 documented. The call site is already hardened; only the factory default remains.

---

## Iteration 1 (initial fix pass)

**Summary (iteration 1):**
- Findings in scope: 9 (1 critical, 4 warning, 4 info — fix_scope: all)
- Fixed: 7
- Skipped: 2

**Verification gates (post iter-1 fix, full repo):**
- `poetry run mypy --strict itrader` → **Success: no issues found in 206 source files**
- `poetry run pytest tests -q` → **1440 passed**
- `poetry run pytest tests/integration/storage tests/unit/order/test_order_storage.py` →
  **63 passed** (the Postgres round-trip arm ran — Docker was available — so the WR-01
  `ON DELETE SET NULL` and WR-02 `NOT NULL` migration changes were exercised against real
  Postgres, not just the SQLite `create_all` path).

### Fixed Issues (iteration 1)

#### CR-01 (iter-1): `'live'` storage factories default to SQLite `:memory:` (PARTIAL fix — requires human verification)

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
**Iteration-2 status:** the iteration-2 re-review re-surfaced this factory-default half as
`WR-01`; it remains deferred to Phase 4 (see above).

**Requires human verification:** this is live-path logic in a mypy-deferred module
(`trading_system.live_trading_system`, `ignore_errors=true`) that no test constructs; confirm
the injected-backend wiring behaves as intended when Phase 4 lands the shared operational
backend.

#### WR-01 (iter-1): Bracket parent deletion can raise `IntegrityError` on Postgres (self-ref FK, no `ON DELETE`)

**Files modified:** `itrader/order_handler/storage/models.py`,
`itrader/storage/migrations/versions/2cbf0bf6b0b6_operational_baseline.py`
**Commit:** 6fd83b2
**Applied fix:** The self-referential `parent_order_id` FK now declares
`ForeignKey("orders.id", ondelete="SET NULL")` in the model and a matching
`ondelete='SET NULL'` on the migration's `ForeignKeyConstraint`. Deleting a bracket parent
now orphans its children cleanly (children's `parent_order_id` set NULL) instead of raising a
Postgres FK-RESTRICT `IntegrityError`. The Postgres migration + round-trip tests pass with the
change applied.

#### WR-02 (iter-1): `orders` / `signals` / `order_state_changes` schema allows NULL on logically-required columns

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

#### WR-03 (iter-1): `get_orders_by_time_range` raises mid-query on naive datetimes

**Files modified:** `itrader/order_handler/storage/sql_storage.py`
**Commit:** 757ddcf
**Applied fix:** Added a `_ensure_utc` boundary helper and applied it to both bounds at the top
of `get_orders_by_time_range`. A naive bound is assumed UTC and stamped tz-aware; an aware
bound is normalized to UTC. This stops the `UtcIsoText` codec `ValueError` (naive-datetime
rejection) from escaping mid-query and makes the lexicographic ISO-text comparison a
consistent UTC compare. (Chose the review's "coerce naive→UTC explicitly" option over the
"raise a typed domain error" option — more forgiving and deterministic.)

#### WR-04 (iter-1): `PortfolioStateStorageFactory` raises plain `ValueError`, diverging from the typed-exception convention

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

#### IN-01 (iter-1): Unused `import json` in `live_trading_system.py`

**Files modified:** `itrader/trading_system/live_trading_system.py`
**Commit:** 92995fe
**Applied fix:** Removed the unused `import json` (the module references no `json` symbol).

#### IN-02 (iter-1): Stale docstring in `PortfolioStateStorageFactory`

**Files modified:** `itrader/portfolio_handler/storage/storage_factory.py`
**Commit:** f8a9a9f
**Applied fix:** Replaced the stale "PostgreSQL backend for live trading (deferred to D-sql)"
class-docstring line with an accurate description of the implemented
`SqlPortfolioStateStorage` SQL-spine backend (OPS-02, D-06).

### Skipped Issues (iteration 1)

#### IN-03 (iter-1): `get_pending_orders(portfolio_id)` keys the nested dict by the argument, not `order.portfolio_id`

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
**Iteration-2 status:** the re-review confirmed this skip rationale holds (parity contract); not
re-flagged as actionable.

**Original issue:** The filtered path returns `{portfolio_id: {...}}` using the literal
argument, while the `None` path keys by the rebuilt `order.portfolio_id`; a non-UUID `IdLike`
makes the key type diverge from the unfiltered path.

#### IN-04 (iter-1): SQL stores silently no-op for non-UUID `IdLike` order ids

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
**Iteration-2 status:** the re-review confirmed this skip rationale holds (parity contract); not
re-flagged as actionable.

**Original issue:** `IdLike = Union[str, int, uuid.UUID]`, but `remove_order` /
`get_order_by_id` / `get_order_history` early-return `False`/`None`/`[]` for any non-`uuid.UUID`
— a quiet divergence from the ABC's declared `IdLike` contract.

---

_Fixed: 2026-06-29T16:55:00Z (iteration 2); 2026-06-29T16:44:31Z (iteration 1)_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 2_
