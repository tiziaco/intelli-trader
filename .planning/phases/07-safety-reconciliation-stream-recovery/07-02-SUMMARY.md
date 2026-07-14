---
phase: 07-safety-reconciliation-stream-recovery
plan: 02
subsystem: infra
tags: [reconciliation, live-trading, safety, exceptions, msgspec, decimal, halt, inertness]

# Dependency graph
requires:
  - phase: 07-01
    provides: "HaltReason.BASELINE_RESIDUAL vocabulary + the reconcile/ package siblings (venue_reconciler.py, drift.py)"
provides:
  - "ReconciliationError(ITraderError) typed exception — fail-loud CF-7 guard vocabulary for the venue re-link path"
  - "ReconciliationCoordinator — startup rehydrate -> venue-reconcile (venue-truth only) -> baseline-guard owner, keyed on account kind"
  - "Account.is_venue_truth kind discriminator (False on the ABC, True on VenueAccount) — replaces the exchange=='okx' proxy"
affects: [07-06]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Typed fail-loud guard (ReconciliationError) at the venue-payload trust boundary — no silent KeyError, message scrubbed to the leg id (V7)"
    - "Constructor-injected orchestration collaborator (no facade back-reference; halt as Callable[[str], None]) with lazy connector imports (inertness-safe)"
    - "Account KIND discriminator (is_venue_truth) as the venue-vs-compute gate, superseding exchange-string proxies"

key-files:
  created:
    - itrader/portfolio_handler/reconcile/reconciliation_coordinator.py
    - tests/unit/portfolio/test_reconciliation_coordinator.py
  modified:
    - itrader/core/exceptions/portfolio.py
    - itrader/core/exceptions/__init__.py
    - itrader/portfolio_handler/reconcile/venue_reconciler.py
    - itrader/portfolio_handler/account/base.py
    - itrader/portfolio_handler/account/venue.py

key-decisions:
  - "CF-7 guard message references child.id (the real Order attribute); the plan/research literal child.internal_id does not exist on Order — using it would raise AttributeError before the ReconciliationError"
  - "Account kind discriminator implemented via the plan's preferred A4 route: an is_venue_truth property on the Account ABC (False) overridden True on VenueAccount, rather than an isinstance check"
  - "venue_account typed VenueAccount | None so mypy --strict narrows to the venue-truth methods after the None/kind guard; the runtime is_venue_truth check is the KIND gate that replaces exchange=='okx'"

patterns-established:
  - "Startup reconcile owned by a single injected coordinator; the facade retains its inline block until Plan 06 swaps it in"
  - "Venue trust-boundary payloads fail loud with a typed, secret-scrubbed error"

requirements-completed: [SAFE-05]

coverage:
  - id: D1
    description: "ReconciliationError(ITraderError) typed exception + CF-7 fail-loud guard replacing the bare str(matched['id']) coercion at venue_reconciler.py; message references only the leg id (V7 scrub)"
    requirement: "SAFE-05"
    verification:
      - kind: unit
        ref: "tests/unit/portfolio/test_reconciliation_coordinator.py#test_cf7_relink_bracket_raises_on_missing_id"
        status: pass
      - kind: unit
        ref: "tests/unit/portfolio/test_reconciliation_coordinator.py#test_cf7_reconciliation_error_is_itrader_error"
        status: pass
    human_judgment: false
  - id: D2
    description: "ReconciliationCoordinator owns rehydrate -> venue-reconcile (venue-truth accounts only, keyed on Account.is_venue_truth, not exchange=='okx') -> baseline-guard; halts via injected callable with fixed literal HaltReason.BASELINE_RESIDUAL.value"
    requirement: "SAFE-05"
    verification:
      - kind: unit
        ref: "tests/unit/portfolio/test_reconciliation_coordinator.py#test_coordinator_compute_account_skips_venue_reconcile"
        status: pass
      - kind: unit
        ref: "tests/unit/portfolio/test_reconciliation_coordinator.py#test_coordinator_baseline_residual_halts_with_fixed_literal"
        status: pass
    human_judgment: false
  - id: D3
    description: "Both phase gates stay green — backtest oracle byte-exact (134 / 46189.87730727451) and OKX import inertness (coordinator keeps connector/SQL imports lazy)"
    verification:
      - kind: integration
        ref: "tests/integration/test_backtest_oracle.py"
        status: pass
      - kind: integration
        ref: "tests/integration/test_okx_inertness.py"
        status: pass
    human_judgment: false

# Metrics
duration: 15 min
completed: 2026-07-14
status: complete
---

# Phase 7 Plan 02: ReconciliationCoordinator + CF-7 Typed Guard Summary

**A first-class `ReconciliationCoordinator` that owns the live startup rehydrate → venue-reconcile → baseline-guard sequence keyed on account KIND (`Account.is_venue_truth`, not `exchange=='okx'`), plus a typed fail-loud `ReconciliationError` that closes the CF-7 KeyError-on-missing-id gap at the venue re-link boundary — both backtest-dark and inertness-safe.**

## Performance

- **Duration:** ~15 min
- **Started:** 2026-07-14T14:20Z
- **Completed:** 2026-07-14T14:35Z
- **Tasks:** 2
- **Files modified:** 7 (2 created, 5 modified)

## Accomplishments
- `ReconciliationError(ITraderError)` added to `core/exceptions/portfolio.py` (4-space, matching the file's actual indentation) and barrel-exported; the bare `venue_id = str(matched["id"])` at the CF-7 site is now a `matched.get("id")` guard that raises `ReconciliationError` on a missing/uncoercible id — the message references only `child.id`, never the full venue payload (ASVS V7 / T-07-09).
- New `ReconciliationCoordinator` (`portfolio_handler/reconcile/`) owns the startup sequence: (1) durable-ledger rehydrate (RESTORE, D-23, any kind); (2) venue reconcile for venue-truth accounts ONLY — snapshot + start_streaming + link-to-portfolios + `VenueReconciler.reconcile()`; (3) baseline guard that HALTs via the injected `halt` callable on an unexplained base-asset residual with the FIXED literal `HaltReason.BASELINE_RESIDUAL.value` (never `str(exc)` — V7).
- The venue-vs-compute gate is now the account KIND discriminator `Account.is_venue_truth` (False on the ABC, True on `VenueAccount`) — replacing the old `hasattr(order_storage,'rehydrate')`/`exchange=='okx'` proxy. `grep -c "== 'okx'"` on the coordinator returns 0.
- All connector/OKX imports stay lazy inside the method body; both phase gates green — backtest oracle byte-exact (`134 / 46189.87730727451`), OKX import inertness green — plus `mypy --strict` clean on all touched source files and 371 portfolio unit tests passing.

## Task Commits

Each task was committed atomically:

1. **Task 1: CF-7 typed fail-loud guard — ReconciliationError + venue_reconciler.py** - `1eca24f7` (feat)
2. **Task 2: ReconciliationCoordinator — startup sequence keyed on account kind** - `adc14928` (feat)

## Files Created/Modified
- `itrader/portfolio_handler/reconcile/reconciliation_coordinator.py` - NEW: the startup-reconcile owner (rehydrate → venue-reconcile → baseline-guard), kind-keyed, injected halt, lazy imports
- `tests/unit/portfolio/test_reconciliation_coordinator.py` - NEW: CF-7 guard tests + coordinator kind-keying/residual-halt tests
- `itrader/core/exceptions/portfolio.py` - added `ReconciliationError(ITraderError)`
- `itrader/core/exceptions/__init__.py` - barrel-export `ReconciliationError`
- `itrader/portfolio_handler/reconcile/venue_reconciler.py` - CF-7 guard replacing the bare `str(matched["id"])`; import `ReconciliationError`
- `itrader/portfolio_handler/account/base.py` - added `is_venue_truth` property (default False) — the kind discriminator
- `itrader/portfolio_handler/account/venue.py` - override `is_venue_truth` → True

## Decisions Made
- **CF-7 message uses `child.id`, not `child.internal_id`.** `Order` has no `internal_id` attribute anywhere in the codebase (verified by grep); the plan/research literal `child.internal_id` would raise `AttributeError` during the f-string build, masking the `ReconciliationError`. Used the real `child.id` — this satisfies the V7 intent (message references only the leg id, never the full `matched` dict).
- **Kind discriminator via the ABC-property route (A4 preferred).** Added `is_venue_truth` to the `Account` ABC (False) and overrode it True on `VenueAccount`, rather than an `isinstance(VenueAccount)` check — the plan explicitly endorsed this route and it keeps the coordinator decoupled from the concrete leaf while staying cleanly unit-testable with duck-typed fakes.
- **`venue_account` typed `VenueAccount | None`** so `mypy --strict` narrows to the venue-truth methods (`snapshot`/`start_streaming`/`positions`) after the None/kind guard, matching the facade's actual `self._venue_account` type. The runtime `is_venue_truth` check remains the KIND gate replacing `exchange=='okx'`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] CF-7 message references `child.id`, not the non-existent `child.internal_id`**
- **Found during:** Task 1 (CF-7 guard)
- **Issue:** The plan's `<action>` and 07-RESEARCH's CF-7 code example specify `f"... leg {child.internal_id} ..."`, and the prohibition acceptance criterion greps for `child.internal_id`. `Order` has no `internal_id` attribute (verified: `grep -rn internal_id itrader/` returns nothing) — it exposes `id`. Referencing `child.internal_id` would raise `AttributeError` before the `ReconciliationError` is constructed, defeating the fail-loud guard.
- **Fix:** Used `child.id` (the real `OrderId` attribute) in the guard message. The V7 intent is preserved — the message references only the leg id, never the full `matched` dict.
- **Files modified:** `itrader/portfolio_handler/reconcile/venue_reconciler.py`
- **Verification:** `test_cf7_relink_bracket_raises_on_missing_id` asserts `ReconciliationError` is raised and `str(child.id)` is in the message while `amount`/`price` are not.
- **Committed in:** `1eca24f7` (Task 1 commit)

**2. [Rule 3 - Blocking] `core/exceptions/portfolio.py` is 4-space, not TAB-indented as the plan claimed**
- **Found during:** Task 1 (ReconciliationError)
- **Issue:** The plan's `<read_first>` states the file "is TAB-indented" and acceptance criterion 5 requires `grep -nP '^\t' ... returns tab-led lines`. The file is actually 4-SPACE indented (`grep -cP '^\t'` returns 0; `grep -cP '^    '` returns 73). CLAUDE.md mandates matching the file's actual indentation and never normalizing; adding tab-indented code would break the file's consistency.
- **Fix:** Authored `ReconciliationError` with 4-space indentation matching the file. Acceptance criterion 5 (tab-led lines) is unsatisfiable given the file's real indentation and was based on a factual error.
- **Files modified:** `itrader/core/exceptions/portfolio.py`
- **Verification:** `mypy --strict` clean; CF-7 tests green; file indentation stays uniform 4-space.
- **Committed in:** `1eca24f7` (Task 1 commit)

**3. [Rule 2 - Missing Critical] Added `is_venue_truth` to `account/base.py` + `account/venue.py` (not in files_modified)**
- **Found during:** Task 2 (coordinator kind discriminator)
- **Issue:** The plan's `files_modified` frontmatter did not list the account files, but the coordinator's kind gate needs a discriminator. The plan's `<action>` explicitly authorized the A4 route ("prefer a property on the Account ABC returning False, overridden True on VenueAccount"), which requires editing those two files.
- **Fix:** Added the `is_venue_truth` property (False on the ABC, True on `VenueAccount`). Returns a constant with no money math — the backtest oracle stays byte-exact and no new imports touch the inertness path.
- **Files modified:** `itrader/portfolio_handler/account/base.py`, `itrader/portfolio_handler/account/venue.py`
- **Verification:** Oracle byte-exact `134 / 46189.87730727451`; inertness green; `mypy --strict` clean; coordinator kind-keying tests green.
- **Committed in:** `adc14928` (Task 2 commit)

**4. [Rule 2 - Missing Critical] Barrel-exported `ReconciliationError` from `core/exceptions/__init__.py`**
- **Found during:** Task 1 (ReconciliationError)
- **Issue:** The plan named `core/exceptions/portfolio.py` but not the barrel; the venue_reconciler and tests import via `from itrader.core.exceptions import ReconciliationError`, mirroring how sibling errors are consumed.
- **Fix:** Added `ReconciliationError` to the barrel import list and `__all__`.
- **Files modified:** `itrader/core/exceptions/__init__.py`
- **Verification:** `from itrader.core.exceptions import ReconciliationError` succeeds; tests green.
- **Committed in:** `1eca24f7` (Task 1 commit)

---

**Total deviations:** 4 auto-fixed (1 bug, 1 blocking, 2 missing-critical)
**Impact on plan:** Deviations 1-2 correct factual errors in the plan/research (a non-existent `Order.internal_id` and a wrong indentation claim) — following them literally would have produced broken code. Deviations 3-4 are sanctioned by the plan's own action text (A4 ABC-property route) and mirror established barrel conventions. No behavioral or security change beyond what the plan specified; the V7 scrub and kind-keying semantics are exactly as designed. No scope creep.

## Issues Encountered
None - both phase gates and `mypy --strict` were green on first full run after the mypy type-narrowing fix (typing `venue_account` as `VenueAccount | None`).

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- `ReconciliationCoordinator` + `ReconciliationError` + `Account.is_venue_truth` are in place and consumable:
  - Plan 06 wires the coordinator into `VenueLifecycle`/`build_live_system`, replacing the facade's inline `start()` reconcile block (1124-1165) and binding `halt` to `SafetyController.halt`.
- The facade still owns its inline reconcile block by design — Plan 06 swaps it in.
- No blockers. Backtest path remains byte-exact and import-inert.

## Self-Check: PASSED
- Created files verified on disk: `itrader/portfolio_handler/reconcile/reconciliation_coordinator.py`, `tests/unit/portfolio/test_reconciliation_coordinator.py` — both present.
- Commits verified: `1eca24f7` (Task 1), `adc14928` (Task 2) both in `git log`.
- Gates: oracle `134 / 46189.87730727451` green; `test_okx_inertness.py` green; `mypy --strict` clean on all touched source files; 371 portfolio unit tests pass.

---
*Phase: 07-safety-reconciliation-stream-recovery*
*Completed: 2026-07-14*
