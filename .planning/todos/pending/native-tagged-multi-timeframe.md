---
status: open
created: "2026-07-01"
source: surfaced in v1.7 Phase 3 (LiveBarFeed) discuss-phase (FEED-01 multi-timeframe handling; Option A lock)
tags: [architecture, bar-feed, timeframe, bar-identity, multi-timeframe, backtest, live, parity, oracle-gated, deferred, post-v1.7]
resolves_phase: ""
---

# Native tagged multi-timeframe (timeframe as part of Bar identity), unified across backtest + live

**Origin:** Surfaced in v1.7 Phase 3 (LiveBarFeed) discuss-phase while deciding how the live feed
serves multiple timeframes to a strategy (5m + 15m + 1h, etc.). We locked **Option A — base-timeframe
stream + pull-resample** (backtest parity): live subscribes the finest needed timeframe as the SINGLE
`BarEvent` stream; higher timeframes are pulled via `feed.window(ticker, tf)` and resampled from the
ring, identical to backtest. This todo captures the architecturally-superior model we deliberately
deferred.

## The decision we made (and why it's a compromise)
- **Locked (Phase 3):** Option A. Multi-timeframe strategies work exactly as in backtest — base-tf
  BarEvents drive the cadence; higher tf via pull-resample. No schema change.
- **Deferred (this todo):** Option B — **native per-timeframe, tagged events** (the Nautilus/LEAN model).
  Judged *architecturally most correct and most robust in production*, but NOT adopted in Phase 3
  because it only stays coherent if backtest adopts the same model — otherwise higher-tf bars are
  computed two different ways (venue-native live vs resample backtest) and the milestone's byte-exact
  parity gate breaks.

## Why Option B is the better long-term architecture
1. **A bar's timeframe is part of its identity.** `Bar` today = `{time, o, h, l, c, v}` with NO
   timeframe field; `BarEvent` = `{time, bars: dict[ticker, Bar]}` with NO timeframe. This only works
   because backtest runs a single base timeframe — an implicit invariant, not clean modeling. Nautilus
   encodes it as `BarType` (instrument + timeframe + aggregation + price-type).
2. **Venue-official bars beat aggregations.** OKX computes the 15m candle authoritatively (own
   `confirm`, correct volume, correct no-trade-sub-interval handling). Resampling 5m→15m can **silently
   diverge from reality** when a sub-bar is missing (gap/illiquidity). Native never drifts.
3. **Explicit per-tf dispatch scales** — "trade on 5m, filter on 1h": each stream drives its own
   stateful indicators on its own authoritative bucket-close.

## What this todo DEFERS (build as a dedicated, oracle-gated multi-timeframe phase)
1. **Add timeframe to `Bar`/`BarEvent` identity** (or a `BarType`-style key) so a bar is fully
   specified by (symbol, timeframe, …).
2. **Native per-timeframe subscriptions on the live path** — subscribe OKX `candle{tf}` per timeframe;
   each closed bar emits its own tagged `BarEvent`; downstream dispatches on the timeframe tag.
3. **Adopt the same tagged model in backtest** — so both paths compute higher-tf bars identically
   (this is the *live half* of the deferred `multi-timeframe-consolidator` todo, §10.G — the two
   together are "real multi-tf support").
4. **Re-baseline + re-validate the oracle** after the schema/dispatch change (byte-exact or
   re-cross-validated), determinism double-run identical.

## Related deferred items
- [[multi-timeframe-consolidator]] — `.planning/todos/multi-timeframe-consolidator.md` (backtest/
  aggregation side; spec §10.G). This todo is its live/native counterpart.
- [[unify-backtest-direct-bar-generation]] —
  `.planning/todos/unify-backtest-direct-bar-generation.md` (the FEED-05 bar-direct unification; a
  sibling backtest-event-model refactor).

## References
- `.planning/phases/03-livebarfeed/03-CONTEXT.md` — FEED-01 multi-timeframe decision (Option A) + the
  full architectural verdict.
- `itrader/core/bar.py` — `Bar` struct (no timeframe field today).
- `itrader/events_handler/events/market.py` — `BarEvent` (no timeframe field today).
- `itrader/price_handler/feed/bar_feed.py` — `window()` / `_resampled_frame` (the pull-resample path
  Option A reuses).
- nautilus-trader `model/data.pyx` (`BarType`, `Bar`) — reference for tagged multi-tf identity.
