---
phase: 02-m2a-identity-money-determinism
plan: 08
subsystem: portfolio/order/clock money-and-determinism gap-closure
tags: [decimal-money, determinism, clock-guard, golden-master, gap-closure]
status: blocked-owner-decision
requires: ["02-01", "02-02", "02-03", "02-04", "02-05", "02-06", "02-07"]
provides:
  - "BacktestClock.now() RuntimeError guard (python -O safe)"
  - "Honest engine clock docstring (seam staged, no domain consumer)"
  - "CashManager.apply_transaction_delta precision-preserving ledger primitive"
  - "Float-seam-free Decimal money path (WR-01/02/03/05 closed)"
affects:
  - itrader/core/clock.py
  - itrader/trading_system/backtest_trading_system.py
  - itrader/portfolio_handler/cash_manager.py
  - itrader/portfolio_handler/transaction_manager.py
  - itrader/portfolio_handler/position_manager.py
  - itrader/order_handler/order_manager.py
tech-stack:
  added: []
  patterns:
    - "Precision-preserving signed-delta cash primitive (bypasses 2dp quantize + policy gate; funds check done upstream)"
    - "Decimal-intermediate / float-at-boundary order sizing (D-01: quantize only at money boundaries)"
key-files:
  created: []
  modified:
    - itrader/core/clock.py
    - test/test_core/test_clock.py
    - itrader/trading_system/backtest_trading_system.py
    - itrader/portfolio_handler/cash_manager.py
    - itrader/portfolio_handler/transaction_manager.py
    - itrader/portfolio_handler/position_manager.py
    - itrader/order_handler/order_manager.py
    - test/test_portfolio_handler/test_transaction_manager.py
    - .planning/phases/02-m2a-identity-money-determinism/deferred-items.md
decisions:
  - "Did NOT re-baseline the golden master — STOPPED per the GOLDEN-MASTER GUARDRAIL; numeric re-baseline is owner-gated."
  - "Did NOT quantize the order-sizing quantity to 8dp — D-01 forbids quantizing an intermediate; the sized qty is an in-flight value, not a money-ledger boundary."
metrics:
  duration: "~22 min"
  completed: "2026-06-04T21:08:41Z"
  commits: 3
  tasks_completed: 3
  tests_passing: "298/299 (oracle blocked — see below)"
---

# Phase 02 Plan 08: M2a Gap-Closure (clock guard + honest docstring + Decimal money path) Summary

Closed the determinism-guard and float-seam gaps end-to-end (clock `RuntimeError` guard that
survives `python -O`, honest engine clock docstring, and a Decimal-end-to-end money path with a
precision-preserving cash primitive) — but the Gap 3 precision fix shifts the numeric oracle past
the existing D-15 tolerance, which is an **owner-gated re-baseline boundary**, so per the plan's
GOLDEN-MASTER GUARDRAIL the executor STOPPED rather than re-bless the golden.

## Status: BLOCKED — owner decision required (numeric re-baseline)

3/3 tasks implemented and committed. SC#1, SC#2, SC#3, SC#5 are met. SC#4 (oracle passes under
existing D-15, golden untouched) cannot be met without an owner-gated numeric re-baseline — the
golden was deliberately left untouched. See **DEF-02-08-A** in `deferred-items.md`.

## Tasks

### Task 1 — Gap 1: BacktestClock.now() guard survives `python -O` (commit e12ebed)
- Replaced `assert self._t is not None` with explicit `if self._t is None: raise RuntimeError(...)`.
- Updated module + class docstrings: `now()` "raises" (not "asserts"); noted it survives `python -O`.
- Updated `test_backtest_clock_now_before_advance_raises` to expect `RuntimeError`.
- Verified: `grep "raise RuntimeError"` hits; no `assert self._t`; `python -O` exits non-zero with
  `RuntimeError`; `test/test_core/test_clock.py` 3/3 green.

### Task 2 — Gap 2: correct false engine clock docstring (DOCSTRING ONLY) (commit e83219b)
- Corrected BOTH comment sites (constructor block + run-loop advance) in
  `backtest_trading_system.py`: the seam is constructed + advanced every ping but has NO domain
  consumer (`clock.now()` read nowhere); consumer-wiring is Phase 3 / M2b (D-09/D-10); result
  determinism holds via explicit `ping_event.time` to `record_metrics`, not via `clock.now()`.
- Removed the false "any engine-path consumer of 'now' reads deterministic time" claim from both.
- `self.clock = BacktestClock()` and `self.clock.set_time(ping_event.time)` preserved unchanged.
- Verified: false phrase gone; staged seam present; `M2b`/`Phase 3`/`no domain consumer` markers
  present; `git diff` shows only comment lines changed.

### Task 3 — Gap 3: remove float re-introductions + stop sub-cent cash precision loss (commit 5aa7f1a)
- **WR-03** — `transaction_manager._calculate_transaction_cost`: dropped redundant
  `Decimal(str(transaction.price/quantity/commission))` round-trips; operates on the already-Decimal
  fields directly. BUY/SELL sign logic unchanged.
- **WR-01/WR-02** — `position_manager`: `_should_close_position` now compares
  `abs(position.net_quantity) <= self.tolerance` (Decimal-to-Decimal, no `float()` cast);
  `_validate_position_consistency` compares against `Decimal("0.000001")` (no `1e-6` float literal).
- **WR-05** — `order_manager._resolve_signal_quantity`: sizing computed in Decimal and coerced to
  `float` ONLY at the `signal_event.quantity = ...` assignment (the SignalEvent field stays `float`
  per IN-02/M4). Exit sizes from `open_position.net_quantity` (Decimal); entry computes
  `(Decimal("0.95") * portfolio.cash) / to_money(price)` at full precision. The 0.95 buffer and the
  branch structure are preserved.
  - **Deviation from plan instruction (c):** the plan said to `quantize(qty, ticker, "quantity")`
    the entry quantity to 8dp. I did NOT do this — quantizing an in-flight sizing intermediate
    violates D-01 ("quantize ONLY at money boundaries, never on an intermediate"); the sized qty is
    consumed by the exchange, not written to the money ledger. (It also worsens the oracle drift.)
    Decimal arithmetic coerced to float at the boundary is bit-identical to the old float path for a
    single sizing; only multi-trade compounding differs (see blocker).
- **CR-03** — added precision-preserving primitive:

  ```python
  # itrader/portfolio_handler/cash_manager.py
  def apply_transaction_delta(
      self,
      delta: Decimal,
      description: str = "Transaction cash delta",
      reference_id: Optional[str] = None,
  ) -> bool:
  ```

  It adds the signed full-precision Decimal `delta` straight to `_balance` under the lock, records a
  `CashOperation` (TRANSACTION_DEBIT/CREDIT) for the audit trail, and does NOT call
  `_validate_and_convert_amount` (so no 2dp quantize) and does NOT enforce the deposit/withdraw
  min/max-balance gates (the transaction layer already ran `_check_funds_availability`).
  `transaction_manager._execute_transaction` now routes through it instead of the
  `self.portfolio.cash += transaction_cost` setter. No `float(` on the money value added to the
  ledger. The public `deposit`/`withdraw`/`process_transaction_cash_flow` methods and their 2dp
  policy gates are untouched for existing external callers.
- **Test double updated:** `MockPortfolio` in `test_transaction_manager.py` gained a `cash_manager`
  shim (`MockCashManager.apply_transaction_delta`) that applies the full-precision delta to `cash`,
  matching the new production collaborator contract; the Decimal-exact assertions still hold.
- Verified: all four grep gates return NOTHING; `apply_transaction_delta` present;
  `test/test_portfolio_handler/` + `test/test_order_handler/` 188/188 green; full suite 298/299
  green (oracle deselected); `mypy --strict` "Success: no issues found in 135 source files".

## Golden master: UNTOUCHED (no re-baseline)

`git status test/golden/` is clean — `trades.csv`, `equity.csv`, `summary.json` are byte-unchanged.
The numeric re-baseline was NOT performed and the D-15 test tolerance was NOT loosened.

## Oracle result under existing D-15 tolerance: FAIL (owner-gated blocker)

`test_full_backtest_matches_frozen_oracle` FAILS. Behavioral identity is fully preserved — 134
trades; `entry_date`/`exit_date`/`side`/`pair` EXACT; equity timestamp grid EXACT. Only numeric
columns drift, and by MORE than D-15 (`atol=5e-2`, `rtol=1e-6`) permits:

| column | abs diff | rel diff |
|--------|----------|----------|
| trades.total_bought | ~0.095 | ~1.72e-6 |
| trades.total_sold | ~0.087 | ~1.72e-6 |
| equity.positions_value | ~0.099 | ~1.47e-6 |
| equity.total_equity | ~0.063 | ~1.48e-6 |
| equity.cash_balance | ~0.0026 | ~1.8e-5 |

Both the 5e-2 atol AND the 1e-6 rtol are exceeded on the four large-value columns (pandas
`assert_series_equal` applies `rtol` as a strict relative bound; numpy-`isclose` would call these
"close", but the test as written fails). Root cause: the golden was frozen on 2dp-quantized cash
(golden `cash_balance` is exactly `141.91`; fresh is `141.9074...`) and the old float sizing; the
Gap 3 CR-03 + WR-05 fixes change both, and the marginal per-trade shift compounds over 134 trades
past 1e-6. This is the same drift class as DEF-02-04-A, ~3.5x larger than the ~2.7e-2 that D-15 was
sized for.

**Why STOPPED (not auto-resolved):** the numeric oracle re-baseline is an owner-gated phase-boundary
gate (PROJECT.md / CLAUDE.md: "re-baselines at exactly two points — after M2, after M5"). The plan's
GOLDEN-MASTER GUARDRAIL is explicit: "If it does NOT pass under that tolerance, STOP and surface — do
not re-bless the golden." Re-baselining the golden OR widening the test tolerance both constitute an
owner-gated re-bless. This is an architectural/owner decision (Rule 4).

**Resolution options (owner to choose):**
1. Re-baseline the numeric oracle now (the PROJECT.md "after M2" re-baseline point).
2. Widen D-15 atol/rtol to absorb the larger drift (effectively a re-bless; risks masking regressions).
3. Defer the CR-03/WR-05 oracle re-freeze to the Pattern E / post-M2 numeric re-baseline plan that
   DEF-02-04-A already routes to (executor recommendation — lands both 02-04 and 02-08 drift in one
   controlled, owner-approved re-freeze).

Full detail recorded in `deferred-items.md` → **DEF-02-08-A**.

## Deviations from Plan

### Auto-fixed / contract-aligned

**1. [Rule 3 — Blocking] MockPortfolio missing `cash_manager` collaborator**
- **Found during:** Task 3 (routing `_execute_transaction` through the new primitive).
- **Issue:** `MockPortfolio` exposed only a `cash` attribute; the new production contract calls
  `portfolio.cash_manager.apply_transaction_delta(...)`.
- **Fix:** added a `MockCashManager` shim that applies the full-precision delta to `cash`.
- **Files modified:** `test/test_portfolio_handler/test_transaction_manager.py`
- **Commit:** 5aa7f1a

**2. [Plan-deviation — D-01 compliance] Did NOT quantize entry sizing quantity to 8dp**
- Plan instruction (c) asked to quantize the sized quantity; quantizing an in-flight intermediate
  violates D-01 (quantize only at money boundaries). The sized qty is consumed by the exchange, not
  written to the ledger, so it is carried at full Decimal precision and coerced to float at the
  assignment boundary only.
- **Files:** `itrader/order_handler/order_manager.py` — **Commit:** 5aa7f1a

### Surfaced (NOT auto-resolved)

**3. [Rule 4 — Architectural/owner] Numeric oracle re-baseline (DEF-02-08-A)** — see above.

## Self-Check: PASSED

- Files created/modified exist: clock.py, cash_manager.py, transaction_manager.py,
  order_manager.py, 02-08-SUMMARY.md — all FOUND.
- Commits exist: e12ebed, e83219b, 5aa7f1a — all FOUND.
- Golden master `test/golden/` byte-unchanged — confirmed clean.
