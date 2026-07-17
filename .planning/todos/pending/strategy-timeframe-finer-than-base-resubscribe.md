---
status: pending
created: "2026-07-17"
source: surfaced in v1.8 Phase 10 (Strategies Registry) discuss-phase — Area 3 (atomic reconfiguration) timeframe-mutability boundary
tags: [strategy, reconfiguration, timeframe, live-feed, feed-subscription, live-control-plane, next-milestone, phase-10-tie-in]
resolves_phase: "future"
folded_into: ""
---

# Runtime timeframe reconfiguration FINER than the feed's base cadence (shared-stream re-subscribe)

**Origin:** Surfaced in v1.8 Phase 10 (Strategies Registry) while scoping STRAT-03 atomic
reconfiguration (`quiesce → apply → re-warmup`). P10 makes an instance's `timeframe` runtime-mutable,
but **only to a value compatible with the live feed's base cadence** — a multiple of / not finer than
`LiveBarFeed.base_timeframe`. A change to a timeframe **finer than the base cadence** (e.g. base `1d`,
operator wants `1h`) is **rejected loudly** in P10 because the feed has no finer stream to read. This
todo is the deferred capability to support it.

## The P10 boundary (the floor)
Within P10, `reconfigure(timeframe=…)` is accepted when the new timeframe is a multiple of the feed's
base cadence (coarser-or-equal): the mechanism is a plain re-warm on the new grid (dark-then-warm if it
grows the required history), no feed change, no `min_timeframe` ripple (streaming finer-than-needed is
harmless; the stream is already up). A **finer-than-base** (or non-multiple) change is refused — a
documented loud no-op / rejection, exactly like P9's RTCFG-04 immutable-key rejections. To change an
instance to a finer timeframe today: operator runs the strategy on the finer timeframe by other means
(e.g. compose the feed at a finer base up front, or remove+add under a finer-base feed).

## Why finer-than-base is the genuinely heavy case
The `LiveBarFeed` carries a single `base_timeframe` (the subscribed stream's cadence), rings per
`(symbol, timeframe)`, and **rejects off-grid bars** (`live_bar_feed.py` — "a sub-timeframe bar from a
mis-subscribed channel or a timeframe mismatch"). So a strategy timeframe finer than the base has **no
stream to read**. Delivering it requires **re-subscribing the shared OKX candle channel at a finer base
cadence** — which affects **every** symbol/strategy on that feed, not just the reconfigured instance.
That is a cross-cutting feed-lifecycle operation (re-subscribe + re-warm all affected instances +
`min_timeframe` recompute driving the base), categorically heavier than a single-instance re-warm.

## The correct implementation (when scheduled)
Do NOT try to widen the single-instance reconfigure path to carry it. Model it as a **feed-cadence
change** in its own right:
1. **Resolve the new required base** = min across all live strategies' timeframes after the change
   (`min_timeframe` recompute).
2. **Re-subscribe the shared stream** at the finer base cadence (venue channel swap) — the connector /
   `LiveBarFeed` subscription lifecycle, on the engine thread, guarded like the P7 stream-recovery seam.
3. **Re-warm every affected instance** on the new grid through the existing P7
   `spawn_warmup → BarsLoaded → WR-02 warm-verify` pipeline (all instances go dark until re-warmed, not
   just the reconfigured one).
   **BLOCKED ON [[live-ring-resize-fixed-maxlen-deque]]** (added 2026-07-17, from P10's F-1): a finer
   base cadence means every existing symbol's ring needs *more* base bars, but a ring is a
   `deque(maxlen=...)` **fixed at creation** — re-registering a deeper consumer does NOT resize it.
   Step 3 silently assumes the new depth takes effect; it will not for any already-created ring. Resize
   must land first (or as part of this).
4. **Atomicity:** the whole feed-cadence swap is one quiesced operation — no instance trades on the
   torn (old-base ring vs new-timeframe) state; validate → persist → apply → re-warm, mirroring the
   P10 STRAT-03 ordering (P9 D-15).

## RESEARCH prerequisite (also flagged for P10)
Pin the live feed's **multi-timeframe model** first: does `LiveBarFeed` **aggregate** base bars up to a
strategy's coarser timeframe, or does each timeframe require its **own subscribed stream**? That answer
sets both the P10 coarser-than-base re-warm mechanism AND the shape of this finer-than-base feature
(pure re-subscribe vs. add a finer aggregation source).

## When to schedule
Next milestone or later, once P10's single-instance reconfigure + the P7 warm-verify pipeline are
landed. Natural fit alongside any live feed-subscription / multi-timeframe work.

## Tie-in
- Extends the P10 STRAT-03 `reconfigure` allowlist (P10 rejects finer-than-base; this adds the path).
- Reuses: P7 `spawn_warmup`/`on_bars_loaded`/WR-02 warm-verify gate, the connector/`LiveBarFeed`
  subscription lifecycle, the P7 stream-recovery engine-thread I/O seam.
- Related: `pair-strategy-live-reconfiguration.md` (both extend the P10/P7 reconfigure + readiness seams).
