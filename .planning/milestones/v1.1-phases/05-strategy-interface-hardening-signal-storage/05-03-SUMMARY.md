---
phase: 05-strategy-interface-hardening-signal-storage
plan: 03
subsystem: strategy
tags: [signal-storage, frozen-dataclass, uuidv7, read-model, sink, byte-exact, golden-master]

# Dependency graph
requires:
  - phase: 05-02
    provides: "Config-object Strategy contract (self.config frozen BaseStrategyConfig), relocated strategies/ package, warmup field"
  - phase: 05-01
    provides: "SignalId NewType + idgen.generate_signal_id(); BaseStrategyConfig frozen pydantic contract"
provides:
  - "Frozen SignalRecord entity with its own UUIDv7 SignalId + config snapshot by reference (SIG-01, D-08/D-10/D-11), no portfolio_id (D-09)"
  - "Pluggable SignalStore seam (ABC + InMemorySignalStore + SignalStorageFactory) mirroring order_handler/storage/ (D-07, SIG-02)"
  - "Per-intent, pre-fan-out signal capture wired into StrategiesHandler.calculate_signals (one record per non-None intent, D-09)"
  - "Composition-root injection of the store + post-run accessors (get_signal_records / get_signal_store) on TradingSystem (D-12)"
affects: [phase-06-strategies, phase-09-e2e, signal-storage]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Sink/read-model storage seam: handler writes records to an injected store during the run; composition root reads them post-run (queue-only contract preserved, D-12)"
    - "Per-intent pre-fan-out capture: one SignalRecord per strategy decision, captured before the per-portfolio SignalEvent fan-out (no portfolio_id on the record)"
    - "Frozen entity id-defaulting via field(default_factory=lambda: SignalId(idgen.generate_signal_id())) — mirrors the Order entity OrderId pattern"

key-files:
  created:
    - itrader/strategy_handler/signal_record.py
    - itrader/strategy_handler/storage/__init__.py
    - itrader/strategy_handler/storage/base.py
    - itrader/strategy_handler/storage/in_memory_storage.py
    - itrader/strategy_handler/storage/storage_factory.py
    - tests/unit/strategy/test_signal_store.py
  modified:
    - itrader/strategy_handler/strategies_handler.py
    - itrader/trading_system/backtest_trading_system.py
    - itrader/trading_system/live_trading_system.py
    - tests/unit/strategy/test_strategy.py
    - tests/integration/test_backtest_oracle.py

key-decisions:
  - "SignalStore ABC placed at strategy_handler/storage/base.py (plan-specified layout) rather than the order_handler convention of order_handler/base.py — the plan explicitly listed storage/base.py as the artifact path."
  - "live_trading_system uses the in-memory signal store (SignalStorageFactory.create('backtest')) as a fallback, mirroring its existing in-memory order-storage fallback — there is no persistent SignalStore backend in v1.1 ('live' raises ConfigurationError)."
  - "SIG-02 golden assertion is a dedicated test that constructs its own TradingSystem over the golden window (the oracle harness invokes scripts/run_backtest.py::main which does not return the system); the byte-exact assertions are left untouched."

requirements-completed: [SIG-01, SIG-02]

# Metrics
duration: ~25min
completed: 2026-06-09
---

# Phase 5 Plan 03: Signal Storage Seam Summary

**Added a typed, frozen `SignalRecord` (own UUIDv7 `SignalId` + config snapshot, no `portfolio_id`) plus a pluggable `SignalStore` seam (ABC + in-memory backend + factory) mirroring the order-storage pattern, wired per-intent pre-fan-out capture into `StrategiesHandler`, injected the store at the composition root with post-run accessors on `TradingSystem`, and proved the golden SMA_MACD run yields a non-empty queryable store — all byte-exact (134 trades / final_equity 46189.87730727451).**

## Performance

- **Duration:** ~25 min
- **Started:** 2026-06-09 (executor session)
- **Completed:** 2026-06-09
- **Tasks:** 3
- **Files modified:** 11 (6 created, 5 modified)

## Accomplishments
- `signal_record.py`: `@dataclass(frozen=True, slots=True, kw_only=True)` `SignalRecord` carrying `signal_id` (defaulted via `idgen.generate_signal_id()`, D-10), `strategy_id`, `ticker`, `time`, `action: Side`, `stop_loss`/`take_profit`, `exit_fraction`, `quantity`, and `config: BaseStrategyConfig` (snapshot by reference, D-11). NO `portfolio_id` (D-09).
- `strategy_handler/storage/` package (all 4-space): `SignalStore(ABC)` (`add`/`get_all`/`by_strategy`/`by_ticker`), `InMemorySignalStore` (flat `{signal_id: record}` dict + list-comp predicate filters), `SignalStorageFactory.create` (`backtest`/`test` -> in-memory; `live`/unknown -> `ConfigurationError`) + `create_in_memory`, barrel re-export.
- `strategies_handler.py`: `signal_store: SignalStore` constructor param stored as `self.signal_store`; per-intent capture inserted AFTER `if intent is None: continue` and BEFORE the `for portfolio_id` fan-out loop (D-09) — one record per non-None intent, side-effect-only (oracle-dark).
- `backtest_trading_system.py`: constructs `SignalStorageFactory.create('backtest')`, injects it into `StrategiesHandler`, holds `self._signal_store`, exposes `get_signal_records()` and `get_signal_store()` post-run accessors (D-12).
- `test_signal_store.py`: 5 tests covering one-record-per-intent regardless of portfolio count, zero records for a None intent, field mirror + config snapshot, and `by_strategy`/`by_ticker` filtering (no cross-strategy bleed, T-05-05).
- SIG-02 golden assertion in `test_backtest_oracle.py`: the golden SMA_MACD run yields >0 queryable records with a serializable config snapshot; byte-exact oracle assertions unchanged.

## Task Commits

Each task was committed atomically:

1. **Task 1: SignalRecord + SignalStore seam (ABC + in-memory + factory + barrel)** - `6d16f6e` (feat)
2. **Task 2 (TDD): per-intent capture + store injection + post-run accessor**
   - RED (failing tests) - `d3ca85f` (test)
   - GREEN (handler wiring + composition root) - `ee3edf1` (feat)
   - REFACTOR: not needed (code clean on first GREEN)
3. **Task 3: golden-run SIG-02 integration assertion** - `8af1569` (test)

## Files Created/Modified
- `itrader/strategy_handler/signal_record.py` - frozen `SignalRecord` entity (SIG-01, D-08/D-10/D-11), no `portfolio_id` (D-09)
- `itrader/strategy_handler/storage/__init__.py` - barrel re-exporting `SignalStore`, `InMemorySignalStore`, `SignalStorageFactory`
- `itrader/strategy_handler/storage/base.py` - `SignalStore` ABC with NumPy-style docstrings
- `itrader/strategy_handler/storage/in_memory_storage.py` - flat-dict predicate-filter backend
- `itrader/strategy_handler/storage/storage_factory.py` - environment-keyed `create` + `create_in_memory`
- `itrader/strategy_handler/strategies_handler.py` - `signal_store` param + per-intent pre-fan-out capture
- `itrader/trading_system/backtest_trading_system.py` - store construction/injection + `get_signal_records`/`get_signal_store` accessors
- `itrader/trading_system/live_trading_system.py` - in-memory signal-store fallback (Rule 3 ripple)
- `tests/unit/strategy/test_signal_store.py` - 5 capture/query tests
- `tests/unit/strategy/test_strategy.py` - `handler_env` fixture passes a store (Rule 3 ripple)
- `tests/integration/test_backtest_oracle.py` - additive SIG-02 golden-run assertion

## Decisions Made
- **SignalStore ABC location:** placed at `strategy_handler/storage/base.py` per the plan's explicit artifact path, not the order-handler convention of `order_handler/base.py`. The plan's `read_first`/`interfaces` referenced the order pattern for style density, but its `<files>` and `artifacts` pinned `storage/base.py`.
- **live_trading_system fallback:** wired `SignalStorageFactory.create('backtest')` (in-memory) so the deferred live module still constructs — there is no persistent SignalStore backend in v1.1 (factory rejects `'live'` loudly). This mirrors the existing in-memory order-storage fallback in the same `__init__`.
- **SIG-02 golden assertion as a dedicated test:** the oracle harness invokes `scripts/run_backtest.py::main()`, which writes the frozen golden CSVs but does not return the `TradingSystem`. To read the post-run accessor on a real golden SMA_MACD run, the SIG-02 test constructs its own `TradingSystem` over the pinned 2018->2026 window with the identical golden config. The byte-exact oracle tests are untouched (capturing a sink record is oracle-dark, HARD-04).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Migrated `live_trading_system.py` StrategiesHandler construction**
- **Found during:** Task 2 (GREEN — the new required `signal_store` param)
- **Issue:** `live_trading_system.py` constructed `StrategiesHandler(self.global_queue, self.feed)` — the new required `signal_store` param would raise `TypeError` on import/construction of the live system.
- **Fix:** Added the `SignalStorageFactory` import and wired `SignalStorageFactory.create('backtest')` (in-memory) into the construction, mirroring the module's existing in-memory order-storage fallback. Not in the plan's file list, but a direct blocking ripple of the Task 2 constructor change.
- **Files modified:** itrader/trading_system/live_trading_system.py
- **Verification:** `mypy --strict itrader` clean (the live module is a deferred-typing subsystem but still imports/constructs); full suite 748 passed.
- **Committed in:** `ee3edf1` (Task 2 GREEN commit)

**2. [Rule 3 - Blocking] Updated `test_strategy.py` handler_env fixture for the new param**
- **Found during:** Task 2 (GREEN)
- **Issue:** `tests/unit/strategy/test_strategy.py::handler_env` constructed `StrategiesHandler(q, _StubFeed(...))` — the new required `signal_store` param broke the existing fan-out tests.
- **Fix:** Passed an `InMemorySignalStore()` to the fixture and added the import. The existing fan-out assertions are unchanged (capture is additive/side-effect-only).
- **Files modified:** tests/unit/strategy/test_strategy.py
- **Verification:** test_strategy.py 9 tests pass; full suite 748 passed.
- **Committed in:** `ee3edf1` (Task 2 GREEN commit)

---

**Total deviations:** 2 auto-fixed (both Rule 3 blocking ripples of the required-param constructor change). No architectural deviations, no scope creep — both changes are direct consequences of the plan's own constructor change.

## Issues Encountered
- The oracle harness (`test_backtest_oracle.py`) runs the golden via `scripts/run_backtest.py::main()`, which does not return the `TradingSystem` instance. Resolved by adding a dedicated SIG-02 test that constructs and runs an equivalent golden-config `TradingSystem` directly, holding the reference so the post-run accessor can be read — without touching the byte-exact harness.

## User Setup Required
None - no external service configuration required, no new packages.

## Known Stubs
None — the signal-storage feature is fully wired: real `SignalRecord`s are captured during the run and read post-run via the `TradingSystem` accessors. The `'live'` persistent backend is intentionally deferred (factory raises `ConfigurationError`); v1.1 ships the in-memory backend only, which is the complete and exercised path.

## Next Phase Readiness
- The pluggable `SignalStore` seam is in place and queryable; Phase 6-9 E2E assertions can read captured signals via `TradingSystem.get_signal_records()` / `get_signal_store()`.
- A persistent ('live') SignalStore backend is the only deferred extension — the factory and ABC are ready for it (mirror `order_handler/storage/postgresql_storage.py`).

## Self-Check: PASSED

- Created files verified on disk (signal_record.py, storage/{__init__,base,in_memory_storage,storage_factory}.py, test_signal_store.py).
- Task commits verified in git log: 6d16f6e, d3ca85f, ee3edf1, 8af1569.
- Oracle byte-exact (134 / 46189.87730727451); full suite 748 passed; mypy --strict clean.

---
*Phase: 05-strategy-interface-hardening-signal-storage*
*Completed: 2026-06-09*
