# Phase 2: Locked-Decision Conformance - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-11
**Phase:** 2-Locked-Decision Conformance
**Areas discussed:** Correlation-ID scheme (DEC-03), Money-API signature (DEC-01), DEC-02 regression proof / misdiagnosis

---

## Area selection

| Option | Description | Selected |
|--------|-------------|----------|
| Correlation-ID scheme | DEC-03: idgen UUIDv7 vs deterministic counter | ✓ |
| Money-API signature shape | DEC-01: strict Optional[Decimal] vs permissive union | ✓ |
| DEC-02 regression proof | behavior-sensitive test/evidence level | ✓ |

**User's choice:** all three.

---

## Correlation-ID scheme (DEC-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Deterministic counter | ph_{n:06d}, fully deterministic, readable | |
| idgen UUIDv7 | single-scheme conformance; oracle-dark nondeterminism | ✓ |

**User's choice:** idgen UUIDv7 — "I'm more for the UUID v7, especially for production purposes."
User asked whether UUIDv7 is bad for backtests.
**Notes:** Verified it is NOT bad — correlation_id is oracle-dark (only on error/log events,
never in golden CSVs); the determinism gate compares trades/equity, not correlation IDs; the run
path already accepts idgen UUIDv7 nondeterminism for all 10 entity-ID call sites; and it is the
more faithful reading of the locked "single UUIDv7 scheme" decision. `FINAL-ORACLE.md:111`
pre-documents this uuid4() as the lone hit to retire. Only test on it asserts uniqueness + prefix.

### Correlation-ID output shape (follow-up)

| Option | Description | Selected |
|--------|-------------|----------|
| Keep ph_ prefix + str | minimal blast radius | |
| Raw UUID string | no prefix | |
| CorrelationId NewType (uuid.UUID) | consistent with D-12 nine-alias pattern | ✓ |

**User's choice:** CorrelationId NewType. User asked "can't we use the uuid type instead of a raw
string?" — confirmed the codebase wraps all nine IDs in NewTypes over uuid.UUID (D-12), so a 10th
alias is the consistent choice. ph_ prefix dropped; dead `import uuid` removed.

---

## Money-API signature (DEC-01)

| Option | Description | Selected |
|--------|-------------|----------|
| Strict Optional[Decimal] | literal requirement; forbids float at boundary | ✓ |
| Permissive money union | Decimal\|float\|int\|str\|None; ergonomic, softens intent | |

**User's choice:** Strict Optional[Decimal].

### DEC-01 in-repo caller scope (follow-up)

| Option | Description | Selected |
|--------|-------------|----------|
| Update boundary callers | fix test/e2e float callers to Decimal | ✓ |
| Retype signatures only | leave callers; runtime coerces | |

**User's choice:** Update boundary callers (handler/manager API callers only; leave Order-entity
.modify_order callers — out of W4-01 scope).

---

## DEC-02 regression proof / misdiagnosis

| Option | Description | Selected |
|--------|-------------|----------|
| Regression test + evidence | Decimal fix + below-min test + bypass note | ✓ (initial) |
| Golden + existing suite only | rely on golden gate | |

**User's choice (initial):** Regression test + evidence.

**Mid-discussion discovery:** while grounding the evidence standard, verified the cited
"latent `Decimal < float` TypeError" does NOT exist — Python-3 comparison operators between
Decimal and float work (only arithmetic raises); no arithmetic on these fields; and the frozen
E2E leaf `release_refused` already drives the `> _max` comparison green. Reframed DEC-02 as a
float-for-money fix and re-asked:

### DEC-02 reframe (follow-up)

| Option | Description | Selected |
|--------|-------------|----------|
| Fix + correct wording + log delta | reframe + bounded gap-discovery delta | ✓ |
| Fix + correct wording, no delta | lighter bookkeeping | |
| Fix only, leave wording | leaves false rationale | |

**User's choice:** Fix + correct wording + log delta.

### DEC-02 test scope (follow-up)

| Option | Description | Selected |
|--------|-------------|----------|
| Add below-min unit test | covers the `< _min` branch no leaf hits | ✓ |
| Rely on release_refused only | symmetric to `> _max` | |

**User's choice:** Add below-minimum unit test.

---

## Claude's Discretion

- Plan/wave decomposition across the three independent fixes.
- Exact placement/naming of the new below-minimum unit test and the CorrelationId test edit.
- Exact wording/home of the gap-discovery delta and the corrected SC-2 wording.
- Touched-path import-cleanup extent beyond the dead `import uuid`.

## Deferred Ideas

None — discussion stayed within phase scope. The rejected alternatives (deterministic counter,
permissive money union, pre-building for the deferred LIFE-01 modify/cancel surface) were
considered and dismissed as out-of-intent, not deferred work.
