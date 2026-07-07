---
status: open
created: "2026-06-24"
source: surfaced in v1.5 Phase 5 discuss-phase (cache-scope decision under Model B feed-centric indicators)
tags: [perf, bar-feed, shared-cache, capacity-derivation, screener, multi-bar, deferred, §4.1, §10.G]
resolves_phase: ""
---

# Deep capacity-derived multi-bar shared cache (the raw-history depth)

**Origin:** Surfaced in v1.5 Phase 5 (Stateful Indicators + Shared Bar Cache) discuss-phase while
scoping the shared cache. Phase 5 locked the **feed-centric (Model B)** indicator model (amends
spec §10.H): indicators hold their OWN minimal bounded buffers and the pair self-buffers its β/z
windows, all fed from the BarEvent newest bars. Consequence: **no current consumer reads deep
raw-bar history**, so Phase 5 builds only the NEWEST-bar provision + the registration/capacity
INTERFACE, and DEFERS the deep multi-bar buffer. This todo captures the deferred depth.

**Design of record:** `docs/superpowers/specs/2026-06-24-stateful-indicator-design.md` §4.1
(shared recent-bars cache + capacity = max lookback over consumers), §10.G (two-layer capacity
under multi-timeframe), §6 (screener subsystem deferred but must register lookbacks).

## What Phase 5 SHIPS (where the line is)
- `BarFeed` owns the shared recent-bars read API (§4.1).
- The **newest-bar** provision: one per-symbol pass feeds both the BarEvent payload AND the cache
  newest row (G5 unify) + mark-to-market.
- The consumer-**registration + capacity-derivation INTERFACE** — a pure wiring-time function
  mirroring `universe/instruments.py::derive_instruments` — shaped but driven by raw-bar consumers
  (NOT indicator min_period, since indicators self-buffer under Model B).

## What this todo DEFERS (build when a raw-bar consumer exists)
1. **The deep multi-bar buffer** per `(symbol, timeframe)` holding `max(lookback)` over raw-bar
   consumers — currently nothing reads it (indicators + pair self-buffer).
2. **Two-layer capacity derivation** (§10.G): base-source entry sized to the coarsest consumer in
   base-bar-equivalents; each derived `(symbol, timeframe)` keeps its own depth. (Overlaps the
   deferred multi-TF consolidator todo — see `multi-timeframe-consolidator.md`.)
3. Wiring the capacity-derivation function to actually allocate depth from registered raw-bar
   lookbacks.

## Trigger / when to schedule
When the first **raw-bar-history consumer** lands:
- the **screener subsystem** (deferred, §6) — screens read multi-symbol close windows
  (`bar_feed.py:573` megaframe path today); or
- a **strategy that reads raw multi-bar history directly** (not via a self-buffering indicator).

Until then the newest-bar cache + interface is sufficient. NOTE: multi-instrument / multi-pair
trading in one strategy does NOT need this (that's per-symbol indicator fan-out, which Phase 5
builds — see the per-symbol fan-out decision in 05-CONTEXT.md).

## Tie-in
Closely related to `multi-timeframe-consolidator.md` (the §10.G consolidator that would FILL the
derived-timeframe depths) and the screener subsystem. Likely lands alongside whichever of those
arrives first.
