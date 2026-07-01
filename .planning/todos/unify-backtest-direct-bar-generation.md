---
status: open
created: "2026-07-01"
source: surfaced in v1.7 Phase 3 (LiveBarFeed) discuss-phase (FEED-05 emission model; Option B lock)
tags: [refactor, event-model, bar-feed, time-event, routes, backtest, oracle-gated, deferred, post-v1.7]
resolves_phase: ""
---

# Unify the backtest loop to direct bar generation (bar-direct, drop the TimeEvent→pull indirection)

**Origin:** Surfaced in v1.7 Phase 3 (LiveBarFeed) discuss-phase while deciding FEED-05 (how the
live feed replaces `TimeGenerator`). We locked **Option B — live emits `BarEvent` directly** onto
the BAR route (framework-idiomatic: Nautilus/LEAN/backtrader all deliver bars straight to the bar
handler; the driver differs, the handler is shared). This leaves a **deliberate, temporary
asymmetry**: backtest still uses the `TimeEvent → generate_bar_event → BarEvent` *pull* model
(D-20), while live uses direct *push*. This todo captures unifying the **backtest** path onto the
same bar-direct model so both paths share one event model.

## Why deferred (NOT done in Phase 3)
- Collides head-on with the v1.7 milestone prime directive: **"deploy live without disturbing the
  byte-exact backtest oracle"** (SMA_MACD → 134 trades / `final_equity 46189.87730727451`,
  `check_exact=True`).
- Rewrites the most oracle-sensitive code in the system — the backtest run loop + the
  `EventHandler._routes` TIME/BAR structure. Even a "behavior-preserving" reorder risks the
  byte-exact number and, critically, the **seeded-RNG draw ordering** (`performance.rng_seed`).
- Requires re-proving byte-exactness AND re-running the `backtesting.py` / `backtrader`
  cross-validation oracles. That is a dedicated oracle-gated refactor phase with its own oracle
  re-baseline — not something to fold into "build LiveBarFeed."

## What Phase 3 SHIPS (so this todo knows where the line is)
- **Live** emits `BarEvent` directly → BAR route (`update(closed_bar)` constructs the `Bar`,
  validates monotonicity, appends to the ring, writes `newest_bar`, puts a single-ticker
  `BarEvent`).
- The **TIME route / `TimeEvent` / `screen_markets` are preserved but dormant** on the live path —
  reserved as the Phase-6 **screening/poll cadence** (a real clock tick, decoupled from bar
  delivery, à la Nautilus clock timers / LEAN scheduled universe selection). Phase 3 simply does
  not route bars through them.
- **Backtest is untouched** — keeps `TimeGenerator → TIME route → generate_bar_event → BarEvent`.

## What this todo DEFERS (build as a post-v1.7 oracle-gated refactor)
1. **Convert the backtest driver to emit `BarEvent` directly** — the `TimeGenerator`/loop produces
   `BarEvent`s (or a bar iterator does) straight to the BAR route; remove the
   `TimeEvent → generate_bar_event` pull indirection (one fewer event per loop iteration).
2. **Repurpose `TimeEvent` to its honest meaning** across both paths — a scheduled screening/poll
   cadence (decoupled from bar production), consistent with the Phase-6 "Lean poll seam."
3. **Re-baseline + re-validate the oracle** — prove 134 / `46189.87730727451` byte-exact after the
   reorder (or, if the reorder legitimately changes results, re-cross-validate against
   `backtesting.py` + `backtrader` and freeze a new numerical reference), plus determinism
   double-run identical.
4. **Collapse the backtest/live asymmetry** — both paths share one bar-direct event model; the
   driver (loop vs socket) differs, the BAR handler + downstream routes are identical.

## References
- `.planning/phases/03-livebarfeed/03-CONTEXT.md` — FEED-05 decision (Option B) + rationale.
- `itrader/events_handler/full_event_handler.py` — the `_routes` TIME/BAR literal (D-14/D-17).
- `itrader/trading_system/simulation/time_generator.py` — the backtest `TimeEvent` source.
- `itrader/price_handler/feed/bar_feed.py` — `generate_bar_event` (D-20, the pull factory).
- v1.7 milestone gate: `.planning/ROADMAP.md` (oracle byte-exact / no W1/W2 regression).
