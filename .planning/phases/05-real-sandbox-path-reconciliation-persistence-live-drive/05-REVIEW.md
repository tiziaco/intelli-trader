---
phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
reviewed: 2026-07-03T00:00:00Z
depth: standard
files_reviewed: 41
files_reviewed_list:
  - itrader/core/enums/system.py
  - itrader/events_handler/full_event_handler.py
  - itrader/execution_handler/exchanges/okx.py
  - itrader/order_handler/order.py
  - itrader/order_handler/reconcile/reconcile_manager.py
  - itrader/order_handler/storage/models.py
  - itrader/order_handler/storage/sql_storage.py
  - itrader/portfolio_handler/account/venue.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/portfolio_handler/reconcile/__init__.py
  - itrader/portfolio_handler/reconcile/drift.py
  - itrader/portfolio_handler/reconcile/venue_reconciler.py
  - itrader/price_handler/providers/okx_provider.py
  - itrader/storage/migrations/versions/p05_venue_order_id.py
  - itrader/trading_system/alert_sink.py
  - itrader/trading_system/live_trading_system.py
  - tests/conftest.py
  - tests/e2e/test_okx_sandbox_recon.py
  - tests/integration/test_bracket_restart_relink.py
  - tests/integration/test_live_bar_metrics.py
  - tests/integration/test_live_system_okx_wiring.py
  - tests/integration/test_okx_inertness.py
  - tests/integration/test_paper_parity.py
  - tests/integration/test_store_live_drive.py
  - tests/integration/test_two_sided_restart.py
  - tests/support/__init__.py
  - tests/support/fake_venue_connector.py
  - tests/support/fixtures/okx_recon_payloads.json
  - tests/unit/connectors/test_fake_venue_connector.py
  - tests/unit/execution/test_drift_halt_policy.py
  - tests/unit/execution/test_okx_exchange.py
  - tests/unit/execution/test_okx_fill_idempotency.py
  - tests/unit/execution/test_reconnect_resilience.py
  - tests/unit/order/test_order_manager.py
  - tests/unit/order/test_partial_fill_terminalize.py
  - tests/unit/portfolio/test_drift_tolerance.py
  - tests/unit/portfolio/test_venue_account_cache.py
  - tests/unit/portfolio/test_venue_account_drift.py
findings:
  critical: 1
  warning: 6
  info: 4
  total: 11
status: issues_found
---

# Phase 5: Code Review Report

**Reviewed:** 2026-07-03T00:00:00Z
**Depth:** standard
**Files Reviewed:** 41
**Status:** issues_found

## Summary

Phase 5 wires the real OKX sandbox order/data arms, a cached `VenueAccount`, a two-sided
restart `VenueReconciler`, engine-thread drift-halt, a reconnect supervisor, and a live SQL
order mirror. The code is unusually well-documented and defensively written; most edge cases
(None-guards before the Decimal edge, cross-thread locking, idempotent release, buffered
fast-fills) are handled thoughtfully. No hardcoded secrets, no injection vectors (the SQL
storage uses parameterized SQLAlchemy Core with an allow-listed searchable-column map
throughout), no dangerous `eval`/`exec`, and the inertness discipline (lazy OKX/SQL imports)
is consistently applied.

The findings below concentrate on the LIVE path, which is oracle-dark (the SMA_MACD golden run
never exercises it), so none of these perturb the frozen backtest. The most serious is a
structural gap between the restart reconciler and the live fill stream that can double-apply the
same economic fill onto portfolio state. The remainder are live-path robustness/correctness
concerns plus quality items. This review supersedes the earlier 16-file partial pass.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01: Restart reconciler can double-count fills against portfolio state

**File:** `itrader/portfolio_handler/reconcile/venue_reconciler.py:187-218` (cross-refs
`itrader/execution_handler/exchanges/okx.py:343-390`,
`itrader/trading_system/live_trading_system.py:1059-1112`)

**Issue:** At startup the order-arm fill streams are spawned FIRST (`start()` lines 1072-1076 →
`OkxExchange.connect` → `_stream_fills`), and only AFTER that does `VenueReconciler.reconcile()`
run (line 1112). `_adopt_fill_deltas` synthesizes a reconciling `FillEvent` for
`delta = venue_filled - order.filled_quantity` and `global_queue.put`s it. That synthetic fill is
minted directly (`_emit_reconciling_fill`) and never passes through `OkxExchange._handle_trade`,
so it is NOT recorded in `_seen_trade_ids`.

If `watch_my_trades` re-delivers the same historical trades after (re)subscribe — which the code
explicitly expects (the dedup at `okx.py:112-124` and the reconciler comment at
`venue_reconciler.py:20-21` exist precisely for reconnect re-sends) — those trades flow through
`_handle_trade` and emit their OWN `FillEvent`s. The order-mirror side
(`ReconcileManager._apply_executed`) will reject the resulting over-fill, but
`PortfolioHandler.on_fill` (`portfolio_handler.py:782-853`) applies EVERY `EXECUTED` fill as a
`Transaction` with no fill-ID dedup. Result: the same 0.5 BTC is booked as the reconciler delta
(0.5) PLUS the stream (0.2 + 0.3) = 1.0 BTC of position/cash.

`_seen_trade_ids` structurally cannot cover this cross-path case because the two emitters share no
dedup key. The subsequent engine-thread drift compare will HALT (engine 1.0 vs venue 0.5), so the
engine fails safe rather than trading on the corrupted state — but portfolio state IS corrupted at
that moment and the run halts on "numbers it cannot trust," defeating the reconcile whose entire
purpose is a clean, tradeable restart.

**Fix (RESOLVED — debug session `cr-01-fill-double-count`, 2026-07-03):** Promote the venue trade
id to a first-class cross-emitter idempotency key (FIX ExecID(17)/TradeID(1003); Nautilus
`TradeId`) and dedup at the portfolio settlement chokepoint. Concretely:

1. `FillEvent` gains an optional `venue_trade_id: str | None = None` (default None so
   backtest/simulated fills are oracle-dark), threaded through `FillEvent.new_fill`.
2. `Transaction` carries the same field so the durable settlement record preserves the key.
   **Persistence tail (quick task `260703-hl5`, 2026-07-03):** the `transactions` table gained a
   nullable `venue_trade_id` column (chained Alembic migration `hl5_transaction_venue_trade_id`) and
   both `sql_storage` mappers thread it, so a rehydrated `Transaction` preserves the venue key instead
   of dropping it — the durable ledger can now be reconciled back to venue executions. Verified by a
   Postgres round-trip test.
3. BOTH live emitters stamp it: `OkxExchange._emit_fill` sets `venue_trade_id = trade['id']`, and
   `VenueReconciler` now emits ONE reconciling fill **per venue trade** (matching the stream's
   granularity) instead of one aggregated summed-delta fill — each carrying its own
   `venue_trade_id`, preserving adopt-once via a skip-budget over `order.filled_quantity`.
4. `PortfolioHandler.on_fill` rejects a fill whose `venue_trade_id` is already in a bounded
   per-handler settled-set (recorded only after a transaction applies). Fills with
   `venue_trade_id=None` skip the guard entirely → SMA_MACD byte-exact.

**Do NOT apply the two originally-suggested fixes.** The `mark_trade_seen` order-arm pre-seed only
covers the OKX stream path (not a second reconciler or a non-OKX venue), and a `Transaction.fill_id`
dedup is structurally ineffective: `FillEvent.new_fill` mints a fresh `uuid7` `fill_id` on every
call, so the two duplicate fills for the same venue trade carry DIFFERENT `fill_id`s and a
`fill_id`-set never matches. The venue trade id is the only stable cross-emitter key.

## Warnings

### WR-01: `OkxExchange.on_order` emits `FillEvent(REFUSED)` on a failed CANCEL, wrongly terminalizing a still-resting order

**File:** `itrader/execution_handler/exchanges/okx.py:192-211`

**Issue:** The boundary `except` fires for BOTH `_submit_order` and `_cancel_order` and emits
`FillEvent("REFUSED", ...)`, which `ReconcileManager._apply_refused` transitions the mirror to
`REJECTED`. For a submit that never reached the venue this is correct. For a CANCEL RPC that raises
transiently (network blip), the venue order is very likely STILL RESTING, yet the local mirror is
now permanently `REJECTED` — a silent divergence that later surfaces as a fill against an order the
engine believes is dead, or an un-cancellable resting order. The WR-02 comment justifies the submit
case only; the cancel case is swept in with it.

**Fix:** Branch on `event.command` in the handler; do not synthesize `REFUSED` for a failed cancel:
```python
except Exception:
    if event.command is OrderCommand.CANCEL:
        self.logger.error("OKX cancel failed for %s — mirror left active", event.order_id, exc_info=True)
        return
    self.global_queue.put(FillEvent.new_fill("REFUSED", event, ...))
```

**Status (RESOLVED — debug session `wr-high-priority-live`, 2026-07-03):** `on_order`'s boundary
`except` now branches on `event.command`. A CANCEL failure leaves the order mirror in its resting
state and publishes an `ErrorEvent` (the operator/dead-letter channel) so the failed cancel is
auditable; the next reconcile/drift pass reconciles true venue state — a command-ack failure is no
longer forced through the execution channel (Nautilus `OrderCancelRejected` semantics; a first-class
event is the deferred full-parity option). A SUBMIT failure keeps the unchanged `FillEvent(REFUSED)`
→ REJECTED path. Verified: failed-cancel-leaves-active + failed-submit-still-rejects tests pass;
oracle byte-exact. Live-sandbox confirmation (transient cancel failure) pending.

### WR-02: A single shared `VenueAccount` is assigned to every live portfolio

**File:** `itrader/trading_system/live_trading_system.py:1085-1089`

**Issue:** `for portfolio in self.portfolio_handler.get_active_portfolios(): portfolio.account =
self._venue_account` assigns the SAME `VenueAccount` instance to all active portfolios. With more
than one live portfolio they share one venue balance/available/positions cache, so buying power and
positions are conflated across portfolios (and `_compare_symbol_drift` would read one venue truth
for every portfolio). It also silently discards each portfolio's prior `SimulatedAccount` ledger.
Latent today (single-portfolio live) but a correctness trap the moment a second portfolio exists.

**Fix:** Build one `VenueAccount` per portfolio (or key the venue cache by sub-account), and assert
`len(active_portfolios) == 1` at wiring time until per-portfolio venue accounts exist.

**Status (RESOLVED — debug session `wr-high-priority-live`, 2026-07-03):** Extracted
`_link_venue_account_to_portfolios` with a fail-loud guard. **Deviation from the literal fix (accepted):**
the guard rejects `len(active_portfolios) > 1` (not strict `== 1`) via a `RuntimeError` (not a
strippable `assert`, so it survives `python -O`). A strict `== 1` regressed a valid existing test that
starts a system with **0** portfolios (added post-start); 0 = benign no-op, 1 = supported
single-portfolio-live, >1 = fail-loud. The actual defect (sharing one `VenueAccount` across multiple
portfolios) is fully caught. Per-portfolio `VenueAccount` keyed by sub-account with clOrdId/tag position
attribution remains the deferred multi-portfolio-live design. Verified: two wiring tests pass; oracle
byte-exact. Known follow-up (out of scope): a portfolio added *post-start* is not linked at this wiring
point (pre-existing behavior, not a regression).

### WR-03: Reconnect retry ceiling can never trip when the socket closes cleanly right after subscribe

**File:** `itrader/price_handler/providers/okx_provider.py:236-350` (mirrored in
`itrader/execution_handler/exchanges/okx.py:501-532`)

**Issue:** `_connect_and_consume_candles` calls `_on_stream_healthy("candles")` immediately after a
successful subscribe (line 260), resetting `_reconnect_attempts[stream] = 0`. If the server then
closes the socket right away (the `async for` exits), the supervisor treats the clean return as a
drop and computes `attempt = 0 + 1 = 1` every cycle — so `attempt > self._reconnect_ceiling` is
never reached and the D-20 "never spin forever → HALT" guarantee is defeated: the loop reconnects
indefinitely at `backoff_base` and never escalates. The order arm has the same reset-on-each-batch
behavior.

**Fix:** Reset the attempt counter only after a minimum healthy dwell (or count consecutive
connect-without-payload cycles separately from payload-bearing successes) so a subscribe-then-close
storm still exhausts the ceiling and halts.

**Status (RESOLVED — debug session `wr-03-reconnect-ceiling-storm`, 2026-07-03):** Two layers.
Layer 1 (both arms): `_on_stream_healthy` no longer resets `_reconnect_attempts` on a mere
subscribe/ack — it performs only the D-19 resume transition; the budget resets via a new
`_reset_reconnect_budget`, called by the real consume loops only on a delivered payload.
Layer 2 (data arm — surfaced ONLY by the online OKX-demo test): OKX pushes an in-progress-candle
SNAPSHOT (`confirm='0'`, ~30ms) on EVERY candle subscribe, so plain payload-gating still reset the
budget every storm cycle. `_connect_and_consume_candles` now carries a per-connection `payload_seen`
flag and resets the budget only on a payload delivered AFTER the subscribe snapshot (real streaming);
the order arm needs no such guard (ccxt.pro `watch_my_trades`/`watch_orders` never emit on bare
subscribe). A subscribe-then-close storm's `attempt` now climbs monotonically to
`_escalate_connector_halt('connector-fatal')` (D-20 restored) on both arms; a genuine streaming
reconnect still clears the budget. Verified: `test_reconnect_resilience.py` 17 passed (adds order+data
storm tests + a snapshot-on-subscribe test driving the REAL `_connect_and_consume_candles` via a fake
WS, RED→GREEN); oracle byte-exact; mypy strict-clean. ONLINE (OKX demo, sandbox asserted): storm reset
budget 0/3 (was 3/3 pre-fix) → HALT; healthy post-snapshot update reset it 1/1 → survives. Commit
`21899dca`.

### WR-04: `_client_order_id` truncation drops entropy, risking clOrdId collisions

**File:** `itrader/execution_handler/exchanges/okx.py:162-172`

**Issue:** `("it" + token)[:32]`, where `token` is the 32 hex chars of a UUIDv7 with hyphens
stripped, yields `"it"` + 32 = 34 chars truncated to 32 — dropping the last 2 hex chars (tail random
bits). The clOrdId is a fast-fill-race correlation key (`_orders_by_clOrdId`); two orders whose
UUIDs differ only in those trailing bits map to the same clOrdId, so an echoed fill could resolve to
the WRONG originating order (wrong order_id/strategy_id/portfolio_id on the emitted `FillEvent`).
Collision probability is low but non-zero and rises with order volume.

**Fix:** Derive a collision-resistant compact token fitting 30 chars after the `it` prefix (base62
of the UUID bytes, or a wider-alphabet hash-truncate) validated against OKX's 32-char alphanumeric
clOrdId limit.

**Status (RESOLVED — debug session `wr-high-priority-live`, 2026-07-03):** `_client_order_id` now
base62-encodes the full 128 bits of the order id (`order_id.bytes`) — a lossless bijection rendering to
≤22 chars, so `"it"` + token ≤24 chars, under OKX's 32-char alphanumeric limit with **no** entropy
dropped. Deterministic (the venue-echoed clOrdId still maps straight back to the pending correlation);
output asserted alphanumeric + ≤32 chars. The internal `order_id` stays a UUIDv7 (locked single-scheme
decision) — the clOrdId is only its venue-charset rendering; `venue_order_id`/`venue_trade_id` (venue-
assigned, opaque strings) untouched. Verified: two-UUIDs-differing-only-in-tail-bits produce distinct
clOrdIds + round-trip-correlation tests pass; oracle byte-exact.

### WR-05: OKX in-memory correlation maps grow unbounded across a live session

**File:** `itrader/execution_handler/exchanges/okx.py:108-127`

**Issue:** `_orders_by_venue_id`, `_venue_id_by_order_id`, `_orders_by_clOrdId`, and
`_seen_trade_ids` are only ever inserted into; nothing is removed when an order terminalizes or a
trade id ages out. Over a long-running session they grow without bound (retaining `OrderEvent`
references and every trade id). Beyond memory, the ever-growing `_seen_trade_ids` means the dedup
window is effectively unbounded with no eviction policy.

**Fix:** Prune the venue-id/clOrdId maps when an order reaches a terminal state (reconcile can
signal it), and bound `_seen_trade_ids` (a bounded LRU/ring keyed by recency — re-sends are only
plausible within a reconnect window).

### WR-06: Live ERROR-route consumer is not self-protected against its own failure

**File:** `itrader/events_handler/full_event_handler.py:126-195` with
`itrader/trading_system/live_trading_system.py:490-521`

**Issue:** In live mode `_on_handler_error` is overridden by `_publish_and_continue`, which puts a
new `ErrorEvent` on the queue; that event is routed to `_log_error_event`, which unconditionally
reads `event.correlation_id` (180), `event.details` (185), and — for CRITICAL — the alert sink.
`_publish_and_continue` constructs its `ErrorEvent` WITHOUT `correlation_id`/`details`. If any read
(or the sink) raises, the exception routes back through `_publish_and_continue`, which emits YET
ANOTHER `ErrorEvent` — an unbounded error→error feedback loop that floods the engine-thread queue.
Whether it triggers depends on `ErrorEvent`'s field defaults (outside this diff), but the ERROR
route is the one place a handler failure must be terminal-safe and it currently is not.

**Fix:** Wrap `_log_error_event` (and the alert-sink call) so a malformed `ErrorEvent` is logged
once and never re-raised into `_dispatch`, breaking any recursion.

## Info

### IN-01: Stale source-line references in reconcile comments

**File:** `itrader/order_handler/reconcile/reconcile_manager.py:236-238`

**Issue:** `_apply_expired` cites `order.py:307-309` for `VALID_ORDER_TRANSITIONS[EXPIRED] == []`,
but that table lives in `core/enums` and `order.py` has grown past those lines. Prefer symbolic
references over line numbers, which rot.

### IN-02: Left-behind `TODO` in the production order lifecycle path

**File:** `itrader/order_handler/order.py:451-452`

**Issue:** `# TODO: check if i have to store the state changes permanently in sql when in live
trading / production` sits inside `add_state_change`, the single validated transition path now used
by the live SQL mirror. Phase 5 wires `SqlOrderStorage` (state changes DO round-trip via
`_state_change_rows`), so this TODO is either resolved or should be an tracked issue, not inline.

**Fix:** Resolve/remove after confirming the SQL round-trip semantics.

### IN-03: `NotImplementedError` raised inside `except` without `from None`

**File:** `itrader/events_handler/full_event_handler.py:134-139`

**Issue:** Raising inside `except KeyError` chains the `KeyError` as `__context__`, producing noisy
"During handling of the above exception..." tracebacks for an intended signal.

**Fix:** `raise NotImplementedError(...) from None`.

### IN-04: Recon fixture symbol (`BTC/USDT`) diverges from the wired live symbol (`BTC/USDC`)

**File:** `tests/support/fixtures/okx_recon_payloads.json:3` vs
`itrader/trading_system/live_trading_system.py:48-51`

**Issue:** The recon fixture narrates a `BTC/USDT` scenario, but production hardcodes
`_OKX_STREAM_SYMBOL = "BTC/USDC"` (MiCA/USDT restriction). The offline recon tests therefore
exercise a symbol the live path will never stream, leaving the symbol-form membership assertion
(`_initialize_live_session` 830-839) and symbol-keyed drift/position matching uncovered by the
fixture.

**Fix:** Parameterize the fixture symbol or add a `BTC/USDC` recon variant matching the wired
constant.

---

_Reviewed: 2026-07-03T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
