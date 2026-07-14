---
status: open
created: "2026-07-14"
source: 07-REVIEW.md (phase-07 code-review gate, IN-02 — owner-approved deferral)
tags: [live, reconcile, startup, redundant-rest-call, correctness-neutral, performance, deferred, IN-02]
resolves_phase: ""
handling: fold into the end-of-milestone live_trading_system.py / live-reconcile refactor
---

# Phase-07 review IN-02 — double `snapshot()` on the startup reconcile path

**Origin:** The phase-07 code-review gate (`07-REVIEW.md`) surfaced this as an INFO nit.
It is **correctness-neutral** (idempotent REST snapshot), so it was owner-approved to defer
rather than clean now — the owner plans a further refactor of the live-system surface
(`live_trading_system.py` and the reconcile collaborators) at the end of this milestone, and
this tidy-up belongs in that pass, not as a one-off edit to a just-completed phase.

## The bug (little one — redundant, not wrong)

On startup reconcile the venue account is REST-snapshotted **twice**, back to back:

- `ReconciliationCoordinator.run_startup_reconcile` calls `account.snapshot()`
  (`itrader/portfolio_handler/reconcile/reconciliation_coordinator.py:125`), then constructs a
  `VenueReconciler` whose `.reconcile()` calls `self._venue_account.snapshot()` **again**
  (`itrader/portfolio_handler/reconcile/venue_reconciler.py:139`).

The REST snapshot is idempotent — the second overwrites the first with the same venue truth — so
this is **not a state defect**. The only cost is one extra venue REST round-trip against the
startup rate budget, **once per process start** (never on a hot path, never per-bar/per-order).

(Note: the review also mentioned a "rehydrate twice", but those are *different* objects —
`portfolio_handler.rehydrate` at coordinator:116 vs `store.rehydrate` at venue_reconciler:135 —
so that is NOT a true duplicate. The only genuine duplication is `snapshot()`.)

## Fix (pick one owner of the startup REST snapshot)

Either:
- have `ReconciliationCoordinator` take the snapshot once and let `VenueReconciler.reconcile()`
  assume a freshly-snapshotted account (drop its inner `snapshot()` call at venue_reconciler:139), OR
- vice-versa — let `VenueReconciler` own the snapshot and drop the coordinator's `account.snapshot()`
  at coordinator:125.

Prefer the first: the coordinator already sequences `snapshot() → start_streaming() → link` before
building the reconciler, so it is the natural owner; `VenueReconciler.reconcile()` would then document
a precondition that the account is already snapshotted.

## Danger / scope

- **Live danger:** zero (idempotent, startup-only). Not oracle-relevant, oracle-dark, live-only.
- **Watch:** if a future change makes `snapshot()` non-idempotent or side-effecting, this stops being
  correctness-neutral — revisit then rather than assuming it stays harmless.
