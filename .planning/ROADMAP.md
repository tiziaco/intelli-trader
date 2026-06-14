# Roadmap: iTrader

## Milestones

- ✅ **v1.0 — Backtest-Correctness Refactor** — Phases 1-8 (shipped 2026-06-08)
- ✅ **v1.1 — Backtest Trustworthiness: Breadth** — Phases 1-9 (shipped 2026-06-10)
- ✅ **v1.2 — Consolidation** — Phases 1-6 (shipped 2026-06-12; numbering reset for v1.2, matching v1.1)
- ✅ **v1.3 — Engine Surface Completion** — Phases 1-6 (shipped 2026-06-14; numbering reset; promoted Backlog 999.5)
- 📋 **N+2 — Margin, Leverage, Shorts & Trailing Stops** — Backlog (planned, next)
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
[`v1.2-MILESTONE-AUDIT.md`](./milestones/v1.2-MILESTONE-AUDIT.md);
v1.3 — [`milestones/v1.3-ROADMAP.md`](./milestones/v1.3-ROADMAP.md) ·
[`v1.3-REQUIREMENTS.md`](./milestones/v1.3-REQUIREMENTS.md) ·
[`v1.3-MILESTONE-AUDIT.md`](./milestones/v1.3-MILESTONE-AUDIT.md).
v1.0 phase working dirs are archived under `milestones/v1.0-phases/`; v1.1 under `milestones/v1.1-phases/`; v1.2 under `milestones/v1.2-phases/`.

> **Note on milestone naming:** **v1.2 _Consolidation_** (shipped 2026-06-12) was a
> behavior-preserving cleanup milestone (Phases 1-6). The feature work formerly seeded as
> "v1.2 — Engine Surface Completion" was promoted to **v1.3 — Engine Surface Completion**
> (shipped 2026-06-14; it was Backlog Phase 999.5). The remaining `999.x` entries are future
> milestones (N+2/N+3/N+4).

## Phases

<details>
<summary>✅ v1.3 — Engine Surface Completion (Phases 1-6) — SHIPPED 2026-06-14</summary>

Phase numbering reset to Phase 1 (matching v1.1/v1.2). Completes the signal/order contracts, the
composition/config interface, and the declared-indicator + strategy-authoring surface — the
result-changing / new-framework items deferred out of v1.2 Consolidation (promoted Backlog 999.5).
Two re-baseline disciplines, both honored: byte-exact phases (1-4) held the v1.1 E2E golden suite +
BTCUSD oracle (134 trades / `final_equity 46189.87730727451`) byte-for-byte; owner-gated phases
(5-6) re-baselined only under explicit owner sign-off (tiziaco, 2026-06-13) + external
cross-validation. Full detail in [`milestones/v1.3-ROADMAP.md`](./milestones/v1.3-ROADMAP.md).

- [x] Phase 1: Engine Hygiene (1/1 plan) — completed 2026-06-12
- [x] Phase 2: Strategy Authoring Surface (3/3 plans) — completed 2026-06-12
- [x] Phase 3: Declared-Indicator Framework (3/3 plans) — completed 2026-06-12
- [x] Phase 4: Composition & Config Interface (5/5 plans) — completed 2026-06-12
- [x] Phase 5: Signal Contract & Reconcile (FRAGILE) (4/4 plans) — completed 2026-06-13
- [x] Phase 6: Order Lifecycle & Time-in-Force (4/4 plans) — completed 2026-06-13

</details>

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
| v1.3 — Engine Surface Completion | 1-6 | 20 | ✅ Shipped | 2026-06-14 |

**Next:** Start the next milestone with `/gsd:new-milestone` (next in promotion order: N+2 —
Margin, Leverage, Shorts & Trailing Stops; see Backlog below).

## Backlog

> Future **milestone-level** seeds — intent + rationale only, NOT detailed plans.
> **Logical promotion order: N+2 (next) → N+3 → N+4**
> (the `N+x` labels carry the dependency order; the `999.x` decimals are just stable IDs
> and need not match the order). Promote one at a time with `/gsd:review-backlog` (or
> start it via `/gsd:new-milestone`); defer detailed planning until promotion so each
> milestone's findings can reshape the next.
>
> **Asset focus: crypto-first** (locked 2026-06-08). Crypto is USD-quoted and 24/7, so
> multi-currency accounting and trading-calendar / corporate-action work are deferred
> indefinitely — see the "Deferred: multi-asset" note at the end.
>
> **N+1 (Backtest Trustworthiness: Breadth) shipped as v1.1 (2026-06-10).** **v1.2 —
> Consolidation** (cleanup, Phases 1-6) shipped 2026-06-12. The Engine Surface Completion feature
> work (former Backlog Phase 999.5) shipped as **v1.3** (2026-06-14). The remaining `999.x` entries
> below are future milestones (N+2/N+3/N+4); **N+2 is next**.

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
