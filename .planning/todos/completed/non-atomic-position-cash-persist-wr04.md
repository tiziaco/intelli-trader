---
status: deferred
created: "2026-07-05"
source: Phase 05.2 (v1.7) code review finding WR-04 — owner-deferred (tiziaco, 2026-07-05)
tags: [live, durable, restart, persistence, atomicity, portfolio, D-07, resilience, phase-05.3]
resolves_phase: "05.3"
---

# Position persist and cash-scalar persist are non-atomic across a crash (WR-04)

**Origin:** Phase 05.2 (Live-Path Remediation Wave 2) code review,
`.planning/phases/05.2-live-path-remediation-wave-2-restart-real-durable-engine-led/05.2-REVIEW.md` finding **WR-04**.
Owner decision 2026-07-05 (tiziaco): defer to backlog / Phase 05.3. Already acknowledged in-code
(the WR-04 comment in `live_trading_system.py`) as a known non-atomicity.

**Finding:** The position write-through (store-first in `transact_shares`) and the cash-scalar write-through
(`PortfolioHandler._persist_account_state`, later on the `on_fill` path) are two separate durable writes with
no enclosing transaction. A crash BETWEEN them leaves the durable store with positions from one point in time
and cash from another.

**Impact:** On restart, `rehydrate()` restores positions and cash from inconsistent snapshots — the engine's
believed state is internally inconsistent before `VenueReconciler.reconcile()` runs (reconcile then diffs
against a torn baseline).

**Fix direction:** Wrap the position + account-state write-through for a single fill in one durable
transaction (single commit), or restructure the settlement persist so cash and positions advance atomically.
Verify the reconcile baseline is always a consistent snapshot after restart.
