---
status: deferred
created: "2026-07-05"
source: Phase 05.2 (v1.7) code review finding WR-05 — owner-deferred (tiziaco, 2026-07-05)
tags: [live, dedup, restart, reconcile, order-mirror, D-08, idempotency, resilience, phase-05.3]
resolves_phase: ""
---

# `ReconcileManager` applied-trade dedup ring is not restart-seeded (WR-05)

**Origin:** Phase 05.2 (Live-Path Remediation Wave 2) code review,
`.planning/phases/05.2-live-path-remediation-wave-2-restart-real-durable-engine-led/05.2-REVIEW.md` finding **WR-05**.
Owner decision 2026-07-05 (tiziaco): defer to backlog / Phase 05.3.

**Finding:** Phase 05.2 made the PORTFOLIO settled-trade dedup ledger durable across restart
(`PortfolioHandler.rehydrate()` seeds `_settled_venue_trade_ids` from `transactions.venue_trade_id`).
The order-handler side — `ReconcileManager`'s in-session applied-trade dedup ring (Plan 05.2-03, A5) —
is NOT restart-seeded: on a live restart it starts EMPTY.

**Impact:** After restart, a re-delivered venue trade's order-mirror reconciliation is guarded only by the
`add_fill` quantity guards, not by the applied-set. The portfolio ledger is protected (durable-seeded) but
the order mirror leans on a weaker backstop for the same re-delivery.

**Fix direction:** Seed the `ReconcileManager` applied-trade ring on restart from a durable source
(mirror the portfolio ledger's `transactions.venue_trade_id` seeding, or persist the applied-set), so both
the portfolio and order-mirror dedup arms survive a restart symmetrically.
