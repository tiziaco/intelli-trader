# iTrader — Backtest-Correctness Refactor

## What This Is

iTrader is an event-driven algorithmic trading framework (Python 3.13, Poetry) for backtesting
and live execution, where all components communicate through a shared FIFO event queue. This
project is a **brownfield structural refactor** of that framework: make it run **correctly in
backtest mode** end-to-end on one reference strategy (`SMA_MACD`) over a fixed golden dataset,
fixing every structural issue surfaced in the architecture review, and leave behind an engine
whose results are trustworthy and regression-locked.

## Core Value

A single backtest run of `SMA_MACD` on `data/BTCUSD_1d_ohlcv_2018_2026.csv` produces
**correct, deterministic, cross-validated numbers** — if nothing else works, the backtest path
must import, run, and yield trustworthy results.

## Requirements

### Validated

<!-- Inferred from existing code + 274 passing component tests. These work today. -->

- ✓ Component-level domains exist and are unit-tested — portfolio (cash/position/transaction/metrics),
  order handler (manager/validator/storage), execution (simulated exchange + matching engine),
  strategy composition scaffolding — existing
- ✓ Event-driven core: `global_queue` + `EventHandler.process_events()` dispatch — existing
- ✓ In-memory order storage backend + `SimulatedExchange`/`MatchingEngine` resting-book matching — existing
- ✓ 274 component tests pass under pytest strictness (`filterwarnings=["error"]`, strict markers) — existing

**Validated in Phase 1 (M1 — Ignition + lock the oracle), 2026-06-04:**
- ✓ Run path imports and `SMA_MACD` runs end-to-end on the golden CSV producing a non-trivial trade log + equity curve — `make backtest`, 134 trades, final equity $53,229.75 (#34, #35-backtest)
- ✓ Reference output captured + committed as the behavioral + numerical oracle at `test/golden/{trades,equity}.csv + summary.json`; regression-locked by an exact-diff (no float tolerance) run-path integration test
- ✓ Test skeleton: root `conftest.py` path-based marker auto-marking, 8 markers applied, run-path smoke + integration tests; full suite 276 green (#40-skeleton, TC1)
- ✓ Minimal fraction-of-cash sizing in the order/risk seam — orders no longer `quantity=0` (KB11, #24/#31 minimal)
- ✓ Ignition bugs fixed: `SMA_MACD` `[-1]`/`fillna` (KB15), `record_metrics` target (KB18), `to_timedelta` None (KB20), config import cascade (KB16/KB17/TD2)
- ⚠ Accepted deferrals (tracked in `phases/01-…/deferred-items.md`): **DEF-01-A** — a minimal Decimal→float commission coercion bridges ignition, to be reconciled when M4 makes money Decimal end-to-end; **DEF-01-C** — no margin/liquidation model, an un-liquidated short drives equity negative (min −$33,748); human-blessed into the M1 oracle as current-behavior-to-preserve, owner-routed to M5.

**Validated in Phase 7 (M5b — Sizing Policy, Metrics, Universe & Coverage), 2026-06-08:**
- ✓ Strategy-declared sizing policy fully resolved engine-side: typed vocabulary in `itrader/core/sizing.py` (`FractionOfCash`/`FixedQuantity`/`RiskPercent`, `TradingDirection`, `SignalIntent`), `SizingResolver` wired into `OrderManager` dispatching on `signal.sizing_policy`, M1's hardcoded `Decimal("0.95")` seam gone; sizing failures are audited PENDING→REJECTED entities; legacy `position_sizer/`/`risk_manager/`/`sltp_models/` packages deleted (M5-06, #24/#31/KB11 closed)
- ✓ Strategies are pure alpha producers (D-12): `SignalEvent` retyped with `sizing_policy`/`direction`/`sltp_policy` fields, `strategy_setting` dict deleted, handler-side fan-out; engine-side SLTP policy (D-13) — `PercentFromDecision` priced at assembly, `PercentFromFill` priced from the actual fill in `on_fill`
- ✓ Reporting/metrics correct (M5-07): pure `reporting/metrics.py` with D-16 backtesting.py-matched formulas (PERIODS=365, ddof=1), legacy `statistics.py`/`performance.py`/`engine_logger.py`/`base.py` deleted (kills `is np.nan`, `profict_factor`, DROP TABLE injection path), plots on plotly 6, engine prints D-14 end-of-run metrics block; `run_backtest.py` emits D-15 `summary.json` metrics + D-17 slippage columns
- ✓ `universe/` collapsed to documented `membership.py` stub (M5-08, #33); BarEvent factory moved into `BacktestBarFeed`; EventHandler TIME route uses injected `bar_event_source`
- ✓ Two owner-approved RESULT-CHANGING re-freezes (D-11): re-freeze 1 — LONG_ONLY direction guard at admission (D-08), 2 blessed shorts eliminated, final equity 53103.0155 → 46132.7668 (fully attributed); re-freeze 2 — `allow_increase=False` honored (D-10), 3 pyramiding fills rejected, final equity → 46189.8773; both documented in `tests/golden/REFREEZE-M5B-{DIRECTION,INCREASE}.md`
- ✓ Test coverage M5-09: suite 590 → 711 green; `mypy --strict` clean; determinism double-run byte-identical
- ⚠ Post-phase code review (07-REVIEW.md): 1 critical (SHORT_ONLY covers sized as entries — oracle-dark, golden strategy is LONG_ONLY), 9 warnings, 9 info — unfixed, advisory; 2 human-UAT items pending in 07-HUMAN-UAT.md

**Validated in Phase 6 (M5a — Backtest Validity, Fills & Data Pipeline), 2026-06-06:**
- ✓ Per-tick market-data payload is an immutable Decimal `Bar` struct (no pandas Series, no `hasattr`/`get_last_close` type-branching) flowing through events, matching, portfolio updates and strategies (M5-02, 06-01)
- ✓ Look-ahead-safe `BacktestBarFeed`: resampled frames precomputed once per (ticker, timeframe) and sliced per tick with the M5-01 visibility rule — no `resample` in the hot loop, no future bars visible (M5-01/M5-03, 06-03)
- ✓ Execution internals honest and Decimal-native: limit fills no longer slip past the limit, maker fees live, tiered fee model fixed, slippage not applied to limit fills, connect-latency sleep removed (M5-04, 06-04)
- ✓ Price handler split into Provider/Store/Feed seams with offline-vs-runtime lifecycle: run path is read-only `CsvPriceStore` + `BacktestBarFeed`, errors loudly on missing data, no mid-run network fetch (M5-05, 06-02/06-05)
- ✓ D-21/D-22 terminal: market orders fill at next-bar open through the resting book (the phase's one result-changing workstream); oracle re-frozen at 134 trades, `final_equity = 53103.01549885479` byte-exact (06-06, REFREEZE-M5A)
- ✓ Gap closure: CR-01 parent-filled bracket gate (two-pass `MatchingEngine.on_bar` — children dormant while parent rests) + WR-06 dead `update_portfolios_market` deleted; re-review critical count 0; suite 590 green, `mypy --strict` clean (06-07/06-08)

**Validated in Phase 5 (M4 — Money & Transaction Correctness), 2026-06-06:**
- ✓ Every trade's cash routes through `CashManager`: `Portfolio.cash` setter deleted, BUY-only check-and-reserve admission gate (price × quantity + injected commission estimate), idempotent release on all terminal reconciliations, live deterministic per-fill `CashOperation` ledger; D-14 inertness trace — 137 reservations over the golden run, trade log byte-identical (M4-01, #22 Critical)
- ✓ Atomic validate-first settlement: validate → funds invariant → position mutate → cash apply → record; saga machinery deleted; D-10 raise/None contract through `transact_shares`/`on_fill`; `Transaction.net_cash_delta` on the entity (M4-02, #16/#23)
- ✓ One-directional facade→manager→storage order-handler layering with flat O(1) `{order_id: order}` storage; cross-handler reads via narrow `PortfolioReadModel` Protocol + frozen `PositionView` in `itrader/core/` (M4-03/M4-04/M4-06, #6/#9/#29, PERF3, D-16..D-18)
- ✓ Thread-safety theater deleted — all 8 portfolio-state locks removed, single-writer contract documented, `readerwriterlock` dependency dropped (M4-05, D-19, #29)
- ✓ Execution DTOs frozen/Decimal/real-ABC; `ExecutionResult` deleted — FillEvents are the only execution output, silent rejection path now emits `FillEvent(REFUSED)` (M4-07, #39, D-21)
- ✓ D-22 closed: Signal/Order/Fill event money fields are Decimal end-to-end with engineered-inert float boundaries in matching internals; golden gate green — `final_equity = 53229.68512642488` byte-exact, suite 429→504 green, `mypy --strict` clean (M4-08)
- ✓ Post-phase code review: 24 findings (2 critical), all 14 critical+warning findings fixed with oracle byte-exact (05-REVIEW.md / 05-REVIEW-FIX.md); WR-09 live-mode smoke-run pending in 05-HUMAN-UAT.md

**Validated in Phase 4 (M3 — Event & Dispatch Core), 2026-06-05:**
- ✓ Events are frozen/slots/kw_only facts in the new `events_handler/events/` package: uuid7 `event_id` + business-time `created_at`, required non-Optional linkage IDs (`order_id`, `fill_id`, `strategy_id`), enum-typed `action: Side`/`order_type: OrderType`, `type` as a real field, dedicated `EventType.ERROR`; legacy `event.py` deleted with no shim (M3-01, D-08/D-09)
- ✓ All in-flight event mutation removed: SignalEvent `verified`/quantity-sentinel gone (Order entity is the pipeline state, rejections audited PENDING→REJECTED), FillEvent construct-complete at the exchange boundary, MatchingEngine replace-in-book via `dataclasses.replace` (D-10..D-13)
- ✓ Race-free dispatch: `get_nowait()`+`queue.Empty` drain (TOCTOU gone), `_routes: dict[EventType, list[Callable]]` registry where list order is execution order, explicit ERROR route, `NotImplementedError` on unknown types (M3-02, D-14..D-17)
- ✓ `ITraderError` exception hierarchy applied consistently (dead execution/concurrency exceptions deleted, order/data domains added, KB24 portfolio constructor args fixed); logging unified on structlog with env-driven level/json config, per-event logs demoted to DEBUG (M3-03, D-18..D-21)
- ✓ Golden-master gate: behavioral + post-M2 numerical oracle byte-exact at every wave; suite 349→429 green; `mypy --strict` clean (M3-04)

**Validated in Phase 3 (M2b — Config, Types, Storage Seam & Oracle Re-Freeze), 2026-06-05:**
- ✓ `config/` collapsed to Pydantic v2 models + `pydantic-settings` (3,380→~1,130 lines); `Settings` has a required `SecretStr database_url` with no working secret default; model round-trips backtest-dict and live-JSONB forms; flat `config.py` shadow + registry/getters/importlib-shim deleted; `FORBIDDEN_SYMBOLS` string-concat bug fixed (M2-06, #12/#13/#34/TD2)
- ✓ Shared enums centralized into `core/enums` (FillStatus + 4 manager enums) with case-insensitive `_missing_` parsers; buggy string→enum maps replaced (M2-07, #15)
- ✓ Portfolio-handler manager state routes through a unified `PortfolioStateStorage` seam (ABC + in-memory backend + factory) mirroring order storage; order/transaction timestamps event-derived; `modify_order` routes through the validated path (M2-08/M2-09, #18/#19)
- ✓ `time_parser` finalized: single `_aligned` epoch seam (daily-UTC byte-exact), `to_timedelta` case-insensitive with week support + month rejection; dead helpers removed (M2-10, #36). ⚠ Weekly/DST `check_timeframe` anchoring deferred via documented caveat + follow-up todo (WR-01; out of golden-path scope)
- ✓ Four dead modules purged: `legacy_config`, `outils/profiling`, `outils/strategy`, orphaned `screener_event_handler` (M2-11, TD4/TD5)
- ✓ Bulk `unittest`→pytest conversion: `test/`→`tests/{unit,integration}` (47 history-preserving renames), 29 TestCase files converted, folder-derived markers, suite 346 green (M2-12, #40)
- ✓ Numerical oracle re-frozen byte-exact after the Decimal shift (`final_equity` 53229.685…); D-15 tolerance + DEF-02-08-A xfail removed, numeric asserts `check_exact=True`; behavioral oracle confirmed unchanged via D-17 inertness gate (M2-13)

### Active

<!-- v1.0 (Backtest-Correctness Refactor) SHIPPED 2026-06-08. All 45 v1 requirements (M1–M5)
     are validated above. No active requirements until the next milestone is defined. -->

**None — v1.0 complete.** The full backtest-correctness program (M1→M5c, all 45 requirements) shipped and is recorded in the Validated section above and in `milestones/v1.0-*`.

**Next milestone candidate:** N+1 — Backtest Trustworthiness: Breadth (multi-strategy/scenario coverage, signal storage, strategy-interface hardening). See ROADMAP.md Backlog. Promote with `/gsd:new-milestone` (or `/gsd:review-backlog`), which defines fresh requirements.

### Out of Scope

<!-- Deferred to future milestones with explicit tags. Reasoning prevents re-adding. -->

- **Live mode** (`D-live`) — Binance streaming, WebSocket reconnection, restart sync, venue
  reconciliation, `TradingInterface`/API order path, live threading lifecycle, env-only secrets —
  whole separate risk surface; this program is backtest-first
- **SQL persistence** (`D-sql`) — order storage Postgres backend, price store, reporting-to-SQL,
  config JSONB, table-injection hardening — backtest uses in-memory + golden CSV; SQL is a
  live/persistence concern
- **Screener wiring** (`D-screener`) — rebalance loop (screener→universe→strategy) — a feature, not
  a correctness blocker; backtest runs a fixed ticker set
- **Compliance layer** (`D-compliance`) — `long_only`/`short_only` centralization — tied to strategy
  relocation + a future order-handler feature
- **OANDA + Binance adapters** (`D-oanda` / `D-live`) — not on the CSV-backed backtest path
- **`my_strategies/*`** (`OUT`) — contains IP; user relocates it to a separate repo before work
  starts; resolved by removal, not refactor

## Context

- **Authoritative analysis already exists.** Do not re-derive requirements. The source of truth is
  four planning docs (the first three are v1.0 input artifacts, now archived under `milestones/`):
  `.planning/milestones/v1.0-REFACTOR-BRIEF.md` (goal/scope/locked decisions/golden-master
  discipline), `.planning/milestones/v1.0-COVERAGE-INDEX.md` (the v1.0 coverage ledger — all 105 items → milestone; superseded by `REQUIREMENTS.md` for active v1.1 work),
  `.planning/milestones/v1.0-ARCHITECTURE-REVIEW.md` (40 design findings #1–40), and the still-current `.planning/codebase/CONCERNS.md`
  (post-refactor concerns).
- **Coverage contract.** Every Section A finding (#1–40) and Section B defect (TD/KB/SEC/PERF/FR/SL/DEP/MF/TC)
  maps to a milestone or a DEFERRED/OUT tag. No in-scope item may be left unmapped. Span items
  (`M1→M2`, `M1→M5`) start in one phase and complete in a later one.
- **Three Criticals:** #34 (M1, the only one that blocks execution — run path won't import today),
  #10 (M2, UUIDv7), #22 (M4, cash bypasses CashManager).
- **Codebase map** lives in `.planning/codebase/` (ARCHITECTURE, STACK, STRUCTURE, CONVENTIONS,
  TESTING, INTEGRATIONS).
- **Gap discovery is bounded.** New issues found during research / planning / the M1 capture / the
  M5 cross-validation are logged as deltas in COVERAGE-INDEX §E with a stable ID and a scope tag,
  flagged for owner approval — never silently folded into the running phase (it would corrupt the
  golden-master behavior contract).

## Constraints

- **Tech stack**: Python 3.13, Poetry, event-driven single-`global_queue` architecture — components
  emit events, never call across domains directly
- **Money**: Decimal end-to-end — float for money is a correctness defect (locked decision)
- **IDs**: single UUIDv7 scheme via the Rust-backed `uuid-utils` package (locked decision)
- **Determinism**: seeded RNG + injected clock — runs must be reproducible
- **Golden-master discipline**: M2–M4 are behavior-preserving against the M1 behavioral oracle;
  the numerical oracle re-baselines at exactly two points (after M2, after M5); M5 is the only
  milestone allowed to change results, validated by external cross-validation
- **Test strictness**: `pyproject.toml` sets `filterwarnings=["error"]`, `--strict-markers`,
  `--strict-config` — any unexpected warning fails the suite; every marker must be declared
- **Indentation**: tabs in handler modules; spaces in `config/` and newer modules — match the file
- **Import side effects**: `itrader/__init__.py` initializes `config`, `logger`, `idgen` singletons
  on import
- **Definition of done** (program-level, REFACTOR-BRIEF §1): `SMA_MACD` runs end-to-end producing a
  non-trivial trade log + equity curve; `mypy --strict` clean; no float money; single UUIDv7 scheme;
  deterministic; 274 component tests green (migrated to pytest) + a run-path integration test;
  metrics cross-validated against `backtesting.py` and `backtrader`; final numerical reference frozen

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Money = Decimal end-to-end | Float round-trips defeat careful Decimal math; financial correctness (#17, #22) | ✓ Good — shipped M2/M4; cash via CashManager, no float money on the result path |
| IDs = UUIDv7 via `uuid-utils` | Integer scheme overflows BIGINT; time-ordered, index-friendly, Rust-backed perf (#10) | ✓ Good — single scheme shipped M2 (⚠️ `portfolio_id: int` annotation carry-over remains; runtime-correct) |
| Backtest-correctness-first | Live is a separate risk surface; get the engine trustworthy first | ✓ Good — backtest path is trustworthy + cross-validated; live deferred to N+4 |
| Keep in-house event bus | Need deterministic synchronous ordered dispatch; libraries optimize for the opposite (#1, #2) | ✓ Good — race-free dict-registry dispatch shipped M3 |
| Config → Pydantic + pydantic-settings | Collapses 3300-line over-engineered package; one model is both backtest-dict and live-JSONB path (#12, #13) | ✓ Good — 3,380 → ~1,130 lines, shipped M2b |
| Strategy declares sizing *policy* + SL/TP; order/risk layer resolves per-portfolio qty | Current sizing migration is stranded (qty=0); put the seam in the architecturally-correct place (#24, #31) | ✓ Good — SizingResolver shipped M5b (⚠️ SHORT_ONLY cover-arm hole, oracle-dark → N+2) |
| Universe → documented thin stub | Collapse false "dynamic" complexity; screener wired later (#33) | ✓ Good — membership stub shipped M5b; screener → N+4 |
| Golden-master two-layer oracle | Behavioral oracle (trade timing) law M2–M4; numerical oracle re-baselines only after M2 & M5 | ✓ Good — held byte-exact through M2–M4; re-baselined exactly at M2b & M5c; final oracle frozen + cross-validated |
| v1.1: crypto-first asset focus | Crypto is USD-quoted + 24/7 → defers multi-currency accounting + trading-calendar/corporate-action work indefinitely | ◷ v1.1 — keeps breadth tractable |
| v1.1: dedicated `tests/e2e/` + `e2e` marker | E2E = whole-system golden-master; needs run-as-a-bucket control + its own re-freeze discipline, distinct from cross-component integration tests | ◷ v1.1 — per-scenario golden fixtures, shared harness |
| v1.1: each E2E oracle hand-verified once, then regression-locked | A regression-lock proves *stability*, not *correctness*; tiny purpose-built scenarios are hand-computable, so verify expected fills/PnL once before freezing | ◷ v1.1 — external cross-val only where backtesting.py/backtrader can express it |
| v1.1: normalize new data via committed script, not loader logic | Split date/time is an export quirk, not a recurring schema; CSV loading is backtest-only (live uses streaming providers) → no run-path generalization | ◷ v1.1 — `CsvPriceStore` unchanged |
| v1.1: minimal real universe (not a workaround) | Heterogeneous data spans make "asset enters mid-backtest" a real scenario; build a minimal `membership`-from-availability primitive the production screener extends, never a throwaway skip | ◷ v1.1 — screener still deferred to v1.3 |
| v1.1: opportunistic-cleanup standard (`.planning/codebase/CLEANUP-STANDARD.md`; fix-list at `.planning/codebase/FIX-LIST.md`) | Cleanup is cross-cutting along touched paths only — no big-bang refactor, no oracle re-baseline; a concrete 4-gate executor checklist (path / eligibility / golden-path / bookkeeping) every later-phase executor applies, verified at milestone close | ◷ v1.1 — ESTABLISHED Phase 1, VERIFIED at milestone close (CLAR-02) |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd-transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active (track in `REQUIREMENTS.md`; the v1.0 COVERAGE-INDEX §E delta log is archived)
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

## Current State

**v1.0 — Backtest-Correctness Refactor — SHIPPED 2026-06-08.** All 8 phases (M1→M5c), 62 plans, all 45 v1 requirements validated. Program definition-of-done green on all 8 checks: `SMA_MACD` runs end-to-end (134 trades / `final_equity = 46189.87730727451` / 3076 equity points), `mypy --strict` clean, no float money, single UUIDv7 scheme, deterministic, 724 tests pass, run-path integration gate byte-exact, cross-validated vs `backtesting.py` + `backtrader` + `nautilus-trader`. The final numerical oracle is frozen in `tests/golden/` as the authoritative reference. ~19.5k LOC Python.

**Tech debt at close (non-blocking, tracked):** partial M3-03 exception migration (bare `ValueError`s in `portfolio.py`, off the golden path), `portfolio_id: int` annotation carry-over, 2 partial Nyquist phases (02, 08), and advisory/live-mode review findings. Substantive behavior deferrals (margin/liquidation, shorts, SHORT_ONLY cover-arm) → N+2. See `milestones/v1.0-MILESTONE-AUDIT.md`.

## Current Milestone: v1.1 — Backtest Trustworthiness: Breadth

**Goal:** Extend trustworthy, regression-locked backtest behavior across the engine's *entire* feature surface — exhaustively exercising the resting-order book, brackets/OCO, fee/slippage variants, SLTP policies, sizing, scale in/out, and multi-strategy/multi-ticker runs — without re-baselining the v1.0 golden numbers. The hardening gate before any margin/live work. **Asset focus: crypto-first** (locked 2026-06-08).

**Target features:**
- **Full E2E coverage matrix** (30 scenarios) for the engine's behavior, in a dedicated `tests/e2e/` tree (registered `e2e` marker, `make test-e2e`, subsystem-grouped, per-scenario golden fixtures, shared harness). v1.0 only exercised a thin slice (MARKET / LONG_ONLY / single-ticker / `FractionOfCash` / `max_positions=1`); the resting-order book, brackets, fee/slippage variants, and SLTP policies have unit tests but **zero end-to-end coverage**.
- **Multi-entity breadth** (all LONG-ONLY): multi-strategy runs, one strategy trading two cryptos (multi-ticker), scale in/out on the same coin (`allow_increase=True` + partial `exit_fraction` — v1.0 only validated the *reject* direction).
- **Strategy signal storage** — persist strategy-generated signals.
- **Strategy interface hardening** — pydantic `BaseStrategyConfig` + per-strategy params model with validators; kill stringly-typed `order_type`; behavior-preserving vs the SMA_MACD oracle.
- **Data ingestion** — committed normalization script → ETH/SOL/AAVE into the golden Binance-kline schema (join split date+time); `CsvPriceStore` unchanged.
- **Minimal real universe** — `membership` from data availability (replaces the stub; production screener still deferred to v1.3).
- **Codebase clarity (scoped)** — one `gsd-map-codebase` pass → objective fix-list + opportunistic cleanup. NO big-bang refactor.

**Deferred to v1.2** (ROADMAP backlog): shorts, real long/short pair trading, margin/leverage, engine-native trailing stop.

---
*Last updated: 2026-06-09 — v1.1 (Backtest Trustworthiness: Breadth): Phase 5 (Strategy Interface Hardening & Signal Storage) complete — HARD-01..04 + SIG-01/02 validated (6/6 must-haves). The strategy interface is now a single frozen pydantic config object: `BaseStrategyConfig`/`SMA_MACDConfig`/`EmptyStrategyConfig` with HARD-01 timeframe-vocabulary + HARD-02 positivity/`short_window < long_window` validators (pydantic v2, construction-time only — `generate_signal` stays pure pandas, D-12). `order_type` is the `OrderType` enum end-to-end with the string boundary parse removed (HARD-03). The per-strategy warmup guard moved into `StrategiesHandler` via a dedicated `warmup` field (D-15, owner-approved Option A) — disambiguating the overloaded `max_window` so SMA stays byte-exact while the `SingleMarketBuy` e2e golden is untouched; the two reference strategies were relocated to `strategy_handler/strategies/` (D-13). A pluggable signal-storage seam landed (SIG-01/02): a frozen `SignalRecord` with its own UUIDv7 `SignalId` + config snapshot (no `portfolio_id`), a `SignalStore` ABC + `InMemorySignalStore` + `SignalStorageFactory` mirroring `order_handler/storage/`, per-intent capture in `calculate_signals` BEFORE the per-portfolio fan-out (queue-only contract preserved), composition-root injection in `TradingSystem`, and `get_signal_records()`/`get_signal_store()` post-run accessors. HARD-04 byte-exact held — BTCUSD golden run 134 trades / `final_equity 46189.87730727451`; 748 tests pass; `mypy --strict` clean (159 files). Post-phase code review (05-REVIEW.md): 0 critical / 4 warning / 6 info — advisory, unfixed (notably WR-01 `portfolio_id: int` annotation carry-over). Prior: Phase 4 (E2E Harness Framework) complete — shared harness + `e2e` marker + first hand-verified canary. Phase 3 (Minimal Real Universe) complete — UNIV-01/UNIV-02 validated. The membership stub is replaced by a real availability primitive: pure `is_active(spans, ticker, T)` + `active_membership(spans, T)` live beside the byte-unchanged `derive_membership` (D-01 inclusive endpoints, D-03). The feed builds a `{ticker: (first, last)}` span cache once in `bar_feed.__init__` and `generate_bar_event`'s warn loop is now span-aware (D-04 — silent for expected pre-listing/post-end absence, warns only on a true mid-life gap); the duplicate strategy-handler warning was removed while the load-bearing `if bar is None: continue` skip is kept (D-05). An optional oracle-dark `csv_paths` passthrough on `TradingSystem.__init__` (default None → identical) drives a synthetic-fixture integration test proving the engine runs the union window of a mid-run lister + a differing-end-date ticker with no crash and no look-ahead (D-06; real ETH/SOL/AAVE E2E run deferred to Phase 9/ROBUST-02). Oracle-dark held — BTCUSD golden run byte-identical; 734 tests pass. Prior: Phase 2 (Data Ingestion) complete — INGEST-01/02/03 validated (ETH/SOL/AAVE normalized into golden kline schema; D-06 volume relaxed to non-negative). Phase 1 (Codebase Map) complete — CLAR-01/CLAR-02. v1.0 phases archived to `milestones/v1.0-phases/`.*
