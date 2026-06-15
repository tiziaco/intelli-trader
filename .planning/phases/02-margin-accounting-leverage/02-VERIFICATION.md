---
phase: 02-margin-accounting-leverage
verified: 2026-06-15T16:30:00Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
---

# Phase 02: Margin Accounting & Leverage Verification Report

**Phase Goal:** A portfolio opens positions on reserved margin (initial_margin = notional / leverage), rejects/clips orders that exceed free margin, tracks maintenance margin per position, and can trade with configurable leverage > 1 — making a levered Kelly fraction > 1 expressible.
**Verified:** 2026-06-15T16:30:00Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|---------|
| 1 | Opening a position reserves `initial_margin = notional / leverage` against available cash (not full notional). [MARGIN-01] | VERIFIED | `admission_manager.py:275-281` branches on `enable_margin`: spot arm uses `notional + commission`, margin arm uses `notional / effective_leverage + commission`. `CashManager.lock_margin` then locks `aggregate_notional / leverage` position-keyed at fill time. `test_levered_long_scenario_parked` asserts `available == 6000` after a 10000-cash portfolio reserves 4000 = 20000/5. |
| 2 | An order exceeding available free margin is rejected (or clipped) rather than silently over-leveraging. [MARGIN-02] | VERIFIED | `admission_manager.py:286-301`: `InsufficientFundsError` from `portfolio_handler.reserve(...)` catches the over-margin case, transitions order PENDING→REJECTED with `triggered_by=CASH_RESERVATION`, stores the audited entity, returns failure_result with nothing emitted. `test_over_margin_order_is_rejected_via_audited_path` in `test_admission_rules.py` (line 629) asserts queue empty, one REJECTED entity stored, free cash unchanged. |
| 3 | Maintenance margin is tracked and queryable per open position. [MARGIN-03] | VERIFIED | `portfolio_handler.py:306-341`: `maintenance_margin` computes `Σ (instrument.maintenance_margin_rate × |size| × current_price)` on demand via the injected Universe; `margin_ratio` = `total_equity / maintenance` returning `Decimal("0")` sentinel when flat. 5 tests in `test_portfolio_handler.py` (lines 590-670) cover the formula, zero-positions sentinel, honest sub-1 reading when breached (D-16). The parked levered-long e2e asserts `maintenance == 160`, `margin_ratio == 162.5` on the adverse mark. |
| 4 | A portfolio configured with leverage > 1 posts `notional/L` as margin; a Kelly fraction > 1 produces `notional = f × equity`. [LEV-01/LEV-02] | VERIFIED | `LeveredFraction` in `core/sizing.py:154` (guarded `f > 0`), resolver arm at `sizing_resolver.py:129-137` computes `qty = (policy.fraction * equity) / price`. `_effective_leverage` in `admission_manager.py:573-601` caps at `min(signal.leverage, Instrument.max_leverage, portfolio.max_leverage)`. `test_margin_makes_otherwise_unaffordable_order_affordable` (admission_rules.py:654) proves a notional > free cash is fundable under leverage. Parked e2e: requested=20, instr_cap=10, pf_cap=5 → effective=5; f=2 × 10000 = 20000 notional; 20000/5 = 4000 reserved. |
| 5 | Strategy-declared leverage flows end-to-end (signal→order→fill→transaction→position) carrying the admission-clamped effective leverage for ALL order types (MARKET/LIMIT/STOP). [LEV-03] | VERIFIED | Tracing the full chain: `strategies_handler.py:184-188` carries `intent.leverage` onto `SignalEvent`; `admission_manager.py:369` calls `_effective_leverage`; `_build_primary_order` passes `leverage=effective_leverage` on ALL THREE arms (MARKET line 374, LIMIT lines 386-389, STOP lines 401-403); `order.py:228-262` `new_stop_order`/`new_limit_order` accept keyword-only `leverage` and set via `to_money`; `events/order.py:59-62,122-125` carries it to `OrderEvent`; `events/fill.py:69-72,146-149` carries it to `FillEvent`; `transaction.py:41-47,149-151` carries it to `Transaction`; `position_manager.py:238-241` sets `Position.leverage` from the transaction. CR-01 closed by plan 02-08 — LIMIT/STOP arms now also carry the clamped leverage. Three dedicated tests in `test_admission_rules.py:669-709` verify MARKET/LIMIT/STOP all produce `order.leverage == Decimal("5")` when signal requests 20 and cap is 5. Parked e2e asserts `position.leverage == Decimal("5")` and `locked == Decimal("4000")`. |

**Score:** 5/5 truths verified

### Owner-Gate Constraints

| Constraint | Status | Evidence |
|-----------|--------|---------|
| SMA_MACD oracle byte-exact: 134 trades / final_equity 46189.87730727451 | VERIFIED | `poetry run pytest tests/integration/test_backtest_oracle.py -x` → 3 passed in 5.47s. Golden `tests/golden/summary.json` confirms `trade_count: 134`, `final_equity: 46189.87730727451`. Oracle test passes twice (determinism double-run). |
| `mypy --strict` clean across `itrader` | VERIFIED | `poetry run mypy itrader` → "Success: no issues found in 185 source files" |
| Decimal end-to-end (no `Decimal(float)`; `float()` only at serialization/logging edge) | VERIFIED | `float()` calls in phase files are exclusively at serialization/logging edges: structured log dict values, exception constructor fields (`required_cash=float(...)`), `get_summary()` reporting dict. No `Decimal(float(...))` found in `portfolio.py`, `cash_manager.py`, `admission_manager.py`, or `order.py`. `Decimal(str(...))` in `position_manager.py:171` is the IN-02 residual (tracked as style-only, correct string path). |
| Full suite green (`make test`) | VERIFIED | `make test` → 1089 passed in 12.76s |
| Determinism double-run byte-identical | VERIFIED | Oracle test run twice consecutively: both pass, same 134/46189.87730727451 result. |

### Required Artifacts

| Artifact | Expected | Status | Details |
|---------|---------|--------|---------|
| `itrader/order_handler/order.py` | `new_limit_order`/`new_stop_order` accept keyword-only `leverage` and set on entity (CR-01) | VERIFIED | Lines 228-262: both factories accept `leverage: Decimal = Decimal("1")` keyword-only parameter and set `leverage=to_money(leverage)` in `cls(...)` constructor, mirroring `new_order`. |
| `itrader/order_handler/admission/admission_manager.py` | LIMIT/STOP arms pass `leverage=effective_leverage` (CR-01) | VERIFIED | Lines 376-404: MARKET arm (374-375), LIMIT arm (376-389), STOP arm (391-403) all pass `leverage=effective_leverage` computed on line 369. |
| `itrader/portfolio_handler/portfolio.py` | `_process_transaction_margin` over-close guard raises (CR-02) | VERIFIED | Lines 390-404: guard at line 399 `if not is_increase and transaction.quantity > prior_qty: raise InvalidTransactionError(...)` fires BEFORE `process_position_update` — no state mutation occurs. |
| `itrader/portfolio_handler/cash/cash_manager.py` | `available_balance` subtracts `locked_margin_total`; `lock_margin`/`release_margin` lifecycle | VERIFIED | Lines 107-129: `available_balance` = `balance - reserved - locked_margin_total`. Lines 478-519: `lock_margin` / `release_margin` with position-keyed storage. |
| `itrader/portfolio_handler/portfolio_handler.py` | `maintenance_margin`/`margin_ratio` queryable via Universe read-model | VERIFIED | Lines 306-341: `maintenance_margin` sums `mmr × |size| × price` over open positions using injected `_universe`; `margin_ratio` = equity/maintenance with `Decimal("0")` sentinel. |
| `tests/e2e/levered_long/test_levered_long_scenario.py` | Parked (not frozen golden) — D-17 | VERIFIED | File header clearly states "PARKED — NOT A GOLDEN"; test function is `test_levered_long_scenario_parked`; module docstring explains re-baseline deferred to Phase 4/XVAL-01. Test passes via hand-computed literals. |
| `.planning/phases/02-margin-accounting-leverage/deferred-items.md` | Residual WR/IN findings tracked (CR-02-residual + WR-01..05 + IN-01..03) | VERIFIED | Table present with all 10 residual entries (CR-01 and CR-02-guard noted CLOSED), WR-04 present as confirmed by `grep -q "WR-04"`. |

### Key Link Verification

| From | To | Via | Status | Details |
|-----|-----|-----|-------|---------|
| `StrategiesHandler.calculate_signals` | `SignalEvent.leverage` | `leverage=intent.leverage` at line 188 | VERIFIED | Fan-out carries strategy-declared leverage onto every SignalEvent. |
| `AdmissionManager._build_primary_order` | `Order.new_limit_order`/`new_stop_order` | `leverage=effective_leverage` on LIMIT/STOP arms | VERIFIED | Lines 386-389, 401-403 — CR-01 fix confirmed. |
| `Order` | `OrderEvent` | `leverage=getattr(order, 'leverage', Decimal("1"))` in `OrderEvent.new_event()` | VERIFIED | `events/order.py:122-125` |
| `OrderEvent` | `FillEvent` | `leverage=getattr(order, "leverage", Decimal("1"))` in `FillEvent.new_fill()` | VERIFIED | `events/fill.py:146-149` |
| `FillEvent` | `Transaction` | `leverage=getattr(filled_order, "leverage", Decimal("1"))` | VERIFIED | `transaction.py:149-151` |
| `Transaction` | `Position.leverage` | `leverage=getattr(transaction, "leverage", Decimal("1"))` at Position open | VERIFIED | `position_manager.py:238-241`; scale-in clamps to `position.leverage` (D-06 one-leverage-per-position invariant at line 162-175). |
| `Portfolio._process_transaction_margin` | `CashManager.lock_margin` | `position.aggregate_notional / leverage` at lines 428, 443 | VERIFIED | Lock uses `position.leverage` (the admission-clamped effective leverage), so `lock == admission_reservation` (LEV-03 invariant). |
| `enable_margin=False` spot path | no division, no instrument read | real `if/else` branch in `process_transaction` and `_effective_leverage` | VERIFIED | `portfolio.py:303-306` branches on `config.trading_rules.enable_margin`; `admission_manager.py:586-588` returns `Decimal("1")` immediately when margin off. NO `/1` division on the spot arm (Pitfall 4 avoided). |

### Data-Flow Trace (Level 4)

The levered-long e2e (`test_levered_long_scenario_parked`) drives the full SIGNAL→ORDER→FILL→PORTFOLIO path through the real engine (no mocks injected onto the queue), asserting the live read-model state at every bar. Key data-flow assertions verified at runtime:

| Flow | Asserted Value | Status |
|------|----------------|--------|
| Admission reservation (decision bar 2020-01-02) | `available == Decimal("6000")` (10000 - 4000 = 10000 - 20000/5) | VERIFIED |
| Position leverage at fill (2020-01-03) | `position.leverage == Decimal("5")` (min(20,10,5)) | VERIFIED |
| Position-life locked margin (2020-01-03) | `locked == Decimal("4000")` (20000/5 == reservation) | VERIFIED |
| Maintenance margin at price 100 | `maintenance == Decimal("200")` (0.01 × 200 × 100) | VERIFIED |
| Honest adverse mark (2020-01-04) | `margin_ratio == Decimal("162.5")` (no clamp, D-16) | VERIFIED |
| Close PnL settled (2020-01-06) | `available == Decimal("14000")`, `locked == Decimal("0")` | VERIFIED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---------|---------|--------|--------|
| Oracle stays byte-exact under all new margin code | `poetry run pytest tests/integration/test_backtest_oracle.py -x -q` | 3 passed, 5.47s | PASS |
| CR-01 LIMIT/STOP leverage threading | `poetry run pytest tests/unit/order/ -x -q` | 51 passed, 0.11s | PASS |
| CR-02 over-close guard | `poetry run pytest tests/unit/portfolio/ -x -q` | 232 passed, 0.25s | PASS |
| Full suite | `make test` | 1089 passed, 12.76s | PASS |
| Parked levered-long e2e | `poetry run pytest tests/e2e/levered_long/ -v` | 1 passed (test_levered_long_scenario_parked) | PASS |
| mypy --strict | `poetry run mypy itrader` | 185 source files, no issues | PASS |

### Probe Execution

Step 7c: SKIPPED — no `scripts/*/tests/probe-*.sh` conventional probes; phase is not a migration/tooling phase.

### Requirements Coverage

| Requirement | Plans | Description | Status | Evidence |
|------------|-------|-------------|--------|---------|
| MARGIN-01 | 02-00, 02-04 | Opening reserves `initial_margin = notional / leverage` | SATISFIED | `admission_manager.py:277-279` reserves `notional/L + commission`; `portfolio.py:426-428` locks `aggregate_notional/leverage` at fill; parked e2e asserts 4000 reserved and 4000 locked (both == notional/L = 20000/5). |
| MARGIN-02 | 02-00, 02-03 | Orders exceeding free margin rejected/clipped | SATISFIED | `admission_manager.py:286-301` catches `InsufficientFundsError` → audited REJECTED; `test_over_margin_order_is_rejected_via_audited_path` verifies queue empty + 1 REJECTED entity. |
| MARGIN-03 | 02-05 | Maintenance margin tracked and queryable per position | SATISFIED | `portfolio_handler.py:306-341` implements `maintenance_margin`/`margin_ratio` on demand; 5 unit tests + parked e2e cover formula, sentinel, honest sub-1 reading. |
| LEV-01 | 02-01, 02-03 | Configurable leverage > 1 via `enable_margin` / config hooks | SATISFIED | `PortfolioConfig.trading_rules.enable_margin: bool`, `max_leverage: Decimal` (ge=1); `_effective_leverage` cap in admission_manager. |
| LEV-02 | 02-02 | Kelly fraction > 1 expressible (`notional = f × equity`) | SATISFIED | `LeveredFraction` in `core/sizing.py:154`; resolver arm `sizing_resolver.py:129-137`; f>1 gated by `_enforce_leverage_admission` requiring `enable_margin=True`. |
| LEV-03 | 02-07, 02-08 | Strategy-declared leverage flows end-to-end for ALL order types | SATISFIED | Full chain verified (StrategiesHandler → Signal → Order → OrderEvent → FillEvent → Transaction → Position); CR-01 closed LIMIT/STOP gap; 3 admission tests + parked e2e confirm end-to-end. |

**Orphaned requirements check:** REQUIREMENTS.md shows MARGIN-01/02/03 + LEV-01/02/03 all mapped to Phase 2 with status "Complete". Zero orphaned requirements.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|---------|--------|
| `itrader/order_handler/order.py` | 373 | `TODO: check if i have to store the state changes permanently in sql when in live trading / production` | INFO | Pre-existing TODO about live SQL persistence; references the live/production design item (a future phase concern). Not a phase-2 deliverable gap. Not referenced by a formal issue ticket, but this file pre-dates this phase and this TODO is not a new unresolved debt marker introduced in phase 2. |
| `itrader/portfolio_handler/position/position_manager.py` | 171 | `Decimal(str(signal_leverage))` instead of `to_money(signal_leverage)` | INFO (IN-02) | Tracked in deferred-items.md as style-only; correct string path, no `Decimal(float)` violation. |

**Debt marker gate assessment:** The `TODO` at `order.py:373` is a pre-existing line (not introduced by this phase — the commit history shows this file was modified by this phase only to add the `leverage` keyword parameter, not this line). It concerns live SQL persistence (a future design item), not an unresolved functional gap in the margin accounting feature. It does not constitute an unresolved Phase 2 debt marker under the gate rules (the gate targets unresolved TBD/FIXME/XXX; this TODO names a live-mode design question, not a broken spot/margin path). Classified as INFO.

### Code Review Blocker Status

| Finding | Status | Evidence |
|---------|--------|---------|
| CR-01: LIMIT/STOP entry orders dropped effective leverage | CLOSED by 02-08 | `new_limit_order`/`new_stop_order` accept `leverage` kwarg; admission LIMIT/STOP arms pass `leverage=effective_leverage`. Commits `fff0b3b` (RED) + `a27e275` (GREEN) confirmed in git log. 3 admission-level tests verify clamped leverage on all 3 order types. |
| CR-02: Partial-close margin settlement mis-credits on over-close | MITIGATED by 02-08 (fail-loud guard) | `portfolio.py:399-404` raises `InvalidTransactionError` before any mutation when `transaction.quantity > prior_qty`. Commits `bc35629` (RED) + `0448ad9` (GREEN) confirmed. Full flip-settlement economics tracked as CR-02-residual for Phase 3. |

### Residual Findings (legitimately deferred)

All 8 residual findings (CR-02-residual, WR-01 through WR-05, IN-01 through IN-03) are correctly classified as deferred — they are either:
- Unreachable on the SMA_MACD spot golden path (`enable_margin=False` — oracle-dark)
- Gated off structurally (shorts/flips blocked at `strategies_handler.add_strategy`)
- Style-only (IN-02: `Decimal(str(...))` vs `to_money(...)`)
- Future-phase concerns (WR-02: None-guard for universe; IN-03: single global MMR rate)

None is a silent gap in this phase's stated goal. All require shorts/flips to become reachable (Phase 3) or a liquidation trigger (Phase 4) before they matter.

### Levered-Long E2E Status (D-17)

`tests/e2e/levered_long/test_levered_long_scenario.py` is correctly PARKED:
- Test function name: `test_levered_long_scenario_parked`
- Module docstring: "PARKED — NOT A GOLDEN ... Phase 2 freezes NO new leveraged golden (D-16/D-17)"
- Assertions are hand-computed literals with arithmetic shown inline
- Does NOT use the `run_scenario` / `golden/` golden-diff harness
- The single owner-gated accounting-core re-baseline is correctly deferred to Phase 4/XVAL-01

Test passes (1 passed in 0.10s), exercising all 5 phase requirements (MARGIN-01/02/03, LEV-01/02/03) end-to-end through the real engine.

### Human Verification Required

None. All phase goal items are programmatically verifiable and verified.

### Gaps Summary

No gaps. All 5 observable truths verified, all owner-gate constraints satisfied, both review blockers (CR-01/CR-02) closed by plan 02-08 with confirmed commit history and passing tests, full suite green (1089), mypy clean (185 files), oracle byte-exact (134/46189.87730727451), determinism confirmed by double-run.

---

_Verified: 2026-06-15T16:30:00Z_
_Verifier: Claude (gsd-verifier)_
