---
phase: 04-liquidation-cross-validation-re-baseline
verified: 2026-06-16T11:35:56Z
status: passed
score: 9/9
overrides_applied: 0
---

# Phase 04: Liquidation & Cross-Validation Re-baseline — Verification Report

**Phase Goal:** Deliver the isolated-margin liquidation engine on the BAR route (LIQ-01/02/03) and the owner-gated accounting-core golden re-baseline cross-validated against backtesting.py + backtrader (XVAL-01), with SMA_MACD staying byte-exact (134 / 46189.87730727451, D-11).

**Verified:** 2026-06-16T11:35:56Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Isolated liq-price formula (D-01-CORR): long `(entry - WB/size)/(1-MMR)`, short `(entry + WB/size)/(1+MMR)`, producing 80.808.../118.811... for the worked case | VERIFIED | `_isolated_liq_price` at `portfolio_handler.py:400-421` uses `Decimal("1")` constants, pure arithmetic, no float. Unit tests `test_isolated_liq_price_long` + `test_isolated_liq_price_short` pass. |
| 2 | Bar-close breach check runs on the BAR route AFTER per-portfolio mark + carry pass (D-02 placement) | VERIFIED | `update_portfolios_market_value` at line 780 calls `_run_liquidation_pass` after the per-portfolio mark+carry loop. 7/7 e2e leaves pass. |
| 3 | Realized loss floored so equity cannot drop below -WB — DEF-01-C closed (D-03-CORR/D-07) | VERIFIED (corrected post-review — see note) | **CORRECTION (CR-01, fix `b461db0`):** the loss bound is delivered by settling the forced close AT the isolated maintenance liq price (D-03 automatic floor), NOT by an explicit `min(realized_loss + penalty, WB)` clamp. The `_capped_realized_loss` helper this row originally cited was dead code (test-only, structurally unreachable when fee_rate < MMR) and has been removed; the false attribution was corrected across docstrings/SUMMARY/PLAN/e2e. The bound itself holds (gap-through regression `test_liquidation_fills_at_liq_price_on_gap_through` pins fill-at-liq-price). |
| 4 | Penalty `= liquidation_fee_rate × |size| × liq_price` rides `FillEvent.commission` (D-05/LIQ-02) | VERIFIED | `_liquidation_penalty` at `portfolio_handler.py:435-442`. `forced_liq_long` e2e asserts `commission == 80.808080...` |
| 5 | Forced close mints a REAL Order tagged `OrderTriggerSource.LIQUIDATION`, registered in `order_storage` via `set_order_storage` seam, reconciling EXECUTED→FILLED with no new FillStatus (LIQ-03) | VERIFIED | `_liquidate_position` at `portfolio_handler.py:517-578` calls `self._order_storage.add_order(order)` + `FillEvent.new_fill("EXECUTED", ...)`. Unit test `test_liquidation_reconcile_executed_to_filled` passes. `test_no_new_fill_status` confirms no new status. |
| 6 | `set_order_storage` write-seam wired in `compose.py` and `live_trading_system.py` (LIQ-03 wiring) | VERIFIED | `compose.py:218-222` calls `portfolio_handler.set_order_storage(order_storage)` after OrderHandler construction. `live_trading_system.py:181` adds live parity. Grep confirmed both sites. |
| 7 | SMA_MACD oracle stays byte-exact 134 / 46189.87730727451 (D-11) — liquidation engine oracle-dark on spot path | VERIFIED | `poetry run pytest tests/integration/test_backtest_oracle.py -x` → 3 passed. The liquidation engine never fires on the SMA_MACD spot path (no locked margin, `liquidation_fee_rate=0`). |
| 8 | Multi-breach deterministic sort `(ticker, open_time, position_id)` + double-run byte-identical | VERIFIED | `_collect_breaches` sorts by `(ticker, open_time, position_id)` (Pitfall 3). `scripts/determinism_liquidation_double_run.py` → "DETERMINISM OK — liquidation double-run byte-identical". |
| 9 | XVAL-01: owner-gated accounting-core golden frozen; CROSS-VALIDATION-ACCOUNTING.md `Status: APPROVED` with attribution (tiziaco, 2026-06-16); all 7 e2e leaves carry FROZEN freeze-provenance banners | VERIFIED | `tests/golden/CROSS-VALIDATION-ACCOUNTING.md` line 138: `Status: APPROVED (2026-06-16, project owner — Approved-by: tiziaco (tiziano.iaco@gmail.com))`. All 7 e2e scenario leaves have `FROZEN — ACCOUNTING-CORE GOLDEN` banner in module docstring. No PARKED banners remain at module-docstring level. |

**Score:** 9/9 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/portfolio_handler/portfolio_handler.py` | BAR-route liquidation engine + set_order_storage seam | VERIFIED | Contains `_isolated_liq_price`, `_liquidation_penalty`, `_liquidate_position`, `_run_liquidation_pass`, `set_order_storage`. (`_capped_realized_loss` removed in CR-01 fix `b461db0` — was dead code; loss bound is fill-at-liq-price. `_collect_breaches` was a dead duplicate, see REVIEW WR findings.) |
| `itrader/trading_system/compose.py` | `set_order_storage` injection after OrderHandler construction | VERIFIED | Lines 218-222: `portfolio_handler.set_order_storage(order_storage)` with SAME instance. |
| `itrader/trading_system/live_trading_system.py` | Live-parity `set_order_storage` injection | VERIFIED | Line 181: `self.portfolio_handler.set_order_storage(order_storage)`. |
| `itrader/core/enums/order.py` | `OrderTriggerSource.LIQUIDATION = "liquidation"` | VERIFIED | Line 193: present, tab-indented, `# LIQ-03` comment. |
| `itrader/core/instrument.py` | `liquidation_fee_rate: Decimal = Decimal("0")` frozen field | VERIFIED | Line 98: field present with `D-06` comment. |
| `itrader/config/portfolio.py` | `TradingRules.liquidation_fee_rate = Field(default=Decimal("0"), ge=0)` | VERIFIED | Lines 83-86: present. |
| `tests/unit/portfolio/test_liquidation.py` | LIQ-01/02 unit tests green | VERIFIED | 7 tests, all pass. |
| `tests/unit/order/test_liquidation_reconcile.py` | LIQ-03 mirror reconcile tests green | VERIFIED | 5 tests, all pass. |
| `tests/unit/portfolio/test_wr04_lock_fits_buying_power.py` | WR-04 regression test green | VERIFIED | 3 tests, all pass (confirmed in plan 02 evidence). |
| `tests/e2e/forced_liq_long/test_forced_liq_long_scenario.py` | White-box forced-liq long e2e, FROZEN | VERIFIED | Passes, real engine assertions, FROZEN banner. |
| `tests/e2e/forced_liq_short/test_forced_liq_short_scenario.py` | White-box forced-liq short e2e, FROZEN | VERIFIED | Passes, real engine assertions, FROZEN banner. |
| `tests/e2e/levered_long_into_liquidation/test_levered_long_into_liquidation_scenario.py` | White-box levered-long-into-liquidation e2e, FROZEN | VERIFIED | Passes, FROZEN banner. |
| `scripts/cross_validate_accounting.py` | Standalone sibling crossval driver (not modifying `cross_validate.py`) | VERIFIED | File exists. `git diff scripts/cross_validate.py` empty — base driver byte-unchanged. |
| `scripts/crossval/short_run.py`, `levered_run.py`, `liquidation_run.py` | Three accounting crossval runners | VERIFIED | All three files exist. |
| `scripts/determinism_liquidation_double_run.py` | Liquidation determinism double-run script | VERIFIED | File exists; output: "DETERMINISM OK — liquidation double-run byte-identical". |
| `tests/golden/CROSS-VALIDATION-ACCOUNTING.md` | Evidence doc, APPROVED Owner Sign-Off, provenance | VERIFIED | Exists; line 138 `Status: APPROVED`; full attribution; 0 BUG / 25 LEGITIMATE-DIFFERENCE verdict. |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `update_portfolios_market_value` BAR route | `_run_liquidation_pass` | Called after mark+carry loop at line 780 | WIRED | LIQ-01/02/03 D-02 placement confirmed by reading and by e2e tests. |
| `_liquidate_position` | `FillEvent.new_fill("EXECUTED", ...)` on `global_queue` | Direct `self.global_queue.put(fill_event)` — NOT ExecutionHandler | WIRED | D-04 — settle on breach bar, not next-bar-open. |
| `_liquidate_position` | `self._order_storage.add_order(order)` | `set_order_storage` seam injected in `compose.py` + `live_trading_system.py` | WIRED | Pitfall 4 guard: without registration, ReconcileManager.on_fill early-returns. Test `test_unregistered_order_no_ops_mirror` confirms. |
| `compose.py` `compose_engine` | `PortfolioHandler.set_order_storage(order_storage)` | SAME `order_storage` instance the OrderHandler/ReconcileManager hold | WIRED | Line 222 in compose.py. Single shared mirror. |
| Minted `FillEvent(EXECUTED)` | `ReconcileManager.on_fill` EXECUTED→FILLED | Existing ORDER FILL route; LIQUIDATION order registered so early-return skipped | WIRED | `test_liquidation_reconcile_executed_to_filled` passes: order reaches FILLED in storage. |
| `scripts/cross_validate_accounting.py` | `backtesting.py` + `backtrader` runners | `scripts/crossval/short_run.py`, `levered_run.py`, `liquidation_run.py` | WIRED | Script-only (no test-file import of reference engines; grep confirms). |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `portfolio_handler.py _run_liquidation_pass` | `close` (bar close price), `wb` (locked margin), `mmr`, `fee_rate` | `BarEvent.close`, `CashManager.get_locked_margin_for`, `Universe.instrument(ticker).maintenance_margin_rate/liquidation_fee_rate` | Yes — live engine data per bar | FLOWING |
| `test_forced_liq_long_scenario.py` | Engine state after tick-by-tick run | Real `TradingSystem` + `BacktestBarFeed` drive | Yes — real engine; `liq_price 80.81`, `penalty 80.808...`, `realised_pnl -3918.808...` observed in determinism run output | FLOWING |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Oracle byte-exact 134 / 46189.87730727451 | `poetry run pytest tests/integration/test_backtest_oracle.py -x -q` | 3 passed | PASS |
| LIQ unit tests green (12 tests) | `poetry run pytest tests/unit/portfolio/test_liquidation.py tests/unit/order/test_liquidation_reconcile.py -q` | 12 passed in 0.08s | PASS |
| Seven-leaf accounting-core e2e gate | `poetry run pytest tests/e2e/forced_liq_long tests/e2e/forced_liq_short tests/e2e/levered_long_into_liquidation tests/e2e/levered_long tests/e2e/short_roundtrip tests/e2e/short_carry tests/e2e/partial_cover -q` | 7 passed in 0.12s | PASS |
| Full suite (1146 tests) | `PYTHONPATH="$PWD" poetry run pytest tests/ -q --tb=no` | 1146 passed in 13.99s | PASS |
| mypy --strict across itrader | `poetry run mypy --strict itrader` | Success: no issues in 185 source files | PASS |
| Liquidation determinism double-run | `PYTHONPATH="$PWD" poetry run python scripts/determinism_liquidation_double_run.py` | "DETERMINISM OK — liquidation double-run byte-identical; final_balance: 6081.191919191919191919191919" | PASS |
| SMA_MACD golden CSVs byte-unchanged | `git diff -- tests/golden/trades.csv tests/golden/equity.csv tests/golden/summary.csv` | Empty (no changes) | PASS |
| No reference-engine imports in tests/ | `grep -rln "import backtesting\|import backtrader" tests/` | No output | PASS |

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| LIQ-01 | 04-02, 04-03 | Bar-close maintenance-margin breach → forced-close FillEvent, loss floored at WB | SATISFIED | `_run_liquidation_pass` wired on BAR route; loss floored by **fill-at-liq-price** (CR-01 correction `b461db0` — not an explicit clamp); gap-through regression `test_liquidation_fills_at_liq_price_on_gap_through` green; `test_forced_liq_long_scenario` + `test_forced_liq_short_scenario` green. WR-04 call-order fix prerequisite in 04-02. |
| LIQ-02 | 04-01, 04-03 | Configurable liquidation penalty/fee charged | SATISFIED | `Instrument.liquidation_fee_rate` (default 0, oracle-dark); `_liquidation_penalty` = `fee_rate × size × liq_price`; rides `FillEvent.commission`; `test_liquidation_penalty` green. |
| LIQ-03 | 04-01, 04-03 | Forced liq reuses `FillStatus.EXECUTED`, mints `OrderTriggerSource.LIQUIDATION`-tagged Order, reconciles via existing mirror path, no new FillStatus | SATISFIED | `OrderTriggerSource.LIQUIDATION` member exists; `_liquidate_position` registers order in `_order_storage` via `set_order_storage` seam; `test_liquidation_reconcile_executed_to_filled` asserts FILLED in mirror; `test_no_new_fill_status` confirms no new FillStatus. |
| XVAL-01 | 04-04, 04-05 | Short/levered-long/liquidation cross-validated; golden freezes only after explicit owner sign-off | SATISFIED | `CROSS-VALIDATION-ACCOUNTING.md` `Status: APPROVED` (tiziaco, 2026-06-16); 7 scenario leaves FROZEN with provenance banner; `scripts/cross_validate_accounting.py` is standalone sibling (base `cross_validate.py` byte-unchanged); trade-level reconciliation PRIMARY green for short + levered; liquidation directionally corroborated (D-08). |

---

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `tests/e2e/levered_long/test_levered_long_scenario.py` | 261 | Function docstring contains legacy "PARKED" text (`def test_levered_long_scenario_parked()`) | Info | No runtime impact — module-level docstring is FROZEN; function was not renamed after freeze. Not a stub (no `pytest.skip`; test runs and passes). |
| `tests/e2e/short_roundtrip/test_short_roundtrip_scenario.py` | ~186 | Same: function docstring contains legacy "PARKED" text | Info | Same — module FROZEN, test runs. |
| `tests/e2e/short_carry/test_short_carry_scenario.py` | ~184 | Same | Info | Same. |
| `tests/e2e/partial_cover/test_partial_cover_scenario.py` | ~162 | Same | Info | Same. |

No blockers. All four are cosmetic residue (the legacy function docstrings were not updated when the module banner was flipped to FROZEN). The tests run, pass, and are not skipped. No TBD/FIXME/XXX markers found in any phase-modified production file.

---

## Human Verification Required

None. All truths are mechanically verifiable and have been verified by running the code.

---

## Gaps Summary

No gaps. All must-haves are VERIFIED.

The four "PARKED" residues in function docstrings are informational only — they do not affect test collection, execution, or correctness. The module-level banners that drive the freeze semantics all correctly read `FROZEN — ACCOUNTING-CORE GOLDEN`.

---

_Verified: 2026-06-16T11:35:56Z_
_Verifier: Claude (gsd-verifier)_
