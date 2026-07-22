---
title: portfolio.cash raises StateError on a live venue portfolio before the first snapshot
created: 2026-07-21
source: v1.8 Phase 11 plan 11-09 (executor-flagged)
severity: latent
resolves_phase: null
---

## What

Plan 11-09 attaches each portfolio's `VenueAccount` at **composition time** (required by its
identity acceptance criterion, which must hold before `start()`). `Portfolio.cash`
(`portfolio.py:285`) delegates to `self.account.balance` (`:295`), and `VenueAccount.balance`
(`account/venue.py:513`) raises a typed `StateError` when the venue cache is still unsnapshotted
(D-15 — surface unsnapshotted loud, never a silent 0 that could authorize a bad order).

So there is now a window — composition until the first `snapshot()` inside `start()` — where
reading `cash` on a live venue portfolio raises. Before 11-09 the attach happened at `start()`
*after* `snapshot()`, so the window did not exist.

## Why it is not urgent

Verified 2026-07-21 against the merged tree: nothing on the boot path reads `cash` in that window.
The only reader is `PortfolioHandler.delete_portfolio` (`portfolio_handler.py:376`,
`if portfolio.cash > 0`), which has **zero callers** anywhere in `itrader/`.

## Why it still matters

The next person to add a `cash` read on a live portfolio — logging, a status surface, a
pre-trade check, an operator endpoint — hits it, and the failure is a raise rather than a wrong
number. `delete_portfolio` would also surface `StateError` instead of its intended
`InvalidPortfolioOperationError` if it ever gains a caller.

## Options if it becomes real

- Defer the attach to `start()` (reverts 11-09's identity criterion — would need a different proof)
- Give `Portfolio` a `cash_or_none` / `is_cash_readable` accessor for pre-snapshot callers
- Snapshot eagerly at attach time (couples composition to venue I/O — probably wrong)
