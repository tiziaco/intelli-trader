# Phase 5: Engine-Native Trailing Stops - Context

**Gathered:** 2026-06-17
**Status:** Ready for planning
**Source:** Conversational discussion (design decisions locked with owner)

<domain>
## Phase Boundary

Implement **fixed-distance trailing stops inside the `MatchingEngine`**
(`itrader/execution_handler/matching_engine.py`), simulating the native trailing-stop
behavior that real venues offer (Binance, Alpaca, OANDA, IB all support native trailing
server-side — this phase models that, it does NOT build a strategy-driven modify/cancel-replace
loop).

A strategy can declare a `TRAILING_STOP` order; the engine rests it, ratchets the stop in the
favorable direction **only** as price extends, and triggers it look-ahead-safely. Matching stays
in the execution layer — the order handler declares the trailing bracket leg via
`parent_order_id`/`child_order_ids` and reconciles its mirror from `FillEvent`s; it never matches.

**Explicitly OUT of scope for Phase 5:**
- **Activation price** (deferred — Binance-futures/IB-only feature, not required for broker parity;
  only adds intrabar decisions + test matrix with no fidelity gain for the core).
- **Strategy-driven adaptive/ATR trailing** (the modify/cancel-replace path) — a separate, more
  expressive capability; not this phase.
- **Native-vs-synthetic live capability seam** — deferred to N+4 per ROADMAP.
- Ticks offset type and PRICE_TIER (would require per-instrument tick-size metadata; not needed).

</domain>

<decisions>
## Implementation Decisions (LOCKED — every one needs a numbered decision tag + golden tests)

### Mechanism
- Two offset types ONLY: **absolute (PRICE)** and **percentage (PERCENT)**. Modeled as one
  `TrailType` enum + one `Decimal` `trail_value` on the resting order / bracket leg.
- `TrailType` is a **config-domain enum** → lives in `config/`, NOT `core/enums/`, per the
  config-enum exception in `.planning/codebase/CONVENTIONS.md` (relocating it would invert the
  core→config dependency). Same pattern as `FeeModelType`, `SlippageModelType`, etc.
- Input unit (bps / percent / pips) is normalized to a `Decimal` at the **serialization edge**;
  the matching engine only ever sees a normalized `Decimal`. Store e.g. `Decimal("0.02")` for 2%.

### Behavioral decisions

**D-TRAIL-1 — Trail off the CLOSED bar's extreme.**
Longs ratchet the high-water-mark from the **closed** bar's HIGH; shorts ratchet the
low-water-mark from the closed bar's LOW (not the close). Note this is marginally more aggressive
than the oracles (backtesting.py / backtrader trail off the *close*) — accepted, documented as a
known systematic cross-val gap (see Testing). TRAIL-02 mandates "closed-bar extremes" → extremes,
not close.

**D-TRAIL-2 — Closed-bar / next-bar activation (look-ahead-safe). [TRAIL-02 core]**
The ratcheted stop computed from bar N's extreme becomes active on bar **N+1**. The engine NEVER
trails to this bar's extreme and triggers off the same bar. This is the explicit reversal of the
earlier conversational "high-first same-bar" idea, which contradicted TRAIL-02 and the
`bar_feed.py` look-ahead contract and matched none of the oracles. On bar N, the trigger is
evaluated against the stop level derived from bars ≤ N-1; then bar N's extreme updates the
HWM/LWM for use on bar N+1.

**D-TRAIL-3 — Seed HWM/LWM from the entry fill price.**
When the trailing stop is declared as a bracket child on entry fill, seed the high/low-water-mark
from the entry fill price. Initial stop = fill − trail (long) / fill + trail (short); it ratchets
only favorably thereafter, activating per D-TRAIL-2.

**D-TRAIL-4 — Gap-through fills reuse the static-stop gap-aware rule verbatim.**
A trailing stop is still a stop: on a clean gap-through bar it fills at the worse price (the open),
exactly like the existing static-stop gap convention. Compute/refresh the active trail level
BEFORE the gap test on each bar.

**D-TRAIL-5 — OCO: trailing SL replaces the fixed SL leg.**
A bracket has EITHER a fixed SL OR a trailing SL, not both. The existing same-bar OCO priority
rule applies unchanged to the now-dynamic SL leg (TP-limit vs trailing-SL same-bar resolution
uses the existing priority).

**D-TRAIL-6 — State ownership: matching engine resting book, not the order mirror.**
HWM/LWM and the current stop level live in the `MatchingEngine` resting book (`_resting`). The
order mirror only knows a trailing child exists and reconciles from `FillEvent`s. Preserves the
"execution is source of truth for fills" contract. (Deterministic + reproducible: the resting-book
state is a pure function of the bar sequence in single-threaded backtest.)

**D-TRAIL-7 — Validation rejects a non-viable trail.**
`EnhancedOrderValidator` rejects a `trail_value` that would place the initial stop at or below zero
(percent ≥ 1, or absolute ≥ entry/reference price) BEFORE the order rests.

**D-TRAIL-8 — Decimal discipline.**
Carry HWM/LWM at full 28-digit precision; `quantize(..., "price")` ONLY the computed stop level
used for the trigger comparison / fill. Money is Decimal end-to-end.

### Claude's Discretion (implementation detail)
- Exact field naming on the order/event; how the `TrailType`+`trail_value` thread through
  `OrderEvent` → bracket declaration → resting order.
- Internal `MatchingEngine` data-structure layout for HWM/LWM tracking on resting trailing orders.
- Test file/module organization (must cover both long AND short — see Testing).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Matching / execution (where the work lands)
- `itrader/execution_handler/matching_engine.py` — pure resting-order book; existing gap-aware
  intrabar stop/limit trigger evaluation + same-bar OCO priority. Trailing EXTENDS this path.
- `itrader/execution_handler/exchanges/simulated.py` — `SimulatedExchange` composes the
  `MatchingEngine`, applies fee/slippage, emits `FillEvent`.
- `itrader/price_handler/feed/bar_feed.py` — the seven-rule look-ahead-safety **bar-timing
  contract**; D-TRAIL-2 (closed-bar/next-bar) is governed by this contract.

### Order declaration / mirror (bracket leg)
- `itrader/order_handler/order_manager.py` — bracket declaration via
  `parent_order_id`/`child_order_ids`; mirror reconcile in `on_fill`. Never matches.
- `itrader/order_handler/order_validator.py` (`EnhancedOrderValidator`) — D-TRAIL-7 validation home.
- `itrader/core/enums/order.py` — `OrderType` (+ `VALID_ORDER_TRANSITIONS`); add `TRAILING_STOP`.

### Config / money / conventions
- `itrader/config/` — home of `TrailType` (config-enum exception).
- `itrader/core/money.py` — `to_money`, `quantize(value, instrument, kind)` (D-TRAIL-8).
- `.planning/codebase/CONVENTIONS.md` — config-enum exception, tab/space indentation hazard
  (matching_engine/order_handler are TAB-indented; config/ and core/ are 4-space — match the file).

### Cross-validation (TRAIL-03)
- `tests/golden/CROSS-VALIDATION.md` — oracle harness conventions.
- backtesting.py `TrailingStrategy` and backtrader `StopTrail` — both trail off the CLOSE and
  activate next bar; cross-val is WITHIN TOLERANCE, not byte-match.

</canonical_refs>

<specifics>
## Specific Ideas

- `TrailType` enum members: `PRICE` ("price", absolute quote distance), `PERCENT` ("percent",
  fraction of HWM/LWM).
- Long sell-stop: `stop = HWM − trail` (PRICE) or `HWM * (1 − trail)` (PERCENT), HWM = running max
  of closed-bar highs seeded at fill price.
- Short buy-stop: `stop = LWM + trail` (PRICE) or `LWM * (1 + trail)` (PERCENT), LWM = running min
  of closed-bar lows seeded at fill price.
- Ratchet invariant: stop moves only favorably (longs: non-decreasing; shorts: non-increasing).

</specifics>

<deferred>
## Deferred Ideas

- **Activation price** — start trailing only after price moves a threshold in favor
  (Binance-futures / IB). Model as an optional field later if wanted; default would be
  immediate-activation = None.
- **Strategy-driven / ATR adaptive trailing** via a modify/cancel-replace order path — separate,
  more expressive capability.
- **Native-vs-synthetic live capability seam** — deferred to N+4 (per ROADMAP).
- Trailing off the closed-bar CLOSE (tightest oracle match) — rejected in favor of "extremes" per
  TRAIL-02 wording; revisit only if cross-val tolerance proves too loose.

</deferred>

---

*Phase: 05-engine-native-trailing-stops*
*Context gathered: 2026-06-17 via conversational design discussion*
