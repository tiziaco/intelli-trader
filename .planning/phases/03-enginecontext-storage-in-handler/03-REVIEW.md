---
phase: 03-enginecontext-storage-in-handler
reviewed: 2026-07-09T00:00:00Z
depth: standard
files_reviewed: 11
files_reviewed_list:
  - itrader/order_handler/storage/storage_factory.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/portfolio_handler/portfolio.py
  - itrader/portfolio_handler/storage/storage_factory.py
  - itrader/storage/__init__.py
  - itrader/storage/engine.py
  - itrader/storage/migrations/env.py
  - itrader/strategy_handler/storage/storage_factory.py
  - itrader/trading_system/backtest_trading_system.py
  - itrader/trading_system/compose.py
  - itrader/trading_system/engine_context.py
findings:
  critical: 0
  warning: 0
  info: 1
  total: 1
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-07-09
**Depth:** standard
**Files Reviewed:** 11
**Status:** issues_found (1 INFO only — no BLOCKER, no WARNING)

## Summary

This phase is a behavior-preserving refactor with two riders: (1) CTX-04 hard-rename
of the shared SQL spine class `SqlBackend` → `SqlEngine`, moving `storage/backend.py`
to `storage/engine.py` and sweeping every importer and kwarg to `sql_engine=` /
`_sql_engine`; (2) the D-03 collapse of the redundant `signal_store` surface on the
`Engine` holder so post-run accessors read through
`engine.strategies_handler.signal_store`.

I reviewed this adversarially with the specific rename failure modes in mind
(incompletely swept references, wrong import paths, a broken Alembic metadata import,
a D-03 accessor that no longer returns the identical store instance, and a
GATE-01 inertness break). I verified the claims empirically rather than by inspection
alone. All checks pass:

- **Reference sweep is complete.** No `SqlBackend`, `storage.backend`, or
  `storage/backend` module-path references remain anywhere in `itrader/` or `tests/`
  (the only surviving "backend" tokens are prose describing the pluggable-storage-backend
  pattern, unrelated to the renamed class). The old `storage/backend.py` file is gone;
  `storage/engine.py` exists.
- **Import-inertness preserved (verified empirically).** Importing the full backtest
  path (`itrader`, `backtest_trading_system`, `compose`, `engine_context`) loads **0**
  `sqlalchemy` modules. The `EngineContext.sql_engine` annotation uses a
  `TYPE_CHECKING`-only import of `SqlEngine` plus a string forward-ref
  (`Optional["SqlEngine"]`), so no eager SQLAlchemy import leaks onto the hot path.
- **Alembic `env.py` metadata import is correct.** `from itrader.storage.engine import
  NAMING_CONVENTION` resolves; the three `build_*_tables` registrars still build on a
  bare `MetaData` (no transient engine leaked at import).
- **D-03 accessor returns the identical store instance.** `StrategiesHandler.signal_store`
  is assigned once in `__init__` and never reassigned; the collapsed accessors
  (`get_signal_records`, `get_signal_store`) read it live off the owning handler, so
  they return the same object the former re-surfaced holder copy pointed at. The
  removed `Engine.signal_store` field has no remaining readers on the backtest path
  (`live_trading_system.py` keeps its own independent `self._signal_store`, untouched
  by the collapse).
- **Behavior is byte-exact.** `tests/unit/storage/`, `tests/integration/test_backtest_oracle.py`,
  and `tests/integration/test_okx_inertness.py` all pass (28 passed). The live 'live'
  arms of all three storage factories and the two direct-injection sites in
  `live_trading_system.py` were swept to `sql_engine=` consistently.
- **Indentation is consistent.** `storage/` (4 spaces), `trading_system/` per-file
  (`engine_context.py`/`compose.py`/`backtest_trading_system.py` TABS), and the
  portfolio handler modules (4 spaces) each match their file convention — no mixed
  tab/space diff was introduced.

## Info

### IN-01: SQL leaf-store constructors retained `backend` as the parameter name after the class rename

**File:** `itrader/order_handler/storage/sql_storage.py` (and the 5 sibling
`SqlEngine`-consuming constructors: `portfolio_handler/storage/sql_storage.py`,
`strategy_handler/storage/sql_storage.py`, `results/sql_storage.py`,
`price_handler/store/sql_store.py`, `storage/halt_record_store.py`)
**Issue:** The phase swept the vocabulary to `sql_engine` at the factory and handler
seams (`sql_engine=` kwargs, `_sql_engine` attributes), but the six leaf-store
constructors kept `def __init__(self, backend: SqlEngine)` — only the *type* was
renamed, not the *parameter name*. This is a cosmetic inconsistency: the identifier
`backend` now names a value of type `SqlEngine`. It is **not a bug** — every call site
invokes these constructors positionally (`SqlOrderStorage(resolved)`,
`SqlPortfolioStateStorage(resolved, portfolio_id)`, `SqlSignalStorage(sql_engine)`,
`SqlResultsStore(backend, ...)`, `SqlHandler(backend)`), so no keyword mismatch can
occur, and `self.engine = backend.engine` / `backend.metadata` access the correct
attributes on `SqlEngine`.
**Fix:** Optionally rename the parameter to `sql_engine` in these six constructors for
full vocabulary consistency with the rest of the sweep, or leave as-is (harmless).
Not required for correctness. (Note: `PortfolioHandler.__init__` also keeps its
`sql_engine` param typed `Optional[Any]` rather than the concrete
`Optional["SqlEngine"]` that `Portfolio.__init__` uses via `TYPE_CHECKING` — a
pre-existing, deliberate looseness noted in its docstring, not introduced by this phase.)

---

_Reviewed: 2026-07-09_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
