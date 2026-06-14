---
title: Margin, Leverage & Shorts (crypto) — N+2 Design (999.4, Phase A)
date: 2026-06-14
context: superpowers:brainstorming session scoping N+2 before /gsd:new-milestone / /gsd:spec-phase
status: designed — ready to spec (Phase A in-scope; Phase B perp realism + trailing stops deferred)
---

# Design: N+2 — Margin, Leverage & Shorts (crypto)

**Roadmap entry:** `.planning/ROADMAP.md` Phase 999.4 (N+2)
**Scope of this doc:** the margin / leverage / shorts / funding portion of milestone 999.4.
Engine-native **trailing stops** (also bundled in the 999.4 title) are deliberately **out of
scope here** — they are resting-order ratchet logic in the `MatchingEngine`, a different
subsystem from accounting, and remain designed in the roadmap entry for later.

---

## 1. Goal

Enable **correct, deterministic, cross-validated** short selling and leverage in backtest,
backed by a **liquidation model** so portfolio equity can no longer drift impossibly negative
(today there is NO liquidation model — DEF-01-C — and an un-liquidated short can drive equity
negative). Land the minimal per-instrument `Instrument` value object the margin model consumes.

This milestone **changes results** the moment shorts/leverage/liquidation are enabled, so it
carries an **owner-gated golden-master re-baseline**, exactly like M5.

---

## 2. Scope decision: two phases, one deferred

The work splits cleanly into a correctness-critical shared core and an additive perp-realism
layer. We build the core now and defer the realism layer.

- **Phase A — IN THIS MILESTONE.** Shared margin / short / leverage / liquidation core. Carry
  modeled as **borrow interest** (a parameter, no external data). Liquidation triggered on
  **bar close**. Validated against `backtesting.py` + `backtrader` on the existing spot golden
  dataset (`data/BTCUSD_1d_ohlcv_2018_2026.csv`).

- **Phase B — DEFERRED TO-DO (tracked, out of scope).** Perp realism: funding-rate accrual,
  mark-price liquidation trigger, funding-data pipeline, `freqtrade` as a fourth oracle. Purely
  **additive** on the Phase A core — only the carry model and the liquidation trigger-price
  change. See §8.

Rationale: Phase A holds all the real correctness risk (margin accounting, liquidation math,
short-side fixes), validates on data and oracles we already have, and is a complete shippable
milestone on its own. Phase B is mostly data engineering and is safer deferred until the core
is regression-locked; if it slips it never blocks a finished Phase A.

---

## 3. Background — why mark price and funding exist (captured for future readers)

These two concepts are the entire reason perps (Phase B) cost more than spot margin (Phase A).

### Mark price
- **Last price** is the most recent trade on one venue — a single large order or thin book can
  spike it for a fraction of a second (a "wick").
- **Mark price** is a smoothed multi-exchange fair value (e.g. Binance: `median(price1, price2,
  contract_price)`, blending a multi-venue spot index with the funding basis). It does not move
  on wicks.
- **All venues trigger liquidation, unrealized PnL, and funding on mark price, never last price** —
  specifically to prevent wick/manipulation liquidations.
- **Backtest consequence:** our `MatchingEngine` triggers resting stops/limits against **intrabar
  high/low** (the most extreme tick in the bar). Reusing that for liquidation would liquidate on
  the wick low even though the smoothed mark never got there → **phantom liquidations** that
  wouldn't happen live. This single mismatch can flip a leveraged backtest result entirely.
- On **daily OHLCV** we have no mark series. Phase A's honest proxy is **liquidate on bar close**
  (no intrabar liquidation), documented as a known limitation. A real mark-price series is a
  Phase B concern (and only meaningful at finer timeframes).

### Funding
- Perps never expire, so nothing tethers the perp price to spot. **Funding** is the tether: every
  interval (8h / 4h / 1h — venue- and symbol-specific, **do not hardcode 8h**) longs and shorts
  exchange a cash payment.
- `funding_payment = position_notional × funding_rate`; rate **positive → longs pay shorts**,
  **negative → shorts pay longs**. Booked to **realized cash** (not unrealized PnL), and **only
  by positions open at the funding timestamp** (no proration).
- Not a rounding error: over a multi-month leveraged hold funding compounds into a multi-percent
  drag/credit on notional, and for the **pair-trading flagship** (long one leg, short the other)
  funding on both legs is often the dominant cost or the actual edge.
- **This is the key difference from Phase A's spot-margin model:** spot margin charges **borrow
  interest** (a simple daily rate, no data feed); perps charge **funding** (a real historical
  time-series you must fetch). Borrow interest is a parameter; funding is a dataset.

---

## 4. Spot margin vs linear perpetual — the path comparison

| Dimension | **Spot margin (Phase A)** | **Linear perpetual (Phase B)** |
|---|---|---|
| What a "short" is | Borrow the asset, sell, buy back to repay (owe units of BTC) | Negative-size USD-settled contract (owe nothing physical) |
| External data needed | **None** — existing spot OHLCV | Funding-rate history (+ optional mark-price series) |
| Carry cost | Borrow interest: `days × price × |size| × (rate/365)` | Funding: `notional × rate` at each interval, sign-dependent |
| PnL math | Long `size×(exit−entry)`; short `|size|×(entry−exit)` − interest | `d×size×(exit−entry)` ± funding, `d=+1/−1` |
| Margin reservation | `initial_margin = notional / leverage` (shared) | Identical (shared) |
| Liquidation trigger price | **Bar close** (no mark feed) | **Mark price** (phantom-wick risk otherwise) |
| Liquidation formula | Long `Entry×(1−(WB/size)/L)/(1+MMR)`; short mirrored | **Identical** (shared) |
| `Instrument` fields | `maintenance_margin_rate`, `max_leverage`, precision | Same **+** `settles_funding` |
| Cross-validation oracle | `backtesting.py` / `backtrader` (existing) | `freqtrade` (only one modeling funding+liquidation) |
| Golden dataset fit | Works on existing spot `BTCUSD_1d` CSV | Needs perp + funding data |

**Shared core ≈ two-thirds of the work, and it is the hard correctness-critical two-thirds.**
The spot-margin edge is small (interest one-liner, no data, existing oracles). The perp edge is
where the data engineering lives (funding pipeline, mark-price decision, new oracle).

---

## 5. Phase A architecture

### Key decision — where liquidation lives
Liquidation lives in **portfolio / cash accounting as a maintenance-margin breach check on the
BAR route** — **NOT** in the `MatchingEngine` alongside stop/limit triggers. The matching engine
is the source of truth for *order* fills; liquidation is an *equity* event. This matches
nautilus-trader (Account-level margin) and backtesting.py (`broker.next()` equity check), and
avoids entangling liquidation with intrabar high/low matching. A forced liquidation **emits a
`FillEvent`** so the existing position / cash / order-mirror reconciliation handles it uniformly.

### Reference designs adopted
- **freqtrade** — backtest behavior reference (the only ecosystem framework that models funding +
  liquidation in backtest; its isolated long/short liquidation formula is the one we copy).
- **nautilus-trader** — object-architecture reference (`MarginAccount` vs `CashAccount`,
  per-instrument + default leverage, `CryptoPerpetual` instrument with `margin_init`/`margin_maint`,
  `FundingRateUpdate` / `PositionAdjusted(FUNDING)` for Phase B). Note: nautilus has **no**
  liquidation in its backtest engine — we go further.
- **backtesting.py** — the minimal-viable liquidation (`equity ≤ 0` → close all) and the
  `margin = 1/leverage` ratio idea.
- **ccxt** — the data/API contract for Phase B (`fetchFundingRateHistory`, `fetchLeverageTiers`,
  `market['linear']`/`['settle']`).

---

## 6. Phase A components

1. **`Instrument` value object** (`core/instrument.py`, frozen, mirrors `core/bar.py::Bar`).
   Fields (each tied to a named consumer — YAGNI gate): `symbol`; `quote_currency` (default
   `"USD"`, principled source of cash precision); `price_precision`, `quantity_precision` (money
   quantize); `maintenance_margin_rate`, `max_leverage` (margin/liquidation + leverage);
   `settles_funding: bool` (lands now, **inert until Phase B**).
   - **Price precision is layered:** declared-wins → infer-from-data (guarded: read CSV string
     not float, cap max dp — DOGE-safe, fixes the catastrophic flat-`0.01` default) →
     `_DEFAULT_SCALES`. Pinned/oracle symbols (e.g. `BTCUSD`, declared 8dp) ALWAYS take the
     declared branch (inference would yield ~2–4dp and drift the golden master off
     `46189.87730727451`). `quantity_precision` is declared-or-default (not inferable).
   - **No `asset_class` taxonomy, no cash instrument** (crypto-first; a first-class `Currency`
     value object waits for deferred multi-currency accounting).
   - **`min_order_size` stays in `ExchangeLimits`** (venue×instrument property). Reconcile
     `Instrument` vs `ExchangeLimits` ownership during phase discussion.
   - **Behavioral gate:** whether the backtest *snaps/rounds* via `Instrument` (vs storing
     metadata only) is result-changing → falls under the owner-gated re-baseline.

2. **Margin accounting** — reserve `initial_margin = notional / leverage` on entry; reject/clip
   orders exceeding free margin (otherwise the sim silently over-leverages); track maintenance
   margin per position.

3. **Liquidation** — per-bar maintenance-margin breach check on **close**; **isolated margin**
   (self-contained, deterministic, loss floored at allocated margin); **flat per-instrument MMR**
   with position notional capped to first-tier validity (documented approximation; schema wired
   so a tier table can replace it later); **configurable liquidation penalty/fee** so liquidation
   PnL isn't optimistic; force-close via `FillEvent`.
   - Simplified isolated formula: `Long Liq = Entry×(1 − (WB/size)/L)/(1+MMR)`, short mirrored.

4. **Short enablement** — remove the `LONG_ONLY` guard in `StrategiesHandler.add_strategy`; fix
   the **CR-01 cover-arm hole** in `_resolve_signal_quantity` so a BUY-to-cover on a `SHORT_ONLY`
   book doesn't fall through to entry sizing and flip the book long. Shorts are modeled as a
   **first-class direction**, not a sign-flipped long (unbounded loss, own carry sign, asymmetric
   liquidation geometry).

5. **Borrow-interest carry** — `days × price × |size| × (rate/365)` on open shorts (the
   spot-margin analogue of funding; one parameter, no data feed). Backtrader's model is the
   reference.

6. **Config wiring** — flip on the existing `allow_short_selling` / `enable_margin` hooks in
   `config/portfolio.py` (currently off). **Levered Kelly** (fraction > 1) becomes expressible
   once margin exists — a Kelly fraction > 1 simply means notional = f × equity, posting
   `notional/L` as margin (structurally inexpressible in a cash-only model).

---

## 7. Phase A data flow, money, determinism, validation

### Data flow — a short, end to end
`SignalEvent` → `OrderManager` (cover-arm-aware sizing) → `OrderEvent` → `ExecutionHandler` /
`SimulatedExchange` fills → `FillEvent` → `Portfolio` (reserve margin, open negative-size
position) → each BAR: `update_portfolios_market_value` → maintenance-margin breach check → if
breached, emit forced-close `FillEvent` → portfolio + order-mirror reconcile as usual.

### Money & determinism
Decimal end-to-end including the liquidation formula and interest accrual (`float()` only at the
serialization/logging edge). Reuses the seeded RNG and injected `BacktestClock`; introduces **no
new nondeterminism**.

### Testing & validation
- Component tests per unit (Instrument, margin reservation, liquidation, cover-arm, interest).
- Integration test: a short scenario + a leveraged-long scenario through the full run path.
- Cross-validate liquidation / short PnL against `backtesting.py` and `backtrader`.
- **Owner-gated golden-master re-baseline** (this milestone is allowed to change results).
- **Flagship validation (may extend into planning):** real long/short **pair trading** —
  market-neutral cointegration/spread strategy (long one leg, short the other), the natural first
  real use of the short side. Confirm whether this lands in Phase A or as a follow-on.

---

## 8. Phase B — deferred to-do (captured, out of scope)

Purely additive on the Phase A core; only the carry model and liquidation trigger-price change.

- **Funding accrual** at funding-timestamp boundaries: `cash += −side_sign × mark_price × |size| ×
  rate`, only for positions open at the stamp; observe at settlement time (no look-ahead).
- **Mark-price liquidation trigger** — swap bar-close for a mark-price series; resolves the
  phantom-wick risk in §3.
- **Funding-data pipeline** — ccxt `fetchFundingRateHistory(symbol, since, limit)` → per-symbol
  CSV (`timestamp, rate, mark_price`) stored alongside OHLCV; per-symbol funding interval from
  market metadata (don't hardcode 8h).
- **`freqtrade` as a fourth oracle** — `backtesting.py`/`backtrader` cannot validate funding;
  freqtrade is the only installed-ecosystem framework that models funding + liquidation in
  backtest.

**Further-deferred (beyond Phase B):** cross margin (account-wide joint liquidation/cascade),
inverse/coin-margined perps (reciprocal PnL in BTC), full tiered MMR brackets, bankruptcy-price
liquidation / insurance fund / ADL, hedge mode. Each is its own milestone-sized effort behind the
same `Instrument`/position seam.

### Deferred: Account abstraction & ownership (→ N+4 live, NOT N+2)

Recorded here so N+2 explicitly does **not** introduce it. Full scope lives in `.planning/ROADMAP.md`
Phase 999.3 (N+4). Two distinct, separately-motivated drivers — do not conflate:

- **Live reconciliation mirror (the real driver, N+4).** The `Account` is the reconciled local
  mirror of the venue's balance/margin state. The **connector is the exchange adapter** (API keys,
  order I/O, streams); it *writes into* the Account — the Account does not talk to the venue. It is
  born in the live milestone because the **source of truth flips**: backtest computes state locally
  (Portfolio = account), live treats the venue as truth and must reconcile against it. No backtest
  analogue → not an N+2 concern. Shape: `CashAccount` vs `MarginAccount`; one per `(venue, login)`;
  Binance spot vs futures = two accounts; IBKR subaccounts = N accounts / one connection.
- **Cross-margin collateral pool (backtest-accounting, beyond Phase B).** Cross margin needs an
  account-equity pool for account-wide liquidation math. Phase A's **isolated** margin is
  per-position and needs no pool — which is exactly why N+2 needs no Account class.

**`user_id` is app-layer — strip from the engine, do NOT relocate onto Account.** The current
`Portfolio.user_id` (`portfolio.py`, `portfolio_handler.add_portfolio`, `validators.py`) is a
multi-tenancy/ownership concern. The FastAPI-wrap layer owns the `user_id → portfolio_id/account_id`
mapping externally; the engine stays owner-agnostic. Removing it is an independent cleanup
(constructor-signature ripple) — keep it OUT of N+2 so it doesn't muddy the golden-master re-baseline.

---

## 9. Open questions to resolve during planning

1. **`Instrument` vs `ExchangeLimits` ownership** — confirm `min_order_size` stays in
   `ExchangeLimits`; define how the two compose.
2. **Liquidation as a `FillEvent`** — confirm the forced-close `FillEvent` shape reconciles
   cleanly through the existing position/cash/order-mirror path (any new `FillStatus` needed?).
3. **Pair-trading flagship placement** — Phase A scope, or an immediate follow-on?
4. **Re-baseline timing** — when in the milestone the owner re-baselines the golden master.
5. **Where Phase B is tracked** — keep it in this doc only, or also add an explicit backlog entry
   in `.planning/ROADMAP.md` / a GSD capture.

---

## 10. References

**Venues:** Binance liquidation-price & maintenance-margin, mark-price/index, leverage brackets,
funding intro & history; Bybit USDT liquidation & funding history; OKX liquidation conditions &
funding. **Frameworks:** freqtrade leverage/futures/funding/liquidation docs + source; ccxt manual
(`setLeverage`, `fetchFundingRateHistory`, `fetchLeverageTiers`); nautilus-trader
`accounting/accounts/margin.pyx`, `model/instruments/crypto_perpetual.pyx`, `model/data.pyx`
(`FundingRateUpdate`); backtrader `comminfo.py` / `brokers/bbroker.py`; backtesting.py
`backtesting.py` (`_Broker`). **Theory:** Kelly criterion / optimal leverage (Kelly > 1 ⇒ borrow).
