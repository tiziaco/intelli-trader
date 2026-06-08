---
phase: 08-m5c-cross-validation-final-oracle
plan: 01
subsystem: portfolio
tags: [decimal, money, portfolio, metrics, order-validation, D-06, M5-10]

# Dependency graph
requires:
  - phase: 05-m4-money-transaction-correctness
    provides: "Decimal money at entity boundaries (cash, Order.price/quantity, position_manager Decimal aggregates)"
  - phase: 07-m5b-sizing-metrics-universe-coverage
    provides: "PortfolioReadModel.total_equity Protocol method (Decimal), reporting/metrics.py float ratio boundary"
provides:
  - "Portfolio.total_market_value/total_equity/total_unrealised_pnl/total_realised_pnl/total_pnl typed -> Decimal with Decimal-native aggregation (no float() narrowing in bodies)"
  - "MetricsManager money fields Decimal end-to-end; float boundary moved to statistical-ratio metric inputs only"
  - "EnhancedOrderValidator golden-path price/quantity/cash/order-value checks compare in native Decimal"
affects: [08-02-mypy-caller-fanout, 08-03-oracle-refreeze, cross-validation]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Decimal end-to-end on the result-bearing path: money read-properties return Decimal; float appears only at statistical-ratio metric INPUTS (returns/volatility/drawdown), never at a money property boundary"
    - "Threshold comparison via Decimal(str(self.<threshold>)) at the comparison site — never Decimal(float) (core/money.py:17 binary-float-repr guard)"

key-files:
  created: []
  modified:
    - "itrader/portfolio_handler/portfolio.py - total_* properties retyped to Decimal; _get_max_position_percentage harmonized Decimal-native"
    - "itrader/portfolio_handler/metrics/metrics_manager.py - get_current_metrics money fields Decimal; _as_decimal pass-through helper; ratio-input float boundaries commented"
    - "itrader/order_handler/order_validator.py - native Decimal golden-path checks; Decimal import added"
    - "tests/unit/portfolio/test_money_decimal.py - Decimal-type assertions for total_* properties"
    - "tests/unit/portfolio/test_metrics_manager.py - Decimal-money-fields assertion for get_current_metrics"
    - "tests/unit/order/test_order_validator.py - Decimal-exact cash-check boundary tests"

key-decisions:
  - "D-06 closure on the golden path: Portfolio money read-properties are Decimal-typed; the float boundary lives only at statistical-ratio metric inputs (drawdown/return-distribution/daily-return), each explicitly commented"
  - "MetricsManager._as_decimal static helper passes a Decimal through unchanged (golden path) and coerces a raw float only for lightweight test portfolios — avoids a str round-trip while keeping the float-attribute MockPortfolio green"
  - "Validator thresholds wrapped via Decimal(str(self.<threshold>)) at comparison sites (never Decimal(float)); cost/order_value computed Decimal*Decimal"
  - "EXPECTED RESULT-CHANGE (D-08): the equity-curve total_equity column shifts at Decimal precision (oracle numeric test now fails ~0.6% on intermediate rows). Behavioral oracle unchanged; final_equity byte-identical at 46189.87730727451. Deferred to 08-03 named re-freeze REFREEZE-M5C-DECIMAL."

patterns-established:
  - "Decimal-native money read boundary: no float() cast in a money property body; aggregation stays Decimal+Decimal"
  - "Statistical-ratio metric input boundary: float() only where a ratio/division is computed, commented as such"

requirements-completed: [M5-10]

# Metrics
duration: 7min
completed: 2026-06-08
---

# Phase 8 Plan 01: Decimal Cleanup at Portfolio/Metrics/Validator Boundary Summary

**Retyped the result-bearing money properties (`Portfolio.total_*`), cleaned the `MetricsManager` money coercions, and converted `EnhancedOrderValidator` golden-path checks to native Decimal — closing the "Float Leaks at Portfolio Property Boundary" concern (D-06) before cross-validation, with the anticipated equity-curve precision shift handed to 08-03 for a named re-freeze.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-06-08T13:50:10Z
- **Completed:** 2026-06-08T13:57:25Z
- **Tasks:** 3 (all TDD: RED → GREEN)
- **Files modified:** 6 (3 source, 3 test)

## Accomplishments
- `Portfolio.total_market_value/total_equity/total_unrealised_pnl/total_realised_pnl/total_pnl` are now `-> Decimal` with Decimal-native aggregation (`total_equity = total_market_value + self.cash`, `total_pnl = total_unrealised_pnl + total_realised_pnl`) and no `float()` narrowing in any body.
- `MetricsManager.get_current_metrics` returns the six money fields as Decimal (no float coercion); the float boundary now lives only at the three statistical-ratio metric inputs (drawdown, return-distribution, daily-return), each explicitly commented as the D-06 metric-input boundary.
- `EnhancedOrderValidator` golden-path price/quantity positivity, range, cash-availability, and risk-limit checks compare native Decimal; thresholds wrapped via `Decimal(str(...))`; a precision-divergence test locks the cash check to exact Decimal arithmetic (a case the old float path wrongly rejected).
- `make test-portfolio` (178) and `make test-orders` (145) both pass; behavioral oracle byte-identical; `mypy --strict` clean (0 errors).

## Task Commits

Each task was committed atomically (TDD test → feat):

1. **Task 1: Retype Portfolio.total_* to Decimal** — `cdf60f5` (test, RED), `6c8ee92` (feat, GREEN)
2. **Task 2: Clean MetricsManager money coercions** — `18cb7be` (test, RED), `e99f1d4` (feat, GREEN)
3. **Task 3: Validator native Decimal golden-path checks** — `d5f7569` (test, RED), `6311378` (feat, GREEN)

**Plan metadata:** (this commit) (docs: complete plan)

## Files Created/Modified
- `itrader/portfolio_handler/portfolio.py` - Five `total_*` properties retyped to `Decimal`, `float()` casts dropped, aggregation Decimal+Decimal; `_get_max_position_percentage` ratio harmonized to Decimal-native (float only on the final reporting ratio).
- `itrader/portfolio_handler/metrics/metrics_manager.py` - `get_current_metrics` money fields returned as Decimal; new `_as_decimal` static pass-through helper replaces the `Decimal(str(...))` round-trip at `initial_equity` and the five `_get_*` readers; drawdown/return-distribution/daily-return float() sites commented as statistical-ratio metric-input boundaries.
- `itrader/order_handler/order_validator.py` - Added `from decimal import Decimal`; price/quantity positivity (`order.price <= 0`, `order.quantity <= 0`), range checks, cash availability (`cost = quantity * price` Decimal*Decimal; `cash < Decimal(str(self.min_cash_required))`), and risk limits (`order_value = order.quantity * order.price`) all native Decimal; pipeline docstring updated.
- `tests/unit/portfolio/test_money_decimal.py` - 5 new assertions that each `total_*` property is Decimal and aggregations equal Decimal sums (pre/post transaction).
- `tests/unit/portfolio/test_metrics_manager.py` - 1 new test that `get_current_metrics` returns all six money fields as Decimal.
- `tests/unit/order/test_order_validator.py` - 2 new cash-check tests; the boundary case (`1.07 * 101 = 108.07` exact Decimal vs `108.07000000000001` float) was a true RED under the old float path.

## Decisions Made
- Kept a defensive `_as_decimal` coercion in `MetricsManager._get_*` rather than a bare pass-through: the real Portfolio now hands Decimal straight through (no str round-trip), but the unit-test `MockPortfolio` still exposes raw float attributes, so the helper coerces only that case. This honors "pass the Decimal straight through" on the golden path while keeping the existing metrics suite green.
- Left `export_metrics_to_dict` float() casts in place: those operate on `PerformanceMetrics` ratio/percentage fields (returns, volatility, sharpe, win_rate), which are statistical-ratio outputs, not Portfolio money property reads — out of this plan's listed scope.

## Deviations from Plan

None - plan executed exactly as written (all three retypes applied to the listed sites; in-file consistency fixed; no external callers touched).

## Issues Encountered

**Anticipated result-change: equity-curve numeric precision shift (D-08, deferred to 08-03)**
- `tests/integration/test_backtest_oracle.py::test_oracle_numeric_values` now FAILS on the `total_equity` equity-curve column (~0.6% on some intermediate rows). `test_oracle_behavioral_identity` PASSES (trade timing/dates/sides byte-identical), and the run's `final_equity = 46189.87730727451` is byte-identical to the frozen oracle.
- **Root cause (not a bug):** the equity curve is built from `MetricsManager` snapshots, whose `total_equity` was previously `Decimal(str(float(market_value) + float(cash)))` — i.e. a float-rounded value re-stringified to Decimal. With the retype, `Portfolio.total_equity` is now the exact `market_value + cash` Decimal, so the snapshot stores the exact value. This is precisely the float-leak D-06 closes.
- **Sanctioned:** 08-CONTEXT.md D-08 explicitly names these properties (line 93) and states "Decimal cleanup gets its own named re-freeze — e.g. `REFREEZE-M5C-DECIMAL` ... plan for a re-freeze since Decimal precision likely shifts metric values." The plan's `<verification>` deliberately lists only `make test-portfolio` / `make test-orders`, not the oracle.
- **Action for 08-03:** regenerate the golden equity curve and write a `REFREEZE-M5C-DECIMAL` note documenting the equity-curve precision diff (behavioral identity preserved, final_equity byte-exact).

## Fan-Out Notes (for plan 08-02)

External consumers that now see a Decimal where they previously saw a float. `mypy --strict` is currently clean (0 errors) — the float-wrapping callers all accept Decimal — so 08-02's sweep is about removing now-redundant float boundaries, not fixing type errors.

| Consumer | Site | Status / Action for 08-02 |
|----------|------|---------------------------|
| `itrader/trading_system/backtest_trading_system.py:247` | `final_equity=float(portfolio.total_equity)` | Still wraps in `float()`. Works (Decimal→float). Decide whether the summary `final_equity` should stay float (it feeds summary.json / the oracle) or move to Decimal — likely keep float at this serialization boundary. |
| `itrader/trading_system/backtest_trading_system.py:233` | `equity = equity_frame["total_equity"].astype(float)` | Reads the (now Decimal-sourced) equity frame and casts to float for pandas/plotting. This is the equity-curve precision-shift surface (see Issues above). |
| `itrader/reporting/frames.py:80-83` | `frame[column] = frame[column].astype(float)` over EQUITY_COLUMNS | Snapshot Decimal money fields serialized to float for stable CSV repr — this is where the oracle equity-curve diff materializes. 08-03 re-freeze covers it. |
| `itrader/portfolio_handler/portfolio.py:463-468` | `to_dict()` snapshot now stores Decimal (`total_market_value`, `total_equity`, `total_unrealised_pnl`, `total_realised_pnl`, `total_pnl`) | Correct end-to-end. Confirm any downstream JSON/serialization consumer of `to_dict()` handles Decimal (no consumer found in-tree on the backtest path; live/JSONB path is D-sql/D-live). |
| `itrader/order_handler/sizing_resolver.py:123` | `equity = self._read_model.total_equity(portfolio_id)` | UNAFFECTED — uses the `PortfolioReadModel.total_equity()` Protocol METHOD (already returns Decimal, portfolio_read_model.py:196), not the Portfolio property. |
| `itrader/core/portfolio_read_model.py:196` | `total_equity(self, portfolio_id) -> Decimal` | UNAFFECTED — already Decimal-typed. |
| `MetricsManager.get_current_metrics()` consumers | money fields now Decimal | No in-tree float-expecting consumer found on the backtest path. 08-02 should grep for callers and confirm none coerces these to float-only. |

**mypy --strict result captured post-retype:** 0 errors.

## Next Phase Readiness
- Decimal cleanup on the result-bearing path is complete and regression-locked by `make test-portfolio` / `make test-orders` plus the new Decimal-type and Decimal-exact-cash tests.
- **Blocker for 08-03:** the golden equity-curve numeric oracle must be re-frozen (`REFREEZE-M5C-DECIMAL`) — `test_oracle_numeric_values` fails by design until then (behavioral identity preserved, final_equity byte-exact).
- **For 08-02:** the fan-out table above lists every Decimal-now-float boundary to sweep; mypy is already clean so this is redundant-cast removal, not error-fixing.

---
*Phase: 08-m5c-cross-validation-final-oracle*
*Completed: 2026-06-08*
