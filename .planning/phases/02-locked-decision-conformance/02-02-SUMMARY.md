---
phase: 02-locked-decision-conformance
plan: 02
subsystem: execution
tags: [decimal, money-policy, simulated-exchange, validate-order, dec-02, d-06, d-07, d-08]

# Dependency graph
requires:
  - phase: 01-locked-decision-conformance (Phase 1, Dead Code & Doc Hygiene)
    provides: clean tree + documented conventions (tab/space hazard, dual-layer validator)
provides:
  - "_min/_max_order_size carried as Decimal end-to-end in SimulatedExchange (float() wraps dropped at init + update_config)"
  - "validate_order size-limit comparisons run Decimal-vs-Decimal on the golden path (via _admit_order)"
  - "below-minimum REFUSED branch regression-cover (Decimal-vs-Decimal) + DEC-02 Decimal-carry assertion (D-08)"
  - "DEC-02 wording reframed (REQUIREMENTS.md): float-for-money consistency, not a TypeError fix (D-07 delta)"
affects: [DEC-01, DEC-03, Phase 3 hot-path perf (Decimal re-wrap audit), order-validator overlap]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Decimal end-to-end at the exchange size-limit boundary — float() only at the serialization edge (get_config_dict)"
    - "update_config(Decimal literals) to avoid the ExchangeLimits setattr-bypass (extra='forbid' + no validate_assignment) storing a float"

key-files:
  created: []
  modified:
    - itrader/execution_handler/exchanges/simulated.py
    - tests/e2e/conftest.py
    - tests/unit/execution/exchanges/test_simulated_exchange.py
    - .planning/REQUIREMENTS.md

key-decisions:
  - "D-07 gap-discovery delta confirmed: the W2-10/DEC-02/SC-2 'latent Decimal < float TypeError' was a MISDIAGNOSIS — Decimal-vs-float COMPARISON works in Py3, only arithmetic raises and there is none. Fix reframed as float-for-money consistency, not a crash fix."
  - "get_config_dict() float() wraps (simulated.py:624-625) left untouched — that is a serialization edge (CLAUDE.md permits float() only at serialization/logging edges) and is out of the plan's cited scope (init :99-100, update_config :605-606)."
  - "ROADMAP.md SC-2 reframe and STATE.md D-07 delta log deferred to the orchestrator (worktree directive forbids executor edits to ROADMAP.md/STATE.md). Exact wording captured below for the central update."

patterns-established:
  - "DEC-02 Decimal-carry regression lock: isinstance(exchange._min_order_size, Decimal) asserted in a unit test (would fail under the old float() wraps OR under float-literal update_config)."

requirements-completed: [DEC-02]

# Metrics
duration: ~6min
completed: 2026-06-11
---

# Phase 02 Plan 02: Decimal Order-Size Conformance Summary

**`SimulatedExchange._min/_max_order_size` carried as Decimal end-to-end (float() wraps dropped at init + update_config + the E2E seam), validate_order runs Decimal-vs-Decimal, a below-minimum REFUSED branch regression-cover added, and the DEC-02/D-07 "latent TypeError" misdiagnosis reframed to float-for-money consistency — golden byte-exact.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-06-11T09:11Z
- **Completed:** 2026-06-11T09:17Z
- **Tasks:** 4 (3 with commits; Task 4 is pure verification)
- **Files modified:** 4

## Accomplishments

- **DEC-02 / D-06 closed:** dropped the `float(...)` wraps on `_min_order_size`/`_max_order_size` at `simulated.py` init (:99-100) and `update_config` (:605-606) so both fields carry the Pydantic `ExchangeLimits` Decimal directly; the size-limit comparisons at :388,390 now run Decimal-vs-Decimal.
- **E2E seam mirrored:** `tests/e2e/conftest.py:331-332` re-derivation now drops `float()` to mirror production, and the `:323` comment block was corrected (the caches are Decimal, not floats).
- **D-08 below-minimum branch covered:** new `test_below_minimum_quantity_refused_decimal` drives `Decimal("0.0001") < Decimal("50")` → REFUSED (genuine Decimal-vs-Decimal), configures limits via `update_config(Decimal literals)` to avoid the setattr-bypass float-store, and asserts `isinstance(_min_order_size, Decimal)` as the DEC-02 regression lock.
- **D-07 delta handled:** the "latent `Decimal < float` `TypeError`" framing was confirmed a misdiagnosis and reframed in `REQUIREMENTS.md` DEC-02 to float-for-money consistency (no crash claim), `[W2-10]` tag retained.
- **Roll-up green:** golden oracle byte-exact (`pytest tests/integration` 12 passed — 134 trades / `final_equity 46189.87730727451`), `pytest tests/e2e -m e2e` 58/58 (including `release_refused`), `mypy --strict` clean (161 files), full suite 811 passed.

## Task Commits

Each task was committed atomically:

1. **Task 1: Drop float() wraps + mirror E2E seam** — `8ac7eac` (fix)
2. **Task 2: Below-minimum REFUSED branch test (D-08)** — `9103572` (test)
3. **Task 3: Reframe DEC-02 wording (REQUIREMENTS portion)** — `f793707` (docs)
4. **Task 4: Golden + suite + mypy roll-up** — pure verification, no commit

_Note: sibling parallel agent for plan 02-03 also committed onto this branch (`eacc0a0`, `57ad3df`) — those are not part of this plan._

## Files Created/Modified

- `itrader/execution_handler/exchanges/simulated.py` — `_min/_max_order_size` carried as Decimal at init + update_config (no `float()`); Decimal-vs-Decimal comparisons. (TAB-indented — matched.)
- `tests/e2e/conftest.py` — exchange seam re-derivation drops `float()`; `:323` comment corrected to say Decimal. (4-space — matched.)
- `tests/unit/execution/exchanges/test_simulated_exchange.py` — added `test_below_minimum_quantity_refused_decimal` (Decimal-vs-Decimal REFUSED + Decimal-carry lock). (4-space — matched.)
- `.planning/REQUIREMENTS.md` — DEC-02 reframed (float-for-money consistency, no TypeError claim; `[W2-10]` retained).

## Decisions Made

- **D-07 misdiagnosis confirmed & reframed.** The cited "latent `Decimal < float` `TypeError` on the below-minimum validation path" does not exist: Decimal-vs-float COMPARISON returns a bool in Py3 (only arithmetic raises, and there is none on these fields). The frozen `tests/e2e/cash/release_refused` leaf (a `> _max`, Decimal-vs-float REFUSED) is empirical proof. The fix is still required — `float(Decimal)` is float-for-money, violating the Decimal-end-to-end locked decision — but the rationale is now float-for-money consistency, not a crash fix.
- **`get_config_dict()` float() wraps (simulated.py:624-625) intentionally NOT touched.** That dict export is a serialization edge; CLAUDE.md money policy permits `float()` only at the serialization/logging edge. The plan scoped Task 1 to the cached-attribute init/update_config sites (:99-100, :605-606), not the serialization dict. The acceptance grep `float(self.config.limits.min_order_size)` therefore still matches those two serialization-edge lines — by design, not an incomplete edit.

## Deviations from Plan

### Orchestrator-directive override (ROADMAP.md / STATE.md)

The plan's Task 3 instructs editing `.planning/ROADMAP.md` (SC-2 reframe) and `.planning/STATE.md` (D-07 delta log + W2-10 blocker reconciliation). The spawn directive explicitly forbids executor edits to **ROADMAP.md and STATE.md** ("DO NOT touch those; the orchestrator owns them") and permits **REQUIREMENTS.md**. The directive takes precedence.

- **Action taken:** completed only the REQUIREMENTS.md DEC-02 reframe (committed `f793707`). ROADMAP.md was edited then reverted via `git checkout --` to honor the directive; STATE.md was never touched (its pre-existing working-tree changes were made by the orchestrator before spawn).
- **Deferred to orchestrator's central update** (exact wording below):

  **ROADMAP.md Phase 2 SC-2 (criterion 2) — replace the "latent Decimal < float TypeError … confirmed never to route through the broken comparison" wording with:**
  > `_min/_max_order_size` are carried as `Decimal` end-to-end (no float-for-money inconsistency at the exchange size-limit boundary); `validate_order` runs `Decimal`-vs-`Decimal` on the golden path (via `_admit_order` — it is NOT bypassed); the symmetric `< _min` below-minimum REFUSED branch is regression-covered (D-08); and the oracle is byte-exact. (D-07: the earlier comparison-crash framing was a misdiagnosis — Decimal-vs-float COMPARISON works in Py3, only arithmetic raises and there is none; the fix is float-for-money consistency, not a crash fix.)

  Also drop the "(latent-TypeError fix)" / "latent Decimal/float TypeError" phrasing from the ROADMAP Phase-2 checklist line and Goal line (replace with "float-for-money fix").

  **STATE.md — add a dated, owner-flagged entry under Accumulated Context > Decisions:**
  > [Phase 02 / 2026-06-11] D-07 gap-discovery delta (owner-flagged, bounded, NOT silently folded): the W2-10/DEC-02/SC-2 "latent `Decimal < float` TypeError" on the below-minimum validation path was a MISDIAGNOSIS — Decimal-vs-float COMPARISON works in Py3; only arithmetic raises and there is none on `_min/_max_order_size`. DEC-02 reframed as float-for-money consistency; SC-2 (ROADMAP) + DEC-02 (REQUIREMENTS) wording corrected. Evidence: the green `tests/e2e/cash/release_refused` leaf (Decimal-vs-float `> _max` REFUSED).

  **STATE.md — reconcile the W2-10 BEHAVIOR-SENSITIVE blocker line:** note it is re-adjudicated by D-07 — the below-minimum comparison was never broken; the golden run DOES route through `validate_order` (via `_admit_order`) and stays byte-exact (the change is float→Decimal of equal magnitude, so comparisons return the same bool).

**Total deviations:** 1 directive override (ROADMAP.md/STATE.md edits deferred to orchestrator; REQUIREMENTS.md portion completed). No source-behavior scope creep.
**Impact on plan:** DEC-02 source fix + test + REQUIREMENTS reframe fully delivered and verified. The two doc files the executor is forbidden to touch carry their exact reframe text here for the central post-wave update.

## Issues Encountered

- **Environment is the main checkout, not an isolated worktree** (`.git` is a directory; branch `v1.2/phase-2-type-conformance`). The per-commit worktree HEAD assertions (gated on `[ -f .git ]`) therefore did not fire; commits land on the shared feature branch alongside the sibling 02-03 agent. No `git clean`/`reset --hard`/`stash` used; all stages were file-scoped (`git add <path>`), never `git add .`.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- DEC-02 closed and verified; Phase 2 SC-2 (reframed per D-07) and SC-4 (golden/e2e/mypy) held.
- **Orchestrator action needed before phase close:** apply the deferred ROADMAP.md SC-2 reframe + STATE.md D-07 delta log/W2-10 reconciliation (exact wording in Deviations above).
- Phase 3 (Hot-Path Performance) `Decimal(str(Decimal))` re-wrap audit can rely on the size-limit boundary now being clean Decimal.

## Self-Check: PASSED

All modified/created files exist on disk; all task commits (`8ac7eac`, `9103572`, `f793707`) present in git history.

---
*Phase: 02-locked-decision-conformance*
*Completed: 2026-06-11*
