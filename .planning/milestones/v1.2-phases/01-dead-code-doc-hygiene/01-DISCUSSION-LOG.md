# Phase 1: Dead Code & Doc Hygiene - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-11
**Phase:** 1-Dead Code & Doc Hygiene
**Areas discussed:** Convention doc home, Stale-doc edit style, Importer-update scope, Discovered dead code

---

## Convention Documentation Home

| Option | Description | Selected |
|--------|-------------|----------|
| Both, CONVENTIONS authoritative | Full write-up in CONVENTIONS.md, concise pointer in CLAUDE.md (read every session) | ✓ |
| CLAUDE.md only | Durable, survives map regeneration; CONVENTIONS.md overwritten on regen | |
| CONVENTIONS.md only | Single formal home; risk of regen overwrite + less per-session visibility | |

**User's choice:** Both, CONVENTIONS authoritative
**Notes:** CLAUDE.md already partially documents indentation + run-mode policy — reinforce/cross-reference rather than duplicate wholesale.

---

## Stale-Doc Edit Style

| Option | Description | Selected |
|--------|-------------|----------|
| Trim to truth + terse ref | Remove obsolete CONCERNS screener item; drop redundant ROADMAP self-reference, keep one factual closure line (quick 260610-sjp). Net reduction. | ✓ |
| Annotate-and-keep with dates | Leave entries, mark closed/done with dated notes — max audit trail, grows current-state docs | |
| Delete outright, no ref | Remove with no traceability — leanest, loses why/when-closed pointer | |

**User's choice:** Trim to truth + terse ref
**Notes:** User questioned whether ROADMAP.md was growing too much and whether FL-01/FL-02 are
truly done. Verified in code: **yes** — `portfolio.py` raise sites are all typed domain
exceptions (FL-01); `portfolio_id: PortfolioId` on all three event facts (FL-02). Found the
ROADMAP 999.5-(d) line already reads "done" with a self-referential "corrected in Phase 1/DEAD-02"
forward-pointer that becomes self-stale once DEAD-02 lands. Conclusion: DEAD-02 should make
ROADMAP slightly *smaller* (trim the self-reference), not bigger. No broader prune (scope creep).
ROADMAP at 392 lines judged healthy.

---

## Importer-Update Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Full sweep + suite gate | Make OrderHandler standalone, drop __init__ re-export, partial-file ABC delete (keep PortfolioStateStorage), grep + full suite + mypy --strict | ✓ |
| Minimal, fix-on-break | Delete + patch direct import errors as suite surfaces them — risks missing dynamic/string refs | |

**User's choice:** Full sweep + suite gate
**Notes:** Reality surfaced during scout — the targets are NOT importer-free: `OrderHandler(OrderBase)`
inherits it and `__init__` re-exports `OrderBase` + `OrderStorage`; the 3 ABCs share `base.py`
with the live `PortfolioStateStorage`. The `get_last_close` test reference
(`test_bar_event_ohlc.py:62`) is a false alarm (tests a `Bar` object via `not hasattr`, not the ABC).

---

## Discovered Dead Code

| Option | Description | Selected |
|--------|-------------|----------|
| Touched-path cleanup, logged | Remove now-dead artifacts in edited files; log anything bigger to FIX-LIST. Matches CLEANUP-STANDARD. | ✓ |
| Strictly the 3 named targets | Touch nothing beyond the named items; leave orphaned imports | |

**User's choice:** Touched-path cleanup, logged
**Notes:** Applies to orphaned `abc`/`abstractmethod`/`typing` imports left in `base.py` after ABC removal.

---

## Claude's Discretion

- Exact wording/placement of convention write-ups within CONVENTIONS.md sections.
- Plan/wave decomposition (deletions vs doc edits combined or separate) — planner's call.

## Deferred Ideas

None — discussion stayed within phase scope. Broader ROADMAP/CONCERNS pruning and the
result-changing 999.5 backlog items were explicitly excluded as scope creep.
