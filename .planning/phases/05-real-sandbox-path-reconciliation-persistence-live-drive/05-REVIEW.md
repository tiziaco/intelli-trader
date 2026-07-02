---
phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
reviewed: 2026-07-02T00:00:00Z
depth: standard
files_reviewed: 16
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
findings:
  critical: 1
  warning: 5
  info: 0
  total: 6
status: issues_found
---

# Phase 5: Code Review Report

**Reviewed:** 2026-07-02T00:00:00Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Phase 5 wires the live/sandbox OKX path: order arm (`okx.py`), data arm
(`okx_provider.py`), venue-cached account (`venue.py`), the drift compare and
two-sided restart reconciler (`portfolio_handler.py`, `venue_reconciler.py`,
`drift.py`), the SQL order mirror + Alembic migration (`sql_storage.py`,
`models.py`, `p05_venue_order_id.py`), the alert-sink egress (`alert_sink.py`),
and the live composition root / halt-pause state machine
(`live_trading_system.py`).

Money is Decimal-clean throughout (every venue edge crosses `to_money(str(x))`;
no `Decimal(float)`), the migration chain is a correct linear single-head
(`2cbf0bf6b0b6` → `47f2b41f3ffe` → `p05_venue_order_id`), the SQL store is fully
parameterized (no injection surface), and the connector-loop callbacks correctly
only flip thread-safe flags. The reconnect supervisors correctly re-raise
`CancelledError` and scrub exception text.

However there is one shipping defect that breaks the live OKX path end-to-end
(the order-arm fill stream is never started), plus several correctness/robustness
warnings around halt idempotency, restart-vs-stream fill correlation, and a
mutate-before-validate ordering in the partial-fill reconcile arm.

## Critical Issues

### CR-01: OKX order-arm fill/order streams are never started — live fills never arrive

**File:** `itrader/trading_system/live_trading_system.py:990-1000` (and `itrader/execution_handler/execution_handler.py:163-183`)
**Issue:**
`OkxExchange.connect()` is the method that spawns the venue order-arm streams
(`watch_my_trades` / `watch_orders` via `connector.spawn`, `okx.py:575-594`) —
this is the ONLY place fills stream back from the venue on the order arm
(`_stream_fills` → `_consume_fills` → `_handle_trade` → `_emit_fill`).

`OkxExchange.connect()` is never invoked anywhere:
- `ExecutionHandler.init_exchanges()` (execution_handler.py:168-181) connects only
  the exchanges it builds at construction time (`simulated`/`csv`/`ccxt`). The
  `'okx'` arm is registered AFTER construction
  (`live_trading_system.py:375: self.execution_handler.exchanges['okx'] = self._okx_exchange`),
  so it is never in that connect loop.
- `start()` (live_trading_system.py:984-1000) calls `self._okx_connector.connect()`,
  `self._okx_data_provider.start_stream()`, and `self._venue_account.start_streaming()`
  — but NOT `self._okx_exchange.connect()`. The data arm (candles) and the venue
  account (balance/positions) streams start; the order arm (fills) does not.

Consequence: on the live OKX path, orders submitted through `on_order` rest/execute
on the venue, but no `FillEvent` ever streams back. `OrderHandler.on_fill` /
`PortfolioHandler.on_fill` never fire, so the order mirror stays PENDING forever and
the portfolio never updates positions/cash. The core Phase-5 deliverable (live drive
with reconciliation) cannot function. The `__init__` comment at
live_trading_system.py:340 explicitly names `OkxExchange.connect()` as the intended
live-wiring step, and `start()` wires its sibling `start_stream()` — the omission is
asymmetric and clearly unintended.

**Fix:** In `start()`, alongside the existing data-arm / venue-account startup, spawn
the order-arm streams when the OKX exchange is wired:
```python
if self.exchange == 'okx' and self._okx_exchange is not None:
    result = self._okx_exchange.connect()
    if not result.success:
        raise ConfigurationError(
            config_key="okx_exchange_connect",
            config_value=result.error_message,
            reason="OKX order-arm stream startup failed")
```
Place it after `self._okx_connector.connect()` (client + `load_markets` must be up
first) and before `RUNNING`.

## Warnings

### WR-01: `halt()` idempotency guard is not atomic — concurrent halts double-alert and clobber the reason

**File:** `itrader/trading_system/live_trading_system.py:529-546`
**Issue:** `halt()` claims "Idempotent — the first halt wins", but the check-and-set
straddles two separate lock acquisitions. The guard reads `self._status` under
`_status_lock`, sets `_halt_reason`, then RELEASES the lock; `self._status` is only
set to `HALTED` later, inside `_update_status()` (line 658-664), under a *second*
acquisition of the same non-reentrant `threading.Lock`. `halt` is wired to at least
three producers that run on different threads — the engine-thread drift compare
(`portfolio_handler.set_halt_signal(self.halt)`), the OKX order-arm supervisor, and
the OKX data-arm supervisor (both connector-loop threads). Two of them can race:
both pass the `if self._status == HALTED: return` check (neither has reached
`_update_status` yet), both write `_halt_reason` (second wins), and both emit a
CRITICAL `ErrorEvent`. Result: duplicate operator alerts and a `halt_reason` that
reflects the second caller, not the first.
**Fix:** Set the status and stamp the reason under one lock acquisition, and guard the
alert emission on the transition:
```python
with self._status_lock:
    if self._status == SystemStatus.HALTED:
        return
    self._status = SystemStatus.HALTED
    self._halt_reason = reason
# emit exactly-once outside the lock
self._update_status(SystemStatus.HALTED, f'halt: {reason}')   # make this not re-set status, or split notify from set
self.global_queue.put(ErrorEvent(...))
```
(Decouple the status write from the callback-notification in `_update_status`, or add
a dedicated `_set_status_locked` helper, so the CRITICAL alert fires only on the
winning transition.)

### WR-02: restart-rehydrated orders never repopulate the OKX correlation maps — post-restart fills are buffered-and-dropped, cancels silently skipped

**File:** `itrader/execution_handler/exchanges/okx.py:108-127, 308-349, 287-296`
**Issue:** After a restart, `VenueReconciler.reconcile()` rehydrates the order working
set from the store, but the `OkxExchange` in-memory correlation maps
(`_orders_by_venue_id`, `_venue_id_by_order_id`, `_orders_by_clOrdId`) start EMPTY
and are only ever written by `_submit_order` (okx.py:266-281), which does not run for
orders that were submitted in a previous process. Consequences on the live restart
path:
- A fill that streams back for a rehydrated *resting* order (e.g. a bracket SL/TP that
  triggers after restart) cannot be correlated in `_handle_trade`: `venue_id` lookup
  misses, `clOrdId` lookup misses, so it is BUFFERED under `_pending_fills_by_venue_id`
  (okx.py:342-343) and never drained (no `_submit_order` ever runs for that order) —
  the fill is effectively lost. `VenueReconciler` runs only once at startup and does
  not poll, so it does not recover a fill that arrives *after* the reconcile.
- `_cancel_order` (okx.py:290-295) looks up `_venue_id_by_order_id.get(event.order_id)`,
  misses for every rehydrated order, and logs "no known venue id — skipping" — so a
  cancel of a rehydrated resting order is a silent no-op even though the venue still
  holds the resting order.

This also undercuts the `venue_reconciler.py:20` claim that "the 05-05 fill-ID dedup
covers the concurrent-stream case": `_seen_trade_ids` is per-process and empty after a
restart, and the reconciler's synthesized fills (`_emit_reconciling_fill`) carry fresh
`fill_id`s and never populate `_seen_trade_ids`.
**Fix:** After `VenueReconciler` re-links a leg to a venue resting order
(`_relink_bracket`, venue_reconciler.py:326-347) and stamps `venue_order_id`,
repopulate the `OkxExchange` correlation maps for every rehydrated order that carries a
`venue_order_id` (add an `OkxExchange.adopt_venue_correlation(order_id, venue_id, event)`
seam the reconciler calls), so streamed fills correlate and cancels resolve. Persist a
periodic REST reconcile (not just startup) if post-restart resting fills must be caught.

### WR-03: partial-fill reconcile arm mutates `filled_quantity` before validating the transition

**File:** `itrader/order_handler/reconcile/reconcile_manager.py:177-200`
**Issue:** In `_apply_executed`, the partial branch writes
`order.filled_quantity = to_money(order.filled_quantity + increment)` (line 183)
BEFORE calling `order.add_state_change(...)` (line 193). If `add_state_change` returns
`False`, the code returns `(False, False)` and logs "mirror left unchanged" (line 198)
— but `filled_quantity` was already mutated, so the log is false and the in-memory
`Order` is left inconsistent. Because `on_fill` then sees `applied=False` and skips
`update_order`, the mutation is not persisted; with the in-memory store (which returns
the live object, not a copy) the corrupted `filled_quantity` survives in memory, while
the SQL store (fresh rebuild per read) would not — a backend-dependent divergence.
The path is currently latent (the `allow_same_status=True` PARTIALLY_FILLED transition
does not fail), but the ordering is a trap for any future transition-validity change.
**Fix:** Compute and validate the transition first, mutate only on success:
```python
new_filled = to_money(order.filled_quantity + increment)
additional_data = {..., "total_filled": new_filled}
if not order.add_state_change(OrderStatus.PARTIALLY_FILLED, "exchange partial fill",
        additional_data=additional_data, time=fill_event.time, allow_same_status=True):
    self.logger.warning('Partial-fill transition rejected for order %s; mirror left unchanged', order_id)
    return False, False
order.filled_quantity = new_filled
return True, False
```

### WR-04: `_maybe_resume_after_reconnect` re-snapshots but does not re-reconcile, contradicting its own contract

**File:** `itrader/trading_system/live_trading_system.py:615-638`
**Issue:** The docstring states resume takes "a fresh REST snapshot + reconcile" and
`resume_submission()` logs "venue stream reconnected + REST reconcile complete"
(line 591-592), but the body only calls `self._venue_account.snapshot()` (line 632) —
it never re-runs the two-sided `VenueReconciler.reconcile()` that `start()` runs before
`RUNNING`. A sustained disconnect is exactly the window in which external fills /
cancels / hand-actions accrue on the venue; resuming submission after only a balance
snapshot (no fill-delta adoption, no orphan-position halt, no bracket re-link) can
resume trading against an engine state that has silently drifted from venue truth —
the precise failure mode the startup reconcile exists to prevent. At minimum the log
message asserts a reconcile that did not happen.
**Fix:** Either invoke the same reconcile the startup path uses on resume (construct/
retain a `VenueReconciler` and call `reconcile()` inside `_maybe_resume_after_reconnect`
before `resume_submission()`), or downgrade the docstring/log to state that only a
balance snapshot is performed and document why a full reconcile is not required.

### WR-05: adopt-and-continue drift path logs adoption without correcting engine state (repeat-fire risk when the resolver is wired)

**File:** `itrader/portfolio_handler/portfolio_handler.py:733-743`
**Issue:** In `_compare_symbol_drift`, when a beyond-band drift "reconciles to a known
venue event", the code logs "Adopted external venue event" and `return`s — but it does
NOT bring the engine position into agreement with venue truth. The engine `net_quantity`
stays diverged from `venue_qty`. On the next fill or bar-sweep compare the same symbol
is still beyond band; if `_drift_reconciler` again answers `True`, this logs "adopted"
on every tick without ever converging — and if it later answers `False` (e.g. the venue
event ages out of the resolver's window) it escalates to a spurious halt. Currently
dormant because `_drift_reconciler` defaults to `None` (line 123-125) so this branch is
unreachable this phase, but the branch ships as written and is the documented extension
point (`set_drift_reconciler`).
**Fix:** When adopting an external venue event, actually reconcile the engine tally to
venue truth (e.g. synthesize a reconciling `FillEvent` through the idempotent fill path,
mirroring `VenueReconciler._emit_reconciling_fill`) so the next compare converges,
rather than only logging.

---

_Reviewed: 2026-07-02T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
