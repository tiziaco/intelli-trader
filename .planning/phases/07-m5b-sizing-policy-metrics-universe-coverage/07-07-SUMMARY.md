---
phase: 07-m5b-sizing-policy-metrics-universe-coverage
plan: 07
subsystem: order-admission
tags: [d-08, direction-guard, long-only, golden-refreeze, d-15-metrics, d-17-slippage, owner-gated, def-01-c]
requires:
  - "07-03 (itrader/reporting/metrics — the D-15 metrics block frozen here)"
  - "07-05 (audited-rejection shape: triggered_by-stamped REJECTED entities at admission)"
  - "07-06 (last oracle-inert workstream — all inert work landed before this result-changing re-freeze)"
provides:
  - "D-08 direction admission gate (_enforce_direction_admission) as step 0 of process_signal: unsized LONG_ONLY SELL with no open long -> audited REJECTED, triggered_by='admission_direction'; SHORT_ONLY+BUY symmetric; LONG_SHORT and explicit-quantity signals pass"
  - "M5b re-freeze 1: long-only golden reference (0 SHORT rows, 134 trades, final equity 46132.76684866844) committed atomically with the owner-approved expected-diff note"
  - "Frozen D-15 summary.json metrics block (cagr/max_drawdown/profit_factor/sharpe/sortino/win_rate) asserted as one exact dict comparison in the oracle test"
  - "Frozen D-17 trades.csv slippage_entry/slippage_exit columns, presence-locked and auto-locked EXACT via the golden-derived _trade_numeric mechanic"
  - "tests/unit/order/test_admission_rules.py — 7 direction-guard tests (test-with-code, D-24)"
affects:
  - "07-08 (re-freeze 2: allow_increase / max_positions admission rules — builds on the same admission shape)"
  - "Phase 8 (cross-validates a clean long-only run against backtesting.py and backtrader)"
tech-stack:
  added: []
  patterns:
    - "Owner-gated result-changing re-freeze (D-21/D-23): blocking human checkpoint before commit; code + goldens + note + extended oracle assertions land as ONE atomic commit"
    - "Direction admission gate dispatches on signal.direction (TradingDirection) before sizing — Pitfall 5 option (a): the audited REJECTED entity is persisted at the gate"
key-files:
  created:
    - tests/unit/order/test_admission_rules.py
    - tests/golden/REFREEZE-M5B-DIRECTION.md
  modified:
    - itrader/order_handler/order_manager.py
    - tests/golden/trades.csv
    - tests/golden/equity.csv
    - tests/golden/summary.json
    - tests/integration/test_backtest_oracle.py
    - tests/integration/test_reservation_inertness.py
decisions:
  - "Gate placement is step 0 of process_signal, BEFORE the SizingResolver — the Pitfall-4 fall-through (exit-SELL while flat being fraction-of-cash sized as a short entry) is intercepted before any sizing math runs"
  - "Explicit-quantity signals (signal.quantity set) skip the gate entirely — the live/manual TradingInterface path is untouched"
  - "LONG_SHORT passes the gate: registration (strategies_handler), not admission, polices LONG_SHORT"
  - "Missing portfolio_handler read model -> gate abstains (returns None) and the sizing step right after fails loudly — no silent pass-through invented"
  - "Metrics block asserted as ONE exact dict comparison (RESEARCH OQ3) — consistent with the D-16 byte-exact discipline; deterministic runs reproduce the floats bit-for-bit"
  - "Slippage columns presence-asserted explicitly (_TRADE_SLIPPAGE_COLUMNS) so the golden-derived _trade_numeric auto-lock cannot silently lose them"
metrics:
  duration: "~40 min across two executor sessions (owner-gated D-23 checkpoint between Task 2 and Task 3)"
  completed: "2026-06-07"
  tasks: 3
  tests-added: 7
---

# Phase 7 Plan 07: LONG_ONLY Direction Guard + M5b Re-freeze 1 Summary

DEF-01-C is dead structurally: the D-08 direction admission gate rejects (audited, `triggered_by="admission_direction"`) any unsized LONG_ONLY SELL with no open long before sizing can turn it into a short entry, and the golden reference was re-frozen owner-approved to a clean long-only run (−2 SHORT, +2 LONG, 134 trades, final equity 53103.0155 → 46132.7668) with the D-15 metrics block and D-17 slippage columns entering the frozen artifacts in the same named re-freeze.

## Tasks Completed

| Task | Name | Commits | Key Files |
|------|------|---------|-----------|
| 1 | Direction admission guard + unit tests (implemented, held uncommitted per D-21) | c9581a1 | itrader/order_handler/order_manager.py, tests/unit/order/test_admission_rules.py |
| 2 | Owner sign-off on the expected-diff note (D-23 blocking checkpoint) | c9581a1 | tests/golden/REFREEZE-M5B-DIRECTION.md |
| 3 | ONE-commit re-freeze: guard + goldens + note + extended oracle assertions | c9581a1 | tests/golden/{trades,equity}.csv, tests/golden/summary.json, tests/integration/test_backtest_oracle.py |

All three tasks land in the single commit `c9581a1` by design — D-21 one-commit discipline for result-changing re-freezes.

## What Was Built

**Direction admission gate (`order_manager.py`, tabs):** `_enforce_direction_admission` runs as step 0 of `process_signal`, BEFORE the SizingResolver. For an unsized signal it dispatches on `signal.direction`: `LONG_ONLY` + `Side.SELL` with no open long (no position, or `net_quantity <= 0`) builds the entity with quantity 0, records `add_state_change(REJECTED, reason naming the violation, triggered_by="admission_direction")` with the signal's event-derived timestamp, stores it, and returns a `failure_result` — the established Phase 4/5 audited-rejection shape. `SHORT_ONLY` + BUY with no open short is rejected symmetrically (oracle-dark). Three paths are explicitly preserved: explicit-quantity signals skip the gate (live/manual path), `LONG_SHORT` passes (registration polices it, not admission), and a LONG_ONLY SELL with an open long passes through to exit sizing unchanged.

**Re-frozen goldens (M5b re-freeze 1, owner-approved):** `tests/golden/{trades.csv,equity.csv,summary.json}` regenerated from the guarded run. The 2 blessed golden shorts (2018-06-10 → 2019-03-12 and 2023-10-29 → 2023-11-14) are rejected at admission; their covering BUYs now open 2 replacement LONGs, so the trade count holds at 134 (−2 SHORT, +2 LONG, 0 SHORT rows remain). Fraction-of-cash compounding shifts every downstream entry — final equity drops 13.13% to 46132.76684866844, fully attributed in `tests/golden/REFREEZE-M5B-DIRECTION.md` (no unexplained residual). The run produced exactly 3 `admission_direction` rejections (2018-06-09, 2018-09-05, 2023-10-28).

**New frozen artifacts riding the named re-freeze:** the summary.json `metrics` block (D-15: cagr 0.1989, max_drawdown −0.5388, profit_factor 1.2908, sharpe 0.6578, sortino 1.0378, win_rate 0.36567) and the trades.csv `slippage_entry`/`slippage_exit` columns (D-17, next-open gap attribution in this zero-slippage run).

**Oracle test extension (same commit, Pitfall 6):** `test_backtest_oracle.py` gains (a) the D-08/D-11 re-baseline narration continuing the key-tuple comment block, (b) an exact dict comparison of `summary["metrics"]` against the golden's metrics object, and (c) a `_TRADE_SLIPPAGE_COLUMNS` presence assertion so the golden-derived `_trade_numeric` auto-lock provably covers the new columns.

**Tests (7, `tests/unit/order/test_admission_rules.py`, spaces, auto-marked unit):** no-open-long rejection (audited PENDING→REJECTED, event-derived timestamp), closed-position rejection (`net_quantity` 0), open-long exit still sizes and emits, LONG_ONLY BUY passes, SHORT_ONLY BUY-with-no-short rejected, LONG_SHORT passes, explicit-quantity SELL skips the gate.

## Verification Evidence

- `make test`: **703 passed** (696 prior + 7 admission tests) against the re-frozen reference
- `make typecheck` (mypy --strict): Success, no issues in 129 source files
- Oracle: `tests/integration/test_backtest_oracle.py` — 2 passed (behavioral identity + numeric EXACT incl. metrics block and slippage columns)
- Determinism: two consecutive `scripts/run_backtest.py` runs byte-identical (`trades.csv`, `equity.csv`, `summary.json`); regenerated output byte-identical to the committed goldens
- Atomicity: `git log -1 --name-only` on `c9581a1` shows order_manager.py, test_admission_rules.py, all 3 goldens, REFREEZE-M5B-DIRECTION.md, and test_backtest_oracle.py in the SAME commit
- `tests/golden/trades.csv`: 0 rows with side SHORT; header carries `slippage_entry,slippage_exit`
- Owner approval: granted at the D-23 blocking checkpoint ("approved"), recorded in the note's status line

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `test_reservation_inertness.py` harness updated for the 13-column golden header**
- **Found during:** Task 3 (full-suite gate after copying the re-frozen goldens)
- **Issue:** The plan-05-06 inertness trace serializes its fresh trade log via `module.build_trade_log(portfolio)` only — 11 columns — while the re-frozen golden now carries the 2 D-17 slippage columns, so `test_trade_log_identical_to_golden` failed on a (134, 11) vs (134, 13) shape mismatch
- **Fix:** The fixture now mirrors the generator's serialization exactly: `module.attach_slippage(trades, system.store.read_bars(module.TICKER)["close"])` and `trades[module.TRADE_COLUMNS + module.SLIPPAGE_COLUMNS]` with the pinned float format. The test's intent (trade log identical to the committed golden) is unchanged and strictly stronger — it now locks the slippage columns too
- **Files modified:** tests/integration/test_reservation_inertness.py
- **Commit:** c9581a1 (must be in the re-freeze commit — the suite must be green at this commit per the gate)

**2. [Rule 3 - Blocking] Worktree environment handling (carried from 07-01/07-05/07-06)**
- **Issue:** Worktree venv resolves `itrader` to the main checkout; `make` targets require a `.env`
- **Fix:** All test runs use `PYTHONPATH="$PWD"`; empty gitignored `.env` present locally. No repo files changed
- **Commit:** n/a

## TDD Gate Compliance

Task 1 carried `tdd="true"` but the plan's D-21 one-commit discipline overrides the per-task RED/GREEN commit cadence: the failing-state evidence (oracle test RED against the old golden after the guard landed — verified by the Task 1 executor) and the unit tests were held uncommitted until the owner-gated re-freeze, then landed atomically in `c9581a1`. The RED→GREEN sequence was executed and verified in the working tree; it is intentionally not visible as separate commits.

## Known Stubs

None — no placeholder values, no unwired data paths introduced.

## Threat Flags

None — no new network endpoints, auth paths, file-access patterns, or trust-boundary schema changes beyond the plan's threat model. T-07-17 (unattributed oracle drift) mitigated via the one-commit + owner-checkpoint + full compounding attribution; T-07-18 (over-rejection) mitigated by the pass-path unit tests; T-07-19 (vanishing rejections) mitigated by the audited-entity assertions.

## Self-Check: PASSED

All 9 claimed files exist on disk; commit c9581a1 present; admission_direction grep confirmed in order_manager.py.
