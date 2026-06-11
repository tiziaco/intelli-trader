# Roadmap: iTrader

## Milestones

- ✅ **v1.0 — Backtest-Correctness Refactor** — Phases 1-8 (shipped 2026-06-08)
- ✅ **v1.1 — Backtest Trustworthiness: Breadth** — Phases 1-9 (shipped 2026-06-10)
- 📋 **v1.2 — Engine Surface Completion** — Backlog (planned, promote ahead of N+2)
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
v1.0 phase working dirs are archived under `milestones/v1.0-phases/`; v1.1 phase dirs remain under `phases/` (archive retroactively with `/gsd:cleanup`).

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

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Codebase Map & Clarity Baseline | v1.1 | 2/2 | Complete | 2026-06-09 |
| 2. Data Ingestion | v1.1 | 1/1 | Complete | 2026-06-09 |
| 3. Minimal Real Universe | v1.1 | 3/3 | Complete | 2026-06-09 |
| 4. E2E Harness & Framework | v1.1 | 3/3 | Complete | 2026-06-09 |
| 5. Strategy Interface Hardening & Signal Storage | v1.1 | 3/3 | Complete | 2026-06-09 |
| 6. Order Matching Scenarios | v1.1 | 5/5 | Complete | 2026-06-09 |
| 7. Cost, Sizing & SLTP Scenarios | v1.1 | 4/4 | Complete | 2026-06-10 |
| 8. Admission, Position Management & Cash Edges | v1.1 | 3/3 | Complete | 2026-06-10 |
| 9. Multi-Entity, Robustness & Metrics Edges | v1.1 | 4/4 | Complete | 2026-06-10 |

## Backlog

> Future **milestone-level** seeds — intent + rationale only, NOT detailed plans.
> **Logical promotion order: N+1 → Engine Surface Completion (999.5) → N+2 → N+3 → N+4**
> (the `N+x` labels carry the dependency order; the `999.x` decimals are just stable IDs
> and need not match the order). Promote one at a time with `/gsd:review-backlog` (or
> start it via `/gsd:new-milestone`); defer detailed planning until promotion so each
> milestone's findings can reshape the next.
>
> **Asset focus: crypto-first** (locked 2026-06-08). Crypto is USD-quoted and 24/7, so
> multi-currency accounting and trading-calendar / corporate-action work are deferred
> indefinitely — see the "Deferred: multi-asset" note at the end.
>
> **N+1 (Backtest Trustworthiness: Breadth) was promoted to active milestone v1.1 on
> 2026-06-09** — see the `## Phases` section above. Its former backlog seed (Phase 999.1)
> is retired.

### Phase 999.5: v1.2 — Engine Surface Completion (BACKLOG)

**Goal:** Consolidate the missing engine-surface features and deferred fixes that surfaced
during v1.1 execution into one milestone — complete the signal/order contracts, give the
system a real composition/config interface, and land the indicator abstraction — BEFORE
N+2 builds margin/shorts on top of these same surfaces.
**Requirements:** TBD
**Plans:** 0 plans

Scope (intent only — consolidated from the v1.1 capture registers):

- **(a) Signal contract completion** — explicit per-intent limit/stop ENTRY price and
  per-intent `order_type` on the signal contract (`SignalIntent` → `SignalEvent` →
  `Order.new_limit_order`/`new_stop_order`). Captured in Phase 6 + 7 CONTEXT deferred
  sections as *"a real missing PRODUCTION feature"*: strategies cannot place a limit/stop
  entry at an arbitrary price (hardwired to the decision-bar close), and `order_type` is
  fixed per strategy instance. Owner-gated (result-risky). Includes the Phase 8 carryover
  per-bar `order_type` override left unwired in the e2e emitter.
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
  the feed have none. Related cleanup item: `BaseStrategyConfig` relocation from
  `strategy_handler/config.py` to `itrader/config/` (SYN-02 — cleanup-eligible, coordinate
  here only if (b) lands first).
- **(c) Declared-indicator framework** — indicator abstraction on the strategy base with
  auto-derived warmup (à la nautilus `register_indicator_for_bars` / LEAN `SetWarmUp` /
  backtrader auto-min-period), so authors stop hand-setting `max_window`. Captured in
  05-CONTEXT.md deferred ideas; note it is a genuine model shift (stateless
  recompute-from-window → optionally stateful incremental) — design carefully against the
  pure-alpha D-12 contract.
- **(d) Order lifecycle completion** — wire run-end resting-order disposition /
  time-in-force (`Order.expire_order()` + `OrderStatus.EXPIRED` exist but are unwired on
  the backtest path; orders currently remain PENDING at run end — result-changing,
  owner-gated). Plus the v1.1 fix-list stragglers that slipped their eligible phases:
  FL-01 (7 bare `raise ValueError` sites in `portfolio_handler/portfolio.py` — tagged
  eligible Phase 8, not fixed) and FL-02 (`portfolio_id: int` annotation carry-over on
  Signal/Order/Fill events — tagged eligible Phase 5, not fixed).

Sources: `phases/05-…/05-CONTEXT.md`, `phases/06-…/06-CONTEXT.md`,
`phases/07-…/07-CONTEXT.md` `<deferred>` sections; `codebase/FIX-LIST.md` (FL-01/FL-02);
Phase 4 RESEARCH Open Q1; Phase 8 DISCUSSION-LOG carryovers.

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
