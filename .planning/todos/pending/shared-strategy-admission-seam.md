---
status: open
created: "2026-07-20"
source: quick task 260720-s6b
tags: [strategy, admission, exception-policy, D-10, refactor, deferred]
resolves_phase: ""
---

# A shared strategy-admission seam owning the zone-1 / zone-2 guard shapes once

**The deeper cause of the whole finding series.** Four separate findings share a single root:

- `260720-ljn` — four DIVERGENT catch tuples across the strategy-admission call sites, which is
  what motivated the shared `StrategyAdmissionError` ancestor in the first place.
- `CR-01` — the `_add_strategy_verb` hole: an arbitrary `init()` raise escaping construction.
- `WR2-02` — the rehydrate divergence, where a bare-`ValueError` residue sat outside
  `_QUARANTINABLE` so ONE stale row aborted the whole live boot.
- `260720-s6b` (this task) — the same hole re-appearing at BOTH `_reconfigure_strategy_verb`
  sites, hidden for a while by a coincidental `ValueError` member in the catch tuple.

None of these is really "a missing except clause". The root is that **exception policy is
DUPLICATED PER CALL SITE instead of owned by one seam** — so every fix only ever reaches the
site someone happened to be looking at, and the next verb starts from zero again. Each
individual fix was correct and none of them was sufficient.

**What the refactor is.** One shared admission seam that owns the two guard SHAPES once:

- **zone 1** (pre-persist, throwaway object) → refuse as a loud no-op, tier-1 WARNING for a
  `StrategyAdmissionError` and tier-2 ERROR for an unexpected kind;
- **zone 2** (post-persist, live mutation) → route into the designed CRITICAL reporting path,
  no rollback, with store/infrastructure calls kept structurally OUTSIDE the guarded body so
  D-19 fail-loud still holds.

Every D-10 verb that invokes `_run_init` on operator-supplied input routes through it,
replacing the per-site guards currently living in `_add_strategy_verb` and (as of `s6b`) both
sites of `_reconfigure_strategy_verb`. New verbs then inherit the policy by construction rather
than by a reviewer remembering the precedent.

**Why it was deferred.** This is a phase, not a quick task. It touches every strategy-admission
call site, needs its own regression coverage per zone, and the seam's shape is a design decision
(a decorator? a context manager? an explicit `admit(zone=...)` helper?) that deserves a proper
discussion rather than being settled inside a bug fix.

**Candidate target:** after Phase 11.

**What `260720-s6b` did instead.** Applied the zone model uniformly to the two reconfigure sites
by hand, pinned both zones with permanent regression tests (including the NON-`ValueError`
coverage that never existed), and recorded the GENERAL RULE in the code comments —
*every D-10 verb invoking `_run_init` on operator-supplied input carries a zone guard, and the
guard's SHAPE follows its zone* — so the next verb inherits the reasoning even before the seam
exists.
