---
phase: 05-signal-contract-reconcile-fragile
verified: 2026-06-13T00:00:00Z
status: passed
score: 5/5
overrides_applied: 0
---

# Phase 5: Signal Contract & Reconcile (FRAGILE) — Verification Report

**Phase Goal:** Complete the signal/order contract — a strategy specifies per-intent ENTRY price and `order_type`, action becomes `Side`-typed with the position snapshot threaded once — AND streamline the `on_fill` reconciliation / `should_release` flow, touching the FRAGILE `reconcile/` path once under a single owner-gated re-baseline + external cross-validation.
**Verified:** 2026-06-13
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #   | Truth | Status | Evidence |
| --- | ----- | ------ | -------- |
| 1 | A strategy can specify a per-intent limit or stop ENTRY price, threaded SignalIntent → SignalEvent → Order.new_limit_order/new_stop_order (SIG-01) | VERIFIED | `buy_limit`/`buy_stop`/`sell_limit`/`sell_stop` exist in `base.py` (4 of 4 count); `SignalIntent.order_type: OrderType` + `entry_price: Decimal | None` in `core/sizing.py`; fan-out reads `intent.entry_price` for LIMIT/STOP; existing Order factories accept `action: Side` |
| 2 | A strategy can specify entry order_type per intent (MARKET/LIMIT/STOP), not fixed per strategy instance; per-instance `Strategy.order_type` attr retired; handler fan-out reads `intent.order_type` (SIG-02) | VERIFIED | `grep -c "order_type: OrderType = OrderType.MARKET" base.py` == 0 (attr retired); `grep -c "order_type=intent.order_type" strategies_handler.py` == 2; `grep -c "order_type=strategy.order_type" strategies_handler.py` == 0; `to_dict()` no longer emits `order_type` key; MARKET branch keeps `to_money(bar.close)` byte-exact |
| 3 | `Order.action` and `_PendingBracket.action` are typed `Side` (not str); position snapshot threaded once through admission→sizing (triple get_position removed); W4-04 validator-overlap doc updated (SIG-03) | VERIFIED | `order.py:49 action: Side`; `bracket_book.py:42 action: Side`; `new_stop_order`/`new_limit_order` params `action: Side`; `levels.py` `action: Side` param, `is Side.SELL` compare; `order_validator.py` `not in (Side.BUY, Side.SELL)` identity compare; `admission_manager.py` `snap` captured ONCE in `process_signal` (lines 143-148), threaded to 3 gate/sizing methods; `.planning/codebase/CONVENTIONS.md` W4-04 section updated with SIG-03 Side retype note |
| 4 | `on_fill` reconciliation + `should_release` release-in-`finally` flow streamlined; idempotent release on EVERY terminal reconciliation (EXECUTED→FILLED, CANCELLED→CANCELLED, REFUSED→REJECTED); `try`/`finally` byte-identical (RECON-01) | VERIFIED | 5 named helpers: `_classify`, `_apply_executed`, `_apply_cancelled`, `_apply_refused`, `_release_reservation`; `finally:` statement inside `on_fill` (line 276, not extracted); `should_release = True` at line 222 (AFTER terminal status, BEFORE further work); `if not body_raised: raise` gate preserved; 6 safety-net tests green (body-raise-releases, unknown-status-holds, 3 terminal releases) |
| 5 | New LIMIT golden frozen ONLY after explicit owner sign-off + full attribution; validated by backtesting.py + backtrader; entry fills on LATER bar, marketable-limit fills at OPEN; entry-fill→SL/TP-bracket exercised; existing oracle 134 / 46189.87730727451 unchanged; mypy --strict clean; determinism double-run byte-identical | VERIFIED | `tests/golden/CROSS-VALIDATION-LIMIT.md`: `grep -ci "sign-off\|signed\|approved"` == 6; owner tiziaco signed 2026-06-13; entry A fills 2018-09-05 (later bar); entry B fills at OPEN 6487.39 (marketable); A1 divergence dispositioned LEGITIMATE-DIFFERENCE; `tests/integration/test_backtest_oracle.py` 3 passed (134 / 46189.87730727451); `poetry run mypy --strict` — Success, 182 source files; `poetry run pytest tests/ -q` — 978 passed |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| -------- | -------- | ------ | ------- |
| `itrader/core/sizing.py` | SignalIntent.order_type: OrderType + entry_price: Decimal \| None | VERIFIED | Both fields present; TODO comment removed; `OrderType` imported |
| `itrader/strategy_handler/base.py` | buy_limit/buy_stop/sell_limit/sell_stop factories; order_type attr retired; to_dict drops order_type | VERIFIED | 4 factories with required keyword-only `price`; class attr retired; to_dict clean |
| `itrader/strategy_handler/signal_record.py` | SignalRecord.order_type + entry_price audit fields | VERIFIED | Both fields present with Attributes docstring entries |
| `itrader/strategy_handler/strategies_handler.py` | Per-intent fan-out reading intent.order_type / intent.entry_price | VERIFIED | Fan-out uses `intent.order_type`; MARKET keeps `to_money(bar.close)`; LIMIT/STOP use `intent.entry_price` |
| `tests/unit/strategy/test_signal_factories.py` | Wave-0 unit coverage for 6 factories + MARKET byte-exactness | VERIFIED | 18 tests, all passing |
| `itrader/order_handler/order.py` | Order.action: Side + new_stop_order/new_limit_order action: Side params | VERIFIED | Entity field and both factory params narrowed to Side |
| `itrader/order_handler/brackets/bracket_book.py` | _PendingBracket.action: Side | VERIFIED | Field typed Side; W2-02 deferred note closed |
| `itrader/order_handler/admission/admission_manager.py` | Single threaded Position snapshot | VERIFIED | 2 get_position call sites (process_signal + create_orders_from_signal), rest are comments; 3 method-level fetches removed |
| `.planning/codebase/CONVENTIONS.md` | Updated W4-04 dual-layer validator-overlap note reflecting Side retype | VERIFIED | W4-04 section documents SIG-03 narrowing; mentions Side |
| `itrader/order_handler/reconcile/reconcile_manager.py` | Extracted-method on_fill with byte-identical try/finally skeleton | VERIFIED | 5 helpers; try/finally in on_fill; gate points intact |
| `tests/unit/order/test_reconcile_manager.py` | Branch coverage for body-raise-still-releases + unknown-status-holds-reservation | VERIFIED | 6 tests covering all required branches |
| `scripts/crossval/limit_entry_strategy.py` | Crafted minimal limit-entry strategy using buy_limit | VERIFIED | 10 references to buy_limit; to_money used; no Decimal(float) |
| `scripts/crossval/backtesting_py_limit_run.py` | backtesting.py LIMIT-entry runner with uniform run() contract | VERIFIED | File exists with run() signature |
| `scripts/crossval/backtrader_limit_run.py` | backtrader LIMIT-entry runner with buy_bracket | VERIFIED | buy_bracket count >= 4 |
| `tests/golden/CROSS-VALIDATION-LIMIT.md` | Owner-signed cross-validation evidence + frozen LIMIT golden numbers | VERIFIED | sign-off count 6; tiziaco attribution; frozen numbers (trade_count 2, final_equity 9503.442073) |
| `tests/e2e/matching/entries/limit_entry_crossval/scenario.py` | e2e leaf running crafted strategy on BTCUSD; HAND-VERIFIED VERIFY note | VERIFIED | References BTCUSD golden CSV; VERIFY note present with min(open,limit) derivations |
| `tests/e2e/matching/entries/limit_entry_crossval/golden/trades.csv` | Frozen golden trades | VERIFIED | 3 lines (header + 2 trades) |
| `tests/e2e/matching/entries/limit_entry_crossval/golden/summary.json` | Frozen golden summary | VERIFIED | trade_count: 2, final_equity: 9503.442073109638 |

### Key Link Verification

| From | To | Via | Status | Details |
| ---- | -- | --- | ------ | ------- |
| `base.py buy_limit/buy_stop/sell_limit/sell_stop` | `core/sizing.py SignalIntent(order_type=, entry_price=)` | factory construction | WIRED | Factories call `_intent(...)` which constructs `SignalIntent(order_type=order_type, entry_price=to_money(price), ...)` |
| `strategies_handler.py calculate_signals` | `SignalEvent(order_type=intent.order_type, price=...)` | per-intent fan-out | WIRED | `order_type=intent.order_type` (2 occurrences); MARKET keeps `to_money(bar.close)`, LIMIT/STOP use `intent.entry_price` |
| `admission_manager.py process_signal` | `_enforce_direction_admission / _enforce_position_admission / _resolve_signal_quantity` | threaded Position \| None snapshot argument | WIRED | `snap` captured once; all three methods accept `snap` parameter; `open_position = snap` at each method |
| `order.py Order.action: Side` | `events/order.py OrderEvent.action: Side` | to_event boundary | WIRED | `Side(order.action)` re-parse is now a no-op pass-through (entity already carries Side); docstring updated |
| `reconcile_manager.py on_fill` | `self.portfolio_handler.release(order.portfolio_id, order.id)` | release-in-finally guarded by should_release | WIRED | `finally:` at line 276 calls `_release_reservation`; `should_release` gate confirmed |
| `scripts/crossval/limit_entry_strategy.py` | `self.buy_limit(ticker, price=...)` | Plan-01 authoring factory | WIRED | Strategy uses `buy_limit` factory (10 occurrences) |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| -------- | ------------- | ------ | ------------------ | ------ |
| `strategies_handler.py calculate_signals` | `intent.order_type`, `intent.entry_price` | `SignalIntent` from strategy factory call | Yes — per-intent values from `buy_limit`/`buy_stop` factories or `OrderType.MARKET`/`None` from `buy`/`sell` | FLOWING |
| `reconcile_manager.py on_fill` | `fill_event.status` | `FillEvent` from exchange | Yes — real FillStatus dispatches to named arm helpers | FLOWING |
| `limit_entry_crossval/test_scenario.py` | frozen golden trades.csv + summary.json | `scenario.py` + BTCUSD dataset | Yes — real dataset, frozen golden with 2 actual trades | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| -------- | ------- | ------ | ------ |
| Existing oracle byte-exact (134 / 46189.87730727451) | `PYTHONPATH="$PWD" poetry run pytest tests/integration/test_backtest_oracle.py -q` | 3 passed | PASS |
| New limit-entry e2e leaf green (not xfail) | `PYTHONPATH="$PWD" poetry run pytest tests/e2e/matching/entries/limit_entry_crossval -m e2e -q` | 1 passed | PASS |
| Full test suite green | `PYTHONPATH="$PWD" poetry run pytest tests/ -q` | 978 passed | PASS |
| mypy --strict clean | `PYTHONPATH="$PWD" poetry run mypy --strict` | Success: no issues found in 182 source files | PASS |
| Signal factory unit tests | `PYTHONPATH="$PWD" poetry run pytest tests/unit/strategy/test_signal_factories.py -q` | 18 passed | PASS |
| Reconcile safety-net tests | `PYTHONPATH="$PWD" poetry run pytest tests/unit/order/test_reconcile_manager.py -q` | 6 passed | PASS |

### Probe Execution

Step 7c: SKIPPED — no `scripts/*/tests/probe-*.sh` probes declared or conventionally present for this phase. Phase uses pytest as the verification mechanism.

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| ----------- | ----------- | ----------- | ------ | -------- |
| SIG-01 | 05-01, 05-04 | Per-intent limit/stop ENTRY price on signal contract | SATISFIED | `buy_limit`/`buy_stop`/`sell_limit`/`sell_stop` factories; `SignalIntent.entry_price`; fan-out threads price to `SignalEvent`; proven by limit_entry_crossval e2e |
| SIG-02 | 05-01, 05-04 | Per-intent entry order_type (MARKET/LIMIT/STOP) not fixed per strategy instance | SATISFIED | `Strategy.order_type` class attr retired; fan-out reads `intent.order_type`; proven by limit_entry_crossval e2e |
| SIG-03 | 05-02 | Order.action/_PendingBracket.action typed Side; snapshot threaded once; W4-04 doc updated | SATISFIED | All literal sites narrowed to Side-member compares; snapshot threading verified; CONVENTIONS.md updated. **NOTE: REQUIREMENTS.md checkbox and traceability table still shows `[ ]` / `Pending` — tracker not updated after Plan 02 completed. Code fully satisfies the requirement.** |
| RECON-01 | 05-03, 05-04 | Streamlined on_fill reconciliation with financial-integrity invariant preserved | SATISFIED | 5 named helpers; try/finally byte-identical; 6 safety-net tests; oracle byte-exact |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| ---- | ---- | ------- | -------- | ------ |
| None found | — | No TBD/FIXME/XXX markers in any phase-modified file | — | — |

Scanned all 8 primary modified source files: `itrader/core/sizing.py`, `itrader/strategy_handler/base.py`, `itrader/strategy_handler/signal_record.py`, `itrader/strategy_handler/strategies_handler.py`, `itrader/order_handler/order.py`, `itrader/order_handler/brackets/bracket_book.py`, `itrader/order_handler/admission/admission_manager.py`, `itrader/order_handler/reconcile/reconcile_manager.py`. Zero debt markers found.

### Human Verification Required

None — all truths are mechanically verifiable. Mypy, test suite, oracle, and cross-validation evidence provide full coverage. The D-07 owner sign-off was the human gate and is recorded with attribution in `tests/golden/CROSS-VALIDATION-LIMIT.md`.

### Gaps Summary

No gaps. All 5 success criteria are verified by direct code inspection, test suite results, and cross-validation evidence.

**One documentation discrepancy noted (not a code gap):** `REQUIREMENTS.md` line 32 still shows `- [ ] SIG-03` and the traceability table still reads `| SIG-03 | ... | Pending |`. The code for SIG-03 (Order.action → Side, _PendingBracket.action → Side, snapshot threading, W4-04 doc update) is fully implemented and verified by mypy --strict clean + 978 test suite passing + oracle byte-exact. The tracker was not updated after Plan 02 completed. This is a bookkeeping issue, not a code defect — recommend updating REQUIREMENTS.md to mark SIG-03 `[x]` / `Complete (05-02)`.

---

_Verified: 2026-06-13_
_Verifier: Claude (gsd-verifier)_
