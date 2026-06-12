# Roadmap: iTrader

## Milestones

- ✅ **v1.0 — Backtest-Correctness Refactor** — Phases 1-8 (shipped 2026-06-08)
- ✅ **v1.1 — Backtest Trustworthiness: Breadth** — Phases 1-9 (shipped 2026-06-10)
- ✅ **v1.2 — Consolidation** — Phases 1-6 (shipped 2026-06-12; numbering reset for v1.2, matching v1.1)
- 🚧 **v1.3 — Engine Surface Completion** — Phases 1-6 (ACTIVE from 2026-06-12; numbering reset; promotes Backlog 999.5)
- 📋 **N+2 — Margin, Leverage, Shorts & Trailing Stops** — Backlog (planned)
- 📋 **N+3 — Persistence & Performance** — Backlog (planned)
- 📋 **N+4 — Live Trading Readiness** — Backlog (planned)

Full milestone detail (phase goals, success criteria, per-plan breakdown) is archived per milestone:
v1.0 — [`milestones/v1.0-ROADMAP.md`](./milestones/v1.0-ROADMAP.md) ·
[`v1.0-REQUIREMENTS.md`](./milestones/v1.0-REQUIREMENTS.md) ·
[`v1.0-MILESTONE-AUDIT.md`](./milestones/v1.0-MILESTONE-AUDIT.md);
v1.1 — [`milestones/v1.1-ROADMAP.md`](./milestones/v1.1-ROADMAP.md) ·
[`v1.1-REQUIREMENTS.md`](./milestones/v1.1-REQUIREMENTS.md) ·
[`v1.1-MILESTONE-AUDIT.md`](./milestones/v1.1-MILESTONE-AUDIT.md);
v1.2 — [`milestones/v1.2-ROADMAP.md`](./milestones/v1.2-ROADMAP.md) ·
[`v1.2-REQUIREMENTS.md`](./milestones/v1.2-REQUIREMENTS.md) ·
[`v1.2-MILESTONE-AUDIT.md`](./milestones/v1.2-MILESTONE-AUDIT.md).
v1.0 phase working dirs are archived under `milestones/v1.0-phases/`; v1.1 under `milestones/v1.1-phases/`; v1.2 under `milestones/v1.2-phases/`.

> **Note on milestone naming:** **v1.2 _Consolidation_** (shipped 2026-06-12) was a
> behavior-preserving cleanup milestone (Phases 1-6). The feature work formerly seeded as
> "v1.2 — Engine Surface Completion" was **promoted to the active milestone v1.3** below
> (it was Backlog Phase 999.5). The remaining `999.x` entries are future milestones (N+2/N+3/N+4).

## Phases

### 🚧 v1.3 — Engine Surface Completion (ACTIVE — Phases 1-6, numbering reset)

Active milestone. Completes the signal/order contracts, the composition/config interface, the
declared-indicator + strategy-authoring surface, and order-lifecycle/TIF — the result-changing /
new-framework items deferred out of v1.2 Consolidation (promotes Backlog 999.5). Phase numbering
reset to 1 (matching the v1.1/v1.2 pattern; v1.2 phase dirs archived to `milestones/v1.2-phases/`).
Re-baseline discipline runs per-phase: byte-exact phases (1-4) must hold the v1.1 E2E golden suite
+ BTCUSD oracle (134 trades / `final_equity 46189.87730727451`); owner-gated phases (5-6) re-baseline
only after explicit owner sign-off + external cross-validation.

- [x] **Phase 1: Engine Hygiene** — SAFE byte-exact cleanup slice (no run-path touch): private-storage test asserts, stale mypy override, dead float constants, validator retype, three v1.2 Phase-6 review residues. (completed 2026-06-12)
- [x] **Phase 2: Strategy Authoring Surface** — class-attribute authoring surface replacing the frozen-config + manual field-copy; re-runnable idempotent `init()` hook; reject-unknown-kwargs. (completed 2026-06-12)
- [x] **Phase 3: Declared-Indicator Framework** — declared indicators with auto-derived `warmup`/`max_window`; lazy per-tick recompute; free-function `crossover`/`crossunder`. (completed 2026-06-12)
- [ ] **Phase 4: Composition & Config Interface** — engine-level composition API + `OrderConfig`; uniform runtime `update_config` on every handler (consumes Phase 2's re-runnable `init()`).
- [ ] **Phase 5: Signal Contract & Reconcile (FRAGILE)** — per-intent entry price + `order_type`, `Side`-typed action + snapshot threading, `on_fill`/`should_release` streamline; ONE owner-gated re-baseline.
- [ ] **Phase 6: Order Lifecycle & Time-in-Force** — run-end resting-order disposition / TIF (`expire_order` + `EXPIRED` wired) + `create_order` second-path gating; owner-gated re-baseline.

## Phase Details

### Phase 1: Engine Hygiene
**Goal**: Close the SAFE hygiene debt — the private-internals test asserts, the stale config/typing residue, and the three v1.2 Phase-6 review leftovers — without touching the run path or the golden numbers.
**Depends on**: Nothing (first phase)
**Requirements**: HYG-01
**Success Criteria** (what must be TRUE):
  1. `tests/unit/portfolio/test_position_manager.py` asserts through public query APIs only — no `pm._storage` private access remains (W3-07, owed from v1.2 NAME-04).
  2. The stale `screener_event_handler.py` mypy override is gone from `pyproject.toml`, the dead `TOLERANCE = 1e-3` float constant is deleted from `portfolio_handler/portfolio.py`, and `PortfolioValidator.validate_transaction_data` no longer accepts `float` (Decimal-money policy honored).
  3. The three v1.2 Phase-6 review residues are resolved: the dead `StrategyId` import dropped (`order_manager.py:20`), the duplicated `_ONE = Decimal("1")` consolidated or documented (`brackets/levels.py` + `sizing_resolver.py`), and the misleading `TYPE_CHECKING` guard doc softened (`reconcile/reconcile_manager.py`).
  4. The golden master is byte-exact (134 trades / `final_equity 46189.87730727451`), e2e 58/58, full suite green, `mypy --strict` clean — no run-path touch, no golden re-run needed.
**Plans**: 1 plan
  - [x] 01-01-PLAN.md — All 7 HYG-01 hygiene items (test asserts to public API, stale mypy override, dead TOLERANCE, strict-Decimal validator, _ONE consolidation, reconcile doc; StrategyId verify-only)

### Phase 2: Strategy Authoring Surface
**Goal**: A strategy author declares params as real annotated class attributes (no frozen-config subclass, no manual field-copy), overridable at construction, with the base rejecting unknown kwargs loudly — and a re-runnable idempotent `init()` hook that later phases build on.
**Depends on**: Phase 1
**Requirements**: STRAT-01
**Success Criteria** (what must be TRUE):
  1. The base `Strategy` owns the engine-facing names with defaults (`timeframe`, `tickers`, `sizing_policy`, `order_type`, `direction`, `allow_increase`, `max_positions`, `sltp_policy`); a subclass pins intrinsic values and adds alpha knobs as annotated class attrs; all are overridable at construction via `**kwargs`.
  2. Constructing a strategy with an unknown kwarg raises `UnknownParamError` loudly; a missing required attr (e.g. `sizing_policy`) is rejected; enum-typed fields (e.g. `timeframe` str) are coerced.
  3. `generate_signal` reads real typed instance attrs (`self.short_window`) — the pure-alpha D-12 contract is preserved; the dropped frozen-config mutation guard is replaced by a sanctioned-reconfigure-method-only discipline.
  4. The reference `SMAMACDStrategy` runs through the new authoring surface byte-exact against the BTCUSD oracle (134 trades / `final_equity 46189.87730727451`); e2e 58/58, `mypy --strict` clean (declared params are real annotated attrs mypy sees).
**Plans**: 3 plans (3 waves — all-or-broken lockstep: source migration lands then construction sites + tests migrate together, then the byte-exact gate)
  - [x] 02-01-PLAN.md — New `core/exceptions/strategy.py` (`UnknownParamError`/`MissingParamError` subclassing `ValidationError`) + barrel re-export (Wave 1, standalone)
  - [x] 02-02-PLAN.md — Core source migration: `base.py` introspection engine + `init`/`validate`/`reconfigure` hooks (timeframe→timedelta Pitfall 1), `SMAMACDStrategy`/`EmptyStrategy` class-attr declarations, `SignalRecord.config` dict snapshot + handler capture, full pydantic config-layer delete (Wave 2)
  - [x] 02-03-PLAN.md — All construction-site migration (e2e fixtures, oracle script, integration sites) + strategy unit-test rewrite/extend (unknown/missing/override/coerce/no-coerce/idempotent/reconfigure/dict-snapshot) + the byte-exact phase gate (Wave 3)
**UI hint**: yes

### Phase 3: Declared-Indicator Framework
**Goal**: A strategy declares indicators (func + input + params) in `init()` and reads pre-evaluated handles (`self.short_sma[-1]`), with the base auto-deriving `warmup`/`max_window` so authors stop hand-setting them — stateless recompute, byte-exact by construction.
**Depends on**: Phase 2
**Requirements**: IND-01
**Success Criteria** (what must be TRUE):
  1. Indicators are registered declaration-only in `init()` (recipes, no compute) and evaluated lazily per-tick from the pushed window using the same `ta` calls as today; the author reads ready handles in `generate_signal` (model-B pre-eval), never passing `bars` into the indicator.
  2. After `init()` runs, the base inspects registered recipes and auto-derives `self.max_window` / `self.warmup = max(min-periods)`; the hand-set `max_window`/`warmup` lines are gone from the reference strategy.
  3. Free functions `crossover(a, b)` / `crossunder(a, b)` over series are available and look-ahead-safe by construction (reading "previous" from the completed-bars window only).
  4. The reference `SMAMACDStrategy` migrated onto the framework is byte-exact against the BTCUSD oracle (134 trades / `final_equity 46189.87730727451`); e2e 58/58, `mypy --strict` clean — stateless recompute, incremental opt-in deferred (W1-05).
**Plans**: 3 plans (3 waves — Wave 1: standalone catalog+primitives modules; Wave 2: base framework + all-or-broken run/test-path migration; Wave 3: byte-exact gate)
  - [x] 03-01-PLAN.md — NEW indicators.py typed adapter catalog (SMA/MACDHist/EMA/RSI, D-04/D-07/D-08) + NEW primitives.py (crossover/crossunder/is_above/is_below, D-01/D-02) + their Wave-0 unit tests (Wave 1, standalone)
  - [x] 03-02-PLAN.md — base.py framework (IndicatorHandle, self.indicator(), evaluate() seam, auto-warmup, D-03/D-06/D-08) + full lockstep migration of SMAMACDStrategy/EmptyStrategy/e2e fixtures/handler call-site + warmup==100 assertion (Wave 2)
  - [x] 03-03-PLAN.md — byte-exact phase gate: BTCUSD oracle (134/46189.87730727451 EXACT), e2e 58/58, full suite, mypy --strict, determinism double-run + signal_record snapshot verify (Wave 3)

### Phase 4: Composition & Config Interface
**Goal**: The system is composed through an engine-level composition API (declarative multi-strategy/multi-portfolio wiring, construction-time `ExchangeConfig` threading, a new `OrderConfig`), and every handler exposes a uniform runtime `update_config` so config can change at runtime in a live scenario — applied between event cycles, thread-safe.
**Depends on**: Phase 3 (consumes Phase 2's re-runnable `init()` for `StrategiesHandler.update_config`)
**Requirements**: COMP-01, COMP-02
**Success Criteria** (what must be TRUE):
  1. A declarative composition API (promoted from the `tests/e2e/scenario_spec.py` `ScenarioSpec` shape) wires multi-strategy/multi-portfolio runs with faithful construction-time `ExchangeConfig` threading (`TradingSystem` → `ExecutionHandler` → `SimulatedExchange`), replacing the Phase 7 D-14 post-construction conftest re-init seam, with a formalized `csv_paths` passthrough.
  2. A new `OrderConfig` Pydantic model is threaded into `OrderManager` (no more loose stringly-typed ctor params), folding the composition-root cleanups W4-02/03/05/06/07.
  3. Every handler/manager — `OrderHandler`/`OrderManager`, `StrategiesHandler`, `ExecutionHandler`, `PortfolioHandler`, `SimulatedExchange`, `BacktestBarFeed` — exposes a uniform `update_config` with one consistent signature (merge → `model_validate` → atomic-swap, unified return/error contract); for `StrategiesHandler` it re-validates → re-runs `init()` → re-derives warmup (consuming Phase 2's idempotent `init()`).
  4. Composition + config changes are byte-exact against the v1.1 E2E golden suite + BTCUSD oracle (134 trades / `final_equity 46189.87730727451`); e2e 58/58, `mypy --strict` clean — no result change, applied between event cycles never mid-cycle.
**Plans**: 5 plans (4 waves — Wave 1: foundational primitives; Wave 2: composition-root collapse (byte-exact-risk heart); Wave 3: update_config rollout (parallel); Wave 4: e2e collapse + byte-exact gate)
  - [x] 04-01-PLAN.md — CommissionEstimator Protocol (D-15) + OrderConfig (D-05) + SystemSpec promotion (D-01/D-02) + Wave-0 coercion/conformance tests (Wave 1, standalone)
  - [x] 04-02-PLAN.md — compose_engine + BacktestRunner + thin BacktestTradingSystem holder + build_backtest_system factory (D-03/D-04/D-14/D-14a); rng dedup (D-16); construction-time ExchangeConfig threading + symbol seeding (D-13); FeeModelCommissionEstimator late-binding (D-06/D-15); reporting lift (W4-07) (Wave 2)
  - [ ] 04-03-PLAN.md — shared deep_merge + canonical update_config on the 5 config-model handlers (Portfolio/PortfolioHandler/SimulatedExchange/ExecutionHandler/OrderManager-OrderHandler) + configure() fix (D-07/D-08/D-09/D-11) (Wave 3)
  - [ ] 04-04-PLAN.md — StrategiesHandler.update_config (re-validate→init()→warmup, D-09) + BacktestBarFeed.update_config raise-only interface-conformance (D-10/D-17) (Wave 3, parallel with 04-03)
  - [ ] 04-05-PLAN.md — e2e _build_and_run collapse onto build_backtest_system(spec) (D-01/D-13/D-14) + construction-site rename migration + byte-exact PHASE GATE (oracle 134/46189.87730727451, e2e 58/58, mypy --strict, determinism double-run) (Wave 4)

### Phase 5: Signal Contract & Reconcile (FRAGILE)
**Goal**: Complete the signal/order contract — a strategy specifies per-intent ENTRY price and `order_type`, action becomes `Side`-typed with the position snapshot threaded once — AND streamline the `on_fill` reconciliation / `should_release` flow, touching the FRAGILE `reconcile/` path once under a single owner-gated re-baseline + external cross-validation.
**Depends on**: Phase 4
**Requirements**: SIG-01, SIG-02, SIG-03, RECON-01
**Success Criteria** (what must be TRUE):
  1. A strategy can specify a per-intent limit or stop ENTRY price (no longer hardwired to the decision-bar close), threaded `SignalIntent → SignalEvent → Order.new_limit_order`/`new_stop_order` (SIG-01).
  2. A strategy can specify the entry `order_type` per intent (MARKET / LIMIT / STOP) rather than fixed per strategy instance, including the Phase 8 per-bar `order_type` override previously left unwired (SIG-02).
  3. `Order.action` and `_PendingBracket.action` are typed `Side` (not `str`), and the position snapshot is threaded once through admission→sizing (the double `get_position()` removed); W4-04 validator-overlap doc updated if the validator path is touched (SIG-03).
  4. The `on_fill` reconciliation + `should_release` release-in-`finally` flow is streamlined while the financial-integrity invariant holds — idempotent release on EVERY terminal reconciliation (EXECUTED→FILLED, CANCELLED→CANCELLED, REFUSED→REJECTED) (RECON-01).
  5. The new golden master is frozen ONLY after explicit owner sign-off with full attribution, validated by external cross-validation (`backtesting.py`/`backtrader`); `reconcile/` is touched once, not twice; `mypy --strict` clean; determinism double-run byte-identical.
**Plans**: TBD

### Phase 6: Order Lifecycle & Time-in-Force
**Goal**: Orders left resting at run end are disposed of via time-in-force instead of lingering PENDING — `Order.expire_order()` + `OrderStatus.EXPIRED` (which exist but are unwired) are wired on the backtest path — and the `create_order` second signal→order path is gated; owner-gated re-baseline.
**Depends on**: Phase 5
**Requirements**: LIFE-01
**Success Criteria** (what must be TRUE):
  1. At run end, orders left resting are transitioned to `EXPIRED` via `Order.expire_order()` on the backtest path; no order remains stuck PENDING after the run loop completes.
  2. The `create_order` second-path gating decision (W4-09) is resolved — the unvalidated 2nd signal→order path is routed through validation, or documented/removed with rationale.
  3. The result change is fully attributed (which previously-PENDING orders now expire, and any equity/metric impact) and the new golden master is frozen ONLY after explicit owner sign-off.
  4. `mypy --strict` clean; determinism double-run byte-identical; the rest of the e2e suite holds except where TIF intentionally changes a leaf's resting-order disposition (re-baselined with attribution).
**Plans**: TBD

<details>
<summary>✅ v1.0 — Backtest-Correctness Refactor (Phases 1-8) — SHIPPED 2026-06-08</summary>

8 phases (M1 → M5c), 62 plans. `SMA_MACD` runs end-to-end producing correct, deterministic,
cross-validated numbers (134 trades / `final_equity 46189.87730727451`). Full detail in
[`milestones/v1.0-ROADMAP.md`](./milestones/v1.0-ROADMAP.md).

</details>

<details>
<summary>✅ v1.1 — Backtest Trustworthiness: Breadth (Phases 1-9) — SHIPPED 2026-06-10</summary>

Phase numbering reset to Phase 1 for v1.1. Spine: codebase map → data → universe → E2E
framework → interface hardening → scenario waves. LONG-ONLY throughout; behavior-preserving
(v1.0 golden numbers NOT re-baselined). Full detail in
[`milestones/v1.1-ROADMAP.md`](./milestones/v1.1-ROADMAP.md).

- [x] Phase 1: Codebase Map & Clarity Baseline (2/2 plans) — completed 2026-06-09
- [x] Phase 2: Data Ingestion (1/1 plan) — completed 2026-06-09
- [x] Phase 3: Minimal Real Universe (3/3 plans) — completed 2026-06-09
- [x] Phase 4: E2E Harness & Framework (3/3 plans) — completed 2026-06-09
- [x] Phase 5: Strategy Interface Hardening & Signal Storage (3/3 plans) — completed 2026-06-09
- [x] Phase 6: Order Matching Scenarios (5/5 plans) — completed 2026-06-09
- [x] Phase 7: Cost, Sizing & SLTP Scenarios (4/4 plans) — completed 2026-06-10
- [x] Phase 8: Admission, Position Management & Cash Edges (3/3 plans) — completed 2026-06-10
- [x] Phase 9: Multi-Entity, Robustness & Metrics Edges (4/4 plans) — completed 2026-06-10

</details>

<details>
<summary>✅ v1.2 — Consolidation (Phases 1-6) — SHIPPED 2026-06-12</summary>

Behavior-preserving cleanup milestone — cleared the v1.1 cleanup-review backlog
(`V1.2-CLEANUP-REVIEW.md`, 46 findings) + the `CONCERNS.md` dead/fragile/tangled debt, byte-exact
against the golden master (134 trades / `final_equity 46189.87730727451`); re-baselined nothing.
Headline: `order_manager.py` decomposed 1279 → 210-line coordinator as pure code-motion. Full detail
in [`milestones/v1.2-ROADMAP.md`](./milestones/v1.2-ROADMAP.md).

- [x] Phase 1: Dead Code & Doc Hygiene (2/2 plans) — completed 2026-06-11
- [x] Phase 2: Locked-Decision Conformance (3/3 plans) — completed 2026-06-11
- [x] Phase 3: Hot-Path Performance (4/4 plans) — completed 2026-06-11
- [x] Phase 4: Type Modeling (5/5 plans) — completed 2026-06-11
- [x] Phase 5: Naming & Encapsulation (4/4 plans) — completed 2026-06-11
- [x] Phase 6: Order-Manager Decomposition (5/5 plans) — completed 2026-06-11

</details>

## Progress

**Shipped milestones** (full per-phase detail archived under `milestones/`):

| Milestone | Phases | Plans | Status | Shipped |
|-----------|--------|-------|--------|---------|
| v1.0 — Backtest-Correctness Refactor | 1-8 | 62 | ✅ Shipped | 2026-06-08 |
| v1.1 — Backtest Trustworthiness: Breadth | 1-9 | 28 | ✅ Shipped | 2026-06-10 |
| v1.2 — Consolidation | 1-6 | 23 | ✅ Shipped | 2026-06-12 |

**Active milestone — v1.3 Engine Surface Completion:**

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Engine Hygiene | 1/1 | Complete   | 2026-06-12 |
| 2. Strategy Authoring Surface | 3/3 | Complete   | 2026-06-12 |
| 3. Declared-Indicator Framework | 3/3 | Complete   | 2026-06-12 |
| 4. Composition & Config Interface | 2/5 | In Progress|  |
| 5. Signal Contract & Reconcile (FRAGILE) | 0/TBD | Not started | - |
| 6. Order Lifecycle & Time-in-Force | 0/TBD | Not started | - |

**Next:** Execute Phase 2 with `/gsd:execute-phase 2`.

## Backlog

> Future **milestone-level** seeds — intent + rationale only, NOT detailed plans.
> **Logical promotion order: v1.3 Engine Surface Completion (ACTIVE) → N+2 → N+3 → N+4**
> (the `N+x` labels carry the dependency order; the `999.x` decimals are just stable IDs
> and need not match the order). Promote one at a time with `/gsd:review-backlog` (or
> start it via `/gsd:new-milestone`); defer detailed planning until promotion so each
> milestone's findings can reshape the next.
>
> **Asset focus: crypto-first** (locked 2026-06-08). Crypto is USD-quoted and 24/7, so
> multi-currency accounting and trading-calendar / corporate-action work are deferred
> indefinitely — see the "Deferred: multi-asset" note at the end.
>
> **N+1 (Backtest Trustworthiness: Breadth) was promoted to milestone v1.1 (shipped
> 2026-06-10).** **v1.2 — Consolidation** (cleanup, Phases 1-6) shipped 2026-06-12. The Engine
> Surface Completion feature work (former Backlog Phase 999.5) was **promoted to the active
> milestone v1.3** — see the `## Phases` section above. The remaining `999.x` entries below are
> future milestones (N+2/N+3/N+4).

### Phase 999.4: N+2 — Margin, Leverage, Shorts & Trailing Stops (crypto) (BACKLOG)

**Goal:** The matching-engine / risk-execution milestone. Build the margin/liquidation
model the engine has deliberately deferred (D-08/D-09, DEF-01-C), unblocking shorts and
leverage, AND add engine-native trailing stops — all are stateful resting-order changes to
the same `MatchingEngine` surface, so they're done in one pass and share one golden master +
cross-validation, like M5. **Extends exactly the signal/order/composition surfaces v1.3
completes, which is why v1.3 lands first.**
**Requirements:** TBD
**Plans:** 0 plans

Scope (intent only):

- **Margin / liquidation model** in `MatchingEngine` + cash/position accounting — today
  there is NO liquidation model (DEF-01-C): an un-liquidated short can drive equity
  negative. Add maintenance margin + liquidation.

- **Unblock shorts** — remove the `LONG_ONLY`-only guard in `StrategiesHandler.add_strategy`
  AND fix the CR-01 cover-arm hole (`_resolve_signal_quantity` has no BUY-to-cover arm for
  a `SHORT_ONLY` book — a cover would fall through to entry sizing and flip the book long).

- **Leverage** + **levered Kelly** (fraction > 1 becomes expressible once margin exists).
- **Funding/carry** — crypto perp funding-rate accounting (the crypto-first analogue of
  forex swap / equity borrow).

- **Engine-native trailing stop** — new `TRAILING_STOP` `OrderType` + `MatchingEngine`
  ratchet logic (track running extreme, move the resting stop per bar). For the
  risk-management-heavy strategies. Look-ahead-safe per the `bar_feed.py` contract. Levered
  Kelly (>1) also unlocks here once margin exists.

- Config hooks already exist and are currently off: `allow_short_selling`, `enable_margin`
  (`config/portfolio.py`).

- **Real long/short PAIR TRADING** (flagship validation) — market-neutral cointegration/spread
  strategy: long one leg, short the other. Deferred here from v1.1 because it inherently needs
  shorts; it is the natural first real use of the short side once the guard is removed. (v1.1
  validates only a long-only multi-ticker proxy, if any.)

Rationale: shorts are the "short half" of the breadth N+1 wanted, but they are gated on
this accounting work — so it must come right after the engine-surface completion, before
infra/live. Crypto-first keeps it tractable (no multi-currency, no borrow-locate).

**Design note — trailing stops on venues WITHOUT native support (spans N+2 build → N+4 live):**
Native trailing is NOT universal (Binance spot lacks a clean native trailing; IBKR stocks
DO have `TRAIL`; many smaller venues / DEXs have none; ccxt coverage is spotty and semantics
vary — absolute vs % vs callback-rate, trigger basis last/mark/index). So make trailing a
**declared intent + an exchange capability**, decided in the execution layer (NOT the
strategy):

- Add a capability seam to `AbstractExchange` (e.g. `supports(OrderType.TRAILING_STOP)`).
  **Native-first** (survives client disconnect, lower latency, no rate-limit churn);
  **synthetic-fallback** otherwise.

- **Synthetic = always keep a REAL resting stop server-side; only the *ratchet* is
  client-side.** Place a normal STOP, recompute the trail each bar (ratchet favorable-only),
  and `MODIFY` the resting stop when the move exceeds a step threshold (rides the existing
  `OrderHandler.modify_order` → `OrderEvent(MODIFY)` round-trip). The venue fills the plain
  stop natively — the engine is NOT in the trigger path.

- Safety property: engine downtime ⇒ trail freezes but the last stop still protects. NEVER
  do the naive version (no resting stop; engine watches price and fires a market order on
  trigger) — downtime = zero protection.

- Risks to handle: modify churn vs rate limits (step threshold); cancel-replace gap on
  venues w/o atomic modify (place-new-then-cancel-old); overnight/weekend gaps (stop-limit
  caps fill price but risks no fill); venue min-distance rules.

- Backtest (`MatchingEngine`) models the IDEAL engine-native trail; synthetic-live has
  modify latency / step / gap behavior → backtest is slightly optimistic (a known sim-to-live
  gap to flag at N+4). Backtest and live should SHARE the trail-computation logic; only "how
  the stop rests" differs.

Plans:

- [ ] TBD (promote with /gsd:review-backlog when ready)

### Phase 999.2: N+3 — Persistence & Performance (BACKLOG)

**Goal:** Durable state + acceptable latency — the infra prerequisites for live trading.
Must come AFTER the correctness work (N+1, N+2) so we are not optimizing/persisting
unvalidated behavior.
**Requirements:** TBD
**Plans:** 0 plans

Scope (intent only):

- **#4 permanent PostgreSQL storage** (orders, signals, fills, equity).
  `PostgreSQLOrderStorage` is currently a `NotImplementedError` placeholder.

- **#5 profiler-guided performance pass** (profiler already used to spot hotspots).
- **#1 continued** — structural cleanup that the live-mode transition specifically demands.
- **FL-06** — SQL injection + hardcoded creds in `SqlHandler` (deferred out of v1.3; module
  is quarantined, belongs with persistence/SQL work).

Rationale: persistence + performance are cross-cutting infra, cleaner done together than
bolted on during the live push.

Plans:

- [ ] TBD (promote with /gsd:review-backlog when ready)

### Phase 999.3: N+4 — Live Trading Readiness (capstone) (BACKLOG)

**Goal:** Land the new operating mode as one coherent, testable thing. Do last — depends on
validated multi-scenario behavior (N+1), the margin model (N+2), durable storage + latency
(N+3), and a streaming data engine.
**Requirements:** TBD
**Plans:** 0 plans

Scope (intent only):

- **#6 real-time data engine** ready for live.
- **#2 live execution engine.**
- **#7 production-ready universe / screener.**
- **FL-13** — `LiveTradingSystem`/`TradingInterface` test coverage (deferred out of v1.3; the
  live surface, not the backtest engine surface).

Plans:

- [ ] TBD (promote with /gsd:review-backlog when ready)

> **Deferred: multi-asset (forex / equities / ETF).** Crypto-first (locked 2026-06-08)
> removes the near-term need. When revisited, this is itself ≥1 milestone and splits into:
> (a) an instrument/contract-spec abstraction (partly folded into N+1 config typing);
> (b) multi-currency accounting (quote→`base_currency` conversion) — needed for forex;
> (c) trading calendars/sessions + corporate actions (splits/dividends) — needed for
> equities/ETF, and a data-engine concern that pairs with N+4's #6.
>
> **Cross-cutting tooling note:** do NOT add third-party graphify / Understand-Anything
> tools — use the native `gsd-map-codebase` + `gsd-graphify`, which write artifacts into
> `.planning/` that integrate with the workflow and that Claude can read directly.
