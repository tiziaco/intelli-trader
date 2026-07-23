---
id: venue-requirement-id-collision-v18
title: "VENUE-01..07 is used by TWO different v1.8 phases (P5 and P11.1)"
status: pending
severity: medium
source: orchestrator, during phase 11.1 close
created: 2026-07-22
resolves_by: v1.8 milestone close
---

# `VENUE-*` requirement IDs collide within milestone v1.8

`.planning/REQUIREMENTS.md` defines the `VENUE-*` namespace **twice**, in the same milestone:

| Block | Heading | IDs |
|-------|---------|-----|
| A | `### Venue Registry + Bundle (P5)` (line ~127) | VENUE-01 … VENUE-07 |
| B | `### One Venue Path + Account Ownership (P11.1 — added 2026-07-22)` (line ~353) | VENUE-01 … VENUE-08 |

Both blocks are now fully `[x]`. The same string means different things depending on block:

- **VENUE-03 (P5)** — connectors memoized by `(venue, account_id)`; credentials at the composition root.
- **VENUE-03 (P11.1)** — the paper venue plugin (D-04).
- **VENUE-06 (P5)** — `VenueLifecycle` orchestrator.
- **VENUE-06 (P11.1)** — `rng` joins `EngineContext` (D-07).

## Why it matters

Milestone-close traceability keys on the requirement ID. With two definitions live, "VENUE-03 validated"
is ambiguous, and any per-ID coverage report will either double-count or silently pick one block. This is
the same class as the **PERF-07/PERF-08 collision** that v1.5 had to resolve at its close (resolution
there: delivered work kept the original IDs, the other set was renumbered).

Note this did NOT affect phase 11.1's execution or verification — both ran against the P11.1 block
explicitly and all 8 are genuinely implemented (`11.1-VERIFICATION.md`, 8/8). This is a bookkeeping
defect in the requirements ledger, not a code defect.

## Fix shape

Renumber one block before v1.8 milestone close. Renaming the **P11.1** set (e.g. `VENUE-*` → `VOWN-*`
for "venue ownership", or `VENUE-1x`) is lower-churn than renaming P5's, since P5 shipped earlier and is
referenced in `PROJECT.md`'s Validated section (line ~852) and in `05-VERIFICATION.md`. Update in step:
- `.planning/REQUIREMENTS.md` (both the block and the Traceability section)
- `.planning/ROADMAP.md` Phase 11.1 requirements line
- the 10 `11.1-*-PLAN.md` frontmatter `requirements:` fields and `11.1-*-SUMMARY.md` `requirements_completed`
- `11.1-VERIFICATION.md`, `11.1-CONTEXT.md`
