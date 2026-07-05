---
status: deferred
created: "2026-07-05"
source: Phase 05.2 (v1.7) code review finding WR-01 — owner-deferred (tiziaco, 2026-07-05)
tags: [live, halt, durable, restart, start-sequence, D-10, ARCH-4, resilience, phase-05.3]
resolves_phase: ""
---

# Durable-halt refusal is sequenced too late in `LiveTradingSystem.start()` (WR-01)

**Origin:** Phase 05.2 (Live-Path Remediation Wave 2) code review,
`.planning/phases/05.2-live-path-remediation-wave-2-restart-real-durable-engine-led/05.2-REVIEW.md` finding **WR-01**.
Owner decision 2026-07-05 (tiziaco): defer to backlog / Phase 05.3 resilience hardening.

**Finding:** The unresolved-durable-halt refusal check in `start()`
(`itrader/trading_system/live_trading_system.py:1396`) runs AFTER the full connector connect,
venue stream spawn, and the state-mutating `VenueReconciler.reconcile()`. A durably-HALTED engine
therefore performs a full venue handshake (and a reconcile that can adopt fills / mutate the order
mirror) before it refuses to enter RUNNING.

**Impact:** A process supervised into auto-restart while durably halted still touches the venue and
mutates state before latching. The refusal is correct (it does refuse RUNNING) but it should short-circuit
BEFORE any venue I/O or reconcile so a halted engine stays inert.

**Fix direction:** Move the `has_unresolved()` durable-halt gate to the top of `start()` (before the OKX
connect/snapshot/stream/reconcile block), re-latch the fresh instance in-process via `_update_status`,
and return without opening the venue. Keep the D-05 in-process check for reconcile/guard halts raised
later in the same start().
