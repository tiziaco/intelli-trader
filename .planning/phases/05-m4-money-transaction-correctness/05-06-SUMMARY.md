---
phase: 05-m4-money-transaction-correctness
plan: 06
subsystem: order_handler
tags: [reservation, cash-manager, admission-gate, tdd, golden-master]
requires:
  - 05-01 (flat-dict InMemoryOrderStorage, facade->manager->storage layering)
  - 05-03 (PortfolioReadModel Protocol with reserve/release, per-reference CashManager reservations)
  - 05-05 (validate-first settlement; balance-based assert_funds_invariant)
provides:
  - Synchronous check-and-reserve admission gate in OrderManager.process_signal (BUY-only)
  - Injected commission estimator seam (Callable[[Decimal, Decimal], Decimal]) wired in both trading systems
  - Idempotent reservation release on every terminal reconciliation in OrderManager.on_fill
  - D-14 golden-run inertness trace (tests/integration/test_reservation_inertness.py)
affects:
  - order admission path (SIGNAL -> ORDER now gated by reservation)
  - available_balance semantics (now diverges from balance while an order is in flight)
tech-stack:
  added: []
  patterns:
    - injected-estimator adapter over exchange fee model (no cross-boundary import)
    - instance-attribute method wrapping for trace probes in integration tests
key-files:
  created:
    - tests/integration/test_reservation_inertness.py
  modified:
    - itrader/order_handler/order_manager.py
    - itrader/order_handler/order_handler.py
    - itrader/trading_system/backtest_trading_system.py
    - itrader/trading_system/live_trading_system.py
    - tests/unit/order/test_order_manager.py
decisions:
  - "05-06: estimator wiring shape — adapter closure over the SimulatedExchange instance reading fee_model at CALL time (survives update_config fee-model rebuilds); isinstance-guarded so a missing/non-simulated exchange degrades to Decimal(0)"
  - "05-06: OQ2 confirmed — release lives in OrderManager.on_fill (the reserver owns the release), uniform idempotent release on FILLED/CANCELLED/REJECTED; Transaction carries no order_id"
  - "05-06: BUY gate keyed on primary.action == Side.BUY.value (entity action stays str; enum referenced, no magic literal)"
metrics:
  duration: ~25 min
  completed: 2026-06-06
  tasks: 2
  commits: 5
---

# Phase 5 Plan 06: Reservation Lifecycle on the Trade Path Summary

Synchronous BUY-only check-and-reserve at order admission (price x quantity + injected commission estimate) with audited REJECTED on shortfall, idempotent release on every terminal fill reconciliation, proven inert on the golden run by a D-14 trace (reserve never rejects, reserved == 0 post-run, trade log byte-identical).

## What Was Built

**Task 1 — Admission gate + commission estimator (D-02/D-03/D-04):**
- `OrderManager` gained `commission_estimator: Optional[Callable[[Decimal, Decimal], Decimal]]` (quantity, price) -> Decimal; `None` -> `Decimal("0")`, reproducing the pre-reservation funds-check math exactly.
- `process_signal`: after validation passes and before bracket assembly, a BUY primary reserves `primary.price * primary.quantity + self._estimate_commission(primary)` via `self.portfolio_handler.reserve(...)` (the 05-03 Protocol member). Decimal-native, no intermediate quantization.
- `InsufficientFundsError` -> audited `PENDING->REJECTED` via `add_state_change(..., triggered_by="cash_reservation")`, persisted to storage, failure `OperationResult`, **nothing emitted** (T-05-16).
- SELLs and bracket SL/TP children never pass the gate (D-03 — no OCO double-reservation, T-05-15). The gate sits before `_assemble_bracket_and_emit`, so children are structurally exempt; a unit test locks it.
- Wiring: `OrderHandler` forwards the estimator; `TradingSystem`/`LiveTradingSystem` construct `ExecutionHandler` BEFORE `OrderHandler` and inject an adapter closure over the simulated exchange's `fee_model.calculate_fee(quantity, price, side="buy", order_type="market")` — `fee_model` read at call time so `update_config` rebuilds are honored. `order_manager.py` has zero `itrader.execution_handler` imports (RESEARCH Pattern 1).

**Task 2 — Terminal release + D-14 inertness trace (D-01/OQ2/D-14):**
- `OrderManager.on_fill`: after the terminal-status branch resolves and the mirror is updated, `self.portfolio_handler.release(portfolio_id, order.id)` — uniform across EXECUTED/CANCELLED/REFUSED reconciliations, idempotent no-op for never-reserved orders. Settlement-debit ordering is irrelevant because the 05-05 invariant guard checks `balance`, never `available_balance` (T-05-17).
- `tests/integration/test_reservation_inertness.py`: runs the pinned golden backtest (constants imported from `scripts/run_backtest.py`) with `PortfolioHandler.reserve` instance-wrapped to record `(amount, available_balance)` pairs.

## Inertness Trace Numbers (D-14)

| Probe | Value |
|-------|-------|
| reserve calls over the golden run | 137 |
| max(amount / available) at call time | 0.95000000000000000000000000 (exactly the sizing fraction) |
| min headroom (available - amount) | $134.857930... |
| reserved_balance post-run | 0.00 |
| closed trades | 134 (identical to tests/golden/trades.csv) |

The gate provably never rejects on the golden path: sizing is 0.95 x available cash with fees 0, so every reservation is exactly 95% of available at the instant of the call, and every reservation is fully released at the fill before the next admission.

## Verification

- `poetry run pytest tests/` — 481 passed (88 in tests/unit/order)
- `poetry run pytest tests/integration/test_backtest_oracle.py` — byte-exact, both layers (behavioral + numeric), assertions untouched
- `poetry run pytest tests/integration/test_reservation_inertness.py` — 3 passed (never-rejects, reserved==0, trade-log identity)
- `poetry run mypy itrader` — `--strict` clean, 135 files
- `git diff --stat tests/golden/` — empty (golden never regenerated)
- Acceptance greps: BUY-guarded `.reserve(` present; `triggered_by="cash_reservation"` + `OrderStatus.REJECTED` in the failure path; zero cross-boundary imports

Note: verification ran via `poetry run python -m pytest` / `poetry run mypy itrader` (the underlying `make test`/`make typecheck` commands — `make` targets are unusable in worktrees due to the gitignored `.env`).

## Commits

| Hash | Type | Description |
|------|------|-------------|
| fe3b7d5 | test | RED: failing admission reservation-gate tests (5) |
| 0213634 | feat | GREEN: check-and-reserve gate + commission-estimator wiring |
| 7203001 | test | RED: failing terminal-release tests (4) |
| 414000c | feat | GREEN: idempotent release on every terminal reconciliation |
| 511adaf | test | D-14 golden-run inertness trace |

## Deviations from Plan

None - plan executed exactly as written. (One planner-anticipated nuance resolved in plan's favor: RESEARCH flagged a possible 2dp quantize on `reserve_cash`, but plan 05-03 already ships the full-precision reserve path, so no adjustment was needed.)

## Known Stubs

None.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or trust-boundary schema changes beyond the plan's sanctioned sync Protocol crossing (signal admission -> cash reservation), which the threat model already registers as mitigated (T-05-14..T-05-17).

## TDD Gate Compliance

Both tasks followed RED -> GREEN: test commits fe3b7d5/7203001 precede feat commits 0213634/414000c respectively. No refactor commits needed.

## M4-01 Status

Closed: every trade now routes cash through CashManager — reservation gate at admission (this plan), full-precision settlement debit/credit (05-05), live ledger/reservations/audit (05-03). No setter bypass exists.

## Self-Check: PASSED

All 6 commits verified on the worktree branch; created files exist; no tracked-file deletions vs base 1c4862f; working tree clean; STATE.md/ROADMAP.md untouched.
