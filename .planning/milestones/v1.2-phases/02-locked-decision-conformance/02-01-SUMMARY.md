---
phase: 02-locked-decision-conformance
plan: 01
subsystem: order
tags: [decimal, money-boundary, type-annotations, mypy-strict, modify_order]

# Dependency graph
requires:
  - phase: 01-dead-code-doc-hygiene
    provides: clean order-handler facade/manager surface to retype
provides:
  - "modify_order public-API price/quantity params typed Optional[Decimal] at both the OrderHandler facade and the OrderManager layer (no float-for-money at a domain boundary)"
  - "in-repo modify_order test callers pass Decimal(\"...\") — the money boundary is float-free in practice (D-04), not only in annotation"
  - "defensive to_money() runtime coercion retained at the manager boundary (belt-and-suspenders)"
affects: [order-handler, money-policy, type-modeling, order-manager-decomposition]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Strict Optional[Decimal] money annotation at a public-API boundary (D-03) — NOT a permissive Decimal|float|int|str|None union; forces callers into the Decimal domain"
    - "Annotation hardens the boundary; the retained to_money() coercion stays as a defensive runtime guard"

key-files:
  created:
    - .planning/phases/02-locked-decision-conformance/deferred-items.md
  modified:
    - itrader/order_handler/order_handler.py
    - itrader/order_handler/order_manager.py
    - tests/unit/order/test_order_manager.py

key-decisions:
  - "D-03: modify_order money params are strictly Optional[Decimal] (not a permissive union) — the strongest no-float-for-money statement"
  - "D-04: convert in-repo float callers to Decimal(\"...\") so the boundary is float-free in practice"
  - "D-05: minimal change — annotations + docstrings + boundary callers only; no pre-build for deferred LIFE-01 modify/cancel work"
  - "Retain the defensive to_money() coercion at order_manager.py:1136-1138 (annotation forbids float, runtime stays defensive)"

patterns-established:
  - "Money-boundary annotation pattern: strict Optional[Decimal] at the public facade + manager, paired with a retained to_money() runtime guard"

requirements-completed: [DEC-01]

# Metrics
duration: 5min
completed: 2026-06-11
---

# Phase 02 Plan 01: Locked-Decision Conformance — DEC-01 (Optional[Decimal] money API) Summary

**Retyped `modify_order` price/quantity params from `Optional[float]` to strict `Optional[Decimal]` at both the OrderHandler facade and OrderManager layer, converted the in-repo float test callers to `Decimal("...")`, and proved it behavior-preserving — golden oracle byte-exact, 58/58 e2e, mypy --strict clean.**

## Performance

- **Duration:** ~5 min
- **Started:** 2026-06-11T09:11Z
- **Completed:** 2026-06-11T09:16Z
- **Tasks:** 3 (2 source/test + 1 pure verification)
- **Files modified:** 3 (+ 1 deferred-items log created)

## Accomplishments
- DEC-01 closed: no `Optional[float]` money params remain on `modify_order` at either layer — `new_price`/`new_quantity` are now `Optional[Decimal]` at the facade (`order_handler.py`) and the manager (`order_manager.py`).
- NumPy docstrings updated (`float` → `Decimal`) at both layers; the defensive `to_money()` boundary coercion retained exactly as-is.
- D-04: the three in-repo float callers (`new_price=28.0`, `new_quantity=2.0`) now pass `Decimal("28.0")` / `Decimal("2.0")` — the money boundary is float-free in practice.
- Behavior-preserving confirmed: golden integration oracle byte-exact (134 trades / `final_equity 46189.87730727451`, 12/12), e2e 58/58 green, `mypy --strict` clean across 161 source files.

## Task Commits

Each task was committed atomically:

1. **Task 1: Retype modify_order signatures + docstrings to Optional[Decimal] (facade + manager)** - `4123039` (refactor)
2. **Task 2: Convert in-repo float modify_order callers to Decimal (D-04)** - `67e6091` (test)
3. **Task 3: Golden + suite + mypy roll-up verification (Phase 2 SC-1/SC-4)** - pure verification, no source edits (no commit)

**Plan metadata:** committed with this SUMMARY + deferred-items.md.

## Files Created/Modified
- `itrader/order_handler/order_handler.py` - `modify_order` facade: `new_price`/`new_quantity` → `Optional[Decimal]`; docstring `float` → `Decimal`. `cancel_order` (no money params) untouched.
- `itrader/order_handler/order_manager.py` - `modify_order` manager: `new_price`/`new_quantity` → `Optional[Decimal]`; docstring `float` → `Decimal`; `to_money()` coercion at :1136-1138 retained.
- `tests/unit/order/test_order_manager.py` - three `harness.handler.modify_order(...)` callers converted from float to `Decimal("...")`.
- `.planning/phases/02-locked-decision-conformance/deferred-items.md` - logs the out-of-scope cross-agent failure (DEF-02-01, owned by plan 02-03).

## Decisions Made
None beyond the plan. Followed D-03 (strict `Optional[Decimal]`, not a union), D-04 (Decimal callers), and D-05 (minimal — annotations + docstrings + callers only) as specified. `Decimal` was already imported in all three files; no import additions needed.

## Deviations from Plan

None - plan executed exactly as written. All annotation/docstring/caller edits matched the planned interfaces; tab-indented handler files and the space-indented test file each preserved their existing indentation (no normalization).

## Issues Encountered

**Cross-agent full-suite failure (out of scope — NOT this plan's domain).** During Task 3 the full suite (`pytest -q`) reported 810 passed / **1 failed**: `tests/unit/portfolio/test_portfolio_handler.py::test_correlation_id_generation` (`AttributeError: 'UUID' object has no attribute 'startswith'`).

- **Root cause / owner:** commit `eacc0a0` "feat(02-03): mint correlation id from idgen…" — a **parallel Wave-1 agent (plan 02-03, DEC-03)** retyped `PortfolioHandler._generate_correlation_id()` from `f"ph_{uuid.uuid4().hex[:12]}"` to a `CorrelationId(UUID)` from idgen, but left the stale `id1.startswith("ph_")` assertion in this test.
- **Why not fixed here:** this is the **shared main checkout** for the wave (not an isolated worktree), so sibling agents' commits are visible on the branch. Per the SCOPE BOUNDARY rule, I only auto-fix issues DIRECTLY caused by this plan's changes. This plan (DEC-01) touched only `order_handler.py`, `order_manager.py`, and `tests/unit/order/test_order_manager.py` — nothing in the portfolio/ids/events surface. Fixing it would be scope creep into plan 02-03's domain.
- **Logged:** `deferred-items.md` → **DEF-02-01**. Expected to clear when plan 02-03's verification updates the assertion.
- **My plan's surface is green:** order domain `tests/unit/order` 145/145 passed; full suite is 810 passed with only the single 02-03 cross-agent failure (deselected → 810 passed, 1 deselected).

## Verification Evidence
- `grep` — no `Optional[float]`/`float, optional` money params or docstrings remain at either layer; `Optional[Decimal]` present at both; `to_money(new_price)` retained.
- `poetry run mypy itrader` → **Success: no issues found in 161 source files**.
- `poetry run pytest tests/integration -q` → **12 passed** (golden oracle byte-exact: 134 trades / `final_equity 46189.87730727451`).
- `poetry run pytest tests/e2e -m e2e -q` → **58 passed**.
- `poetry run pytest tests/unit/order -q` → **145 passed** (this plan's domain).
- `poetry run pytest -q --deselect …test_correlation_id_generation` → **810 passed, 1 deselected** (the single deselected failure is the unrelated cross-agent 02-03 item, DEF-02-01).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- DEC-01 fully closed; the `modify_order` money boundary is now strict `Optional[Decimal]` at both layers, float-free in annotation and in practice.
- No blockers introduced by this plan. The one observed cross-agent failure (DEF-02-01) is owned by sibling plan 02-03 and is expected to resolve when that plan's verification completes.

## Self-Check: PASSED

- `itrader/order_handler/order_handler.py` — modified, FOUND.
- `itrader/order_handler/order_manager.py` — modified, FOUND.
- `tests/unit/order/test_order_manager.py` — modified, FOUND.
- `.planning/phases/02-locked-decision-conformance/deferred-items.md` — created, FOUND.
- Commit `4123039` (Task 1) — FOUND in git log.
- Commit `67e6091` (Task 2) — FOUND in git log.

---
*Phase: 02-locked-decision-conformance*
*Completed: 2026-06-11*
