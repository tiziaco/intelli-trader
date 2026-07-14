---
phase: 07-safety-reconciliation-stream-recovery
plan: 05
subsystem: infra
tags: [safety, throttle, rate-limit, notional-cap, live-trading, determinism, decimal]

# Dependency graph
requires:
  - phase: 07-01
    provides: ThrottleSettings/SafetySettings + config.safety.throttle (static caps, ON by default)
  - phase: 07-03
    provides: shared classify(event)->OrderRiskRole predicate + OrderRiskRole enum (D-05/D-16)
provides:
  - PreTradeThrottle — operator pre-trade risk backstop (SAFE-06)
  - ENTRY-only sliding-window rate cap (D-04) off the injected clock
  - Per-order Decimal max-notional cap (D-10)
  - Breach egress — FillEvent(REFUSED) (D-02) + read-model breach_count + de-duped WARNING ErrorEvent (D-09)
affects: [07-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Shared-classifier reuse — throttle imports the SINGLE classify() so it physically cannot reject CANCEL/PROTECTIVE (D-05)"
    - "Injected-clock sliding window (deque of timestamps, prune-left) — deterministic, no wall clock (D-04)"
    - "Min-interval dedup off the injected clock so a breach burst cannot flood the ERROR route (D-09)"

key-files:
  created:
    - itrader/trading_system/safety/pre_trade_throttle.py
    - tests/unit/trading_system/test_pre_trade_throttle.py
  modified: []

key-decisions:
  - "D-10 notional computed off OrderEvent.price (limit for LIMIT; decision-bar-close mark estimate for MARKET/STOP) — no separate feed injection, since the order layer already stamps the mark"
  - "Public gate named allow(event)->bool (True=submit, False=rejected); REFUSED fill emitted internally on breach"
  - "breach_count exposed via a thin read-only property accessor for the P9 stats/state UI"

patterns-established:
  - "PreTradeThrottle: a plain injected collaborator (settings/clock/bus + bound logger), no facade back-reference, never barrel-exported (inertness-safe)"

requirements-completed: [SAFE-06]

coverage:
  - id: D1
    description: "PreTradeThrottle rejects the 11th ENTRY inside the 10s sliding window with FillEvent(REFUSED), not recording the rejected order (D-04 rate cap)"
    requirement: "SAFE-06"
    verification:
      - kind: unit
        ref: "tests/unit/trading_system/test_pre_trade_throttle.py#test_eleventh_entry_in_window_is_refused"
        status: pass
    human_judgment: false
  - id: D2
    description: "The sliding window prunes-left off the injected clock — an ENTRY is allowed again once the window elapses (determinism seam, never wall clock)"
    requirement: "SAFE-06"
    verification:
      - kind: unit
        ref: "tests/unit/trading_system/test_pre_trade_throttle.py#test_window_prunes_left_off_injected_clock"
        status: pass
    human_judgment: false
  - id: D3
    description: "An ENTRY whose Decimal notional exceeds $25k is REFUSED (D-10 max-notional, Decimal end-to-end)"
    requirement: "SAFE-06"
    verification:
      - kind: unit
        ref: "tests/unit/trading_system/test_pre_trade_throttle.py#test_entry_over_max_notional_is_refused"
        status: pass
    human_judgment: false
  - id: D4
    description: "CANCEL and PROTECTIVE (parent_order_id set) orders ALWAYS pass and are NEVER counted toward the window — even over the rate cap and over the notional cap (D-05 shared-classifier bypass)"
    requirement: "SAFE-06"
    verification:
      - kind: unit
        ref: "tests/unit/trading_system/test_pre_trade_throttle.py#test_cancel_and_protective_bypass_uncounted_even_over_cap"
        status: pass
    human_judgment: false
  - id: D5
    description: "On breach the read-model breach_count increments and the WARNING ErrorEvent is de-duped off the injected clock (a 5-breach burst emits exactly 1 WARNING; a later breach past the interval emits a 2nd) (D-09)"
    requirement: "SAFE-06"
    verification:
      - kind: unit
        ref: "tests/unit/trading_system/test_pre_trade_throttle.py#test_breach_warning_is_deduped_off_injected_clock"
        status: pass
    human_judgment: false
  - id: D6
    description: "Backtest oracle stays byte-exact (134 / 46189.87730727451) and OKX import inertness stays green (throttle not barrel-exported)"
    verification:
      - kind: integration
        ref: "tests/integration/test_backtest_oracle.py"
        status: pass
      - kind: integration
        ref: "tests/integration/test_okx_inertness.py"
        status: pass
    human_judgment: false

# Metrics
duration: 20min
completed: 2026-07-14
status: complete
---

# Phase 7 Plan 5: PreTradeThrottle Summary

**Net-new operator pre-trade risk backstop (SAFE-06) — ENTRY-only sliding-window submit-rate + per-order Decimal max-notional caps that reject over-cap orders via FillEvent(REFUSED) before submission, reusing the shared classify() so CANCEL/PROTECTIVE bypass uncounted.**

## Performance

- **Duration:** ~20 min
- **Tasks:** 1
- **Files modified:** 2 (both created)

## Accomplishments
- `PreTradeThrottle` — a plain injected collaborator (injected `ThrottleSettings`, injected clock, injected bus, bound logger; no facade back-reference) authored at `itrader/trading_system/safety/pre_trade_throttle.py` (4 spaces).
- Meters **ENTRY only**: `allow(event)` reuses the SINGLE shared `classify` from `safety_controller` — CANCEL and PROTECTIVE (bracket-child) orders return `True` immediately, uncounted, so the throttle physically cannot reject a stop/bracket-child/cancel (D-05/D-16).
- D-04 sliding-window rate cap: a `deque` of ENTRY submit timestamps pruned-left off the **injected clock** (never wall clock); breach when `len(stamps) >= max_orders`. A rejected order consumes no slot.
- D-10 max-notional cap: `abs(price * quantity)` in **Decimal** end-to-end (no float on the notional path); the reference price is `OrderEvent.price` (limit for LIMIT, decision-bar-close mark estimate for MARKET/STOP).
- D-02 breach egress: `FillEvent.new_fill('REFUSED', order, ...)` on the bus — the same path `EnhancedOrderValidator` uses, so the mirror reconciles REFUSED->REJECTED; order flow continues (not a pause/halt).
- D-09 observability: a read-model `breach_count` (thin property accessor for P9) plus a WARNING-severity `ErrorEvent` de-duped by `warn_min_interval_s` off the injected clock — a runaway burst cannot flood the ERROR route. Only declared ErrorEvent fields + a fixed message are bound (V7 secret-scrub).

## Task Commits

1. **Task 1: PreTradeThrottle — sliding-window rate + max-notional, ENTRY-only metering (SAFE-06)** - `9c68aecd` (feat)

**Plan metadata:** committed with this SUMMARY.

## Files Created/Modified
- `itrader/trading_system/safety/pre_trade_throttle.py` - The `PreTradeThrottle` risk backstop (net-new).
- `tests/unit/trading_system/test_pre_trade_throttle.py` - 5 unit tests (fake clock + fake bus): rate breach, window prune, notional breach, CANCEL/PROTECTIVE bypass, WARNING dedup.

## Decisions Made
- **D-10 notional off `OrderEvent.price`, no feed injection.** The order layer already stamps the D-10 reference (limit price for LIMIT; the decision-bar-close mark estimate for MARKET/STOP) onto `OrderEvent.price`, so a separate feed dependency would add untested surface for no correctness gain. `_exceeds_notional` reads `price`/`quantity` defensively (skips the notional check if absent — the rate cap still applies).
- **Public gate `allow(event) -> bool`** (True=submit, False=rejected), emitting the REFUSED fill internally on breach — matches the runner pre-submit callable seam (D-06/A3).
- **`breach_count` exposed via a read-only `@property`** — the thin P9 read-model accessor (D-09).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- The literal acceptance grep `grep -c 'float(' ...` must return 0, but two docstring lines referenced `` ``float()`` `` as prose (tripping the grep). Reworded to `` ``float`` coercion`` — preserves meaning, grep now returns 0. Not a behavior change.
- `mypy --strict` flagged `_exceeds_notional` returning `Any` (price/quantity come via `getattr`); wrapped the comparison in `bool(...)`. Clean.

## Next Phase Readiness
- `PreTradeThrottle` is authored and unit-verified but **unwired** — Plan 07-06 constructs it in `build_live_system` and invokes it at the pre-submit (ORDER->execution) boundary ahead of the dispatch gate (D-06), and surfaces `breach_count` through the facade `get_status()` read-model.
- Both per-phase gates green: backtest oracle byte-exact (134 / 46189.87730727451); OKX import inertness green (throttle not barrel-exported).

## Self-Check: PASSED
- `itrader/trading_system/safety/pre_trade_throttle.py` — FOUND
- `tests/unit/trading_system/test_pre_trade_throttle.py` — FOUND
- Commit `9c68aecd` — FOUND
- `tests/unit/trading_system` — 59 passed; `mypy --strict` clean on the new file; oracle + inertness green.

---
*Phase: 07-safety-reconciliation-stream-recovery*
*Completed: 2026-07-14*
