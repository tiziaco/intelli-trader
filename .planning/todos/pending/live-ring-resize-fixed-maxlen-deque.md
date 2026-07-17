---
status: pending
created: "2026-07-17"
source: v1.8 Phase 10 (Strategies Registry) planning — RESEARCH pitfall F-1, option 2; owner ratified the deferral 2026-07-17
tags: [live, bar-feed, ring-buffer, warmup, reconfiguration, timeframe, feed-lifecycle, phase-10-tie-in, f-1]
resolves_phase: "future"
folded_into: ""
---

# Live ring resize — an existing `deque(maxlen=...)` cannot grow

**Origin:** v1.8 Phase 10 planning, pitfall **F-1** (confirmed real by source read). P10 fixed the
*unit* half of F-1; this is the deferred *resize* half (the research's "option 2"). The owner
explicitly ratified deferring it on 2026-07-17 — this todo is the record so the capability gap is not
silently lost.

## The mechanism

`LiveBarFeed` creates each per-symbol ring as `deque(maxlen=self.cache_capacity())`
(`live_bar_feed.py:675`, `:394`). **`maxlen` is fixed at creation.** `cache_capacity()` re-derives
lazily from the registered raw-bar consumers, so re-registering a *deeper* consumer changes the derived
value — but **existing rings do not resize**. Only rings created afterwards (i.e. new symbols) get the
new depth.

## What P10 shipped instead (the floor)

- `10-03` made `derive_warmup_depth` / `required_base_depth` **timeframe-aware** — depth is now derived
  in base-bar units as `max(warmup × ceil(strategy_timeframe / base_timeframe))`. Opt-in via
  `base_timeframe`; omitted → byte-identical to the old `max(s.warmup)` (this is what protects the
  backtest oracle). This fixes **boot/rehydrate** and **newly-created rings**.
- `10-07` / `10-08` **loud-reject** when `required_base_depth` exceeds an existing ring's
  `cache_capacity()`, naming both depths (`UnwarmableTimeframeError`). Fails loud rather than leaving a
  strategy permanently `is_ready == False`, silent and error-free.

## The resulting capability gap (the reason this todo exists)

**D-15 (`timeframe` is constrained-mutable) lands PARTIALLY after P10:**

| Scenario | P10 behaviour |
|---|---|
| Boot / rehydrate a coarse strategy | works — ring sized from persisted config |
| `add` a coarse strategy on a **new** symbol | works — fresh ring gets current capacity |
| `reconfigure` to a coarser timeframe on an **already-warm** symbol | **loud-reject** |

The last row is the gap. In the common homogeneous-timeframe case the ring is sized to the strategy's
own warmup, so *any* live coarsening needs `warmup × multiple` and is rejected. The reject is correct
(loud, not silently dark) but D-15's runtime arm — which the owner deliberately overrode an
"immutable" recommendation to obtain — is not fully delivered until this lands.

Note the reject fires at **trial-validate**, i.e. *before* persist (D-13 ordering), so there is no
"persist and let restart heal" workaround: the change never reaches the DB. The operator's path today
is to change the config and restart, or `remove` + `add` on a fresh symbol.

## Why this is not just a D-15 concern

Two other deferred items need the same primitive — this is a shared blocker, not a one-off:

- **[[warmup-depth-max-concerned-strategy]]** (CF-10, `status: scheduled`) — generalizing
  `derive_warmup_depth` to a per-concerned-strategy `max` changes depth for *existing* symbols, which
  is exactly what a fixed `maxlen` refuses to honour.
- **`strategy-timeframe-finer-than-base-resubscribe.md`** — a base-cadence re-subscribe re-warms all
  affected instances against rings that were sized for the old base.

Both currently assume a depth change takes effect; neither can be correct without resize.

## The correct implementation (when scheduled)

Model it as a **ring-lifecycle operation on the feed**, not as a widening of the single-instance
reconfigure path:

1. Rebuild the ring as a new `deque(maxlen=new_depth)` seeded from the existing contents
   (`deque(old, maxlen=new)` preserves the most-recent `new` items — verify the tail-vs-head semantics
   against the monotonic-guard contract before relying on it).
2. Decide the **grow-only** question: shrinking a ring discards history another strategy may still need
   (the ring is shared per symbol across strategies). Grow-only is the safe default.
3. Preserve `LiveBarFeed`'s monotonic guard and the WR-01 off-grid rejection across the swap — the
   resize must not admit a bar the guard would have dropped.
4. Re-derive via the existing named seam (`derive_warmup_depth` — its docstring pins it as the single
   replaceable depth boundary); do **not** add a second depth path.
5. Once it lands, relax `10-08`'s `UnwarmableTimeframeError` gate from "reject" to "resize then accept",
   and drop the corresponding `must_haves` prohibition.

## Gates that must stay green

Backtest oracle byte-exact `134 / 46189.87730727451` (the ring is live-only / backtest-dark — the
backtest run loop never registers a warmup consumer, `register_strategy_warmup` has exactly one caller
at `session_initializer.py:124`); `test_okx_inertness.py` green.

## Watch for

A strategy that stays permanently `is_ready == False` while raising nothing — `window()` returns a
*short frame*, it does not raise. That is the F-1 signature and the reason this class of bug is worth
failing loud about.
