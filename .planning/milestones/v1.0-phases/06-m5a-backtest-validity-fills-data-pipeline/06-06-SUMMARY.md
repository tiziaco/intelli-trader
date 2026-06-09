---
phase: 06-m5a-backtest-validity-fills-data-pipeline
plan: "06"
subsystem: execution
tags: [matching-engine, simulated-exchange, fill-timing, golden-master, look-ahead, decimal]

# Dependency graph
requires:
  - phase: 06-m5a-backtest-validity-fills-data-pipeline (plan 06-04)
    provides: Decimal matching engine + fee/slippage correctness, 06-04 golden re-freeze
  - phase: 06-m5a-backtest-validity-fills-data-pipeline (plan 06-05)
    provides: CsvPriceStore + BacktestBarFeed run path (PriceHandler deleted)
provides:
  - Single matching path — EVERY validated NEW order (market included) rests in the MatchingEngine book
  - Next-bar-open market fills (D-01/D-13) — order decided at tick T fills at the open of bar T+1tf with FillEvent.time = T+1tf
  - Same-bar bracket rule settled — parent market fill at N+1 open, SL/TP children may trigger against that same bar's high/low (STOP beats LIMIT)
  - Last-bar edge documented + tested — orders decided on the final dataset bar never fill
  - Re-frozen M5a working reference (tests/golden/) with owner-approved expected-diff note (REFREEZE-M5A.md)
  - Pitfall 6 unit lock — gap-up next-open settlement succeeds against decision-close reservation
affects: [phase-7-m5b, phase-8-cross-validation, execution_handler, golden-master]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "One-path matching: SimulatedExchange.on_order routes ALL NEW orders to matching_engine.submit; no immediate-execution branch"
    - "Fill timestamps carry the MATCHING bar's time, never the decision tick"
    - "OrderEvent.price for market orders = decision-price ESTIMATE (pre-trade reservation gate, not a fill ceiling)"
    - "Golden re-freeze discipline: code flip + re-frozen goldens + expected-diff note in ONE commit (D-21), owner-gated (D-23)"

key-files:
  created:
    - tests/golden/REFREEZE-M5A.md
    - tests/unit/portfolio/test_cash_reservations.py
  modified:
    - itrader/execution_handler/exchanges/simulated.py
    - itrader/execution_handler/matching_engine.py
    - itrader/execution_handler/exchanges/base.py
    - itrader/execution_handler/result_objects.py
    - itrader/events_handler/events/order.py
    - itrader/events_handler/events/fill.py
    - tests/golden/trades.csv
    - tests/golden/equity.csv
    - tests/golden/summary.json

key-decisions:
  - "Same-bar bracket rule (Open Question 1, accepted): parent market fill at bar N+1's open does NOT shield SL/TP children — they evaluate against the same bar's high/low; STOP-beats-LIMIT arbitrates double triggers; parent fill emitted before child fills"
  - "Last-bar edge (timing-contract rule 7): orders decided on the final dataset bar never fill — documented, not special-cased"
  - "Owner approved the re-freeze (D-23): 134 trades unchanged, all timestamps +1 bar, final equity 53229.68512642489 -> 53103.01549885479 (-0.238%), no unexplained residual"
  - "Pitfall 6 resolved without Phase 5 changes: gap-up settlement succeeds (funds invariant checks ledger balance, not reservation-adjusted buying power); empirically exercised by trade 122 (+4.25% gap)"

patterns-established:
  - "Result-changing commits are named: every numeric golden change carries an expected-diff note in the same commit"
  - "FillEvent.new_fill accepts an explicit time kwarg so fills are stamped with the matching bar's time"

requirements-completed: [M5-01]

# Metrics
duration: ~2h 30m (across two executor sessions, including D-23 owner checkpoint)
completed: 2026-06-06
---

# Phase 6 Plan 06: Next-Bar-Open Fills + M5a Oracle Re-freeze Summary

**Market orders now rest in the unified MatchingEngine book and fill at the next bar's open (look-ahead-free D-01/D-13 convention); golden reference re-frozen behind owner-approved expected-diff note — the phase's one sanctioned result change, fully attributed in commit fcd516b.**

## Performance

- **Duration:** ~2h 30m across two executor sessions (Task 1 + checkpoint prep in session 1; re-freeze + phase gate in session 2)
- **Started:** 2026-06-06 (session 1)
- **Completed:** 2026-06-06T16:17Z
- **Tasks:** 3/3 (Task 2 was the D-23 blocking human-verify checkpoint — owner typed "approved")
- **Files modified:** 16 (6 source, 7 test, 3 golden + 1 note)

## Accomplishments

- **One matching path:** `SimulatedExchange.on_order` routes every validated NEW order to `matching_engine.submit`; the `execution_timing == "immediate"` branch, the `execution_timing` attribute, and the immediate-fill `execute_order` path are deleted. Pre-trade validation/rejection still runs at on_order time, preserving the FillEvent(REFUSED) reconciliation path.
- **Look-ahead eliminated:** a market order decided at tick T fills at the open of the bar stamped T+1tf, with `FillEvent.time = T+1tf`. The backtest no longer trades on information it could not have had.
- **Matching-rule tests locked:** (a) fill price == next bar's open with Decimal equality and FillEvent.time == next bar time; (b) last-bar orders never fill, book still holds them; (c) same-bar parent fill + child SL trigger + sibling TP OCO cancel in one on_bar; (d) gap-up reservation settle (Pitfall 6).
- **Golden re-freeze (D-21/D-23):** flip + re-frozen `tests/golden/{trades,equity}.csv` + `summary.json` + owner-approved `REFREEZE-M5A.md` landed as ONE commit (`fcd516b`). 134 trades unchanged; all entry/exit timestamps +1 bar exactly; final equity 53229.68512642489 → 53103.01549885479 (−0.238%); zero fee/slippage pinned (D-09).
- **Full phase gate green:** 586 tests passed (including all 3 golden-comparison oracle tests), `mypy --strict` clean (139 files), `make backtest` end-to-end green, determinism double-run byte-identical.

## Task Commits

Per D-21 the plan mandated ONE commit for the entire flip + re-freeze (Tasks 1–3 atomically), not per-task commits:

1. **Tasks 1+3: next-bar-open fills + M5a oracle re-freeze** - `fcd516b` (feat) — routing flip, test updates, re-frozen goldens, owner-approved REFREEZE-M5A.md
2. **Task 2: D-23 owner sign-off** — checkpoint, no commit (owner typed "approved" after reviewing the expected-diff note)

**Plan metadata:** see final docs commit (SUMMARY + REQUIREMENTS)

## Files Created/Modified

- `itrader/execution_handler/exchanges/simulated.py` - on_order routes ALL NEW orders to matching_engine.submit; immediate path deleted
- `itrader/execution_handler/matching_engine.py` - same-bar bracket evaluation order (parent fill before child evaluation); module docstring documents the same-bar bracket rule + last-bar edge
- `itrader/execution_handler/exchanges/base.py` - `execute_order` removed from the AbstractExchange Protocol (method no longer exists on the concrete exchange)
- `itrader/execution_handler/result_objects.py` - DTO adjustments for the deleted immediate path
- `itrader/events_handler/events/order.py` - OrderEvent.price documented as decision-price ESTIMATE (pre-trade gate, not fill ceiling)
- `itrader/events_handler/events/fill.py` - `FillEvent.new_fill` optional `time` kwarg so fills carry the matching bar's time
- `tests/golden/REFREEZE-M5A.md` - owner-approved expected-diff note (what/why/deltas/spot checks/Pitfall 6 finding)
- `tests/golden/{trades.csv,equity.csv,summary.json}` - re-frozen M5a working reference
- `tests/unit/portfolio/test_cash_reservations.py` - new Pitfall 6 gap-up reservation/settlement lock
- `tests/unit/execution/test_matching_engine.py`, `tests/unit/execution/exchanges/test_simulated_exchange.py`, `tests/unit/execution/test_execution_handler.py`, `tests/integration/test_execution_handler_routing.py`, `tests/unit/order/test_stop_limit_orders.py` - same-bar-fill assumptions converted to follow-up-BAR fills (Pitfall 5 inventory)

## Decisions Made

- **Same-bar bracket semantics** (Open Question 1 recommendation accepted): entry at bar N+1's open, children evaluated against that same bar's high/low — real-exchange semantics, matching both Phase 8 reference engines; parent fill processed before child evaluation within one on_bar.
- **Last-bar edge:** not special-cased — orders decided on the final bar simply never match (no next bar exists); documented in the matching_engine module docstring as timing-contract rule 7 and locked by test.
- **Owner approval (D-23 checkpoint):** owner reviewed REFREEZE-M5A.md (trade count 134 unchanged, −0.238% equity delta fully attributed to open-vs-close drift across 134 round trips including genuine gaps, 3 spot-checked trades verified against the raw CSV) and typed "approved".
- **Commit type `feat` not `refactor`:** the plan's example message used `refactor(06-06)`, but this change alters results (the phase's one sanctioned result change) — `feat` per the orchestrator's commit guidance.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Optional `time` kwarg on `FillEvent.new_fill`**
- **Found during:** Task 1 (one matching path)
- **Issue:** The must-have truth requires `FillEvent.time = T+1tf` (the matching bar's time), but the factory stamped fills with the current tick — fills from the book would carry the wrong timestamp
- **Fix:** Added an optional `time` kwarg to `FillEvent.new_fill`; the exchange passes the matching bar's time for book fills
- **Files modified:** itrader/events_handler/events/fill.py, itrader/execution_handler/exchanges/simulated.py
- **Verification:** next-open test asserts FillEvent.time == the follow-up bar time (Decimal/timestamp equality)
- **Committed in:** fcd516b

**2. [Rule 3 - Blocking] Removed `execute_order` from the `AbstractExchange` Protocol**
- **Found during:** Task 1 (deleting the immediate-fill path)
- **Issue:** After deleting `SimulatedExchange.execute_order`, the concrete exchange no longer satisfied the Protocol — mypy --strict structural conformance failure
- **Fix:** Removed `execute_order` from the Protocol in `exchanges/base.py` (no remaining callers — verified)
- **Files modified:** itrader/execution_handler/exchanges/base.py, itrader/execution_handler/result_objects.py
- **Verification:** `make typecheck` clean (139 files)
- **Committed in:** fcd516b

**3. [Rule 1 - Bug] Fixed a same-drain-fill assumption in test_execution_handler.py**
- **Found during:** Task 1 (Pitfall 5 test-inventory conversion)
- **Issue:** One test in `tests/unit/execution/test_execution_handler.py` (outside the plan's listed files) asserted a FillEvent on the same drain as the OrderEvent — invalid under next-bar-open semantics
- **Fix:** Converted it to enqueue a follow-up BAR and assert the fill at that bar's open, consistent with the rest of the Pitfall 5 inventory
- **Files modified:** tests/unit/execution/test_execution_handler.py
- **Verification:** full suite green (586 passed)
- **Committed in:** fcd516b

---

**Total deviations:** 3 auto-fixed (1 missing critical, 1 blocking, 1 bug)
**Impact on plan:** All three were direct consequences of the planned flip (timestamp contract, Protocol conformance, test inventory completeness). No scope creep.

## Issues Encountered

- **Pitfall 6 (gap-up reservation) resolved benignly:** the plan flagged a possible Phase 5 escalation if the cash manager rejected a settlement above the decision-close reservation. No rejection occurs — the funds invariant checks the ledger balance, never reservation-adjusted buying power, and the terminal release frees the exact reserved amount idempotently. Unit-locked in `tests/unit/portfolio/test_cash_reservations.py` and empirically exercised by trade 122 (entered +4.25% above its reserved estimate, settled cleanly). Surfaced in REFREEZE-M5A.md as a FINDING, no behavior change needed.
- **Oracle test pins no literals:** `tests/integration/test_backtest_oracle.py` derives all expectations from `tests/golden/` files, so the re-baseline was purely the file copy — no test-code change needed in Task 3 (its docstrings still narrate the M2b history; left untouched per the plan's "only touch test code if it pins literals").

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- **Phase 6 (M5a) complete:** all 6 plans done; the working reference in `tests/golden/` is trustworthy, look-ahead-free, Decimal-clean, deterministic, and fully attributed.
- **Phase 7 (M5b)** builds on this reference (behavior-preserving against it).
- **Phase 8 still owns the FINAL sanctioned baseline:** this is the M5a working-reference re-freeze, not the program definition-of-done freeze — Phase 8 validates by external cross-validation against `backtesting.py` and `backtrader` (both default to next-bar-open, now like-for-like).
- **Known edge carried forward:** orders decided on the final dataset bar rest unfilled in the book at run end (documented contract, tested) — Phase 8 cross-validation should account for reference engines' identical behavior.

## Self-Check: PASSED

- All created/modified key files verified on disk (goldens, REFREEZE-M5A.md, test_cash_reservations.py)
- Commit `fcd516b` verified in git log (flip + goldens + note atomically, 16 files)
- Full suite 586 passed; mypy --strict clean; determinism double-run byte-identical

---
*Phase: 06-m5a-backtest-validity-fills-data-pipeline*
*Completed: 2026-06-06*
