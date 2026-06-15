# Phase 2: Margin Accounting & Leverage - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-15
**Phase:** 2-Margin Accounting & Leverage
**Areas discussed:** Over-margin handling, Leverage config model, Levered Kelly API, Phase 2 proof scope, Margin reservation lifecycle, Equity basis, Over-cap leverage, Maintenance-margin storage, Config surface, Runtime reconfig, Margin-call warning event, Commission interaction, Locked-margin ownership, Scale-in/out margin proportioning, Negative free-margin stance

---

## Over-margin handling (MARGIN-02)

| Option | Description | Selected |
|--------|-------------|----------|
| Reject | Reuse over-cash REJECTED path; no reservation, empty cash ledger; byte-exact when margin off | ✓ |
| Clip to fit | Reduce qty so margin == free margin; partial position | |
| Config-switchable | reject\|clip flag, default reject | |

**User's choice:** Reject
**Notes:** Mirrors today's over-cash semantics; clip deferred as an alternative.

---

## Leverage config model (LEV-01) — two turns

**Turn 1 — where the leverage value lives.** Options: portfolio config field / per-strategy / per-signal intent. User clarified twice, steering toward **dynamic, risk-adjusted leverage that lives in the strategy and rides the SignalEvent** (it needs the price time series). Resolved to the D-12 split: strategy decides (has the series), order/risk layer applies (cap + margin math + reject). Caps compose `min(signal, Instrument.max_leverage, portfolio cap)`, forced to 1 when margin off.

**Turn 2 — what the strategy emits / does leverage need equity.**

| Option | Description | Selected |
|--------|-------------|----------|
| Strategy/instrument concrete Decimal; equity in sizing | Scalar on SignalEvent, engine caps+applies; equity-based exposure stays in sizing (no double-count) | ✓ |
| Equity-aware leverage policy now | Typed, engine-resolved against equity/drawdown | (→ deferred to-do) |
| Static class-attr only | Per-strategy static, no per-signal | |

**User's choice:** Strategy/instrument value; equity in sizing — **plus** add a to-do for the equity-aware leverage policy.
**Notes:** User asked how real-world leverage works (vol + equity/risk). Resolved: equity-dependent exposure → sizing policy (already reads equity); leverage = strategy/instrument margin-backing knob; field shaped to grow into an equity-aware policy later without a second contract change.

---

## Levered Kelly API (LEV-02)

| Option | Description | Selected |
|--------|-------------|----------|
| New equity-fraction sizing policy | New SizingPolicy kind reads equity, permits f>1 when enable_margin; FractionOfCash guard intact | ✓ |
| Relax FractionOfCash >1 | Lift the (0,1] cap when margin enabled | |
| Leverage carries it (f≤1) | Ruled OUT by the Area-2 leverage model (leverage = margin divisor, not exposure multiplier) | |

**User's choice:** New equity-fraction policy
**Notes:** User asked whether Kelly estimates leverage (no — it estimates exposure fraction f; L is separate), for worked examples of all three options, the most architecturally-correct choice, and how `f` is defined today (it's the `FractionOfCash.fraction`, a cash-fraction in (0,1]; resolver outputs units). Architecturally-correct = new policy (D-02 growth rule; Kelly is equity-based vs FractionOfCash cash-based + byte-exact).

---

## Phase 2 proof scope (design-note Q4)

| Option | Description | Selected |
|--------|-------------|----------|
| Components + parked leveraged-long e2e | Component tests + build a hand-verified leveraged-long e2e now; freeze only at P4/XVAL-01 | ✓ |
| Component tests only | Defer all full-run leveraged scenarios to P4 | |
| Freeze a leveraged golden now | Own mini re-baseline; contradicts the one-re-baseline-at-P4 discipline | |

**User's choice:** Components + parked leveraged-long e2e
**Notes:** SMA_MACD held byte-exact; de-risks the full run path early without an early freeze.

---

## Margin reservation lifecycle (MARGIN-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Two models gated by enable_margin | Spot=debit-notional (byte-exact); margin=lock initial_margin for position life, settle PnL on close | ✓ |
| Unify onto lock-and-settle | All positions lock-and-settle; breaks the byte-exact spot golden | |
| Margin as order-pending reservation only | Release on fill like today; wrong scope — lock must persist for the open position | |

**User's choice:** Two models gated by enable_margin
**Notes:** Lock-and-settle is the only model supporting P3 shorts (no notional to spend) and P4 liquidation (locked margin to floor loss against).

---

## Equity basis (LEV-02 / MARGIN-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Mark-to-market total_equity() | cash + unrealized PnL at decision-bar close; PortfolioReadModel.total_equity() exists | ✓ |
| Realized cash balance only | Ignore unrealized PnL; inconsistent with liquidation | |

**User's choice:** Mark-to-market total_equity()
**Notes:** Oracle-dark for the spot golden (FractionOfCash never reads equity).

---

## Over-cap leverage

| Option | Description | Selected |
|--------|-------------|----------|
| Clamp to cap + log warning | effective = min(...); trade proceeds at cap; venue-realistic, debuggable | ✓ |
| Reject loudly | Treat over-cap as config error; kills an affordable trade | |
| Clamp silently | No log; hides a buggy strategy | |

**User's choice:** Clamp to cap + log warning
**Notes:** Distinct from over-margin reject — over-cap leverage is still affordable.

---

## Maintenance-margin storage (MARGIN-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Compute-on-demand via read-model, current notional | Stateless compute; expose maintenance_margin + margin_ratio on PortfolioReadModel | ✓ |
| Stored mutable field on Position | Marked per bar; second source of truth | |
| Compute-on-demand, entry notional | Static; diverges from mark-to-market equity | |

**User's choice:** Compute-on-demand via read-model (current notional)
**Notes:** User raised the live-trading + UI angle. Resolved: read-model query (not pushed mutable state) is *more* correct for live — avoids a second source of truth fighting the N+4 Account venue-reconciliation mirror; persistence (N+3) is snapshot-then-store. Liquidation-formula notional basis finalized in P4.

---

## Config surface: leverage/margin fields (LEV-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Add portfolio max_leverage cap; keep enable_margin | TradingRules.max_leverage (Decimal, default 1); compose min(signal, instrument, portfolio) | ✓ |
| Rely on Instrument.max_leverage only | No portfolio cap | |
| Add both portfolio default_leverage and cap | Duplicates the strategy default | |

**User's choice:** Add portfolio max_leverage cap; keep enable_margin
**Notes:** No portfolio default_leverage — leverage is a strategy/signal concern.

---

## Runtime reconfig (update_config)

| Option | Description | Selected |
|--------|-------------|----------|
| Participate in update_config | Margin/leverage config flows through the COMP-02 atomic-swap seam; live-ready | ✓ |
| Construction-time only this phase | Defer runtime reconfig to live (N+4) | |

**User's choice:** Participate in update_config
**Notes:** Open positions keep opened-under terms; new config applies to new orders only.

---

## Margin-call / liquidation-warning event

| Option | Description | Selected |
|--------|-------------|----------|
| Defer; expose margin_ratio on read-model | No new EventType; UI computes warnings from margin_ratio | ✓ |
| Add a margin-call warning EventType now | Unconsumed/untested in backtest this phase | |

**User's choice:** Defer; expose margin_ratio on read-model
**Notes:** Avoids minting an unrouted EventType (anti-pattern); tracked as N+4 live/UI deferred idea.

---

## Commission interaction with margin

| Option | Description | Selected |
|--------|-------------|----------|
| Reserve = initial_margin + commission-on-notional | Fee on full traded notional; consistent with D-04 | ✓ |
| Reserve = initial_margin only | Settle commission separately on fill | |

**User's choice:** Reserve = initial_margin + commission-on-notional
**Notes:** Confirmed the Phase-4 liquidation penalty rides the existing commission/fee field (no new field).

---

## Locked-margin ownership

| Option | Description | Selected |
|--------|-------------|----------|
| Extend CashManager | Position-keyed locked-margin container; one cash authority; available = balance − order_reservations − locked_margin | ✓ |
| New MarginManager sub-manager | 5th manager; must coordinate with CashManager over the same cash | |

**User's choice:** Extend CashManager
**Notes:** Locked margin is reserved cash with position-lifetime scope; avoids a cross-manager invariant.

---

## Scale-in/out margin proportioning

| Option | Description | Selected |
|--------|-------------|----------|
| Pro-rata aggregate, one leverage per position | locked_margin = aggregate_notional/L; partial close releases p×margin + settles p×PnL; differing add-leverage clamped | ✓ |
| Per-tranche FIFO | Each fill locks at its own leverage; FIFO release; path-dependent | |

**User's choice:** Pro-rata aggregate, one leverage per position
**Notes:** Venue-realistic for isolated margin; deterministic; FIFO over-scoped.

---

## Negative free-margin stance (pre-P4)

| Option | Description | Selected |
|--------|-------------|----------|
| Track honestly, reject new orders, no force-close | Read-model reads negative/breached honestly; reject new orders; DEF-01-C open until P4 | ✓ |
| Clamp/block at maintenance in P2 | Premature liquidation-trigger behavior belonging in P4 | |

**User's choice:** Track honestly, reject new orders, no force-close
**Notes:** Clean P2/P4 boundary: P2 = accounting + reject; P4 = the force-close trigger.

---

## Claude's Discretion

- Exact placement of the `notional/L` division (admission gate vs portfolio reserve); free-margin computation plumbing.
- New sizing-policy name/signature (`LeveredFraction` vs `KellyFraction`) + resolver arm shape (mirror `RiskPercent`).
- `SignalEvent.leverage` field name/default plumbing; `PortfolioReadModel.maintenance_margin`/`margin_ratio` accessor signatures.
- BTCUSD `Instrument` `max_leverage` / `maintenance_margin_rate` values for the parked leveraged-long scenario (oracle-dark; realistic crypto defaults).

## Deferred Ideas

- Equity/drawdown-aware leverage policy (typed risk overlay) — replaces the scalar SignalEvent leverage later.
- Clip-to-fit over-margin handling (config-switchable alternative to reject).
- Vol-targeting / portfolio-level leverage overlays (gross/drawdown scaling, correlation caps).
- Per-tranche FIFO margin (revisit if one-leverage-per-position proves limiting).
- Margin-call / liquidation-warning EventType (N+4 live/UI).
- Liquidation force-close (LIQ-01, Phase 4); shorts + CR-01 + carry (Phase 3); funding/perp realism (Phase B / N+4); N+4 Account reconciliation mirror.
