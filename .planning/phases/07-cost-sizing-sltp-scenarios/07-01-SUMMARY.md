---
phase: 07-cost-sizing-sltp-scenarios
plan: 01
subsystem: e2e-test-scaffolding
tags: [e2e, commission, fee-model, sltp, golden-master, foundational]
requires:
  - "tests/e2e/ harness (Phase 4) + matching leaves (Phase 6)"
  - "itrader Position.commission, ExchangeConfig, SLTPPolicy (shipped)"
provides:
  - "always-on commission golden column (oracle-dark) in tests/e2e/conftest.py"
  - "D-14 exchange-config seam: spec.exchange now applies fee/slippage to the run"
  - "ScriptedEmitter sltp_policy kwarg (D-12) for Wave-2 SLTP leaves"
  - "frozen COST-01 percent-fee canary leaf (non-zero commission, hand-verified)"
  - "15 re-frozen pre-existing E2E trade goldens (commission=0.00)"
affects:
  - "every Wave-2 plan (02 COST, 03 SIZE, 04 SLTP) depends_on this plan (D-16)"
tech-stack:
  added: []
  patterns:
    - "conftest-LOCAL COMMISSION_COLUMN (NOT in reporting/) keeps the BTCUSD oracle byte-exact"
    - "D-14 seam re-runs only _init_fee_model/_init_slippage_model, never _supported_symbols"
    - "order-independent key-merge on (entry_date,exit_date,side) for commission attach"
key-files:
  created:
    - "tests/e2e/cost/__init__.py"
    - "tests/e2e/cost/percent_fee/__init__.py"
    - "tests/e2e/cost/percent_fee/scenario.py"
    - "tests/e2e/cost/percent_fee/test_scenario.py"
    - "tests/e2e/cost/percent_fee/bars.csv"
    - "tests/e2e/cost/percent_fee/golden/trades.csv"
    - "tests/e2e/cost/percent_fee/golden/summary.json"
  modified:
    - "tests/e2e/conftest.py"
    - "tests/e2e/strategies/scripted_emitter.py"
    - "15 pre-existing tests/e2e/{matching,smoke}/**/golden/trades.csv (re-frozen)"
decisions:
  - "D-07: commission column sourced from real Position.commission (buy+sell), not recomputed"
  - "D-08: column is always-on + oracle-dark, appended after TRADE_COLUMNS+SLIPPAGE_COLUMNS"
  - "D-12: ScriptedEmitter takes an sltp_policy kwarg (no bespoke per-policy classes)"
  - "D-14: exchange seam re-inits fee/slippage from spec.exchange WITHOUT touching _supported_symbols"
  - "D-16: foundational-plan-first sequencing — this plan is the locked non-parallel prerequisite"
metrics:
  duration: "~5 min"
  completed: "2026-06-10"
  tasks: 4
  files: 24
---

# Phase 7 Plan 01: Cost/Sizing/SLTP Scaffolding Foundation Summary

Installed the three shared E2E test-scaffolding seams Phase 7 Wave-2 depends on
(always-on commission golden column, the D-14 exchange-config seam fix, and the
`ScriptedEmitter.sltp_policy` kwarg), proved them end-to-end on one hand-verified
COST-01 percent-fee canary (commission=285.00), re-froze the 15 pre-existing E2E
trade goldens additively (commission=0.00), and confirmed the BTCUSD oracle stays
byte-exact.

## What Was Built

**Task 1 — commission column + D-14 seam (`tests/e2e/conftest.py`):**
- Added a conftest-LOCAL `COMMISSION_COLUMN = ["commission"]` (deliberately NOT in
  `itrader/reporting/`, so the core `TRADE_COLUMNS` pin and the BTCUSD oracle stay
  byte-exact — oracle-dark, D-08).
- In `_assemble`, attach the column from the real `Position.commission`
  (`buy_commission + sell_commission`, position.py:131) via an order-independent
  key-merge on `(entry_date, exit_date, side)`; empty-trade leaves get a uniform
  `0.00` schema. `float(p.commission)` narrows the Decimal only at the CSV edge.
- `_freeze` / `_diff` now write/round-trip `TRADE_COLUMNS + SLIPPAGE_COLUMNS +
  COMMISSION_COLUMN`. `_roundtrip` is unchanged (it takes `columns` as a param).
- Replaced the broken `model_dump()`/`update_config(**fields)` block with the
  constructor-path re-init (`simulated.config = exchange_config`; re-run
  `_init_fee_model`/`_init_slippage_model`). It does NOT touch
  `simulated._supported_symbols` (PATTERNS A2 — re-deriving it would wipe the
  post-construction BTCUSD admission and silently REFUSE every order).

**Task 2 — `ScriptedEmitter.sltp_policy` kwarg (`tests/e2e/strategies/scripted_emitter.py`):**
- Added a keyword-only `sltp_policy: "SLTPPolicy | None" = None` (default `None`),
  imported `SLTPPolicy` from `itrader.core.sizing`, and threaded it into
  `BaseStrategyConfig`, reusing the existing kwarg→config→SignalEvent plumbing
  (config.py:55 → base.py:67 → strategies_handler.py:165). No bespoke per-policy
  strategy classes (D-12).

**Task 3 — COST-01 percent-fee canary (`tests/e2e/cost/percent_fee/`):**
- New leaf cloned from the `oco_lifecycle` template: a MARKET BUY → MARKET SELL
  round-trip on contrived round-priced BTCUSD bars with a 1% PERCENT fee
  (`ExchangeConfig(fee_model=FeeModelConfig(model_type=PERCENT,
  fee_rate=Decimal("0.01")), slippage_model=...NONE)`), applied via the D-14 seam.
- VERIFY note hand-derives: qty = (0.95 × 10000)/100 = 95; buy_commission = 95 ×
  100 × 0.01 = 95.00; sell_commission = 95 × 200 × 0.01 = 190.00; total commission
  = 285.00; realised_pnl = 9215.00; final_cash = 19215.00. The frozen golden
  matches to the cent (commission column = 285.00, non-zero).

**Task 4 — re-freeze 15 pre-existing goldens:**
- Re-froze all 15 `tests/e2e/{matching,smoke}/**/golden/trades.csv` ONE AT A TIME
  (the harness refuses `--freeze` with >1 selected test).
- Audited every `git diff`: the ONLY change is the additive `,commission` column
  (value `0.00` on every row of these zero-fee `exchange=None` leaves; empty leaves
  changed only the header). No other value drifted — Assumption A2 holds.

## Verification Results

- `poetry run pytest tests/e2e/cost/percent_fee -x` → 1 passed (canary, non-zero commission).
- `poetry run pytest tests/e2e/matching tests/e2e/smoke -x` → all 15 re-frozen leaves green.
- `poetry run pytest tests/integration/test_backtest_oracle.py -x` → 3 passed (byte-exact, oracle-dark).
- `poetry run pytest tests/e2e` → 16 passed.
- `mypy itrader` (`--strict`) → no issues in 160 source files (no `itrader/` source changed).
- `grep -rn "COMMISSION_COLUMN" itrader/reporting/` → empty (column stays out of core).

## TDD Gate Compliance (Task 3, tdd="true")

The COST-01 leaf followed the E2E freeze discipline as its RED/GREEN cycle. Note:
the RED-phase run (no goldens) PASSED vacuously because `_diff` only asserts golden
files that EXIST and the empty `golden/` dir contained none. The GREEN gate is the
substantive proof: after `--freeze` produced real goldens, the leaf was re-run
WITHOUT `--freeze` and diffed green against a hand-verified golden whose commission
(285.00) and final_cash (19215.00) match the VERIFY-note derivation to the cent.
The freeze proves stability; the VERIFY note proves correctness (T-07-01 mitigation).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected the COST-01 VERIFY-note slippage_exit derivation**
- **Found during:** Task 3 (freeze vs VERIFY cross-check)
- **Issue:** The VERIFY note initially claimed `slippage_exit = 200 - 150 = 50.0`,
  but the frozen golden showed `0.0`. `attach_slippage` indexes the STORE close
  series (not the run/decision grid): the store bar immediately before the
  2020-01-05 exit fill is the 2020-01-04 bar (close=200), so `200 - 200 = 0.0`.
- **Fix:** Corrected the VERIFY-note slippage lines to match the engine's actual
  store-indexed attribution. The frozen golden was correct; only the hand-note's
  derivation was wrong. No code/golden change.
- **Files modified:** tests/e2e/cost/percent_fee/scenario.py (VERIFY note only)
- **Commit:** cf33593

No other deviations — the three seams and the 15 re-freezes executed exactly as planned.

## Known Stubs

None. The COST-01 canary runs a real fill end-to-end with a real configured fee
model; the commission column is sourced from real Position state, not placeholder data.

## Threat Flags

None — no new security-relevant surface. This is pure in-repo test scaffolding;
no package installs (T-07-SC accepted), no network/auth/schema surface introduced.

## Self-Check: PASSED

All created files verified present on disk; all 4 task commits verified in git log:
- 522cb0a feat(07-01): commission golden column + D-14 exchange-seam fix in conftest
- a9023a8 feat(07-01): add sltp_policy kwarg to ScriptedEmitter
- cf33593 feat(07-01): author + hand-verify + freeze COST-01 percent-fee canary
- 34d5b2f test(07-01): re-freeze 15 E2E trade goldens with commission=0.00
