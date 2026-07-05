---
status: resolved
trigger: Spot base-currency fee not modeled — live engine spuriously HALTs ('drift') on every OKX spot BUY and the position is overstated by the base-fee
created: 2026-07-05
updated: 2026-07-05
---

# Debug Session: spot-base-fee-drift-halt

## Symptoms

**Expected behavior:** A clean spot BUY fill on the live OKX path settles without halting the engine, and the engine's believed position equals the venue base balance (no reconcile drift). `test_demo_order_produces_real_fill_event` should pass its `status != HALTED` assertion, and `test_venue_account_reconciles_post_fill_within_tolerance` should pass.

**Actual behavior:** After the cash double-count fix (commit 30cfb73), the online run `make test-e2e-live` (2026-07-05) shows:
- `test_demo_order_produces_real_fill_event` → fails at `AssertionError: engine HALTED after a clean demo fill: 'drift'`.
- `test_venue_account_reconciles_post_fill_within_tolerance` → fails: `engine 1.0003997 vs venue 1.0003996` (diff 1e-7) beyond `is_within_single_unit_tolerance(precision=8)` = 1e-8.

**Error messages:** `'halted' != 'halted'` (status is HALTED, reason `'drift'`); drift `1.0003997 vs 1.0003996`.

**Timeline:** Surfaced 2026-07-05 immediately after the cash fix let `test_demo_order` reach the not-HALTED assertion. This code path was never exercised online before the seed adaptation (quick 260705-fqe) unblocked `start()`.

**Reproduction:** `make test-e2e-live` (OKX demo creds in `.env`). Places one real demo BUY on the OKX sandbox (`sandbox=True` asserted; demo = no real money).

## Root Cause (CONFIRMED — go straight to fix)

OKX charges the spot **BUY** taker fee in the **BASE** currency (BTC). `fetch_my_trades('BTC/USDC')` confirms `fee={currency: 'BTC', cost: 1e-07}` on a 0.0001 BTC buy. The venue credits `amount - base_fee` BTC, but the engine records the **full** fill `amount` as the position:
- `OkxExchange._emit_fill` (execution_handler/exchanges/okx.py:451-453) reads only `fee.get('cost')` (via `abs(to_money(str(fee_cost)))`) and **drops** `fee.get('currency')`; `FillEvent.quantity = amount`.
- Portfolio settlement adds the full `amount` to the position and debits cash `-(price*qty + commission)` — treating the base-fee as a (tiny, unit-mismatched) cash debit rather than a base reduction.

Result: `engine_qty` = `venue_qty + base_fee`. The on-fill drift compare (`portfolio_handler.py::_compare_symbol_drift`, ~line 760) sees the mismatch; its spurious-halt absorber (line 772) only forgives the "venue hasn't streamed the fill yet" case (`venue ≈ engine - fill_qty`), but the venue **has** caught up — to `engine - fee` — so it falls through and calls `halt('drift')` (freeze-in-place). The drift also accumulates `N*fee` across N buys in production, so widening the band is NOT a real fix (and leaves the position overstated).

## Chosen Fix (LOCKED by user — full fee-currency-aware settlement)

Carry the fee **currency** on the `FillEvent` (frozen dataclass, events_handler/events/fill.py; update `FillEvent.new_fill` + all construction sites; optional/defaulted so simulated fills stay unaffected). Branch settlement on fee currency:
- fee in the pair's **BASE** asset → deduct it from the **position** quantity (net base received = `amount - base_fee`), do NOT debit cash for it.
- fee in the **QUOTE** asset → debit **cash** (current `Transaction.net_cash_delta` behavior, transaction/transaction.py:121).
Handle BUY (base-fee on OKX) and SELL (quote-fee on OKX). After the fix engine position == venue base balance (drift eliminated at the source, no halt) and cash is debited the correct leg only.

## Current Focus

**hypothesis:** CONFIRMED above — engine overstates the position by the base-denominated fee, tripping the on-fill drift halt.

**test:** Offline unit regression (write FIRST, RED): a base-denominated-fee BUY fill settles `position = amount - fee` and `cash -= amount*price` (no cash fee debit); a quote-fee SELL settles `cash += amount*price - fee` and `position -= amount`. Then the settlement produces engine position == (amount - base_fee) so a subsequent drift compare against a venue balance of (amount - base_fee) is within band.

**expecting:** RED before fix (position = amount, drift = fee > 1e-8). GREEN after (position = amount - base_fee, drift = 0).

**next_action:** write the RED offline regression lock, then implement the fee-currency-aware settlement, then verify oracle + unit suite + mypy --strict; propose the online proof as a human-gated checkpoint.

**reasoning_checkpoint:**
- hypothesis: The engine records the full fill `amount` as the spot position and debits the base-denominated fee as a quote cash outflow, so `engine_qty = venue_qty + base_fee` — tripping the on-fill drift halt.
- confirming_evidence: OKX `fetch_my_trades('BTC/USDC')` returns `fee={currency:'BTC', cost:1e-07}`; `OkxExchange._emit_fill` (okx.py:451-453) reads only `fee.get('cost')` and drops `fee.get('currency')`; `_process_transaction_spot` adds full `amount` to the position and `net_cash_delta` subtracts commission from cash.
- falsification_test: After carrying fee.currency and netting a base fee out of the position, the offline unit regression must show `position.net_quantity == amount - fee` and `cash == amount*price` (no fee cash debit); if the position still equals `amount`, the branch is not reached.
- fix_rationale: Fee-currency-aware settlement models the venue's actual base credit (`amount - base_fee`), so `engine_qty == venue_qty` EXACTLY at the source — the drift is eliminated, not masked by a wider band.
- blind_spots: Margin arm base-fee is out of scope (live demo is spot, enable_margin=False); avg_price cost-basis for base-fee positions carries the fee as an immediate equity reduction (economically correct) rather than folding it into avg_price.

**tdd_checkpoint:**
  test_file: tests/unit/portfolio/test_spot_base_fee_settlement.py
  test_names: test_base_fee_buy_reduces_position_not_cash, test_quote_fee_sell_debits_cash_not_position, test_none_fee_currency_preserves_oracle_behavior, test_base_fee_buy_scale_in_nets_each_leg, test_transaction_seam_properties_are_fee_currency_aware
  status: green
  failure_output: "TypeError: Unexpected keyword argument 'fee_currency' (5 failed) — the Transaction fee_currency field + settlement seam did not exist yet"
  green_output: "5 passed — base-fee BUY nets position = amount - fee, cash = amount*price; quote-fee SELL + None-fee unchanged; Transaction seam properties locked"

## Offline verification (all GREEN)

- tests/unit/portfolio/test_spot_base_fee_settlement.py: 5 passed (RED→GREEN)
- tests/integration/test_backtest_oracle.py: 3 passed — SMA_MACD oracle BYTE-EXACT (134 / 46189.87730727451 unchanged)
- tests/unit/portfolio: 348 passed (343 prior + 5 new; zero regressions)
- tests/unit/execution + tests/unit/events: 318 passed; the 5 execution failures are PRE-EXISTING on the clean tree (supervisor-catchall x3, venue-order-id-persist x1, submit-timeout-inflight x1 — timing/thread tests unrelated to fills, confirmed via git stash + isolated run)
- OKX emit/fill/exchange tests: 83 passed — fee_currency propagates through _emit_fill
- poetry run mypy (--strict): Success, no issues in 228 source files

## Resolution

root_cause: OkxExchange._emit_fill dropped the venue fee CURRENCY (read only fee.cost), so a base-denominated OKX spot BUY fee (charged in BTC) was recorded as a full-amount position + a quote cash debit. engine_qty = venue_qty + base_fee tripped the on-fill drift halt.

fix: Fee-currency-aware spot settlement. FillEvent + Transaction carry fee_currency (defaulted None → oracle-dark). Transaction gains base_asset / is_base_fee / quote_commission / position_quantity; net_cash_delta uses quote_commission (0 for a base fee). Position.open_position / update_position settle transaction.position_quantity (amount - base_fee for a base BUY) with quote_commission. OkxExchange._emit_fill stamps fee_currency from trade['fee']['currency']. Result: engine position == venue base balance EXACTLY (drift 0, no band change needed).

fix (extension — commit 2, after online proof showed test (i) still halted): the on-fill drift ABSORBER was inconsistent with the fee-aware settlement. PortfolioHandler.on_fill passed the RAW fill_event.quantity as just_applied_fill_qty, but settlement moves a base-fee BUY by (amount - base_fee); the absorber's pre-fill reconstruction (engine_qty - just_applied_fill_qty) was off by the fee, so when the async venue cache was still pre-fill at compare time it spuriously halted('drift'). Now just_applied_fill_qty = transaction.position_quantity signed by action (net-base delta; identity to raw quantity on the oracle/quote path). RED→GREEN offline regression: tests/unit/portfolio/test_spot_base_fee_drift_absorber.py (base-fee fill with pre-fill venue cache must NOT halt; genuine unexplained divergence still halts).

verification: OFFLINE GREEN (above) + ONLINE CONFIRMED (make test-e2e-live, both commits in tree). The 'drift' HALT is GONE: test_demo_order_produces_real_fill_event passes ALL 4 hard settlement assertions (position delta, cash delta, status != HALTED, spot fetch_positions()==[]); test_venue_account_reconciles_post_fill_within_tolerance passes (engine==venue, drift 0); test_restart_rehydrate passes. The run's remaining 1 failure is OUT OF SCOPE — a test-side ARCH-3 diagnostic capture (_capture_arch3_finalization → fetch_my_trades with {"paginate": True}) that OKX rejects with code 51000 'Parameter limit error'; NOT an engine settlement bug (coordinator handling separately). Resolved 2026-07-05.

files_changed: [itrader/events_handler/events/fill.py, itrader/execution_handler/exchanges/okx.py, itrader/portfolio_handler/transaction/transaction.py, itrader/portfolio_handler/position/position.py, itrader/portfolio_handler/portfolio_handler.py (settlement + absorber), itrader/portfolio_handler/portfolio.py, tests/unit/portfolio/test_spot_base_fee_settlement.py, tests/unit/portfolio/test_spot_base_fee_drift_absorber.py]

online proof (partial, after commit 1 cdfd55a1): 2 passed / 1 failed — test_venue_account_reconciles_post_fill_within_tolerance PASSED (engine==venue, drift 0); test_demo_order_produces_real_fill_event STILL HALTED on 'drift' (absorber not yet fee-aware). Commit 2 addresses the remaining halt; awaiting re-run of make test-e2e-live (all 3 expected green).

**Chosen seam (implementation):** Fee-awareness lives in Transaction properties: `fee_currency` field + `base_asset` / `is_base_fee` / `quote_commission` / `position_quantity`. `net_cash_delta` uses `quote_commission` (0 for a base fee → no cash leg). `Position.open_position` / `update_position` read `transaction.position_quantity` (= amount - fee for a base BUY) and `transaction.quote_commission`. Default path (fee_currency None or == quote) returns identity values → byte-exact oracle. FillEvent carries `fee_currency` (defaulted None); OkxExchange._emit_fill stamps it from `fee.get('currency')`.

## Eliminated

- hypothesis: reconcile tolerance too tight (widen the band) — REJECTED as the fix: the base-fee drift accumulates `N*fee` per buy and would trip any fixed band eventually, and it leaves the position overstated. The band (1e-8) is correct ONCE the base-fee is modeled into the position (engine==venue exactly); confirm no band change is needed rather than loosening it.

## Constraints

- ORACLE SAFETY: touches the SMA_MACD golden settlement path. Backtest/paper SimulatedExchange fills must stay BYTE-EXACT (oracle-dark) — they carry no venue fee-currency, so the new branch MUST default to current behavior when fee currency is absent/None or equals the quote currency. Verify with `tests/integration/test_backtest_oracle.py` (3) + the portfolio unit suite (343).
- Money is Decimal end-to-end; enter Decimal via `to_money(str(x))`, never `Decimal(float)`. No second ID scheme.
- Indentation: handler modules use TABS; events package / core / config use 4 spaces — match each file.
- The online proof (`make test-e2e-live`) is human-gated and places one real demo BUY — propose as a checkpoint, do not run unprompted; assert `connector.sandbox is True` first. After the fix, `test_venue_account_reconciles` should pass (engine==venue) and `test_demo_order` should no longer halt on 'drift'.
