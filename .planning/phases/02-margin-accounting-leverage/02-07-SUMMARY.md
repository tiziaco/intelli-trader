---
phase: 02-margin-accounting-leverage
plan: 07
subsystem: api
tags: [leverage, margin, decimal, signal-event, order-event, fill-event, transaction, position, admission]

# Dependency graph
requires:
  - phase: 02-margin-accounting-leverage
    provides: "Plan 03 admission leverage cap (_effective_leverage); Plan 04 lock-and-settle position-keyed locked margin; Plan 05 maintenance_margin/margin_ratio read-model; Plan 06 parked leveraged-long e2e (the two findings)"
provides:
  - "Strategy-declared EFFECTIVE leverage flows end-to-end: SignalIntent -> SignalEvent -> Order -> OrderEvent -> FillEvent -> Transaction -> Position (LEV-03)"
  - "Position-life locked margin (aggregate_notional / leverage) EQUALS the admission reservation (notional / effective_leverage) under leverage > 1"
  - "OrderEvent.leverage and FillEvent.leverage fields carrying the admission-clamped effective leverage"
  - "Order entity + Order.new_order kw-only leverage; Transaction kw-only leverage"
  - "Reworked 02-06 parked leveraged-long e2e: leverage driven through the normal fan-out, corrected self-consistent numbers (position.leverage=5, locked_margin=4000)"
affects: [phase-03-shorts, phase-04-liquidation-xval, margin, leverage]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "getattr-default leverage read at each hop (mirrors stop_price) — robust to pre-field stubs, degrades to Decimal('1') oracle-dark"
    - "effective leverage computed once at the order-build site and threaded onto the Order entity"

key-files:
  created:
    - tests/unit/order/test_leverage_plumbing.py
  modified:
    - itrader/strategy_handler/strategies_handler.py
    - itrader/order_handler/order.py
    - itrader/order_handler/admission/admission_manager.py
    - itrader/events_handler/events/order.py
    - itrader/events_handler/events/fill.py
    - itrader/portfolio_handler/transaction/transaction.py
    - itrader/portfolio_handler/portfolio_handler.py
    - tests/unit/strategy/test_strategy.py
    - tests/e2e/levered_long/test_levered_long_scenario.py

key-decisions:
  - "The leverage carried to the Position is the admission-clamped EFFECTIVE leverage min(signal.leverage, Instrument.max_leverage, portfolio.max_leverage), NOT the raw signal request — makes locked margin == reservation"
  - "effective leverage computed once at _build_primary_order via _effective_leverage (returns Decimal('1') with no division/instrument-read on the spot path — oracle-dark)"
  - "Run-path Transaction is built directly in PortfolioHandler.on_fill (not via new_transaction), so the leverage thread was also added there (Rule 1/2 deviation — the actual flow site)"

patterns-established:
  - "Each leverage hop reads via getattr(obj, 'leverage', Decimal('1')) — pre-field stubs degrade to 1 (byte-exact)"
  - "kw-only leverage with Decimal('1') default on Order.new_order and Transaction preserves positional construction byte-exact"

requirements-completed: [LEV-03]

# Metrics
duration: 18min
completed: 2026-06-15
---

# Phase 2 Plan 07: Plumb Strategy-Declared Leverage End-to-End (LEV-03) Summary

**Effective leverage now flows signal -> order -> fill -> transaction -> position so position-life locked margin (aggregate_notional/leverage) equals the admission reservation (notional/effective_leverage); SMA_MACD spot oracle held byte-exact.**

## Performance

- **Duration:** ~18 min
- **Started:** 2026-06-15T12:40:00Z
- **Completed:** 2026-06-15T12:58:00Z
- **Tasks:** 3
- **Files modified:** 9 (1 created, 8 modified)

## Accomplishments
- Closed Finding A: `StrategiesHandler.calculate_signals` now carries `intent.leverage` onto the fan-out `SignalEvent`.
- Closed Finding B: the admission-clamped EFFECTIVE leverage flows `Order -> OrderEvent -> FillEvent -> Transaction -> Position`; `Position.leverage` resolves via the existing getattr consumer (unchanged).
- Position-life locked margin now EQUALS the admission reservation under leverage > 1 (20000/5 = 4000 both sides — self-consistent).
- Reworked the 02-06 parked leveraged-long e2e: leverage driven through the production fan-out (no injected SignalEvent), corrected hand-computed numbers asserted (position.leverage=5, locked_margin=4000, adverse-mark free margin positive 6000), docstring updated (findings CLOSED). Still PARKED (D-17).
- SMA_MACD spot oracle byte-exact (134 / 46189.87730727451); `mypy --strict` clean (185 files); full suite 1079 passed.

## Task Commits

1. **Task 1 (RED): fan-out leverage failing test** - `42d0763` (test)
2. **Task 1 (GREEN): carry intent.leverage onto SignalEvent** - `81f85ec` (feat)
3. **Task 2 (RED): effective-leverage plumbing failing tests** - `978b646` (test)
4. **Task 2 (GREEN): plumb Order->OrderEvent->FillEvent->Transaction** - `df8c2a0` (feat)
5. **Task 3: rework parked e2e + close run-path leverage gap** - `4e9ca05` (feat)

_TDD tasks 1 and 2 each have a RED test commit then a GREEN impl commit._

## Files Created/Modified
- `tests/unit/order/test_leverage_plumbing.py` - per-hop RED/GREEN tests (Order/OrderEvent/FillEvent/Transaction/Position + admission clamp)
- `tests/unit/strategy/test_strategy.py` - fan-out leverage tests (Finding A)
- `itrader/strategy_handler/strategies_handler.py` - `leverage=intent.leverage` on the SignalEvent fan-out (TABS)
- `itrader/order_handler/order.py` - Order entity `leverage` field + kw-only `leverage` on `new_order` (TABS)
- `itrader/order_handler/admission/admission_manager.py` - `_build_primary_order` threads `_effective_leverage` onto the MARKET Order (TABS)
- `itrader/events_handler/events/order.py` - `OrderEvent.leverage` + getattr read in `new_order_event` (4 spaces)
- `itrader/events_handler/events/fill.py` - `FillEvent.leverage` + carry from order in `new_fill` (4 spaces)
- `itrader/portfolio_handler/transaction/transaction.py` - `Transaction.leverage` kw-only + read in `new_transaction` (TABS)
- `itrader/portfolio_handler/portfolio_handler.py` - run-path `on_fill` Transaction carries `fill_event.leverage` (4 spaces)
- `tests/e2e/levered_long/test_levered_long_scenario.py` - normal-fan-out rework, corrected parked numbers

## Decisions Made
- The leverage carried to the Position is the admission-clamped EFFECTIVE leverage (clamped to caps), NOT the raw request — keeps locked margin == reservation (locked by owner, honored).
- `_effective_leverage` is called unconditionally at the order-build site; on the spot path it returns `Decimal("1")` with no division/instrument read, so no oracle drift.
- Used getattr-default reads at every hop (mirrors the existing `stop_price` pattern) so hand-built stubs predating the fields degrade to `Decimal("1")`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1/2 - Missing Critical] Run-path Transaction leverage thread in PortfolioHandler.on_fill**
- **Found during:** Task 3 (e2e rework) — the e2e asserted `position.leverage == 5` but read 1.
- **Issue:** The plan pointed at `Transaction.new_transaction` as the leverage carry site, but the RUN PATH constructs the `Transaction` directly in `PortfolioHandler.on_fill` (`portfolio_handler.py:381`), bypassing `new_transaction`. Without threading leverage there, the position-life locked margin stayed at the default leverage 1 (= full notional 20000), so LEV-03's core truth (locked == reservation) was unmet in the actual engine flow.
- **Fix:** Added `leverage=getattr(fill_event, "leverage", Decimal("1"))` to the direct `Transaction(...)` construction in `on_fill`.
- **Files modified:** `itrader/portfolio_handler/portfolio_handler.py` (not in the plan's `files_modified` list)
- **Verification:** e2e asserts `position.leverage == 5` and `locked_margin == 4000`; SMA_MACD oracle byte-exact (the getattr default keeps spot fills at 1); full suite green; mypy clean.
- **Committed in:** `4e9ca05` (Task 3 commit)

---

**Total deviations:** 1 auto-fixed (1 missing critical run-path site)
**Impact on plan:** The deviation was required for correctness — it is the actual leverage flow site on the run path. `Transaction.new_transaction` is still wired (covered by the hop unit test) for the non-engine/test construction path. No scope creep; oracle held byte-exact.

## Issues Encountered
- None beyond the run-path deviation above. The over-cap clamp warning logs twice (once at build, once at reservation) since both call `_effective_leverage` — harmless and intentional (both sites need the clamped value).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- LEV-03 closed; the Phase-2 margin core is internally consistent under leverage > 1.
- The parked leveraged-long e2e now proves leverage end-to-end with self-consistent margin numbers (still PARKED — freezes at Phase 4 / XVAL-01 under owner sign-off + cross-validation, D-17).
- Phase 3 (shorts) and Phase 4 (liquidation) consume `Position.leverage` / locked margin; both now see the effective leverage on every position opened through the run path.

---
*Phase: 02-margin-accounting-leverage*
*Completed: 2026-06-15*
