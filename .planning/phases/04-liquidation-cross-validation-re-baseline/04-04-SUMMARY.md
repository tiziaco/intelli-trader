---
phase: 04-liquidation-cross-validation-re-baseline
plan: 04
subsystem: XVAL-01 accounting-core cross-validation evidence (liquidation e2e + crossval runners)
tags: [XVAL-01, LIQ-01, LIQ-02, LIQ-03, D-08, D-10, D-12, e2e, cross-validation, oracle-dark]
requirements-completed: [XVAL-01, LIQ-01, LIQ-02, LIQ-03]
dependency-graph:
  requires:
    - "04-03: the isolated-margin liquidation engine + the LOCKED set_order_storage wiring (compose.py construction-time injection) the e2e leaves drive"
    - "04-00: Wave-0 e2e stubs (forced_liq_long/short, levered_long_into_liquidation) un-skipped + filled"
  provides:
    - "Three white-box liquidation e2e leaves (PRIMARY oracle D-08): corrected isolated liq price, penalty on commission, WB-capped loss, LIQUIDATION-tagged forced-close FILLED in the mirror"
    - "The combined SEVEN-leaf accounting-core regression gate (3 liquidation + 4 parked P2/P3) — green together BEFORE the 04-05 owner sign-off"
    - "scripts/crossval/{short,levered,liquidation}_run.py + the standalone sibling scripts/cross_validate_accounting.py"
    - "tests/golden/CROSS-VALIDATION-ACCOUNTING.md (PENDING Owner Sign-Off — the evidence the 04-05 owner gate reviews)"
  affects:
    - "04-05 owner gate: reviews CROSS-VALIDATION-ACCOUNTING.md, signs the Owner Sign-Off PENDING->APPROVED, then freezes the accounting-core golden + replaces the PARKED banners with freeze provenance"
tech-stack:
  added: []
  patterns:
    - "white-box hand-computed e2e (NOT run_scenario/golden-diff) — asserts liquidation INTERNALS the trades/equity/summary CSVs don't capture (mirrors tests/e2e/levered_long EXACTLY)"
    - "STANDALONE SIBLING crossval driver (cross_validate_accounting.py) mirroring the v1.3 _limit precedent — base cross_validate.py byte-unchanged"
    - "SCRIPT-ONLY reference-engine imports (D-10) — backtesting.py/backtrader only under scripts/, never tests/ (keeps filterwarnings=[error] intact)"
    - "directional-corroboration-only liquidation crossval (D-08) — the hand-computed closed-form is PRIMARY; engines corroborate the DIRECTION, not the isolated formula"
key-files:
  created:
    - "tests/e2e/forced_liq_long/test_forced_liq_long_scenario.py (white-box forced-liq long)"
    - "tests/e2e/forced_liq_short/test_forced_liq_short_scenario.py (white-box forced-liq short)"
    - "tests/e2e/levered_long_into_liquidation/test_levered_long_into_liquidation_scenario.py (margin-core -> liq thread)"
    - "scripts/crossval/short_run.py (short round-trip through backtesting.py + backtrader)"
    - "scripts/crossval/levered_run.py (leveraged long, margin = 1/L)"
    - "scripts/crossval/liquidation_run.py (levered-long-into-liquidation, directional corroboration)"
    - "scripts/cross_validate_accounting.py (standalone sibling driver)"
    - "tests/golden/CROSS-VALIDATION-ACCOUNTING.md (evidence doc, PENDING Owner Sign-Off)"
  modified:
    - "tests/e2e/levered_long/test_levered_long_scenario.py + bars.csv ([Rule 1] adverse mark 80->90 — see Deviations)"
decisions:
  - "All three liquidation leaves use the corrected isolated liq price the 04-03 engine computes (D-01-CORR): long (entry - WB/|size|)/(1 - MMR) = 80.808080... quantized to 80.81; short (entry + WB/|size|)/(1 + MMR) = 118.811881... quantized to 118.81 — matching the plan must_haves"
  - "Position.realised_pnl on a forced close is the close PnL at the QUANTIZED fill price NET of the penalty commission (long -3838.00 - 80.808... = -3918.808080...; short -3762.00 - 118.811... = -3880.811881...) — the penalty folds into the close PnL, not a separate carry line; verified against the live engine before anchoring the assertions"
  - "A liquidation order is identified by a LIQUIDATION-tagged entry in order.state_changes (the trigger source rides the OrderStateChange audit trail, NOT an Order.triggered_by field — the Order has no such top-level attribute)"
  - "short/levered FULLY cross-validate (final equity matches the e2e: short 100200, levered 14000); liquidation is DIRECTIONAL corroboration only (D-08) — both engines liquidate; backtrader drifts to -8000 (does NOT floor equity), exactly the DEF-01-C defect iTrader's explicit WB-cap closes"
  - "backtesting.py uses plain Backtest (whole-unit absolute sizing) NOT FractionalBacktest for the accounting scenarios — FractionalBacktest's size>=1 rescaling floored the fixed-quantity positions to ~0; plain Backtest shorts/buys the exact unit count, reconciling cleanly"
  - "the evidence doc is WRITTEN by the driver (report body), mirroring the cross_validate_limit.py precedent where the script emits the report and the Owner Sign-Off is appended/signed at the gated checkpoint"
metrics:
  duration-min: 70
  completed: 2026-06-16
  tasks: 3
  files: 10
---

# Phase 4 Plan 04: XVAL-01 Accounting-Core Cross-Validation Evidence Summary

Built the XVAL-01 evidence (NOT the freeze — that is the owner-gated 04-05 plan): three crafted
white-box liquidation e2e scenarios that are the PRIMARY correctness oracle for the liquidation
event (D-08), the cross-validation runners for short / leveraged-long / liquidation against
backtesting.py + backtrader, and the accounting-core cross-validation evidence doc with a PENDING
Owner Sign-Off block. The combined SEVEN-leaf automated gate (3 new liquidation + 4 parked P2/P3)
is green BEFORE the 04-05 human checkpoint — and it caught a real regression the 04-03 engine
introduced into the parked `levered_long` leaf (documented + fixed below). The BTCUSD spot oracle
stays byte-exact (134 / 46189.87730727451, D-11); `mypy --strict` clean (163 files).

## What Was Built

**Task 1 — three white-box liquidation e2e + the seven-leaf regression gate (LIQ-01/02/03, D-08):**
- `forced_liq_long/` — a leveraged long (LeveredFraction f=2, leverage clamps 20->5, WB=4000,
  MMR=0.01, fee_rate=0.005) survives the adverse mark 90 (> 80.808 liq floor) and is FORCE-
  LIQUIDATED on the breach bar (close 75 <= 80.808) at the quantized isolated liq price 80.81;
  penalty (80.808...) rides commission; `realised_pnl = -3918.808080...` (loss net of penalty)
  within WB; the LIQUIDATION-tagged forced-close SELL Order reaches FILLED in the mirror; equity
  stays > 0 (DEF-01-C closed).
- `forced_liq_short/` — the mirrored short force-COVERED at liq 118.81 (close 125 >= 118.811);
  `realised_pnl = -3880.811881...`; LIQUIDATION-tagged BUY-to-cover Order FILLED.
- `levered_long_into_liquidation/` — the Phase-2 margin core (LeveredFraction sizing, locked
  WB = notional/L) threaded into the P4 liquidation trigger: the locked 4000 is RELEASED on the
  forced close, the loss is clamped at WB (directional corroboration of backtesting.py
  equity<=0->close-all, D-08).
- All three drive the REAL engine tick-by-tick (`system.engine.time_generator`); synthetic ticker
  `LIQUSD` only (NEVER BTCUSD); oracle-dark margin Instrument declaring max_leverage / MMR /
  liquidation_fee_rate; flat-OHLC `bars.csv`. Commit `f1bbcc1`.

**Task 2 — crossval runners + standalone sibling driver (XVAL-01):**
- `scripts/crossval/short_run.py`, `levered_run.py`, `liquidation_run.py` — each runs the scenario
  through backtesting.py + backtrader (uniform `run_*()` contract, normalized trade columns).
- `scripts/cross_validate_accounting.py` — a STANDALONE SIBLING of `cross_validate.py` (mirrors the
  v1.3 `_limit` precedent), orchestrating the three scenarios, reusing `scripts/crossval/reconcile.py`
  VERBATIM; iTrader the authoritative baseline; headlines recomputed via `itrader.reporting.metrics`
  (apples-to-apples). Short FULLY reconciles (final 100200), levered FULLY reconciles (final 14000),
  liquidation is DIRECTIONAL corroboration only (D-08 — both engines liquidate). Base
  `cross_validate.py` byte-unchanged; no reference-engine import under `tests/`. Commit `fe17f5f`.

**Task 3 — accounting-core evidence doc (unsigned):**
- `tests/golden/CROSS-VALIDATION-ACCOUNTING.md` — sibling of `CROSS-VALIDATION.md`: per-scenario
  trade-level (PRIMARY) + metric-level (SECONDARY) reconciliation tables, the D-08 oracle boundary
  (hand-computed 80.808.../118.811... recorded PRIMARY; engines directional), per-divergence
  disposition, and an Owner Sign-Off block marked **PENDING** (NOT approved). NO golden frozen.
  Commit `efb1346`.

## Verification

- `pytest tests/e2e/forced_liq_long forced_liq_short levered_long_into_liquidation levered_long short_roundtrip short_carry partial_cover` → **7 passed** (the combined seven-leaf gate).
- `python scripts/cross_validate_accounting.py` → runs to completion; emits the per-scenario tables; `liquidation_directional={'backtesting.py': True, 'backtrader': True}`.
- `tests/golden/CROSS-VALIDATION-ACCOUNTING.md` exists with `Owner Sign-Off` + `PENDING`; records 80.808080... PRIMARY; no `Status: APPROVED`; no golden CSV frozen.
- `git diff scripts/cross_validate.py` → empty (base driver byte-unchanged).
- `grep -rln "import backtesting|import backtrader" tests/` → none (D-10 SCRIPT-ONLY held).
- `pytest tests/integration/test_backtest_oracle.py` → **3 passed** (byte-exact 134 / 46189.87730727451, D-11).
- `pytest tests/e2e -m e2e` → **66 passed** (was 63; the 3 new liquidation leaves now run instead of skip; no other leaf regressed).
- `mypy --strict itrader` → Success, no issues in 163 source files (the new scripts are outside `files=["itrader"]`).
- Full suite collects cleanly under `filterwarnings=["error"]` (1146 tests collected).

## Deviations from Plan

### [Rule 1 — Bug / regression caught by the seven-leaf gate] levered_long adverse mark 80 -> 90

- **Found during:** Task 1 (running the combined seven-leaf gate, exactly threat T-04-04-REG).
- **Issue:** The parked `tests/e2e/levered_long` leaf FAILED once the 04-03 liquidation engine was
  in place. Its adverse-mark bar drops the LEVUSD close to **80**, which is the long BANKRUPTCY
  price `entry x (1 - 1/L) = 100 x 0.8 = 80` and sits BELOW the corrected isolated maintenance liq
  price `80.808080...`. The Phase-2 leaf (authored when DEF-01-C was still open) asserted the
  position "survives the adverse mark" — but the 04-03 engine now CORRECTLY force-liquidates it at
  that bar. This is the genuine parked-scenario regression the combined gate is designed to surface
  BEFORE the 04-05 human checkpoint (T-04-04-REG), not an engine defect.
- **Fix:** Raised the `levered_long` adverse-mark bar from 80 to **90** (still a meaningful adverse
  10% drawdown, but ABOVE the 80.808 liq floor so the position stays healthy and the leaf keeps
  testing its margin-core intent: admission reservation, position-life locked margin, honest
  read-model on an adverse mark, profitable close at 120). Updated the three affected
  hand-computed assertion sites + the docstring price-series table and arithmetic
  (maintenance 160->180, equity 26000->28000, margin_ratio 162.5->155.5555...). The deep-mark
  BREACH case (mark 80/75) is now owned by the dedicated NEW `levered_long_into_liquidation` leaf,
  so coverage is not lost — it is relocated to the correct leaf.
- **Files modified:** `tests/e2e/levered_long/test_levered_long_scenario.py`, `tests/e2e/levered_long/bars.csv`.
- **Commit:** `f1bbcc1`.
- **Scope note:** `levered_long` is outside this plan's declared `files_modified` (it IS listed in
  the 04-05 plan for the freeze-provenance banner). Resolving it here was necessary to satisfy this
  plan's explicit must_have/acceptance requirement that the SEVEN-leaf gate be green together; the
  fix is minimal (one mark value) and preserves the leaf's intent. Flagged for the 04-05 owner gate.

### [Plan-premise clarification] forced-close Order trigger source lives on state_changes

- The plan/research framed detecting a liquidation order via its `OrderTriggerSource.LIQUIDATION`
  tag. The `Order` entity has NO top-level `triggered_by` attribute — the trigger source rides each
  `OrderStateChange` in `order.state_changes` (the 04-03 engine records a PENDING state change
  tagged `LIQUIDATION`). The leaves detect a liquidation order via
  `any(sc.triggered_by == OrderTriggerSource.LIQUIDATION for sc in o.state_changes)`. No code change
  — a test-authoring clarification consistent with the 04-03 engine's actual mint path.

### [Discretion] plain Backtest (not FractionalBacktest) for the accounting crossval runners

- `FractionalBacktest` rescales `size >= 1` by `fractional_unit`, flooring the fixed-quantity
  accounting positions to ~0 (the short PnL came out ~0). Switched to plain `backtesting.Backtest`
  (integer absolute unit count) so the runners short/buy the exact unit count and reconcile cleanly
  (short final 100200, levered 14000 — matching the hand-computed e2e). Pure script-side scenario
  shaping; oracle-dark.

## Threat-Model Coverage

- **T-04-04-WARN (mitigate):** SCRIPT-ONLY discipline held — `grep -rln "import backtesting|import backtrader" tests/` returns nothing; the full suite collects under `filterwarnings=["error"]`. Held.
- **T-04-04-REG (mitigate):** the combined SEVEN-leaf gate ran the parked `levered_long`/`short_roundtrip`/`short_carry`/`partial_cover` alongside the three new liquidation leaves and CAUGHT the `levered_long` regression (mark 80 now liquidates) — fixed at THIS automated gate, before the 04-05 human sign-off. Held (the gate did exactly its job).
- **T-04-04-SIB (mitigate):** `cross_validate_accounting.py` is a standalone sibling; `git diff scripts/cross_validate.py` is empty (base driver byte-unchanged). Held.
- **T-04-04-ORC (mitigate):** synthetic tickers only (`SHORTUSD`/`LEVUSD`/`LIQUSD`); the BTCUSD spot oracle stays byte-exact (134 / 46189.87730727451, D-11); the integration oracle is green. Held.
- **T-04-04-PREM (mitigate):** the Owner Sign-Off is PENDING; NO golden CSV is frozen in this plan (the freeze is the gated 04-05 plan). Held.
- **T-04-04-SC (accept):** no package installs (backtesting/backtrader already pinned + installed). N/A.

## Known Stubs

None. All three liquidation e2e leaves are fully implemented and assert real engine internals; the
crossval runners + driver produce live reconciliation evidence. The PARKED banners on the e2e
leaves and the PENDING Owner Sign-Off are INTENTIONAL and by-design — the freeze + sign-off is the
gated 04-05 plan (D-10/D-12), not a stub.

## Self-Check: PASSED

Files (all present):
- tests/e2e/forced_liq_long/test_forced_liq_long_scenario.py
- tests/e2e/forced_liq_short/test_forced_liq_short_scenario.py
- tests/e2e/levered_long_into_liquidation/test_levered_long_into_liquidation_scenario.py
- scripts/crossval/short_run.py, levered_run.py, liquidation_run.py
- scripts/cross_validate_accounting.py
- tests/golden/CROSS-VALIDATION-ACCOUNTING.md (Owner Sign-Off PENDING)

Commits (all in git log):
- f1bbcc1 (Task 1 — three liquidation e2e + seven-leaf gate + levered_long Rule-1 fix)
- fe17f5f (Task 2 — crossval runners + standalone sibling driver)
- efb1346 (Task 3 — evidence doc, unsigned)
