# Roadmap: iTrader — Backtest-Correctness Refactor

## Overview

This is a brownfield structural refactor that takes iTrader from a backtest path that does not
import today to an engine whose `SMA_MACD` results on the golden BTCUSD CSV are correct,
deterministic, and externally cross-validated. The journey is governed by a two-layer golden-master
oracle: Phase 1 (M1) makes the engine run and captures the reference output (the oracle cannot exist
until the engine runs); the foundations, event/dispatch, and money phases (M2–M4) are
behavior-preserving against that oracle; and only the validity phases (M5) are permitted to change
results, closing with cross-validation against `backtesting.py` and `backtrader` and a frozen final
numerical reference. The numerical oracle re-baselines at exactly two points — end of M2 (float→Decimal
shift) and end of M5 (look-ahead/fill-realism fixes). Milestone identity is preserved in phase names
(M2a/M2b, M5a/M5b/M5c) so each golden-master gate stays attributable to a milestone boundary.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: M1 — Ignition + Lock the Oracle** - Make the backtest run end-to-end and capture/commit the reference output (completed 2026-06-04)
- [x] **Phase 2: M2a — Identity, Money & Determinism** - UUIDv7 IDs, Decimal money, mypy-strict frozen DTOs, real ABCs, seeded/clocked determinism (all 8 plans executed incl. gap-closure 02-08; re-verification PASS 4/4 SC 2026-06-04; numeric oracle re-freeze deferred to post-M2 per DEF-02-08-A) (completed 2026-06-04)
- [x] **Phase 3: M2b — Config, Types, Storage Seam & Oracle Re-Freeze** - Pydantic config, centralized types, portfolio storage seam, time_parser final, dead-code purge, pytest conversion, re-freeze numerical oracle (completed 2026-06-05)
- [x] **Phase 4: M3 — Event & Dispatch Core** - Immutable events with linkage IDs, race-free dispatch registry, unified domain errors/logging (completed 2026-06-05)
- [ ] **Phase 5: M4 — Money & Transaction Correctness** - Cash through CashManager, atomic transactions, order facade layering, frozen execution DTOs
- [ ] **Phase 6: M5a — Backtest Validity, Fills & Data Pipeline** - Look-ahead/fill realism, Bar struct, precomputed frames, fee/slippage, price-handler Provider/Store/Feed split
- [ ] **Phase 7: M5b — Sizing Policy, Metrics, Universe & Coverage** - Complete strategy-declared sizing, correct reporting/metrics, universe stub, strategy/data/reporting tests
- [ ] **Phase 8: M5c — Cross-Validation & Final Oracle** - Cross-validate vs backtesting.py + backtrader; freeze the final numerical reference

## Phase Details

### Phase 1: M1 — Ignition + Lock the Oracle
**Goal**: Make the backtest path import and run `SMA_MACD` end-to-end on the golden CSV producing real trades, then capture and commit the reference output (the behavioral + numerical oracle) and stand up the test skeleton. The only milestone built without an oracle — kept ruthlessly minimal.
**Depends on**: Nothing (first phase)
**Requirements**: M1-01, M1-02, M1-03, M1-04, M1-05, M1-06, M1-07, M1-08, M1-09, M1-10
**Success Criteria** (what must be TRUE):
  1. `make backtest` imports and runs the full PING→BAR→SIGNAL→ORDER→FILL loop without error (Critical #34 ignition resolved; `record_metrics`, `to_timedelta`, `SMA_MACD` indexing fixed)
  2. Orders carry real non-zero quantities via minimal sizing placed in the order/risk seam (no `quantity=0` reaching fills)
  3. `SMA_MACD` produces a non-trivial trade log + equity curve on `data/BTCUSD_1d_ohlcv_2018_2026.csv`, and that reference output (trade log with entry/exit time + side, equity curve, final cash/metrics) is **captured and committed** as the behavioral + numerical oracle
  4. A run-path smoke test (import→construct→run) and a run-path integration test exist, the 8 declared pytest markers are applied, and the 274 existing component tests stay green
**Plans**: 5 plans
  - [x] 01-01-PLAN.md — Test skeleton (conftest + auto-marking) + import ignition (config re-export, TIMEZONE, to_timedelta)
  - [x] 01-02-PLAN.md — CSV/offline price feed inside PriceHandler (exact CCXT frame shape, no SQL/CCXT)
  - [x] 01-03-PLAN.md — Loop/strategy/sizing fixes (SMA_MACD .iloc/fillna, record_metrics per-Portfolio, fraction-of-cash sizing seam)
  - [x] 01-04-PLAN.md — Run script + make backtest + deterministic oracle serialization; smoke test green
  - [x] 01-05-PLAN.md — Freeze oracle to test/golden/ (human-blessed) + run-path integration test; full suite green

### Phase 2: M2a — Identity, Money & Determinism
**Goal**: Replace the overflow-prone integer ID scheme with UUIDv7, make money Decimal end-to-end, achieve `mypy --strict` cleanliness with frozen/typed DTOs and real ABCs, and make runs deterministic via seeded RNG and an injected clock — the structural foundations the rest of the program builds on.
**Depends on**: Phase 1
**Requirements**: M2-01, M2-02, M2-03, M2-04, M2-05
**Success Criteria** (what must be TRUE):
  1. A single UUIDv7 scheme via `uuid-utils` replaces the integer `id_generator`; IDs are stored as native UUIDs with type no longer encoded in the value (Critical #10)
  2. Money is `Decimal` end-to-end (prices, quantities, cash, commissions, PnL) with no `float` round-trips and a centralized quantization policy
  3. `mypy --strict` is clean across the package; hot-path DTOs/events are `frozen=True`/`slots=True` with `NewType` ID aliases; the eight Py2 `__metaclass__` bases are real ABCs/Protocols with non-conforming subclasses fixed
  4. Backtests are deterministic — RNG seeded behind an injected `Random`, clock injected (no local `datetime.now()`), flat global order index by id
**Plans**: 8 plans (7 execute + 1 gap-closure)
  - [x] 02-01-PLAN.md — Install deps (uuid-utils, mypy) + mypy --strict gate + make typecheck + Wave 0 test scaffolds
  - [x] 02-02-PLAN.md — New core modules: ids.py (NewType aliases), money.py (Decimal quantization), clock.py (injectable Clock)
  - [x] 02-03-PLAN.md — UUIDv7 identity infra: idgen facade + native-UUID storage/flat index + UUID-typed exceptions
  - [x] 02-04-PLAN.md — Entity typing: UUID id fields + Decimal money; remove the transaction_manager float cash round-trip
  - [x] 02-05-PLAN.md — Convert 11 dead __metaclass__ bases to real ABCs/Protocols + SimulatedExchange conformance
  - [x] 02-06-PLAN.md — Determinism: seeded RNG injected into slippage/exchange + injected BacktestClock on the engine path
  - [x] 02-07-PLAN.md — mypy --strict clean pass + frozen/slots events + D-15 oracle tolerance split + phase gate
  - [x] 02-08-PLAN.md — Gap-closure: clock.now() raise guard (python -O safe) + honest clock docstring + remove float seams (WR-01/02/03/05) + Decimal-precision cash ledger

### Phase 3: M2b — Config, Types, Storage Seam & Oracle Re-Freeze
**Goal**: Collapse the over-engineered config package to Pydantic models, centralize scattered types, route portfolio-handler state through an in-memory storage seam, finalize `time_parser` timing correctness, delete dead modules, complete the bulk pytest conversion, and re-freeze the numerical oracle after the Decimal shift while confirming the behavioral oracle is unchanged. This closes the `#34` and `#36` spans started in M1.
**Depends on**: Phase 2
**Requirements**: M2-06, M2-07, M2-08, M2-09, M2-10, M2-11, M2-12, M2-13
**Success Criteria** (what must be TRUE):
  1. The `config/` package collapses to Pydantic v2 models + `pydantic-settings` (one model round-trips backtest-dict and live-JSONB forms; no working secret defaults), completing the `#34`/TD2 dual-config span; shared enums/entities are centralized and buggy string→enum maps replaced
  2. Portfolio-handler manager state routes through an in-memory storage seam mirroring the order-storage pattern; order audit and transaction timestamps are event-derived/deterministic and `modify_order` routes through the validated path
  3. `time_parser` timing is correct (anchoring fixed for non-UTC/DST/week-month; `to_timedelta` case-insensitive with week/month), completing the `#36` span; dead modules (`legacy_config`, `outils/profiling`, `outils/strategy`, orphaned `screener_event_handler` `EventHandler`) are deleted; the bulk `unittest`→pytest conversion lands
  4. **Golden-master gate:** the numerical oracle is re-frozen after the Decimal precision shift and the behavioral oracle (trade timing) is verified unchanged
**Plans**: 9 plans (8 waves; oracle re-freeze isolated as the terminal wave)
  - [x] 03-01-PLAN.md — Wave 0: capture D-17 inertness reference FIRST + poetry add pydantic/pydantic-settings + 5 characterization test stubs
  - [x] 03-02-PLAN.md — Dead-module purge (M2-11): delete legacy_config, outils/profiling, outils/strategy, orphaned screener_event_handler EventHandler
  - [x] 03-03-PLAN.md — Enum centralization (M2-07): relocate FillStatus + 4 manager enums to core/enums as class enums with _missing_; replace string→enum maps
  - [x] 03-04-PLAN.md — time_parser finalization (M2-10): epoch-aligned _aligned seam + case-insensitive to_timedelta (week/month) + delete dead helpers
  - [x] 03-05-PLAN.md — Config collapse (M2-06): Pydantic v2 models + Settings fail-loud secrets + core/constants.py; absorb+delete flat config shadow; rewire consumers
  - [x] 03-06-PLAN.md — Portfolio subdomain reorg (M2-08, D-11): pure git mv into position/transaction/cash/metrics packages
  - [x] 03-07-PLAN.md — Storage seam + timestamp determinism (M2-08/M2-09): unified PortfolioStateStorage seam + event-derived order timestamps + modify_order validated path
  - [x] 03-08-PLAN.md — pytest restructure + conversion (M2-12): test/→tests/ type-split + folder-derived markers + convert all unittest.TestCase
  - [x] 03-09-PLAN.md — Oracle re-freeze (M2-13), TERMINAL: D-17 inertness gate (blocking owner sign-off) → D-16 byte-exact re-freeze, tolerance/xfail removed; D-18 behavioral identity unchanged

### Phase 4: M3 — Event & Dispatch Core
**Goal**: Make events immutable facts with linkage IDs and `event_id`, replace the racy/fused dispatch loop with a race-free routing registry, and apply the domain-exception hierarchy and unified logging consistently — all behavior-preserving against the post-M2 oracle.
**Depends on**: Phase 3
**Requirements**: M3-01, M3-02, M3-03, M3-04
**Success Criteria** (what must be TRUE):
  1. Events are `frozen=True` facts carrying a unique `event_id` + `created_at`, required (non-`Optional`) linkage IDs, enum-typed `action`/`order_type`, `type` as a real field, and a dedicated error `EventType`
  2. The dispatch loop is race-free — `get_nowait()`+`queue.Empty` replaces the `empty()`/`get(False)` TOCTOU; routing is separated from ordering via a `dict[EventType, list[Callable]]` registry; unknown types raise `NotImplementedError`
  3. The domain-exception hierarchy is used consistently (no bare `ValueError`/`NotImplemented`/swallowed `None`), logging is unified, and portfolio exceptions are constructed with correct-typed arguments
  4. **Golden-master gate:** the behavioral oracle is unchanged and the post-M2 numerical oracle is reproduced exactly after the event/dispatch refactor
**Plans**: 8 plans (7 waves; mostly sequential by design — event.py is the shared choke point and the byte-exact oracle gates every commit; exceptions runs parallel with dispatch in wave 6)
  - [x] 04-01-PLAN.md — Foundations: class-based EventType (TIME/ERROR) + Side in core/enums, FillId/EventId aliases, TimeEvent/TimeGenerator rename (D-08)
  - [x] 04-02-PLAN.md — Order pipeline de-mutation: drop signal.verified + quantity-0 sentinel, Order entity as pipeline state with audited REJECTED route, create-all-then-emit brackets (D-03/D-10/D-11/D-13)
  - [x] 04-03-PLAN.md — Execution de-mutation: construct-complete FillEvent with fill_id/strategy_id, MatchingEngine replace-in-book (Pattern 5, D-12)
  - [x] 04-04-PLAN.md — Frozen events package build: Event base (event_id/created_at), all concrete events, ErrorEvent hierarchy (D-01/D-02/D-06/D-09) + inverted immutability tests
  - [x] 04-05-PLAN.md — Big-bang cutover: repoint ~31 itrader + 20 test files, kw-only pass (~79 sites), Side/OrderType typing, required IDs, delete event.py
  - [x] 04-06-PLAN.md — Race-free dispatch registry: get_nowait drain, route-dict literal, ERROR consumer, _on_handler_error seam (D-14..D-17) + D-23 tests
  - [x] 04-07-PLAN.md — Exceptions: ITraderError rename, delete execution.py/ConcurrencyError, KB24 arg fixes, new order/data modules (D-18/D-19)
  - [x] 04-08-PLAN.md — Logging: env-driven log_level/json_logs (no Settings() at import), guarded handler init, structlog swaps, DEBUG demotions (D-20/D-21)

### Phase 5: M4 — Money & Transaction Correctness
**Goal**: Route every trade's cash through `CashManager` (Critical #22), make transaction processing atomic with rollback, enforce one-directional order-handler layering with O(1) lookup and a narrow read-model Protocol, and freeze the execution result DTOs — value-preserving against the oracle.
**Depends on**: Phase 4
**Requirements**: M4-01, M4-02, M4-03, M4-04, M4-05, M4-06, M4-07
**Success Criteria** (what must be TRUE):
  1. Every trade routes cash through `CashManager` with no `portfolio.cash += float(...)` setter bypass; ledger/reservations/audit are live (Critical #22)
  2. Transaction processing is atomic — funds checked before position mutation, rollback on failure, one coherent error/return contract (no unreachable `return False` behind a re-raise)
  3. Order-handler layering is one-directional facade→manager→storage with the read path through `OrderManager`, an O(1) `{order_id: order}` index, cross-handler reads via a narrow `PortfolioReadModel` Protocol, and resolved intra-portfolio coupling; execution `result_objects`/`base` DTOs are frozen, Decimal-typed, real-ABC, and carry `fill_id`
  4. **Golden-master gate:** value-preserving against the oracle — any numeric difference is explained and the behavioral oracle is unchanged
**Plans**: 7 plans (5 waves; lock-deletion and DTO-cleanup run parallel to their wave peers; D-22 retype isolated as the terminal oracle-risk wave)
  - [x] 05-01-PLAN.md — Order layering + flat storage: facade→manager→storage one-directional, nested dicts deleted (M4-03, M4-06)
  - [x] 05-02-PLAN.md — Lock-theater deletion + documented single-writer contract; readerwriterlock removed (M4-05)
  - [x] 05-03-PLAN.md — PortfolioReadModel Protocol + frozen PositionView + per-reference reservation API + consumer retypes (M4-04)
  - [x] 05-04-PLAN.md — Execution DTO cleanup: ExecutionResult deleted, real ABC, frozen/Decimal survivors (M4-07 structural)
  - [ ] 05-05-PLAN.md — Settlement atomicity: validate-first reorder, saga deletion, raise/None contract, live deterministic ledger (M4-02)
  - [ ] 05-06-PLAN.md — Reservation lifecycle wiring: check-and-reserve at admission, terminal release, D-14 inertness trace (M4-01)
  - [ ] 05-07-PLAN.md — D-22 event-money Decimal retype + M4-08 value-preservation phase gate (M4-07, M4-08)

### Phase 6: M5a — Backtest Validity, Fills & Data Pipeline
**Goal**: Fix the correctness of the backtest itself — remove resampling look-ahead, make fills realistic, replace the per-tick pandas Series payload with an immutable `Bar` struct, precompute resampled frames, correct fee/slippage, and split the price handler into Provider/Store/Feed seams with an offline-deterministic read path. This is where results are first allowed to change.
**Depends on**: Phase 5
**Requirements**: M5-01, M5-02, M5-03, M5-04, M5-05
**Success Criteria** (what must be TRUE):
  1. Backtest validity is fixed — resampling look-ahead removed, limit fills no longer slip past the limit, and bar-timing is documented and consistent between same/other-timeframe branches
  2. The per-tick market-data payload is an immutable `Bar` struct (no pandas Series, no `hasattr`/`get_last_close` type-branching), and resampled frames are precomputed once per (ticker, timeframe) and sliced per tick (no `resample` in the hot loop)
  3. Fee/slippage models are correct (maker fees live, tiered model fixed, slippage not applied to limit fills, connect latency `time.sleep` gated/removed)
  4. The price handler splits into Provider/Store/Feed seams with an offline-vs-runtime lifecycle: the run path is read-only and errors loudly on missing data (no mid-run network fetch), bare `except:`→`None` and `to_megaframe` tz/key bugs fixed, strategies use the resampled-bars API not `price_handler.prices`
**Plans**: TBD

### Phase 7: M5b — Sizing Policy, Metrics, Universe & Coverage
**Goal**: Complete the strategy-declared sizing policy started minimally in M1 (closing the `#24`/`#31`/KB11 span), make reporting/metrics correct, collapse the universe to a documented stub, and add strategy/data/reporting/universe test coverage.
**Depends on**: Phase 6
**Requirements**: M5-06, M5-07, M5-08, M5-09
**Success Criteria** (what must be TRUE):
  1. Strategy-declared sizing **policy** is fully resolved per-portfolio in the order/risk layer, completing the M1 minimal seam — `VariableSizer` finished, `RiskManager.check_cash` covers position increases, `calculate_signal` contract enforced (closes the `#24`/`#31`/KB11 span)
  2. Reporting/metrics are correct — drawdown math, pandas-2/plotly API breakage, `is np.nan` identity bug, and rolling-stats stub resolved, dead `EngineLogger` removed, computation split from presentation
  3. `universe/` collapses to a thin documented symbol-set stub (false "dynamic"/redundant copies removed)
  4. Strategy/data/reporting/universe paths gain test coverage (CSV price store, reporting/statistics, universe)
**Plans**: TBD

### Phase 8: M5c — Cross-Validation & Final Oracle
**Goal**: Prove the engine's numbers are trustworthy by cross-validating against external references and freeze the final numerical oracle — the program-level definition of done.
**Depends on**: Phase 7
**Requirements**: M5-10
**Success Criteria** (what must be TRUE):
  1. The engine is cross-validated against `backtesting.py` and `backtrader` on the same strategy + data, with reported metrics reconciled and any divergence explained
  2. **Golden-master gate:** the final numerical reference output is frozen, establishing the new authoritative oracle
  3. Program definition-of-done holds: `SMA_MACD` runs end-to-end with a non-trivial trade log + equity curve, `mypy --strict` clean, no float money, single UUIDv7 scheme, deterministic runs, 274 component tests green (pytest) plus a run-path integration test
**Plans**: TBD

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. M1 — Ignition + Lock the Oracle | 5/5 | Complete   | 2026-06-04 |
| 2. M2a — Identity, Money & Determinism | 8/8 | Complete   | 2026-06-04 |
| 3. M2b — Config, Types, Storage Seam & Oracle Re-Freeze | 9/9 | Complete   | 2026-06-05 |
| 4. M3 — Event & Dispatch Core | 8/8 | Complete   | 2026-06-05 |
| 5. M4 — Money & Transaction Correctness | 4/7 | In Progress|  |
| 6. M5a — Backtest Validity, Fills & Data Pipeline | 0/TBD | Not started | - |
| 7. M5b — Sizing Policy, Metrics, Universe & Coverage | 0/TBD | Not started | - |
| 8. M5c — Cross-Validation & Final Oracle | 0/TBD | Not started | - |
