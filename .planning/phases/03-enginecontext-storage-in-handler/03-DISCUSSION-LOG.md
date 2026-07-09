# Phase 3: EngineContext + Storage-in-Handler - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-09
**Phase:** 3-EngineContext + Storage-in-Handler
**Areas discussed:** Sweep breadth, Back-compat handling, Redundant signal_store surfacing

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

## Redundant signal_store surfacing

User flagged `compose.py:252` (`signal_store=strategies_handler.signal_store`) as a suspected violation of the storage-in-handler decision, and asked to verify whether the field is actually used before deciding whether to clean it up in this phase.

**Investigation:** It is NOT a decision violation — line 252 is a read-*back* of the handler-owned store, not an injection (the handler constructs it in-module at `strategies_handler.py:87`). The capability is genuinely used (`test_backtest_oracle.py:284,288` call `get_signal_records()`/`get_signal_store()`). But the *surfacing* is redundant: `Engine.signal_store` + the `BacktestTradingSystem` `signal_store=` ctor param + `_signal_store` cache all duplicate what `engine.strategies_handler.signal_store` already provides, and every other component is exposed via a plain `@property` delegating to the engine. The facade's `signal_store=` override param is dead (only the factory passes it, passing the same object).

| Option | Description | Selected |
|--------|-------------|----------|
| Fold into Phase 3 as D-03 | Add the mechanical, behavior-preserving cleanup as a distinct rider decision; planner scopes it separate from the rename diff. | ✓ |
| Keep as deferred idea | Record in Deferred Ideas only; keep Phase 3 a pure single-requirement rename. | |

**User's choice:** Fold into Phase 3 as D-03
**Notes:** Mechanical, oracle byte-exact, mypy-clean — same character as the rename. Captured as CONTEXT D-03 with the exact remove/keep footprint. Handler ownership + its test-override seam explicitly preserved.

---

## Claude's Discretion

- Rename ordering (module move vs. importer updates first), commit/plan granularity, scripted find-replace vs. per-file edits — subject to byte-exact oracle + `mypy --strict` gates.
- Docstring/comment refresh in the moved `storage/engine.py` and any cosmetic old-name mentions.

## Deferred Ideas

- Whether Phase 3 folds into P2 or P4 — ROADMAP flags this for review *at phase close*, a roadmap-structure question out of scope for this discussion. Noted so it isn't lost.
