---
phase: 01-m1-ignition-lock-the-oracle
plan: 03
subsystem: ignition-bugfixes (strategy / run-loop / order-sizing)
tags: [sma-macd, iloc, fillna, record-metrics, sizing-seam, fraction-of-cash, ignition]
requires:
  - "01-01: importable backtest path + package-level config re-exports + RED smoke scaffold"
  - "01-02: PriceHandler csv/offline feed (3076 BTCUSD bars, exact CCXT frame shape)"
provides:
  - "SMA_MACD .iloc[-1] label-safe indexing + fillna=False boolean (no FutureWarning hard-error under filterwarnings=error)"
  - "record_metrics iterated per active Portfolio with the bar time (deterministic snapshot, D-12)"
  - "Fraction-of-cash sizing seam in OrderManager._create_primary_order: qty=(0.95*cash)/price (D-08), seam locked to OrderManager (D-09)"
  - "quantity=0 strategy sentinel resolved to a real non-zero order quantity before Order.new_order"
affects:
  - itrader/strategy_handler/SMA_MACD_strategy.py
  - itrader/trading_system/backtest_trading_system.py
  - itrader/order_handler/order_manager.py
tech-stack:
  added: []
  patterns:
    - "Resolve sizing in the order/risk seam (OrderManager), not the strategy or position_sizer (D-09)"
    - "Mutate the in-flight signal's quantity before Order.new_order so the MARKET path (reads signal.quantity internally) carries the resolved size"
    - "Gate the sizing mutation on qty<=0 so explicit caller-supplied quantities pass through unchanged (legacy contract preserved)"
key-files:
  created: []
  modified:
    - itrader/strategy_handler/SMA_MACD_strategy.py
    - itrader/trading_system/backtest_trading_system.py
    - itrader/order_handler/order_manager.py
decisions:
  - "D-03: SMA_MACD params unchanged (short=50/long=100/FAST=6/SLOW=12/WIN=3)"
  - "D-08: qty = (0.95 * available_cash) / price, fractional BTC, 95% buffer"
  - "D-09: sizing seam = OrderManager._create_primary_order, NOT strategy/position_sizer"
  - "Sizing mutation gated on qty<=0 so explicit quantities are preserved (keeps 274 legacy tests green)"
metrics:
  duration: ~13 min
  completed: 2026-06-04
---

# Phase 1 Plan 03: Ignition Bugfixes (Strategy / Run-Loop / Sizing) Summary

Fixed the three runtime/logic ignition bugs that prevented the backtest loop from
completing and from producing real trades: the SMA_MACD label-keyed indexing + truthy-string
`fillna` (M1-04, a FutureWarning that is a hard error under `filterwarnings=["error"]`), the
`record_metrics` wrong-object call (M1-05, an AttributeError on `PortfolioHandler`), and the
stranded `quantity=0` order seam (M1-06, resolved to a fraction-of-cash size in the OrderManager).
After these land the PING->BAR->SIGNAL->ORDER->FILL loop runs per-tick and emits orders with
correct non-zero quantities (e.g. 1.27 / 1.42 BTC at the bar close) — the precondition for the oracle.

## What Was Built

### Task 1 — SMA_MACD .iloc indexing + fillna boolean (M1-04)
- `itrader/strategy_handler/SMA_MACD_strategy.py` (TABS): changed the label-keyed positional
  access `short_sma[-1]`/`long_sma[-1]` to `short_sma.iloc[-1]`/`long_sma.iloc[-1]`. pandas
  emits a `FutureWarning` for positional access on a label-indexed Series, and
  `pyproject.toml`'s `filterwarnings=["error"]` promotes that to a hard exception (Pitfall 3),
  so any test that runs the strategy fails until fixed.
- Changed `ta.trend.MACD(..., fillna='False')` (a truthy STRING — always evaluates truthy,
  so it silently enabled forward-filling) to `fillna=False` (boolean).
- Strategy parameters unchanged (D-03: short=50/long=100/FAST=6/SLOW=12/WIN=3). `pyproject.toml`
  was NOT modified — the FutureWarning is fixed in code, not muted in the ignore list (anti-pattern).

### Task 2 — record_metrics per-Portfolio in the run loop (M1-05)
- `itrader/trading_system/backtest_trading_system.py` (TABS): replaced the broken
  `self.portfolio_handler.record_metrics(ping_event.time)` (PortfolioHandler has no such method
  → AttributeError that aborted every tick) with iteration over
  `self.portfolio_handler.get_active_portfolios()` calling `portfolio.record_metrics(ping_event.time)`.
- The deterministic bar time `ping_event.time` is passed explicitly so `record_snapshot` never
  falls back to its `datetime.now()` default (D-12 determinism). Loop structure otherwise unchanged.

### Task 3 — Fraction-of-cash sizing in OrderManager._create_primary_order (M1-06)
- `itrader/order_handler/order_manager.py` (TABS, matching the `_create_primary_order` body):
  injected sizing before order construction. Fetches
  `portfolio = self.portfolio_handler.get_portfolio(signal_event.portfolio_id)` and computes
  `qty = (0.95 * portfolio.cash) / signal_event.price` (D-08: fraction-of-cash, fractional BTC,
  95% buffer so float/rounding can't overshoot a cash check).
- The computed qty is carried into the in-flight signal via `signal_event.quantity = qty` BEFORE
  `Order.new_order(signal_event, exchange)` — the MARKET path reads `signal.quantity` internally
  (order.py:143). A single mutation covers the MARKET and LIMIT/STOP branches. Safe per RESEARCH
  A5 (SMA_MACD uses only MARKET orders; the signal is consumed immediately and never re-queued).
- Defensive guard: zero/None `signal_event.price` returns an `OperationResult.failure_result`
  instead of dividing by zero (mitigates T-03-02).
- The seam is LOCKED to OrderManager (D-09) — `position_sizer/` and `order.py` are untouched
  (verified by empty `git diff --stat`).

## Verification Results

- `poetry run python -c "from itrader.trading_system.backtest_trading_system import TradingSystem"` — exits 0
- `poetry run python -c "from itrader.order_handler.order_manager import OrderManager"` — exits 0
- Task 1: `grep -c "iloc\[-1\]"` = 4; no `short_sma[-1]`/`long_sma[-1]`; `fillna=False` present, no `fillna='False'`; pyproject untouched; params intact — PASS
- Task 2: `get_active_portfolios` present; `portfolio_handler.record_metrics` gone; `record_metrics(ping_event.time)` present — PASS
- Task 3: `0.95`*cash formula present; `position_sizer/` and `order.py` untouched; defensive price guard present — PASS
- `poetry run pytest test/ --ignore=test/test_smoke -q` — **274 passed** (no legacy regression)
- End-to-end loop trace: 274 signals generated, orders created with correct non-zero quantities
  (1.27 / 1.42 BTC at the bar close prices) — confirming the sizing seam works as designed.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Gate the sizing mutation on qty<=0 to preserve explicit caller quantities**
- **Found during:** Task 3 (legacy `test_on_signal.py` x4 failed: asserted an explicitly-supplied
  `quantity=100.0` flows through, but the unconditional seam overwrote it with 237.5).
- **Issue:** The plan's seam mutated `signal_event.quantity` unconditionally. Four order_handler
  tests supply an explicit non-zero quantity and assert it is preserved end-to-end.
- **Fix:** Gate the resolution on `if not signal_event.quantity or signal_event.quantity <= 0`.
  The strategy emits `quantity=0` (base.py:63, confirmed) so SMA_MACD always sizes; explicit
  quantities are preserved. This honors both the seam intent ("quantity=0 never reaches fills")
  and the existing contract — and keeps the 274-green success criterion.
- **Files modified:** itrader/order_handler/order_manager.py
- **Commit:** 6d04c1c

### Out-of-Scope Discoveries (NOT fixed here — logged to deferred-items.md)

While driving the RED smoke scaffold (Plan 01) forward to validate the seam end-to-end, three
integration blockers and one money-type defect surfaced. Each is outside this plan's three
`files_modified` and belongs to a later plan/milestone; experimental edits made to locate them
were reverted to keep the diff in-scope and the 274 legacy tests green:

- **DEF-01-A (→ M4):** `Position.avg_price` (position.py:81) mixes `float` (avg_sold/quantity)
  with `Decimal` (sell_commission) → `TypeError` once a SELL fill executes. This is exactly the
  Decimal-money-end-to-end / cash-through-CashManager work owned by M4 (#22 Critical).
- **DEF-01-B (→ Plan 04):** end-to-end smoke-green also needs (1) a `csv`→SimulatedExchange
  execution-venue alias, (2) `BTCUSD` in the simulated exchange's `supported_symbols` (default
  preset lists only `*USDT`), and (3) the validator allowing `quantity=0` to reach the seam
  (currently `_validate_quantity_ranges` hard-rejects it and `test_zero_quantity_signal` locks
  that). The plan explicitly defers smoke-green: "confirm in Plan 04".

## Threat Model Compliance

- T-03-01 (Tampering — sizing overshoots cash): mitigated. The 0.95 buffer (D-08) leaves headroom.
- T-03-02 (DoS — price=0/None → ZeroDivisionError stalls loop): mitigated. Defensive guard returns
  a failure OperationResult before division.
- T-03-SC (npm/pip/cargo installs): accept — no package installs.

## Known Stubs

None. The sizing seam computes a real quantity from live portfolio cash and the signal price;
the loop runs and emits non-zero-quantity orders. The remaining smoke-RED state is due to the
documented DEF-01-A money-type defect (M4) and DEF-01-B integration wirings (Plan 04), not a stub.

## Notes for Next Plan

- Plan 04 (oracle capture) must address DEF-01-B to make the smoke/integration run green:
  the `csv`→simulated execution alias, `BTCUSD` supported-symbol, and the validator zero-quantity
  passthrough. It will hit DEF-01-A (Position float/Decimal) unless M4's money work lands first —
  flag for owner sequencing.
- The sizing seam is proven correct at the unit/source level and emits correct quantities in the
  loop trace; only downstream fill-application (money types) and venue/symbol wiring remain.

## Self-Check: PASSED
- FOUND: itrader/strategy_handler/SMA_MACD_strategy.py (modified)
- FOUND: itrader/trading_system/backtest_trading_system.py (modified)
- FOUND: itrader/order_handler/order_manager.py (modified)
- FOUND commit: 8580d83 (Task 1 — .iloc/fillna)
- FOUND commit: f7f5f7e (Task 2 — record_metrics per-Portfolio)
- FOUND commit: 6d04c1c (Task 3 — fraction-of-cash sizing seam)
