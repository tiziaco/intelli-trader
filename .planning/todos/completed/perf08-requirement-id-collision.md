---
status: resolved
created: "2026-06-25"
resolved: "2026-06-26"
source: Phase 8 verification (08-VERIFICATION.md advisory) — REQUIREMENTS.md PERF-08 ID reused
tags: [docs, requirements, traceability, perf-08, naming-collision]
resolves_phase: ""
---

> **RESOLVED 2026-06-26 at v1.5 milestone close (option 2 — renumber the deferred items).** The
> delivered Phase 7/8 hot-path work keeps PERF-07 (Phase 7) / PERF-08 (Phase 8); the two
> still-deferred v2 items formerly under those IDs were renumbered PERF-09 (EthBtc dedup) / PERF-10
> (O(n²) guard). REQUIREMENTS.md v1 PERF list + traceability table updated (now 11 v1 reqs across
> Phases 1-8, 100% coverage) and archived to `milestones/v1.5-REQUIREMENTS.md`.

# Resolve the PERF-08 requirement-ID collision in REQUIREMENTS.md

**Origin:** Phase 8 verification (08-VERIFICATION.md) flagged that `PERF-08` is used for **two
different things**:
- In `REQUIREMENTS.md`: a deferred v2 item (an O(n²) guard).
- In the Phase 8 ROADMAP entry + all 08-*-PLAN.md frontmatter (`requirements: [PERF-08]`): the
  hot-path fusion/prebuild/msgspec work that was just delivered.

**Impact:** Documentation/traceability inconsistency only — **no functional gap**. Phase 8 shipped and
is gate-verified; the collision just makes the requirement ID ambiguous in traceability.

**Fix options (pick at milestone-close or next doc sweep):**
1. Renumber the Phase 8 hot-path requirement to a fresh ID (e.g. `PERF-09`) and update the ROADMAP
   entry + the 6 plan frontmatters + REQUIREMENTS.md traceability.
2. OR renumber the deferred v2 O(n²)-guard item to a fresh ID and let PERF-08 formally denote the
   delivered Phase 8 work.

Recommend (2) if the delivered work is the more "canonical" PERF-08, else (1). Either way update
REQUIREMENTS.md traceability so the delivered Phase 8 requirement maps cleanly.

**Note:** good candidate to fold into `/gsd-complete-milestone` (the milestone close already touches
REQUIREMENTS.md traceability).
