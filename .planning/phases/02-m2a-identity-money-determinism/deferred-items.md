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

## From Plan 02-08 (Gap-Closure Execution) — SURFACED BLOCKER (owner decision required)

### DEF-02-08-A — Gap 3 precision fix shifts numeric oracle past existing D-15 tolerance

- **Discovered during:** Plan 02-08, Task 3 (Gap 3 — CR-03 cash-precision fix + WR-05 Decimal sizing).
- **Status:** **BLOCKER — STOPPED per the plan's GOLDEN-MASTER GUARDRAIL.** The executor did
  NOT re-baseline `test/golden/` and did NOT loosen the D-15 test tolerance. Owner decision
  required (numeric re-baseline is an owner-gated phase-boundary gate per PROJECT.md / CLAUDE.md:
  "the numerical oracle re-baselines at exactly two points — after M2, after M5").
- **What:** All of Task 3's correctness fixes are implemented and pass everything EXCEPT the
  oracle: WR-01/WR-02/WR-03/WR-05 float seams removed; CR-03 precision-preserving cash primitive
  (`CashManager.apply_transaction_delta`) added and routed; 298/299 tests green; `mypy --strict`
  clean (Success, 135 source files). The ONE failure is
  `test_full_backtest_matches_frozen_oracle`.
- **Why it fails:** behavioral identity is fully preserved (134 trades; entry/exit/side/pair
  EXACT). Only numeric columns drift — but MORE than the existing D-15 tolerance allows:
  | column | abs diff | rel diff | D-15 bound |
  |--------|----------|----------|------------|
  | total_bought | ~0.095 | ~1.72e-6 | atol=5e-2, rtol=1e-6 |
  | total_sold | ~0.087 | ~1.72e-6 | atol=5e-2, rtol=1e-6 |
  | positions_value / total_equity (equity) | ~0.06–0.10 | ~1.47e-6 | atol=5e-2, rtol=1e-6 |
  | cash_balance (equity) | ~0.0026 | ~1.8e-5 | atol=5e-2, rtol=1e-6 |
  Both the 5e-2 atol AND the 1e-6 rtol are exceeded on total_bought/total_sold/positions_value/
  total_equity. (Note: pandas `assert_series_equal` applies `rtol` as a strict relative bound; it
  does NOT combine atol+rtol the numpy-`isclose` way — `numpy.isclose` would call these "close",
  but the test as written fails.)
- **Root cause:** the golden was frozen on (a) 2dp-quantized cash (the old setter path) and
  (b) the old float sizing `0.95 * float(cash) / price`. The Gap 3 fixes change BOTH: CR-03 keeps
  full-precision cash on the ledger (golden `cash_balance` is exactly 2dp, e.g. `141.91`; fresh is
  `141.9074...`), and WR-05 sizes in Decimal. Each marginally shifts the compounding quantity; over
  134 trades the relative drift grows past 1e-6. This is the SAME drift class as DEF-02-04-A, but
  ~3.5x larger than the ~2.7e-2 worst case D-15 (atol=5e-2) was sized for.
- **The conflict (why owner decision is required):** the owner's Gap 3 decision mandates the
  precision fix in M2a gap-closure ("stop the precision loss + float seams"), AND the guardrail
  forbids re-baselining the golden (owner-gated), AND the existing D-15 tolerance was sized for the
  smaller 02-04 drift. These three cannot all hold simultaneously once CR-03/WR-05 land. Resolution
  is one of: (1) re-baseline the numeric oracle now (the PROJECT.md "after M2" re-baseline point) —
  owner-gated; (2) widen D-15 atol/rtol to absorb the larger drift (still effectively a re-bless,
  also owner-gated — and would mask future regressions); (3) defer the CR-03 cash-precision portion
  to the M2b/Pattern-E numeric re-baseline plan that DEF-02-04-A already routes to.
- **Executor recommendation:** option (3) is the cleanest under the no-re-baseline guardrail — the
  Pattern E / post-M2 numeric re-baseline plan (already owning DEF-02-04-A) is the natural home to
  land BOTH the 02-04 drift AND the 02-08 CR-03/WR-05 drift and re-freeze the golden in one
  controlled, owner-approved step. The 02-08 code changes are correct and committed; only the
  oracle re-freeze must wait for that gate.
