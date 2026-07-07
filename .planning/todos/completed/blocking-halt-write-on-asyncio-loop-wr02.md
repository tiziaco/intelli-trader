---
status: deferred
created: "2026-07-05"
source: Phase 05.2 (v1.7) code review finding WR-02 — owner-deferred (tiziaco, 2026-07-05)
tags: [live, halt, durable, threading, asyncio, pitfall-9, D-10, resilience, phase-05.3]
resolves_phase: "05.3"
---

# `halt()`'s blocking `record_halt` SQL write runs on the connector asyncio loop thread (WR-02)

**Origin:** Phase 05.2 (Live-Path Remediation Wave 2) code review,
`.planning/phases/05.2-live-path-remediation-wave-2-restart-real-durable-engine-led/05.2-REVIEW.md` finding **WR-02**.
Owner decision 2026-07-05 (tiziaco): defer to backlog / Phase 05.3 resilience hardening.

**Finding:** During a `connector-fatal` escalation the halt path calls the durable `HaltRecordStore.record_halt`
(a blocking, synchronous SQL write) while executing on the connector's asyncio loop thread — a Pitfall 9
violation (blocking I/O on the event loop). This can stall the loop that drives every venue stream.

**Impact:** A synchronous DB write on the loop thread blocks all in-flight venue coroutines for the write's
duration; under a slow/contended Postgres this widens the fatal-escalation window and can cascade stream
timeouts.

**Fix direction:** Perform the durable halt write off the loop thread (schedule onto the engine thread /
a thread executor, or hand the record to the engine-thread halt handler) so the connector loop is never
blocked on SQL. Preserve the winner-only single-write semantics and the D-10 latch ordering.
