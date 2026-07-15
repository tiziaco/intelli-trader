---
phase: 08-error-subsystem
fixed_at: 2026-07-15T00:00:00Z
review_path: .planning/phases/08-error-subsystem/08-REVIEW.md
iteration: 1
findings_in_scope: 4
fixed: 4
skipped: 0
status: all_fixed
---

# Phase 8: Code Review Fix Report

**Fixed at:** 2026-07-15
**Source review:** .planning/phases/08-error-subsystem/08-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 4
- Fixed: 4
- Skipped: 0

All four findings were low-severity robustness/observability notes — the reviewer
confirmed all seven load-bearing invariants are correct and found NO correctness,
security, or data-loss defects. Fixes applied are the reviewer's preferred low-risk
options (documentation tightening + two mechanical control-flow hoists). Per-file
indentation was preserved (`error_policy.py` = 4-space; `okx.py` = tabs).

## Fixed Issues

### WR-01: `breaker_snapshot()` cross-thread read without synchronization

**Files modified:** `itrader/events_handler/error_policy.py`
**Commit:** 45a21735
**Applied fix:** Documentation fix (reviewer's primary suggestion — "not a correctness
bug"). Tightened the `breaker_snapshot` docstring to state that the *writes* to
`self._hits` are single-threaded (engine thread via `should_trip`/`record_failure`) while
this *reader* runs on a different thread (`get_status`, a public status API), making it a
best-effort GIL-atomic cross-thread read that cannot crash/corrupt but may be momentarily
inconsistent. No lock was added to `ErrorPolicy` (per instruction — avoid non-trivial
locking; the accurate comment is the primary fix).

### IN-01: `_error_counter()` bumped before the WR-06 source-guard early-return

**Files modified:** `itrader/events_handler/error_policy.py`
**Commit:** e2f8f7d4
**Applied fix:** Moved the `if self._error_counter is not None: self._error_counter()`
call from above the `EventType.ERROR` source-guard to below it, so a swallowed
ERROR-route consumer failure is now a complete bookkeeping no-op (does not increment the
facade `errors_count` stat). Verified the guard still returns before both the republish
(`self._bus.put(...)`) and the tripwire count (`classify_failure`/`record_failure`). Added
an IN-01 note in the guard comment documenting the intent.

### IN-02: FILL_TRANSLATION ErrorEvent uses wall-clock `time` on catch-up/consume paths

**Files modified:** `itrader/execution_handler/exchanges/okx.py`
**Commit:** fba2da8c
**Applied fix:** Behavior unchanged (reviewer: "No change required"). Added a two-line
explanatory comment above each of the two FILL_TRANSLATION emits (catch-up path and
consume path) noting the error-record `time` is intentionally wall clock because the trade
did not translate, so no business time is recoverable.

### IN-03: `catch_up_missed_fills` leaves `_disconnect_ts_ms` set on empty-symbols early return

**Files modified:** `itrader/execution_handler/exchanges/okx.py`
**Commit:** cd70f82c
**Applied fix:** Hoisted the `symbols = sorted(self._active_symbols)` read and its
`if not symbols:` guard above the `since = self._disconnect_ts_ms` read, and set
`self._disconnect_ts_ms = None` inside the early-return branch. The floor clear is now
unconditional, so a symbols-empty resume cannot leave a stale non-`None` floor that would
suppress re-arming on the next disconnect (`_on_stream_down_with_floor` only arms when
`None`). This is pre-existing Phase-7 (D-12) code, in scope because `okx.py` is under review.

## Verification

- Syntax verified per fix (Tier 2: `ast.parse` on both edited Python files — passed).
- Full test suite for the phase (run via `poetry run pytest` with `PYTHONPATH="$PWD"` per
  the worktree `.venv` shadowing gotcha; NOT `make test`, which disables logs / aborts on
  missing `.env`):

  ```
  tests/unit/events/test_error_policy.py    23 passed
  tests/unit/events/test_error_handler.py   11 passed
  tests/unit/events/test_error_flow.py       7 passed
  tests/unit/execution/test_okx_exchange.py 25 passed
  ============================== 66 passed in 1.39s ==============================
  ```

---

_Fixed: 2026-07-15_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
