---
phase: 08-m5c-cross-validation-final-oracle
plan: 09
subsystem: golden-oracle
tags: [oracle, freeze, definition-of-done, cross-validation, terminal, program-close]
requires:
  - "tests/golden/* frozen oracle (08-03 Decimal re-freeze, byte-unchanged through 08-08)"
  - "tests/golden/CROSS-VALIDATION.md cross-validation evidence (08-07/08-08, owner-approved)"
provides:
  - "tests/golden/FINAL-ORACLE.md — terminal freeze declaration (D-11) + D-13 DoD evidence block + owner sign-off"
  - "Program-level definition of done verified GREEN against the frozen oracle"
affects:
  - "Closes the iTrader Backtest-Correctness Refactor program (M5-10 satisfied end-to-end)"
tech-stack:
  added: []
  patterns:
    - "Golden-master terminal freeze: owner sign-off recorded on the final oracle before close"
key-files:
  created:
    - "tests/golden/FINAL-ORACLE.md (08-09 Task 2; sign-off recorded Task 3)"
    - ".planning/phases/08-m5c-cross-validation-final-oracle/08-09-SUMMARY.md"
  modified: []
decisions:
  - "Owner approved the final oracle freeze at the 08-09 terminal human-verify checkpoint (2026-06-08); no re-freeze, golden artifacts byte-unchanged"
  - "D-13 definition-of-done verified GREEN on all 8 checks against the frozen oracle (134 trades / final_equity 46189.87730727451 / 3076 equity points; mypy clean 151 files; 724 tests pass under filterwarnings=['error']; integration gate byte-exact)"
metrics:
  duration: "~6 min (continuation: Task 3 + program close)"
  completed: 2026-06-08
---

# Phase 8 Plan 9: Cross-Validation & Final Oracle Freeze Summary

Terminal plan of the iTrader Backtest-Correctness Refactor: recorded the project owner's
APPROVED sign-off in `tests/golden/FINAL-ORACLE.md`, freezing the final authoritative numerical
oracle and closing the program — no code change, no re-freeze, golden artifacts byte-unchanged.

## What This Plan Did

This was executed across two executor sessions:

- **Task 1 (prior session)** — ran the full D-13 definition-of-done command gate; all 8 checks GREEN.
- **Task 2 (prior session, commit a34ea32)** — authored `tests/golden/FINAL-ORACLE.md`: the D-11
  final-oracle declaration, frozen values, M5-C lineage, cross-validation reference (D-10), and the
  D-13 DoD evidence block.
- **Task 3 — terminal checkpoint (this session)** — the blocking human-verify checkpoint was
  APPROVED by the owner. Recorded the sign-off in FINAL-ORACLE.md §6, freezing the final oracle and
  closing the program. Commit `aec6575`.

## D-13 Definition-of-Done Evidence (all GREEN, verified against the frozen oracle)

| # | Criterion | Result |
|---|-----------|--------|
| 1 | End-to-end `make backtest` | 134 trades / final_equity 46189.87730727451 / 3076 equity points |
| 2 | `make typecheck` (mypy --strict) | clean, 151 source files, exit 0 |
| 3 | No float money on golden path | Portfolio.total_* return Decimal; residual float() only on derived ratio inputs |
| 4 | Single UUIDv7 scheme | idgen/uuid-utils only; sole uuid4 hit is non-result-bearing correlation id |
| 5 | Determinism | two runs byte-identical |
| 6 | Full live suite | 724 collected / 724 passed under filterwarnings=["error"] |
| 7 | Run-path integration test | byte-exact frame-equal vs frozen golden, passes |
| 8 | Cross-validation evidence | CROSS-VALIDATION.md present with per-divergence root-cause dispositions |

## Frozen Final Oracle

`tests/golden/{summary.json, trades.csv, equity.csv}` — declared the FINAL authoritative numerical
oracle (D-11). 134 trades, final_equity 46189.87730727451, run window 2018-01-01 → 2026-06-03,
BTCUSD 1d, $10,000 starting cash. No further re-baseline is sanctioned.

## Owner Sign-Off

> Owner: tiziaco   Date: 2026-06-08   Signal: "approved"

The owner reviewed the FINAL-ORACLE declaration and the D-13 evidence block at the terminal
human-verify checkpoint and approved. This freezes the final oracle and closes the program.

## Deviations from Plan

None — Task 3 executed exactly as the plan specifies. No code change, no re-freeze; only
FINAL-ORACLE.md §6 was edited to record the sign-off. Golden artifacts (summary.json, trades.csv,
equity.csv) remained byte-unchanged.

## Program Close

M5-10 is satisfied end-to-end: cross-validated (08-07/08-08) + final numerical reference frozen
(this plan). The iTrader Backtest-Correctness Refactor program is complete — the backtest path is
correct, deterministic, type-clean, Decimal-money, single-UUID-scheme, and regression-locked by the
byte-exact run-path integration gate.

## Commits

- `aec6575` — docs(08-09): record owner sign-off — final oracle FROZEN, program CLOSED
- `a34ea32` (prior session) — docs(08-09): declare final authoritative oracle (D-11) + D-13 DoD evidence

## Self-Check: PASSED

- tests/golden/FINAL-ORACLE.md — FOUND, sign-off recorded
- .planning/phases/08-m5c-cross-validation-final-oracle/08-09-SUMMARY.md — FOUND
- Commit aec6575 — FOUND
- Commit a34ea32 — FOUND
