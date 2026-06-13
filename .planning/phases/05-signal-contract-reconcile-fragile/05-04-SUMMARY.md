---
phase: 05-signal-contract-reconcile-fragile
plan: 04
subsystem: cross-validation/limit-entry-golden
tags: [SIG-01, SIG-02, RECON-01, D-07, cross-validation, limit-entry, owner-signed-golden]
requires:
  - "Plan-01 buy_limit/buy_stop authoring factories (SIG-01/SIG-02 surface)"
  - "Plan-02 Side-typed + snapshot-threaded admission (final Phase-5 engine state)"
  - "Plan-03 streamlined reconcile (RECON-01 entry-fill -> bracket reconciliation)"
  - "Phase-4 e2e --freeze harness (tests/e2e/conftest.py)"
provides:
  - "An owner-signed, externally cross-validated (backtesting.py + backtrader) LIMIT-entry golden on the BTCUSD dataset (D-07)"
  - "A live green e2e regression lock: tests/e2e/matching/entries/limit_entry_crossval/golden/ (trades.csv + summary.json)"
  - "A crafted minimal deterministic LimitEntryStrategy + two LIMIT cross-val runners + a LIMIT orchestrator entry (SCRIPT-ONLY, D-10)"
  - "tests/golden/CROSS-VALIDATION-LIMIT.md evidence artifact with owner sign-off + attribution"
affects:
  - "tests/e2e/matching/entries/limit_entry_crossval/ (new leaf)"
  - "scripts/crossval/ (new LIMIT runners + strategy)"
  - "tests/golden/CROSS-VALIDATION-LIMIT.md"
tech-stack:
  added: []
  patterns:
    - "Crafted-minimal cross-val strategy (NOT SMA_MACD) to isolate the entry-fill->bracket mechanic across 3 engines"
    - "Owner-gated golden freeze via the e2e harness --freeze flag (one hand-verified scenario at a time, Pitfall 5)"
    - "Additive regression lock: the new LIMIT golden is a SEPARATE leaf, the existing SMA_MACD oracle stays byte-exact"
key-files:
  created:
    - "scripts/crossval/limit_entry_strategy.py"
    - "scripts/crossval/backtesting_py_limit_run.py"
    - "scripts/crossval/backtrader_limit_run.py"
    - "scripts/cross_validate_limit.py"
    - "tests/golden/CROSS-VALIDATION-LIMIT.md"
    - "tests/e2e/matching/entries/limit_entry_crossval/scenario.py"
    - "tests/e2e/matching/entries/limit_entry_crossval/test_scenario.py"
    - "tests/e2e/matching/entries/limit_entry_crossval/golden/trades.csv"
    - "tests/e2e/matching/entries/limit_entry_crossval/golden/summary.json"
  modified:
    - "tests/e2e/matching/entries/limit_entry_crossval/test_scenario.py (un-xfail at Task 3)"
    - "tests/golden/CROSS-VALIDATION-LIMIT.md (owner sign-off appended at Task 3)"
decisions:
  - "D-07: ONE owner-signed, externally cross-validated LIMIT-entry golden frozen ONLY after explicit owner sign-off with full attribution"
  - "A1 LEGITIMATE-DIFFERENCE accepted: iTrader fills the same-bar protective SL intrabar; both gating engines defer the contingent SL to the next bar and agree with each other (0 BUG, iTrader numbers kept)"
  - "The crafted strategy is minimal (NOT SMA_MACD) so the limit-fill + SL/TP-bracket algebra is reproducible across iTrader / backtesting.py / backtrader by construction"
metrics:
  duration: "~9 min (Task 3 freeze + verify; full plan spanned 3 waves)"
  completed: "2026-06-13"
  tasks: 3
  files: 9
---

# Phase 5 Plan 04: Owner-Signed LIMIT-Entry Cross-Validation Golden Summary

Froze ONE owner-signed, externally cross-validated (backtesting.py 0.6.5 + backtrader 1.9.78.123) LIMIT-entry golden on the real BTCUSD dataset, proving the SIG-01/SIG-02 `buy_limit` authoring surface end-to-end (a crafted strategy emits a limit → it fills on a LATER bar → the entry-fill anchors a percent SL/TP bracket, plus a marketable-limit case that fills at the bar OPEN) and exercising the RECON-01 entry-fill→bracket reconciliation — the regression anchor the N+2 margin/shorts milestone builds on.

## What Was Built

**Task 1 — Crafted strategy + e2e leaf (commit `4729448`):**
`scripts/crossval/limit_entry_strategy.py` (4-space) — a minimal deterministic `LimitEntryStrategy` using the Plan-01 `self.buy_limit(...)` factory with percent SL/TP (money via `to_money`, never `Decimal(float)`), plus the BTCUSD e2e leaf (`scenario.py` with a HAND-VERIFIED VERIFY note deriving each fill from the bar OHLC via the `min(open, limit)` rule; `test_scenario.py` delegating to the shared `run_scenario` harness). No cross-val engine imported under `tests/` (SCRIPT-ONLY, D-10). The leaf landed with an `xfail(not golden exists)` pending-golden marker.

**Task 2 — LIMIT runners + orchestrator + evidence (commit `c2fdc6f`):**
`scripts/crossval/backtesting_py_limit_run.py` + `backtrader_limit_run.py` (SCRIPT-ONLY) reproducing the crafted strategy's limit/SL/TP semantics under the uniform `run() -> (trade_log_df, equity_curve_series)` contract (backtrader via `buy_bracket(..., exectype=bt.Order.Limit, ...)`, default next-bar fills). `scripts/cross_validate_limit.py` loads the BTCUSD golden CSV once, runs the three engines, reuses `scripts/crossval/reconcile.py`, and writes `tests/golden/CROSS-VALIDATION-LIMIT.md` (metric table + the A1 same-bar protective-SL divergence dispositioned LEGITIMATE-DIFFERENCE).

**Task 3 — Owner sign-off + freeze (commit `75fb676`, THIS wave):**
Owner (tiziaco, 2026-06-13) signed off, explicitly accepting the A1 LEGITIMATE-DIFFERENCE. Then:
- Froze `tests/e2e/matching/entries/limit_entry_crossval/golden/{trades.csv, summary.json}` via the e2e harness `--freeze` flag (byte-identical serialization to the diff path; one hand-verified scenario, Pitfall 5).
- Removed the `xfail` pending-golden marker on `test_scenario.py` → the leaf is now a live green regression lock.
- Appended the owner sign-off + full-attribution block to `tests/golden/CROSS-VALIDATION-LIMIT.md` (mirroring `tests/golden/CROSS-VALIDATION.md`).

The frozen golden, hand-verified against the VERIFY note:
- **Entry A:** resting limit, decision 2018-09-02, fills 2018-09-05 @ 7155.9698 (a LATER bar) → protective SL fills same bar @ 6798.17131.
- **Entry B:** marketable limit, decision 2018-09-13, fills 2018-09-14 at the bar OPEN @ 6487.39 → protective SL fills same bar @ 6471.16155.
- **trade_count:** 2; **final_equity:** 9503.442073 (total_realised_pnl −496.557927).

## Verification Results

- `poetry run pytest tests/e2e/matching/entries/limit_entry_crossval -m e2e -q` → **1 passed** (green, no xfail/xpass — the leaf now DIFFS the frozen golden exact and would fail on drift).
- `poetry run pytest tests/integration/test_backtest_oracle.py` → **3 passed**; the existing SMA_MACD oracle stays **byte-exact (134 / 46189.87730727451)** — this plan added a NEW golden, it did not re-baseline the old one.
- Golden numbers match the verified, externally cross-validated run and the CROSS-VALIDATION-LIMIT.md metric table (final_equity 9503.442073; entry A 7155.9698→SL; entry B 6487.39→SL; trade_count 2).
- `grep -ci "sign-off\|approved" tests/golden/CROSS-VALIDATION-LIMIT.md` ≥ 1 (owner sign-off + attribution present).

## Deviations from Plan

None — Task 3 executed exactly as written in the plan's `<action>` and the checkpoint return. The freeze happened ONLY after the explicit owner "approved" signal with attribution (T-05-13 mitigation honored); the existing oracle was verified unchanged (T-05-14); no engine import entered `tests/` (T-05-15); the A1 divergence was dispositioned LEGITIMATE-DIFFERENCE and surfaced for owner review (T-05-16).

## Owner Sign-Off (Task 3 — blocking-human gate)

Approved by **tiziaco (Tiziano Iacovelli) <tiziano.iaco@gmail.com>**, 2026-06-13. The owner explicitly accepted the dispositioned same-bar protective-SL LEGITIMATE-DIFFERENCE (A1): iTrader fills the SL intrabar; both gating engines (backtesting.py, backtrader) defer the contingent SL to the next bar and agree with each other. 0 BUG; iTrader numbers kept.

## Known Stubs

None — the crafted strategy, runners, and golden are all live; the leaf is a real diff-on-drift regression lock.

## Threat Flags

None — no new security-relevant surface. The cross-val runners are SCRIPT-ONLY (never importable under `tests/`); the golden freeze was owner-gated; the existing oracle is untouched.

## Self-Check: PASSED

- FOUND: scripts/crossval/limit_entry_strategy.py
- FOUND: scripts/crossval/backtesting_py_limit_run.py
- FOUND: scripts/crossval/backtrader_limit_run.py
- FOUND: scripts/cross_validate_limit.py
- FOUND: tests/golden/CROSS-VALIDATION-LIMIT.md
- FOUND: tests/e2e/matching/entries/limit_entry_crossval/scenario.py
- FOUND: tests/e2e/matching/entries/limit_entry_crossval/test_scenario.py
- FOUND: tests/e2e/matching/entries/limit_entry_crossval/golden/trades.csv
- FOUND: tests/e2e/matching/entries/limit_entry_crossval/golden/summary.json
- FOUND commit: 4729448 (Task 1 — strategy + leaf)
- FOUND commit: c2fdc6f (Task 2 — runners + orchestrator + evidence)
- FOUND commit: 75fb676 (Task 3 — owner-signed golden freeze + un-xfail)
