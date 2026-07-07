---
status: open
created: "2026-06-24"
source: surfaced in v1.5 Phase 5 discuss-phase (G1 scope decision; spec §10.G / §10.D-1)
tags: [perf, indicators, multi-timeframe, consolidator, bar-feed, shared-cache, deferred, G1, §10.G]
resolves_phase: ""
---

# Full multi-timeframe bar consolidator (register-at-base / consolidate-up)

**Origin:** Surfaced in v1.5 Phase 5 (Stateful Indicators + Shared Bar Cache) discuss-phase
while scoping G1 (the indicator update-trigger seam). The data model is RESOLVED in the design
spec §10.G (register-at-base, consolidate-up; `base_timeframe ≤ min(timeframe)`), but Phase 5
deliberately ships only the **interface + golden-collapsed implementation** — NOT the full
consolidator. This todo captures the deferred remainder so it is not lost.

**Design of record:** `docs/superpowers/specs/2026-06-24-stateful-indicator-design.md` — §10.G
(multi-timeframe data model, worked example), §10.D-1 (framework delta: feed an aggregator from
the fast stream; do NOT resample-per-tick), §10.E-G1 (the update-trigger seam).

## What Phase 5 SHIPS (so this todo knows where the line is)
- The update-trigger **seam/interface** defined as: "a consolidator emits on `(symbol, timeframe)`
  bucket-close → drives both the derived-bar buffer and `indicator.update()`" — but the interface
  **must NOT hardcode per-base-tick updates** (spec §10.D-1).
- Only the `base_timeframe == timeframe` path implemented — for golden SMA_MACD `1d == base == 1d`,
  so the trigger collapses to "every tick."
- The wiring-time assertion `base_timeframe ≤ min(timeframe)` over all registered consumers.

## What this todo DEFERS (build when a real multi-TF consumer exists)
1. **Bucket-close consolidation for arbitrary `(symbol, timeframe)`** — a consolidator that
   consumes the base feed and emits a completed higher-TF bar on bucket-close, driven by the
   existing rule-4 visibility contract (`bar_feed.py:24-30`), NOT a per-tick resample. (Nautilus
   `BarAggregator` / LEAN consolidator analog; copy LEAN's single-call
   `RegisterIndicator(symbol, indicator, timeframe)` ergonomic.)
2. **Two-layer capacity derivation** (spec §10.G, refines §4.1's flat `max(lookback)`):
   - Base-source entry `(symbol, base)`: capacity = `max` over consumers of lookback in
     base-bar-equivalents = `max(lookback_c × timeframe_c / base_timeframe)` — the coarsest
     consumer binds.
   - Each derived `(symbol, timeframe)`: keeps its own `lookback` depth.
3. **Per-TF indicator update routing** — P1's indicators update on each 1h bucket-close, P2's on
   each 4h bucket-close (every 4th 1h bar), both fed from the one base stream.

## Trigger / when to schedule
When the concrete near-term requirement lands: **the same instrument traded on two portfolios at
two different timeframes** (the §10.G worked example — e.g. BTCUSD on a 1h strategy and a 4h
strategy at once). No current consumer needs it; the golden path is single-TF.

## Worked example to validate against (from spec §10.G)
BTCUSD on P1 @ 1h (lookback 100) + P2 @ 4h (lookback 50), store base = 1h →
base-source holds **200** 1h-bars (4h consumer binds: 50 × 4); derived `BTCUSD@1h` depth 100,
`BTCUSD@4h` depth 50. The bucket-close **is** the `indicator.update()` trigger (G1-a).

## Constraints to preserve
- Resample UP only, never DOWN (`base_timeframe ≤ min(timeframe)`).
- One look-ahead contract: rule-4 visibility governs bucket completion — provider-native
  higher-TF bars would re-open that audit (deferred exception for session-aligned equities only;
  N/A for 24/7 crypto, which resamples exactly).
- Single backtest/live code path — live backfill flows through the same `update(bar)` path
  (spec §10.D-3), no bulk-warmup bypass.
