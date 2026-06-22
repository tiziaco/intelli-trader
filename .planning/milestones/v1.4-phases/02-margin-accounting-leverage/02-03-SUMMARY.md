---
phase: 02-margin-accounting-leverage
plan: 03
subsystem: api
tags: [margin, leverage, admission, order-handler, universe, decimal, byte-exact]

# Dependency graph
requires:
  - phase: 02-margin-accounting-leverage (Plan 01)
    provides: SignalEvent.leverage (D-03) + TradingRules.max_leverage ge=1 (D-14) inert fields
  - phase: 02-margin-accounting-leverage (Plan 02)
    provides: LeveredFraction sizing kind (D-07) + SizingResolver arm + SignalIntent.leverage mirror
  - phase: 01-instrument-value-object
    provides: Instrument.max_leverage (inert) + Universe.instrument(symbol) + derive_instruments
provides:
  - "Universe-aware order domain — Optional[Universe] threaded compose-root → OrderHandler → OrderManager → AdmissionManager (Pitfall 1 BLOCKING gap closed)"
  - "_effective_leverage cap helper (D-04/D-05): min(signal, instr.max_leverage, pf cap), clamp+warn, force-to-1 when margin off"
  - "f>1-without-enable_margin admission gate (LEV-02/D-07) → audited REJECTED (ADMISSION_LEVERAGE)"
  - "enable_margin-branched admission reservation (byte-exact site #1): margin reserves notional/L + commission (D-08), spot reserves full notional with NO division (Pitfall 4)"
  - "over-margin REJECT routed through the existing audited CASH_RESERVATION path verbatim (MARGIN-02/D-01)"
  - "set_universe injection seam wired in backtest_runner.py + live_trading_system.py after the exchange injection (Trap-4)"
affects: [02-04-liquidation, 02-shorts-carry, margin-settlement, portfolio-handler-margin]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "byte-exact enable_margin gate: a real if-branch, NEVER notional/1 (Decimal exponent risk)"
    - "Trap-4 set_universe injection mirroring SimulatedExchange.set_universe into the order domain"
    - "audited REJECTED path reused verbatim for both over-margin and the f>1 gate"

key-files:
  created: []
  modified:
    - itrader/order_handler/admission/admission_manager.py
    - itrader/order_handler/order_manager.py
    - itrader/order_handler/order_handler.py
    - itrader/order_handler/order_validator.py
    - itrader/trading_system/compose.py
    - itrader/trading_system/backtest_runner.py
    - itrader/trading_system/live_trading_system.py
    - itrader/core/enums/order.py

key-decisions:
  - "Optional[Universe] injected into the order domain (RESEARCH OQ1 recommendation) — not a narrow Protocol — defaulted None so spot stays byte-exact"
  - "The f>1-without-margin gate lives in AdmissionManager (RESEARCH A3), not the config-free resolver/policy"
  - "Spot reservation arm computes notional + commission with NO division — a real if enable_margin branch (Pitfall 4)"
  - "Rule-3 deviation: EnhancedOrderValidator made margin-aware (enable_margin flag, default False) so its full-notional cash check defers to the reservation gate in margin mode"

patterns-established:
  - "set_universe late-injection seam: order domain receives the Universe at the Trap-4 wiring point after construction"
  - "OrderTriggerSource.ADMISSION_LEVERAGE audit trail for the f>1 gate"

requirements-completed: [LEV-01, LEV-02, MARGIN-01, MARGIN-02]

# Metrics
duration: 18min
completed: 2026-06-15
---

# Phase 2 Plan 03: Order/Risk-Layer Margin Logic Summary

**Universe-aware order domain with a leverage cap (D-04/D-05), an enable_margin-branched margin reservation (notional/L + commission, D-08) routing over-margin through the audited REJECTED path (MARGIN-02/D-01), and the LeveredFraction f>1 admission gate — SMA_MACD spot oracle held byte-exact at 134 / 46189.87730727451.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-06-15T11:20:00Z
- **Completed:** 2026-06-15T11:32:00Z
- **Tasks:** 3
- **Files modified:** 8 (+ 1 test file, + deferred-items.md)

## Accomplishments
- Closed the BLOCKING structural gap (Pitfall 1): the order domain can now read `Instrument.max_leverage` via an injected `Optional[Universe]` threaded from the compose root through `OrderHandler → OrderManager → AdmissionManager`, with a `set_universe` seam wired in both runners after the existing `simulated_exchange.set_universe`.
- Added `_effective_leverage` (D-04/D-05): `enable_margin=False` forces `Decimal("1")` with NO instrument read (spot byte-exact); margin-on caps `min(signal, instr.max_leverage, pf cap)` and clamps-with-warning above the cap.
- Added the `f > 1 without enable_margin` admission gate (LEV-02/D-07): a `LeveredFraction(fraction>1)` reaching admission with margin off is REJECTED via the audited path.
- Branched the admission reservation cost on `enable_margin` (byte-exact site #1): margin reserves `notional / effective_leverage + commission` (D-08); spot reserves `notional + commission` with NO division (Pitfall 4). Over-margin rejects via the existing `InsufficientFundsError → CASH_RESERVATION` audited path verbatim.

## Task Commits

Each task was committed atomically (TDD tasks have test → feat commits):

1. **Task 1: Thread Optional[Universe] + enable_margin + portfolio_max_leverage through the order domain + runner wiring** - `33a62b8` (feat)
2. **Task 2: _effective_leverage cap (D-04/D-05) + f>1 gate (LEV-02)** - `5f46ae2` (test, RED) → `682440f` (feat, GREEN)
3. **Task 3: enable_margin reservation branch (D-08/D-09) + over-margin reject (MARGIN-02/D-01)** - `3703c68` (test, RED) → `0d59f12` (feat, GREEN)

## Files Created/Modified
- `itrader/order_handler/admission/admission_manager.py` - universe/enable_margin/portfolio_max_leverage ctor params + set_universe; `_effective_leverage` cap helper; `_enforce_leverage_admission` f>1 gate; enable_margin-branched reservation cost (TAB file, tabs preserved)
- `itrader/order_handler/order_manager.py` - thread enable_margin/portfolio_max_leverage into AdmissionManager + the validator; `set_universe` forwarder; Universe import
- `itrader/order_handler/order_handler.py` - thread params into OrderManager; `set_universe` facade; Universe import
- `itrader/order_handler/order_validator.py` - Rule-3: `enable_margin` flag (default False) defers the full-notional cash-cost check to the reservation gate in margin mode (4-space file)
- `itrader/trading_system/compose.py` - read `config_data.trading_rules` for enable_margin/max_leverage into OrderHandler
- `itrader/trading_system/backtest_runner.py` - `order_handler.set_universe(universe)` after the exchange injection (Trap-4)
- `itrader/trading_system/live_trading_system.py` - mirrored OrderHandler margin threading + `set_universe`
- `itrader/core/enums/order.py` - `OrderTriggerSource.ADMISSION_LEVERAGE`
- `tests/unit/order/test_admission_rules.py` - 12 new tests (leverage cap/clamp/force-to-1/no-instrument-read, f>1 gate, margin reservation, spot reservation, over-margin reject, leverage-affordable); replaced the 5 Wave-0 stubs
- `.planning/phases/02-margin-accounting-leverage/deferred-items.md` - logged DEF-02-03-A

## Decisions Made
- Injected the concrete `Optional[Universe]` (RESEARCH OQ1 recommendation) rather than a narrow `InstrumentReadModel` Protocol — smallest seam; the order domain already injects concrete read-models. Defaulted `None` keeps every existing construction and the spot path byte-exact.
- Placed the `f>1` gate in `AdmissionManager` (RESEARCH A3), keeping the resolver/policy config-free; added a dedicated `OrderTriggerSource.ADMISSION_LEVERAGE` for the audit trail.
- Used a real `if self._enable_margin:` branch for the reservation cost; the spot arm never routes through division (Pitfall 4 — a `/1` can shift the Decimal exponent and drift the byte-exact oracle).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Made EnhancedOrderValidator margin-aware**
- **Found during:** Task 3 (enable_margin reservation branch)
- **Issue:** The validator's `_check_cash_availability` (step 3 of `process_signal`) checks the FULL notional cost against available cash and runs BEFORE the margin reservation gate (step 3b). In margin mode this pre-empts the designed gate: it wrongly rejected a leverage-affordable order (notional > cash but notional/L ≤ cash) and routed an over-margin reject through the VALIDATOR trigger instead of the designed audited CASH_RESERVATION path (MARGIN-02/D-01).
- **Fix:** Added an `enable_margin: bool = False` flag to `EnhancedOrderValidator`; the full-notional cash-cost check is skipped when margin is on (the reservation gate is the cash authority in margin mode). The minimum-cash floor still applies. Threaded `enable_margin` into the validator construction in `OrderManager` (which builds the validator the AdmissionManager holds).
- **Files modified:** `itrader/order_handler/order_validator.py` (out of the plan's declared files_modified), `itrader/order_handler/order_manager.py`
- **Verification:** `test_over_margin_order_is_rejected_via_audited_path` (trigger is CASH_RESERVATION) and `test_margin_makes_otherwise_unaffordable_order_affordable` pass; default False keeps spot byte-exact (193 unit/order green, oracle byte-exact).
- **Committed in:** `0d59f12` (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 blocking).
**Impact on plan:** The validator change was required for the margin reservation gate to be the cash authority and for over-margin to reject via the designed audited path. Defaulted False → zero behavior change on the spot/golden path. No scope creep beyond making the existing spot-only cash check margin-aware.

## Issues Encountered
- **DEF-02-03-A (pre-existing, out of scope, logged):** `tests/unit/core/test_sizing.py::test_sizing_policy_union_members` asserts the OLD 3-member `SizingPolicy` union, but Plan 02-02 (`e2afb00`) grew the union with `LeveredFraction` without updating this test — confirmed failing at plan start, in an unrelated file. Logged to `deferred-items.md` for Plan 02-02 / a follow-up quick-task; NOT fixed here (SCOPE BOUNDARY). The plan's own verify targets (`tests/unit/order`, `tests/integration`) are fully green.

## Known Stubs
None. All five Wave-0 admission stubs were replaced with real tests; no placeholder/empty-value patterns introduced.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- The order/risk layer is Universe-aware and margin-gated; the leverage cap + margin reservation + over-margin/f>1 rejects work and are unit-covered. The portfolio-side lock-and-settle settlement (Plan 02-04) builds on this — the admission reservation reserves `notional/L`, leaving the position-keyed `locked_margin` lifecycle (D-10/D-11) and `maintenance_margin`/`margin_ratio` read-model (D-13) to the settlement plan.
- No blockers. enable_margin remains owner-gated/config-gated (default PortfolioConfig is `enable_margin=False`), so the new arms stay oracle-dark until the parked leveraged scenario is frozen at P4/XVAL-01.

## Self-Check: PASSED

- SUMMARY.md + deferred-items.md exist on disk.
- All task commits verified present: `33a62b8`, `5f46ae2`, `682440f`, `3703c68`, `0d59f12`.

---
*Phase: 02-margin-accounting-leverage*
*Completed: 2026-06-15*
