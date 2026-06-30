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
oracle. The engine then gained its **authoring + contract surfaces** (v1.3), **margin, leverage,
first-class shorts and engine-native trailing stops** (v1.4 — it now trades on margin), and a
**profiler-guided hot-path optimization pass** (v1.5 — materially faster with the numbers unchanged).
The result is a backtest engine that is trustworthy, regression-locked across the whole surface, and
fast — ready for the persistence and live work ahead.

## Core Value

A single backtest run of `SMA_MACD` on `data/BTCUSD_1d_ohlcv_2018_2026.csv` produces
**correct, deterministic, cross-validated numbers** — if nothing else works, the backtest path
must import, run, and yield trustworthy results.

## Current Milestone: v1.6 — N+3b Persistence Foundation

**Goal:** Build the durable-storage + caching foundation — one swappable SQL interface
(Turso / SQLite / Postgres selected by config, not code), a results store for backtest/optimization
runs, concrete SQL backends for all three live operational storage seams (order mirror, portfolio
state, strategy/signal), and a classified cache — so the backtest path stays byte-exact and N+4 Live
Trading inherits a persistent, restart-safe system of record. Persistence half of Backlog 999.2 (the
performance half shipped as v1.5); precedes N+4 Live Trading (999.3).

**Target features (scope locked through owner clarification 2026-06-27 — these refinements supersede
the seed where they differ; see "Owner Decisions" below):**
- **Swappable SQL interface (the spine):** one storage interface, backend = config via `SqlSettings`.
  This milestone ships **SQLite** (research store default) + **Postgres** (operational store) drivers;
  **Turso/libSQL is opt-in *later*** — the interface stays Turso-ready, but the beta `sqlalchemy-libsql`
  driver is NOT added now (research Q2: its perf edge didn't hold for our batch-dump workload and the
  driver is beta/stale). Spine = **composition, not inheritance** (research Q1): the 3 existing domain
  ABCs + a new `ResultsStore` ABC, each implemented by ONE `Sql<Concern>Storage` that composes a shared
  `SqlBackend`.
- **Results store (#1):** all-SQL `runs` (lean indexed summary metrics + a JSON settings column) +
  `run_artifacts` (the equity-curve / trade-log frame as a **JSON / gzip'd-text column — NOT Parquet**,
  so `pyarrow` is not added). Every backtest/optimization run persisted so a parameter sweep never lives
  in memory. **All-`Float` typing** (analytical store, float-tolerant — no exact-reproduction need).
  Backend = **SQLite**, schema via `create_all()` (ephemeral, no Alembic). **Substrate only** — the
  sweep/optimization loop (Optuna sampler) is a later milestone; schema stays Optuna-FK-ready (research Q6).
- **Live operational store (#2):** a concrete SQL storage class for EACH of the three existing
  operational seams, all on the shared spine — order mirror (`PostgreSQLOrderStorage`, currently a
  `NotImplementedError` stub), portfolio state (new `SqlPortfolioStateStorage` —
  cash/position/transaction/metrics; the `PortfolioStateStorageFactory` has no SQL backend today), and
  strategy/signal (new `SqlSignalStorage`; the `SignalStorageFactory` has no SQL backend today).
  **Postgres-only** (live), schema via **Alembic**; backtest keeps the in-memory backend unchanged
  (factories stay `in_memory` vs `postgresql`, mirroring the existing `OrderStorageFactory`). Money =
  **native `Numeric`** on Postgres (Decimal end-to-end preserved on the real-money path; no
  `DecimalAsText` needed since money never lands on a SQLite-family backend). Tests via **testcontainers**.
  **Two-knob mode-awareness:** backtest = retain-all in-memory + optional end-of-run dump (write-through
  off, **zero hot-path cost** — the backtest backend contains no serialization code at all); live =
  working-set cache + write-through + purge-on-terminalize + read-through + restart rehydration (Nautilus
  model; research Q9/Q10).
- **Cache classification (#3):** inventory every ad-hoc cache / `lru_cache`, classify into (a) hot-path
  data cache (leave the v1.5 hot path alone — research Q7), (b) storage-index lookups already solved by
  v1.5 secondary indexes, (c) legitimate pure-function memoization — route each home; **classify, do not
  rewrite or unify** (research Q8: ~14 sites, most already correct; the only genuinely new cache is the
  live working-set cache).
- **Migrations + security:** Alembic for the live Postgres store only, `create_all()` for the ephemeral
  research DB (research Q4); FL-06 hardening in `SqlHandler` (`sql_store.py`) — confirmed hardcoded creds
  (L17), f-string `DROP TABLE` (L35), symbol-as-table-name (L56/58/69).

**Owner Decisions (research-time, supersede the seed):** (1) backends = SQLite-default research +
Postgres-only operational + Turso-opt-in-later (not the seed's "Turso default / 3 live drivers");
(2) results store is **all-`Float`** — the locked money-policy applies to the operational store (real
money), the results store is the analytical edge where float is allowed; (3) **no Parquet / no `pyarrow`**
— frames are a JSON/gzip'd-text column; (4) **no `DecimalAsText`** and the seed's "Turso native DECIMAL"
premise is RETRACTED as false — money fidelity is preserved by Postgres-native `Numeric`, and money never
touches SQLite; (5) optimization sweep loop OUT (substrate only).

**Correctness discipline (DB-gated milestone — NOT backtest-oracle-covered):** the lock is two-part —
(a) the SMA_MACD backtest oracle stays **byte-exact** (`134 / 46189.87730727451`), proving the
persistence layer adds **zero hot-path cost when write-through is off**, with no W1/W2 perf regression
vs the v1.5 frozen baseline (15.7 s / 152.8 MB); plus (b) new DB round-trip / restart-rehydration tests
for the genuinely new persistence code (in-process SQLite for the results store; testcontainers Postgres
for the operational store). Money policy preserved on the live path (Postgres-native `Numeric`); single
UUIDv7, determinism all carried.

**Design source:** `.planning/notes/persistence-milestone-design.md` (converged seed) + the four research
docs in `.planning/research/` (`STACK`/`FEATURES`/`ARCHITECTURE`/`PITFALLS`/`SUMMARY`, Q1–Q10 resolved,
committed `e4ad7c9`). Where the seed and the Owner Decisions differ, the Owner Decisions win.

## Shipped Milestone: v1.5 Backtest Performance Optimization (2026-06-26)

**SHIPPED 2026-06-26.** 8 phases (1–8, numbering reset), 26 plans, all 11 v1 requirements satisfied at
audit (`milestones/v1.5-MILESTONE-AUDIT.md` — 11/11 requirements, 8/8 phases verified, integration
clean, 1/1 E2E flow). The performance analog of v1.2 Consolidation — a **behavior-preserving**
milestone that made the SMA_MACD backtest materially faster while **changing no numbers**. **Next
milestone:** N+3b — Persistence (the split-out half of Backlog 999.2); start with `/gsd:new-milestone`.

**Delivered:** Profiler-ranked, oracle-gated hot-path optimizations across the engine. The #1
order-storage linear scan (~37% CPU) was replaced by derived secondary indexes over the flat
`{id: order}` dict (D-20 source of truth preserved, Postgres-extensible interface); the per-bar
realised-PnL re-summation (~13%) collapsed to a running Decimal accumulator; the full-window `ta`
indicator rebuild (~24%) replaced by hand-written O(1) stateful SMA/EMA/MACD/RSI recurrences on a
shared recent-bars feed (dropping `ta` on the runtime path); per-tick `searchsorted` window slicing
replaced by a monotonic int64 cursor (view-returning `window()`); hot-loop logging level-gated +
`get_type_hints` memoized; a latent O(n²) snapshot-retention copy killed via `deque(maxlen)`; and a
`msgspec.Struct` migration of the `Bar` + full event chain (Decimal contract intact). Every phase was
gated on BOTH (a) the byte-exact oracle staying green AND (b) a measured **same-machine-A/B** W1
improvement, re-frozen after the phase. Final W1 baseline re-frozen at **15.7 s / 152.8 MB** on a
verified-cool box.

**Re-baseline discipline (honored):** the SMA_MACD oracle held **byte-exact** (134 trades /
`final_equity 46189.87730727451`) across all 8 phases. Phase 5 carried a deliberate re-baseline
carve-out (cross-validation gated, owner sign-off) that proved **unnecessary** — the indicators only
gate boolean decisions, never enter money arithmetic, so the oracle came out byte-identical.
**Keep-only-measured** discipline was enforced: the naive Phase-8 mark-to-market "fusion" was
A/B-measured as a −15% W1 regression and **reverted** (the correct single-pass design deferred,
profile-first gated). `mypy --strict` clean, full suite **1340/1340** green (zero warnings), Decimal
end-to-end (no new float-for-money), determinism double-run byte-identical.

**Measurement caveat:** absolute pre/post W1 wall-clocks are not directly comparable across the
milestone, because the Phase-1 benchmark **probe had a quadratic bug** that inflated early numbers
(re-froze 153.7 s → 28.3 s on 2026-06-25 once fixed); per-phase wins were therefore attributed by
same-machine A/B and Scalene CPU-share, never the frozen-baseline diff.

**Tech-debt resolved at close:** the PERF-07/PERF-08 requirement-ID collision (delivered Phase 7/8
work keeps PERF-07/08; the originally-deferred items renumbered PERF-09/PERF-10). **Deferred:** the
correct single-pass per-bar portfolio valuation (`single-pass-portfolio-valuation.md`, profile-first
gated); advisory Nyquist VALIDATION.md gaps (the byte-exact oracle + same-machine A/B perf gate are
the real regression lock and ran green every phase).

<details>
<summary>✅ v1.4 Margin, Leverage, Shorts & Trailing Stops — SHIPPED 2026-06-22</summary>

7 phases (1–6 + inserted 5.1), 35 plans, all 23 requirements validated at audit
(`milestones/v1.4-MILESTONE-AUDIT.md`). The matching-engine / risk-execution milestone — the engine
now trades on margin. A frozen per-symbol `Instrument` value object is the single source of
price/quantity scales, `max_leverage`, and `maintenance_margin_rate` (INST-01/02/03); positions open
on reserved margin with effective leverage threaded signal→order→fill→transaction→position
(MARGIN/LEV); the `LONG_ONLY` guard is gone — shorts are first-class with PnL + daily borrow-carry
(SHORT/CARRY); bar-close maintenance-margin breach liquidates with capped loss, cross-validated
(LIQ/XVAL); `TRAILING_STOP` ratchets favorably-only from closed-bar extremes (TRAIL); short scale-in
through the side-agnostic SCALE-IN branch (SCALE); a market-neutral ETH/BTC pair flagship runs both
legs end-to-end (PAIR). The SMA_MACD spot oracle held byte-exact (134 / `46189.87730727451`) across
all 7 phases; the three result-changing re-baselines (accounting P4, trailing P5, scale-in P5.1) were
each owner-signed (tiziaco) + externally cross-validated. `mypy --strict` clean (187 files), full
suite 1193, determinism double-run byte-identical. Full detail in `milestones/v1.4-ROADMAP.md`.

</details>

<details>
<summary>✅ v1.3 Engine Surface Completion — SHIPPED 2026-06-14</summary>

All 6 phases / 20 plans complete; 10/10 requirements validated (`milestones/v1.3-MILESTONE-AUDIT.md`).
Completed the engine's authoring + contract surfaces BEFORE v1.4 built margin/shorts on them:
class-attribute strategy authoring (STRAT-01), declared-indicator framework with auto-derived warmup
(IND-01), engine-level composition API + uniform `update_config` (COMP-01/02), per-intent
entry-price/order_type signal contract + streamlined reconcile (SIG-01/02/03 + RECON-01), and run-end
TIF expiry (LIFE-01). Two re-baseline disciplines in separate phases: byte-exact (1–4) held the
BTCUSD oracle (134 / `46189.87730727451`); owner-gated (5–6) re-baselined under owner sign-off
(tiziaco, 2026-06-13) + external cross-validation. Full detail in `milestones/v1.3-ROADMAP.md`.

</details>


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

**Validated in v1.3 — Engine Surface Completion (Phases 1–6), 2026-06-14** — engine authoring +
contract surfaces completed; byte-exact phases (1–4) held the BTCUSD oracle (134 trades /
`final_equity 46189.87730727451`); owner-gated phases (5–6) re-baselined under owner sign-off +
external cross-validation; 10/10 requirements validated at audit:
- ✓ **STRAT-01 — strategy authoring surface (Phase 2):** class-attribute params (engine-facing
  names + defaults on the base, alpha knobs on the subclass) overridable at construction via
  `**kwargs`; base rejects unknown kwargs loudly (`UnknownParamError`/`MissingParamError`); re-runnable
  idempotent `init()` hook; the frozen pydantic strategy-config layer deleted. Byte-exact.
- ✓ **IND-01 — declared-indicator framework (Phase 3):** indicators registered declaration-only in
  `init()`, evaluated lazily per-tick; base auto-derives `warmup`/`max_window` from recipes (hand-set
  lines gone, derived `warmup == max_window == 100`); look-ahead-safe `crossover`/`crossunder`. Byte-exact.
- ✓ **COMP-01/COMP-02 — composition & config interface (Phase 4):** engine-level composition API
  (`SystemSpec`/`build_backtest_system`/`compose_engine`) with construction-time `ExchangeConfig`
  threading (replacing the Phase 7 D-14 conftest seam) + new `OrderConfig`; uniform `update_config`
  (merge → `model_validate` → atomic-swap) on all 7 handlers for between-cycle live reconfig. Byte-exact.
- ✓ **SIG-01/02/03 + RECON-01 — signal contract & reconcile (Phase 5, FRAGILE, owner-gated):**
  per-intent limit/stop ENTRY price + per-intent `order_type` threaded `SignalIntent → SignalEvent →
  Order.new_limit/stop_order`; `Order.action`/`_PendingBracket.action` typed `Side` with the position
  snapshot threaded once; `on_fill` reconciliation streamlined into named helpers, idempotent
  terminal-release invariant held. Proven by an owner-signed, externally cross-validated LIMIT golden.
- ✓ **LIFE-01 — order lifecycle / time-in-force (Phase 6, owner-gated):** run-end resting orders
  expire (`EXPIRED` wired through all four arms, non-cascading sweep); dead `create_order` second path
  removed → one validated `process_signal` path. Equity-neutral; 3 e2e leaves re-baselined `PENDING→EXPIRED`.
- ✓ **HYG-01 — engine hygiene (Phase 1):** SAFE byte-exact cleanup (public-API test asserts,
  Decimal-money validator retype, stale mypy override + dead constants removed, v1.2 Phase-6 residues).
- ⚠ Non-blocking at close: Nyquist Wave-0 partial on phases 2/3/6 (behavioral net = oracle + 59 e2e +
  mypy strict); 5 completed quick-tasks flagged by the `audit-open` ledger (canonically `status: complete`).
  Phase-6 robustness warnings reconciled (WR-01 by-design; WR-02/WR-03 fixed in PR #42). See
  `milestones/v1.3-MILESTONE-AUDIT.md`.

**Validated in v1.4 — Margin, Leverage, Shorts & Trailing Stops (Phases 1–6 + 5.1), 2026-06-22** —
the matching-engine / risk-execution surface; SMA_MACD spot oracle byte-exact (134 /
`46189.87730727451`) across all 7 phases, 3 owner-signed result-changing re-baselines externally
cross-validated; 23/23 requirements validated at audit (`milestones/v1.4-MILESTONE-AUDIT.md`):
- ✓ **INST-01/02/03 — `Instrument` value object (Phase 1):** frozen per-symbol source of
  price/quantity scales + `max_leverage` + `maintenance_margin_rate` behind a `Universe` facade;
  `_INSTRUMENT_SCALES` deleted; BTCUSD pinned 8dp held the oracle byte-exact.
- ✓ **MARGIN-01/02/03 + LEV-01/02/03 — margin accounting & leverage (Phase 2):** reserved-margin
  position opening (`initial_margin = notional / leverage`), over-margin → audited REJECTED path,
  position-keyed lock-and-settle, effective leverage threaded end-to-end for MARKET/LIMIT/STOP.
- ✓ **SHORT-01/02/03 + CARRY-01 — shorts & borrow carry (Phase 3):** `LONG_ONLY` guard removed via a
  side-agnostic cover-arm; short PnL + daily borrow-carry settle through the hardened margin seam.
- ✓ **LIQ-01/02/03 + XVAL-01 — liquidation & cross-validation (Phase 4):** bar-close maintenance-margin
  breach, capped-loss liquidation at fill-at-liq-price; owner-signed accounting-core golden
  cross-validated vs `backtesting.py`/`backtrader`.
- ✓ **TRAIL-01/02/03 — engine-native trailing stops (Phase 5):** first-class `TRAILING_STOP` ratcheting
  favorably-only from closed-bar extremes; declared via `PercentFromFill`, cross-validated, own
  owner-signed re-baseline; D-TRAIL-7 viability gate fails loud on the production path.
- ✓ **SCALE-01/02/03 — short scale-in (Phase 5.1, INSERTED):** same-side SELL add through the existing
  side-agnostic SCALE-IN branch with a symmetric admission solvency gate; own owner-signed re-baseline.
- ✓ **PAIR-01 — pair-trading flagship (Phase 6):** market-neutral ETH/BTC strategy end-to-end, both
  legs (94 round trips) through the unchanged accounting core; additive stability snapshot, not the oracle.
- ⚠ Non-blocking at close: tech debt deferred by design (flip/split economics, Phase-B perp realism →
  N+4, pair-strategy advisory β/coint items dormant for ETH/BTC, D-07×D-12 re-entry guard); Nyquist
  Wave-0 partial/absent (behavioral net = spot oracle + crafted scenarios + 1193 suite). See
  `milestones/v1.4-MILESTONE-AUDIT.md` and STATE.md → Deferred Items.

**Validated in v1.5 — Backtest Performance Optimization (Phases 1–8), 2026-06-26** — the
profiler-guided hot-path pass; behavior-preserving, SMA_MACD oracle **byte-exact** (134 /
`46189.87730727451`) across all 8 phases, full suite 1340/1340 green, `mypy --strict` clean; 11/11
v1 requirements satisfied at audit (`milestones/v1.5-MILESTONE-AUDIT.md`):
- ✓ **TOOL-01/02/04 — perf measurement harness (Phase 1):** root-Makefile `perf-*` surface, a
  two-mode runner (clean profiler-free benchmark = the gate, vs a separate Scalene `--cpu-only
  --program-path` profile), committed `W1-BASELINE.json` + soft ≥5% regression guard. TOOL-03
  cross-validation dropped — a behavior-preserving milestone proves correctness by *invariance*.
- ✓ **PERF-01 — order-storage indexing (Phase 2):** derived secondary indexes over the flat
  `{id: order}` dict (D-20 source of truth), removing the #1 ~37% CPU linear scan; Postgres-extensible.
- ✓ **PERF-02 — running PnL accumulator (Phase 3):** realised PnL maintained on close, removing the
  per-bar re-summation (~13%); Decimal preserved, mathematically equal at every bar.
- ✓ **PERF-03/04 — hot-path discipline (Phase 4):** level-gated hot-loop logging + per-bar `debug()`
  removed + admission-spam demoted; `get_type_hints` memoized per class — behavior-only.
- ✓ **PERF-05 — stateful indicators + shared bar cache (Phase 5, FRAGILE/LAST):** SMA/EMA/MACD/RSI as
  hand-written O(1) recurrences (dropping `ta` on the runtime path) on a shared recent-bars feed,
  per-symbol fan-out, per-tick window slice cut; ~24% CPU. Re-baseline carve-out proved unnecessary —
  oracle byte-identical.
- ✓ **PERF-06 — bar-feed window copies (Phase 6, optional):** view-returning `window()` + memoized
  offset alias + monotonic int64 cursor replacing per-tick `searchsorted`; all 7 look-ahead rules held.
- ✓ **PERF-07 — per-bar metrics & timestamp polish (Phase 7, byte-exact):** memoized `_aligned`,
  dropped eager snapshot-log arg-eval, snapshot retention → `deque(maxlen)` (killed a latent O(n²)),
  removed metrics-cache churn (~24% W1 CPU combined; from the post-Phase-6 re-profile).
- ✓ **PERF-08 — hot-path fusion, bar prebuild & msgspec (Phase 8, byte-exact):** `Position` cache
  (+15% W1), `to_dict` static-snapshot cache, `itertuples` `Bar` prebuild, and the `msgspec.Struct`
  migration (Bar + full event chain, Decimal intact, cleared a ≥5% W1 A/B). Keep-only-measured: the
  naive mark-to-market "fusion" was reverted as a measured −15% W1 regression.
- ⚠ Non-blocking at close: the PERF-07/PERF-08 ID collision was **resolved** at close (delivered work
  keeps PERF-07/08; deferred items renumbered PERF-09/10); the correct single-pass per-bar valuation
  is deferred (profile-first gated); advisory Nyquist VALIDATION.md gaps (the byte-exact oracle +
  same-machine A/B perf gate are the regression lock). See `milestones/v1.5-MILESTONE-AUDIT.md`.

### Active

<!-- v1.0 (Backtest-Correctness Refactor) SHIPPED 2026-06-08 — 45 requirements.
     v1.1 (Backtest Trustworthiness: Breadth) SHIPPED 2026-06-10 — 51 requirements.
     v1.2 (Consolidation) SHIPPED 2026-06-12 — 18 requirements.
     v1.3 (Engine Surface Completion) SHIPPED 2026-06-14 — 10 requirements.
     v1.4 (Margin, Leverage, Shorts & Trailing Stops) SHIPPED 2026-06-22 — 23 requirements.
     v1.5 (Backtest Performance Optimization) SHIPPED 2026-06-26 — 11 requirements.
     v1.6 (N+3b — Persistence Foundation) ACTIVE from 2026-06-27 — requirements being defined. -->

**ACTIVE: v1.6 — N+3b Persistence Foundation** (started 2026-06-27) — see the **Current Milestone:
v1.6** section near the top for the full goal, target features, and correctness discipline.
Requirements are being defined (`/gsd:new-milestone` → research → `REQUIREMENTS.md` → roadmap). The
milestone builds the durable-storage + caching foundation: one swappable SQL interface (Turso research
/ SQLite fallback / Postgres live), an all-SQL results store (#1), concrete SQL backends for all three
operational seams (order mirror, portfolio state, strategy/signal — #2), and a classified cache (#3) —
a live-path, DB-gated concern **not covered by the backtest oracle**, sequenced AFTER the v1.5
performance work so we are not persisting unvalidated behavior. v1.0 (45 reqs), v1.1 (51 reqs),
v1.2 (18 reqs), v1.3 (10 reqs), v1.4 (23 reqs), and v1.5 (11 reqs) are shipped and recorded in the
Validated section above and under `milestones/`.

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
| v1.1: opportunistic-cleanup standard (`.planning/codebase/CLEANUP-STANDARD.md`; fix-list archived at `.planning/milestones/v1.1-FIX-LIST.md`) | Cleanup is cross-cutting along touched paths only — no big-bang refactor, no oracle re-baseline; a concrete 4-gate executor checklist (path / eligibility / golden-path / bookkeeping) every later-phase executor applies, verified at milestone close | ✓ Good — shipped v1.1; ESTABLISHED Phase 1, VERIFIED at close (CLAR-02); FL-01/FL-02 closed, FL-03/FL-04 along touched paths |
| v1.1: behavior-preserving across the full surface (no oracle re-baseline) | Breadth coverage must add E2E leaves without changing the v1.0 numbers; result-changing findings are owner-gated, never silently folded in | ✓ Good — shipped v1.1; BTCUSD oracle byte-exact throughout (134 trades / 46189.87730727451); result-changing items (entry price, TIF) deferred to v1.2 |
| v1.2: MOD-01 god-module split is a dedicated, isolated, LAST phase | The `order_manager.py` fill-reconciliation / reservation-release path is FRAGILE; bundling code-motion with any behavior fix would make a regression unattributable | ✓ Good — shipped v1.2; 1279 → 210-line coordinator, pure code-motion, `on_fill` moved as one intact unit, golden byte-exact + determinism double-run identical |
| v1.2: consolidation is behavior-preserving (re-baselines nothing) | Clear the cleanup-review + CONCERNS debt without touching the numbers, so engine-surface features later build on a clean foundation; result-changing items deferred to Engine Surface Completion | ✓ Good — shipped v1.2; golden byte-exact across all 6 phases / 23 plans; SIG/COMP/IND/LIFE deferred to Backlog 999.5 |
| v1.2: D-07 — re-adjudicate the W2-10 "latent TypeError" as a misdiagnosis | Decimal-vs-float COMPARISON works in Py3 (only arithmetic raises, and there is none); the honest fix is float-for-money consistency, not a crash fix — surfaced as a bounded, owner-flagged gap delta, not silently folded | ✓ Good — DEC-02 reframed; below-minimum REFUSED branch regression-covered; golden byte-exact |
| v1.3: complete the engine's contract/authoring surfaces BEFORE margin/shorts (N+2) | N+2 builds margin/shorts/leverage on the exact signal/order/composition surfaces v1.3 completes; finishing them first avoids reworking N+2 against a moving surface | ✓ Good — shipped v1.3; SIG/COMP/IND/STRAT/LIFE surfaces complete, N+2 builds on a stable contract |
| v1.3: two re-baseline disciplines in SEPARATE phases (byte-exact 1–4 vs owner-gated 5–6) | A byte-exact phase's golden gate must be a clean pass/fail; mixing a result-change in makes a regression unattributable | ✓ Good — shipped v1.3; phases 1–4 held the oracle byte-exact, phases 5–6 each owned an attributed owner-signed re-baseline |
| v1.3: class-attribute strategy authoring replaces frozen-pydantic config | Authors hand-copied fields into a frozen config subclass; real annotated class attrs (mypy-visible, `**kwargs`-overridable, reject-unknown) are the natural Python surface + the seam runtime `update_config` needs | ✓ Good — shipped v1.3 (STRAT-01); re-runnable `init()` consumed by `StrategiesHandler.update_config` |
| v1.3: declared indicators with framework-derived warmup (model-B pre-eval) | Hand-set `warmup`/`max_window` is a footgun (under-gating → `IndexError`); deriving from declared recipes removes it while staying byte-exact (stateless recompute) | ✓ Good — shipped v1.3 (IND-01); derived `warmup == max_window == 100`, oracle byte-exact; incremental/stateful deferred to IND-02 |
| v1.3: per-intent entry price + order_type on the signal contract | Entry was hardwired to decision-bar close + fixed per strategy instance; per-intent limit/stop price + type is the contract N+2's richer orders need | ✓ Good — shipped v1.3 (SIG-01/02/03); owner-signed LIMIT golden cross-validated vs backtesting.py + backtrader |
| v1.3: run-end resting orders expire via TIF; collapse to one validated order path | Orders lingered PENDING at run end (`expire_order`/`EXPIRED` existed but unwired); a second unvalidated `create_order` path was dead weight | ✓ Good — shipped v1.3 (LIFE-01); EXPIRE wired through 4 arms (non-cascading), dead path removed, equity-neutral owner-gated re-baseline |
| v1.4: frozen per-symbol `Instrument` value object replaces `_INSTRUMENT_SCALES` | Margin/liquidation/carry all need per-symbol precision + leverage + MMR from one source; a hard-coded scales table cannot carry it and forces drift | ✓ Good — shipped v1.4 (INST-01/02/03); BTCUSD pinned 8dp held the oracle byte-exact, all consumers inject the `Universe` |
| v1.4: owner-gated result-changing re-baselines, one per result-changing subsystem, each cross-validated | Shorts/leverage/liquidation/trailing/scale-in each change the numbers; isolating one re-baseline per subsystem keeps every regression attributable, and external oracles guard correctness | ✓ Good — shipped v1.4; 3 re-baselines (accounting P4, trailing P5, scale-in P5.1) each owner-signed (tiziaco) + backtesting.py/backtrader cross-validated; spot oracle byte-exact across all 7 phases |
| v1.4: shorts/leverage reuse the side-agnostic accounting core (no new correctness branches) | A second settlement path for shorts/levered/scaled positions would double the surface to validate; the lock-and-settle model is already direction-agnostic | ✓ Good — shipped v1.4; LONG_ONLY guard removed via cover-arm, short scale-in and both pair legs settle through the unchanged SCALE-IN branch (SHORT/SCALE/PAIR), zero new engine branches |
| v1.4: bar-close maintenance-margin breach check (no intrabar mark feed) | Daily OHLCV has no mark price; checking on bar close is the honest, documented proxy — mark-price liquidation is Phase-B perp realism, deferred | ✓ Good — shipped v1.4 (LIQ-01/02/03); capped-loss liquidation at fill-at-liq-price, cross-validated; mark-price trigger → N+4 Phase B |
| v1.4: pair flagship is additive (a stability snapshot, NOT the correctness oracle) | A two-leg strategy partially cancels its own sign errors → a weak oracle by construction; the crafted XVAL-01 scenarios are the oracle | ✓ Good — shipped v1.4 (PAIR-01); ETH/BTC runs end-to-end both sides (94 round trips), snapshot-locked for drift detection only, re-baselines nothing |
| v1.5: behavior-preserving perf milestone (re-baselines nothing) — the perf analog of v1.2 | Speed wins must not change the numbers; the byte-exact oracle is the lock so every optimization is attributable and trustworthy | ✓ Good — shipped v1.5; oracle byte-exact (134 / `46189.87730727451`) across all 8 phases, 1340/1340 suite green |
| v1.5: attribute per-phase wins by same-machine A/B + Scalene CPU-share, NOT the frozen-baseline diff | The box is thermally sensitive AND a Phase-1 benchmark-probe quadratic bug shifted absolute numbers mid-milestone — frozen-baseline compares would over/under-credit phases | ✓ Good — every gate-(b) win attributed by A/B; baseline re-frozen only on a verified-cool box (final 15.7 s / 152.8 MB) |
| v1.5: keep-only-measured — revert any optimization that lands in A/B noise | A "clean" optimization that shows no attributable win is churn (risk with no payoff); reverting keeps the diff honest | ✓ Good — the Phase-8 naive mark-to-market fusion was A/B-measured at −15% W1 and reverted; correct single-pass design deferred (profile-first gated) |
| v1.5: stateful indicators isolated as a dedicated LAST phase with a re-baseline carve-out | Dropping `ta` for hand-written O(1) recurrences is FRAGILE; isolating it makes any byte-exactness regression attributable, and the carve-out pre-authorized a cross-validated re-baseline if needed | ✓ Good — shipped v1.5 (PERF-05); carve-out proved unnecessary (indicators only gate boolean decisions) — oracle came out byte-identical |

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

**v1.3 — Engine Surface Completion — SHIPPED 2026-06-14.** 6 phases (numbering reset to Phase 1), 20 plans, all 10 v1.3 requirements validated at milestone audit (10/10 requirements, 6/6 phases passed, 5/5 cross-phase seams wired, 5/5 E2E flows — `milestones/v1.3-MILESTONE-AUDIT.md`). The engine's authoring + contract surfaces are complete: class-attribute strategy authoring (STRAT-01), declared-indicator framework with auto-derived warmup (IND-01), engine-level composition API + uniform `update_config` (COMP-01/02), per-intent entry-price/order_type signal contract + streamlined reconcile (SIG-01/02/03 + RECON-01), and run-end TIF expiry (LIFE-01). Byte-exact phases (1–4) held the BTCUSD oracle (134 / `46189.87730727451`); owner-gated phases (5–6) re-baselined under owner sign-off + external cross-validation. `mypy --strict` clean (182 files), full suite 995, e2e 59/59, determinism double-run identical. Phase 6 (Order Lifecycle & Time-in-Force, owner-gated) detail: added `OrderCommand.EXPIRE` + `FillStatus.EXPIRED` enum seams and wired a run-end EXPIRE sweep across all four arms — `LifecycleManager.expire_all_resting()` (deterministic portfolio-then-UUIDv7 order), the `SimulatedExchange` EXPIRE arm (`matching_engine.cancel` + `FillEvent(EXPIRED)`), the `ReconcileManager` EXPIRED arm (idempotent for free via `VALID_ORDER_TRANSITIONS[EXPIRED]==[]`), and the `BacktestRunner` post-loop sweep + provably non-cascading final drain. The dead, unvalidated second signal→order path (`create_order`/`create_orders_from_signal`) was removed, collapsing the engine to one validated `process_signal` path (W4-09/D-03). Result-change is owner-gated and equity-neutral: the SMA_MACD oracle stays byte-exact (134 / `46189.87730727451`); exactly 3 e2e leaves (`matching/never_fill`, `sltp/from_decision_held`, `sltp/from_fill_held`) re-baselined run-end disposition `PENDING→EXPIRED` under explicit owner sign-off (tiziaco, 2026-06-13, `06-ATTRIBUTION.md`). Milestone v1.3 closed and archived 2026-06-14; next milestone N+2 (Backlog 999.4).

**v1.4 — Margin, Leverage, Shorts & Trailing Stops — SHIPPED 2026-06-22.** 7 phases (1–6 + inserted 5.1), 35 plans, all 23 requirements validated at milestone audit (23/23 requirements, 7/7 cross-phase seams, 3/3 E2E flows — `milestones/v1.4-MILESTONE-AUDIT.md`). The engine now trades on margin: a frozen per-symbol `Instrument` value object replaces `_INSTRUMENT_SCALES` as the source of price/quantity scales + `max_leverage` + `maintenance_margin_rate` (INST-01/02/03); positions open on reserved margin with effective leverage threaded signal→order→fill→transaction→position for MARKET/LIMIT/STOP and over-margin routed to the audited REJECTED path (MARGIN-01/02/03, LEV-01/02/03); the `LONG_ONLY` guard is removed and shorts are first-class with short PnL + daily borrow-carry (SHORT-01/02/03, CARRY-01); bar-close maintenance-margin breach liquidates with capped loss, cross-validated (LIQ-01/02/03, XVAL-01); `TRAILING_STOP` ratchets favorably-only from closed-bar extremes (TRAIL-01/02/03); a short can scale in through the side-agnostic SCALE-IN branch with a symmetric admission solvency gate (SCALE-01/02/03); and a market-neutral ETH/BTC pair strategy runs end-to-end both legs (94 round trips) through the unchanged accounting core (PAIR-01). The SMA_MACD spot oracle held byte-exact (134 / `46189.87730727451`) across all 7 phases; the three result-changing re-baselines (accounting P4, trailing P5, scale-in P5.1) were each owner-signed (tiziaco, 2026-06-16 / 06-17) + externally cross-validated. `mypy --strict` clean (187 files), full suite 1193, determinism double-run byte-identical. ~13.9k LOC code added since v1.3 (itrader + tests). Milestone v1.4 closed and archived 2026-06-22; next milestone N+3 (Backlog 999.2).

**Tech debt at v1.4 close (non-blocking, tracked):** flip/split full-settlement economics (out of scope, over-close fails loud); Phase-B perp realism (funding/mark-price liquidation) deferred to N+4; pair-strategy advisory review items (no negative/NaN β guard in `_fit_beta`, dormant for ETH/BTC; coint OLS cross-platform reproducibility snapshot limitation) — none affect the 94-round-trip flagship; the D-07×D-12 single-sided-liquidation pair re-entry guard (accepted+documented for the flagship); Nyquist Wave-0 partial/absent across phases (behavioral net = spot oracle + crafted scenarios + 1193 suite). 6 completed quick tasks were flagged only by the `gsd-sdk audit-open` filename-convention bug (it reads `quick/<dir>/SUMMARY.md` vs the GSD `<slug>-SUMMARY.md`); resolved at close with completion markers. See `milestones/v1.4-MILESTONE-AUDIT.md` and STATE.md → Deferred Items.

**v1.5 — Backtest Performance Optimization — SHIPPED 2026-06-26.** 8 phases (numbering reset to Phase 1), 26 plans, all 11 v1 requirements satisfied at milestone audit (11/11 requirements, 8/8 phases verified, integration clean, 1/1 E2E flow — `milestones/v1.5-MILESTONE-AUDIT.md`). The performance analog of v1.2 Consolidation: a behavior-preserving milestone that made the SMA_MACD backtest materially faster while changing no numbers — the byte-exact oracle held (134 / `46189.87730727451`) across all 8 phases. Headline wins: derived secondary order-storage indexes (killed the #1 ~37% CPU linear scan, D-20 source of truth preserved), a running Decimal PnL accumulator (~13%), hand-written O(1) stateful SMA/EMA/MACD/RSI on a shared recent-bars feed (~24%, `ta` dropped on the runtime path), a monotonic int64 window cursor replacing per-tick `searchsorted`, level-gated logging + memoized `get_type_hints`, a `deque(maxlen)` snapshot retention that killed a latent O(n²), and a `msgspec.Struct` migration of the `Bar` + full event chain (Decimal intact). Every phase gated on the byte-exact oracle + a measured same-machine-A/B W1 win; **keep-only-measured** enforced (the Phase-8 naive mark-to-market fusion was reverted at −15% W1). `mypy --strict` clean, full suite 1340/1340 green, determinism double-run byte-identical. Final W1 baseline 15.7 s / 152.8 MB on a verified-cool box. Milestone v1.5 closed and archived 2026-06-26; next milestone N+3b — Persistence (Backlog 999.2 persistence half).

**Tech debt at v1.5 close (non-blocking, tracked):** the correct single-pass per-bar portfolio valuation is deferred (`single-pass-portfolio-valuation.md`, profile-first gated — re-profile W1/W2 before building, else keep-only-measured rejects it); advisory Nyquist VALIDATION.md gaps on phases 03/04/08 + partial 05/06/07 (the byte-exact oracle + same-machine A/B perf gate are the real regression lock and ran green every phase). **Resolved at close:** the PERF-07/PERF-08 requirement-ID collision (delivered work keeps PERF-07/08; deferred items renumbered PERF-09/10), the stale `human_needed` status on Phase 01 (owner-approved-deferred profiler inspection) and Phase 03 verification/UAT (cool-machine re-freeze, done via quick task 260625-0qj + Phase 8), and 7 completed quick tasks flagged only by the `gsd-sdk audit-open` filename bug (cleared with completion markers). See `milestones/v1.5-MILESTONE-AUDIT.md` and STATE.md → Deferred Items.

## Next Milestones (after v1.5)

N+2 (Margin, Leverage, Shorts & Trailing Stops) shipped as **v1.4** (2026-06-22) and N+3 Performance
shipped as **v1.5** (2026-06-26) — see the **Shipped Milestone** sections above. Remaining backlog, in
promotion order (full intent in
`ROADMAP.md` Backlog); **N+3b is next**:

- **N+3b — Persistence** (Backlog 999.2, persistence half, split out) — durable PostgreSQL state
  (orders, signals, fills, equity; `PostgreSQLOrderStorage` is a `NotImplementedError` placeholder),
  FL-06 (SQL injection / hardcoded creds); follows v1.5 as its own milestone (live-path, DB-gated, not
  oracle-covered). The v1.5 order-storage indexing (PERF-01) designed its interface for this backend.
- **N+4 — Live Trading Readiness** (Backlog 999.3) — real-time data engine, live execution, the
  `Account` reconciliation abstraction, production screener / dynamic universe membership, FL-13
  live-system test coverage, the trailing-stop native-vs-synthetic capability seam.

Crypto-first keeps the whole sequence tractable (no multi-currency, no borrow-locate). Multi-asset
(forex / equities / ETF) is deferred indefinitely.

---
*Last updated: 2026-06-27 — **v1.6 — N+3b Persistence Foundation** STARTED via `/gsd:new-milestone`. Scope locked through clarification: all three concerns IN (#1 all-SQL results store, #2 live operational store with a concrete SQL backend for ALL THREE seams — order mirror / portfolio state / strategy-signal — on a shared spine, #3 cache inventory & classify). Backends: Turso (research default) + SQLite (free fallback, dialect sibling) + Postgres (live), backend = config not code. Optimization sweep loop OUT (substrate only). Correctness lock is DB-gated two-part: (a) backtest oracle byte-exact (134 / `46189.87730727451`) + no W1/W2 regression (proves write-through-off inertness) + (b) new DB round-trip / rehydration / cross-backend parity tests. Seed: `.planning/notes/persistence-milestone-design.md`; research answers Q1–Q10 (`.planning/research/questions.md`). v1.0–v1.5 SHIPPED — archived under `milestones/`.*

*Updated 2026-06-30 — v1.6 roadmap created (5 phases); **Phases 1–4 complete**: SQL spine + security hardening, all-SQL results store, operational SQL backends (3 seams), and Phase 4 retention + live write-through (`CachedSql{Order,PortfolioState,Signal}Storage` — store-first write-through, purge-on-terminalize + bracket-parent-resident, read-through, open-only rehydration; integration-tested on testcontainers Postgres). GATE-01 inertness held byte-exact (134 / `46189.87730727451`) with write-through OFF; RETAIN-01/02/03 + GATE-01 validated. Next: Phase 5 (Cache Classification #3).*
*Earlier: 2026-06-26 after the **v1.5 — Backtest Performance Optimization** milestone (SHIPPED 2026-06-26). 8 phases / 26 plans / 11 v1 requirements; behavior-preserving — oracle byte-exact (134 / `46189.87730727451`) across all 8 phases, 1340/1340 suite green, `mypy --strict` clean, final W1 baseline 15.7 s / 152.8 MB. Profiler-ranked hot-path wins (order-storage indexes, running PnL accumulator, stateful O(1) indicators, int64 window cursor, msgspec migration) under keep-only-measured discipline. PERF-07/08 ID collision resolved at close (deferred items → PERF-09/10). Next: N+3b — Persistence (`/gsd:new-milestone`). v1.0/v1.1/v1.2/v1.3/v1.4/v1.5 SHIPPED — archived under `milestones/`.*
*Earlier: 2026-06-25 — v1.5 Phase 5 (Incremental Indicators, PERF-05 — FRAGILE/oracle-gated, LAST) COMPLETE: all four indicators (SMA/EMA/MACD/RSI) converted to hand-written O(1) stateful float64 recurrences (`ta` dropped on the runtime path), a shared recent-bars feed layer added, and the per-tick master-frame window slice removed ENTIRELY (handler loop = `update(ticker,bar)`→`is_ready`→`generate_signal`). The SMA_MACD oracle was deliberately RE-BASELINED under owner sign-off (tiziaco, P5-D02) and came out **byte-IDENTICAL** (134 / `46189.87730727451` unchanged — the indicators only gate boolean decisions, never enter money arithmetic); cross-val PASS within 1% rel tol (backtesting.py −0.35%, backtrader exact) with no new divergence. Gate (a) correctness PASS; `mypy --strict` clean (188 files), full suite 1287, determinism double-run byte-identical. **Gate (b) (W1/W2 perf re-freeze) is the one carried-over thermal todo** — re-freeze on a verified-cool machine. With Phase 5 done, **ALL SIX v1.5 phases (1-6) are Complete → v1.5 (Backtest Performance Optimization) is FINISHED**; next step is milestone close (`/gsd-complete-milestone`). PERF-05 validated.*
*Context update: 2026-06-24 — Phase 5 DISCUSSED + reframed. The design spec
(`docs/superpowers/specs/2026-06-24-stateful-indicator-design.md`) + `05-CONTEXT.md` (P5-D01..D22)
**supersede** the byte-exact ROADMAP entry: Phase 5 is now **Stateful Indicators + Shared Bar Cache**,
a structural refactor that **deliberately RE-BASELINES** the SMA_MACD oracle (cross-validated, not
byte-exact) — Gate (a) becomes a re-baseline + cross-val freeze (P5-D02), the v1.5 "change numbers
nowhere" invariant gets a Phase-5 carve-out. Locked: feed-centric stateful indicators (Nautilus/LEAN
Model B), per-symbol/per-pair lazy fan-out, EMA seed-from-first + SMA running-sum, drop per-tick
`self.bars`, A→B→C plan split. 4 deferrals tracked in `.planning/todos/`. Next: /gsd:plan-phase 5.*
*v1.5 (Backtest Performance Optimization) STARTED. Promoted the performance
half of Backlog 999.2 and split Persistence out into its own following milestone. Goal: cut the frozen
W1 baseline (240.8 s / 167.3 MB) via profiler-ranked, oracle-gated hot-path optimizations without
changing the numbers — P0 perf tooling & baseline (root-Makefile `perf-*` targets, two-mode
benchmark/Scalene-HTML-profile runner, backtesting.py/backtrader cross-val runners, re-freeze), then
P1 order-storage indexing, P2 running PnL accumulator, P3 hot-path logging discipline, P4
`get_type_hints` cache, P5 incremental indicators (oracle-gated, last), P6 optional bar-feed window
copies. Every phase gated on the byte-exact SMA_MACD oracle (134 / 46189.87730727451) staying green +
a measurable W1 improvement — **EXCEPT Phase 5 (reframed 2026-06-24), which deliberately re-baselines
the oracle** (drops `ta` on the runtime path); its lock is cross-validation + a re-frozen reference
(P5-D01/D02), not byte-identity. Source: `perf/results/PERF-BASELINE-RESULTS.md` (spike = the research).
v1.0/v1.1/v1.2/v1.3/v1.4 SHIPPED — archived under `milestones/`.*
