# Requirements — iTrader Backtest-Correctness Program

> **Requirement source = `COVERAGE-INDEX.md`.** Every in-scope architecture finding (#1–40) and
> concrete defect (TD/KB/SEC/PERF/FR/SL/DEP/MF/TC) is encoded here as a requirement, grouped by the
> milestone COVERAGE-INDEX assigns it. Each requirement carries its origin ID(s) for traceability.
> **Span items** (`M1→M2`, `M1→M5`) are split into a *start* requirement (early milestone) and a
> *complete* requirement (later milestone) so each REQ maps to exactly one phase while the span stays
> visible. The deferred register (`D-live`/`D-sql`/`D-screener`/`D-compliance`/`D-oanda`/`OUT`) is in
> Out of Scope. **Coverage assertion:** no in-scope finding/defect is left unmapped.
>
> Read with: `REFACTOR-BRIEF.md`, `COVERAGE-INDEX.md`, `codebase/ARCHITECTURE-REVIEW.md`, `codebase/CONCERNS.md`.

## v1 Requirements

### M1 — Ignition + lock the oracle

> Goal: `SMA_MACD` runs end-to-end on the golden CSV producing real trades; capture the reference
> output; stand up the test skeleton. **The only milestone built without an oracle — keep minimal.**
> Critical #34 is the sole execution blocker. No oracle exists until M1 makes the engine run.

- [x] **M1-01**: The backtest run path imports successfully — resolve the config package/flat-module
  shadowing so `itrader.config` names load and the price-handler→trading-system import cascade no
  longer fails *(#34 Critical [start of M1→M2], KB16, KB17, TD2 [start])*
- [x] **M1-02**: `config.TIMEZONE`-style attribute access on the runtime config dict no longer raises
  on the backtest path (minimal fix sufficient to run the golden daily UTC dataset) *(KB17 [start], #36 [start of M1→M2])*
- [x] **M1-03**: `to_timedelta` returns a real value for the timeframes the golden run uses (no silent
  `None` flowing into timing/resampling) *(KB20 [start of M1→M2], #36 [start])*
- [x] **M1-04**: `SMA_MACD_strategy` runs without error — fix `[-1]` label-indexing to `.iloc[-1]` and
  the string `fillna='False'` → `fillna=False` *(KB15, instance of #24/#38)*
- [x] **M1-05**: Backtest orchestration runs a full PING→BAR→SIGNAL→ORDER→FILL loop — fix
  `record_metrics` being called on `PortfolioHandler` instead of `Portfolio` *(KB18, #35 [backtest part])*
- [x] **M1-06**: Orders carry a real non-zero quantity — implement *minimal* position sizing in the
  architecturally-correct order/risk seam so `quantity=0` no longer reaches orders/fills
  *(KB11 [start of M1→M5], #24/#31 [minimal-sizing start])*
- [x] **M1-07**: `SMA_MACD` produces a **non-trivial trade log + equity curve** on
  `data/BTCUSD_1d_ohlcv_2018_2026.csv` (`make backtest` runs) *(definition-of-done gate, #35)*
- [ ] **M1-08**: The **reference output is captured and committed** — trade log (entry/exit time +
  side), equity curve, final cash/metrics — establishing the behavioral + numerical oracle *(golden-master spine)*
- [x] **M1-09**: Test skeleton stands up — pytest migration scaffold, the 8 declared markers actually
  applied to tests, conftest/fixtures layout, run-path **smoke test** (import→construct→run minimal
  backtest) *(#40 [skeleton], TC1 Critical)*
- [ ] **M1-10**: A **run-path integration test** exists exercising the full backtest end-to-end, and
  the 274 existing component tests stay green *(#40, TC1)*

### M2 — Foundations

> Goal: UUIDv7, Decimal, mypy-strict + frozen DTOs, real ABCs, determinism, config→Pydantic, type
> placement, time_parser finalized. **Numerical oracle re-baselines here** (float→Decimal shift).
> Behavioral oracle must stay unchanged.

- [ ] **M2-01**: A single ID scheme — UUIDv7 via the Rust-backed `uuid-utils` package — replaces the
  overflow-prone integer `id_generator`; IDs stored as native UUID, type not encoded in the value
  *(#10 Critical)*
- [ ] **M2-02**: Money is `Decimal` end-to-end (prices, quantities, cash, commissions, PnL) with no
  `float` round-trips and a centralized quantization policy *(#17)*
- [ ] **M2-03**: `mypy --strict` is clean across the package; hot-path DTOs/events are
  `frozen=True`/`slots=True`; `NewType` ID aliases applied *(#8)*
- [ ] **M2-04**: The eight Py2 `__metaclass__ = ABCMeta` "abstract" bases become real ABCs (or
  `Protocol`s), surfacing and fixing the non-conforming subclasses *(#20)*
- [ ] **M2-05**: Backtests are deterministic — RNG seeded behind an injected `Random`, clock injected
  (no local `datetime.now()`), flat global order index by id *(#5, PERF2)*
- [ ] **M2-06**: The `config/` package collapses to Pydantic v2 models + `pydantic-settings` for
  infra/secrets; one model round-trips backtest-dict and live-JSONB forms; settings layer carries no
  working secret defaults *(#13, #12 [settings part; secrets→D-live], completes #34/TD2 dual-config)*
- [ ] **M2-07**: Shared enums/entities are centralized in `core/enums` / own modules; scattered
  string→enum map dicts and their buggy `ValueError`s are replaced *(#15)*
- [ ] **M2-08**: Portfolio-handler manager state routes through an in-memory storage **seam**
  (transactions/positions/cash-ledger/metrics), mirroring the order-storage pattern; durable record
  shapes decided (Postgres backend → D-sql) *(#18 [seam part])*
- [ ] **M2-09**: Order state-change audit and transaction timestamps are **event-derived/deterministic**
  (not `datetime.now()`); `modify_order` routes through the validated `add_state_change` path
  *(#19 [timestamps part])*
- [ ] **M2-10**: `time_parser` timing is correct — `check_timeframe` anchoring fixed for non-UTC/DST/
  week-month, `to_timedelta` case-insensitive with week/month support, dead buggy helpers removed
  *(completes #36 M1→M2, KB21)*
- [ ] **M2-11**: Dead modules deleted — `legacy_config.py`, `outils/profiling.py`, `outils/strategy.py`,
  and the orphaned duplicate `screener_event_handler.py` `EventHandler` *(TD4 [`my_strategies`→OUT], TD5, KB14, #32 [orphan delete part])*
- [ ] **M2-12**: The bulk `unittest.TestCase` → pytest conversion proceeds (layered `tests/{unit,integration}`,
  conftests), building on the M1 skeleton *(#40 [bulk-conversion part])*
- [ ] **M2-13**: **Numerical oracle re-frozen** after the Decimal shift; behavioral oracle (trade
  timing) verified unchanged *(golden-master re-baseline gate)*

### M3 — Event & dispatch core

> Goal: immutable events with linkage IDs, race-free dispatch, unified errors/logging.
> **Behavior-preserving** — behavioral oracle is law, numerical oracle must reproduce.

- [ ] **M3-01**: Events are immutable (`frozen=True`) facts carrying a unique `event_id` + `created_at`,
  required linkage IDs (`order_id`/`fill_id`/`strategy_id`/`child_order_ids` no longer `Optional=None`),
  and enum-typed `action`/`order_type`; `type` becomes a real field; errors get their own `EventType`
  *(#11)*
- [ ] **M3-02**: The dispatch loop is race-free — `get_nowait()`+`queue.Empty` replaces the
  `empty()`/`get(False)` TOCTOU; routing is separated from ordering via a `dict[EventType, list[Callable]]`
  registry; unknown type raises `NotImplementedError` (not `NotImplemented`) *(#1, #2, FR2, KB1)*
- [ ] **M3-03**: The existing domain-exception hierarchy is used consistently (no bare
  `ValueError`/`NotImplemented`/swallowed-`None`); logging convention unified; portfolio exceptions
  constructed with correct-typed arguments *(#7 [domain part; FastAPI edge→D-live], #37, KB24)*
- [ ] **M3-04**: Behavioral oracle unchanged and numerical oracle reproduced after the event/dispatch
  refactor *(golden-master gate)*

### M4 — Money & transaction correctness

> Goal: cash through `CashManager` (Critical #22), atomic transactions, decoupling, order facade,
> exec DTOs. **Value-preserving** — any numeric diff must be explained; oracle holds.

- [ ] **M4-01**: Every trade routes cash through `CashManager` — no `portfolio.cash += float(...)`
  setter bypass; ledger/reservations/audit become live *(#22 Critical)*
- [ ] **M4-02**: Transaction processing is atomic — funds checked before position mutation, rollback on
  failure, one coherent error/return contract (no unreachable `return False` behind a re-raise)
  *(#23, #16)*
- [ ] **M4-03**: Order-handler layering is one-directional — facade→manager→storage; the read path
  delegates through `OrderManager` (not straight to storage); deprecated facade methods and the
  manager→handler back-ref removed; manager owns storage *(#9, #6)*
- [ ] **M4-04**: Cross-handler reads go through a narrow `PortfolioReadModel` Protocol (read-only views),
  not the concrete `PortfolioHandler` or its internals *(#6)*
- [ ] **M4-05**: Intra-portfolio manager coupling and cross-lock composite reads are resolved (no
  thread-safety theater) *(#29)*
- [ ] **M4-06**: In-memory order storage uses an O(1) flat `{order_id: order}` index instead of nested-
  dict O(n) scans for removal/lookup *(PERF3)*
- [ ] **M4-07**: Execution `result_objects`/`base` DTOs are frozen, Decimal-typed, real-ABC, carry
  `fill_id`, and are no longer a discarded side-channel *(#39; frozen/Decimal/ABC ride the M2 work)*
- [ ] **M4-08**: Value-preserving against the oracle — any numeric difference is explained; behavioral
  oracle unchanged *(golden-master gate)*

### M5 — Backtest validity, fills, metrics, strategy/data

> Goal: make the numbers trustworthy, then calibrate. **The one milestone allowed to change results** —
> the oracle becomes external cross-validation; **final numerical oracle frozen** here.

- [ ] **M5-01**: Backtest validity fixed — resampling look-ahead removed, limit fills no longer slip
  past the limit, bar-timing documented and consistent between same/other-timeframe branches *(#21)*
- [ ] **M5-02**: The per-tick market-data payload is an immutable `Bar` struct (not pandas Series);
  the `hasattr` accessor ladders and `get_last_close` type-branching disappear *(#3, FR1)*
- [ ] **M5-03**: Resampled frames are precomputed once per (ticker, timeframe) at load and sliced per
  tick — no `resample` in the hot loop *(#4)*
- [ ] **M5-04**: Fee/slippage models are correct — maker fees live, tiered model fixed, validation
  consistent, slippage not misapplied to limit fills; `time.sleep(0.1)` connect latency gated/removed
  *(#28, PERF1)*
- [ ] **M5-05**: The price handler splits into Provider/Store/Feed seams with an offline-vs-runtime
  lifecycle — the run path is read-only and errors loudly on missing data (no mid-run network fetch);
  bare `except:`→`None` and `to_megaframe` tz-drop/key-misalign fixed; strategies use the resampled-bars
  API not `price_handler.prices` directly *(#30, #27 [price seam; book-persist→D-live], FR6, FR7, FR8, PERF4)*
- [ ] **M5-06**: Strategy-declared sizing **policy** is fully resolved per-portfolio in the order/risk
  layer, completing the M1 minimal seam — `VariableSizer` finished, `RiskManager.check_cash` covers
  position increases, `calculate_signal` contract enforced *(completes #24/#31 M1→M5, KB11 [final], TD7, TD10)*
- [ ] **M5-07**: Reporting/metrics are correct — drawdown math, pandas-2/plotly API breakage, `is np.nan`
  identity bug, rolling-stats stub, and the dead `EngineLogger` resolved; computation split from
  presentation *(#38, #14 [compute; persist→D-sql], KB2, KB23, TD6)*
- [ ] **M5-08**: `universe/` collapses to a thin documented symbol-set stub (false "dynamic"/redundant
  copies removed) *(#33)*
- [ ] **M5-09**: Strategy/data/reporting/universe paths gain test coverage — CSV price store, reporting/
  statistics, universe *(TC2 [CSV part; adapters→D-oanda], TC4, TC6)*
- [ ] **M5-10**: The engine is **cross-validated against `backtesting.py` + `backtrader`** on the same
  strategy + data; metrics reconciled; the **final numerical reference output is frozen** *(golden-master
  external-validation gate, definition-of-done)*

## v2 Requirements (deferred to future milestones — not this program)

These have explicit deferred tags and their own future milestone. Listed so they are visibly *out of
this program's scope*, not forgotten. See COVERAGE-INDEX §D.

- **Live mode** (`D-live`): #7 FastAPI edge, #12 secrets, #35 `TradingInterface`/live threading, KB3,
  KB4, KB5, KB9, KB19, MF3, SEC2, SL2, TC5
- **SQL persistence** (`D-sql`): #25, #26, #14 persist, #18 backend, #19 durable, TD1, TD3, KB6, KB7,
  SEC1, FR5, SL1, DEP2, MF1
- **Screener / rebalance loop** (`D-screener`): #32, TD8, KB12, KB13, FR9, FR10, TC3
- **Compliance layer** (`D-compliance`): TD9, MF2
- **Adapters** (`D-oanda`): TD11, KB8, KB10, SEC3, FR4, DEP1, TC2 adapters

## Out of Scope

- **`my_strategies/*`** (`OUT`) — contains IP; user relocates it to a separate repo before work
  starts. Findings/defects scoped only to it (KB22, parts of TD4/TD9/FR3/PERF4) are resolved by
  removal, not refactor.
- **Live execution correctness** — backtest-first is a locked decision; live is a separate risk surface.
- **Adopting a third-party event-bus library** — explicitly rejected (#2); the in-house registry stays.
- **Vectorizing the engine** — the event-driven tax is an accepted, deliberate trade-off (#5).

## Definition of Done (program-level)

Per REFACTOR-BRIEF §1, the program is done when: `SMA_MACD` runs end-to-end on the golden CSV with a
non-trivial trade log + equity curve; `mypy --strict` clean; no float money (Decimal end-to-end);
single UUIDv7 scheme; deterministic runs (seeded RNG + injected clock); 274 component tests green
(migrated to pytest) **plus** a run-path integration test; reported metrics cross-validated against
`backtesting.py` and `backtrader`; final numerical reference output frozen.

## Traceability

REQ-ID → Phase. Span items map the *start* REQ to the early phase and the *complete* REQ to the later
phase; a span is not done until its final phase completes.

| Requirement | Phase | Milestone | Span | Status |
|-------------|-------|-----------|------|--------|
| M1-01 | Phase 1 | M1 | #34 start → M2-06 | Pending |
| M1-02 | Phase 1 | M1 | #36 start → M2-10 | Pending |
| M1-03 | Phase 1 | M1 | #36 start → M2-10 | Pending |
| M1-04 | Phase 1 | M1 | — | Pending |
| M1-05 | Phase 1 | M1 | — | Pending |
| M1-06 | Phase 1 | M1 | KB11/#24/#31 start → M5-06 | Pending |
| M1-07 | Phase 1 | M1 | — | Pending |
| M1-08 | Phase 1 | M1 | golden-master spine | Pending |
| M1-09 | Phase 1 | M1 | — | Pending |
| M1-10 | Phase 1 | M1 | — | Pending |
| M2-01 | Phase 2 | M2a | — | Pending |
| M2-02 | Phase 2 | M2a | — | Pending |
| M2-03 | Phase 2 | M2a | — | Pending |
| M2-04 | Phase 2 | M2a | — | Pending |
| M2-05 | Phase 2 | M2a | — | Pending |
| M2-06 | Phase 3 | M2b | completes #34 (from M1-01) | Pending |
| M2-07 | Phase 3 | M2b | — | Pending |
| M2-08 | Phase 3 | M2b | — | Pending |
| M2-09 | Phase 3 | M2b | — | Pending |
| M2-10 | Phase 3 | M2b | completes #36 (from M1-02/03) | Pending |
| M2-11 | Phase 3 | M2b | — | Pending |
| M2-12 | Phase 3 | M2b | — | Pending |
| M2-13 | Phase 3 | M2b | numerical oracle re-freeze gate | Pending |
| M3-01 | Phase 4 | M3 | — | Pending |
| M3-02 | Phase 4 | M3 | — | Pending |
| M3-03 | Phase 4 | M3 | — | Pending |
| M3-04 | Phase 4 | M3 | behavior/value-preserving gate | Pending |
| M4-01 | Phase 5 | M4 | — | Pending |
| M4-02 | Phase 5 | M4 | — | Pending |
| M4-03 | Phase 5 | M4 | — | Pending |
| M4-04 | Phase 5 | M4 | — | Pending |
| M4-05 | Phase 5 | M4 | — | Pending |
| M4-06 | Phase 5 | M4 | — | Pending |
| M4-07 | Phase 5 | M4 | — | Pending |
| M4-08 | Phase 5 | M4 | value-preserving gate | Pending |
| M5-01 | Phase 6 | M5a | — | Pending |
| M5-02 | Phase 6 | M5a | — | Pending |
| M5-03 | Phase 6 | M5a | — | Pending |
| M5-04 | Phase 6 | M5a | — | Pending |
| M5-05 | Phase 6 | M5a | — | Pending |
| M5-06 | Phase 7 | M5b | completes #24/#31/KB11 (from M1-06) | Pending |
| M5-07 | Phase 7 | M5b | — | Pending |
| M5-08 | Phase 7 | M5b | — | Pending |
| M5-09 | Phase 7 | M5b | — | Pending |
| M5-10 | Phase 8 | M5c | final numerical oracle frozen | Pending |

**Coverage:** 45/45 in-scope v1 REQ-IDs mapped to exactly one phase. No orphans, no duplicates. All
`D-live`/`D-sql`/`D-screener`/`D-compliance`/`D-oanda`/`OUT` items remain in v2/Out of Scope and are
excluded from all phases.
