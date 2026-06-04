# Phase 02 — Deferred / Out-of-Scope Items (Execution Delta Log)

Items discovered during plan execution that are outside the executing plan's scope.
Per STATE.md policy, new issues go to COVERAGE-INDEX §E with owner approval — never
silently folded into the running plan.

## From Plan 02-04 (Decimal money + UUID entity retype)

### DEF-02-04-A — Golden oracle numeric drift after float→Decimal (numeric re-baseline)

- **Discovered during:** Plan 02-04, Task 2 (portfolio.cash → Decimal, transaction_manager
  round-trip removal).
- **What:** `test/test_integration/test_backtest_oracle.py::test_full_backtest_matches_frozen_oracle`
  fails. The behavioral oracle is fully preserved — 134 trades in both runs, and the
  identity key columns `_TRADE_KEY_COLUMNS = ["entry_date", "exit_date", "side"]` plus
  `pair` are byte-identical. Only **numeric** columns drift by the expected float→Decimal
  precision shift:
  | column | max abs diff |
  |--------|--------------|
  | net_quantity | 1.4e-16 |
  | avg_bought | 5.8e-11 |
  | avg_price / avg_sold | 7.5e-6 |
  | realised_pnl | 7.9e-3 |
  | total_bought | 1.9e-2 |
  | total_sold | 2.7e-2 |
- **Why out of scope for 02-04:** `test_backtest_oracle.py` is NOT in plan 02-04's
  `files_modified`. The fix is **Pattern E** (split identity-EXACT from numeric-TOLERANT,
  `02-PATTERNS.md` §"Pattern E — D-15 oracle test tolerance"), which is assigned to a
  different plan. Additionally, the **numerical oracle re-baseline** is a controlled
  golden-master phase-boundary gate (CLAUDE.md: "the numerical oracle re-baselines at
  exactly two points — after M2, after M5") that requires owner approval; the executor
  must NOT overwrite `test/golden/trades.csv` or regenerate the golden silently.
- **Status:** Deferred to the Pattern E / post-M2 numeric re-baseline plan (owner-gated).
- **Not a regression of behavior:** trade timing, count, side, and pair are exactly
  preserved — this is precisely the intended M2a numeric improvement (exact Decimal money
  replacing accumulated float error).

## From Phase 02 Verification (02-VERIFICATION.md → gaps_found) + Owner Decisions

Verifier scored 2/4 success criteria fully met. Owner chose the **gap-closure plan** path
(`/gsd:plan-phase 02 --gaps`) to resolve the gaps before Phase 2 is marked complete.

### Gap 1 — BLOCKER (CR-02, SC#4): `BacktestClock.now()` bare-assert guard
- **What:** `core/clock.py:45` guards "not advanced" with `assert self._t is not None`,
  stripped under `python -O` → `now()` returns `None` instead of raising.
- **Owner decision:** FIX in the gap-closure plan. Replace the assert with an explicit
  `raise RuntimeError(...)` and update `test_backtest_clock_now_before_advance_raises`
  to expect `RuntimeError`.
- **Scope:** M2a gap-closure.

### Gap 2 — WARNING (CR-01, SC#4): injected clock has no domain consumers
- **What:** `BacktestClock.now()` is constructed + advanced on the engine loop but has zero
  domain consumers (order/transaction/cash/metrics timestamps still call `datetime.now()`).
  The wiring is a recorded M2b deferral (decision D-09/D-10). The defect is that the engine
  docstring (`backtest_trading_system.py:46-51`) makes a FALSE guarantee that engine-path
  consumers read deterministic time.
- **Owner decision (chosen):** ACCEPT the M2b deferral — do NOT pull consumer-wiring forward.
  In the gap-closure plan, ONLY correct the false docstring so it accurately states the
  clock seam is staged and consumer-wiring lands in Phase 3 / M2b (SC2). Result determinism
  already holds via `record_metrics(ping_event.time)`.
- **Scope:** M2a gap-closure (docstring only); consumer-wiring stays Phase 3 / M2b.

### Gap 3 — WARNING (CR-03, SC#2): cash setter quantization + float re-introductions
- **What:** `transaction_manager._execute_transaction` does `self.portfolio.cash += cost`,
  routing through the cash setter → `deposit/withdraw` → `_validate_and_convert_amount`,
  which quantizes every cost to 2dp (drops sub-cent precision; sub-cent BTC amounts RAISE
  `InvalidTransactionError` from inside the setter). Plus redundant `Decimal(str(...))`
  round-trips on already-Decimal fields, and float re-introductions WR-01 (`float(tolerance)`),
  WR-02 (`1e-6` literal vs Decimal), WR-05 (`float(portfolio.cash)` for order sizing).
- **Owner decision (split scope):**
  - **M2a gap-closure scope:** remove the SC#2-violating float round-trips (WR-01/WR-02/WR-05)
    and the sub-cent precision drop / setter-raises-on-cost behavior, since "Decimal
    end-to-end, no float round-trips" is an M2a success criterion.
  - **Phase 5 / M4 scope:** the deeper structural "cash routed through CashManager / atomic
    transactions" rework (Phase 5: "M4 — Money & Transaction Correctness") owns the
    cash-setter routing redesign. Do NOT attempt the full structural redesign in M2a
    gap-closure — only stop the precision loss + float seams.
