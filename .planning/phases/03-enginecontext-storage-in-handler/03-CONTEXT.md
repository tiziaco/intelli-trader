# Phase 3: EngineContext + Storage-in-Handler - Context

**Gathered:** 2026-07-09
**Status:** Ready for planning

<domain>
## Phase Boundary

A **purely mechanical rename** delivering the single remaining requirement **CTX-04**:

- Rename the class `SqlBackend` → `SqlEngine`.
- Move its module `itrader/storage/backend.py` → `itrader/storage/engine.py`.
- Tighten `EngineContext.sql_engine` from `Optional[Any]` to the concrete `Optional[SqlEngine]` type.
- Update all ~118 importers/references across ~34 files.

**End-state gates (already locked by ROADMAP success criteria — not up for discussion):**
- `mypy --strict` clean.
- Backtest oracle stays byte-exact (per-PLAN gate; oracle 134 / `46189.87730727451`).
- Factory SQL imports stay lazy so `tests/integration/test_okx_inertness.py` stays green on the backtest path.

**Explicitly NOT in this phase (Phase 2 D-03 pulled these forward into P2 — downstream must NOT re-open or "fix back"):**
- CTX-01 `compose_engine(ctx, spec)` signature — delivered in P2.
- CTX-02 handler-owned storage — delivered in P2.
- CTX-03 byte-exact / inertness gate wiring — delivered in P2.
- The `EngineContext` **shape** (exactly 4 fields `bus / config / environment / sql_engine`, in order). P3 only TIGHTENS the `sql_engine` type — it NEVER widens a type and NEVER adds/removes a field.

</domain>

<decisions>
## Implementation Decisions

### Rename sweep breadth
- **D-01 (Full consistency sweep):** The rename is NOT limited to the class + module. Every handler/factory parameter and field that carries a `SqlBackend` instance is also renamed for uniform vocabulary end-to-end:
  - `backend=` params → `sql_engine=` (e.g. `order_handler/storage/storage_factory.py`, `portfolio_handler/storage/storage_factory.py`, `PortfolioHandler.__init__`).
  - `_backend` fields → `_sql_engine` (e.g. `PortfolioHandler._backend` → `_sql_engine`, and its call sites).
  - Rationale: CTX-04 literally reads "field/param `sql_engine`"; leaving a `backend`-named param holding a `SqlEngine` would be a lingering naming mismatch. Larger diff (touches most of the ~118 refs) is accepted in exchange for a clean, self-consistent end-state.
  - Callers of these params (`compose.py` passes `ctx.sql_engine`) update their keyword argument names accordingly.

### Back-compat handling
- **D-02 (Hard rename, no alias):** Delete the `SqlBackend` name entirely. Do NOT leave a `SqlBackend = SqlEngine` deprecation alias.
  - Rationale: internal-only refactor with no external consumers; `mypy --strict` (the phase gate) flags every missed importer, so no stale reference can silently survive. Cleanest end-state, no dead vocabulary.

### Claude's Discretion
- Ordering of the rename (module move first vs. importer updates first), exact commit/plan granularity, and whether to use a scripted find-replace vs. per-file edits — planner/executor's call, subject to the byte-exact oracle and `mypy --strict` gates.
- Docstring/comment refresh in `storage/engine.py` (module docstring currently says "The shared SQL spine — `SqlBackend`") and any cosmetic mentions of the old name in comments — update to match, no separate decision needed.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase framing & locked scope
- `.planning/ROADMAP.md` § "Phase 3: EngineContext + Storage-in-Handler" — the goal, the two success criteria, and the "review at close whether this folds into P2 or P4" note.
- `.planning/REQUIREMENTS.md` § "EngineContext + Storage-in-Handler (CTX-01/02/03 → P2, CTX-04 → P3)" — the CTX-04 line and the Phase 2 D-03 reassignment note (lines ~78-98). **This is the authoritative statement that CTX-01/02/03 are NOT P3 work.**
- `.planning/phases/02-event-bus/02-CONTEXT.md` — Phase 2 D-03 rationale for pulling CTX-01/02/03 forward; the reason P3 is single-requirement.

### Code that defines the frozen contract this rename must respect
- `itrader/trading_system/engine_context.py` — the frozen `EngineContext` (4-field invariant, "P3 only tightens `sql_engine`" note). The `sql_engine: Optional[Any]` field tightened here.
- `itrader/storage/backend.py` — the `SqlBackend` class being renamed/moved to `storage/engine.py` (note the `NAMING_CONVENTION` constant and env.py import dependency — keep it intact).
- `itrader/trading_system/compose.py` — passes `ctx.sql_engine` into handler-owned storage; its keyword args update under D-01.

### Gate references
- `tests/integration/test_okx_inertness.py` — the lazy-SQL-import / backtest-inertness gate that must stay green.
- `tests/unit/storage/test_sql_backend.py` — existing test of the renamed class (uses both `SqlBackend` and a `sql_backend` reference); update under D-01/D-02.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `mypy --strict` (`pyproject.toml [tool.mypy]`, `files = ["itrader"]`) is the primary correctness net for this rename — it will enumerate every missed importer. Run it as the sweep-completeness check, not just the phase gate.

### Established Patterns
- **Rename footprint (verified):** ~118 `SqlBackend` references across ~34 files (`itrader/` + `tests/`). Importers span every storage concern: `price_handler/store/sql_store.py`, `order_handler/storage/`, `portfolio_handler/storage/` + `portfolio.py` + `portfolio_handler.py`, `strategy_handler/storage/`, `results/`, `storage/halt_record_store.py`, `storage/__init__.py`, `storage/migrations/env.py`, and both trading-system composition roots.
- `storage/__init__.py` re-exports the spine — update the barrel export name (`SqlBackend` → `SqlEngine`) so all `from itrader.storage import ...` importers follow.
- **Indentation hazard:** `trading_system/` (incl. `engine_context.py`, `compose.py`, `live_trading_system.py`) is 4-space; `storage/` and handler modules vary. Match each file's existing indentation — do NOT normalize. (`live_trading_system.py` is 100% 4-space despite the "handlers use tabs" rule.)

### Integration Points
- `storage/migrations/env.py` imports the spine's `NAMING_CONVENTION` / MetaData — the module move must keep that import path working (it becomes `from itrader.storage.engine import ...`).
- `EngineContext.sql_engine` is `None` on the backtest path (GATE-01 inertness). Tightening its type to `Optional[SqlEngine]` must NOT introduce an eager import of the SQL engine on the backtest path — use `TYPE_CHECKING` / string annotation if a real import would break lazy-loading inertness.

</code_context>

<specifics>
## Specific Ideas

Both micro-decisions favor the clean, decisive end-state: full vocabulary sweep + hard rename. No half-measures, no compatibility shims. The oracle and `mypy --strict` gates are the safety net that makes an aggressive rename safe.

</specifics>

<deferred>
## Deferred Ideas

- **Whether Phase 3 folds into P2 or P4** — the ROADMAP explicitly flags this for review *at phase close*, not now. It is a roadmap-structure question, out of scope for implementation discussion. Noted so it isn't lost.

None else — discussion stayed strictly within phase scope.

</deferred>

---

*Phase: 3-EngineContext + Storage-in-Handler*
*Context gathered: 2026-07-09*
