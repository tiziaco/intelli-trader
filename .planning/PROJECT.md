# iTrader — Backtest-Correctness Refactor

## What This Is

iTrader is an event-driven algorithmic trading framework (Python 3.13, Poetry) for backtesting
and live execution, where all components communicate through a shared FIFO event queue. The
program began as a **brownfield structural refactor** — making the engine run **correctly in
backtest mode** end-to-end on one reference strategy (`SMA_MACD`) over a fixed golden dataset
(shipped v1.0) — and then **hardened that engine across its entire feature surface** (shipped
v1.1): the resting-order book, brackets/OCO, fee/slippage variants, SLTP policies, sizing,
scale in/out, and multi-strategy/multi-ticker/multi-portfolio runs are now each exercised
end-to-end by a 58-leaf frozen golden E2E matrix — all behavior-preserving against the v1.0
oracle. The result is a backtest engine whose results are trustworthy and regression-locked
across the whole surface, ready for the margin/shorts and live work ahead.

## Core Value

A single backtest run of `SMA_MACD` on `data/BTCUSD_1d_ohlcv_2018_2026.csv` produces
**correct, deterministic, cross-validated numbers** — if nothing else works, the backtest path
must import, run, and yield trustworthy results.

## Current Milestone: v1.3 Engine Surface Completion

**Goal:** Complete the signal/order contracts, give the system a real composition/config
interface, and land the declared-indicator + strategy-authoring abstraction — BEFORE N+2 builds
margin/shorts on top of these same surfaces. Promotes Backlog Phase 999.5. Phase numbering resets
to Phase 1 (matching the v1.1/v1.2 pattern; v1.2 phase dirs archived to `milestones/v1.2-phases/`).

**Target workstreams:**
- **(a) Signal contract completion** — explicit per-intent limit/stop ENTRY price + per-intent
  `order_type` on the signal contract (`SignalIntent` → `SignalEvent` →
  `Order.new_limit_order`/`new_stop_order`); folds W2-02 (`Order.action`/`_PendingBracket.action`
  `str`→`Side`) and W1-11 (position-snapshot threading); W4-04 validator-overlap doc if touched.
  **Owner-gated re-baseline** (result-changing).
- **(b) System composition/config interface** — promote `ScenarioSpec` to an engine-level
  composition API (declarative multi-strategy/portfolio wiring; faithful construction-time
  `ExchangeConfig` threading replacing the Phase 7 D-14 conftest seam; `csv_paths` passthrough);
  new `OrderConfig` model + threading (SYN-05); folds W4-02/03/05/06/07. **Plus COMP-02 — a uniform
  runtime `update_config` surface on EVERY handler** (`OrderHandler`/`OrderManager`,
  `StrategiesHandler`, `ExecutionHandler`, `PortfolioHandler`, `SimulatedExchange`,
  `BacktestBarFeed`) with ONE consistent signature (merge→validate→atomic-swap per SYN-03), so
  config can change at runtime in a **live scenario** — applied between event cycles, thread-safe,
  not a mid-cycle attribute poke. Today only 3 modules have it with 2 inconsistent signatures.
  **Byte-exact.**
- **(c) Declared-indicator framework + strategy authoring surface** — IND-01 + STRAT-01:
  class-attribute authoring surface (engine-facing names on the base, alpha knobs on the subclass,
  overridable at construction, reject-unknown-kwargs), re-runnable/idempotent `init()` hook,
  auto-derived `warmup`/`max_window`, model-B pre-eval reads (`self.sma[-1]`), free-function
  `crossover`/`crossunder`. The re-runnable `init()` is the seam COMP-02 needs for `StrategiesHandler`
  runtime reconfig. Folds W1-05 as declaration-only (stateless recompute stays byte-exact;
  incremental opt-in later). STRAT-01 separable — may ship first as a smaller slice. Full design:
  `notes/strategy-authoring-surface-999.5c.md`. **Byte-exact.**
- **(d) Order lifecycle completion** — wire run-end resting-order disposition / time-in-force
  (`Order.expire_order()` + `OrderStatus.EXPIRED` exist but unwired on the backtest path; orders
  stay PENDING at run end); `create_order` second-path gating (W4-09). **Owner-gated re-baseline**
  (result-changing).
- **Engine Hygiene slice** (net-new, from `notes/v1.3-concerns-triage.md` §B items 1–4) —
  `test_position_manager` private `_storage` asserts (W3-07, owed from v1.2 NAME-04, MISSED); stale
  mypy override for deleted `screener_event_handler.py`; dead `TOLERANCE = 1e-3` float constant;
  `PortfolioValidator.validate_transaction_data` accepts `float`. All SAFE, no golden re-run. One
  short phase.

**Re-baseline discipline:** (b)/(c) stay byte-exact against the v1.1 E2E golden suite
(134 trades / `final_equity 46189.87730727451`); (a) and (d)-TIF are owner-gated result-changing
re-baselines. **Deferred OUT of v1.3:** FL-13 live-system coverage → 999.3; FL-06 SQL injection →
999.2. Full fold-in/defer decisions in `notes/v1.3-concerns-triage.md`.

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

**Validated in Phase 8 (v1.1 — Admission, Position Management & Cash Edges), 2026-06-10:**
- ✓ E2E golden-locked coverage of the admission + cash-reservation surface — ADMIT-01..04, CASH-01/02 validated (13/13 must-haves), 7 new hand-verified leaves under `tests/e2e/admission/` and `tests/e2e/cash/`
- ✓ New determinism-safe cash-ledger snapshot serializer `itrader/reporting/cash_operations.py` (opt-in, oracle-dark — never added to `TRADE_COLUMNS`): correlates raw UUIDv7 reference_ids to stable `ORDER-{n}` ordinals, exposes the RESERVATION / RELEASE_RESERVATION / TRANSACTION_DEBIT|CREDIT lifecycle as a frozen CSV lens
- ✓ Admission leaves: `scale_in` (ADMIT-01 pyramiding via `allow_increase=True`, two adds aggregate + over-cash add no-commit), `scale_out` (ADMIT-02 partial close — `avg_sold=135` proves 40/20/20 `resolve_exit` sizing), `max_positions` (ADMIT-03 — first multi-ticker leaf; `open_position_count >= max_positions` REJECT), `re_entry` (ADMIT-04 exit-then-re-enter, two distinct round-trips)
- ✓ Cash leaves (CASH-02 reservation-release): `release_cancelled` (operator cancel → RELEASE_RESERVATION), `release_refused` (deterministic `max_order_size` lever → `FillEvent(REFUSED)` → terminal release — NOT the RNG `simulate_failures` path), `release_rejected` (over-cash → empty cash ledger, the honest no-orphan negative)
- ✓ Load-bearing no-orphan contrast frozen: ADMIT-03 max_positions reject is **gate-before-sizing** (`orders.csv quantity=0`, no `reserve()` call) vs CASH-02 release_rejected which is **gate-after-sizing** (`orders.csv quantity=1000`, `reserve_cash` raises `InsufficientFundsError` before recording any RESERVATION row) — both leave `available_cash` intact, for different reasons
- ✓ Test-infra seam fix (Rule-3, backward-compatible): conftest `spec.exchange` re-init now re-derives `_min/_max_order_size` from the applied config (mirrors `SimulatedExchange.update_config`), so a per-scenario `max_order_size` is actually honored by `validate_order`'s cached field; `_supported_symbols` left untouched; all prior leaves unaffected
- ✓ Oracle byte-exact held — BTCUSD golden 134 trades / `final_equity 46189.87730727451`; full suite 789 pass (37 e2e), `mypy --strict` clean
- ⚠ Post-phase code review (08-REVIEW.md): 0 blocker / 3 warning / 3 info — advisory, unfixed (WR-01 `ORDER-{n}` lexicographic sort misorders at ≥10 references — dormant, current goldens top at ORDER-5; WR-02 cash-ops sort lacks a unique trailing tiebreak; WR-03 conftest seam unconditionally re-inits fee/slippage models vs the conditionally-guarded `update_config` it claims to mirror)

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

**Validated in v1.2 — Consolidation (Phases 1–6), 2026-06-11/12** — behavior-preserving cleanup,
golden master byte-exact (134 trades / `final_equity 46189.87730727451`) throughout; `mypy --strict`
clean (172 files); e2e 58/58; full suite 851; 18/18 requirements verified at milestone audit:
- ✓ **Dead code & doc hygiene (DEAD-01/02):** deleted the dead ABCs (`AbstractPortfolioHandler`/`AbstractPortfolio`/`AbstractPosition` + orphan `get_last_close`), unused `OrderBase`, dead numpy import — zero importer breakage; closed stale CONCERNS/ROADMAP notes; documented four standing conventions (config-enum exception, broad-`except` run-mode policy, tab/space hazard, dual-layer validator overlap as justified-by-decision) in CONVENTIONS/CLAUDE.
- ✓ **Locked-decision conformance (DEC-01/02/03):** `Optional[Decimal]` money API on `modify_order`/`cancel_order`; Decimal `_min/_max_order_size` end-to-end (`validate_order` runs Decimal-vs-Decimal); retired the `uuid4()` second ID scheme to single UUIDv7 (`CorrelationId` NewType). D-07: the W2-10 "latent TypeError" was a misdiagnosis — reframed as float-for-money consistency.
- ✓ **Hot-path performance (PERF-01/02/03):** dropped per-tick storage copies (D-19 single-writer) with `snapshot_count()`/`get_latest_snapshot()` accessors; eliminated `Decimal(str(Decimal))` re-wraps + duplicated per-tick work; prebuilt `Bar`s in `BacktestBarFeed` + MACD computed inside the SMA guard — values bit-identical.
- ✓ **Type modeling (TYPE-01..05):** frozen/slots decision DTOs (`FillDecision`/`CancelDecision`/`OperationResult`/`SignalProcessingResult`/`_PendingBracket`); class-based string enums (`OrderStatus`/`OrderCommand` + `ErrorSeverity`/`OrderOperationType`/`OrderTriggerSource`/`market_execution`) with `assert_never` dispatch; `OrderId`/`PortfolioId` NewTypes on public APIs; `BaseStrategyConfig` co-located in `config/strategy.py`.
- ✓ **Naming & encapsulation (NAME-01..04):** `events_queue→global_queue`; PascalCase `SMAMACDStrategy`/`EmptyStrategy` + `fast_window`/`slow_window`/`signal_window`; public `routes` field; `register_symbol()` + complete `update_config` seam (no direct `_supported_symbols`/`_min_order_size` mutation); six tests re-asserted through public query APIs.
- ✓ **Order-Manager Decomposition (MOD-01, Phase 6 — FRAGILE, isolated, LAST):** `order_manager.py` 1279 → 210-line thin coordinator + `admission/`/`brackets/`/`lifecycle/`/`reconcile/` collaborators, **pure code-motion**; `on_fill` moved as one intact unit; terminal-status/`should_release`/`finally` interplay byte-for-byte unchanged; cross-bucket seams via coordinator callback + injected `BracketManager` (no sibling edges/circular import); determinism double-run byte-identical.
- ⚠ Non-blocking tech debt: DEF-02-02 (`simulated.py` diagnostic dicts emit raw `Decimal` — cosmetic); 6 REQ-IDs omitted from SUMMARY `requirements-completed` frontmatter (bookkeeping only); Nyquist Wave-0 not run (behavioral net = oracle + 58 e2e + mypy strict). See `milestones/v1.2-MILESTONE-AUDIT.md`.

### Active

<!-- v1.0 (Backtest-Correctness Refactor) SHIPPED 2026-06-08 — 45 requirements.
     v1.1 (Backtest Trustworthiness: Breadth) SHIPPED 2026-06-10 — 51 requirements.
     v1.2 (Consolidation) SHIPPED 2026-06-12 — 18 requirements.
     v1.3 (Engine Surface Completion) ACTIVE from 2026-06-12 — see REQUIREMENTS.md. -->

**v1.3 — Engine Surface Completion (ACTIVE).** Promotes Backlog Phase 999.5. Requirements are
defined in `.planning/REQUIREMENTS.md` (SIG-01/SIG-02 signal contract; COMP-01 composition API +
COMP-02 uniform live `update_config`; IND-01 indicator framework + STRAT-01 authoring surface;
LIFE-01 order lifecycle/TIF; HYG-01 engine-hygiene slice). v1.0 (45 reqs), v1.1 (51 reqs), and
v1.2 (18 reqs) shipped and are recorded in the Validated section above and under `milestones/`.

**Following milestone (N+2 — Backlog 999.4):** Margin/liquidation model → shorts (remove the
D-08/D-09 LONG_ONLY guard + fix the CR-01 cover-arm hole) → leverage / levered Kelly → perp
funding → engine-native trailing stop → real long/short pair trading. N+2 extends exactly the
signal/order/composition surfaces v1.3 completes, which is why v1.3 lands first.

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
| v1.1: crypto-first asset focus | Crypto is USD-quoted + 24/7 → defers multi-currency accounting + trading-calendar/corporate-action work indefinitely | ✓ Good — shipped v1.1; breadth stayed tractable (ETH/SOL/AAVE all USD-quoted) |
| v1.1: dedicated `tests/e2e/` + `e2e` marker | E2E = whole-system golden-master; needs run-as-a-bucket control + its own re-freeze discipline, distinct from cross-component integration tests | ✓ Good — shipped v1.1; 58-leaf matrix, shared harness, per-scenario golden fixtures, `make test-e2e` |
| v1.1: each E2E oracle hand-verified once, then regression-locked | A regression-lock proves *stability*, not *correctness*; tiny purpose-built scenarios are hand-computable, so verify expected fills/PnL once before freezing | ✓ Good — shipped v1.1; every leaf hand-verified in a VERIFY note before `--freeze` |
| v1.1: normalize new data via committed script, not loader logic | Split date/time is an export quirk, not a recurring schema; CSV loading is backtest-only (live uses streaming providers) → no run-path generalization | ✓ Good — shipped v1.1; `CsvPriceStore` byte-unchanged, all four datasets load identically |
| v1.1: minimal real universe (not a workaround) | Heterogeneous data spans make "asset enters mid-backtest" a real scenario; build a minimal `membership`-from-availability primitive the production screener extends, never a throwaway skip | ✓ Good — shipped v1.1; `is_active`/`active_membership` span primitive, proven over mid-run listings; production screener still deferred to v1.3 |
| v1.1: opportunistic-cleanup standard (`.planning/codebase/CLEANUP-STANDARD.md`; fix-list at `.planning/codebase/FIX-LIST.md`) | Cleanup is cross-cutting along touched paths only — no big-bang refactor, no oracle re-baseline; a concrete 4-gate executor checklist (path / eligibility / golden-path / bookkeeping) every later-phase executor applies, verified at milestone close | ✓ Good — shipped v1.1; ESTABLISHED Phase 1, VERIFIED at close (CLAR-02); FL-01/FL-02 closed, FL-03/FL-04 along touched paths |
| v1.1: behavior-preserving across the full surface (no oracle re-baseline) | Breadth coverage must add E2E leaves without changing the v1.0 numbers; result-changing findings are owner-gated, never silently folded in | ✓ Good — shipped v1.1; BTCUSD oracle byte-exact throughout (134 trades / 46189.87730727451); result-changing items (entry price, TIF) deferred to v1.2 |
| v1.2: MOD-01 god-module split is a dedicated, isolated, LAST phase | The `order_manager.py` fill-reconciliation / reservation-release path is FRAGILE; bundling code-motion with any behavior fix would make a regression unattributable | ✓ Good — shipped v1.2; 1279 → 210-line coordinator, pure code-motion, `on_fill` moved as one intact unit, golden byte-exact + determinism double-run identical |
| v1.2: consolidation is behavior-preserving (re-baselines nothing) | Clear the cleanup-review + CONCERNS debt without touching the numbers, so engine-surface features later build on a clean foundation; result-changing items deferred to Engine Surface Completion | ✓ Good — shipped v1.2; golden byte-exact across all 6 phases / 23 plans; SIG/COMP/IND/LIFE deferred to Backlog 999.5 |
| v1.2: D-07 — re-adjudicate the W2-10 "latent TypeError" as a misdiagnosis | Decimal-vs-float COMPARISON works in Py3 (only arithmetic raises, and there is none); the honest fix is float-for-money consistency, not a crash fix — surfaced as a bounded, owner-flagged gap delta, not silently folded | ✓ Good — DEC-02 reframed; below-minimum REFUSED branch regression-covered; golden byte-exact |

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

**v1.1 — Backtest Trustworthiness: Breadth — SHIPPED 2026-06-10.** 9 phases (numbering reset to Phase 1), 28 plans, all 51 v1.1 requirements validated. The engine's entire feature surface is now exercised end-to-end by a 58-leaf frozen golden E2E matrix (`tests/e2e/`, `e2e` marker, `make test-e2e`, shared harness) + the BTCUSD integration oracle — `pytest tests/e2e -m e2e` 58 passed, `pytest tests/integration` 12 passed (oracle byte-exact: 134 trades / `final_equity 46189.87730727451`), `mypy --strict` clean across 161 source files. Behavior-preserving guarantee held — v1.0 golden numbers NOT re-baselined. New surface delivered: ETH/SOL/AAVE data ingestion + real `membership` universe primitive, pydantic strategy-config hardening + typed queryable signal store, and full-coverage scenario waves (matching, cost/sizing/SLTP, admission/cash, multi-entity/robustness). ~31k LOC Python (+11.5k since v1.0, incl. golden fixtures).

**Tech debt at v1.1 close (non-blocking, tracked):** 4 completed quick tasks flagged only by a `gsd-sdk` v1.42.3 SDK-port filename bug (canonically clean); formal Nyquist Wave-0 incomplete on 6 phases / absent on 2 (strong behavioral coverage via the 58-leaf matrix); empty `requirements_completed` SUMMARY frontmatter on phases 1/4/5/7/9 (cosmetic). Per-phase code reviews left advisory warnings unfixed (e.g. `ORDER-{n}` lexicographic sort at ≥10 refs, dormant). See `milestones/v1.1-MILESTONE-AUDIT.md` and STATE.md → Deferred Items.

**v1.2 — Consolidation — SHIPPED 2026-06-12.** 6 phases (numbering reset to Phase 1), 23 plans, all 18 v1.2 requirements validated. A behavior-preserving cleanup milestone: the v1.1 cleanup-review backlog (46 findings) + the CONCERNS.md dead/fragile/tangled debt cleared **byte-exact against the golden master** (134 trades / `final_equity 46189.87730727451`) — re-baselined nothing. `pytest tests/integration` oracle byte-exact (3/3), `pytest tests/e2e -m e2e` 58/58, full suite 851, `mypy --strict` clean across 172 source files, determinism double-run byte-identical. Headline: `order_manager.py` decomposed from a 1279-line god-module into a 210-line coordinator + `admission/`/`brackets/`/`lifecycle/`/`reconcile/` collaborators as pure code-motion (FRAGILE path byte-for-byte unchanged). Locked-decision conformance closed (Decimal money API + size limits; single UUIDv7, `uuid4()` retired); hot-path per-tick copies/re-wraps/Bar-MACD churn eliminated bit-identically; closed vocabularies → class-based enums + frozen decision DTOs; consistent naming + public seams. ~21.7k LOC Python under `itrader/`.

**Tech debt at v1.2 close (non-blocking, tracked):** 4 completed quick tasks flagged only by the `gsd-sdk` SDK-port filename bug (canonically clean, `status: complete`); DEF-02-02 (`simulated.py` diagnostic dicts emit raw `Decimal` — cosmetic, no consumer breaks); 6 REQ-IDs omitted from SUMMARY `requirements-completed` frontmatter (bookkeeping only — coverage intact); Nyquist Wave-0 not run (behavioral net = oracle + 58 e2e + mypy strict). See `milestones/v1.2-MILESTONE-AUDIT.md` and STATE.md → Deferred Items.

## Following Milestone Goals: Engine Surface Completion (next milestone)

**Candidate (promote after v1.2 Consolidation, ahead of N+2 — see ROADMAP.md Phase 999.5).**
v1.1 proved empirically where the engine's contracts are still incomplete: every E2E scenario
phase had to work around the hardwired entry price, the fixed per-strategy order type, and the
missing composition interface (`ScenarioSpec` is the evidence). v1.2 Consolidation cleans the
foundation first (byte-exact); this milestone then completes the contracts before margin/shorts
(N+2) builds on the same surfaces:

- **Signal contract completion** — explicit per-intent limit/stop ENTRY price + per-intent `order_type` on the signal contract (`SignalIntent` → `SignalEvent` → `Order.new_limit_order`/`new_stop_order`). Result-risky → owner-gated re-baseline discipline.
- **System composition/config interface** — promote the `ScenarioSpec` shape into an engine-level composition API (declarative multi-strategy/multi-portfolio wiring; faithful construction-time `ExchangeConfig` threading, replacing the Phase 7 D-14 post-construction conftest seam; formalize the `csv_paths` passthrough). Should stay byte-exact vs the v1.1 E2E suite.
- **Declared-indicator framework** — indicator abstraction on the strategy base with auto-derived warmup (à la nautilus `register_indicator_for_bars`), so authors stop hand-setting `max_window`. A genuine model shift — design against the pure-alpha D-12 contract.
- **Order-lifecycle completion** — wire run-end resting-order disposition / time-in-force (`Order.expire_order()` + `OrderStatus.EXPIRED` exist but are unwired on the backtest path; orders currently remain PENDING at run end — result-changing, owner-gated). Plus the FL-stragglers (FL-01/FL-02 already closed; remaining along touched paths).

**Then N+2** (ROADMAP backlog): margin/liquidation model → shorts (remove the D-08/D-09 LONG_ONLY guard + fix the CR-01 cover-arm hole) → leverage / levered Kelly → perp funding → engine-native trailing stop → real long/short pair trading. Promote one at a time with `/gsd:review-backlog` or start with `/gsd:new-milestone`.

---
*Last updated: 2026-06-12 — milestone v1.3 Engine Surface Completion STARTED (promotes Backlog 999.5; phase numbering reset to 1). Scope: signal-contract completion (a, owner-gated), composition/config interface + uniform live `update_config` (b, byte-exact), declared-indicator framework + strategy authoring surface (c, byte-exact), order lifecycle/TIF (d, owner-gated), and a net-new engine-hygiene slice. FL-13→999.3, FL-06→999.2. Requirements in `.planning/REQUIREMENTS.md`; triage in `notes/v1.3-concerns-triage.md`; (c) design in `notes/strategy-authoring-surface-999.5c.md`. v1.2 (Consolidation) SHIPPED — archived under `milestones/v1.2-*`.*
