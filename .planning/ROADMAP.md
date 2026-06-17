# Roadmap: iTrader

## Milestones

- ✅ **v1.0 — Backtest-Correctness Refactor** — Phases 1-8 (shipped 2026-06-08)
- ✅ **v1.1 — Backtest Trustworthiness: Breadth** — Phases 1-9 (shipped 2026-06-10)
- ✅ **v1.2 — Consolidation** — Phases 1-6 (shipped 2026-06-12; numbering reset for v1.2, matching v1.1)
- ✅ **v1.3 — Engine Surface Completion** — Phases 1-6 (shipped 2026-06-14; numbering reset; promoted Backlog 999.5)
- 🚧 **v1.4 — Margin, Leverage, Shorts & Trailing Stops** — Phases 1-6 (ACTIVE, started 2026-06-14; numbering reset; promoted Backlog 999.4 / N+2)
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
v1.0 phase working dirs are archived under `milestones/v1.0-phases/`; v1.1 under `milestones/v1.1-phases/`; v1.2 under `milestones/v1.2-phases/`; v1.3 under `milestones/v1.3-phases/`.

> **Note on milestone naming:** **v1.2 _Consolidation_** (shipped 2026-06-12) was a
> behavior-preserving cleanup milestone (Phases 1-6). The feature work formerly seeded as
> "v1.2 — Engine Surface Completion" was promoted to **v1.3 — Engine Surface Completion**
> (shipped 2026-06-14; it was Backlog Phase 999.5). **v1.4 — Margin, Leverage, Shorts &
> Trailing Stops** (ACTIVE) promotes Backlog Phase 999.4 (N+2). The remaining `999.x` entries
> are future milestones (N+3/N+4).

## Phases

### v1.4 — Margin, Leverage, Shorts & Trailing Stops (ACTIVE)

Phase numbering reset to Phase 1 (matching v1.1/v1.2/v1.3; v1.3 phase dirs archived to
`milestones/v1.3-phases/`, so the new `01-*..06-*` dirs do not collide — only the `999.2`/`999.3`
backlog seed dirs remain alongside). This is an **owner-gated, result-changing** milestone (M5-style):
enabling shorts/leverage/liquidation changes results, so each result-changing phase re-baselines the
golden master ONLY after explicit owner sign-off + external cross-validation
(`backtesting.py` 0.6.5 / `backtrader` 1.9.78.123). The existing SMA_MACD spot oracle
(134 trades / `final_equity 46189.87730727451`) stays byte-exact except where shorts/leverage
legitimately change a leaf. `mypy --strict` clean, Decimal end-to-end, determinism double-run
byte-identical hold throughout. Full design: PROJECT.md "Current Milestone: v1.4" + the (promoted)
999.4 scoping block in the Backlog below + `notes/margin-leverage-shorts-999.4.md`.

- [x] **Phase 1: Instrument Value Object** - Per-symbol precision/lot/margin source replacing `_INSTRUMENT_SCALES`; BTCUSD stays declared 8dp (byte-exact behavioral gate) — completed 2026-06-15
- [x] **Phase 2: Margin Accounting & Leverage** - Reserve `initial_margin = notional/leverage`, reject over-leverage, track maintenance margin, levered Kelly > 1 (owner-gated) — completed 2026-06-15 (9/9 plans; +LEV-03 discovered/closed)
- [x] **Phase 3: Shorts & Borrow Carry** - First-class short direction (LONG_ONLY guard removed, CR-01 cover-arm fixed), short PnL, borrow-interest accrual (owner-gated) — completed 2026-06-15 (6/6 plans; review BLOCKER CR-01 found+fixed inline)
- [x] **Phase 4: Liquidation & Cross-Validation Re-baseline** - Bar-close maintenance-margin breach → forced-close `FillEvent`; the owner-gated accounting-core golden re-baseline cross-validated against backtesting.py/backtrader (owner-gated) — completed 2026-06-16 (6/6 plans; owner-signed golden freeze; review BLOCKER CR-01 found+fixed via debug → fill-at-liq-price)
- [ ] **Phase 5: Engine-Native Trailing Stops** - `TRAILING_STOP` order type + `MatchingEngine` ratchet (closed-bar/next-bar look-ahead); own re-baseline + cross-validation (owner-gated)
- [ ] **Phase 6: Pair-Trading Flagship** - Market-neutral long/short cointegration/spread strategy end-to-end; flagship demo (NOT the correctness oracle); final, slip-able capstone

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

## Phase Details

### Phase 1: Instrument Value Object
**Goal**: A frozen per-symbol `Instrument` value object is the single source of price/quantity
precision + `min_order_size` + margin params (`maintenance_margin_rate`, `max_leverage`,
`settles_funding`); it replaces the deleted hard-coded `_INSTRUMENT_SCALES` table, with `BTCUSD`
pinned to its declared 8dp so the golden oracle does not drift.
**Depends on**: Nothing (foundational — margin/liquidation/leverage all consume it)
**Requirements**: INST-01, INST-02, INST-03
**Success Criteria** (what must be TRUE):
  1. `core/money.py::quantize` reads precision from an `Instrument` and the `_INSTRUMENT_SCALES`
     table no longer exists in the codebase.
  2. Price precision resolves declared → inferred-from-data (guarded: string read, max-dp cap)
     → default; `quantity_precision`/`min_order_size` resolve declared → default.
  3. `BTCUSD` takes the declared 8dp branch and the SMA_MACD oracle stays byte-exact
     (134 trades / `final_equity 46189.87730727451`) — the behavioral gate for "snap via Instrument".
  4. An `Instrument` exposes `maintenance_margin_rate`, `max_leverage`, `settles_funding` for
     downstream phases, and `ExchangeLimits` is demoted to a venue-level fallback for undeclared symbols.
**Re-baseline**: Byte-exact behavioral gate. The Instrument seam lands metadata + precision-read;
whether the backtest *snaps/rounds* via Instrument must hold the oracle byte-exact (BTCUSD declared
8dp branch). `mypy --strict` clean; determinism double-run byte-identical.
**Plans**: 3 plans
- [x] 01-01-PLAN.md — Frozen Instrument value object + quantize(Instrument) rewire; delete _INSTRUMENT_SCALES (INST-01/03)
- [x] 01-02-PLAN.md — derive_instruments ladder + Universe facade + ExchangeLimits demotion + SimulatedExchange/wiring (INST-02/03)
- [x] 01-03-PLAN.md — Byte-exact oracle + mypy --strict + determinism phase gate (INST-01/02/03)

### Phase 2: Margin Accounting & Leverage
**Goal**: A portfolio opens positions on reserved margin (`initial_margin = notional / leverage`),
rejects/clips orders that exceed free margin, tracks maintenance margin per position, and can trade
with configurable leverage > 1 — making a levered Kelly fraction > 1 expressible.
**Depends on**: Phase 1 (consumes `Instrument.max_leverage`/`maintenance_margin_rate`)
**Requirements**: MARGIN-01, MARGIN-02, MARGIN-03, LEV-01, LEV-02
**Success Criteria** (what must be TRUE):
  1. Opening a position reserves `initial_margin = notional / leverage` against available cash
     (not full notional).
  2. An order exceeding available free margin is rejected (or clipped) rather than silently
     over-leveraging the simulated account.
  3. Maintenance margin is tracked and queryable per open position.
  4. A portfolio configured with leverage > 1 (via `enable_margin`/`allow_short_selling`) posts
     `notional / L` as margin; a Kelly fraction > 1 produces `notional = f × equity`.
**Re-baseline**: Owner-gated (result-changing). Levered/margin behavior changes results; the new
golden master freezes ONLY after explicit owner sign-off + external cross-validation
(`backtesting.py`/`backtrader`), with full attribution. `mypy --strict` clean; Decimal end-to-end;
determinism double-run byte-identical.
**Plans**: 7 plans
- [x] 02-00-PLAN.md — [Wave 0] Nyquist stub plan: collectible -k/-m targets for every Phase-2 verify command (MARGIN-01/02/03, LEV-01/02)
- [x] 02-01-PLAN.md — SignalEvent.leverage + TradingRules.max_leverage inert contract fields (LEV-01)
- [x] 02-02-PLAN.md — LeveredFraction equity-based sizing kind + resolver arm + SignalIntent.leverage (LEV-02)
- [x] 02-03-PLAN.md — [BLOCKING] Universe wiring into the order domain + leverage cap + margin reservation/over-margin reject (LEV-01/02, MARGIN-01/02)
- [x] 02-04-PLAN.md — Lock-and-settle cash model: position-keyed locked_margin + one-leverage-per-position + process_transaction branch (MARGIN-01)
- [x] 02-05-PLAN.md — maintenance_margin/margin_ratio compute-on-demand read-model + max_leverage update_config (MARGIN-03, LEV-01)
- [x] 02-06-PLAN.md — Parked leveraged-long e2e (hand-computed, NOT frozen) + byte-exact/determinism/mypy phase gate (MARGIN-01/02/03, LEV-01/02)
- [x] 02-07-PLAN.md — LEV-03 closed: effective leverage flows signal->order->fill->transaction->position (run-path on_fill carry site) (LEV-03)
- [x] 02-08-PLAN.md — Gap closure: CR-01 LIMIT/STOP leverage threading (LEV-03 all order types) + CR-02 margin over-close fail-loud guard (LEV-03)

### Phase 3: Shorts & Borrow Carry
**Goal**: A strategy can open and hold a first-class short position (the `LONG_ONLY` guard removed,
the CR-01 cover-arm hole fixed), with correct short PnL and borrow-interest carry accrued on open
shorts.
**Depends on**: Phase 2 (margin must exist to reserve against a short; carry rides shorts)
**Carry-forward (Phase 2 review residuals)**: address the margin-hardening residuals parked for
Phase 3 in `phases/02-margin-accounting-leverage/deferred-items.md` — CR-02-residual (full flip
settlement: split a flip fill into close+open, or correct `realised_increment` to the clamped
quantity), WR-01 (settlement-side solvency assertion that the locked margin fits buying power),
WR-03 (margin-lock release symmetry at the assembly-failure site), WR-04 (`≥1` leverage floor +
zero guard on `_effective_leverage`), WR-05 (per-lock open-commission accumulator). These are
oracle-dark today (margin off on the SMA_MACD spot path) but become reachable once shorts/levered
entries lock margin on the run path. (WR-02 universe-unwired guard spans Phase 3/4; IN-03 → Phase 4.)
**Requirements**: SHORT-01, SHORT-02, SHORT-03, CARRY-01
**Success Criteria** (what must be TRUE):
  1. A `SHORT_ONLY` / long-short strategy is admitted — the `LONG_ONLY` guard in
     `StrategiesHandler.add_strategy` no longer blocks it.
  2. A BUY-to-cover on a `SHORT_ONLY` book reduces/closes the short instead of falling through to
     entry sizing and flipping the book long (CR-01 cover-arm fix in `_resolve_signal_quantity`).
  3. A closed short computes first-class short PnL (`|size| × (entry − exit)` minus carry), not a
     sign-flipped long.
  4. An open short accrues borrow interest (`days × price × |size| × rate/365`) booked to realized
     cash.
**Re-baseline**: Owner-gated (result-changing). Shorts change results (the v1.0 oracle eliminated 2
blessed shorts under D-08 LONG_ONLY); the new golden freezes ONLY after owner sign-off + external
cross-validation. `mypy --strict` clean; Decimal end-to-end; determinism double-run byte-identical.
**Plans**: 6 plans (3 waves)
- [x] 03-01-PLAN.md — inert data/enum plumbing: Instrument.borrow_rate (D-01) + CashOperationType.BORROW_INTEREST (D-03), default-off/oracle-dark
- [x] 03-02-PLAN.md — Wave 0 test scaffolding: collectible skipped stubs for every selector + 3 parked e2e dirs (Nyquist contract, D-10)
- [x] 03-03-PLAN.md — SHORT-01 two-flag registration gate (allow_short_selling AND enable_margin, D-07) + compose/live wiring
- [x] 03-04-PLAN.md — SHORT-02 side-agnostic cover-arm + clamp-to-flat (D-05/D-06) + WR-04 leverage floor + SHORT-03 PnL confirm
- [x] 03-05-PLAN.md — CARRY-01 per-bar BORROW_INTEREST carry accrual: thread bar business time + Universe into the mark (D-02/D-04/D-08)
- [x] 03-06-PLAN.md — WR-01/02/03/05 margin-seam hardening (D-09) + 3 parked e2e scenarios + owner-gated phase gate (D-10)

### Phase 4: Liquidation & Cross-Validation Re-baseline
**Goal**: A position breaching maintenance margin (checked on bar close — the honest daily-OHLCV
proxy) is force-closed via a `FillEvent` with loss floored at allocated isolated margin and a
configurable penalty, reconciling through the existing position/cash/order-mirror path — and the
margin/shorts/liquidation accounting core is cross-validated and the new golden master frozen under
owner sign-off.
**Depends on**: Phase 2 (maintenance margin) AND Phase 3 (shorts to liquidate)
**Carry-forward (review residuals → Phase 4)**: address the residuals parked in
`phases/03-shorts-borrow-carry/deferred-items.md` — WR-04 (`assert_lock_fits_buying_power` add-back
reads `0` because `release_margin` pops the prior lock before the assertion runs; fix the call order —
assert before release, or pass the released amount in — so the solvency assertion credits the prior
lock it claims to). Conservative today (fails loud, not a leak) but lands on the FRAGILE margin seam
this phase re-touches, so bundle it under the single XVAL-01 owner-gated re-baseline. Plus IN-03
(per-instrument maintenance-margin-rate table) declared here before liquidation consumes `margin_ratio`.
(WR-02 universe-unwired guard — resolved in Phase 3 as a fail-loud `StateError` — no longer carries forward.)
**Requirements**: LIQ-01, LIQ-02, LIQ-03, XVAL-01
**Success Criteria** (what must be TRUE):
  1. A position breaching maintenance margin on bar close is force-closed via a `FillEvent`, loss
     floored at the position's allocated isolated margin — equity can no longer drift impossibly
     negative (closes DEF-01-C).
  2. A configurable liquidation penalty/fee is charged so liquidation PnL is not optimistic.
  3. Forced liquidation reuses `FillStatus.EXECUTED`, mints an admission-bypassing close order
     tagged `OrderTriggerSource.LIQUIDATION`, and reconciles with no new `FillStatus`.
  4. Crafted short, leveraged-long, and forced-liquidation scenarios are cross-validated against
     `backtesting.py` and `backtrader`, and the new accounting-core golden master freezes ONLY after
     explicit owner sign-off with full attribution.
**Re-baseline**: Owner-gated (result-changing) — the single accounting-core golden re-baseline,
gated by XVAL-01 (cross-validation + explicit owner sign-off). The crafted scenarios are the
correctness oracle (NOT pair trading). `mypy --strict` clean; Decimal end-to-end including the
liquidation formula + interest accrual; determinism double-run byte-identical.
**Plans**: 6 plans
- [x] 04-00-PLAN.md — [Wave 0] Nyquist stubs: collectible liquidation unit + e2e scaffolds (LIQ-01/02/03)
- [x] 04-01-PLAN.md — Inert plumbing: OrderTriggerSource.LIQUIDATION + Instrument/TradingRules liquidation_fee_rate (default-off, D-06) (LIQ-02/03)
- [x] 04-02-PLAN.md — WR-04 carry-forward: assert_lock_fits_buying_power call-order fix (both sites) + regression (LIQ-01)
- [x] 04-03-PLAN.md — Liquidation engine on the BAR route: corrected isolated formula + explicit loss cap + registered forced-close Order + direct FillEvent (LIQ-01/02/03)
- [x] 04-04-PLAN.md — Crafted liquidation e2e (PRIMARY oracle) + crossval runners + accounting-core evidence doc (XVAL-01)
- [x] 04-05-PLAN.md — [owner-gated] Blocking sign-off checkpoint → freeze accounting-core golden (D-10/D-12) + phase gate (XVAL-01)

### Phase 5: Engine-Native Trailing Stops
**Goal**: A strategy can declare a `TRAILING_STOP` order; the `MatchingEngine` ratchets the resting
stop in the favorable direction only as price extends, look-ahead-safe (trail updates from closed-bar
extremes, active the next bar), cross-validated against the external oracles.
**Depends on**: Phase 4 (sequenced after the accounting core; different subsystem → own re-baseline)
**Requirements**: TRAIL-01, TRAIL-02, TRAIL-03
**Success Criteria** (what must be TRUE):
  1. A declared `TRAILING_STOP` order rests in the `MatchingEngine` and its stop ratchets in the
     favorable direction only as price extends (never loosens).
  2. The trail updates from closed-bar extremes and becomes active on the NEXT bar — never trails to
     this bar's extreme and triggers off the same bar (look-ahead-safe per the `bar_feed.py` contract).
  3. Trailing-stop backtest behavior is cross-validated against `backtesting.py` and `backtrader`,
     and any result-change freezes only under owner sign-off.
**Re-baseline**: Owner-gated (result-changing) — its OWN re-baseline, separate from the accounting
core (MatchingEngine resting-order subsystem, not portfolio/cash accounting). The native-vs-synthetic
live capability seam is deferred to N+4. `mypy --strict` clean; determinism double-run byte-identical.
**Plans**: 5 plans
- [ ] 05-00-PLAN.md — [Wave 0] Nyquist stubs: collectible trailing unit + e2e selectors (long AND short) (TRAIL-01/02/03)
- [ ] 05-01-PLAN.md — Static plumbing: OrderType.TRAILING_STOP + TrailType config-enum + event/entity fields + factory + dual-layer D-TRAIL-7 validation (TRAIL-01/02)
- [ ] 05-02-PLAN.md — MatchingEngine ratchet core: side-table HWM/LWM, end-of-on_bar ratchet (D-TRAIL-2), STOP-arm reuse + long/short unit tests (TRAIL-01/02)
- [ ] 05-03-PLAN.md — Fill-anchored trailing-SL bracket declaration (D-TRAIL-3/5) + long/short e2e scenarios (TRAIL-01/02)
- [ ] 05-04-PLAN.md — [owner-gated] Cross-validation vs backtesting.py/backtrader + evidence report + blocking re-baseline sign-off (TRAIL-03)

### Phase 6: Pair-Trading Flagship
**Goal**: A market-neutral long/short pair-trading strategy (cointegration/spread) runs end-to-end,
exercising both sides — the flagship demonstration that shorts work end-to-end (explicitly NOT the
primary correctness oracle; the crafted scenarios under XVAL-01 are).
**Depends on**: Phase 3 (shorts) and Phase 4 (liquidation/margin core) — final, slip-able capstone
**Requirements**: PAIR-01
**Success Criteria** (what must be TRUE):
  1. A cointegration/spread pair-trading strategy runs end-to-end through the full run path, opening
     a long leg and a short leg.
  2. Both legs settle correctly through margin, short PnL, carry, and (if triggered) liquidation —
     reusing the Phase 2-4 accounting core with no new correctness branches.
  3. The flagship run is self-contained and able to slip to a follow-on without blocking the
     shippable margin/shorts core — it is the headline demo, NOT the correctness oracle.
**Re-baseline**: Capstone — additive flagship strategy, not a re-baseline of the SMA_MACD oracle.
NOT the correctness oracle (a two-leg strategy partially cancels its own sign errors → weak oracle).
Slip-able to an immediate follow-on. `mypy --strict` clean; determinism double-run byte-identical.
**Plans**: TBD

## Progress

**Shipped milestones** (full per-phase detail archived under `milestones/`):

| Milestone | Phases | Plans | Status | Shipped |
|-----------|--------|-------|--------|---------|
| v1.0 — Backtest-Correctness Refactor | 1-8 | 62 | ✅ Shipped | 2026-06-08 |
| v1.1 — Backtest Trustworthiness: Breadth | 1-9 | 28 | ✅ Shipped | 2026-06-10 |
| v1.2 — Consolidation | 1-6 | 23 | ✅ Shipped | 2026-06-12 |
| v1.3 — Engine Surface Completion | 1-6 | 20 | ✅ Shipped | 2026-06-14 |

**Active milestone — v1.4 Margin, Leverage, Shorts & Trailing Stops:**

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Instrument Value Object | 3/3 | Complete   | 2026-06-15 |
| 2. Margin Accounting & Leverage | 9/9 | Complete   | 2026-06-15 |
| 3. Shorts & Borrow Carry | 6/6 | Complete   | 2026-06-15 |
| 4. Liquidation & Cross-Validation Re-baseline | 6/6 | Complete   | 2026-06-16 |
| 5. Engine-Native Trailing Stops | 0/5 | Planned | - |
| 6. Pair-Trading Flagship | 0/TBD | Not started | - |

**Next:** Plan Phase 1 with `/gsd:plan-phase 1`.

## Backlog

> Future **milestone-level** seeds — intent + rationale only, NOT detailed plans.
> **Logical promotion order: N+3 (next) → N+4**
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
> Consolidation** (cleanup, Phases 1-6) shipped 2026-06-12. Engine Surface Completion (former
> Backlog Phase 999.5) shipped as **v1.3** (2026-06-14). **N+2 — Margin, Leverage, Shorts &
> Trailing Stops (former Backlog Phase 999.4) was promoted to the ACTIVE milestone v1.4 on
> 2026-06-14** — see `## Phases` above; its rich design lives in PROJECT.md "Current Milestone:
> v1.4" + `notes/margin-leverage-shorts-999.4.md`. The remaining `999.x` entries below are future
> milestones (N+3/N+4); **N+3 is next**.

### Phase 999.4: N+2 — Margin, Leverage, Shorts & Trailing Stops (crypto) — PROMOTED TO v1.4 (2026-06-14)

> **PROMOTED to the ACTIVE milestone v1.4 on 2026-06-14.** The 20 v1.4 requirements
> (INST/MARGIN/LIQ/SHORT/CARRY/LEV/TRAIL/XVAL/PAIR) and their phase mapping are in
> `.planning/REQUIREMENTS.md`; the active phase structure is in `## Phases` above. The full design
> intent below is RETAINED as the historical seed (it is also folded into PROJECT.md "Current
> Milestone: v1.4" and `notes/margin-leverage-shorts-999.4.md`, which the active phases reference).
> Phase B perp realism (funding-rate accrual, mark-price liquidation, funding-data pipeline,
> `freqtrade` as a 4th oracle) and the `Account` abstraction are DEFERRED out of v1.4 (tracked as
> FUND-0x / ACCT-01 in REQUIREMENTS.md "Future Requirements" → N+3/N+4).

**Goal:** The matching-engine / risk-execution milestone. Build the margin/liquidation
model the engine has deliberately deferred (D-08/D-09, DEF-01-C), unblocking shorts and
leverage, AND add engine-native trailing stops — all are stateful resting-order changes to
the same `MatchingEngine` surface, so they're done in one pass and share one golden master +
cross-validation, like M5. Also lands the minimal per-instrument value object (`Instrument`)
the margin/funding model consumes. **Extends exactly the signal/order/composition surfaces v1.3
completes, which is why v1.3 lands first.**
**Requirements:** INST-01/02/03, MARGIN-01/02/03, LIQ-01/02/03, SHORT-01/02/03, CARRY-01,
LEV-01/02, TRAIL-01/02/03, XVAL-01, PAIR-01 (20 total — see REQUIREMENTS.md)
**Plans:** promoted to v1.4 (see `## Phases`)

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

- **Minimal per-instrument value object (crypto-only)** — introduce `Instrument`
  (`core/instrument.py`, a frozen value object mirroring `core/bar.py::Bar`). Lands here because
  margin & funding rates are inherently per-instrument, so N+2 is the spec's first real consumer.
  **Replaces (deletes) the hard-coded `_INSTRUMENT_SCALES` table in `core/money.py`** — `Instrument`
  becomes the per-symbol source that `money.py::quantize` reads precision from, giving
  margin/liquidation + funding/carry a real per-symbol home (instead of new hard-coded tables).
  **Field set (each tied to a named N+2 consumer — YAGNI gate):** `symbol`; `quote_currency`
  (default `"USD"`, the principled source for cash precision); `price_precision`,
  `quantity_precision` (money quantize, doubles as the lot/qty step); `min_order_size`
  (order validation/sizing — per-symbol, see below); `maintenance_margin_rate`, `max_leverage`
  (margin/liquidation + leverage); `settles_funding: bool` (funding/carry).
  - **Precision, NOT trading tick.** Backtest needs rounding precision, not a price grid; `tick`
    is live-only (fetched from the exchange) and only bites N+2 via trailing-stop min-distance —
    deferred from this value object. **Price precision is layered: declared-wins → infer-from-data
    (guarded: read CSV string not float, cap max dp — DOGE-safe, fixes the catastrophic flat-`0.01`
    default) → `_DEFAULT_SCALES`.** Pinned/oracle symbols (e.g. `BTCUSD`, declared 8dp) ALWAYS take
    the declared branch — inference from BTCUSD data would yield ~2–4dp and drift the golden master
    off `46189.87730727451`. `quantity_precision` is declared-or-default (not inferable — no quantity
    column).
  - **Funding is a flag, not a rate.** Perp funding is a time-series (accrues ~8h, changes), so
    `Instrument` carries only `settles_funding`; the rate schedule comes from data/config, like prices.
    Maintenance-margin rate IS a static venue property → fine as a field.
  - **No cash instrument.** Cash has no price/margin/funding/fills — it doesn't fit the Instrument
    shape. Cash precision = the quote currency's precision (USD → 2dp). A first-class `Currency` value
    object (sibling of `Instrument`, not cash-crammed-in) waits for multi-currency accounting (deferred
    indefinitely, crypto-first).
  - **`min_order_size` moves ONTO `Instrument`** (REVISED 2026-06-14, owner directive). Min size,
    lot step, and precision are all per-symbol trading metadata; in reality the venue publishes them
    per market (ccxt `loadMarkets` → `market['precision']`/`['limits']['amount']['min']`; IBKR
    `contractDetails`). So `Instrument` is the per-symbol source of truth; `ExchangeLimits` is
    **demoted to a venue-level fallback** for undeclared symbols, NOT the per-symbol authority (its
    flat per-venue `min/max_order_size` stays only as that fallback). The full **(venue, symbol)**
    matrix — same symbol differing across venues — only bites in multi-venue **live**, so it is an
    **N+4** concern; v1.4's single simulated venue does not need it. **Population by mode:** backtest
    = declared → default (`min_order_size`/`quantity_precision` are NOT inferable from OHLCV — no
    quantity column; only `price_precision` is inferable, guarded); **live (N+4)** = fetched per
    market from the venue. Reconcile the exact `ExchangeLimits` disposition (keep-as-fallback vs
    absorb) during phase discussion.
  - **Crypto-only, NO `asset_class` taxonomy** — crypto/stock/forex tagging stays in the deferred
    multi-asset milestone (dead metadata until non-crypto accounting exists).
  - **Behavioral gate:** whether the backtest *snaps/rounds* via `Instrument` (vs storing metadata
    only) is result-changing → falls under N+2's owner-gated re-baseline.

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

**Scoping decisions locked (2026-06-14, pre-`/gsd:new-milestone`):**

- **Trailing stop — IN v1.4, as its OWN phase.** Small in backtest: the `MatchingEngine` already
  fills resting stops (`_evaluate` STOP branch) and already has `modify()` (`dataclasses.replace`).
  The work is a `TRAILING_STOP` `OrderType` member + map entry, a trail param + running-extreme
  field on `OrderEvent`, and one ratchet step at the top of `on_bar` (recompute stop from the
  running extreme, favorable-only) that hands off to the existing STOP fill path. It is a DIFFERENT
  subsystem from margin/shorts accounting (matching-engine vs portfolio/cash) → kept in a SEPARATE
  phase so each result-change owns its own golden re-baseline (v1.3 "result-changing phases kept
  separate" discipline). **Look-ahead rule:** the trail updates from CLOSED-bar extremes and is
  live for the NEXT bar (the engine's standard one-bar lag) — never trail to this bar's high and
  trigger off this bar's low. The native-vs-synthetic capability seam is **live-only → N+4**.

- **Pair trading — IN v1.4 as the FINAL, slip-able capstone phase; NOT the correctness oracle.**
  A market-neutral two-leg strategy partially cancels its own sign errors (short PnL sign,
  cover-arm, liquidation geometry — exactly the bugs to catch), so it is a weak oracle.
  **Correctness is locked** by crafted, hand-computable, adversarial scenarios (pure short,
  leveraged long, forced liquidation) cross-validated against `backtesting.py`/`backtrader`. Pair
  trading is the headline "shorts work end-to-end" demo, scoped as a distinct phase so it can slip
  to an immediate follow-on without blocking the shippable margin/shorts core.

- **Liquidation — NO new `FillStatus`.** `FillStatus` is outcome (EXECUTED/REFUSED/CANCELLED/
  EXPIRED); "liquidated" is a CAUSE. A liquidation's accounting effect IS an `EXECUTED` fill
  (position closes, cash settles, penalty applied), so it reuses `status=EXECUTED` and flows
  through the existing `on_fill` → position-close → cash-settle path with zero new branches (adding
  `LIQUIDATED` would force a new arm into the load-bearing EXECUTED→FILLED reconcile map for no
  benefit). The real work: the liquidation engine **mints a forced close order** (owned by the
  position's strategy, so the required `strategy_id`/`order_id` on `FillEvent` are real and the
  fill→order→strategy audit chain + order-mirror reconcile stay intact) that **bypasses
  admission/sizing** (a forced deleverage must never be rejected by a margin check); tag the cause
  with a new `OrderTriggerSource.LIQUIDATION` member (fits the existing closed vocab) for trade-log
  / metrics filtering; the configurable liquidation penalty rides the existing `commission`/fee
  field. (Resolves §9 Q2 of `notes/margin-leverage-shorts-999.4.md`.)

- **Instrument metadata ownership** — see the revised `min_order_size` sub-bullet above: `Instrument`
  is the per-symbol source of truth for precision + lot step + min size + margin params (deletes
  `_INSTRUMENT_SCALES`); `ExchangeLimits` demoted to venue-level fallback; per-`(venue,symbol)`
  generality deferred to N+4 live. (Resolves §9 Q1.)

Plans:

- [x] Promoted to v1.4 (2026-06-14) — see `## Phases`

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
- **Dynamic universe membership** — a lean `UniverseSelectionModel` poll seam for mid-run
  adds/removes (distinct from, and a prerequisite step toward, the full production screener
  above; grows in `universe/membership.py` per its documented D-20 growth target). Engine
  integration edges: warmup-on-add and open-position-handling-on-remove. Orthogonal to N+2
  (its pair-trading validation uses a fixed pair); sequenced here because it pairs with the
  real-time data engine (#6).
- **FL-13** — `LiveTradingSystem`/`TradingInterface` test coverage (deferred out of v1.3; the
  live surface, not the backtest engine surface).
- **Perp realism — "Phase B" (FUND-01..04, deferred out of v1.4)** — funding-rate accrual at
  funding-timestamp boundaries, mark-price liquidation trigger (resolves phantom-wick risk),
  funding-data pipeline (ccxt `fetchFundingRateHistory` → per-symbol CSV; per-symbol interval, no
  hardcoded 8h), and `freqtrade` as a fourth cross-validation oracle. Purely additive on the v1.4
  Phase A core — only the carry model + liquidation trigger-price change. May land as its own
  milestone or fold into N+3/N+4 data work (see `notes/margin-leverage-shorts-999.4.md` §8).
- **Account abstraction (born here, with the connector)** — introduce a first-class `Account`
  domain object as the **reconciled local mirror of the venue's balance/margin state**. The
  **connector is the exchange adapter** (API keys, order I/O, fill/balance/funding streams — the
  `AbstractExchange`/provider boundary); the adapter *writes into* the `Account`, the `Account`
  does NOT talk to the venue. It is born here, not earlier, because in live the **source of truth
  flips**: backtest computes cash/positions locally (Portfolio = account), but live treats the
  **venue as truth**, so the engine needs a mirror to **reconcile** against (detect/repair drift
  from partial fills, fees, funding, liquidations, manual/other-bot trades). Reconciliation has
  no backtest analogue — which is exactly why the Account is a live concern, not an N+2 one.
  - **Shape:** `CashAccount` vs `MarginAccount` typing (nautilus pattern); one `Account` per
    `(venue, login)`; **Binance spot vs futures = two separate accounts** (cash vs margin);
    **IBKR subaccounts = N accounts under one connection**. Leverage/maintenance-margin/liq-price
    are **venue-controlled** live (set on the venue, cached in the `Account`) — distinct from the
    N+2 backtest model that *computes* them.
  - **Distinct driver from cross-margin.** Cross-margin (deferred beyond N+2 Phase B) needs an
    account *collateral pool* for account-wide liquidation math — a **backtest-accounting** driver.
    The live `Account` here is a **reconciliation** driver. Related, separately motivated; do not
    conflate.
  - **`user_id` is app-layer, strip from the engine.** Multi-tenancy ownership does NOT belong in
    the trading-domain `Portfolio` (current smell: `Portfolio.user_id`) and must NOT be relocated
    onto `Account`. The FastAPI-wrap layer owns the `user_id → portfolio_id/account_id` mapping
    externally; the engine stays owner-agnostic, keyed by its own domain IDs. Removing
    `Portfolio.user_id` is an independent cleanup (constructor-signature ripple) — kept OUT of v1.4
    to avoid muddying that milestone's golden-master re-baseline.

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
