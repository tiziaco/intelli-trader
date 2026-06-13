---
phase: 05-signal-contract-reconcile-fragile
plan: 01
subsystem: strategy
tags: [signal-contract, order-type, limit-order, stop-order, signal-intent, decimal-money]

# Dependency graph
requires:
  - phase: 04-composition-and-config
    provides: per-instance Strategy.order_type class attr + buy()/sell() sugar (now generalized per-intent)
provides:
  - SignalIntent.order_type (required OrderType) + entry_price (Decimal | None) fields
  - buy_limit/buy_stop/sell_limit/sell_stop strategy-base factories with required keyword-only price
  - retirement of the per-instance Strategy.order_type class attr (per-intent order type instead)
  - StrategiesHandler per-intent fan-out (reads intent.order_type / intent.entry_price)
  - SignalRecord.order_type / entry_price oracle-dark audit fields
affects: [05-02, 05-03, 05-04, margin-shorts-trailing-N+2, live-readiness-N+4]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Per-intent order-type authoring: each buy/sell call states its own OrderType; no strategy-wide default"
    - "Make-illegal-states-unrepresentable: typed limit/stop factories require keyword-only price; buy()/sell() omit it (D-01/D-04)"
    - "Byte-exact MARKET canary: fan-out gates on intent.order_type, MARKET keeps to_money(bar.close)"

key-files:
  created:
    - tests/unit/strategy/test_signal_factories.py
  modified:
    - itrader/core/sizing.py
    - itrader/strategy_handler/base.py
    - itrader/strategy_handler/signal_record.py
    - itrader/strategy_handler/strategies_handler.py
    - tests/e2e/strategies/scripted_emitter.py
    - tests/unit/core/test_sizing.py

key-decisions:
  - "D-01: SignalIntent.order_type is required (never None); MARKET for plain buy()/sell(), LIMIT/STOP for typed factories"
  - "D-01: typed factories take a required keyword-only price; illegal (order_type, price) combos are unrepresentable"
  - "D-01: retired the per-instance Strategy.order_type class attr + its _COERCE entry + to_dict() order_type key"
  - "D-02: SignalRecord gains order_type/entry_price as oracle-dark audit fields"
  - "Behavior-preserving: ScriptedEmitter routes LIMIT/STOP through the typed factories at the decision-bar close to keep every e2e golden byte-exact"

patterns-established:
  - "Shared private _intent() helper folds sl/tp/exit_fraction/entry_price across all 6 buy/sell methods"
  - "Money enters the Decimal domain only via to_money(price); never Decimal(float)"

requirements-completed: [SIG-01, SIG-02]

# Metrics
duration: ~35min
completed: 2026-06-13
---

# Phase 5 Plan 01: Signal Authoring Surface (per-intent order_type + entry price) Summary

**Strategy authors can now call buy_limit/buy_stop/sell_limit/sell_stop with a required entry price to emit LIMIT/STOP SignalIntents, while plain buy()/sell() stay MARKET byte-exact and the per-instance Strategy.order_type attr is retired in favour of per-intent order type.**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-06-13
- **Completed:** 2026-06-13
- **Tasks:** 3
- **Files modified:** 6 (1 created, 5 modified)

## Accomplishments
- Added required `order_type: OrderType` + `entry_price: Decimal | None` to `SignalIntent` and oracle-dark audit equivalents to `SignalRecord` (D-01/D-02).
- Added four typed factories (`buy_limit`/`buy_stop`/`sell_limit`/`sell_stop`) with a required keyword-only `price`, sharing a private `_intent()` helper; `buy()`/`sell()` stay MARKET byte-exact with no new params.
- Retired the per-instance `Strategy.order_type` class attr, its `_COERCE` enum entry, and the `to_dict()` `order_type` key (D-01 blast radius).
- Rewired `StrategiesHandler.calculate_signals` to read `intent.order_type`/`intent.entry_price` per intent; MARKET keeps `to_money(bar.close)` (the byte-exact canary), LIMIT/STOP use the declared entry price.
- Existing oracle stayed byte-identical (134 trades / final_equity 46189.87730727451); e2e 58/58; 906 unit+integration green; mypy --strict clean over all 160 source files.

## Task Commits

Each task was committed atomically:

1. **Task 1: order_type/entry_price on SignalIntent + SignalRecord** - `b8bd261` (feat)
2. **Task 2: typed buy/sell limit/stop factories; retire order_type attr** - `eda2cf7` (feat, incl. new factory unit test)
3. **Task 3: per-intent handler fan-out + SignalRecord capture** - `7c648f9` (feat)

_TDD tasks: implementation + factory test landed in the same task commit; the integration oracle and e2e suites served as the regression gate._

## Files Created/Modified
- `itrader/core/sizing.py` - SignalIntent gains required `order_type` + `entry_price` fields; removed the line-243 TODO marker; `OrderType` added to the enum import.
- `itrader/strategy_handler/base.py` - four typed factories + shared `_intent()` helper; `buy()`/`sell()` pass MARKET/None explicitly; retired the `order_type` class attr, its `_COERCE` entry, and the `to_dict()` order_type key.
- `itrader/strategy_handler/signal_record.py` - SignalRecord gains `order_type`/`entry_price` audit fields + docstrings.
- `itrader/strategy_handler/strategies_handler.py` - per-intent fan-out (order_type=intent.order_type; MARKET keeps to_money(bar.close), LIMIT/STOP use intent.entry_price); SignalRecord capture threads the new fields; `OrderType` imported.
- `tests/unit/strategy/test_signal_factories.py` - new: 18 assertions over the 6 factories, price-required/keyword-only, MARKET byte-exactness, and the dropped to_dict order_type key.
- `tests/e2e/strategies/scripted_emitter.py` - (deviation) per-instance `order_type` stashed on the fixture and routed through the typed factories at the decision-bar close to preserve every golden byte-exact.
- `tests/unit/core/test_sizing.py` - (deviation) SignalIntent constructions now pass the required `order_type=OrderType.MARKET`; minimal-construction test asserts the new defaults.

## Decisions Made
- Followed D-01/D-02 exactly. Discretion exercised: a shared private `_intent()` helper folds the sl/tp/exit_fraction/entry_price logic across all six methods (allowed by D-01); SignalRecord field names are `order_type`/`entry_price` (allowed by D-02).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Retire-order_type blast radius: ScriptedEmitter passed the now-rejected `order_type` base kwarg**
- **Found during:** Task 3 (per-intent fan-out)
- **Issue:** Retiring the `Strategy.order_type` class attr (D-01) made `get_type_hints` stop surfacing it, so the e2e `ScriptedEmitter` fixture — which passed `order_type=...` straight into `super().__init__()` — raised `UnknownParamError`, failing all 57 LIMIT/STOP-touching e2e scenarios.
- **Fix:** Stashed `order_type` as a per-instance fixture attr (not a base kwarg) and routed each scripted intent through the matching typed factory (`buy_limit`/`buy_stop`/`sell_limit`/`sell_stop`) at the decision-bar close (`self.bars["close"].iloc[-1]`) — value-identical to the legacy `SignalEvent.price = to_money(decision_bar.close)` fan-out, so every golden stays byte-exact.
- **Files modified:** tests/e2e/strategies/scripted_emitter.py
- **Verification:** `poetry run pytest tests/e2e -m e2e` -> 58/58 green (golden CSVs/summaries byte-identical).
- **Committed in:** 7c648f9 (Task 3 commit)

**2. [Rule 3 - Blocking] SignalIntent now requires order_type — 6 unit constructions broke**
- **Found during:** Task 3 (full-suite regression)
- **Issue:** `order_type` is now a required (never-None) field on `SignalIntent` (D-01), so 6 constructions in `tests/unit/core/test_sizing.py` that omitted it raised `TypeError: missing required keyword-only argument`.
- **Fix:** Added `order_type=OrderType.MARKET` to each construction (+ `OrderType` import); the minimal-construction test now also asserts `order_type`/`entry_price` defaults.
- **Files modified:** tests/unit/core/test_sizing.py
- **Verification:** `poetry run pytest tests/unit tests/integration` -> 906 passed.
- **Committed in:** 7c648f9 (Task 3 commit)

---

**Total deviations:** 2 auto-fixed (both Rule 3 - blocking, both direct blast radius of the D-01 order_type retirement explicitly anticipated by the plan/context).
**Impact on plan:** Both were necessary to keep the suite green under the intended D-01 retirement. No scope creep — both fixes preserve byte-exact behavior (the existing oracle and every e2e golden are unchanged).

## Issues Encountered
- The plan referenced `05-PATTERNS.md`, which does not exist in the phase directory. The plan's inline `<interfaces>` block and `05-CONTEXT.md` (with exact file/line targets) provided sufficient detail; no PATTERNS lookup was needed.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The strategy->signal authoring surface for per-intent order_type + entry price is complete (SIG-01/SIG-02). The order/admission/matching consumers were already wired and remain untouched.
- Ready for 05-02+ (SIG-03 typing + snapshot threading, RECON-01 reconcile cleanup, and the owner-gated limit-entry cross-validation golden).
- No blockers. The existing golden (134 / 46189.87730727451) is byte-exact, so any future drift is an unambiguous SIG-03/RECON-01 signal.

## Self-Check: PASSED

---
*Phase: 05-signal-contract-reconcile-fragile*
*Completed: 2026-06-13*
