---
status: scheduled
created: "2026-07-06"
source: Phase 7 (v1.7 Live Dynamic-Universe Hardening) plans 07-06 / 07-07 — deferred seam
tags: [live, warmup, universe, bar-feed, depth-hint, strategies-handler, seam-only, phase-7-tie-in]
resolves_phase: "P6"
folded_into: "v1.8 spec §18 — CF-10 (P6 LiveRunner/SessionInitializer, seam-only); renumbered post-P4-merge"
---

# Deferred seam: max-across-concerned-strategies warmup depth (K)

**Deferred from:** Phase 7 (Live Dynamic-Universe Hardening), plans 07-06 / 07-07.
**Captured:** 2026-07-06
**Folded into v1.8 as CF-10 (P7), seam-only — 2026-07-08.**

## What v1.8 P7 does NOW (seam-only — resume point for later)

**Scope locked at fold (CF-10, seam-only):** P7 is already rehoming `_LiveWarmupConsumer` →
`StrategyWarmupConsumer` and rewriting `UniverseHandler` init (`_initialize_live_session` →
`SessionInitializer`) — i.e. it rebuilds the exact wiring this seam plugs into. So P7 **shapes the
depth-hint interface** while it is in that code, but does **NOT** change the behavioural K computation
(no roster exercises it today — see "Why deferred" below).

**P7 delivers (the seam):**
- A depth-hint **interface** on `StrategiesHandler` — e.g. `warmup_depth_hint(symbol) ->
  max(strategy.warmup for strategies concerned with symbol)` — designed but **not yet consumed** to
  change fetch depth. Shape it so the future consumer is a one-line wire-up, not a re-plumb.
- Thread that seam through `SessionInitializer` / `UniverseHandler` construction (the new composition
  root), so the hint is *available* at the point the add-branch K is computed.
- The add-branch K stays `cache_capacity() + _WARMUP_MARGIN` (unchanged, byte-for-byte behaviour).

**P7 does NOT do (resume here when the trigger lands):**
- Step 3 below — changing the K computation to `max(cache_capacity(), depth_hint(sym)) +
  _WARMUP_MARGIN`. That is the only behavioural change and it waits for a real deeper-warmup roster.

When you pick this up later, the seam + composition wiring already exist; you only implement the
`max(...)` swap in the add-branch and add a test for a divergent-warmup roster.

## What (original TODO — full deferred design)

Phase 7's async warmup fetches `K = cache_capacity() + _WARMUP_MARGIN` bars per added symbol
(`live_bar_feed.py:252-253`, `_WARMUP_MARGIN = 5`). When a single symbol is shared by MULTIPLE strategies
with DIFFERENT declared indicator warmups, the venue-correct depth is
`K = max(cache_capacity(), max(strategy.warmup for concerned strategies)) + _WARMUP_MARGIN` — driven by an
injected depth-hint seam that the StrategiesHandler (which owns strategy warmups) provides at composition.

## Why deferred (not built this phase)

RESEARCH OQ4 confirms the `cache_capacity() + _WARMUP_MARGIN` fallback is **SAFE for the current
SMA_MACD-only roster**: `cache_capacity()` = 100 (03-04 D-13 registration) is already ≥ the deepest declared
SMA_MACD indicator warmup (100 = `max(SMA50, SMA100, MACDHist15)`). So there is no roster today for which the
fallback under-fetches. Building the max-concerned-strategy seam now would be speculative wiring with no
behavioral difference.

## ⚠ Re-evaluate: v1.8 P10 invalidates the deferral rationale (added 2026-07-17)

The "Why deferred" reasoning above rests explicitly on **"the current SMA_MACD-only roster"** — a fixed,
homogeneous, compile-time roster. **v1.8 Phase 10 (Strategies Registry) demolishes that premise:** D-01
rehydrates arbitrary persisted instances from `store × catalog × codec` at boot, and D-10 adds arbitrary
strategies at runtime via `STRATEGY_COMMAND` — with divergent warmups AND divergent timeframes. The
trigger condition below ("a symbol shared by strategies with divergent warmups") therefore becomes
**reachable in P10**, where it was unreachable when this was deferred.

This is a flag to **re-evaluate, not a claim that it is now broken**: `derive_warmup_depth` remains a
GLOBAL `max` post-P10, which is conservative per-symbol (it over-fetches for a shallow strategy rather
than under-fetching). The efficiency cost grows with roster divergence; the correctness case needs a
fresh read against the P10 roster model before this is scheduled.

**Related, and a hard blocker on any depth change this todo makes:**
[[live-ring-resize-fixed-maxlen-deque]] — a ring is a `deque(maxlen=...)` **fixed at creation**, so
changing the derived depth does NOT resize an already-created ring. Step 3 below assumes the new K takes
effect; it will not for existing symbols.

**Also note P10 changed this function's contract:** `10-03` made it timeframe-aware
(`derive_warmup_depth(strategies, *, base_timeframe=None)`, depth in base-bar units as
`max(warmup × ceil(strategy_timeframe / base_timeframe))`) and added the shared `required_base_depth`
helper. Re-read the current signature before implementing — the "P7 delivers (the seam)" description
above predates it.

## Trigger to implement

A future phase adds a strategy whose declared indicator warmup exceeds `cache_capacity()`, OR a symbol is
shared by strategies with divergent warmups such that the fixed `cache_capacity()` fallback would under-fetch.
**(Both are reachable as of P10 — see the re-evaluate note above.)**
At that point:
1. Add a depth-hint seam on StrategiesHandler exposing `max(strategy.warmup for concerned strategies)`.
2. Wire it into `UniverseHandler` at the composition root (`_init_live_session`).
3. Change the add-branch K computation to `max(cache_capacity(), depth_hint(sym)) + _WARMUP_MARGIN`.
