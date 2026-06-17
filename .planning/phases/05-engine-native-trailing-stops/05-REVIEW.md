---
phase: 05-engine-native-trailing-stops
reviewed: 2026-06-17T00:00:00Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - itrader/config/__init__.py
  - itrader/config/order.py
  - itrader/core/enums/order.py
  - itrader/core/sizing.py
  - itrader/events_handler/events/order.py
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/execution_handler/fee_model/base.py
  - itrader/execution_handler/matching_engine.py
  - itrader/execution_handler/slippage_model/base.py
  - itrader/order_handler/brackets/bracket_book.py
  - itrader/order_handler/brackets/bracket_manager.py
  - itrader/order_handler/order_validator.py
  - itrader/order_handler/order.py
  - scripts/cross_validate_trailing.py
  - scripts/crossval/backtesting_py_trailing_run.py
  - scripts/crossval/backtrader_trailing_run.py
  - scripts/crossval/trailing_run.py
findings:
  critical: 1
  warning: 4
  info: 4
  total: 9
status: issues_found
---

# Phase 5: Code Review Report

**Reviewed:** 2026-06-17
**Depth:** standard
**Files Reviewed:** 18 (one listed source path, `scripts/crossval/trailing_run.py`, appears once but two oracle runners cross-reference it; 17 distinct review targets + the orchestrator)
**Status:** issues_found

## Summary

The MatchingEngine ratchet subsystem is well-built and the core look-ahead invariant is
correct: I traced the seed/evaluate/ratchet ordering and the documented `100.8` trigger
reproduces exactly (HWM 112 × 0.90, derived from bar N-1, live on bar N). The
end-of-`on_bar` ratchet step runs after both fill passes and OCO cancels, so a "tall bar"
cannot ratchet-and-trigger in the same bar. The `_trails` side-table is popped at every
`_resting.pop` site (book management, both fill passes, OCO cancels), so no ratchet state
leaks for a filled/cancelled order. Decimal discipline is clean (HWM/LWM full precision,
only `current_stop` quantized, and the quantize path is dormant because no resolver is
wired). Indentation matches conventions on every file (no mixed-indentation breakage).
Reference-engine imports stay script-only — `tests/` carries no `backtesting`/`backtrader`
import, only a doc reference inside the committed evidence markdown.

The one serious defect is a **safety gap on the ONLY path that actually creates trailing
stops**: the fill-anchored bracket child bypasses the D-TRAIL-7 viability validator, so a
`PercentFromFill` declaring a non-viable trail (PERCENT `trail_value >= 1`, or PRICE
`trail_value >= entry fill`) silently rests an SL whose computed stop is negative — a stop
that can NEVER trigger, leaving the position unprotected with no rejection event. The
planning artifacts (05-RESEARCH.md:291, 05-01-SUMMARY) explicitly expected D-TRAIL-7 to
guard exactly this case; the implementation routes the real trailing path around it.

## Critical Issues

### CR-01: Fill-anchored trailing SL child bypasses the D-TRAIL-7 viability gate — non-viable trail rests an unprotected position

**File:** `itrader/order_handler/brackets/bracket_manager.py:254-276` (child creation), `itrader/core/sizing.py:245-256` (policy validation), `itrader/order_handler/order_validator.py:249-272` (the gate that is never reached)

**Issue:**
The only path that creates an engine-native trailing stop in practice is the
`PercentFromFill` carve-out: `_create_fill_anchored_children` builds the trailing SL child
at parent-fill time and the handler emits it straight as an `OrderEvent` to the exchange.
That path NEVER calls `EnhancedOrderValidator.validate_order_pipeline` — only the *primary*
(MARKET) order is validated at admission (`admission_manager.py:233`). The D-TRAIL-7
viability checks in `order_validator.py:259-272` (PERCENT `trail_value < 1`; PRICE
`trail_value < reference price`) are therefore dead for every trailing SL created via the
carve-out.

`PercentFromFill.__post_init__` (`sizing.py:245-256`) only enforces `trail_value > 0` — it
imposes **no upper bound** on a PERCENT trail. So `PercentFromFill(sl_pct=..., tp_pct=...,
trail_type=TrailType.PERCENT, trail_value=Decimal("1.5"))` constructs successfully.

At fill, `_create_fill_anchored_children` sets the child's `price = anchor` (the positive
entry fill, e.g. 100) and passes `trail_value=1.5`. The child's `order.price` is positive,
so BOTH the exchange `validate_order` (`simulated.py:497`) and the entity positive-price
gate pass — the order is **admitted and rests**. Inside the engine,
`_seed_trail` → `_compute_stop` produces `current_stop = anchor * (1 - 1.5) = -50`. A long
sell-stop fires only when `low <= current_stop`, i.e. `low <= -50` — which never happens.
The position is silently left with a resting SL that can never trigger and never
reconciles. (The PRICE analog: `trail_value >= anchor` → negative `current_stop`, same
unprotected-rest outcome.) This is worse than a rejection: there is no `FillEvent(REFUSED)`,
no audit trail, and the SMA_MACD spot oracle being byte-exact hides it entirely.

Confirmed numerically: anchor 100, PERCENT trail 1.5 → initial `current_stop = -50.0`,
order.price stays 100 (admitted).

**Fix:** Validate the trailing child's trail viability before it is emitted — either run
the trail-viability portion of D-TRAIL-7 inside `_create_fill_anchored_children` against
the resolved anchor, or (cleaner) bound the PERCENT trail at policy construction so a
non-viable trail cannot be declared:
```python
# itrader/core/sizing.py — PercentFromFill.__post_init__
if self.trail_value is not None:
    _require_positive("PercentFromFill", "trail_value", self.trail_value)
    if self.trail_type == TrailType.PERCENT and self.trail_value >= ONE:
        raise SizingPolicyViolation(
            f"PercentFromFill.trail_value must be < 1 for a PERCENT trail: "
            f"got {self.trail_value!r}"
        )
```
The PRICE case (`trail_value >= anchor`) is only knowable at fill, so additionally gate it
in `_create_fill_anchored_children` and reject the bracket (emit REFUSED for the child)
rather than resting a dead stop:
```python
# bracket_manager._create_fill_anchored_children, before building sl_order
if pending.trail_type == TrailType.PRICE and pending.trail_value >= anchor:
    # reject: a non-viable absolute trail would seed a non-positive stop
    raise SizingPolicyViolation(...)  # or route to an audited REFUSED path
```
(Importing `TrailType` at runtime here is fine — `bracket_manager.py` already participates
in the order domain; or compare via the policy's `is_trailing`/a helper.)

## Warnings

### WR-01: MODIFY on a resting trailing stop leaves the ratchet side-table stale

**File:** `itrader/execution_handler/matching_engine.py:147-171` (`modify`), `itrader/execution_handler/exchanges/simulated.py:371-374`

**Issue:**
`matching_engine.modify` replaces the resting `OrderEvent` via `dataclasses.replace` but
does NOT touch the parallel `_trails[order_id]` TrailState. For a `TRAILING_STOP`, the
TrailState carries `hwm`/`lwm`/`current_stop` seeded from the ORIGINAL `order.price`. After
a MODIFY changes `price` (and `replace` preserves `trail_type`/`trail_value`), the engine
keeps triggering against the stale `current_stop`/`hwm` — the modified price has no effect
on the dynamic trigger, and a quantity change is the only thing that lands. There is a live
MODIFY path (`lifecycle_manager.py:126` → `OrderCommand.MODIFY` → `simulated.py:373`), so
this is reachable if any lifecycle code ever modifies a trailing order.

**Fix:** In `modify`, when the resting order is a `TRAILING_STOP`, re-seed (or explicitly
reject the modify): after the `replace`, call `self._trails[order_id] =
self._seed_trail(updated_order)` so the ratchet restarts from the new reference, or raise
on a price-modify of a trailing order to make the no-op explicit.

### WR-02: PercentFromFill policy permits PERCENT trail >= 1 (no upper-bound guard)

**File:** `itrader/core/sizing.py:245-256`

**Issue:**
`PercentFromFill.__post_init__` validates the trail descriptor as all-or-nothing and
`trail_value > 0`, but never bounds a PERCENT trail to `(0, 1)`. The validator
(`order_validator.py:259`) and both oracle runners assume a fraction `< 1`. This is the
root enabler of CR-01 and is also independently wrong: a PERCENT fraction `>= 1` is
semantically meaningless (it places the stop at or below zero). Even if CR-01's
fill-path validation is added, the policy should fail loud at construction — the same
fail-loud contract every other sizing field follows (D-06).

**Fix:** Add the `(0, 1)` upper bound for PERCENT in `__post_init__` (see CR-01 snippet).
PRICE trails legitimately have no fixed upper bound at construction (the anchor is unknown),
so bound only the PERCENT case here.

### WR-03: `_quantize_stop` Instrument-resolver path is never wired — quantization claim is unverifiable in the run path

**File:** `itrader/execution_handler/matching_engine.py:107-122, 227-239`; `itrader/execution_handler/exchanges/simulated.py:78`

**Issue:**
`MatchingEngine.__init__` accepts an `instrument_resolver`, but the only construction site
(`simulated.py:78`) is `MatchingEngine()` with no resolver. So `_instrument_resolver` is
always `None`, `_quantize_stop` always returns `raw` unquantized, and the D-TRAIL-8
"quantize the computed stop to the symbol's price scale" behavior is dead on every real
run. The docstrings present quantization as an active feature; in practice trailing stops
trigger and fill at full-precision unquantized levels. This is defensible (matches D-14
never-round-prices), but the gap between the documented capability and the wired reality is
a maintenance trap — a reader will assume stops are scale-aligned when they are not, and
the resolver branch (lines 234-239) is untested-by-construction dead code.

**Fix:** Either wire the resolver from the exchange's injected `Universe`
(`self._universe.instrument`) so the documented behavior is real, or drop the resolver
parameter and `_quantize_stop` and state plainly that trailing stops carry full precision
like every other matching price. Do not leave a documented-but-dead capability.

### WR-04: Trailing child trail viability is split across two layers that disagree on coverage

**File:** `itrader/order_handler/order_validator.py:249-272`, `itrader/execution_handler/exchanges/simulated.py:489-500`

**Issue:**
The dual-layer validator overlap (CONVENTIONS.md D-03a) is documented as defense-in-depth,
but for trailing orders the two layers check DIFFERENT things and neither covers the real
path. `EnhancedOrderValidator` checks trail viability (PERCENT<1, PRICE<reference) but is
skipped for fill-anchored children (CR-01). The exchange `validate_order` checks only
`event.price <= 0` and has NO trail-awareness at all — its comment (lines 489-496) asserts
"the disposition matches the domain validator," which is FALSE for a non-viable trail: the
domain validator would reject, the exchange admits. The defense-in-depth claim does not
hold for the trailing case.

**Fix:** Once CR-01 is fixed at the policy/fill boundary, update the `simulated.py:489-496`
comment to stop claiming agreement, or add a trail-awareness check to the exchange layer so
the documented dual-layer agreement is actually true for trailing orders.

## Info

### IN-01: `get_config_dict` leaks raw Decimal/None for fee/slippage rates while the rest of the method uses `float()`

**File:** `itrader/execution_handler/exchanges/simulated.py:778-783`

**Issue:** `get_config_dict` calls `float(...)` for `failure_rate`, `min_order_size`,
`max_order_size` (the serialization edge) but returns `fee_rate`/`maker_rate`/`taker_rate`/
`base_slippage_pct`/`slippage_pct` as raw `Decimal` (or `None`). Inconsistent
serialization shape for a "config dict" that callers may JSON-encode. Not money-policy
wrong (these are rates, and keeping Decimal is arguably safer), but the within-method
inconsistency is a smell.

**Fix:** Pick one convention for this dict and apply it uniformly; if it is a
serialization boundary, coerce the rate fields the same way as the size fields.

### IN-02: `OrderType._missing_` / mapping carries TRAILING_STOP but the string-map `order_type_map` is now redundant

**File:** `itrader/core/enums/order.py:63-68`

**Issue:** `order_type_map` duplicates what `OrderType(value)` (via `_missing_`) already
does case-insensitively. Adding `TRAILING_STOP` to the map keeps it in sync, but the map
itself is dead weight now that the enum parses strings. Low priority — flagged for cleanup
debt, not correctness.

**Fix:** Confirm no remaining callers of `order_type_map`; if none, remove it (and the
sibling `order_status_map`/`order_command_map`) in a cleanup pass.

### IN-03: TP-limit `tp_pct=Decimal("5")` in the cross-val runner is a 500% offset masquerading as a fraction

**File:** `scripts/crossval/trailing_run.py:100-105`

**Issue:** `PercentFromFill(tp_pct=Decimal("5"), ...)` is intended to push the TP far above
the path so the trailing SL is the exit. `_require_positive` accepts it, but `tp_pct` is
documented as "a fraction of fill price" — `5` is 500%, which is fine for this scenario
only because the path never reaches it. It reads as a likely typo (5 vs 0.5) to a future
maintainer and would be a real bug if copied into a scenario where the TP matters.

**Fix:** Add an inline comment that `5` is a deliberate "unreachable TP" sentinel (500% of
fill), or use a value that is unambiguously out-of-path with a clarifying comment.

### IN-04: `_validate_market_hours` indexes `market_hours[exchange]` for NYSE/NASDAQ but the dict comparison mixes `datetime.time` — verify tz

**File:** `itrader/order_handler/order_validator.py:339-349`

**Issue:** `order.time.time()` strips tz and compares against naive `time(9,30)` bounds.
For the crypto/csv backtest path `exchange in ["NYSE","NASDAQ"]` is never true, so this is
oracle-dark, but the naive-time comparison is a latent correctness issue for any future
real-exchange wiring (a UTC-stamped order time compared against exchange-local market
hours). Not in this phase's behavior, flagged as pre-existing debt touched by the reviewed
file.

**Fix:** When market-hours validation is activated for real exchanges, convert
`order.time` to the exchange's local tz before extracting `.time()`.

---

_Reviewed: 2026-06-17_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
