---
phase: 05-real-sandbox-path-reconciliation-persistence-live-drive
plan: 05-13
reviewed: 2026-07-04T00:00:00Z
depth: standard
files_reviewed: 3
files_reviewed_list:
  - itrader/execution_handler/exchanges/venue_correlation.py
  - itrader/execution_handler/exchanges/okx.py
  - tests/unit/execution/test_venue_correlation.py
findings:
  critical: 0
  warning: 3
  info: 2
  total: 5
status: issues_found
---

# Phase 05 (Plan 05-13): Code Review Report

**Reviewed:** 2026-07-04
**Depth:** standard
**Files Reviewed:** 3
**Status:** issues_found

## Summary

Plan 05-13 lifts the OKX arm's four insert-only correlation structures (three
venue-id/order-id/clOrdId maps, the late-fill buffer, and the dedup set) into a
new cohesive, socket-free `VenueCorrelationIndex` and wires `OkxExchange` to
delegate to it. The core mechanics the plan targets are implemented correctly:

- **Lock discipline / WR-03** is sound. Every map/ring/counter read+write is
  guarded by the single non-reentrant `_correlation_lock`. `resolve` performs the
  full dedup + venue-id/clOrdId resolve + buffer + mark-seen in ONE lock hold; the
  FillEvent mint (`_emit_fill`) and `global_queue.put` always happen OUTSIDE the
  lock, and `register`/`adopt`/`release` return buffered trades for the caller to
  re-drain outside the lock. No fill is minted under the lock and there is no
  reentrant-deadlock path.
- **Money policy** is clean end-to-end: the cumulative counter is `Decimal`, the
  venue edge crosses via `to_money(str(amount))`, and no `float` touches money.
- **Partial vs. full self-release** is correct: `record_fill` accumulates and
  reports terminal on `cumulative >= order.quantity` (`>=` tolerates over-fill);
  partials retain entries; `release` drains-then-evicts, emitting buffered late
  fills before dropping correlation (no WR-02 regression).
- **Idempotency** of `release` on an unknown/already-released venue_id is a clean
  no-op, and the bounded dedup ring FIFO eviction keeps the companion set in sync.
- **Indentation** is correct: `venue_correlation.py` is 100% tab-indented (the
  only leading-space lines are docstring bullet continuations); no space-indented
  code was introduced in `okx.py`.

The findings below are residual bounding gaps and an emit/dedup ordering hazard,
not defects in the primary lifecycle path. None are blockers, but WR-01 and WR-02
each leave a growth vector open that the plan's R2 goal ("bound the growth") does
not fully close.

## Warnings

### WR-01: clOrdId map still grows unbounded on the submit-failure and fast-fill-race-full-fill paths

**File:** `itrader/execution_handler/exchanges/venue_correlation.py:115-135, 226-247`; `itrader/execution_handler/exchanges/okx.py:305-321, 408-420`
**Issue:** `release` only drops the `_orders_by_clOrdId` entry via
`_clordid_by_venue_id[venue_id]`, which is populated **only** by `register`/`adopt`
— never by `register_pending`. Two live paths therefore leak past R2's bound:

1. **Submit failure / no venue id.** `_submit_order` calls
   `self._index.register_pending(client_order_id, event)` (writes
   `_orders_by_clOrdId`) *before* the `create_order` RPC. If the RPC raises (caught
   in `on_order` → `FillEvent(REFUSED)`) or `response` carries no `id`, `register`
   never runs and that clOrdId entry is orphaned forever. Over a long live session
   with intermittent submit rejections this is exactly the unbounded-growth vector
   WR-05 set out to close.

2. **Fast-fill-race full fill resolved via clOrdId.** When a market fill streams in
   after `register_pending` but before `register`, `resolve` resolves it via the
   clOrdId fallback and returns `venue_id = trade["order"]` (a venue id NOT yet in
   `_orders_by_venue_id`). `_handle_trade` then calls
   `record_fill(venue_id, ...)`; if it terminalizes, `release(venue_id)` finds
   nothing in `_orders_by_venue_id` → `order is None` → it never drops the orphaned
   `_orders_by_clOrdId` entry. Worse, `_submit_order` then proceeds to
   `register(venue_id, ...)` and re-adds three now-DEAD entries
   (`_orders_by_venue_id` / `_venue_id_by_order_id` / `_clordid_by_venue_id`) for an
   order that has already fully filled — no further fill will ever fire `release`,
   so those entries live for the process lifetime.

**Fix:** Track the clOrdId on the pending write and key its cleanup independently of
the venue-id resolution. Two concrete options:
```python
# In register_pending, also record the reverse link so release can find it
# even when register never ran:
def register_pending(self, clordid: str, order: OrderEvent) -> None:
    with self._correlation_lock:
        self._orders_by_clOrdId[clordid] = order
        self._clordid_by_order_id[order.order_id] = clordid   # NEW reverse link

# In release, when order is None, still attempt clOrdId cleanup via order_id
# (requires resolve to return the order_id), OR expose a release_pending(clordid)
# for the submit-failure branch and call it from on_order's REFUSED path.
```
At minimum, add a `release_pending(clordid)` path invoked from the
`on_order` submit-failure branch so a rejected submit does not orphan its clOrdId
entry, and in the fast-fill full-fill case have `release` also pop the clOrdId map
by the resolved order's `order_id`.

### WR-02: `resolve` marks a trade id seen before `_emit_fill` validates the payload — a malformed fill permanently consumes its dedup slot

**File:** `itrader/execution_handler/exchanges/venue_correlation.py:181-183`; `itrader/execution_handler/exchanges/okx.py:392-438`
**Issue:** `resolve` calls `_mark_seen_locked(trade_id)` on the `"emit"` outcome
*before* the caller mints. `_emit_fill` then validates the payload and returns
`False` (skip) when `price`/`amount`/`timestamp` is missing. The trade id is already
recorded as seen, so if the venue redelivers the same `trade['id']` on reconnect
with a complete payload, `resolve` classifies it as `"duplicate"` and the fill is
**silently lost** — no FillEvent is ever emitted for a trade that did settle. This
is preserved-not-introduced behavior (the pre-refactor `_handle_trade` also marked
seen before `_emit_fill`), but the refactor was the opportunity to fix it and the
docstring claims "never crashed... skipped-and-logged" without noting the fill is
also un-recoverable.
**Fix:** Do not consume the dedup slot for a fill that was not actually emitted.
Either (a) move mark-seen to occur only after a successful emit (return the
resolved order from `resolve` but let the caller call `mark_seen` post-emit — at
the cost of a second lock hold and a re-send race window), or (b) validate the
price/amount/timestamp presence inside `resolve` before marking seen and return an
`"uncorrelated"`/`"malformed"` outcome so the slot stays free for a corrected
re-send. Given the WR-03 single-hold requirement, (b) is the cheaper fix.

### WR-03: uncorrelated fills are not deduped, so a reconnect re-send double-buffers and later double-emits

**File:** `itrader/execution_handler/exchanges/venue_correlation.py:176-179`; `itrader/execution_handler/exchanges/okx.py:487-491`
**Issue:** In `resolve`, the `"buffered"` branch appends to
`_pending_fills_by_venue_id` but never marks the trade id seen (mark-seen only runs
on `"emit"`). If the same uncorrelated fill is re-sent during the pre-correlation
window (reconnect within the fast-fill race), `resolve` does not dedup it — the dedup
guard `trade_id in self._seen_trade_ids` misses — so the identical trade is appended
to the buffer **twice**. When `register`/`adopt`/`release` later drain the buffer,
both copies emit a FillEvent with the same `venue_trade_id`. Correctness is salvaged
only by the downstream CR-01 `venue_trade_id` settlement dedup; within the index the
economic trade is double-counted (and would double-advance the cumulative counter if
the drain goes through `_handle_trade`).
**Fix:** Dedup on `trade['id']` before buffering — either mark the trade id seen when
buffering (and un-mark / re-key on drain), or check membership of an
already-buffered id before `setdefault(...).append(trade)`:
```python
if venue_id is not None:
    bucket = self._pending_fills_by_venue_id.setdefault(venue_id, [])
    if trade_id is None or trade_id not in self._seen_trade_ids:
        bucket.append(trade)
        if trade_id is not None:
            self._mark_seen_locked(trade_id)   # dedup buffered re-sends too
    return ResolveResult(None, venue_id, "buffered")
```

## Info

### IN-01: `capacity=0` makes the dedup set grow unbounded while the ring stores nothing

**File:** `itrader/execution_handler/exchanges/venue_correlation.py:90, 195-205`
**Issue:** With `capacity=0`, `deque(maxlen=0)` never stores an element, but
`_mark_seen_locked` guards the eviction with `if self._capacity > 0` and still runs
`self._seen_trade_ids.add(trade_id)`. The membership set therefore grows without
bound and is never evicted — the opposite of the R3 goal — for a degenerate but
constructor-reachable config value.
**Fix:** Reject `capacity < 1` in `__init__` (`raise ValueError`) or clamp to a
minimum of 1, so the ring and set can never desynchronize.

### IN-02: `test_partial_fill_retains_entries_full_fill_self_releases` does not model the real counter flow

**File:** `tests/unit/execution/test_venue_correlation.py:141-161`
**Issue:** The test feeds `record_fill(0.2)` + `record_fill(0.3)` = `0.5` to reach
terminal, but the interleaved `resolve({"amount": "0.1"})` at line 150 is never fed
to `record_fill`. In the real `_handle_trade` flow every emitted fill advances the
counter, so that 0.1 fill would count too (0.2 + 0.1 + 0.3 = 0.6 > 0.5), meaning the
index would terminalize one fill earlier than the test's manual accounting implies.
The unit is correct in isolation; the concern is fidelity — the test does not exercise
the emit → `record_fill` coupling that production relies on.
**Fix:** Either drive the counter through the same trades passed to `resolve`, or add
an integration-level assertion on `OkxExchange._handle_trade` that confirms every
emitted fill advances the cumulative counter exactly once.

---

_Reviewed: 2026-07-04_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
