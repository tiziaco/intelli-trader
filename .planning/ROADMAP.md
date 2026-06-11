# Roadmap: iTrader

## Milestones

- ✅ **v1.0 — Backtest-Correctness Refactor** — Phases 1-8 (shipped 2026-06-08)
- ✅ **v1.1 — Backtest Trustworthiness: Breadth** — Phases 1-9 (shipped 2026-06-10)
- 🚧 **v1.2 — Consolidation** — Phases 1-6 (in progress, started 2026-06-11; numbering reset for v1.2, matching v1.1)
- 📋 **Engine Surface Completion** — Backlog Phase 999.5 (planned, promote next, ahead of N+2)
- 📋 **N+2 — Margin, Leverage, Shorts & Trailing Stops** — Backlog (planned)
- 📋 **N+3 — Persistence & Performance** — Backlog (planned)
- 📋 **N+4 — Live Trading Readiness** — Backlog (planned)

Full milestone detail (phase goals, success criteria, per-plan breakdown) is archived per milestone:
v1.0 — [`milestones/v1.0-ROADMAP.md`](./milestones/v1.0-ROADMAP.md) ·
[`v1.0-REQUIREMENTS.md`](./milestones/v1.0-REQUIREMENTS.md) ·
[`v1.0-MILESTONE-AUDIT.md`](./milestones/v1.0-MILESTONE-AUDIT.md);
v1.1 — [`milestones/v1.1-ROADMAP.md`](./milestones/v1.1-ROADMAP.md) ·
[`v1.1-REQUIREMENTS.md`](./milestones/v1.1-REQUIREMENTS.md) ·
[`v1.1-MILESTONE-AUDIT.md`](./milestones/v1.1-MILESTONE-AUDIT.md).
v1.0 phase working dirs are archived under `milestones/v1.0-phases/`; v1.1 phase dirs are archived under `milestones/v1.1-phases/`.

> **Note on milestone naming:** the **active v1.2 is _Consolidation_** — a behavior-preserving
> cleanup milestone (this roadmap, Phases 1-6). The feature work formerly seeded as
> "v1.2 — Engine Surface Completion" was **deferred** to the next milestone and remains in the
> Backlog as Phase 999.5; it will be promoted after v1.2 Consolidation ships, ahead of N+2.

## Phases

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

### 🚧 v1.2 — Consolidation (In Progress)

**Milestone Goal:** Put the engine in order — clear the v1.1 cleanup-review backlog
(`.planning/codebase/V1.2-CLEANUP-REVIEW.md`, 46 findings) and the `CONCERNS.md` dead/fragile/
tangled debt — **byte-exact against the golden master** — so the next milestone's engine-surface
features build on a clean, decomposed foundation. **Behavior-preserving: re-baselines NOTHING.**

Phase numbering starts at Phase 1 (numbering reset for v1.2, matching v1.1). Phases follow the
V1.2-CLEANUP-REVIEW §6 oracle-checkable batch sequence: dead-code/docs → locked-decision
conformance → hot-path perf → type modeling → naming/encapsulation → the isolated
`order_manager.py` god-module split (last, FRAGILE, dedicated). Result-changing / new-framework
items (SIG/COMP/IND/LIFE) are explicitly deferred to the next milestone (Backlog Phase 999.5).

**Milestone-wide gate (applies to EVERY phase):**

- `pytest tests/integration` byte-exact oracle held — **134 trades / `final_equity 46189.87730727451`** (no re-baseline)
- `pytest tests/e2e -m e2e` **58/58 green** (no leaf re-baselined); full suite green
- **`mypy --strict` clean** across all source files
- No new float-for-money; single UUIDv7 ID scheme (no second `uuid4()` on the run path)
- **FRAGILE-zone rule:** any touch of `order_manager.py` fill-reconciliation / reservation-release
  requires the golden-master re-run; the terminal-status / `should_release` / `finally`-release
  interplay must never change.

- [x] **Phase 1: Dead Code & Doc Hygiene** - Delete dead ABCs / `OrderBase` / dead numpy import; correct stale CONCERNS/ROADMAP notes; document the config-enum / run-mode / indentation conventions (completed 2026-06-11)
- [x] **Phase 2: Locked-Decision Conformance** - `Optional[Decimal]` money API; Decimal `_min/_max_order_size` (float-for-money fix); retire the `uuid4()` second ID scheme (completed 2026-06-11)
- [x] **Phase 3: Hot-Path Performance** - Eliminate per-tick storage copies + add snapshot accessors; drop `Decimal(str(Decimal))` re-wraps + duplicated per-tick work; prebuilt `Bar` lookups + guarded MACD (completed 2026-06-11)
- [x] **Phase 4: Type Modeling** - Freeze decision/result dataclasses; class-based `OrderStatus`/`OrderCommand` + new `core/enums`; enum-member dispatch; relocate `BaseStrategyConfig` to `config/` (completed 2026-06-11)
- [ ] **Phase 5: Naming & Encapsulation** - `events_queue→global_queue`; strategy PascalCase + `*_window`; publicize `routes`; `register_symbol()` API; test hygiene through public APIs
- [ ] **Phase 6: Order-Manager Decomposition** - Split the 1279-line `order_manager.py` god-module into `admission/`/`brackets/`/`reconcile/` collaborators — pure code-motion, isolated, byte-exact (FRAGILE)

### 📋 Engine Surface Completion (Planned — Backlog Phase 999.5)

**Milestone Goal:** Complete the signal/order contracts, the composition/config interface, the
declared-indicator framework, and order-lifecycle/TIF — the result-changing / new-framework items
deferred out of v1.2 Consolidation. Promote after v1.2, ahead of N+2. See Backlog Phase 999.5.

## Phase Details

### Phase 1: Dead Code & Doc Hygiene

**Goal**: Remove dead code and correct stale documentation so the tree and the planning docs tell the truth — oracle-dark, pure deletions plus doc edits.
**Depends on**: v1.1 shipped (Phase 9, now archived)
**Requirements**: DEAD-01, DEAD-02
**Success Criteria** (what must be TRUE):

  1. The dead ABCs (`AbstractPortfolioHandler`/`AbstractPortfolio`/`AbstractPosition` + orphan `get_last_close`), the unused `OrderBase`, and the dead `import numpy as np` in `portfolio.py` are deleted with zero importer breakage; full suite green.
  2. Stale docs are corrected: the CONCERNS.md `screener_event_handler` item is closed (file already gone), and ROADMAP 999.5-(d) FL-01/FL-02 text reads "done".
  3. CONVENTIONS/CLAUDE documents the config-enum-in-`config/` exception, the broad-`except` run-mode policy (backtest fail-fast vs live publish-and-continue), the tab/space indentation hazard, and the dual-layer validator overlap as justified-by-decision (not removed).
  4. Golden master byte-exact (134 trades / `final_equity 46189.87730727451`); `mypy --strict` clean; 58/58 e2e green.

**Plans**: 2 plans

Plans:

- [x] 01-01-PLAN.md (01-code-deletions) — delete 3 dead ABCs + OrderBase + dead numpy import; importer sweep; oracle byte-exact (DEAD-01)
- [x] 01-02-PLAN.md (02-doc-hygiene) — trim stale CONCERNS/ROADMAP entries; document 4 conventions in CONVENTIONS/CLAUDE (DEAD-02)

### Phase 2: Locked-Decision Conformance

**Goal**: Close the three bounded locked-decision violations (float money at the API boundary, the float-for-money inconsistency at the order-size boundary, the second `uuid4()` ID scheme) without changing results.
**Depends on**: Phase 1
**Requirements**: DEC-01, DEC-02, DEC-03
**Success Criteria** (what must be TRUE):

  1. `modify_order`/`cancel_order` public API price/quantity params are typed `Optional[Decimal]`, not `Optional[float]` — no float-for-money at a domain boundary.
  2. `_min/_max_order_size` are carried as `Decimal` end-to-end (no float-for-money inconsistency at the exchange size-limit boundary); `validate_order` runs `Decimal`-vs-`Decimal` on the golden path (via `_admit_order` — it is NOT bypassed); the symmetric `< _min` below-minimum REFUSED branch is regression-covered (D-08); and the oracle is byte-exact. (D-07: the earlier comparison-crash framing was a misdiagnosis — Decimal-vs-float COMPARISON works in Py3, only arithmetic raises and there is none; the fix is float-for-money consistency, not a crash fix.)
  3. Correlation IDs use the single UUIDv7 `idgen` scheme (or a deterministic counter); `uuid.uuid4()` is gone from the run path (single ID scheme restored, no non-deterministic crypto RNG).
  4. Golden master byte-exact (134 trades / `final_equity 46189.87730727451`); `mypy --strict` clean; 58/58 e2e green; determinism double-run byte-identical.

**Plans**: 3 plans

Plans:

- [x] 02-01-PLAN.md (01-decimal-money-api) — retype modify_order/cancel_order money params Optional[float]→Optional[Decimal] (facade + manager); Decimal boundary callers (DEC-01)
- [x] 02-02-PLAN.md (02-decimal-order-size) — drop float() wraps on _min/_max_order_size (Decimal end-to-end); reframe/correct the D-07 "latent TypeError" misdiagnosis; below-minimum REFUSED branch test (DEC-02)
- [x] 02-03-PLAN.md (03-uuidv7-correlation-id) — retire uuid4() correlation id → single UUIDv7 idgen scheme; CorrelationId NewType + generate_correlation_id; CorrelationId|None event field (DEC-03)

### Phase 3: Hot-Path Performance

**Goal**: Eliminate the dominant per-tick perf costs — defensive storage copies, redundant Decimal re-wraps, duplicated per-tick work, and per-tick Bar/MACD churn — with bit-identical values.
**Depends on**: Phase 2
**Requirements**: PERF-01, PERF-02, PERF-03
**Success Criteria** (what must be TRUE):

  1. In-memory portfolio storage no longer copies the snapshot list / position dicts per tick under the D-19 single-writer contract; `snapshot_count()` / `get_latest_snapshot()` accessors replace the never-firing per-tick trim copy. (D-04: the `*_snapshot()` variant is declined — a query-based live backend is copy-safe for free, so no speculative API was added.)
  2. Redundant `Decimal(str(Decimal))` re-wraps on the mark-to-market/equity path and duplicated per-tick work (`open_position_count` ×2, `is_connected` ×2–3, premature `on_fill` guard allocation, load-time copy) are eliminated.
  3. MACD is computed inside the SMA guard (not unconditionally before it), and `BacktestBarFeed` serves prebuilt `Bar`s instead of 5 `Decimal(str(...))` conversions per symbol per tick; values bit-identical.
  4. Golden master byte-exact (134 trades / `final_equity 46189.87730727451`); `mypy --strict` clean; 58/58 e2e green.

**Plans**: 4 plans

Plans:
**Wave 1**

- [x] 03-01-PLAN.md — PERF-01: storage copy-drop + read-only-view ABC contract + snapshot accessors (D-03/D-04/D-06)
- [x] 03-02-PLAN.md — PERF-03: eager-prebuild Bars in BacktestBarFeed; current_bars() dict lookup, no per-tick Bar.from_row (D-07/08/09)
- [x] 03-03-PLAN.md — PERF-02: mechanical transforms (W1-08/03/14/07/09; W1-13 descoped per D-10)

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 03-04-PLAN.md — PERF-03 W1-12 MACD-guard reorder (oracle-only, D-02) + doc corrections + byte-exact phase gate

**Cross-cutting constraints:**

- Golden master stays byte-exact: 134 trades / final_equity 46189.87730727451

### Phase 4: Type Modeling

**Goal**: Make closed vocabularies enums and decision/result objects frozen facts — bring `OrderStatus`/`OrderCommand` and four new vocabularies onto the canonical class-based enum form, freeze the engine's decision DTOs, harden config-boundary validation, and co-locate the strategy config base.
**Depends on**: Phase 3
**Requirements**: TYPE-01, TYPE-02, TYPE-03, TYPE-04, TYPE-05
**Success Criteria** (what must be TRUE):

  1. `FillDecision`, `CancelDecision`, `OperationResult`, `SignalProcessingResult`, and `_PendingBracket` are `frozen=True, slots=True, kw_only=True` facts.
  2. Fee/slippage model dispatch compares enum members with `assert_never` exhaustiveness (not `.value` strings); `rebalance_frequency` is validated at the Pydantic boundary; the `PortfolioConfig.portfolio_id` false affordance is removed or documented; and the `OrderHandler`/`OrderManager` public-API `order_id: int` / `portfolio_id: int` method-parameter annotations are retyped to `OrderId` / `PortfolioId` (single-UUIDv7 conformance; carried over from Phase 2 DEF-02-03).
  3. `ErrorSeverity`, `OrderOperationType`, `OrderTriggerSource`, and `market_execution` are class-based string-valued enums in `core/enums/` (with `_missing_` + `<domain>_<type>_map` where they cross a boundary), and `OrderStatus`/`OrderCommand` are converted to the same canonical form with working `order_status_map` `.value` lookups (int→string value change audited against serialization/tests).
  4. The `BaseStrategyConfig` base contract lives in `itrader/config/strategy.py` (re-exported via `config/__init__.py`), consistent with `ExchangeConfig`/`PortfolioConfig`/`SystemConfig`; all importers updated.
  5. Golden master byte-exact (134 trades / `final_equity 46189.87730727451`); `mypy --strict` clean; 58/58 e2e green.

**Plans**: 5 plans

Plans:
**Wave 1** *(parallel — no shared files)*

- [x] 04-01-PLAN.md — TYPE-01: freeze FillDecision/CancelDecision + OperationResult/SignalProcessingResult (tuple fields) (D-07)
- [x] 04-02-PLAN.md — TYPE-02/03: ErrorSeverity enum; enum-member fee/slippage dispatch (assert_never); rebalance_frequency validation; portfolio_id removal; portfolio/events/validators id NewTypes (D-05/08/09/10/11/12/13)
- [x] 04-03-PLAN.md — TYPE-05: relocate BaseStrategyConfig to config/strategy.py; co-locate concrete configs (tab re-indent); update D-16 importers (D-14/15/16)

**Wave 2** *(FRAGILE order-domain core; blocked on Wave 1)*

- [x] 04-04-PLAN.md — TYPE-04/03/01: class-based OrderStatus/OrderCommand + D-02 .name audit; OrderOperationType/OrderTriggerSource value-equal swap; frozen _PendingBracket (D-01/02/03/04/07)

**Wave 3** *(shares order_manager.py/order.py with Wave 2; blocked on 04-04)*

- [x] 04-05-PLAN.md — TYPE-03/02: market_execution enum (ctor-coerced, no OrderConfig); order-domain id NewType retypes (D-06/12/13)

### Phase 5: Naming & Encapsulation

**Goal**: Make names consistent and close the encapsulation gaps — uniform `global_queue`/count-by-status naming, PascalCase strategies with `*_window` config, a public `routes` accessor, a real `register_symbol()`/`update_config` exchange seam, and tests that assert through public APIs.
**Depends on**: Phase 4
**Requirements**: NAME-01, NAME-02, NAME-03, NAME-04
**Success Criteria** (what must be TRUE):

  1. `OrderHandler` names its queue `global_queue` (constructor param + attribute), not `events_queue`, and the count-by-status operation has a single precise name across façade and storage.
  2. Strategy classes are PascalCase (`SMAMACDStrategy` / `EmptyStrategy`) and strategy-config windows are `fast_window`/`slow_window`/`signal_window` (not `FAST`/`SLOW`/`WIN`); all importers (scripts/tests/crossval/e2e) are updated.
  3. `EventHandler` routes are reachable through a public name/accessor (not `_routes`); `SimulatedExchange` exposes `register_symbol()` + a complete `update_config` seam, and production code no longer mutates `_supported_symbols`/`_min_order_size` directly.
  4. Tests assert through public query APIs, not `_by_id`/`_storage`/`_routes`/`_generate_correlation_id` internals.
  5. Golden master byte-exact (134 trades / `final_equity 46189.87730727451`); `mypy --strict` clean; 58/58 e2e green.

**Plans**: 4 plans

Plans:
**Wave 1** *(parallel — no shared files; oracle-dark + the load-bearing strategy re-run)*

- [ ] 05-01-PLAN.md — NAME-01: queue events_queue→global_queue (D-02) + canonical count_orders_by_status across façade/manager/Protocol/2 backends (D-01)
- [ ] 05-02-PLAN.md — NAME-03: public routes field rename (D-06) + register_symbol() seam closing the _supported_symbols direct-mutation gap + update_config completeness audit (D-07/D-08)
- [ ] 05-03-PLAN.md — NAME-02: PascalCase SMAMACDStrategy/EmptyStrategy + fast_window/slow_window/signal_window config (defaults 6/12/3); all run-path importers updated; load-bearing golden re-run (D-03/D-04)

**Wave 2** *(test hygiene — depends on the renamed public surfaces from 05-01 + 05-02)*

- [ ] 05-04-PLAN.md — NAME-04: tests assert through public APIs (routes / get_order_by_id / count_orders_by_status / emitted correlation_id / register_symbol), not _routes/_by_id/_generate_correlation_id/_supported_symbols internals (D-09)

### Phase 6: Order-Manager Decomposition

**Goal**: Decompose the 1279-line `order_manager.py` god-module into focused collaborators under `order_handler/` (mirroring the `portfolio_handler/` manager layout) — pure code-motion, no semantics change, dedicated and isolated as the LAST phase so the FRAGILE fill-reconciliation / reservation-release path is never bundled with behavior fixes.
**Depends on**: Phase 5 (and ALL other v1.2 phases — this is the dedicated late, isolated phase; nothing else ships in it)
**Requirements**: MOD-01
**Success Criteria** (what must be TRUE):

  1. `order_manager.py` is decomposed into `admission/`, `brackets/`, and `reconcile/` collaborators under `order_handler/`, mirroring the `portfolio_handler/` manager layout — as pure code-motion with no semantics change.
  2. The terminal-status / `should_release` / `finally`-release interplay (CONCERNS.md Fragile Areas) is byte-for-byte unchanged in behavior; `release` idempotency preserved.
  3. This is the sole change in the phase — no enum, naming, perf, or doc change rides along (FRAGILE-zone isolation rule).
  4. Golden master byte-exact (134 trades / `final_equity 46189.87730727451`); `mypy --strict` clean; 58/58 e2e green; determinism double-run byte-identical.

**Plans**: TBD

Plans:

- [ ] TBD (decompose with /gsd:plan-phase 6)

## Progress

**Execution Order:**
v1.2 phases execute in numeric order: 1 → 2 → 3 → 4 → 5 → 6 (Phase 6 is the dedicated,
isolated, LAST phase — the `order_manager.py` god-module split).

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Dead Code & Doc Hygiene | v1.2 | 2/2 | Complete   | 2026-06-11 |
| 2. Locked-Decision Conformance | v1.2 | 3/3 | Complete   | 2026-06-11 |
| 3. Hot-Path Performance | v1.2 | 4/4 | Complete   | 2026-06-11 |
| 4. Type Modeling | v1.2 | 5/5 | Complete   | 2026-06-11 |
| 5. Naming & Encapsulation | v1.2 | 0/TBD | Not started | - |
| 6. Order-Manager Decomposition | v1.2 | 0/TBD | Not started | - |

## Backlog

> Future **milestone-level** seeds — intent + rationale only, NOT detailed plans.
> **Logical promotion order: Engine Surface Completion (999.5) → N+2 → N+3 → N+4**
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
> 2026-06-10).** **v1.2 — Consolidation** (cleanup, Phases 1-6) is now the active milestone —
> see the `## Phases` section above. The Engine Surface Completion feature work (Phase 999.5
> below) was deferred out of v1.2 and is the next milestone to promote.

### Phase 999.5: Engine Surface Completion (BACKLOG — promote next, after v1.2 Consolidation)

**Goal:** Consolidate the missing engine-surface features and deferred fixes that surfaced
during v1.1 execution into one milestone — complete the signal/order contracts, give the
system a real composition/config interface, and land the indicator abstraction — BEFORE
N+2 builds margin/shorts on top of these same surfaces. (These are the **result-changing /
new-framework** items deferred out of v1.2 Consolidation so the cleanup foundation lands first.)
**Requirements:** SIG-01, SIG-02, COMP-01, IND-01, LIFE-01 (see `REQUIREMENTS.md` v-next section)
**Plans:** 0 plans

Scope (intent only — consolidated from the v1.1 capture registers):

- **(a) Signal contract completion** — explicit per-intent limit/stop ENTRY price and
  per-intent `order_type` on the signal contract (`SignalIntent` → `SignalEvent` →
  `Order.new_limit_order`/`new_stop_order`). Captured in Phase 6 + 7 CONTEXT deferred
  sections as *"a real missing PRODUCTION feature"*: strategies cannot place a limit/stop
  entry at an arbitrary price (hardwired to the decision-bar close), and `order_type` is
  fixed per strategy instance. Owner-gated (result-risky). Includes the Phase 8 carryover
  per-bar `order_type` override left unwired in the e2e emitter. Also folds the
  V1.2-CLEANUP-REVIEW deferrals **W2-02** (`Order.action`/`_PendingBracket.action`
  `str`→`Side`) and **W1-11** (position-snapshot threading through admission→sizing), both
  FRAGILE and coupled to this contract; and **W4-04** validator-overlap documentation if the
  validator path is touched here.

- **(b) System composition/config interface** — promote the `tests/e2e/scenario_spec.py`
  `ScenarioSpec` shape into an engine-level composition API: declarative multi-strategy /
  multi-portfolio wiring, faithful construction-time `ExchangeConfig` threading through
  `TradingSystem` → `ExecutionHandler` → `SimulatedExchange` (replacing the Phase 7 D-14
  post-construction conftest re-init seam / Phase 4 Open Q1), and formalization of the
  `csv_paths` manual passthrough (Phase 3). Today this interface exists only as a
  test-harness workaround. Also includes a **uniform per-handler runtime config-update
  surface** (owner-noted 2026-06-11, V1.2-CLEANUP-REVIEW SYN-03): today only
  `PortfolioHandler.update_config` / `Portfolio.update_config` /
  `SimulatedExchange.update_config` exist, with inconsistent signatures (`Dict` updates vs
  `**kwargs`); `OrderHandler`/`OrderManager`, `StrategiesHandler`, `ExecutionHandler`, and
  the feed have none. Related: the order domain has **no Pydantic config model at all**
  (no `config/order.py`; `OrderManager` takes loose ctor params incl. stringly-typed
  `market_execution` — V1.2-CLEANUP-REVIEW SYN-05) — create `OrderConfig` and thread it
  here alongside `ExchangeConfig`. Folds the V1.2-CLEANUP-REVIEW composition-root deferrals
  **W4-02/03/05/06/07**. (Note: `BaseStrategyConfig` relocation — SYN-02 — was pulled FORWARD
  into v1.2 Consolidation Phase 4 / TYPE-05, so it is no longer pending here.)

- **(c) Declared-indicator framework** — indicator abstraction on the strategy base with
  auto-derived warmup (à la nautilus `register_indicator_for_bars` / LEAN `SetWarmUp` /
  backtrader auto-min-period), so authors stop hand-setting `max_window`. Captured in
  05-CONTEXT.md deferred ideas; note it is a genuine model shift (stateless
  recompute-from-window → optionally stateful incremental) — design carefully against the
  pure-alpha D-12 contract. Folds the V1.2-CLEANUP-REVIEW deferral **W1-05** (incremental
  SMA/MACD state); the W1-12 control-flow reorder was pulled forward into v1.2 Phase 3.

- **(d) Order lifecycle completion** — wire run-end resting-order disposition /
  time-in-force (`Order.expire_order()` + `OrderStatus.EXPIRED` exist but are unwired on
  the backtest path; orders currently remain PENDING at run end — result-changing,
  owner-gated). Includes the `create_order` second-path gating decision (V1.2-CLEANUP-REVIEW
  **W4-09**). FL-01/FL-02 closed in v1.1 (quick 260610-sjp).

Sources: `phases/05-…/05-CONTEXT.md`, `phases/06-…/06-CONTEXT.md`,
`phases/07-…/07-CONTEXT.md` `<deferred>` sections; `codebase/FIX-LIST.md` (FL-01/FL-02);
`codebase/V1.2-CLEANUP-REVIEW.md` §6 "Deferred to 999.5"; Phase 4 RESEARCH Open Q1;
Phase 8 DISCUSSION-LOG carryovers.

Rationale: v1.1 proved these gaps empirically — every E2E scenario phase had to work
around the hardwired entry price, the fixed per-strategy order type, and the missing
composition interface (ScenarioSpec is the evidence). N+2 (margin/leverage/shorts/trailing
stops) extends exactly these signal/order/composition surfaces, so completing them first
avoids building new behavior on known-incomplete contracts. Promote AHEAD of N+2.
Result-changing items ((a), (d) TIF) follow the established owner-gated re-baseline
discipline; (b)/(c) should stay byte-exact against the full v1.1 E2E golden suite.

Plans:

- [ ] TBD (promote with /gsd:review-backlog when ready)

### Phase 999.4: N+2 — Margin, Leverage, Shorts & Trailing Stops (crypto) (BACKLOG)

**Goal:** The matching-engine / risk-execution milestone. Build the margin/liquidation
model the engine has deliberately deferred (D-08/D-09, DEF-01-C), unblocking shorts and
leverage, AND add engine-native trailing stops — all are stateful resting-order changes to
the same `MatchingEngine` surface, so they're done in one pass and share one golden master +
cross-validation, like M5.
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
this accounting work — so it must come right after N+1, before infra/live. Crypto-first
keeps it tractable (no multi-currency, no borrow-locate).

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
