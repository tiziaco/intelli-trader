---
phase: quick-260722-hpz
plan: 01
subsystem: trading_system
tags: [live-trading, teardown, resource-leak, WR-08, code-review-fix]
status: complete
requires:
  - itrader/venues/lifecycle.py::VenueLifecycle.stop
  - itrader/connectors/provider.py::ConnectorProvider.close_all
provides:
  - "LiveTradingSystem.stop() fans out teardown across every _venue_lifecycles entry"
  - "per-lifecycle teardown isolation at the facade call site"
affects:
  - itrader/trading_system/live_trading_system.py
tech-stack:
  added: []
  patterns: [guard-at-call-site, snapshot-before-try, per-iteration-exception-isolation]
key-files:
  created:
    - tests/unit/trading_system/test_stop_tears_down_every_lifecycle.py
  modified:
    - itrader/trading_system/live_trading_system.py
decisions:
  - "Teardown guard lives at the facade call site, per iteration — NOT inside VenueLifecycle.stop()"
  - "Snapshot _venue_lifecycles into a list before the try, so the finally holds the full map on every return path and a mutating teardown cannot raise during iteration"
metrics:
  duration: ~12 min
  completed: 2026-07-22
---

# Quick Task 260722-hpz: Fix WR-08 — stop() tears down every venue lifecycle Summary

`LiveTradingSystem.stop()` now drives `VenueLifecycle.stop()` once per entry of
`_venue_lifecycles` with per-lifecycle exception isolation, closing the non-primary
authenticated-socket leak that the single-lifecycle shortcut left open.

## What Was Built

**Task 1 — RED regression gate** (`83c0c8ce`)
`tests/unit/trading_system/test_stop_tears_down_every_lifecycle.py`, four tests driving the
REAL `LiveTradingSystem.stop` body re-bound onto a minimal host (the in-repo pattern from
`test_live_runner_stats.py:35-46`). Lifecycles and the SQL backend are hand-written recorders,
so assertions name WHICH lifecycles were torn down rather than counting calls.

**Task 2 — the fix** (`59eb44e3`), two edits inside `stop()`, nothing else in the file:

1. `:897-898` — `lifecycles = getattr(...) or {}` + `lifecycle = next(iter(...), None)`
   became a single snapshot `lifecycles = list((getattr(self, '_venue_lifecycles', None) or {}).items())`,
   still BEFORE the `try` and still behind the defensive `getattr`.
2. The `finally`'s `if lifecycle is not None:` block became a `for account_id, lifecycle in lifecycles:`
   loop with the `try/except Exception` INSIDE it, logging the failing account by name.
   The stale `11-09` block comment that justified the shortcut was replaced with a `WR-08` comment
   recording the real branch analysis.

The `_system_db_backend` dispose block that follows was left completely untouched.

## RED Evidence (pre-fix, unmodified `live_trading_system.py`)

```
tests/unit/trading_system/test_stop_tears_down_every_lifecycle.py FFF.   [100%]

_____________________ test_stop_tears_down_every_lifecycle _____________________
>       assert calls == ['acct-a', 'acct-b', 'acct-c']
E       AssertionError: assert ['acct-a'] == ['acct-a', 'acct-b', 'acct-c']
E         Right contains 2 more items, first extra item: 'acct-b'

_____________ test_a_raising_lifecycle_does_not_strand_the_others ______________
>       assert calls == ['acct-a', 'acct-b', 'acct-c']
E       AssertionError: assert ['acct-a'] == ['acct-a', 'acct-b', 'acct-c']

___________ test_teardown_runs_and_does_not_mask_a_raising_stop_body ___________
>       assert calls == ['acct-a', 'acct-b', 'acct-c']
E       AssertionError: assert ['acct-a'] == ['acct-a', 'acct-b', 'acct-c']

========================= 3 failed, 1 passed in 1.08s ==========================
```

Exactly the gate's required 3-failed/1-passed split, and every failure message shows the
recorded call log containing only `acct-a` — the defect reproduced precisely. `git status --short -- itrader/`
was empty at that point, confirming the RED came from unmodified source.

The one pre-fix pass is `test_partially_constructed_facade_stop_does_not_raise`, labelled in its
own docstring as a preservation guard whose green is NOT evidence of the fix.

## Key Decision: guard placement

The `try/except Exception` sits at the **facade call site, inside the loop, per iteration** —
deliberately NOT pushed down into `VenueLifecycle.stop()`. Rationale:

- `VenueLifecycle.stop()` must stay honest and keep raising for its own single-lifecycle
  callers and its unit contract (`tests/unit/venues/test_lifecycle.py`, which drives it directly).
  Swallowing there would silently weaken that contract for every other caller.
- Isolation is a property of the *fan-out*, not of one venue's teardown. Only the call site
  knows there are siblings still to tear down and a SQL-spine `dispose()` still to run after them.
- Swallowing here is also what stops a teardown failure from masking an exception already
  propagating out of the `try` body (test 3).

The dropped `if lifecycle is not None:` guard is not a lost check — the loop is self-guarding on
an empty map, which is the preferred guard-clause/early-exit shape.

## Verification

| Gate | Result |
|------|--------|
| `pytest tests/unit/trading_system/test_stop_tears_down_every_lifecycle.py` | 4 passed |
| `+ tests/unit/venues/test_lifecycle.py + tests/unit/connectors/test_provider.py` | 16 passed |
| live wiring / multi-account / paper-lifecycle / multi-portfolio / okx-inertness | 48 passed |
| `tests/integration/test_backtest_oracle.py` | 3 passed — byte-exact (134 trades / 46189.87730727451) |
| `poetry run pytest tests` (full suite, the mandated gate) | **2823 passed, 6 skipped** (all 6 are OKX-credential-gated opt-ins) |
| `poetry run mypy` | Success: no issues found in 281 source files |
| `git diff -U0 -- itrader/trading_system/live_trading_system.py \| grep -cP '^\+\t'` | `0` — zero tabs added to the 4-space file |
| `git diff --stat` scope | 1 source file (+ the test committed separately); nothing from the Phase 11.1 lock list |

## Deviations from Plan

None — plan executed exactly as written. Every factual claim in `<interface_context>` was
re-verified against source before editing and all held:

- `live_trading_system.py` is 4-space throughout (0 tab-indented lines).
- `ConnectorProvider.close_all()` (`connectors/provider.py:82-91`) clears `self._memo` in a
  `finally`, so the extra calls in the shared-provider case are genuine no-ops — the load-bearing
  idempotency premise is confirmed.
- `VenueLifecycle.stop()` (`venues/lifecycle.py:146-149`) does have the
  `elif self._bundle.connector is not None: disconnect()` fallback covering only its own bundle,
  which is the branch that leaked.
- `stop()` uses `self.logger`, not the module-local `logger` idiom.
- The `test_live_runner_stats.py:35-46` host-rebinding precedent exists as described.

## Out-of-Scope Observations (noted, deliberately NOT fixed)

1. **`_streaming_lifecycles()` has no teardown counterpart.** `start()` reads
   `self._streaming_lifecycles()` at `:634` and `:772` to spawn venue-truth exchange streams,
   but `stop()` never walks that list — it relies entirely on the connector-level teardown to
   cancel spawned stream tasks. Whether that is sufficient in the non-shared-provider case is
   worth a look, but `_streaming_lifecycles` is explicitly on the Phase 11.1 scope-lock list.
2. **`VenueLifecycle.stop()` shared-provider branch is coarse.** When a provider IS shared,
   the first lifecycle's `close_all()` disconnects every account's connector, so the remaining
   iterations are no-ops. Correct today, but it means one lifecycle's `stop()` has cross-account
   side effects — relevant if Phase 11.1 ever needs to tear down a single account without
   stopping the whole run.

Neither was touched. No file on the scope-lock list (`_venue_lifecycles` keying/construction,
`_attach_venue_accounts`, `or DEFAULT_ACCOUNT_ID`, `ExecutionHandler.on_order`,
`_primary_lifecycle`, `_streaming_lifecycles`, the `start()` loop) was modified.

## Commits

- `83c0c8ce` — `test(quick-260722-hpz): add failing regression for WR-08 stop() fan-out`
- `59eb44e3` — `fix(quick-260722-hpz): tear down every venue lifecycle in stop() (WR-08)`

## Self-Check: PASSED

- `itrader/trading_system/live_trading_system.py` — FOUND (modified)
- `tests/unit/trading_system/test_stop_tears_down_every_lifecycle.py` — FOUND (created)
- Commit `83c0c8ce` — FOUND
- Commit `59eb44e3` — FOUND
