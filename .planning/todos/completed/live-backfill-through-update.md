---
status: resolved
created: "2026-06-24"
resolved: "2026-07-07"
source: surfaced in v1.5 Phase 5 discuss-phase (Area 8 / spec §10.D-3); deferred, roadmap-tracked
tags: [live-trading, backfill, warmup, indicators, bar-feed, single-code-path, deferred, §10.D-3, N+4]
resolves_phase: "v1.7 (LiveBarFeed live path)"
---

# Route live-start backfill through the same update(bar) path (single code path)

> **RESOLVED in v1.7 (verified at milestone close, 2026-07-07).** The requirement was met
> exactly: `LiveBarFeed.warmup()` REST-fetches `depth` bars and replays each through the same
> `update()` path (`price_handler/feed/live_bar_feed.py:267,293`), and `:280-281` documents the
> deliberate absence of any bulk `warmup_from` fast-path (LX-09, the parity decision) — precisely
> what this todo required. All backfill entry points (`warmup`, `backfill_on_resume`, gap replay)
> funnel through `update()`. Wired at `live_trading_system.py:1747`.

**Origin:** Surfaced in v1.5 Phase 5 (Stateful Indicators + Shared Bar Cache) discuss-phase,
Area 8. Phase 5 builds the stateful-indicator `update(bar)` surface and the `BarFeed` interface
but does NOT implement live (`LiveBarFeed` stays interface-only). The decision was to **defer**
shaping the live-warmup/backfill path — but track it so it isn't lost and so the live milestone
(N+4 — Live Trading Readiness) picks it up.

**Design of record:** `docs/superpowers/specs/2026-06-24-stateful-indicator-design.md` §10.D-3
(framework delta 3) + §4.1 (LiveBarFeed ring-buffer backing) + §2 goal-2 (backtest/live parity,
one code path).

## The decision to implement later
When live trading is built (N+4), historical warmup at live-start MUST replay bars through the
**identical `update(bar)` path** the backtest uses (Nautilus `request_bars()` → same `handle_bar`
/ `update_raw`). Do **NOT** add a separate bulk `warmup_from(series)` fast-path — a second
state-building code path can diverge from per-bar `update()` and re-opens the look-ahead/parity
audit the single-path design exists to close. The warmup region is simply "indicators not yet
`is_ready`."

## Why deferred (and the accepted risk)
- `LiveBarFeed` is not implemented in Phase 5, so there's nothing to wire yet.
- **Accepted risk:** Phase 5's Plan A interface is shaped without this in mind, so it *could* bake
  in update-only-from-feed assumptions that make a clean single-path backfill harder to retrofit.
  Soft mitigation (not a Phase 5 requirement): when Plan A defines the `BarFeed` / indicator
  `update` surface, prefer an `update(bar)` entry point that a future backfill loop could call
  directly, rather than coupling state-building exclusively to the live feed callback.

## When to schedule
N+4 — Live Trading Readiness (Backlog 999.3): real-time data engine + live execution. This is a
sub-task of standing up `LiveBarFeed` + live strategy warmup. Added to ROADMAP backlog so GSD
surfaces it when N+4 is promoted.
