---
phase: 05-signal-contract-reconcile-fragile
plan: 03
subsystem: order_handler/reconcile
tags: [RECON-01, reconcile, on_fill, clarity-refactor, exception-safety]
requires:
  - "ReconcileManager.on_fill verbatim move (v1.2 Phase-6 enabling surface)"
provides:
  - "Extracted-method ReconcileManager.on_fill with byte-identical try/finally skeleton"
  - "RECON-01 branch-coverage safety net (body-raise-releases, unknown-status-holds, three terminal releases)"
affects:
  - "itrader/order_handler/reconcile/reconcile_manager.py"
  - "tests/unit/order/test_reconcile_manager.py"
tech-stack:
  added: []
  patterns:
    - "Extract-method for clarity WITHOUT control-flow rewrite (try/finally + gate points byte-identical)"
    - "Lightweight fakes for isolated exception-safety branch testing"
key-files:
  created:
    - "tests/unit/order/test_reconcile_manager.py"
  modified:
    - "itrader/order_handler/reconcile/reconcile_manager.py"
decisions:
  - "D-06: clarity-only extract — named _classify / per-status arms / _release_reservation around a byte-identical skeleton; state-machine rewrite explicitly REJECTED"
  - "_classify returns (terminal, transition) as a READABILITY aid only; it does NOT drive the mirror transition (the arms still call order.add_fill/cancel_order/reject_order)"
metrics:
  duration: "~12 min"
  completed: "2026-06-13"
  tasks: 2
  files: 2
---

# Phase 5 Plan 03: RECON-01 on_fill Clarity Cleanup Summary

Extracted `ReconcileManager.on_fill` into named helpers (`_classify`, the three per-status arms, `_release_reservation`) around a byte-identical `try`/`finally` exception-safety skeleton, with a Wave-0 branch-coverage safety net pinning the WR-04 body-raise-releases and unknown-status-holds-reservation invariants BEFORE the refactor.

## What Was Built

**Task 1 — Wave-0 safety net (`tests/unit/order/test_reconcile_manager.py`, 4-space, folder-derived `unit` marker):**
Six tests over lightweight fakes (fake storage, recording portfolio, fake order, fake fill) that isolate the `should_release` / `try` / `finally` control flow:
- `test_body_raise_still_releases_and_propagates_original_exception` — a terminal fill whose body raises AFTER the `should_release = True` arm point still releases in the `finally`; the ORIGINAL body exception propagates unmasked (WR-04 / T-05-09).
- `test_body_raise_then_release_failure_does_not_mask_original` — body-raise + release-failure: the original body exception still propagates, release failure only logged (WR-03).
- `test_unknown_status_holds_reservation_and_does_not_release` — unknown/non-terminal status early-returns and HOLDS the reservation (T-05-10).
- Three terminal-transition tests (EXECUTED/CANCELLED/REFUSED) each release exactly once.

Green against the CURRENT (pre-refactor) `reconcile_manager.py`.

**Task 2 — Extract-method (`itrader/order_handler/reconcile/reconcile_manager.py`, TABS):**
- `_classify(status) -> (terminal, transition)` — names the EXECUTED→FILLED / CANCELLED→CANCELLED / REFUSED→REJECTED mapping + terminal-ness. Readability aid only; does not drive the transition.
- `_apply_executed` / `_apply_cancelled` / `_apply_refused` — the three per-status arm bodies.
- `_release_reservation(order, should_release, body_raised)` — wraps the `finally` body CONTENTS (the inner release `try`/`except` + the `if not body_raised: raise` gate). The `finally` STATEMENT stays in `on_fill`.

The `try`/`finally` statements, the `should_release = True` arm point (armed AFTER terminal status, BEFORE further work), the `body_raised = True; raise` in the except, and the `if not body_raised: raise` inner re-raise gate are byte-identical. The unknown-status branch stays a non-terminal early-return inside `on_fill` (NOT pushed into `_classify`). `OrderManager.on_fill` remains a 1-line delegation.

## Verification Results

- `poetry run pytest tests/unit/order/test_reconcile_manager.py` — 6 passed (green pre- and post-refactor).
- `poetry run pytest tests/unit/order` — 163 passed (no regression).
- `poetry run mypy --strict itrader/order_handler/reconcile/reconcile_manager.py` — Success, no issues.
- `poetry run pytest tests/integration/test_backtest_oracle.py` — 3 passed; oracle byte-exact (134 / 46189.87730727451), deterministic across a double-run.
- `poetry run pytest tests/e2e -m e2e` — 58/58 passed.
- `git diff` of `reconcile_manager.py` — no space-indent additions (TAB-only); grep confirms 5 named helpers, `finally:` preserved, `if not body_raised` preserved.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test correctness] Body-raise injection point corrected to the post-arm window**
- **Found during:** Task 1 (first run of the safety-net tests failed).
- **Issue:** The initial `test_body_raise_still_releases_*` test injected the raise INSIDE `add_fill` — i.e. during the EXECUTED arm body, which runs BEFORE the `should_release = True` arm point (line 155). At that point `should_release` is still `False`, so the `finally` correctly does NOT release. The test therefore asserted a behavior the code does not (and must not) have, and failed against current code.
- **Fix:** Moved the raise injection to `storage.update_order`, which runs AFTER the `should_release = True` arm — exactly the window WR-04 protects (terminal status already set, body then raises → reservation MUST still release). Added an `update_raises` hook to `_FakeStorage` and removed the now-unused `add_fill_raises` hook.
- **Why this matters:** This is the precise WR-04 contract — release fires for a raise AFTER the terminal status is armed, not for a raise during the arm body itself (a raise inside `add_fill` aborts before any terminal status, so holding the reservation is correct). The corrected test pins the real invariant.
- **Files modified:** `tests/unit/order/test_reconcile_manager.py`
- **Commit:** b39f9c8

### Note: PATTERNS.md absent

The plan's `<read_first>` referenced `.planning/phases/05-signal-contract-reconcile-fragile/05-PATTERNS.md`, which does not exist in the phase directory. The extract boundaries and the state-machine anti-pattern warning were fully specified in the plan's `<action>`/`<objective>` and in 05-CONTEXT.md D-06, so no information was lost.

## Known Stubs

None.

## Threat Flags

None — no new security-relevant surface; the FillEvent → ReconcileManager → release internal reconcile path is unchanged in behavior (financial-integrity invariant preserved byte-for-byte).

## Self-Check: PASSED

- FOUND: tests/unit/order/test_reconcile_manager.py
- FOUND: itrader/order_handler/reconcile/reconcile_manager.py
- FOUND commit: b39f9c8 (test safety net)
- FOUND commit: 6e21c54 (refactor extract)
