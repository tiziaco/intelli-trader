# Retired plans — Phase 11

## 11-07b-PLAN.md — retired 2026-07-21, never executed

Split out of 11-07 on 2026-07-21 to carry the deletions (`_link_venue_account_to_portfolios`,
its `RuntimeError(>1)` guard, the facade `_venue_account` singleton) safely, sequenced after
11-08's distinct-account invariant and 11-09's coordinator rehome.

**It became empty before its wave arrived.** Plan 11-09 deleted all three targets as a direct
consequence of its own work: making reconciliation per-portfolio left the single-account link
function with no caller, and the facade alias collapse removed `_venue_account` as one of five
aliases of an object the composition root now holds directly. 11-09 also rehomed
`StreamRecoveryHandler` onto a `venue_accounts` callable — the other rehoming 11-07b was to do.

Its two remaining items were absorbed into 11-10:
  1. the stale `conformance.py:3,51` docstrings
  2. the shared-resting-order-book investigation that blocks 11-11

Kept for provenance: the deletion-safety analysis in its `must_haves` documents WHY those
deletions were dangerous in isolation, which is why 11-09's approach (replace the object, then
the aliases fall away) was safer than deleting scalars and adding a source separately.
