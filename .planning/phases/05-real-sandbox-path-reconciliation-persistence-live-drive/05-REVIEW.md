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

**Fix:** Pre-seed the order arm's dedup ledger with every venue `trade['id']` the reconciler
adopts, so a stream re-send of the same trade is a no-op:
```python
# VenueReconciler._adopt_fill_deltas, after selecting the adopted trades for an order:
if self._exchange is not None:
    for t in trades:
        tid = t.get("id")
        if tid is not None:
            self._exchange.mark_trade_seen(str(tid))  # new seam, guarded by _correlation_lock
```
Alternatively, add fill-ID dedup on the portfolio settlement path — `Transaction.fill_id` is
already threaded through `on_fill`, so `PortfolioHandler.on_fill` can reject a duplicate `fill_id`.

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
