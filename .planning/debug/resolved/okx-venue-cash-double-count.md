---
status: resolved
trigger: Live-path cash double-count in the OKX venue-backed account — a single real demo BUY fill debits portfolio cash by 2x the notional while position is single-counted
created: 2026-07-05
updated: 2026-07-05
---

# Debug Session: okx-venue-cash-double-count

## Symptoms

**Expected behavior:** A single spot BUY fill of 0.0001 BTC @ 59513 (notional 5.9513 USDC, venue fee 1e-07 BTC) should debit the portfolio's available cash by ~5.9513 (one notional + tiny fee). `_assert_settlement` in `tests/e2e/test_okx_sandbox_recon.py::test_demo_order_produces_real_fill_event` should pass: `cash_before - cash_after` within `[fill_cost*(1-band), fill_cost*(1+band)]`.

**Actual behavior:** Cash drops by `11.9026001` = **exactly 2x the 5.9513 notional**, while the POSITION delta is correct (single-counted ~0.0001 BTC). So the same fill settles cash twice but position once. Fails:
```
AssertionError: cash decrease 11.9026001 exceeds cost 5.95130 + fee band — unexpected debit
assert Decimal('11.9026001') <= (Decimal('5.95130') * (Decimal('1') + Decimal('0.02')))
```

**Error messages:** see above (test_okx_sandbox_recon.py:504). The position-delta assertion immediately above it PASSED, so the divergence is cash-only.

**Timeline:** First observed 2026-07-05 on the first successful online settlement run after quick task 260705-fqe adapted the e2e test to seed the believed position so `start()` reaches RUNNING on a non-flat demo account. Before that, the test halted at `start()` (baseline-residual) and never reached settlement — so this cash path had never been exercised online.

**Reproduction:** `make test-e2e-live` (or `poetry run pytest tests/e2e/test_okx_sandbox_recon.py -m live -v`) with OKX demo creds in `.env`. Places one real demo BUY on the OKX sandbox (`sandbox=True` asserted before submit; demo = no real money).

## Evidence (pre-gathered — do not re-derive)

- timestamp: 2026-07-05 — `fetch_my_trades('BTC/USDC')` shows each fill: `price=59513.0 amount=0.0001 cost=5.9513 fee={currency: 'BTC', cost: 1e-07}`. Fee is genuinely tiny → `commission` is NOT the source of the 2x.
- `Transaction.net_cash_delta` (transaction.py:121) for BUY = `-(price*quantity + commission)` = `-(5.9513 + 1e-7)` for ONE fill — a single notional.
- `transact_shares → process_transaction → _process_transaction_spot` (portfolio.py:326-404) applies EXACTLY ONE `apply_fill_cash_flow(amount=net_delta)` per transaction.
- CR-01 dedup guard `_settled_venue_trade_ids` (portfolio_handler.py:877 reject / 931 mark) gates position+cash atomically — a duplicate FillEvent would double BOTH; position is single-counted, so a re-dispatched same-id FillEvent is ruled out.
- Live available-cash is venue-snapshot-backed: `VenueAccount.balance = _venue_balance (cached) + _ledger_delta` (venue.py:325-344). Test line 72: portfolio cash "superseded by the VenueAccount cache on start()". `snapshot()` refreshes `_venue_balance` from the venue (already reflects the -5.95 trade) and is documented to reset `_ledger_delta` to zero (venue.py ~141/319).
- The recently-committed test seed (quick 260705-fqe) only calls `set_position` on position storage; it never touches venue cash or `_ledger_delta`, so this is a real live-path settlement bug, not a test artifact.
- timestamp: 2026-07-05 (this session) — `snapshot()` DOES reset `_ledger_delta` to zero (venue.py:315-320) — so the original snapshot-centric hypothesis is REFUTED. The culprit is `_stream_account` (venue.py:254-258): `if balance is not None: self._venue_balance = balance` with NO ledger reset. Two independent cash channels both reflect the fill → 2x.
- timestamp: 2026-07-05 — Grep confirms NO consumer reads `_venue_balance` alone: every reader (`balance`, `available_balance`, `assert_funds_invariant`, `reserve`) reads `_venue_balance + _ledger_delta`. The engine-thread drift compare (venue_reconciler.py:336, live_trading_system.py:605) reads ONLY `.positions`, never `.balance`. So removing the stream's cash-baseline write has no cash-side reader that needs a live venue balance — the D-01 `snapshot()`-baseline + `_ledger_delta` model fully covers cash.
- timestamp: 2026-07-05 — `test_account_conformance.py::test_buy_settlement_through_transact_shares` PINS the shared ABC contract: "venue leaf moves its local fill-ledger" and `available_balance == before - 10` after a BUY (snapshot-only, no stream). So the `_ledger_delta` channel is the mandated cash channel and CANNOT be dropped → the stream's cash-baseline write is the channel to remove.

## Current Focus

**hypothesis (CONFIRMED — corrected from the original snapshot-centric theory):** The double count is NOT in `snapshot()` — `snapshot()` (venue.py:315-320) correctly resets `_ledger_delta` to zero when it refreshes `_venue_balance`. The culprit is the async balance stream writer `_stream_account` (venue.py:254-258): it refreshes `_venue_balance = balance` from the venue's post-fill `watch_balance` push WITHOUT resetting `_ledger_delta`. Cash is a TWO-channel surface — `balance = _venue_balance + _ledger_delta` — where BOTH channels reflect the same fill: `apply_fill_cash_flow` (the ABC settlement primitive, portfolio.py:398, shared with the Simulated leaves) moves `_ledger_delta` by -5.9513, AND the balance stream moves `_venue_balance` to the fill-inclusive venue value. Position is single-counted because it has only ONE source (`_venue_positions`, no ledger overlay). Fix B (reset ledger on stream write) is NOT robust: on the live path the venue `watch_balance` push routinely LEADS the engine-thread `on_fill` apply (queue latency), so resetting-then-applying double-counts in the opposite order. The robust fix is single-channel cash.

**test:** Deterministic OFFLINE regression (`tests/unit/portfolio/test_venue_cash_no_double_count.py`): snapshot a spot `VenueAccount` to a pre-fill baseline, `apply_fill_cash_flow(-5.9513)` (assert balance = 94.0487), then drive the balance-stream cache write with a post-fill push carrying `total[USDC]=94.0487` + `total[BTC]=0.0001`; assert `balance == 94.0487` (single count, NOT 88.0974) and `positions == {BTC/USDC: 0.0001}` (position liveness preserved). No network, no demo order.

**expecting:** Before the fix the push double-debits cash to 88.0974 (RED). After the fix the stream leaves the cash baseline to `snapshot()` (D-01 reconcile point) and cash stays single-counted at 94.0487 while spot position liveness is preserved.

**next_action:** extract `_stream_account`'s cache write into a testable `_write_balance_stream` helper (behavior-preserving), add the RED regression test, then apply the fix (stream writes POSITIONS only, never the cash baseline) and verify GREEN.

**reasoning_checkpoint:**
- hypothesis: `_stream_account` refreshes `_venue_balance` to the fill-inclusive venue push while `_ledger_delta` still holds the same fill applied by `apply_fill_cash_flow` → `balance = _venue_balance + _ledger_delta` double-counts cash; position (single-sourced from `_venue_positions`) does not.
- confirming_evidence: (1) `balance` property is literally `_venue_balance + _ledger_delta` (venue.py:344). (2) `apply_fill_cash_flow` mutates `_ledger_delta` for every fill (venue.py:456) and is called once per spot settle (portfolio.py:398). (3) `_stream_account` writes `_venue_balance = balance` with NO ledger reset (venue.py:255-256), unlike `snapshot()` which DOES reset (venue.py:320). (4) The asymmetry — cash 2x, position 1x — is explained exactly by cash having two channels and position one.
- falsification_test: if the offline harness shows `balance == 94.0487` even with the CURRENT (unfixed) stream write, the two-channel theory is wrong. (It shows 88.0974 → confirms.)
- fix_rationale: cash must be single-channel. The `apply_fill_cash_flow`/`_ledger_delta` channel is the shared Account-ABC settlement contract (backtest depends on it; `test_account_conformance` pins it). Therefore the redundant channel — the stream's cash-baseline write — is removed. `snapshot()` remains the sole cash-reconcile point (D-01), which atomically re-baselines `_venue_balance` AND resets `_ledger_delta`. Robust against stream/fill ordering because only one channel ever moves cash between snapshots.
- blind_spots: (a) DERIVATIVE market type shares the same latent double-count; the fix is uniform, which invalidates the DERIVATIVE `_venue_balance` premise of the already-RED future-work gate `test_supervisor_catchall_venue_stream_survives_networkerror` (Phase 05.3 / D-11) — flagged, not modified. (b) `test_push_stream_mutates_cache` asserts the stream writes the cash baseline (the buggy behavior) and must be updated. (c) Reconcile's snapshot()-then-adopt-fill path is unchanged by this fix; not re-examined here.

**tdd_checkpoint:** RED test written first against a behavior-preserving `_write_balance_stream` extraction, then fix flips it GREEN.

## Eliminated

- hypothesis: commission/fee inflates net_cash_delta — ELIMINATED: venue fee is 1e-07 BTC (fetch_my_trades), far too small; 2x tracks the notional exactly, not the fee.
- hypothesis: duplicate FillEvent (same venue_trade_id) settled twice — ELIMINATED by the position being single-counted while the CR-01 guard gates position+cash atomically (both would double, or neither).

## Resolution

root_cause: >
  The venue-cached cash surface `VenueAccount.balance = _venue_balance + _ledger_delta`
  (venue.py:344) had TWO independent channels both reflecting each fill. Channel 1: the
  shared Account-ABC settlement primitive `apply_fill_cash_flow` (venue.py:456), called
  once per fill by `Portfolio._process_transaction_spot` (portfolio.py:398), moves
  `_ledger_delta` by the signed net cash delta (-5.9513 for the demo BUY). Channel 2: the
  async balance stream writer `_stream_account` (venue.py, old lines 254-258) refreshed
  `_venue_balance = balance` from the venue's post-fill `watch_balance` push — which
  ALREADY reflects the -5.9513 — WITHOUT resetting `_ledger_delta`. Net: the same fill was
  debited twice (2x = 11.9026001). Position was single-counted because it has only ONE
  source (`_venue_positions`), with no ledger overlay — exactly the observed cash-2x /
  position-1x asymmetry. `snapshot()` was NOT the culprit (it correctly resets
  `_ledger_delta`, venue.py:320) — the original snapshot-centric hypothesis was refuted.

fix: >
  Make cash single-channel. `apply_fill_cash_flow`/`_ledger_delta` is the mandated ABC
  settlement channel (backtest depends on it; `test_account_conformance` pins it), so the
  REDUNDANT channel — the stream's cash-baseline write — is removed. Extracted
  `_stream_account`'s cache write into a testable `_write_balance_stream` helper and made
  it write POSITIONS only (spot `total[BASE]` liveness for the drift compare), NEVER the
  cash baseline `_venue_balance`. `snapshot()` remains the SOLE cash-reconcile point (D-01):
  it atomically re-baselines `_venue_balance` AND resets `_ledger_delta`. Robust against
  stream/fill ordering (the live venue push routinely LEADS the engine on_fill apply) because
  only one channel ever moves cash between snapshots. Backtest (`SimulatedCashAccount`) is
  untouched → SMA_MACD golden oracle unaffected.

verification: >
  RED/GREEN offline regression `tests/unit/portfolio/test_venue_cash_no_double_count.py`
  (deterministic, no network, no demo order): with the buggy cash-baseline write restored it
  fails at balance==88.0974 (the 2x); with the fix it passes at 94.0487 and preserves spot
  position liveness. Full `tests/unit/portfolio/` = 343 passed. `tests/integration/
  test_backtest_oracle.py` = 3 passed (golden oracle intact). `mypy --strict` clean on
  venue.py. Updated `test_venue_account_cache.py::test_push_stream_mutates_positions_cache`
  (the old assertion encoded the buggy stream-writes-cash-baseline behavior). No new failures
  introduced (the only remaining reds — test_supervisor_catchall, test_submit_timeout_inflight,
  test_venue_order_id_persist, test_redeliver_dedup — are pre-existing Phase 05.2/05.3 RED
  gates, confirmed failing on the pristine tree). ONLINE proof (`make test-e2e-live`) is
  human-gated (places one real demo BUY) — proposed as a checkpoint, not run unprompted.

files_changed:
  - itrader/portfolio_handler/account/venue.py (extract _write_balance_stream; stop writing cash baseline from the stream)
  - tests/unit/portfolio/test_venue_cash_no_double_count.py (new offline regression lock)
  - tests/unit/portfolio/test_venue_account_cache.py (update stream-cache test to positions-only contract)

follow_ups:
  - Phase 05.3 / D-11: `test_supervisor_catchall_venue_stream_survives_networkerror` asserts the
    DERIVATIVE balance stream writes `_venue_balance` — that premise is invalidated by this fix
    (the stream no longer moves the cash baseline for either market type). When the supervisor
    lands, re-express that test's survival assertion (e.g. via a write-spy or positions) rather
    than via `_venue_balance`.

## Constraints

- OKX demo account is authorized for live-sandbox tests (demo creds, no real money) — but ASSERT `connector.sandbox is True` before any order.
- Each instrumented online run places one real demo BUY (venue BTC currently ~1.0002; harmless on demo). Prefer an OFFLINE harness driving VenueAccount's snapshot/ledger sequence if it can reproduce the ordering without the network.
- Money is Decimal end-to-end; `float()` only at serialization/logging edges.
- Live suite is `-m live` + credential gated; default `make test` excludes it.
