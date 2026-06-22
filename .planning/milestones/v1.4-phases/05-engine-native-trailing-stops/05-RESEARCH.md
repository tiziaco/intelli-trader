# Phase 5: Engine-Native Trailing Stops - Research

**Researched:** 2026-06-17
**Domain:** Resting-order matching engine (intrabar trigger evaluation, stateful ratchet, look-ahead-safe bar mechanics) + order-type/event/validator/config plumbing
**Confidence:** HIGH (all findings grounded in the actual source files read this session; no external library API claims required)

## Summary

Phase 5 adds a `TRAILING_STOP` order type whose stop level is recomputed (ratcheted favorably-only) inside the `MatchingEngine` from closed-bar extremes and becomes active on the NEXT bar. The phase touches a thin, well-isolated set of seams: (1) the `MatchingEngine._evaluate`/`on_bar` matching path (where the ratchet step and the trigger reuse live), (2) the `OrderType` enum + maps, (3) `OrderEvent`/`Order` order-type-specific fields (`TrailType` + `trail_value` + per-order running extreme), (4) bracket declaration in `BracketManager` (trailing SL REPLACES the fixed SL leg), (5) `TrailType` as a new config-domain enum, (6) `EnhancedOrderValidator` for the non-viable-trail rejection, and (7) a cross-validation scenario against `backtesting.py`/`backtrader`.

The single most correctness-sensitive mechanic is D-TRAIL-2 (closed-bar/next-bar). The engine already has the right shape for it: `MatchingEngine` holds mutable per-order state in `_resting` (a `dict[OrderId, OrderEvent]`), `on_bar` is the single per-bar entry point, and the existing static-stop gap-aware fill rule and same-bar OCO priority are exactly the rules D-TRAIL-4 and D-TRAIL-5 must reuse verbatim. The crucial design constraint is **ordering within `on_bar`**: the trigger on bar N must be evaluated against a stop level derived from bars ≤ N-1, and ONLY AFTER that evaluation may bar N's extreme update the running HWM/LWM for use on bar N+1. There is friction here: `OrderEvent` is a **frozen** dataclass, so the running extreme cannot be mutated in place — the engine will need a side-table (or a `dataclasses.replace` write-back, as `modify` already does) to carry HWM/LWM. This is Claude's-discretion (D-TRAIL-6 places state ownership in the resting book), but the frozen-event constraint is a real implementation fact the plan must sequence around.

**Primary recommendation:** Model `trail_value`/`TrailType` as new optional fields on `OrderEvent` (mirroring how `stop_price`/`leverage` were added), carry the mutable running extreme + computed stop in a `MatchingEngine`-owned side-structure keyed by `OrderId` (NOT on the frozen event), add the ratchet-then-evaluate ordering as an explicit two-phase step inside `on_bar` that runs BEFORE the existing `_evaluate` trigger pass uses the level, reuse the existing STOP gap-aware fill and OCO priority verbatim, declare the trailing SL as a bracket child that replaces the fixed SL leg in `BracketManager`, and add a single crafted long+short cross-val scenario that is within-tolerance (not byte-match) against the oracles which trail off the close.

## User Constraints (from CONTEXT.md)

### Locked Decisions

**Mechanism**
- Two offset types ONLY: **absolute (PRICE)** and **percentage (PERCENT)**. Modeled as one `TrailType` enum + one `Decimal` `trail_value` on the resting order / bracket leg.
- `TrailType` is a **config-domain enum** → lives in `config/`, NOT `core/enums/`, per the config-enum exception in `.planning/codebase/CONVENTIONS.md`. Same pattern as `FeeModelType`, `SlippageModelType`, etc.
- Input unit (bps / percent / pips) is normalized to a `Decimal` at the **serialization edge**; the matching engine only ever sees a normalized `Decimal`. Store e.g. `Decimal("0.02")` for 2%.

**D-TRAIL-1 — Trail off the CLOSED bar's extreme.** Longs ratchet the high-water-mark from the **closed** bar's HIGH; shorts ratchet the low-water-mark from the closed bar's LOW (not the close). Marginally more aggressive than the oracles (they trail off the close) — accepted, documented as a known systematic cross-val gap. TRAIL-02 mandates "closed-bar extremes" → extremes, not close.

**D-TRAIL-2 — Closed-bar / next-bar activation (look-ahead-safe). [TRAIL-02 core]** The ratcheted stop computed from bar N's extreme becomes active on bar **N+1**. The engine NEVER trails to this bar's extreme and triggers off the same bar. On bar N, the trigger is evaluated against the stop level derived from bars ≤ N-1; then bar N's extreme updates the HWM/LWM for use on bar N+1.

**D-TRAIL-3 — Seed HWM/LWM from the entry fill price.** When the trailing stop is declared as a bracket child on entry fill, seed the high/low-water-mark from the entry fill price. Initial stop = fill − trail (long) / fill + trail (short); ratchets only favorably thereafter, activating per D-TRAIL-2.

**D-TRAIL-4 — Gap-through fills reuse the static-stop gap-aware rule verbatim.** A trailing stop is still a stop: on a clean gap-through bar it fills at the worse price (the open), exactly like the existing static-stop gap convention. Compute/refresh the active trail level BEFORE the gap test on each bar.

**D-TRAIL-5 — OCO: trailing SL replaces the fixed SL leg.** A bracket has EITHER a fixed SL OR a trailing SL, not both. The existing same-bar OCO priority rule applies unchanged to the now-dynamic SL leg.

**D-TRAIL-6 — State ownership: matching engine resting book, not the order mirror.** HWM/LWM and the current stop level live in the `MatchingEngine` resting book (`_resting`). The order mirror only knows a trailing child exists and reconciles from `FillEvent`s. Deterministic: the resting-book state is a pure function of the bar sequence in single-threaded backtest.

**D-TRAIL-7 — Validation rejects a non-viable trail.** `EnhancedOrderValidator` rejects a `trail_value` that would place the initial stop at or below zero (percent ≥ 1, or absolute ≥ entry/reference price) BEFORE the order rests.

**D-TRAIL-8 — Decimal discipline.** Carry HWM/LWM at full 28-digit precision; `quantize(..., "price")` ONLY the computed stop level used for the trigger comparison / fill. Money is Decimal end-to-end.

### Claude's Discretion
- Exact field naming on the order/event; how `TrailType`+`trail_value` thread through `OrderEvent` → bracket declaration → resting order.
- Internal `MatchingEngine` data-structure layout for HWM/LWM tracking on resting trailing orders.
- Test file/module organization (must cover both long AND short).

### Deferred Ideas (OUT OF SCOPE)
- **Activation price** (Binance-futures/IB-only). Default would be immediate-activation = None.
- **Strategy-driven / ATR adaptive trailing** via modify/cancel-replace order path — separate capability.
- **Native-vs-synthetic live capability seam** — deferred to N+4.
- **Ticks offset type and PRICE_TIER** (need per-instrument tick-size metadata; not needed).
- Trailing off the closed-bar CLOSE (tightest oracle match) — rejected in favor of "extremes" per TRAIL-02.

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| TRAIL-01 | A strategy can declare a `TRAILING_STOP` order; `MatchingEngine` ratchets the resting stop favorably-only as price extends | New `OrderType.TRAILING_STOP` member + `order_type_map` entry (`core/enums/order.py`); `TrailType`+`trail_value` fields on `OrderEvent`/`Order`; ratchet step in `MatchingEngine.on_bar`/`_evaluate`; `BracketManager` declares the trailing SL child |
| TRAIL-02 | The trail updates from closed-bar extremes and becomes active on the next bar (look-ahead-safe per `bar_feed.py`) | D-TRAIL-2 maps to the engine's existing one-bar-lag convention (bar_feed rules 2/3/5); explicit ratchet-AFTER-evaluate ordering inside `on_bar`; reuse of `_evaluate` STOP branch |
| TRAIL-03 | Trailing-stop behavior cross-validated against `backtesting.py` and `backtrader` | Existing harness: `scripts/cross_validate*.py` + `scripts/crossval/` runners + `tests/golden/CROSS-VALIDATION*.md`; new long+short crafted scenario; within-tolerance (oracles trail off close, D-TRAIL-1 trails off high) |

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Ratchet HWM/LWM + recompute stop level | Execution (`MatchingEngine`) | — | D-TRAIL-6: resting-book state ownership; matching is execution-layer source of truth for fills (CLAUDE.md) |
| Trigger evaluation + gap-aware fill | Execution (`MatchingEngine._evaluate`) | — | D-TRAIL-4 reuses existing STOP branch verbatim |
| Same-bar OCO (trailing-SL vs TP-limit) | Execution (`MatchingEngine._pick_bracket_winner`) | — | D-TRAIL-5 reuses existing STOP-beats-LIMIT priority |
| Declare trailing bracket child | Order (`BracketManager`) | — | Order handler declares brackets via `parent_order_id`; never matches (CLAUDE.md) |
| Mirror reconcile from FillEvents | Order (`ReconcileManager`) | — | Order mirror only knows a trailing child exists (D-TRAIL-6) |
| `TrailType`+`trail_value` carriage | Events (`OrderEvent`) / Entity (`Order`) | — | Order-type-specific fields thread signal→order→event→resting order |
| Non-viable-trail rejection | Order (`EnhancedOrderValidator`) | Execution (`SimulatedExchange.validate_order`) | D-TRAIL-7 in domain validator; execution-layer `validate_order` is the defense-in-depth second path |
| `TrailType` enum definition | Config (`config/`) | — | Config-enum exception (CONVENTIONS.md) — relocating to core/ inverts core→config dependency |
| Normalize input unit → Decimal | Serialization edge (strategy/signal) | — | Engine only sees a normalized Decimal (locked decision) |

## Standard Stack

No new external packages. The phase is implemented entirely with the existing stdlib + project primitives.

### Core (already present — no install)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `decimal` (stdlib) | 3.13 | HWM/LWM + stop-level math (D-TRAIL-8) | Money is Decimal end-to-end (locked decision) |
| `dataclasses` (stdlib) | 3.13 | `OrderEvent` frozen event; `dataclasses.replace` for resting-book write-back | Already used by `MatchingEngine.modify` |
| `backtesting.py` | 0.6.5 | Cross-val oracle (gating) — `TrailingStrategy` | Already pinned in `pyproject.toml`; existing harness |
| `backtrader` | 1.9.78.123 | Cross-val oracle (gating) — `StopTrail` | Already pinned in `pyproject.toml`; existing harness |
| `pytest` / `pytest-cov` | 8.4.2 / 7.1.0 | Unit + e2e tests | Project test runner |

**Installation:** None. `[VERIFIED: pyproject.toml]` — `backtesting = "0.6.5"`, `backtrader = "1.9.78.123"` both already declared.

## Package Legitimacy Audit

> **Not applicable.** This phase installs ZERO external packages. All work uses stdlib (`decimal`, `dataclasses`) and packages already present in `poetry.lock`. No registry verification or slopcheck required — no `npm install` / `pip install` step exists in this phase.

## Architecture Patterns

### System Architecture Diagram (trailing-stop data flow)

```
STRATEGY declares TRAILING_STOP intent
   (TrailType + trail_value normalized to Decimal at the serialization edge)
        |
        v
SignalEvent  --(carries trail fields)-->  OrderManager.process_signal
        |                                        |
        |                                  AdmissionManager (admission/sizing/validation)
        |                                        |
        |                                  EnhancedOrderValidator  <-- D-TRAIL-7: reject non-viable trail
        |                                        |
        |                                  BracketManager._assemble_bracket_and_emit
        |                                        |   D-TRAIL-5: trailing SL child REPLACES fixed SL leg
        |                                        v
        |                                  OrderEvent(order_type=TRAILING_STOP, trail_type, trail_value,
        |                                             parent_order_id=<entry>)  --> global_queue
        v                                        |
ExecutionHandler.on_order --> SimulatedExchange.on_order
        |
        v
   _admit_order (validate_order = defense-in-depth) --> MatchingEngine.submit  (order RESTS, dormant until parent fills)
        ...
   PARENT entry fills (FillEvent EXECUTED) --> seed HWM/LWM = entry fill price (D-TRAIL-3)
        ...
BarEvent (bar N) --> SimulatedExchange.on_market_data --> MatchingEngine.on_bar
        |
        |  PHASE A: evaluate trigger against stop level derived from bars <= N-1
        |           (reuse STOP branch gap-aware fill, D-TRAIL-4)  --> maybe FillDecision
        |  PHASE B: AFTER evaluation, update HWM/LWM from bar N's HIGH/LOW (D-TRAIL-1),
        |           recompute + ratchet stop favorably-only for use on bar N+1 (D-TRAIL-2)
        v
   FillDecision / CancelDecision --> SimulatedExchange emits FillEvent(EXECUTED / CANCELLED)
        |
        v
   OrderManager.on_fill (ReconcileManager) reconciles the mirror (knows only that a trailing child exists)
```

The diagram above traces the primary use case (long entry → trailing SL declared → ratchet → trigger) end-to-end. File-to-implementation mapping is in the responsibility map and the canonical-refs of CONTEXT.md.

### Pattern 1: Add an order type (mirror how STOP/LIMIT exist)
**What:** `OrderType` is a plain `Enum` (NOT `str, Enum`) in `core/enums/order.py:11-30` with members `MARKET`/`STOP`/`LIMIT`, a case-insensitive `_missing_`, and a parallel `order_type_map` dict (lines 59-63).
**When to use:** Adding `TRAILING_STOP`.
**Example:**
```python
# Source: itrader/core/enums/order.py:11-63 (read this session)
class OrderType(Enum):
    MARKET = "MARKET"
    STOP = "STOP"
    LIMIT = "LIMIT"
    TRAILING_STOP = "TRAILING_STOP"   # NEW — member + .value string
# ... _missing_ already handles any new member case-insensitively ...
order_type_map = {
    "MARKET": OrderType.MARKET,
    "STOP": OrderType.STOP,
    "LIMIT": OrderType.LIMIT,
    "TRAILING_STOP": OrderType.TRAILING_STOP,   # NEW — parallel map entry
}
```
**CRITICAL:** `_init_fee_model`/`_init_slippage_model` in `simulated.py` use `assert_never` exhaustiveness over the FEE/SLIPPAGE enums — those are unaffected. But check every `match`/`assert_never` over `OrderType` and every `if/elif` chain in `_evaluate` (matching_engine.py:154-182), `_emit_fill` (`is_maker = event.order_type is OrderType.LIMIT`, simulated.py:273), and `_fill_reason` (matching_engine.py:316-322). A `TRAILING_STOP` must be classified as a STOP-like taker for fee/slippage (`is_maker=False`, slippage applies) and as a STOP for `_fill_reason`.

### Pattern 2: `TrailType` config-enum (mirror `FeeModelType`/`SlippageModelType`)
**What:** Config-domain enums are `(str, Enum)` with lowercase `.value`s, defined in `config/` and re-exported via `config/__init__.py`.
**When to use:** Adding `TrailType` (`PRICE`/`PERCENT`).
**Example:**
```python
# Source: itrader/config/exchange.py:26-43 (read this session) — the analog to follow
class FeeModelType(str, Enum):
    ZERO = "zero"
    PERCENT = "percent"
    # ...
# TrailType follows this exact shape; per the locked decision it is a config-domain enum.
class TrailType(str, Enum):
    PRICE = "price"       # absolute quote distance
    PERCENT = "percent"   # fraction of HWM/LWM
```
Re-export it from `config/__init__.py` (the `__all__` list, exchange.py:67-106) the same way `FeeModelType` is. **Placement choice for the plan:** `FeeModelType`/`SlippageModelType` live in `config/exchange.py`. A trailing-stop is an order concept — `config/order.py` (the home of `OrderConfig`) is the more cohesive home, but either is convention-compliant. Flag this as a plan decision.

### Pattern 3: Order-type-specific fields on the frozen event (mirror `stop_price`/`leverage`)
**What:** `OrderEvent` (`events_handler/events/order.py:16-67`) is `@dataclass(frozen=True, slots=True, kw_only=True)`. It already carries optional order-type-specific fields with defaults: `stop_price: Decimal | None = None` (line 58), `leverage: Decimal = Decimal("1")` (line 62). `Order.new_order_event` reads them off the entity via `getattr(order, 'stop_price', None)` / `getattr(order, 'leverage', Decimal("1"))` (lines 121-125) — the robust-to-old-stubs pattern.
**When to use:** Adding `trail_type: TrailType | None = None` and `trail_value: Decimal | None = None`.
**Example:**
```python
# Source: events_handler/events/order.py:58-62 (the pattern to copy)
stop_price: Decimal | None = None
leverage: Decimal = Decimal("1")
# NEW (Phase 5):
trail_type: "TrailType | None" = None     # None for non-trailing orders
trail_value: Decimal | None = None        # normalized Decimal (e.g. Decimal("0.02"))
```
The `Order` entity (`order_handler/order.py:34-100`) needs the same two fields + a `new_trailing_stop_order` factory mirroring `new_stop_order` (lines 227-271). `new_order_event` reads them via the same `getattr` default pattern.

### Pattern 4: Bracket child declaration (trailing SL replaces fixed SL)
**What:** `BracketManager._assemble_bracket_and_emit` (`order_handler/brackets/bracket_manager.py:54-223`) builds the SL child via `Order.new_stop_order(...)` and sets `sl_order.parent_order_id = primary.id` (lines 138-150). The TP child is `Order.new_limit_order(...)`. Two-directional linkage: `primary.child_order_ids = [child.id ...]` (lines 168-170). For `PercentFromFill`, children are created at parent fill in `_create_fill_anchored_children` (lines 225-276) — this is where D-TRAIL-3 (seed from entry fill price) most naturally lands.
**When to use:** D-TRAIL-5 — when the bracket declares a trailing SL, build it via the new `Order.new_trailing_stop_order(...)` instead of `new_stop_order(...)`, carrying `trail_type`/`trail_value`. The TP-limit leg and OCO linkage are unchanged.
**Example:**
```python
# Source: bracket_manager.py:138-150 (the fixed-SL path that the trailing-SL path replaces)
if sl_price > 0:
    sl_order = Order.new_stop_order(time=..., action=..., price=sl_price, ...)
    sl_order.parent_order_id = primary.id
# D-TRAIL-5: when trailing is declared, build a trailing-stop child instead:
#   sl_order = Order.new_trailing_stop_order(time=..., action=..., trail_type=..., trail_value=..., ...)
# EITHER fixed SL OR trailing SL — never both.
```
**Friction (report, don't fix):** `BracketManager` currently builds the fixed SL from an explicit `sl_price` (from `signal_event.stop_loss` or `_bracket_levels`). A trailing SL has NO fixed entry price at declaration — its initial stop is computed at fill (D-TRAIL-3). The `PercentFromFill` carve-out (`_brackets.arm(...)` + `_create_fill_anchored_children`) is the existing precedent for "child priced from actual fill" and is the cleanest seam for a trailing SL. The plan should route a declared trailing SL through a fill-anchored path analogous to `PercentFromFill`, OR seed HWM/LWM in the matching engine when the resting trailing order is first submitted with the parent's eventual fill. Either way the declaration must NOT carry a meaningful `price` field as a static trigger.

### Pattern 5: The ratchet-then-evaluate ordering inside `on_bar` (D-TRAIL-2 — the critical mechanic)
**What:** `MatchingEngine.on_bar` (`matching_engine.py:184-304`) runs two passes (parents pass 1, children pass 2). Each order is triggered via `_evaluate(order, bar)` (lines 137-182). The STOP branch (lines 158-164) is the verbatim rule D-TRAIL-4 reuses:
```python
# Source: matching_engine.py:158-164 (the gap-aware STOP fill — reuse verbatim)
if order.order_type == OrderType.STOP:
    if order.action is Side.SELL:           # stop-loss on a long
        if low <= trigger:
            return min(open_, trigger)      # pessimistic gap-down
    else:                                   # BUY stop (cover short)
        if high >= trigger:
            return max(open_, trigger)      # pessimistic gap-up
```
**When to use:** A `TRAILING_STOP` evaluates EXACTLY like a STOP, using its CURRENT (already-ratcheted, derived from bars ≤ N-1) stop level as `trigger`. AFTER the evaluation pass, the engine updates the running extreme from bar N and recomputes the ratcheted stop for bar N+1.
**Where the ordering lives:** The ratchet update must happen AFTER `_evaluate` reads the level on bar N but is consumed on bar N+1. Two viable layouts (Claude's discretion):
  - (a) At the END of `on_bar`, after both fill passes complete and OCO cancels are resolved, iterate the still-resting trailing orders and update HWM/LWM + recompute stop from bar N's high/low.
  - (b) Carry "current stop level" as state; a separate `_ratchet(bar)` private called at the END of `on_bar`.
**Anti-pattern (explicitly forbidden by D-TRAIL-2):** Updating HWM/LWM at the TOP of `on_bar` (or inside `_evaluate`) from THIS bar's high, then triggering off this bar's low — the "high-first same-bar" idea the CONTEXT explicitly reverses. It contradicts the bar_feed contract and matches none of the oracles.

### Anti-Patterns to Avoid
- **Mutating the frozen `OrderEvent` in place to store HWM/LWM.** `OrderEvent` is `frozen=True, slots=True` — assignment raises `FrozenInstanceError`. Use a `MatchingEngine`-owned side-table keyed by `OrderId`, or `dataclasses.replace` write-back (as `modify` does, matching_engine.py:103-127). D-TRAIL-6 places state in the resting book; a parallel `dict[OrderId, TrailState]` is the cleanest layout.
- **Matching inside `OrderHandler`/`OrderManager`/`BracketManager`.** The order handler declares brackets and reconciles the mirror; it NEVER matches (CLAUDE.md anti-pattern). All ratchet/trigger logic is execution-layer.
- **Ratcheting same-bar then triggering same-bar.** See Pattern 5 anti-pattern (D-TRAIL-2).
- **Quantizing HWM/LWM on every bar.** D-TRAIL-8: carry full 28-digit precision; `quantize(..., "price")` ONLY the computed stop level used for the trigger comparison/fill — never the running extreme.
- **Adding `TrailType` to `core/enums/`.** Config-enum exception (CONVENTIONS.md) — it lives in `config/`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Gap-through fill on a trailing stop | A new gap-fill formula | The existing STOP branch in `_evaluate` (matching_engine.py:158-164) | D-TRAIL-4 mandates verbatim reuse; `min(open_, trigger)` / `max(open_, trigger)` already encodes pessimistic gap semantics matched by both oracles |
| Same-bar trailing-SL vs TP-limit resolution | New priority logic | `_pick_bracket_winner` (matching_engine.py:306-314) | D-TRAIL-5: STOP-beats-LIMIT priority applies unchanged to the dynamic SL leg |
| OCO sibling cancel when one leg fills | New OCO scan | The existing sibling-scan in `on_bar` (matching_engine.py:288-302) | Bracket OCO already cancels siblings on any leg fill; a trailing SL is just a STOP-typed sibling |
| Bracket child priced from the actual fill | New fill-anchored path | The `PercentFromFill` carve-out (`_brackets.arm` + `_create_fill_anchored_children`, bracket_manager.py:121-134, 225-276) | D-TRAIL-3 (seed from entry fill) is structurally identical to PercentFromFill's "price from actual fill" |
| Decimal entry / rounding | `Decimal(float)` or per-op quantize | `to_money` + `quantize(value, instrument, "price")` (core/money.py:59-86) | Locked money policy; `quantize` reads scale off the `Instrument` |
| Resting-order replace | In-place mutation | `dataclasses.replace` (matching_engine.py:103-127, `modify`) | Frozen events; `modify` already demonstrates replace-in-book preserving `order_id` |
| Cross-val oracle reconcile helpers | New diff/align code | `scripts/crossval/reconcile.py` (`align_trades`/`build_metric_table`/`recompute_headline`/`flag_divergences`) | The accounting + limit cross-val both reuse these verbatim |

**Key insight:** A trailing stop is a STOP whose trigger price changes between bars. ~90% of the engine work is the ratchet bookkeeping + the ratchet-then-evaluate ordering; the trigger, gap-fill, OCO, and fee/slippage paths are ALL existing STOP machinery reused unchanged.

## Runtime State Inventory

> This phase is feature-additive to a single-threaded backtest engine, not a rename/migration. The only "runtime state" is the in-process `MatchingEngine._resting` book, which is rebuilt fresh every run (no persistence on the backtest path). No external datastore, OS registration, or build artifact carries trailing-stop state.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — the backtest order store is `in_memory` (`OrderStorageFactory`); the resting book is in-process and rebuilt per run. PostgreSQL order storage is a `NotImplementedError` placeholder (not on the backtest path). | None |
| Live service config | None — this is a backtest-only feature; the native-vs-synthetic live seam is explicitly deferred to N+4. | None |
| OS-registered state | None — no daemons, schedulers, or system services involved. | None |
| Secrets/env vars | None — no new credentials; `performance.rng_seed` (existing, default 42) governs determinism; trailing is a pure function of the bar sequence (D-TRAIL-6). | None |
| Build artifacts | None — pure-Python source change; no compiled artifacts, no `egg-info` rename. | None |

**Nothing found in any category — verified by reading the backtest composition root surface (`SimulatedExchange`, `MatchingEngine`, `OrderStorageFactory` is `in_memory` for backtest per CLAUDE.md) and the determinism seam.**

## Common Pitfalls

### Pitfall 1: Same-bar ratchet+trigger (the look-ahead trap)
**What goes wrong:** Updating HWM/LWM from bar N's high then triggering the (tighter) stop off bar N's low in the same `on_bar` call — uses information not yet available, inflates results, matches no oracle.
**Why it happens:** It "feels" natural to update the running extreme at the top of the per-bar loop.
**How to avoid:** Evaluate the trigger FIRST against the stop derived from bars ≤ N-1, THEN update HWM/LWM at the END of `on_bar`. Cross-check against bar_feed.py rules 2/3/5 (the one-bar-lag fill convention). This is the single phase-defining invariant — make it an explicit, separately-tested step.
**Warning signs:** A trailing-stop unit test where a single bar both ratchets to a new extreme AND fills at the new tighter level; a cross-val run where iTrader fills EARLIER than both oracles.

### Pitfall 2: Frozen-event mutation attempt
**What goes wrong:** `order_event.hwm = new_high` raises `FrozenInstanceError` (slots + frozen).
**Why it happens:** D-TRAIL-6 says "state lives in the resting book" — but the resting book stores frozen events.
**How to avoid:** Keep a `MatchingEngine`-owned side-table (`dict[OrderId, TrailState]` with mutable HWM/LWM + current stop), parallel to `_resting`. Pop it when the order leaves the book (mirror the `_resting.pop` sites at lines 235, 298-302). OR `dataclasses.replace` the event each bar (heavier; `modify` shows the pattern). Side-table is simpler and keeps the event immutable.
**Warning signs:** `FrozenInstanceError` at runtime; or a leaked `TrailState` entry for a filled/cancelled order.

### Pitfall 3: `filterwarnings = ["error"]` + `--strict-markers`
**What goes wrong:** Any unexpected warning fails the suite; an undeclared marker fails collection.
**Why it happens:** `pyproject.toml` sets `filterwarnings = ["error", ...]`, `--strict-markers`, `--strict-config`; only `unit`, `integration`, `slow`, `e2e` markers are registered (CLAUDE.md).
**How to avoid:** New unit tests go under `tests/unit/execution/` (auto-tagged `unit` by `tests/conftest.py`); e2e leaves under `tests/e2e/<scenario>/` (auto-tagged `e2e`). Do NOT import `backtesting`/`backtrader` under `tests/` — the cross-val oracle imports live in `scripts/crossval/` (SCRIPT-ONLY, D-10) precisely to keep `filterwarnings=["error"]` intact. Use only the four registered markers.
**Warning signs:** Collection error on an unknown marker; a FutureWarning from a reference engine import surfacing as a test error.

### Pitfall 4: `mypy --strict` exhaustiveness over `OrderType`
**What goes wrong:** Adding `TRAILING_STOP` without handling it in every `match`/`assert_never` over `OrderType` fails `mypy --strict`, or silently mis-routes through an `if/elif` fallthrough.
**Why it happens:** `simulated.py` uses `assert_never` for fee/slippage enums; `_evaluate`/`_fill_reason` use `if/elif` chains that fall through to `return None` / `"market fill"`.
**How to avoid:** Grep every `OrderType.` reference and `order_type` switch. Specifically: `_evaluate` (must add a TRAILING_STOP arm that reuses the STOP logic with the ratcheted level), `_fill_reason` (must classify as a stop), `_emit_fill` `is_maker`/slippage gating (must be taker, slippage applies). `mypy --strict` is the gate (CLAUDE.md: "the only static-analysis gate is mypy").
**Warning signs:** mypy `assert_never` error; a trailing stop filling with `is_maker=True` (no slippage) in a test.

### Pitfall 5: Tab vs 4-space indentation
**What goes wrong:** A mixed-indentation diff breaks a tab file.
**Why it happens:** `matching_engine.py` and `simulated.py` are **4-SPACE** (verified this session — read the files); `order_handler/` modules (`order.py`, `bracket_manager.py`, `order_manager.py`, `reconcile_manager.py`, `order_handler.py`) are **TAB**; `config/`, `core/`, `events_handler/events/` are **4-SPACE**.
**How to avoid:** Match the file. See the per-file table below.
**Warning signs:** `git diff` showing whitespace-only churn; Python `TabError`.

### Pitfall 6: Trailing SL has no static entry price at declaration
**What goes wrong:** `BracketManager` and the validators assume a positive `price`/`stop_price` on the SL child; a trailing SL's initial trigger is only known at parent fill (D-TRAIL-3).
**Why it happens:** The existing SL path is fixed-price (`new_stop_order(price=sl_price)`); `EnhancedOrderValidator._validate_critical_fields` rejects `order.price <= 0` (order_validator.py:213-220) and `SimulatedExchange.validate_order` rejects `event.price <= 0` (simulated.py:490-491).
**How to avoid:** Route the trailing SL through a fill-anchored declaration (PercentFromFill precedent) so the initial stop is computed from the actual fill, OR define a sentinel/derived initial price that passes both validators. The D-TRAIL-7 viability check (`trail_value` would put initial stop ≤ 0) belongs in `EnhancedOrderValidator` and must be expressed against the trail_value + the reference/entry price, NOT a static `price` field. Plan must reconcile the validator's positive-price assumption with a trailing order whose price is dynamic.

## Code Examples

### Existing STOP trigger (the rule D-TRAIL-4 reuses)
```python
# Source: itrader/execution_handler/matching_engine.py:158-164
if order.order_type == OrderType.STOP:
    if order.action is Side.SELL:           # stop-loss on a long
        if low <= trigger:
            return min(open_, trigger)      # pessimistic gap-down
    else:                                   # BUY stop (cover short)
        if high >= trigger:
            return max(open_, trigger)      # pessimistic gap-up
```

### Resting-book replace-in-place (the frozen-event write-back precedent)
```python
# Source: itrader/execution_handler/matching_engine.py:122-127 (modify)
self._resting[order_id] = dataclasses.replace(
    order,
    price=order.price if new_price is None else to_money(new_price),
    quantity=order.quantity if new_quantity is None else to_money(new_quantity),
)
```

### Ratchet math (locked decision — long/short formulas)
```python
# Source: 05-CONTEXT.md "Specific Ideas" — to implement inside MatchingEngine ratchet step
# Long sell-stop:  stop = HWM - trail (PRICE)  |  HWM * (1 - trail) (PERCENT)
#                  HWM = running max of CLOSED-bar highs, seeded at entry fill price
# Short buy-stop:  stop = LWM + trail (PRICE)  |  LWM * (1 + trail) (PERCENT)
#                  LWM = running min of CLOSED-bar lows, seeded at entry fill price
# Ratchet invariant: longs non-decreasing stop; shorts non-increasing stop.
# quantize(stop, instrument, "price") ONLY on the stop used for the trigger/fill (D-TRAIL-8).
```

### Order-type-specific optional field pattern
```python
# Source: itrader/events_handler/events/order.py:58-62 + 121-125 (the stop_price/leverage precedent)
stop_price: Decimal | None = None
leverage: Decimal = Decimal("1")
# read back robustly in new_order_event:
stop_price=getattr(order, 'stop_price', None),
leverage=getattr(order, 'leverage', Decimal("1")),
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Strategy-driven SL modify loop (the synthetic-live design) | Engine-native trailing inside `MatchingEngine` (ideal trail) | Phase 5 (this) | Backtest models the ideal native trail; synthetic-live modify/latency/step is N+4 |
| Order matched anywhere | Single matching path in execution layer (D-13) | v1.0 | Trailing ratchet/trigger MUST be execution-layer; order handler only declares |
| `OrderType` as `str, Enum` int values | Plain `Enum` with explicit string `.value` + `_missing_` | v1.x (04-05 cutover) | `TRAILING_STOP` follows the current plain-Enum shape |

**Deprecated/outdated:**
- The "high-first same-bar" trailing idea (conversational) — explicitly REVERSED by D-TRAIL-2.
- Building a strategy-side modify/cancel-replace trailing loop — out of scope (deferred capability).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `backtesting.py` 0.6.5 exposes `TrailingStrategy` (`set_trailing_sl`) and `backtrader` 1.9.78.123 exposes `StopTrail`/`StopTrailLimit`, both trailing off the close and activating next bar | Cross-Validation Architecture | If an oracle's trailing API differs, the cross-val runner needs a different config; the within-tolerance gap may differ. The KNOWN-FACT (oracles trail off close vs D-TRAIL-1 trails off high) was supplied in the phase brief, not independently re-verified against the installed versions this session. Plan should verify the exact API in the runner during implementation. |
| A2 | Routing the trailing SL through a fill-anchored (PercentFromFill-style) declaration is the cleanest seam for D-TRAIL-3 | Pattern 4 / Pitfall 6 | If the planner prefers seeding HWM/LWM at submit-time instead, the bracket-declaration site differs — but both satisfy the locked decisions. This is Claude's-discretion territory; the assumption only affects WHERE the seed lands, not WHETHER it works. |
| A3 | `config/order.py` (vs `config/exchange.py`) is the more cohesive home for `TrailType` | Pattern 2 | Either location is convention-compliant; wrong guess only means a different (still-valid) file. Flagged as a plan decision. |

## Open Questions (RESOLVED)

1. **Where does the trailing SL's initial stop get seeded — at bracket declaration or at parent fill?**
   - What we know: D-TRAIL-3 seeds HWM/LWM from the entry fill price; the `PercentFromFill` carve-out already creates fill-anchored children at parent EXECUTED fill (`_create_fill_anchored_children`).
   - What's unclear: Whether the trailing SL is a resting order from declaration (dormant until parent fills, with HWM/LWM seeded when the parent fill is observed in the engine) or created fresh at parent fill (PercentFromFill path).
   - Recommendation: Prefer the fill-anchored path (A2) — it reuses an existing, tested seam and naturally provides the entry fill price for the D-TRAIL-3 seed. Let the planner confirm against the engine's view of the parent fill.
   - **RESOLVED: 05-03 adopts the fill-anchored path (A2).**

2. **How does the validator's positive-`price` assumption coexist with a dynamic trailing stop?**
   - What we know: Both `EnhancedOrderValidator` (order_validator.py:213-220) and `SimulatedExchange.validate_order` (simulated.py:490-491) reject `price <= 0`.
   - What's unclear: The trailing SL has no fixed trigger price at declaration; D-TRAIL-7 validates `trail_value` viability, not a static price.
   - Recommendation: D-TRAIL-7 validation expressed against `trail_value` + reference price; for the resting trailing order, either carry the computed initial stop as `price` (after fill seed) or branch the positive-price check on `order_type == TRAILING_STOP`. Plan must pick one and keep the spot oracle byte-exact (trailing is oracle-dark on the SMA_MACD path).
   - **RESOLVED: 05-01 adopts the positive computed-initial-stop strategy (skip static-price check for TRAILING_STOP, validate trail_value viability instead).**

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | All code | ✓ | 3.13 | — |
| Poetry / `.venv` | Build/test | ✓ | (in-project) | — |
| `backtesting.py` | TRAIL-03 cross-val | ✓ | 0.6.5 | — (gating; no fallback) |
| `backtrader` | TRAIL-03 cross-val | ✓ | 1.9.78.123 | — (gating; no fallback) |
| `pytest` | Unit + e2e | ✓ | 8.4.2 | — |

**Missing dependencies with no fallback:** None — both cross-val oracles are already declared in `pyproject.toml`.
**Missing dependencies with fallback:** None.

> Worktree note (from MEMORY.md): if planning/executing in a worktree, `make test` aborts on missing `.env`; run `poetry run pytest tests` there and re-run `make test` in the main checkout. Also prepend `PYTHONPATH="$PWD"` to avoid the editable-install shadowing worktree edits.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 (+ pytest-cov 7.1.0) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` (testpaths=["tests"], filterwarnings=["error"], strict-markers/strict-config) |
| Quick run command | `poetry run pytest tests/unit/execution/test_matching_engine.py -x` |
| Full suite command | `make test` (or `poetry run pytest tests` in a worktree) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TRAIL-01 | TRAILING_STOP rests + ratchets favorably-only (long) | unit | `poetry run pytest tests/unit/execution/test_matching_engine.py -k "trailing and long" -x` | ❌ Wave 0 |
| TRAIL-01 | TRAILING_STOP rests + ratchets favorably-only (short) | unit | `poetry run pytest tests/unit/execution/test_matching_engine.py -k "trailing and short" -x` | ❌ Wave 0 |
| TRAIL-02 | Ratchet from bar N's extreme active on bar N+1 (never same-bar) | unit | `poetry run pytest tests/unit/execution/test_matching_engine.py -k "trailing and next_bar" -x` | ❌ Wave 0 |
| TRAIL-02 | Gap-through trailing fill at open (D-TRAIL-4, long+short) | unit | `poetry run pytest tests/unit/execution/test_matching_engine.py -k "trailing and gap" -x` | ❌ Wave 0 |
| TRAIL-01/05 | Trailing SL vs TP-limit same-bar OCO priority (D-TRAIL-5) | unit | `poetry run pytest tests/unit/execution/test_matching_engine.py -k "trailing and oco" -x` | ❌ Wave 0 |
| TRAIL-07 | Validator rejects non-viable trail (percent ≥ 1 / abs ≥ price) | unit | `poetry run pytest tests/unit/order/ -k "trailing and reject" -x` | ❌ Wave 0 |
| TRAIL-01 | Bracket declares trailing SL replacing fixed SL (D-TRAIL-5) | unit/integration | `poetry run pytest tests -k "trailing and bracket" -x` | ❌ Wave 0 |
| TRAIL-01/02 | End-to-end trailing scenario (long) through the run path | e2e | `poetry run pytest tests/e2e -k "trailing_long" -x` | ❌ Wave 0 |
| TRAIL-01/02 | End-to-end trailing scenario (short) through the run path | e2e | `poetry run pytest tests/e2e -k "trailing_short" -x` | ❌ Wave 0 |
| TRAIL-03 | Cross-val within-tolerance vs backtesting.py/backtrader | script (evidence, not CI) | `poetry run python scripts/cross_validate_trailing.py` | ❌ Wave 0 |
| (gate) | SMA_MACD spot oracle stays byte-exact (trailing oracle-dark) | golden | `poetry run pytest tests/golden -x` | ✅ exists |
| (gate) | Determinism double-run byte-identical | gate | `poetry run python scripts/run_backtest.py` (×2, diff) | ✅ exists |

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/unit/execution/test_matching_engine.py -x` (+ the specific `-k` selector for the task)
- **Per wave merge:** `make test` (full suite; worktree: `poetry run pytest tests`)
- **Phase gate:** Full suite green + golden byte-exact + determinism double-run + owner-gated cross-val sign-off before re-baseline (this phase has its OWN result-changing re-baseline, separate from the accounting core)

### Wave 0 Gaps
- [ ] `tests/unit/execution/test_matching_engine_trailing.py` (or trailing cases added to `test_matching_engine.py`) — TRAIL-01/02, long AND short, ratchet/next-bar/gap/OCO
- [ ] `tests/unit/order/test_trailing_validation.py` — D-TRAIL-7 non-viable-trail rejection
- [ ] `tests/e2e/trailing_long/` + `tests/e2e/trailing_short/` — e2e leaves (follow the `tests/e2e/sltp/` + `tests/e2e/short_roundtrip/` structure; use `scenario_spec.py`)
- [ ] `scripts/cross_validate_trailing.py` + `scripts/crossval/trailing_run.py` (+ backtesting.py/backtrader trailing runners) — sibling of `cross_validate_accounting.py`, reuse `scripts/crossval/reconcile.py` verbatim
- [ ] Bar-factory fixtures: existing `make_bar` in `tests/conftest.py` (Decimal `dict[str, Bar]` payload) covers the trailing unit tests — no new fixture needed
- Framework install: none — pytest + both oracles already present

## Cross-Validation Architecture (TRAIL-03)

**Existing harness (read this session):**
- Orchestrators: `scripts/cross_validate.py` (SMA_MACD MARKET), `scripts/cross_validate_limit.py` (v1.3 LIMIT precedent), `scripts/cross_validate_accounting.py` (XVAL-01 short/levered/liq). The trailing orchestrator should be a STANDALONE SIBLING (do not modify the base) — `scripts/cross_validate_trailing.py`.
- Reusable helpers: `scripts/crossval/reconcile.py` — `align_trades` / `build_metric_table` / `recompute_headline` / `flag_divergences` (reused verbatim by both existing sibling orchestrators).
- Per-engine runners: `scripts/crossval/{backtesting_py_run,backtrader_run,short_run,levered_run,liquidation_run}.py` — add `trailing_run.py` (iTrader white-box) + backtesting.py/backtrader trailing runners.
- Evidence artifacts: `tests/golden/CROSS-VALIDATION*.md` — add `CROSS-VALIDATION-TRAILING.md` (evidence, NOT the oracle; NOT wired into `make test`/CI; the e2e leaves are the regression lock).

**Tolerance approach (verified from existing reports):** trade-level reconciliation (entry/exit date alignment) is the PRIMARY gate; metric-level reconciliation is SECONDARY at a **1% relative tolerance** (`TOLERANCE = 0.01` in `cross_validate_accounting.py`). Divergences are dispositioned (LEGITIMATE-DIFFERENCE vs BUG); iTrader is kept unless the trace proves a defect. Use **synthetic tickers** (e.g. `TRAILUSD`) NEVER BTCUSD, so the spot oracle stays byte-exact (the accounting cross-val used `SHORTUSD`/`LEVUSD`/`LIQUSD`).

**Known systematic gap to document (from the phase brief, A1):** both oracles trail off the CLOSE and activate next bar; D-TRAIL-1 trails off the closed-bar HIGH (long) / LOW (short). So iTrader's stop is marginally tighter → it may exit slightly earlier on some trades. The cross-val is WITHIN-TOLERANCE (trade-timing may SHIFT by a bar on borderline trades; metric within 1%), **NOT byte-match**. Craft the scenario so the trail distance is large relative to intrabar range on most bars (minimizes the high-vs-close divergence) and document the residual as a LEGITIMATE-DIFFERENCE with the high-vs-close root cause — exactly the disposition style the accounting/SMA_MACD reports use.

**Owner-gated re-baseline:** This phase is result-changing (new resting-order subsystem behavior) and has its OWN golden re-baseline, separate from the Phase 4 accounting core. The freeze happens ONLY after explicit owner sign-off + the cross-val evidence (mirror the `## Owner Sign-Off` block in `CROSS-VALIDATION-ACCOUNTING.md`). `mypy --strict` clean + determinism double-run byte-identical must hold.

**Test-surfacing note (long AND short):** Shorts were only added in Phase 3. Long trailing-stop tests do NOT cover the short buy-stop ratchet (`stop = LWM + trail`, non-increasing). Both directions need explicit unit + e2e + cross-val coverage — this is called out in the locked Claude's-discretion note and the Wave 0 gaps.

## Per-File Indentation Map (Pitfall 5)

| File | Indentation | Touched for |
|------|-------------|-------------|
| `itrader/execution_handler/matching_engine.py` | **4-SPACE** (verified) | ratchet step, `_evaluate` TRAILING_STOP arm, `_fill_reason`, side-table |
| `itrader/execution_handler/exchanges/simulated.py` | **4-SPACE** (verified) | `_emit_fill` is_maker/slippage gating, `validate_order` price branch |
| `itrader/core/enums/order.py` | **TAB (verified)** | `OrderType.TRAILING_STOP` + `order_type_map` |
| `itrader/events_handler/events/order.py` | **4-SPACE** (verified) | `trail_type`/`trail_value` fields + `new_order_event` read-back |
| `itrader/config/order.py` or `config/exchange.py` | **4-SPACE** (config is spaces) | `TrailType` enum |
| `itrader/config/__init__.py` | **4-SPACE** | re-export `TrailType` |
| `itrader/order_handler/order.py` | **TAB** (verified) | `trail_type`/`trail_value` entity fields + `new_trailing_stop_order` factory |
| `itrader/order_handler/brackets/bracket_manager.py` | **TAB** (verified) | trailing-SL declaration replacing fixed SL |
| `itrader/order_handler/order_validator.py` | **TAB** (verified) | D-TRAIL-7 non-viable-trail rejection |
| `itrader/order_handler/reconcile/reconcile_manager.py` | **TAB** (verified) | mirror reconcile (likely unchanged — trailing child reconciles like any STOP child) |

## Project Constraints (from CLAUDE.md)

- **Queue-only cross-domain communication.** Trailing ratchet/trigger is execution-layer; the order handler declares brackets and reconciles from FillEvents — it NEVER matches.
- **Money is Decimal end-to-end.** `to_money` for entry, `quantize(value, instrument, "price")` ONLY at the stop-level boundary (D-TRAIL-8). NEVER `Decimal(float)`.
- **Single UUIDv7 ID scheme** via `idgen` — no second scheme; trailing child orders get ids via `Order(...)` default_factory.
- **Determinism:** trailing is a pure function of the bar sequence (D-TRAIL-6); no per-call RNG; double-run byte-identical must hold.
- **Tabs vs 4-space:** match the file (see the per-file map above; never normalize).
- **`filterwarnings=["error"]`, `--strict-markers`, `--strict-config`:** only `unit`/`integration`/`slow`/`e2e` markers; cross-val oracle imports stay SCRIPT-ONLY under `scripts/crossval/`, never under `tests/`.
- **`mypy --strict`** over `itrader` is the only static gate — handle `TRAILING_STOP` in every `OrderType` switch/`assert_never`.
- **Config-enum exception:** `TrailType` lives in `config/`, not `core/enums/` (CONVENTIONS.md, would invert core→config dependency).
- **GSD workflow enforcement:** all edits go through a GSD command (this is planning research, not edits).

## Sources

### Primary (HIGH confidence — read this session)
- `itrader/execution_handler/matching_engine.py` — resting book `_resting`, `_evaluate` (STOP/LIMIT/MARKET branches), `on_bar` two-pass, `_pick_bracket_winner`, `modify` (replace-in-book), `_fill_reason`
- `itrader/execution_handler/exchanges/simulated.py` — `on_market_data` → `MatchingEngine.on_bar`, `_emit_fill` (is_maker/slippage gating), `on_order`, `validate_order`, `_admit_order`
- `itrader/core/enums/order.py` — `OrderType`, `order_type_map`, `VALID_ORDER_TRANSITIONS`, `OrderTriggerSource`
- `itrader/events_handler/events/order.py` — `OrderEvent` frozen fields (`stop_price`/`leverage` precedent), `new_order_event`
- `itrader/events_handler/events/signal.py` — `SignalEvent` fields (`sltp_policy`/`leverage` carriage precedent)
- `itrader/order_handler/order.py` — `Order` entity, `new_stop_order`/`new_limit_order` factories, `child_order_ids`/`parent_order_id`
- `itrader/order_handler/order_manager.py` — coordinator wiring, `process_signal`/`on_fill` delegation
- `itrader/order_handler/brackets/bracket_manager.py` — `_assemble_bracket_and_emit`, `_create_fill_anchored_children`, `_brackets.arm`
- `itrader/order_handler/brackets/levels.py` — `_bracket_levels` ± pct math
- `itrader/order_handler/order_validator.py` — `EnhancedOrderValidator` phases, positive-price/quantity checks (D-TRAIL-7 home)
- `itrader/order_handler/reconcile/reconcile_manager.py` — `on_fill` reconcile, `_classify` FillStatus→OrderStatus map
- `itrader/price_handler/feed/bar_feed.py` — the seven-rule bar-timing contract (rules 2/3/5 govern D-TRAIL-2)
- `itrader/core/money.py` — `to_money`, `quantize(value, instrument, kind)`
- `itrader/core/sizing.py` — `SLTPPolicy`/`PercentFromFill`/`PercentFromDecision`, `SizingPolicy`
- `itrader/config/exchange.py` + `config/__init__.py` — config-enum (`str, Enum`) pattern + re-export
- `tests/golden/CROSS-VALIDATION.md`, `CROSS-VALIDATION-ACCOUNTING.md` — tolerance (1%), trade-level-primary/metric-secondary, divergence disposition style, owner-sign-off block
- `tests/unit/execution/test_matching_engine.py` — unit test shape, `make_order_event` helper, `make_bar` fixture usage
- `scripts/cross_validate_accounting.py`, `scripts/crossval/` listing — sibling-orchestrator + reusable reconcile-helper pattern
- `.planning/REQUIREMENTS.md`, `ROADMAP.md` (Phase 5), `05-CONTEXT.md` — requirements, success criteria, locked decisions
- `pyproject.toml` (grep) — `backtesting = "0.6.5"`, `backtrader = "1.9.78.123"` present
- `.planning/config.json` (grep) — `workflow.nyquist_validation: true`

### Secondary (MEDIUM confidence)
- `.planning/codebase/CONVENTIONS.md` (grep) — config-enum exception, tab/space hazard

### Tertiary (LOW confidence — flagged in Assumptions Log)
- backtesting.py `TrailingStrategy` / backtrader `StopTrail` exact API + "trail off close, activate next bar" behavior (A1 — supplied by the phase brief, not re-verified against installed versions this session; verify in the cross-val runner during implementation)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; all primitives read in-repo this session
- Architecture (seams, ratchet ordering, frozen-event constraint, bracket declaration): HIGH — every claim cites a file/line read this session
- Pitfalls: HIGH — derived from the actual strict-test/mypy/indentation/frozen-event facts in the code
- Cross-validation oracle API specifics: MEDIUM-LOW — harness structure + tolerance verified HIGH; the oracle trailing-API/behavior is ASSUMED (A1) pending runner-time verification

**Research date:** 2026-06-17
**Valid until:** 2026-07-17 (stable brownfield engine; the only fast-moving element is the oracle API, verify at implementation time)
