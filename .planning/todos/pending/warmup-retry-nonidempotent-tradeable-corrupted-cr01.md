---
status: deferred
created: "2026-07-07"
source: Phase 07 (v1.7) plan 07-09 code review finding CR-01 — owner-deferred (tiziaco, 2026-07-07)
tags: [live, warmup, readiness, idempotency, retry, indicators, ring, WR-02, CR-02, phase-07-gap-closure, 07-10]
resolves_phase: "07.1"
---

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

## Decisions required (why this was deferred, not fixed inline)

1. **Remediation strategy** — two incompatible approaches:
   - **Reset-then-reabsorb:** clear the ring + `L` and each concerned strategy's per-symbol state
     (`_bar_counts[sym]`, `_recent_closes[sym]`, handle state) before re-warming. Needs new
     `reset_symbol()` methods on the feed AND the strategy. Isolated to the retry path.
   - **Monotonic dedup:** make `absorb_warmup` and `Strategy.update` reject `bar.time <= last_delivered`
     so an overlapping re-fetch is a no-op. Touches the hot `update()` path used by every live bar.
2. **Retry policy** — add a ceiling / backoff so a permanently-unwarmable symbol cannot churn
   FAILED↔retry forever. Cap value + backoff shape TBD.
3. **Scope / priority** — engine is not in live production yet (live-only path). Confirm the swallowed
   `on_bars_loaded` scenario is actually reachable before investing, so the fix is chosen on facts.

## Suggested first step

Confirm reachability (does the CR-02 retry actually re-run `spawn_warmup`/`absorb_warmup` against the
same ring, and is `on_bars_loaded`'s raise-and-swallow path real?), then take the decisions above into a
`07-10` gap-closure plan (or a `07.1` gap-closure phase). Add a regression test that fails on the
duplicate-inflated `is_warm`-flips-tradeable path before fixing.
