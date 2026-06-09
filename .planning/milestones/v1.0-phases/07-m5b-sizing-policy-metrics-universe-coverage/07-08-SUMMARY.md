---
phase: 07-m5b-sizing-policy-metrics-universe-coverage
plan: 08
subsystem: order-admission
tags: [d-10, d-11, allow-increase, max-positions, golden-refreeze, check-and-reserve, owner-gated, m5-06, phase-gate]
requires:
  - "07-07 (the direction gate _enforce_direction_admission and the re-freeze-1 long-only baseline the new gates extend; the test_admission_rules.py harness)"
  - "Phase 5 check-and-reserve gate (the allow_increase=True path's cash coverage — M5-06 check_cash; no new reservation code)"
provides:
  - "D-10 increase admission gate (_enforce_position_admission, step 0b of process_signal): unsized BUY-while-long with allow_increase=False -> audited REJECTED, triggered_by='admission_increase'; allow_increase=True sizes by policy on CURRENT remaining available_cash through the existing check-and-reserve gate"
  - "max_positions admission gate (oracle-dark, new-position entries only): unsized new-ticker BUY at the open-position limit -> audited REJECTED, triggered_by='admission_max_positions'"
  - "M5b re-freeze 2 (final numeric change of Phase 7): N=3 rejected increases, 134 trades identical keys, final equity 46189.87730727451, owner-approved expected-diff in tests/golden/REFREEZE-M5B-INCREASE.md"
  - "Green phase gate: 711 tests, mypy --strict clean, make backtest, determinism double-run byte-identical — the M5b working reference Phase 8 starts from"
affects:
  - "Phase 8 (cross-validation + FINAL sanctioned baseline — this is the M5b working reference, long-only and non-pyramiding, that it validates against backtesting.py and backtrader)"
tech-stack:
  added: []
  patterns:
    - "Owner-gated result-changing re-freeze (D-21/D-23): blocking human checkpoint before commit; guards + tests + goldens + note land as ONE atomic commit"
    - "Disjoint admission gates dispatching on position state: direction -> max_positions -> increase; the increase case is an OPEN ticker, the max_positions case is a NEW ticker, so a signal trips at most one gate"
key-files:
  created:
    - tests/golden/REFREEZE-M5B-INCREASE.md
  modified:
    - itrader/order_handler/order_manager.py
    - tests/unit/order/test_admission_rules.py
    - tests/golden/trades.csv
    - tests/golden/equity.csv
    - tests/golden/summary.json
decisions:
  - "Increase gate placement is step 0b of process_signal — after the 07-07 direction gate, BEFORE sizing — in the same audited-rejection shape (entity persisted at the gate, Pitfall 5 option (a))"
  - "FractionOfCash on an allow_increase=True increase reads CURRENT available_cash — that IS 'fraction of remaining available cash' semantics (CONTEXT discretion clause, documented inline; oracle-dark since the golden strategy declares False)"
  - "max_positions polices NEW-position entries only (discretion exercised: sibling strategy field); a BUY for the already-open ticker is the increase case — no double-gating"
  - "BUY against an open short is a cover/exit — neither gate applies (short increases out of v1 scope with the margin model, D-09)"
  - "Explicit-quantity signals skip both gates (preserved live/manual TradingInterface path); first entries under the limit size EXACTLY as before"
  - "tests/integration/test_backtest_oracle.py untouched: it has no pinned numeric literals — identity and numeric assertions derive from the golden files, so the re-freeze moves it automatically"
metrics:
  duration: "~50 min across two executor sessions (owner-gated D-23 checkpoint between Task 2 and Task 3)"
  completed: "2026-06-08"
  tasks: 3
  tests-added: 8
---

# Phase 7 Plan 08: allow_increase + max_positions Admission Guards + M5b Re-freeze 2 Summary

M5-06 is fully delivered: `_enforce_position_admission` (step 0b of `process_signal`) makes SMA_MACD's declared-but-ignored `allow_increase=False` finally honest — the golden run's 3 unsized BUY-while-long signals are now audited REJECTED orders (`triggered_by="admission_increase"`) instead of silently pyramiding 95% of remaining cash, and the owner-approved re-freeze 2 moves final equity 46132.7668 → 46189.8773 (+0.124%) on 134 identity-unchanged trades, closing Phase 7 with a green full gate.

## Tasks Completed

| Task | Name | Commits | Key Files |
|------|------|---------|-----------|
| 1 | Increase + max_positions admission guards + 8 unit tests (implemented, held uncommitted per D-21) | 5095baf | itrader/order_handler/order_manager.py, tests/unit/order/test_admission_rules.py |
| 2 | Owner sign-off on the increase-enforcement expected-diff note (D-23 blocking checkpoint) | 5095baf | tests/golden/REFREEZE-M5B-INCREASE.md |
| 3 | ONE-commit re-freeze 2 + full phase gate | 5095baf | tests/golden/{trades,equity}.csv, tests/golden/summary.json |

All three tasks land in the single commit `5095baf` by design — D-21 one-commit discipline for result-changing re-freezes. The owner typed "approved" at the D-23 checkpoint; the note's status line records it.

## What Was Built

**Position admission gates (`order_manager.py`, tabs):** `_enforce_position_admission` runs as step 0b of `process_signal` — after the 07-07 direction gate, BEFORE the SizingResolver. It polices unsized BUYs only and dispatches on position state, so the cases are disjoint and a signal trips at most ONE gate:

- **INCREASE case (D-10)** — open long for the ticker (`net_quantity > 0`): `allow_increase=False` persists an audited REJECTED entity (`triggered_by="admission_increase"`, reason "position increase not allowed by strategy", event-derived timestamp) via the established `_reject_unsized_signal` shape and short-circuits. `allow_increase=True` falls through to entry sizing: the resolver's FractionOfCash arm reads CURRENT `available_cash` (documented inline as the "remaining cash" semantics of the CONTEXT discretion clause) and the existing Phase 5 check-and-reserve gate covers the cash check — the literal M5-06 check_cash-covers-increases requirement, with zero new reservation code; insufficient funds still yields the audited `cash_reservation` rejection (T-07-21).
- **NEW-POSITION case (max_positions, oracle-dark)** — no open position for the ticker: when `open_position_count(portfolio_id) >= signal.max_positions`, the entry is audited REJECTED (`triggered_by="admission_max_positions"`). The golden run is single-ticker with `max_positions=1` and at most one open position, so the gate tripped ZERO times — confirmed in the note.
- **Preserved paths:** BUY against an open short is a cover/exit (neither gate applies); first entries under the limit size EXACTLY as before (byte-exactness of the no-position path verified by a str-equal quantity test); explicit-quantity signals skip both gates; SELLs pass through.

**Re-frozen goldens (M5b re-freeze 2, owner-approved):** `tests/golden/{trades.csv,equity.csv,summary.json}` regenerated from the guarded run. N=3 rejected increases (decision bars 2022-04-15, 2024-10-28, 2025-05-20 — each had deployed 95% of then-remaining cash into an already-open long). Trade count holds at 134 with every trade keeping its identity (the behavioral oracle passes WITHOUT regeneration — increases resized positions, never opened/closed trades); 0 SHORT rows as re-freeze 1 left it. The 3 increase-containing trades lose their second fill (avg_price reverts to the pure entry price; D-17 slippage_entry collapses to the plain next-open gap), and fraction-of-cash compounding shifts the 64 downstream trades — net +57.11 final equity (+0.124%), `win_rate` exactly unchanged at 0.3656716417910448 (identical trade keys, unchanged win/loss signs). Full attribution with no unexplained residual in `tests/golden/REFREEZE-M5B-INCREASE.md`, including the ±1-ULP Decimal repr artifacts on 9 single-fill trades.

**Tests (8 new, 15 total in `tests/unit/order/test_admission_rules.py`, spaces, auto-marked unit):** False-rejects-increase (audited entity), True-sizes-on-remaining-cash-and-reserves, insufficient-funds-increase yields the `cash_reservation` rejection, first-entry untouched (quantity str-equal), max_positions rejects a new-ticker entry at the limit (multi-ticker harness portfolio), under-the-limit entry passes, open-ticker BUY is the increase case not max_positions (no double-gating), explicit-quantity BUY skips both gates.

## Verification Evidence

- `make test`: **711 passed** (703 prior + 8 admission tests) against the re-frozen reference
- `make typecheck` (mypy --strict): Success, no issues in 129 source files
- `make backtest`: runs end-to-end, prints the D-14 end-of-run metrics block
- Oracle: `tests/integration/test_backtest_oracle.py` — 2 passed (behavioral identity holds without regeneration; numeric EXACT against the new goldens). No pinned literals needed to move — the test derives all assertions from the golden files
- Determinism: two consecutive `scripts/run_backtest.py` runs byte-identical (`diff -r` clean); regenerated output byte-identical to the committed goldens
- Atomicity: `git log -1 --name-only` on `5095baf` shows order_manager.py, test_admission_rules.py, all 3 goldens, and REFREEZE-M5B-INCREASE.md in the SAME commit
- The note states N explicitly (N=3 increases; 0 max_positions rejections) with old→new headline numbers and the frozen D-15 metrics block old→new
- Owner approval: granted at the D-23 blocking checkpoint ("approved"), recorded in the note's status line
- Phase history now carries exactly two named, owner-approved numeric changes: REFREEZE-M5B-DIRECTION.md (07-07) and REFREEZE-M5B-INCREASE.md (07-08) — D-11 satisfied

## Scope Note for Phase 8

Phase 8 owns the FINAL sanctioned baseline (external cross-validation against `backtesting.py` and `backtrader`, then the final freeze). This re-freeze is the M5b **working reference** Phase 8 starts from: long-only (re-freeze 1), non-pyramiding (re-freeze 2) — matching the default broker semantics of both cross-validation frameworks.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Worktree environment handling (carried from 07-01/07-05/07-06/07-07)**
- **Issue:** Worktree venv resolves `itrader` to the main checkout; `make` targets require a `.env` (Makefile `include .env`)
- **Fix:** All test/gate runs use `PYTHONPATH="$PWD"`; empty gitignored `.env` created locally in the worktree. No repo files changed
- **Commit:** n/a

No other deviations — the plan executed as written.

## TDD Gate Compliance

Task 1 carried `tdd="true"` but the plan's D-21 one-commit discipline overrides the per-task RED/GREEN commit cadence: the unit tests and the oracle-RED evidence (the post-direction reference contained 3 increases, so the numeric oracle was RED in the working tree after the guard landed) were held uncommitted until the owner-gated re-freeze, then landed atomically in `5095baf`. The RED→GREEN sequence was executed and verified in the working tree; it is intentionally not visible as separate commits.

## Known Stubs

None — no placeholder values, no unwired data paths introduced.

## Threat Flags

None — no new network endpoints, auth paths, file-access patterns, or trust-boundary schema changes beyond the plan's threat model. T-07-20 (unattributed oracle drift) mitigated via the one-commit + owner-checkpoint + N=3 fully attributed; T-07-21 (reservation bypass on increases) mitigated by the unit-locked check-and-reserve flow and the insufficient-funds rejection test; T-07-22 (over-rejection) mitigated by the first-entry/explicit-quantity/under-the-limit pass-path tests.

## Self-Check: PASSED

All 6 commit files exist on disk; commit 5095baf present on worktree-agent-a44c9f633ac98185b; `admission_increase` and `admission_max_positions` grep-confirmed in order_manager.py; note status line reads APPROVED.
