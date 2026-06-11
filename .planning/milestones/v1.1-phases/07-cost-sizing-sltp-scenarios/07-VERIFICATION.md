---
phase: 07-cost-sizing-sltp-scenarios
verified: 2026-06-10T14:45:00Z
status: passed
score: 14/14
overrides_applied: 0
---

# Phase 7: Cost, Sizing & SLTP Scenarios — Verification Report

**Phase Goal:** Give fee models, slippage models, sizing policies, and SL/TP policies their first end-to-end golden coverage with cash math verified to the cent.
**Verified:** 2026-06-10T14:45:00Z
**Status:** passed
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | percent and maker_taker fee models covered E2E (maker vs taker distinguished on limit vs market) | VERIFIED | `tests/e2e/cost/percent_fee/` (1% rate, commission=285.00); `tests/e2e/cost/maker_taker/` (maker=0.001 commission 21.375, taker=0.002 commission 70.4156625 side by side in frozen golden) |
| 2 | combined fee+slippage round-trip cash math verified to the cent | VERIFIED | `tests/e2e/cost/combined_roundtrip/golden/summary.json` final_cash=18645.0; VERIFY note derives starting_cash + realised_pnl(8645) − commission(285) = 18645.00 exactly; frozen golden matches |
| 3 | fixed slippage covered (deterministic, RNG zeroed) | VERIFIED | `tests/e2e/cost/fixed_slippage/scenario.py` line 109: `random_variation=False`; frozen golden shows fill prices 102/196 matching VERIFY derivation |
| 4 | linear slippage covered (size-impact only, base noise zeroed) | VERIFIED | `tests/e2e/cost/linear_slippage/scenario.py` line 124: `base_slippage_pct=Decimal("0")`; engine fix (is-not-None, commit 7815130) required to honor Decimal("0") — confirmed present in simulated.py line 520 |
| 5 | slippage proven NOT applied to limit fills | VERIFIED | `tests/e2e/cost/limit_no_slip/scenario.py` uses `order_type=OrderType.LIMIT` with a 2% FIXED slippage model; frozen golden shows fill price = limit/trigger price exactly (commission=0.00, no price impact) |
| 6 | FixedQuantity sizing produces hand-verified fill of exactly the declared quantity | VERIFIED | `tests/e2e/sizing/fixed_quantity/golden/trades.csv` shows net_quantity=10, matching `sizing_policy=FixedQuantity(qty=Decimal("10"))` declared in scenario.py |
| 7 | RiskPercent sizing off stop distance produces hand-derivable quantity | VERIFIED | `tests/e2e/sizing/risk_percent/scenario.py` uses `RiskPercent(risk_pct=Decimal("0.02"))` + explicit script `sl=Decimal("80")`; VERIFY note derives qty=(10000*0.02)/|100-80|=10; frozen closed trade has net_quantity=10, realised_pnl=-200 (exactly 2% risk) |
| 8 | over-cash sizing produces audited insufficient-funds REJECTED order | VERIFIED | `tests/e2e/sizing/over_cash_reject/golden/orders.csv` row 2: `STANDALONE,BTCUSD,MARKET,BUY,REJECTED,100.0,1000.0,0.0,...`; summary.json trade_count=0, final_cash=10000 (untouched) |
| 9 | PercentFromDecision SL/TP priced at signal assembly (decision-bar close anchor) | VERIFIED | `tests/e2e/sltp/from_decision_*` scenario files use `sltp_policy=PercentFromDecision(sl_pct=0.10, tp_pct=0.20)` NO explicit sl/tp in script; frozen goldens show SL=90, TP=120 (anchor=decision close=100) |
| 10 | PercentFromFill SL/TP anchored to actual fill price | VERIFIED | `tests/e2e/sltp/from_fill_*` scenario files use `sltp_policy=PercentFromFill(...)`; frozen goldens show SL=81, TP=108 (anchor=next-bar-open fill=90); demonstrably different from decision anchor |
| 11 | Decision and Fill anchors produce DIFFERENT SL/TP levels for same percentages | VERIFIED | Decision: SL=90, TP=120; Fill: SL=81, TP=108 — confirmed in `from_decision_held/golden/orders.csv` and `from_fill_held/golden/orders.csv`; bars authored so decision close(100) != next-bar open(90) |
| 12 | Each policy exercised across SL-hit, TP-hit, and held-to-end outcomes | VERIFIED | 6 leaves exist: from_decision_sl_hit, from_decision_tp_hit, from_decision_held, from_fill_sl_hit, from_fill_tp_hit, from_fill_held; all 6 pass (30 total e2e passed) |
| 13 | held-to-end leaves assert via orders-snapshot (PENDING children) + summary, not empty trades.csv | VERIFIED | `from_decision_held/golden/orders.csv` (4 lines: header + ENTRY FILLED + SL PENDING + TP PENDING); `from_fill_held/golden/orders.csv` same structure; both summary.json trade_count=0 |
| 14 | BTCUSD oracle stays byte-exact (oracle-dark guarantee preserved) | VERIFIED | `poetry run pytest tests/integration/test_backtest_oracle.py -q` → 3 passed; COMMISSION_COLUMN is conftest-LOCAL only (`grep -rn COMMISSION_COLUMN itrader/reporting/` → empty) |

**Score:** 14/14 truths verified

---

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `tests/e2e/conftest.py` | COMMISSION_COLUMN + D-14 exchange-seam fix | VERIFIED | Line 93: `COMMISSION_COLUMN = ["commission"]`; lines 268-270: `simulated.config = exchange_config; simulated.fee_model = simulated._init_fee_model(); simulated.slippage_model = simulated._init_slippage_model()`; `_supported_symbols` never touched |
| `tests/e2e/strategies/scripted_emitter.py` | sltp_policy constructor kwarg | VERIFIED | Line 86: `sltp_policy: "SLTPPolicy | None" = None`; line 103: `sltp_policy=sltp_policy` threaded into `BaseStrategyConfig`; `SLTPPolicy` imported from `itrader.core.sizing` line 51 |
| `tests/e2e/cost/percent_fee/scenario.py` | COST-01 canary + VERIFY note | VERIFIED | Contains `ExchangeConfig` with `FeeModelType.PERCENT`, `Decimal("0.01")` fee_rate; VERIFY note fences present (lines 15/90); non-zero commission=285.00 in frozen golden |
| `tests/e2e/cost/percent_fee/golden/trades.csv` | Frozen canary golden with non-zero commission | VERIFIED | Header ends with `,commission`; data row shows `commission=285.0000000000` |
| `tests/e2e/cost/maker_taker/golden/trades.csv` | COST-02 maker vs taker commission contrast | VERIFIED | Two trade rows: commission 21.3750000000 (maker) and 70.4156625000 (taker) |
| `tests/e2e/cost/fixed_slippage/scenario.py` | COST-03 fixed slippage with random_variation=False | VERIFIED | Line 109: `random_variation=False` confirmed present |
| `tests/e2e/cost/linear_slippage/scenario.py` | COST-04 linear slippage with base_slippage_pct=0 | VERIFIED | Line 124: `base_slippage_pct=Decimal("0")` confirmed present |
| `tests/e2e/cost/limit_no_slip/scenario.py` | COST-05 limit-no-slip proof | VERIFIED | Contains `order_type=OrderType.LIMIT` line 134 and FIXED slippage model configured |
| `tests/e2e/cost/combined_roundtrip/golden/summary.json` | COST-06 cash-to-the-cent | VERIFIED | `final_cash: 18645.0`; VERIFY note reconciles commission+slippage+pnl to the cent |
| `tests/e2e/sizing/fixed_quantity/golden/trades.csv` | SIZE-01 FixedQuantity fill | VERIFIED | Contains BTCUSD trade with net_quantity=10 matching declared FixedQuantity |
| `tests/e2e/sizing/risk_percent/scenario.py` | SIZE-02 RiskPercent + decision-time stop | VERIFIED | Contains `RiskPercent` and explicit `"sl"` in script; produces closed trade (not REJECTED) |
| `tests/e2e/sizing/over_cash_reject/golden/orders.csv` | SIZE-03 REJECTED order mirror | VERIFIED | Row contains `REJECTED`; `grep -q REJECTED` passes |
| `tests/e2e/sltp/from_decision_tp_hit/scenario.py` | SLTP-01 PercentFromDecision TP-hit | VERIFIED | Contains `PercentFromDecision`; frozen avg_sold=120 = TP level (anchor=100, tp_pct=0.20) |
| `tests/e2e/sltp/from_fill_sl_hit/scenario.py` | SLTP-02 PercentFromFill SL-hit | VERIFIED | Contains `PercentFromFill`; frozen avg_sold=81 = SL level (anchor=fill=90, sl_pct=0.10) |
| `tests/e2e/sltp/from_decision_held/golden/orders.csv` | SLTP-03 held-to-end (children PENDING) | VERIFIED | 4 lines: header + ENTRY FILLED + SL STOP SELL PENDING@90 + TP LIMIT SELL PENDING@120 |
| `itrader/execution_handler/exchanges/simulated.py` | is-not-None fee/slippage knob fix | VERIFIED | Lines 497, 500-501, 520, 522, 524, 530-531: all use `if config.x is not None else <default>` pattern; commit 7815130 |

---

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `tests/e2e/conftest.py::_assemble` | `portfolio.closed_positions Position.commission` | key-merge on (entry_date, exit_date, side) | VERIFIED | Lines 326-344: builds commission_frame from `float(p.commission)` for each closed position; left-merge; fillna(0.0) for zero-trade leaves |
| `tests/e2e/conftest.py::_build_and_run` | `simulated._init_fee_model / _init_slippage_model` | `simulated.config = spec.exchange` then re-init | VERIFIED | Lines 268-270: re-init without touching `_supported_symbols` (comment at line 260 confirms PATTERNS A2) |
| `tests/e2e/strategies/scripted_emitter.py::__init__` | `BaseStrategyConfig.sltp_policy` | constructor kwarg | VERIFIED | Line 86: kwarg declared; line 103: `sltp_policy=sltp_policy` passed to `BaseStrategyConfig(...)` |
| `tests/e2e/cost/*/scenario.py` | simulated fee/slippage models via spec.exchange | ExchangeConfig + D-14 seam | VERIFIED | All 6 COST scenario.py files contain `ExchangeConfig(...)` with configured fee/slippage; confirmed via test execution (30 passed) |
| `tests/e2e/sltp/from_decision_*/scenario.py` | `OrderManager _bracket_levels(signal.price)` | PercentFromDecision sltp_policy | VERIFIED | 3 from_decision scenario files contain `PercentFromDecision`; frozen SL=90/TP=120 match decision-close(100) anchor formula |
| `tests/e2e/sltp/from_fill_*/scenario.py` | `OrderManager _create_fill_anchored_children` | PercentFromFill sltp_policy | VERIFIED | 3 from_fill scenario files contain `PercentFromFill`; frozen SL=81/TP=108 match fill-price(90) anchor formula, distinct from decision anchor |

---

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All 30 E2E scenarios pass | `poetry run pytest tests/e2e -q` | 30 passed in 0.64s | PASS |
| BTCUSD oracle byte-exact | `poetry run pytest tests/integration/test_backtest_oracle.py -q` | 3 passed in 6.12s | PASS |
| Full suite (777 tests) green | `poetry run pytest tests/ -q` | 777 passed in 12.79s | PASS |
| mypy --strict clean | `poetry run mypy itrader` | Success: no issues found in 160 source files | PASS |

---

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|---------|
| COST-01 | 07-01 | percent fee model on a round-trip | SATISFIED | `tests/e2e/cost/percent_fee/` frozen with commission=285.00 |
| COST-02 | 07-02 | maker_taker fee model — maker vs taker distinguished | SATISFIED | `tests/e2e/cost/maker_taker/` frozen with two distinct commission rows (21.375 / 70.416) |
| COST-03 | 07-02 | fixed slippage model | SATISFIED | `tests/e2e/cost/fixed_slippage/` frozen; `random_variation=False` |
| COST-04 | 07-02 | linear slippage model | SATISFIED | `tests/e2e/cost/linear_slippage/` frozen; `base_slippage_pct=Decimal("0")`; engine fix ensures zero honored |
| COST-05 | 07-02 | slippage not applied to limit fills | SATISFIED | `tests/e2e/cost/limit_no_slip/` frozen; LIMIT fill price = limit price exactly |
| COST-06 | 07-02 | combined fee+slippage round-trip cash math to the cent | SATISFIED | `tests/e2e/cost/combined_roundtrip/golden/summary.json` final_cash=18645.0 reconciled by VERIFY note |
| SIZE-01 | 07-03 | FixedQuantity sizing | SATISFIED | `tests/e2e/sizing/fixed_quantity/` frozen with qty=10 exactly |
| SIZE-02 | 07-03 | RiskPercent sizing off stop distance | SATISFIED | `tests/e2e/sizing/risk_percent/` frozen; closed trade quantity=10 from (10000*0.02)/20 formula |
| SIZE-03 | 07-03 | over-cash sizing → audited insufficient-funds rejection | SATISFIED | `tests/e2e/sizing/over_cash_reject/golden/orders.csv` shows REJECTED; summary.json trade_count=0 |
| SLTP-01 | 07-04 | PercentFromDecision — SL/TP priced at signal assembly | SATISFIED | 3 from_decision_* leaves frozen; SL/TP levels derive from decision-bar close (anchor=100) |
| SLTP-02 | 07-04 | PercentFromFill — SL/TP anchored to actual fill price | SATISFIED | 3 from_fill_* leaves frozen; SL/TP levels derive from next-bar-open fill (anchor=90) |
| SLTP-03 | 07-04 | SL-hit, TP-hit, and held-to-end exit outcomes | SATISFIED | All 6 SLTP leaves present; held leaves use opt-in orders.csv (PENDING) + summary trade_count=0 |

All 12 Phase 7 requirements satisfied. No orphaned requirements.

---

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `tests/e2e/cost/combined_roundtrip/scenario.py` | 108 | Comment states "fee is charged on the slipped notional, so both costs compound" — directly contradicts the engine truth and the same file's own VERIFY note | Warning (WR-01 from code review) | Maintenance hazard: a reader trusting this comment would hand-derive the wrong golden (283.10 not 285.00). The frozen golden is correct; only the comment is wrong. No VERIFY note fence is broken; the test still passes. |
| `itrader/execution_handler/exchanges/simulated.py` | 497, 500-501 | `float(config.fee_rate ...)` narrows Decimal to float before passing to PercentFeeModel / MakerTakerFeeModel | Warning (WR-02 from code review) | Latent correctness trap for fee rates with imprecise float repr (e.g. Decimal("0.07")). Round values used in Phase 7 scenarios are lossless through str(float()), so no current scenario is broken. Pre-dates Phase 7. |
| `tests/e2e/conftest.py` | 325-342 | commission merge on (entry_date, exit_date, side) not validated for uniqueness — a many-to-many violation would silently duplicate rows | Warning (WR-03 from code review) | Not triggered by any Phase 7 scenario (all single round-trips). Would manifest as confusing golden diff on future multi-trade leaves. `pandas merge(validate="one_to_one")` would convert silent failure to hard error. |

No TBD/FIXME/XXX debt markers found in any Phase 7 modified files.

Note: The three "placeholder" mentions in `over_cash_reject/scenario.py`, `from_decision_held/scenario.py`, and `from_fill_held/scenario.py` refer to the legitimate opt-in mechanism (placing an empty orders.csv file to activate the snapshot freeze) — these are not implementation stubs. The referenced golden files are populated and frozen.

---

### Human Verification Required

None. All must-haves are programmatically verifiable and verified. The phase is test-authoring only; no visual/UI/real-time behavior is in scope.

---

### Gaps Summary

No gaps. All 14 observable truths verified, all 12 requirements satisfied, all 30 E2E tests pass, mypy --strict clean on 160 files, BTCUSD oracle byte-exact.

**Three advisory warnings** were carried forward from the code review (07-REVIEW.md). None are blockers:
- WR-01: Contradicting comment in `combined_roundtrip/scenario.py` (maintenance hazard, golden and test are correct)
- WR-02: `float()` cast in simulated.py fee init path (latent trap for imprecise rates, not triggered by Phase 7 values)
- WR-03: Commission merge key not validated for uniqueness (no Phase 7 scenario triggers it)

These warnings are appropriate for follow-up in Phase 8 or a dedicated cleanup task but do not prevent the Phase 7 goal from being achieved.

---

_Verified: 2026-06-10T14:45:00Z_
_Verifier: Claude (gsd-verifier)_
