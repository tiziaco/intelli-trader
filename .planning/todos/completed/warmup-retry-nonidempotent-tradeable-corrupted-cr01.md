---
status: resolved
created: "2026-07-07"
resolved: "2026-07-07"
resolved_by: "07-10-PLAN.md (see 07-10-SUMMARY.md) — Option B unified monotonic idempotency, Level 2"
source: Phase 07 (v1.7) plan 07-09 code review finding CR-01 — owner-deferred (tiziaco, 2026-07-07)
tags: [live, warmup, readiness, idempotency, retry, indicators, ring, WR-02, CR-02, phase-07-gap-closure, 07-10]
resolves_phase: "07.1"
---

> **RESOLVED 2026-07-07 by 07-10** — absorb_warmup honors the existing `_last_delivered`
> cursor (CR-01-feed), `Strategy.update` gains a `_last_bar_time` per-symbol cursor
> (CR-01-strategy), and `UniverseHandler` gains a Level-2 cadence-gate + 3-strike retry
> policy (CR-01-retry). A RED-first headline regression proved the corruption reachable
> pre-fix and unreachable after. Oracle byte-exact (134 / 46189.87730727451). See
> `.planning/phases/07-live-dynamic-universe-hardening/07-10-SUMMARY.md`.

# WR-02 retry re-warm is non-idempotent — a warm-verify MISS can flip a symbol tradeable on CORRUPTED ring/indicator state (CR-01)

**Origin:** Phase 07 plan 07-09 (post-review remediation) code review,
`.planning/phases/07-live-dynamic-universe-hardening/07-09-REVIEW.md` finding **CR-01** (BLOCKER).
Owner decision 2026-07-07 (tiziaco): fix the two WARNINGS (WR-01/WR-02) inline; **defer CR-01 to a
Phase 07 gap-closure ("07-10")**. The two warnings are already fixed and committed
(`fix(07-09): make OKX unsubscribe a true no-op + close cleanup coro on spawn failure`).

## Finding

WR-02 marks a symbol `FAILED` on an `is_warm` MISS *after* `self._feed.absorb_warmup(...)` has
already run, and composes this with the CR-02 next-poll FAILED-retry. Neither re-warm path is
idempotent against re-delivery of an overlapping warmup window:

- `absorb_warmup` (`itrader/price_handler/feed/live_bar_feed.py:~321-333`) does an unconditional
  `ring.append(bar)` with **no timestamp dedup** (confirmed independently — it is the controlled
  single-purpose absorb that deliberately bypasses `_deliver`'s duplicate/stale guard).
- `StrategiesHandler.on_bars_loaded` → `Strategy.update` (`itrader/strategy_handler/base.py:~479-512`)
  is **not timestamp-guarded**: it unconditionally increments `_bar_counts`, appends to
  `_recent_closes`, and advances the stateful indicator handles.

**Sequence (reachability caveat — NOT yet confirmed to fire in practice):** the target scenario is a
*swallowed* partial strategy warmup — `strategies_handler.on_bars_loaded` raised and was caught by the
per-handler route isolation, so the strategy is partial/not warm while the ring absorb succeeded. The
symbol is marked FAILED and retried next poll. Warmup re-spawns, re-fetches a largely-overlapping REST
window, fed AGAIN:
1. `absorb_warmup` re-appends the same bars → duplicate-timestamp bars in the bounded ring →
   `window()` returns a corrupted trailing window.
2. `strategy.update` re-feeds overlapping bars → `_bar_counts` inflates past `min_period` even off
   duplicates; SMA/MACD O(1) recurrence state advanced over duplicated values → garbage indicator state.
3. On retry `is_warm` now returns True (count crossed depth) → `mark_ready` + `subscribe` → the symbol
   becomes **tradeable in LIVE with corrupted indicators**, driving live order decisions off bad state.

This is the exact "half-warmed tradeable" defect class WR-02 was meant to eliminate, converted into a
*garbage-warmed* tradeable reached automatically via CR-02 auto-retry. If duplicates instead never
re-cross depth, the path degenerates into unbounded FAILED↔retry churn with no backoff.

## Reachability — CONFIRMED (2026-07-07)

Traced end-to-end; the corruption is reachable with **no exception required**:
- `on_poll` folds a FAILED symbol back into `added` (`universe_handler.py:342-345`) → `_begin_warmup`
  → `spawn_warmup` → `BarsLoaded` → `on_bars_loaded` → `absorb_warmup` **on the same ring, no reset**.
- Dispatch isolates errors **per-consumer** (`full_event_handler.py:146-150`) and live mode is
  publish-and-continue, so `strategies_handler.on_bars_loaded` can fail while
  `universe_handler.on_bars_loaded` still absorbs the ring (the review's trigger).
- Simpler trigger (no exception): any first attempt where the warmup window < strategy `min_period`
  (new-ish symbol / provider under-delivers / poll cadence faster than bar close) → FAILED → retry
  re-appends the same bars → count crosses `min_period` off duplicates → READY + subscribe →
  tradeable on a duplicate-corrupted ring + inflated indicators.

## Decided design (2026-07-07, owner: tiziaco) — Option B "unified monotonic idempotency", Level 2

**ts_event is `Bar.time` — no new timestamp field.** The fix applies the timestamp already present as a
monotonic *key* in the two places that currently ignore it.

1. **Feed side — reuse the existing cursor, stop bypassing it.** `absorb_warmup` must honor the SAME
   `_last_delivered` guard `_deliver` already uses: reject `bar.time <= _last_delivered[(sym, tf)]`
   before `ring.append`. Zero new state; initial warmup unaffected (cursor unset → all pass). Feed
   cursor **stays `pd.Timestamp`** (the feed's ring/`window()` model is pandas-native — see
   [[livebarfeed-depandas-time-model-datetime]]; full de-pandas migration deferred to next milestone).
2. **Strategy side — one new per-symbol cursor, stdlib `datetime`.** Add `_last_bar_time: dict[str,
   datetime]` to the base `Strategy`; store raw `bar.time` (no pandas, no conversion). In `update`:
   reject `bar.time <= last` before touching `_bar_counts` / `_recent_closes` / indicator handles.
   Keyed by symbol (each strategy owns one timeframe). Also hardens the live per-tick path against a
   duplicate bar on reconnect resend.
3. **Drop semantics (both cursors):** `==` (duplicate) → **silent** drop (expected, benign);
   strict `<` (out-of-order, older than last) → **`warning`** + drop. Reject is `<=`, never `<`.
4. **Retry policy = Level 2 (cadence-gate + warn).** Once idempotency lands, retry can no longer
   corrupt state, so this is hygiene/observability: do NOT re-warm a FAILED symbol more often than its
   bar interval (no new data before then), and emit a `warning` after N consecutive failed re-warms
   (start N=3) so a stuck symbol surfaces — but keep trying (never auto-drop). Level 3 hard-ceiling +
   quarantine-drop is explicitly OUT (ping-pongs against the selection source without a cooldown set;
   delisting is better handled by markets-freshness — see
   [[okx-markets-map-freshness-delisting-detection]]).

## Test to write first (RED)

A regression that drives the confirmed path — first warmup shorter than `min_period` (or a swallowed
`strategies_handler.on_bars_loaded`) → FAILED → CR-02 retry re-warm → assert the ring has NO duplicate
timestamps and `is_warm` does NOT flip True off duplicates (symbol stays not-tradeable until genuinely
warm). Then implement Option B to turn it GREEN.

## Target

A `07-10` gap-closure plan (or `07.1` gap-closure phase). Backtest oracle must stay byte-exact
(all changes live-only / inert on the backtest path).
