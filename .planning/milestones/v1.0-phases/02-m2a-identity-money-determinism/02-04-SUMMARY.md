---
phase: 02-m2a-identity-money-determinism
plan: 04
subsystem: portfolio
tags: [decimal, money, uuid, portfolio, transaction, position, order, determinism]

# Dependency graph
requires:
  - phase: 02-02
    provides: core/money.py (to_money, quantize) + core/ids.py NewType aliases
  - phase: 02-03
    provides: idgen.generate_*_id() returns uuid.UUID (single UUIDv7 scheme)
provides:
  - Five domain entities (order, transaction, position, portfolio) typed UUID-id + Decimal-money
  - portfolio.cash is Decimal end-to-end on the cash path (no float read round-trip)
  - The #17 defect removed — transaction_manager `cash += float(transaction_cost)` is now `cash += transaction_cost`
  - Decimal-money regression test locking M2-02
affects: [m2b, m4, numeric-oracle-rebaseline, pattern-e-oracle-tolerance]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Entity money enters the Decimal domain at the construction boundary via __post_init__/__init__ to_money() (D-04 string entry, never Decimal(float))"
    - "Float execution/event layer is sandwiched between two Decimal entity boundaries: Order->OrderEvent coerces to float; FillEvent->Transaction re-enters Decimal via to_money()"
    - "Portfolio aggregate read-properties stay float for float consumers; only the cash ledger field is Decimal (cash routing through CashManager deferred to M4)"

key-files:
  created:
    - test/test_portfolio_handler/test_money_decimal.py
  modified:
    - itrader/order_handler/order.py
    - itrader/portfolio_handler/transaction.py
    - itrader/portfolio_handler/position.py
    - itrader/portfolio_handler/portfolio.py
    - itrader/portfolio_handler/transaction_manager.py
    - itrader/portfolio_handler/cash_manager.py
    - itrader/events_handler/event.py
    - itrader/order_handler/order_manager.py

key-decisions:
  - "Added __post_init__ to Order and Transaction to normalise money to Decimal regardless of construction path (factory or direct), guaranteeing Decimal-end-to-end with no Decimal(float)"
  - "portfolio.cash getter returns Decimal (float() cast removed) — required for the Decimal cash += transaction_cost path fix; aggregate read-props (total_equity/market_value/pnl) kept float for float consumers"
  - "DEF-01-A reconciled: position.avg_price float(commission) coercion removed (commissions are now Decimal end-to-end)"
  - "Float execution layer (matching/fee/slippage) left unchanged (M4/M5); OrderEvent.new_order_event coerces order money to float at the entity->execution boundary"

patterns-established:
  - "Pattern: Decimal money at entity boundaries (__post_init__/to_money), float coercion only at entity->float-consumer read boundaries"
  - "Pattern: cash-path Decimal purity — no float() round-trip on cash read or on the transaction cost apply"

requirements-completed: [M2-01, M2-02]

# Metrics
duration: 20min
completed: 2026-06-04
---

# Phase 02 Plan 04: Decimal Money + UUID Entity Retype Summary

**Five domain entities retyped to UUID ids + Decimal money, the `transaction_manager.py:229` `cash += float(transaction_cost)` round-trip (#17) removed, and a Decimal-money regression test locking M2-02.**

## Performance

- **Duration:** ~20 min
- **Started:** 2026-06-04T18:00:00Z
- **Completed:** 2026-06-04T18:18:00Z
- **Tasks:** 3
- **Files modified:** 8 (+1 created)

## Accomplishments
- `order.py`/`transaction.py`/`position.py` money fields typed `Decimal`, id/fk fields typed `core.ids` NewType aliases (`OrderId`, `PortfolioId`, `PositionId`, `TransactionId`, `StrategyId`); `Order` left mutable (not frozen).
- `portfolio.cash` typed `Decimal`; the cash getter no longer `float()`-casts the ledger balance (M2-02: no float round-trip on read).
- THE money defect removed: `transaction_manager.py` `self.portfolio.cash += float(transaction_cost)` → `self.portfolio.cash += transaction_cost`; defensive `Decimal(str(self.portfolio.cash))` dropped; money `float()` casts in log/error payloads replaced with `str()`.
- Decimal-money regression test (`test_money_decimal.py`) proving cash is Decimal before AND after a transaction, and Transaction money fields + `cost` are Decimal.

## Task Commits

1. **Task 1: Retype order/transaction/position (UUID id + Decimal money)** - `f6ee9dc` (feat)
2. **Task 2: Decimal cash + remove transaction_manager float round-trip** - `3567aa8` (feat)
3. **Task 3: Decimal-money regression test (M2-02)** - `80ca119` (test)
4. **Follow-up: widen CashManager money params to float | Decimal** - `9a55313` (fix)

## Files Created/Modified
- `itrader/order_handler/order.py` - id/fk → UUID aliases; price/quantity/filled_quantity → Decimal; `__post_init__` + factory `to_money()` boundary conversion; property return types Decimal.
- `itrader/portfolio_handler/transaction.py` - money fields → Decimal, ids → aliases; `__post_init__` to_money(); `cost`/`total_cost` return Decimal.
- `itrader/portfolio_handler/position.py` - money attrs → Decimal via `__init__` to_money(); property return types Decimal; DEF-01-A float(commission) cast removed.
- `itrader/portfolio_handler/portfolio.py` - cash constructor arg + getter/setter → Decimal (no float read round-trip); aggregate read-props kept float; `_get_max_position_percentage` coerces Decimal market_value to float.
- `itrader/portfolio_handler/transaction_manager.py` - #17 round-trip removed; defensive Decimal(str(cash)) dropped; money float() casts → str() in payloads; Decimal(str(...)) redundant round-trips in `_validate_transaction` removed.
- `itrader/portfolio_handler/cash_manager.py` - to_money() at Decimal entry boundary; money params widened to `float | Decimal`.
- `itrader/events_handler/event.py` - `OrderEvent.new_order_event` coerces order price/quantity to float at the entity→execution boundary (Rule 3).
- `itrader/order_handler/order_manager.py` - sizing path coerces Decimal cash/net_quantity to float at the float sizing boundary (Rule 3).
- `test/test_portfolio_handler/test_money_decimal.py` - M2-02 regression lock.

## Decisions Made
- `__post_init__` Decimal normalisation on `Order`/`Transaction` so both factory and direct construction store Decimal money (robust Decimal-end-to-end, no `Decimal(float)`).
- Portfolio aggregate read-properties (`total_equity`/`total_market_value`/`total_*_pnl`) deliberately kept float — only the cash *ledger field* is Decimal in M2a. Routing cash + aggregates through Decimal/CashManager is M4 (#22). This confines the Decimal change to the cash path the plan scopes.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] OrderEvent boundary coercion (entity Decimal → float execution layer)**
- **Found during:** Task 1 (entity retype)
- **Issue:** With `Order.price`/`quantity` now Decimal, `OrderEvent.new_order_event` propagated Decimal into the float matching/fee/slippage layer → `Decimal * float` TypeError in `simulated.py` (stop/limit integration tests).
- **Fix:** Coerce `order.price`/`order.quantity` to `float` in `new_order_event`. The execution layer stays float until M4; the cash path re-enters Decimal at `Transaction.new_transaction`. `event.py` event-id concerns (M3) untouched.
- **Files modified:** itrader/events_handler/event.py
- **Verification:** test_stop_limit_orders + full order_handler suite green.
- **Committed in:** f6ee9dc (Task 1 commit)

**2. [Rule 3 - Blocking] OrderManager sizing coercion (Decimal cash → float sizer)**
- **Found during:** Task 2 (portfolio.cash → Decimal)
- **Issue:** `order_manager.py:272` `(0.95 * portfolio.cash) / price` and `:269` `net_quantity` assignment mixed float with the now-Decimal cash/net_quantity → `float * Decimal` TypeError in the signal sizing path (smoke + integration backtest).
- **Fix:** Coerce `float(portfolio.cash)` / `float(net_quantity)` at the float sizing boundary. `order_manager.py` is not retyped here (M4 sizing scope).
- **Files modified:** itrader/order_handler/order_manager.py
- **Verification:** smoke backtest produces 134 non-zero trades; full suite minus oracle green.
- **Committed in:** 3567aa8 (Task 2 commit)

**3. [Rule 1 - Bug] Updated Decimal-incompatible test assertions**
- **Found during:** Tasks 1 & 2
- **Issue:** Several existing tests encoded the old float contract: `assertEqual(price, 42350.72)` (Decimal != float), `assertAlmostEqual(Decimal, float, delta=...)` (TypeError), `Decimal + 0.5` float arithmetic, and a MockPortfolio with float cash that breaks `cash += Decimal`.
- **Fix:** Updated assertions to compare against `Decimal`/coerce computed Decimals to float for tolerance checks; MockPortfolio cash → Decimal; the precision test now asserts exact Decimal equality (strengthening the no-round-trip guarantee).
- **Files modified:** test/test_transaction/test_transaction_init.py, test/test_positions/test_multiple_buy.py, test/test_portfolio_handler/test_position_manager.py, test/test_portfolio_handler/test_transaction_manager.py
- **Verification:** all four touched suites green.
- **Committed in:** f6ee9dc, 3567aa8

**4. [Rule 3 - Type] Widened CashManager money param types to float | Decimal**
- **Found during:** post-task mypy check
- **Issue:** Decimal cash setter passes a Decimal `difference` to `CashManager.deposit`/`withdraw` typed `amount: float` → mypy arg-type errors.
- **Fix:** Widened the six CashManager money-input signatures to `float | Decimal` (inputs already enter via `to_money()`).
- **Files modified:** itrader/portfolio_handler/cash_manager.py
- **Verification:** mypy arg-type errors resolved; cash/portfolio suites green.
- **Committed in:** 9a55313

---

**Total deviations:** 4 (2 blocking boundary coercions, 1 test-contract update, 1 type widening)
**Impact on plan:** All deviations are minimal boundary coercions or test-contract updates strictly required by the locked Decimal-end-to-end decision. No architectural change; the float execution/sizing layer is untouched (M4 scope). No scope creep.

## Issues Encountered

**Golden oracle numeric drift (out of scope — deferred).** `test_backtest_oracle.py::test_full_backtest_matches_frozen_oracle` fails because float→Decimal money produces tiny numeric deltas in NON-key columns (`net_quantity` 1.4e-16, `avg_price` 7.5e-6, `realised_pnl` 7.9e-3, etc.). The **behavioral** oracle is fully preserved: 134 trades in both runs, key columns (`entry_date`/`exit_date`/`side`) and `pair` byte-identical. The oracle test (`test_backtest_oracle.py`) is NOT in this plan's files; the fix is **Pattern E** (identity-EXACT / numeric-TOLERANT split, another plan's target) and the **post-M2 numerical oracle re-baseline** is an owner-gated golden-master phase-boundary decision (CLAUDE.md). The executor must NOT silently overwrite `test/golden/trades.csv`. Logged to `deferred-items.md` as DEF-02-04-A.

## Next Phase Readiness
- Five entities are UUID-id + Decimal-money typed; the cash path is Decimal-pure with the #17 round-trip removed; M2-02 regression-locked.
- **Blocker for the next golden gate:** the numerical oracle must be re-baselined (after M2) via the Pattern E plan with owner approval before the oracle integration test goes green again.
- M4 (#22) will route cash through CashManager and may move the portfolio aggregate read-properties to Decimal.

## Self-Check: PASSED

- Files verified present: `test/test_portfolio_handler/test_money_decimal.py`, `02-04-SUMMARY.md`, `deferred-items.md`
- Commits verified present: `f6ee9dc` (Task 1), `3567aa8` (Task 2), `80ca119` (Task 3), `9a55313` (type fix)

---
*Phase: 02-m2a-identity-money-determinism*
*Completed: 2026-06-04*
