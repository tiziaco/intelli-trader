# Deferred seam: max-across-concerned-strategies warmup depth (K)

**Deferred from:** Phase 7 (Live Dynamic-Universe Hardening), plans 07-06 / 07-07.
**Captured:** 2026-07-06

## What

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

## Trigger to implement

A future phase adds a strategy whose declared indicator warmup exceeds `cache_capacity()`, OR a symbol is
shared by strategies with divergent warmups such that the fixed `cache_capacity()` fallback would under-fetch.
At that point:
1. Add a depth-hint seam on StrategiesHandler exposing `max(strategy.warmup for concerned strategies)`.
2. Wire it into `UniverseHandler` at the composition root (`_init_live_session`).
3. Change the add-branch K computation to `max(cache_capacity(), depth_hint(sym)) + _WARMUP_MARGIN`.
