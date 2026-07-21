---
title: OCO sibling scan is O(n) over the whole resting book and now scales with portfolio count
created: 2026-07-21
source: v1.8 Phase 11 (resting-book safety question, resolved by inspection)
severity: performance
resolves_phase: null
---

## Correctness: SAFE — and the reason is load-bearing

Cross-portfolio OCO interference is structurally impossible. `MatchingEngine._resting` is
`dict[OrderId, OrderEvent]` keyed by a globally-unique UUIDv7 (`core/ids.py:17`). The sibling
scan (`matching_engine.py:433`) filters on `sibling.parent_order_id == bracket` where `bracket`
is an `OrderId`, so two portfolios can never match. Pass 2 (`:384`) and Pass 1 (`:354`) are safe
for the same reason.

**The safety comes from the single UUIDv7 id scheme, NOT from portfolio awareness** —
`matching_engine.py` contains zero references to `portfolio_id`. A future optimisation that
pre-indexes the scan on something less unique would silently reintroduce cross-portfolio
cancellation. Plan 11-10 adds a comment at the scan recording this.

## Performance: worth revisiting

The scan is O(n) over the entire book per filled bracket. Its own comment says: *"negligible at
backtest scale (< ~100 resting orders per symbol). Pre-index by parent_order_id if the book ever
grows to thousands."*

Multi-portfolio-live multiplies the book by the portfolio count. At two paper accounts this is
irrelevant. It becomes worth measuring when either portfolio count or resting-orders-per-portfolio
grows — the fix is already named in the comment (a `parent_order_id -> children` index maintained
at the same sites that mutate `_resting`).

Not urgent. Recorded so the growth condition is remembered rather than rediscovered under load.
