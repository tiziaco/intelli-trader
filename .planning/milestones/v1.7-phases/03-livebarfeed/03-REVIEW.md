---
phase: 03-livebarfeed
reviewed: 2026-07-01T20:26:31Z
depth: standard
files_reviewed: 3
files_reviewed_list:
  - itrader/price_handler/providers/okx_provider.py
  - itrader/price_handler/feed/live_bar_feed.py
  - itrader/trading_system/live_trading_system.py
findings:
  critical: 1
  warning: 4
  info: 2
  total: 7
status: resolved
resolution: CR-01 + WR-01..WR-04 fixed and committed (a704a637, deab31d7, 9a44effa, 34049962, 54af1372); CR-01 regression-locked by test_gap_backfill_overfetch_delivers_trigger_bar_once. IN-01/IN-02 (info) deferred.
---

# Phase 3: Code Review Report

**Reviewed:** 2026-07-01T20:26:31Z
**Depth:** standard
**Files Reviewed:** 3
**Status:** issues_found

## Summary

Reviewed the Phase-3 LiveBarFeed source changes: the new push-driven ring-buffer
feed (`live_bar_feed.py`, +447 lines), the `ClosedBar` routing-key extension in
`okx_provider.py` (+12 lines), and the `LiveTradingSystem` wiring that swaps
`BacktestBarFeed` for `LiveBarFeed` (+59 lines).

Inertness (lazy imports) and the Decimal edge are handled correctly — the provider
crosses the money boundary via `to_money(str(...))`, the feed never re-casts through
float except at the documented analytics edge (`_base_frame`, D-17), and
`live_bar_feed` is lazy-imported so the backtest path stays inert.

The correctness-critical FEED-04 monotonic guard, however, has a real defect on the
**gap-backfill path**: `_backfill_gap` calls `fetch_ohlcv_backfill(limit=N)` expecting
an interior-bounded result, but the real provider paginates with no upper bound and
over-fetches past the gap into the trigger bar `t` (and beyond). Combined with the
unconditional `_deliver(t)` after `_backfill_gap` in `update()`, this double-delivers
`t` and can rewind the last-delivered stamp `L` — the exact monotonic-guard violation
the phase exists to prevent. The unit/integration tests do not catch it because both
`_StubProvider.fetch_ohlcv_backfill` implementations return the programmed bar list
verbatim, ignoring `since`/`limit` — so the pagination contract the live code depends
on is never exercised.

## Critical Issues

### CR-01: Gap-backfill over-fetch double-delivers the trigger bar and can rewind the monotonic stamp `L`

**File:** `itrader/price_handler/feed/live_bar_feed.py:170-172` and `267-285`;
interacting with `itrader/price_handler/providers/okx_provider.py:269-279`

**Issue:**
`update()` handles a gap (`t > last + tf`) by calling `_backfill_gap(sym, tf, last+tf, t-tf)`
and then **unconditionally** falling through to `_deliver(sym, tf, t, closed_bar)`:

```python
if t > last + tf:
    self._backfill_gap(sym, tf_str, last + tf, t - tf)
self._deliver(sym, tf_str, t, closed_bar)   # runs even after backfill
```

`_backfill_gap` computes `limit = interior-bar-count` and calls
`self._provider.fetch_ohlcv_backfill(sym, tf_str, since=since_ms, limit=limit)`,
assuming the result is bounded to `[first_missing .. last_missing]` (i.e. `[L+tf .. t-tf]`).

But the real `fetch_ohlcv_backfill` (okx_provider.py:269-279) treats `limit` as a
**per-page size** and paginates with `while len(page) == limit:` — it has **no upper
bound**. Fetching from `since=first_missing`, the first page returns exactly `limit`
bars (`[L+tf .. t-tf]`); because `len(page) == limit` and the venue has more bars past
`t-tf` (the trigger bar `t` exists — it just arrived on the stream), the loop keeps
fetching `[t, t+tf, ...]` until a short page is returned.

Consequences when those over-fetched bars are replayed one-by-one through `update()`:
1. The interior bars advance `L` to `t-tf`.
2. The replayed bar `t` is then delivered in-sequence (`t == L+tf`) — `L` becomes `t`,
   a `BarEvent` is emitted, and `t` is appended to the ring.
3. Any bars beyond `t` are also delivered, pushing `L` to `t + k*tf`.
4. Control returns to the outer `update()`, which calls `_deliver(t)` **again** —
   re-appending `t` to the ring (a duplicate ring entry), re-emitting a duplicate
   `BarEvent` for `t`, and setting `_last_delivered` back to `t` (a **rewind** of `L`
   from `t+k*tf`).

This defeats the FEED-04 guarantee that "an out-of-order or replayed bar can never
rewind indicator state." `backfill_on_resume` shares the same `_backfill_gap` helper
and has the same defect on the reconnect path.

The tests miss it: both `_StubProvider.fetch_ohlcv_backfill`
(`tests/unit/price/conftest.py:122` and `tests/integration/test_live_bar_feed_warmup.py:103`)
return `list(self.backfill_bars)` verbatim, ignoring `since`/`limit`, so the unbounded
pagination is never simulated. (Warmup is safe because it calls with `since=None`, which
returns the newest page and terminates pagination immediately — only the `since`-anchored
gap/resume path over-fetches.)

**Fix:** Bound the backfill result to the requested interior in `_backfill_gap` (do not
rely on `limit` capping the provider), and/or guard the post-backfill `_deliver`. For
example, filter fetched bars to the closed range before replay:

```python
def _backfill_gap(self, sym, tf_str, first_missing, last_missing):
    tf = to_timedelta(tf_str)
    since_ms = int(first_missing.value // _NS_PER_MS)
    last_ms = int(last_missing.value // _NS_PER_MS)
    limit = int((last_missing - first_missing) / tf) + 1
    bars = self._provider.fetch_ohlcv_backfill(
        sym, tf_str, since=since_ms, limit=limit)
    # Provider pagination is unbounded above — clamp to the requested interior
    # so the trigger bar t (and anything past it) is NOT replayed here; the
    # outer update() delivers t exactly once.
    for cb in bars:
        if cb["ts"] > last_ms:
            break
        self.update(cb)
```

Add a test whose stub honors `since`/`limit` (or returns bars past `last_missing`) so
the interior-boundary contract is actually asserted.

## Warnings

### WR-01: `update()` in-sequence branch accepts any bar in `(L, L+tf)` and sets `L` off the tf-grid

**File:** `itrader/price_handler/feed/live_bar_feed.py:165-172`

**Issue:** The taxonomy documents in-sequence as `t == L + tf`, but the code reaches
`_deliver` for the entire `else` region `L < t <= L + tf` (only `t < L`, `t == L`, and
`t > L + tf` are branched). An off-grid bar (`L < t < L + tf` — e.g. a sub-timeframe
timestamp from a mis-subscribed channel or a timeframe mismatch) is delivered and sets
`_last_delivered = t` off the tf-grid. Every subsequent bar is then measured against an
off-grid `L`, which can spuriously trip the `t > L + tf` gap branch and cascade.
Confirm-gated venue bars are normally grid-aligned, so this is a robustness/defensive gap
rather than a guaranteed failure, but the guard should reject a non-grid `t` explicitly
instead of silently delivering it.

**Fix:** Make the in-sequence branch explicit and reject/log the off-grid remainder:

```python
if t == last + tf:
    self._deliver(sym, tf_str, t, closed_bar)
else:  # last < t < last + tf — off the tf-grid, not a valid closed bar
    self.logger.warning("Off-grid bar for %s at %s (not L+tf) — dropped", sym, str(t))
```

### WR-02: `_emit` uses `assert` for the bound-queue precondition (stripped under `python -O`)

**File:** `itrader/price_handler/feed/live_bar_feed.py:316-318`

**Issue:** The only guard that `bind()` ran before a bar is emitted is an `assert
self.global_queue is not None`. Under `python -O` (assertions disabled) the assert is
removed and `self.global_queue.put(...)` dereferences `None`, raising `AttributeError`.
On the live path this fires inside the stream/async task or the warmup loop, where it is
swallowed by the broad `except` in `_event_processing_loop` / connector task handling and
silently drops bars. An `assert` is for invariants, not for a runtime wiring precondition
that depends on caller ordering.

**Fix:** Raise a typed error instead:

```python
if self.global_queue is None:
    raise StateError("LiveBarFeed", "unbound",
                     "update() requires a bound queue — call bind() first")
self.global_queue.put(BarEvent(time=bar.time, bars={sym: bar}))
```

### WR-03: Hardcoded `'BTC/USDT'` / `'1d'` warmup args risk ring-key vs universe-membership mismatch

**File:** `itrader/trading_system/live_trading_system.py:527` (and `:281`, `:290-293`)

**Issue:** `start()` calls `self.feed.warmup('BTC/USDT', '1d')` with the symbol/timeframe
hardcoded, duplicating the values passed to the `OkxDataProvider` constructor at line 281.
The feed keys its ring on whatever string the provider stamps into `ClosedBar['symbol']`
(here `'BTC/USDT'`), while `feed.bind(self.global_queue, universe.members)` binds
membership derived from the strategy/screener universe (`derive_membership`, line 422).
If the strategy declares its instrument in a different form (e.g. `'BTCUSD'` or
`'BTC-USDT'`), the ring key and the ticker a strategy passes to `window()` will not match,
and `_find_ring` raises `MissingPriceDataError`. Two hardcoded copies of the subscription
config also drift independently.

**Fix:** Source the warmup symbol/timeframe from a single wiring constant (or from
`self._okx_data_provider`'s configured `symbol`/`timeframe`), and assert the streamed
symbol string is a member of `universe.members` at wiring time so a format mismatch fails
loudly instead of at first `window()`.

### WR-04: `okx_provider._process_row` guards row *length* but not field validity — malformed numeric fields crash the stream task

**File:** `itrader/price_handler/providers/okx_provider.py:228-248`

**Issue:** `_process_row` skips rows shorter than 9 fields, but then calls `int(row[0])`
and `to_money(str(row[1..5]))` on the remaining fields with no guard. A row of correct
length carrying a non-numeric/empty field (a malformed or partial venue frame) raises
`ValueError` out of `_process_row`, propagates through the `for row in rows` loop in
`_stream_candles`, and terminates the candle task — the stream silently dies with no
reconnect. The module docstring claims malformed rows are "skipped-and-logged, never
indexed blindly," but that only holds for the length check, not field-level malformation.
(Largely pre-existing parsing, but the phase now depends on this loop as the live driver.)

**Fix:** Wrap the field extraction in a try/except that logs and skips the row, keeping the
`async for` loop alive:

```python
try:
    closed: ClosedBar = {"ts": int(row[0]), "open": to_money(str(row[1])), ...}
except (ValueError, TypeError, IndexError):
    self.logger.warning("Unparseable OKX candle row — skipping")
    return
```

## Info

### IN-01: `_backfill_gap` recomputes `tf` the caller already derived

**File:** `itrader/price_handler/feed/live_bar_feed.py:171,276`

**Issue:** `update()` computes `tf = to_timedelta(tf_str)` and then `_backfill_gap`
recomputes the same `tf = to_timedelta(tf_str)` from the string. Minor redundant work and a
second parse path; pass `tf` through instead. Purely cosmetic.

### IN-02: `_newest_bars` is keyed by symbol only, not `(symbol, timeframe)`

**File:** `itrader/price_handler/feed/live_bar_feed.py:305,322-324`

**Issue:** The ring is keyed on `(sym, tf_str)` but `_newest_bars` is keyed on `sym`
alone, so if a single symbol ever streams two timeframes the newest-bar provision is
clobbered by whichever timeframe delivered last. The live feed streams one base timeframe
per symbol today, so this is latent, not active — but the asymmetry with the ring key is a
trap for a future multi-timeframe live consumer. Consider keying `_newest_bars` on
`(sym, tf_str)` (with a `newest_bar(ticker)` that resolves the base timeframe) for
consistency.

---

_Reviewed: 2026-07-01T20:26:31Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
