# Phase 3: EngineContext + Storage-in-Handler - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-09
**Phase:** 3-EngineContext + Storage-in-Handler
**Areas discussed:** Sweep breadth, Back-compat handling

---

## Sweep breadth

| Option | Description | Selected |
|--------|-------------|----------|
| Class + module + type only | Rename `SqlBackend`→`SqlEngine`, `backend.py`→`engine.py`, tighten `EngineContext.sql_engine` type; leave existing `backend=`/`_backend` param/field names as-is (smallest diff). | |
| Full consistency sweep | Additionally rename all handler/factory `backend=` params and `_backend` fields to `sql_engine`/`_sql_engine` for uniform vocabulary end-to-end. | ✓ |

**User's choice:** Full consistency sweep
**Notes:** CTX-04 literally reads "field/param `sql_engine`"; a `backend`-named param holding a `SqlEngine` would be a lingering naming mismatch. Larger diff (most of ~118 refs) accepted for a self-consistent end-state. Captured as CONTEXT D-01.

---

## Back-compat handling

| Option | Description | Selected |
|--------|-------------|----------|
| Hard rename, no alias | Delete the `SqlBackend` name entirely; rely on `mypy --strict` to flag every missed importer. | ✓ |
| Leave deprecation alias | Keep `SqlBackend = SqlEngine` so straggler imports still resolve. | |

**User's choice:** Hard rename, no alias
**Notes:** Internal-only refactor, no external consumers; `mypy --strict` is the phase gate so no stale reference can survive silently. Captured as CONTEXT D-02.

---

## Claude's Discretion

- Rename ordering (module move vs. importer updates first), commit/plan granularity, scripted find-replace vs. per-file edits — subject to byte-exact oracle + `mypy --strict` gates.
- Docstring/comment refresh in the moved `storage/engine.py` and any cosmetic old-name mentions.

## Deferred Ideas

- Whether Phase 3 folds into P2 or P4 — ROADMAP flags this for review *at phase close*, a roadmap-structure question out of scope for this discussion. Noted so it isn't lost.
