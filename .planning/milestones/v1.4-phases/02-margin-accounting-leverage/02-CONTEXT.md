# Phase 2: Margin Accounting & Leverage - Context

**Gathered:** 2026-06-15
**Status:** Ready for planning

<domain>
## Phase Boundary

Give the backtest portfolio a **margin accounting model**: opening a position
reserves `initial_margin = notional / leverage` (not full notional), orders that
exceed free margin are rejected, maintenance margin is tracked & queryable per
open position, and a portfolio can trade with configurable **leverage > 1** —
making a **levered Kelly fraction > 1** expressible (`notional = f × equity`,
posting `notional / L` as margin). Requirements: MARGIN-01/02/03, LEV-01/02.

**Two cash models, gated by `enable_margin`:**
- `enable_margin = False` (spot): today's debit-notional flow is **untouched** →
  the SMA_MACD oracle (134 trades / `final_equity 46189.87730727451`) stays
  **byte-exact** (default leverage 1, FractionOfCash never reads equity).
- `enable_margin = True` (margin): lock-and-settle accounting — lock margin for
  the position's life, settle realized PnL on close.

**Re-baseline discipline:** Phase 2 is part of the **accounting core** whose
golden master re-baselines **once, at Phase 4 / XVAL-01** (cross-validation +
owner sign-off). Phase 2 itself freezes **no** new leveraged golden — it holds
SMA_MACD byte-exact and parks a hand-verified leveraged-long scenario for the P4
freeze.

**In scope:** margin reservation (`notional/L`), over-margin reject, maintenance
margin tracking (computed/read-model), leverage value on the SignalEvent + caps,
a new equity-based levered sizing policy, lock-and-settle cash model gated by
`enable_margin`, config surface (portfolio `max_leverage` cap) + `update_config`
participation, scale-in/out margin proportioning, component tests + a parked
leveraged-long e2e.

**Out of scope (later phases / deferred):** the force-close **liquidation
trigger** (Phase 4, LIQ-01 — DEF-01-C stays open until then), **shorts** + the
CR-01 cover-arm fix + borrow carry (Phase 3), a margin-call/liquidation **warning
event** (N+4 live/UI), an equity/drawdown-aware **leverage policy** risk overlay
(deferred to-do), funding/perp realism (Phase B / N+4).

</domain>

<decisions>
## Implementation Decisions

### Over-margin handling (MARGIN-02)
- **D-01:** An order whose required `initial_margin` exceeds available **free
  margin** is **rejected** — reuse the existing over-cash REJECTED path (no
  reservation recorded, empty cash ledger; the CASH-02 `release_rejected`
  precedent). NOT clipped. With `enable_margin = False` / leverage 1, required
  margin == notional, so the check is **byte-exact** vs today's funds check.
  Clip-to-fit is a deferred alternative.

### Leverage configuration & application (LEV-01)
- **D-02:** Leverage is **decided by the strategy** (it owns the price series /
  vol model) and **applied by the order/risk layer** — the D-12 "strategies
  declare, engine resolves against per-portfolio state" split, mirroring sizing.
- **D-03:** The strategy emits a **concrete `leverage: Decimal` on the
  `SignalEvent`** (default `Decimal("1")` → byte-exact). NOT a typed policy, NOT
  class-attr-only — a scalar is already fully dynamic (the strategy can compute
  it per signal) and needs no per-portfolio data to resolve. The field is shaped
  so a typed/equity-aware policy can replace the scalar later **without a second
  contract change**.
- **D-04:** The order/risk layer **caps** leverage:
  `effective = min(signal.leverage, Instrument.max_leverage, portfolio.max_leverage)`
  when `enable_margin`, else **forced to 1**. `Instrument.max_leverage` = per-symbol
  venue ceiling; `portfolio.max_leverage` = account-wide risk cap.
- **D-05 (over-cap):** When requested leverage exceeds the cap, **clamp to the
  cap + log a warning** (venue-realistic — max leverage is a ceiling, not a
  trade-killer; it's the natural reading of D-04's `min(...)`). NOT reject (the
  trade is still affordable), NOT silent (debuggability under the owner gate).
- **D-06:** A position has **one effective leverage, set at open** (venue-realistic
  isolated margin). A differing `signal.leverage` on a **scale-in** is clamped to
  the position's leverage (documented), not a per-tranche re-margin.

### Levered Kelly API (LEV-02)
- **D-07:** Add a **new equity-based `SizingPolicy` kind** (e.g.
  `LeveredFraction` / `KellyFraction`) that **reads equity** (like `RiskPercent`)
  and permits `f > 1` **only when `enable_margin`** → `notional = f × equity`.
  Resolver gets a new match arm (D-02 growth rule: add a kind, never relax a
  guard). `FractionOfCash` keeps its strict `(0, 1]` cash guard **intact** — the
  byte-exact golden path is untouched (oracle-dark).
- **D-07a (rationale):** Kelly estimates the **exposure fraction `f`** (sizing),
  not leverage. `f` sets position size; `L` (D-03) sets margin backing +
  liquidation distance — complementary, not redundant. "Leverage carries
  exposure with `f ≤ 1`" was **ruled out** because D-09's model makes leverage a
  margin divisor, not an exposure multiplier (it can never push notional above
  `f × equity`).

### Cash model & margin lifecycle (MARGIN-01)
- **D-08:** Margin reservation = **`initial_margin (= notional / L) +
  estimated_commission`**, where commission is computed by the fee model on the
  **full traded notional** (fees ride traded value, not margin) — consistent
  with today's D-04 reserve-includes-commission behavior. (The Phase-4
  liquidation penalty rides the existing commission/fee field — locked design,
  no new field.)
- **D-09:** **Two cash models gated by `enable_margin`.** Spot (`False`): today's
  **debit-notional** flow untouched (byte-exact). Margin (`True`):
  **lock-and-settle** — lock `initial_margin` for the **position's life** (NOT
  just the pending order), do not spend notional, settle realized PnL to cash on
  close, release margin on close. Lock-and-settle is the only model that supports
  Phase-3 shorts (no notional to spend) and Phase-4 liquidation (a locked margin
  to floor loss against).
- **D-10 (ownership):** **`CashManager` owns** the position-lifetime locked
  margin — a **position-keyed** locked-margin container, distinct from the
  `order_id`-keyed order-pending reservation, reserved on the opening fill and
  released on the closing fill. One cash authority:
  `available = balance − order_reservations − locked_margin`. No 5th sub-manager
  reaching into cash state.
- **D-11 (scale-in/out):** **Pro-rata aggregate.** A position carries aggregate
  notional + one leverage (D-06); `locked_margin = aggregate_notional / L`,
  recomputed as fills aggregate. Scale-in adds margin at the position's leverage;
  a partial close of fraction `p` releases `p × locked_margin` and settles
  `p × PnL`. NOT per-tranche FIFO (path-dependent, over-scoped for isolated margin).

### Equity basis (LEV-02, MARGIN-03)
- **D-12:** Levered-Kelly sizing and the free-margin / maintenance-margin check
  use **mark-to-market `total_equity()`** (cash + unrealized PnL, marked at the
  decision-bar close) — `PortfolioReadModel.total_equity()` already exists. The
  correct, consistent basis (liquidation in P4 MUST see unrealized losses).
  Oracle-dark for the spot golden (FractionOfCash never reads equity).

### Maintenance margin (MARGIN-03)
- **D-13:** Maintenance margin is **computed on demand, exposed via the
  read-model** — NOT a stored mutable `Position` field.
  `maintenance_margin = Instrument.maintenance_margin_rate × |size| ×
  current_price` (current/mark notional, consistent with D-12). Expose
  `maintenance_margin` + `margin_ratio` on `PortfolioReadModel` for the UI/live
  layer to **query**.
- **D-13a (live-readiness rationale):** A stored field creates a **second source
  of truth** that fights the N+4 `Account` venue-reconciliation mirror. A
  computed read-model swaps cleanly: backtest computes locally, live reconciles
  from the venue, **consumers (UI included) never change**. Persistence (N+3) is
  snapshot-then-store (the `reporting/cash_operations.py` pattern), not
  authoritative `Position` state. The exact entry-vs-current notional basis for
  the **liquidation formula** is finalized in Phase 4.

### Config surface & runtime reconfig (LEV-01)
- **D-14:** Add `max_leverage: Decimal = 1` to `config/portfolio.py::TradingRules`
  as the account-wide cap (alongside the existing `enable_margin` /
  `allow_short_selling` bools). NO portfolio `default_leverage` (leverage is a
  strategy/signal concern). Default 1 → byte-exact.
- **D-15:** Margin/leverage config **participates in the uniform `update_config`
  seam** (COMP-02: merge → validate → atomic-swap between cycles) — consistent +
  live-ready. **Caveat (documented):** existing open positions keep their
  opened-under terms; new config applies only to new orders (no retroactive
  re-margining). SMA_MACD unaffected (config never changes mid-run).

### Pre-liquidation boundary (P2/P4)
- **D-16:** Phase 2 has **no force-close**. On adverse marks, free margin /
  margin_ratio **read negative/breached honestly** (read-model reflects reality);
  new-order admission is rejected when free margin < required (D-01); equity can
  still drift negative — **DEF-01-C stays open until Phase 4** builds the
  liquidation trigger (LIQ-01). Clean boundary: P2 = accounting + reject; P4 =
  the force-close trigger. No liquidation-like clamp/block in P2 (avoids two
  liquidation code paths + muddied P4 attribution).

### Proof scope & re-baseline (this phase)
- **D-17:** Phase 2 builds **thorough component/unit tests** (margin reservation
  = `notional/L`, over-margin reject, lock-and-settle lifecycle, maintenance-margin
  + margin_ratio compute, levered-Kelly resolution, scale-in/out proportioning)
  **AND** a **leveraged-long integration/e2e scenario** — hand-verified and
  **parked**, frozen as golden **only at Phase 4 under XVAL-01**. SMA_MACD held
  byte-exact throughout. `mypy --strict` clean; Decimal end-to-end (margin
  formula + commission); determinism double-run byte-identical.

### Claude's / Planner's Discretion
- Exact placement of the `notional/L` division (admission gate vs portfolio
  reserve) and the precise free-margin computation plumbing.
- The new sizing-policy name/signature (`LeveredFraction` vs `KellyFraction`) and
  its resolver arm shape (mirror `RiskPercent`).
- The `SignalEvent` `leverage` field name/default plumbing and the
  `PortfolioReadModel` `maintenance_margin`/`margin_ratio` accessor signatures.
- The BTCUSD `Instrument` `max_leverage` / `maintenance_margin_rate` values used
  for the parked leveraged-long scenario (oracle-dark; realistic crypto defaults).
- Indentation: tabs in `portfolio_handler/`, `order_handler/`, `strategy_handler/`,
  `execution_handler/`; 4 spaces in `core/`, `config/` — match the file.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements & milestone discipline
- `.planning/REQUIREMENTS.md` — MARGIN-01/02/03, LEV-01/02 (the locked Phase 2
  requirements); the owner-gated/result-changing milestone discipline.
- `.planning/ROADMAP.md` — v1.4 Phase 2 entry + Phase Details (success criteria);
  the "Owner-gated phases (2/3/4)" re-baseline block; Phase 4 XVAL-01 gate.
- `.planning/STATE.md` — "Milestone Gate (v1.4)" → the owner-gated accounting-core
  block: **one** re-baseline at P4/XVAL-01; oracle 134 / `46189.87730727451`;
  determinism + Decimal + mypy held all phases. Blockers/Concerns → owner-gate
  dependency, CR-01 (P3), correctness-oracle = crafted scenarios.

### Design source
- `.planning/notes/margin-leverage-shorts-999.4.md` — §5 (where liquidation
  lives: portfolio/cash accounting, NOT MatchingEngine — relevant to the P2/P4
  boundary), §6 (Phase A components: Instrument fields, margin accounting,
  config wiring, levered Kelly), §4 (spot-margin vs perp comparison: margin
  reservation `notional/L` is **shared**; PnL/liq formulas), §9 (open
  questions — Q4 re-baseline timing resolved to P4).

### Carried-forward phase context
- `.planning/phases/01-instrument-value-object/01-CONTEXT.md` — the `Instrument`
  value object (D-04), the `Universe` read-model façade (D-06/D-07) that resolves
  `symbol → Instrument` (and thus `maintenance_margin_rate` / `max_leverage`),
  the `quantize(Instrument)` precision seam.

### Code to change / mirror
- `itrader/core/sizing.py` — `SizingPolicy` union + `FractionOfCash` (keep `(0,1]`
  guard), `RiskPercent` (equity-reading template for the new levered policy),
  `_require_unit_interval`; the D-02 growth rule.
- `itrader/order_handler/admission/admission_manager.py` — line ~228 reserves
  `price*qty + estimated_commission` today (D-04); the margin reservation +
  over-margin reject lands here.
- `itrader/order_handler/sizing_resolver.py` — the one resolver that
  match-dispatches on `SizingPolicy`; gets the new levered-fraction arm.
- `itrader/portfolio_handler/cash/cash_manager.py` — `available_balance`
  (= balance − reserved), `reserve_cash` / `release_reservation` (order-pending,
  keyed by reference_id); add the position-keyed locked-margin container (D-10).
- `itrader/portfolio_handler/position/position.py` + `position_manager.py` —
  aggregate notional / one-leverage-per-position (D-06/D-11); margin computed off
  these (D-13).
- `itrader/core/portfolio_read_model.py` — `total_equity()` (D-12), `available_cash`,
  `reserve`/`release`; add `maintenance_margin` / `margin_ratio` accessors (D-13).
- `itrader/config/portfolio.py` — `TradingRules` (`enable_margin`,
  `allow_short_selling`); add `max_leverage` (D-14).
- `itrader/events_handler/events/signal.py` — `SignalEvent`; add the `leverage`
  field (D-03). `itrader/core/sizing.py::SignalIntent` — the strategy-return
  contract leverage rides into.
- `itrader/core/instrument.py` — `maintenance_margin_rate` / `max_leverage`
  (landed inert in Phase 1; consumed here).
- `itrader/portfolio_handler/portfolio_handler.py` — `update_config` (D-15);
  `PortfolioReadModel` Protocol satisfaction.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `RiskPercent` (`core/sizing.py:129`) — the equity-reading sizing template the
  new `LeveredFraction`/`KellyFraction` policy mirrors (resolves against equity).
- `PortfolioReadModel.total_equity()` (`core/portfolio_read_model.py:214`) — the
  mark-to-market equity D-12 reuses; `reserve`/`release` seam for margin locks.
- `CashManager.reserve_cash` / `release_reservation` — the reservation mechanism
  D-10 extends with a position-keyed, position-lifetime variant.
- The over-cash REJECTED path (CASH-02 `release_rejected`, ADMIT-03) — the exact
  pattern D-01 reuses for over-margin reject (empty cash ledger, no reservation).
- `reporting/cash_operations.py` — the determinism-safe snapshot-then-store
  pattern D-13a cites for N+3 margin/equity persistence.
- The uniform `update_config` (COMP-02, all 7 handlers) — D-15's seam.

### Established Patterns
- **D-12 "strategies declare, engine resolves"** — leverage (D-02/D-03) and the
  levered sizing policy (D-07) both ride this split; strategies never size or
  reserve.
- **Read-model seam over stored state** (`PortfolioReadModel`, `BacktestBarFeed`,
  the Phase-1 `Universe`) — D-13's compute-on-demand maintenance margin follows
  it; single source of truth, live-ready for the N+4 `Account` mirror.
- **Decimal end-to-end** — the margin formula (`notional/L`), commission, and
  equity math stay Decimal; `float()` only at the serialization/logging edge.
- **Byte-exact gate via default-off** — `enable_margin=False` / leverage-1 /
  `FractionOfCash`-unchanged keeps SMA_MACD byte-exact; the new behavior is
  gated and oracle-dark.

### Integration Points
- `SignalEvent` (+ `SignalIntent`) gains `leverage`; `sizing_resolver` gains the
  levered arm; `admission_manager` gains margin reservation + over-margin reject.
- `CashManager` gains position-lifetime locked margin; `Position`/`PositionManager`
  carry aggregate notional + one leverage; `PortfolioReadModel` gains
  `maintenance_margin`/`margin_ratio`.
- `Universe` (Phase 1) supplies per-symbol `max_leverage` / `maintenance_margin_rate`.
- `TradingRules.max_leverage` flows through `PortfolioHandler.update_config`.

</code_context>

<specifics>
## Specific Ideas

- The user steered leverage to **live in the strategy and ride the SignalEvent**
  (risk-adjusted, dynamic from the price series) — the engine only caps + applies.
  They explicitly want this for a **live-trading** future, which drove the
  read-model (not stored-state) choice for maintenance margin (D-13/D-13a) and
  the `update_config` participation (D-15).
- The user wants leverage to *eventually* be **equity/drawdown-aware** (a typed
  risk overlay) — captured as a deferred to-do, with the `SignalEvent` field
  shaped to grow into it without a second contract change.
- Architectural-correctness was the user's repeated decision criterion (chose the
  D-02 growth rule over relaxing `FractionOfCash`; chose compute-on-demand over a
  stored field explicitly for live source-of-truth cleanliness).

</specifics>

<deferred>
## Deferred Ideas

- **Equity/drawdown-aware leverage policy** (typed, engine-resolved risk overlay)
  — replaces the scalar `SignalEvent.leverage` later; field shaped for it now.
  (LEV "option 2"; future risk-engine work, beyond LEV-01/02.)
- **Clip-to-fit over-margin handling** — alternative to D-01 reject; config-
  switchable if ever needed.
- **Vol-targeting / portfolio-level leverage overlays** (gross/drawdown scaling,
  correlation caps) — future risk-engine feature.
- **Per-tranche FIFO margin** — more precise than D-11 pro-rata when leverage
  varies across adds; revisit only if isolated-margin one-leverage proves limiting.
- **Margin-call / liquidation-warning EventType** — N+4 live/UI; the read-model's
  `margin_ratio` (D-13) is the surface a UI computes warnings from.
- **Liquidation force-close trigger (LIQ-01)** — Phase 4; DEF-01-C stays open
  until then (D-16). **Shorts + CR-01 cover-arm + borrow carry** — Phase 3.
  **Funding / mark-price / perp realism** — Phase B / N+4.
- **N+4 `Account` reconciliation mirror** — backs the same read-model margin
  surface from venue truth in live; not introduced in v1.4.

None outside phase scope were raised that aren't already tracked above.

</deferred>

---

*Phase: 2-Margin Accounting & Leverage*
*Context gathered: 2026-06-15*
