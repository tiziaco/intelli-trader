# Phase 5: Cache Classification (#3) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-30
**Phase:** 5-Cache Classification (#3)
**Areas discussed:** Artifact form & location, Vestigial config-knob cleanup, New-cache classification & map freshness

---

## Artifact form & location

| Option | Description | Selected |
|--------|-------------|----------|
| In-repo docs/ markdown | Durable shipped doc (docs/CACHE-CLASSIFICATION.md) next to code; survives .planning archival; serves FastAPI work; grep-match criterion stays near code | ✓ (combined) |
| Planning artifact only | Lives under .planning/; GSD-consistent but archived with milestone, less discoverable from code | |
| Code-level annotations | Tag each ~14 site with a docstring/comment marker + thin index; can't drift but scattered | ✓ (combined) |

**User's choice:** "in-repo docs/ + a small code-level annotation" — both homes (D-01).
**Notes:** Wants the readable inventory map AND the drift-proof per-site anchor.

---

## Vestigial config-knob cleanup

| Option | Description | Selected |
|--------|-------------|----------|
| Remove them this phase | Delete PerformanceSettings.enable_caching / cache_size_mb (Q8 #14); oracle-inert; the one real code edit; needs suite green | ✓ |
| Document-only, defer removal | Keep Phase 5 strictly documentation; note knobs as a cleanup candidate + defer | |

**User's choice:** Remove them this phase (D-02).
**Notes:** Blast radius confirmed this session — config/system.py:45-46 (zero consumers) + system.default.yaml:32,34 (YAML mis-keyed as max_cache_size_mb; clean both).

---

## New-cache classification & map freshness

| Option | Description | Selected |
|--------|-------------|----------|
| Own tag + fresh re-verify | Give the 3 Phase-4 live working-set caches their own class (e.g. (d)); re-grep all of itrader/ at HEAD so the map matches current code exactly | ✓ |
| Footnote under existing scheme | Keep strict a/b/c, mention Phase-4 caches as the "one genuinely new cache" without a full HEAD reconciliation | |

**User's choice:** Own tag + fresh re-verify (D-03).
**Notes:** Map must be true to current HEAD, not a verbatim copy of the 2026-06-27 Q8 table; the live working-set cache is "a separate construct" per research.

---

## Claude's Discretion

- Exact docs/ filename/path and the code-annotation marker convention/format; whether every site or only non-obvious ones are annotated.
- Final letter/label for the new live-retention class (proposed (d)).
- Map layout (flat table vs grouped) and how it cites Q8 / Q7 / FEATURES anti-features.
- Whether removed knobs need a migration note for gitignored prod YAML overrides.

## Deferred Ideas

- Arrow-backed unification of the hot-path cache — rejected (Q7 / FEATURES anti-features), recorded as a decision, not deferred work.
- Async batch write-through for append-heavy live writes — keep-only-measured; N+4/later.
- Reviewed-not-folded todo: single-pass-portfolio-valuation.md — a profile-gated perf build (a cache that doesn't yet exist), not a classification of an existing cache; stays deferred.
