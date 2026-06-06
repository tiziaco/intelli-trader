---
phase: 05-m4-money-transaction-correctness
plan: 07
subsystem: events / execution / strategy
tags: [decimal, money, events, matching-engine, oracle-gate, d-22, m4-07, m4-08]
requires:
  - "05-04: FillEvents as the only execution output (ExecutionResult deleted)"
  - "05-06: BUY-only check-and-reserve admission gate; commission-estimator seam"
provides:
  - "Decimal-typed SignalEvent/OrderEvent/FillEvent money fields (nine-field inventory)"
  - "to_money as the single float->Decimal crossing at FillEvent construction"
  - "float-internal matching/slippage boundary with Decimal-at-emission contract"
  - "M4-08 phase gate evidence: value-preserving, behavioral oracle unchanged"
affects:
  - any future consumer of event money fields (Decimal, not float)
  - M5a Bar struct (will push Decimal deeper past the float OHLC boundary)
tech-stack:
  added: []
  patterns:
    - "to_money (Decimal(str(x))) at every float->Decimal crossing — D-04 string path"
    - "float-internal execution math, Decimal-at-emission (Pitfall 4 boundary)"
key-files:
  created: []
  modified:
    - itrader/events_handler/events/signal.py
    - itrader/events_handler/events/order.py
    - itrader/events_handler/events/fill.py
    - itrader/execution_handler/exchanges/simulated.py
    - itrader/execution_handler/matching_engine.py
    - itrader/strategy_handler/base.py
    - itrader/strategy_handler/sltp_models/sltp_models.py
    - itrader/strategy_handler/position_sizer/variable_sizer.py
    - itrader/strategy_handler/risk_manager/advanced_risk_manager.py
    - itrader/order_handler/order_manager.py
    - itrader/portfolio_handler/portfolio_handler.py
    - tests/unit/events/test_events.py
    - tests/unit/events/test_order_event_schema.py
    - tests/unit/events/test_fill_event_schema.py
    - tests/unit/execution/test_matching_engine.py
    - tests/unit/execution/exchanges/test_simulated_exchange.py
    - tests/unit/strategy/test_strategy.py
decisions:
  - "D-22 boundary locked as planned: matching/slippage math stays FLOAT internally; conversion happens ONCE at FillEvent construction via to_money — engineered numerically inert (Decimal(str(float)) reproduces exactly what the old float path delivered to the ledger)"
  - "FillEvent.new_fill owns the to_money normalization (accepts Decimal | float); Decimal inputs pass through as identity — callers cannot bypass the D-04 string path"
  - "_emit_fill float-converts BOTH price and quantity on entry so the EXECUTED fill quantity equals to_money(float(entity_qty)) — identical to the old float round-trip (passing the full-precision entity Decimal through would have shifted the ledger numbers)"
  - "portfolio_handler.on_fill / order_manager.on_fill to_money calls KEPT as identity normalization at the domain entry (plan step 6)"
  - "MatchingEngine.modify to_money-normalizes its Decimal args so a legacy float caller still stores Decimal in the book"
metrics:
  duration: "~16 min"
  completed: "2026-06-06"
  tasks: 2
  commits: 2
---

# Phase 5 Plan 07: D-22 Event-Money Decimal Retype + M4-08 Phase Gate Summary

**One-liner:** Signal/Order/Fill event money retyped float→Decimal with to_money-inert boundaries (entity Decimals ride events untouched; execution math stays float internally, converting once at FillEvent construction) — oracle byte-exact at every sub-step, M4-08 gate green.

## What Was Built

### Task 1 — D-22 retype (commits 69000d7 RED, 2ebf081 GREEN)

**Nine-field inventory retyped (M4-07):**
- `SignalEvent.price/stop_loss/take_profit: Decimal`, `quantity: Decimal | None`
- `OrderEvent.price/quantity: Decimal`, `stop_price: Decimal | None`
- `FillEvent.price/quantity/commission: Decimal`

**Boundary conversion points (the engineered-inert design):**

| Crossing | Mechanism | Inertness argument |
|----------|-----------|--------------------|
| Order entity → OrderEvent | pass-through (float() coercion block at order.py:74-75 deleted) | no conversion at all — exact Decimal |
| strategy float close/sl/tp → SignalEvent | `to_money` in `Strategy._generate_signal` | same `Decimal(str(float))` the Order factories produced downstream before |
| Decimal order.price → float matching math | `float(order.price)` once in `MatchingEngine._evaluate` (`trigger`) | float(full Decimal) is the same double the old pre-coerced event float carried |
| float fill price/qty → FillEvent | `to_money` inside `FillEvent.new_fill`; `_emit_fill` float-converts price AND quantity on entry | `to_money(float(x))` == old path's `to_money(fill_event.price)` at the ledger |
| fee model Decimal → FillEvent.commission | pass-through (identity to_money) | golden run pins fees 0 |
| REFUSED/CANCELLED fills | order's own Decimal price/quantity, `commission=Decimal("0")` | never reach the ledger (portfolio settles EXECUTED only) |

### Task 2 — M4-08 phase gate (verification only, no production changes)

**Gate evidence:**
- Full suite: **494 passed** (`poetry run python -m pytest tests/ -q`)
- `mypy --strict`: **Success: no issues found in 135 source files**
- Integration: **10 passed** (oracle + smoke + wiring + execution routing + reservation inertness)
- `git diff --quiet tests/golden/` — **byte-identical**
- Oracle test assertions unmodified this phase: last commit touching `tests/integration/test_backtest_oracle.py` is `54396db` (phase 3)
- Determinism: two consecutive `scripts/run_backtest.py` runs produced identical trades.csv / equity.csv / summary.json; fresh run matches committed golden byte-exact; `final_equity = 53229.68512642488` (the frozen M2b value — **M4 changed no numbers**)

**Deletion audit (all zero across itrader/ + tests/):**
ExecutionResult (only a docstring explaining its deletion in result_objects.py), TransactionContext, TransactionState, apply_transaction_delta, add_pending_order, readerwriterlock, RLock in portfolio_handler/, datetime.now() in cash_manager, nested order dicts (only `get_active_orders` method names — the D-20 predicate API, not containers), concrete PortfolioHandler imports in order/strategy domains.

**Acceptance-criteria greps:**
- `float(order.price)|float(order.quantity)` in events/order.py: **0**
- `commission=0.0|float(commission)` in simulated.py: **0**
- `Decimal(float|Decimal(fill_price` across itrader/: **0 code instances** (2 matches are money.py docstring text prohibiting the pattern)

## Per-Sub-Step Oracle Results

| Sub-step | Oracle |
|----------|--------|
| Event field retype + order.py coercion removal + fill.py to_money + simulated/matching boundary + strategy to_money (single GREEN batch) | byte-exact (2 passed) |
| Test Decimal-exact updates (test_events.py, test_fill_event_schema.py) | byte-exact (2 passed) |
| Full suite + gate | byte-exact; fresh run == committed golden |

No oracle diff was observed at any point — no §E entry required.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Strategy-layer Decimal×float TypeErrors / mypy --strict failures**
- **Found during:** Task 1 (consumer survey after SignalEvent retype)
- **Issue:** `sltp_models.py` (FixedPercentage/Proportional), `variable_sizer.py` (DynamicSizer), and `advanced_risk_manager.py` (RiskManager.check_cash) do arithmetic on signal money with float factors — `Decimal * float` raises TypeError and fails mypy --strict. These modules were not in the plan's file list but are in mypy scope and consume the retyped fields.
- **Fix:** `float(signal.price)` / `float(signal.stop_loss)` / `float(signal.quantity)` coercion at each module's float boundary (these compute in the pre-signal float domain; their outputs re-enter Decimal via to_money at signal construction).
- **Files modified:** itrader/strategy_handler/sltp_models/sltp_models.py, itrader/strategy_handler/position_sizer/variable_sizer.py, itrader/strategy_handler/risk_manager/advanced_risk_manager.py
- **Commit:** 2ebf081

**2. [Rule 1 - Bug-prevention] Pre-existing event tests updated to Decimal-exact assertions**
- **Found during:** Task 1 GREEN verification
- **Issue:** `test_events.py` and `test_fill_event_schema.py::test_executed_values_land_without_mutation` asserted float equality (e.g. `price == 42350.72`) that no longer holds against `Decimal("42350.72")` (float 42350.72 is not exactly representable).
- **Fix:** fixtures/assertions moved to exact-Decimal equality per the plan's test instruction ("assert exact Decimal equality, not pytest.approx").
- **Commit:** 2ebf081

### Out of Scope (documented, not changed)

- `trading_interface.py` (D-live, mypy-ignored) still constructs OrderEvents with float `price=0.0`/`quantity` — runtime-unenforced on a deferred subsystem; the live-mode Decimal cleanup belongs to the D-live milestone.

## Known Stubs

None introduced by this plan.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or trust-boundary schema changes. The threat register's mitigations all landed: T-05-18 (to_money everywhere, `Decimal(float)` grep 0), T-05-19 (float-internal boundary + Decimal-price matching tests), T-05-20 (oracle assertions unmodified, byte-exact-or-stop honored — no diff occurred).

## Commits

| Commit | Type | Description |
|--------|------|-------------|
| 69000d7 | test | failing tests for D-22 Decimal event-money retype (RED) |
| 2ebf081 | feat | retype event money to Decimal with inert boundaries (GREEN) |

## TDD Gate Compliance

RED (`test(05-07)` 69000d7, 10 failing tests verified) → GREEN (`feat(05-07)` 2ebf081, all green). No refactor commit needed.

## Self-Check: PASSED

- itrader/events_handler/events/{signal,order,fill}.py Decimal annotations: FOUND
- Commits 69000d7, 2ebf081: FOUND in git log
- tests/golden/ byte-identical: VERIFIED (`git diff --quiet` exit 0)
- Full suite 494 passed, mypy --strict clean: VERIFIED
