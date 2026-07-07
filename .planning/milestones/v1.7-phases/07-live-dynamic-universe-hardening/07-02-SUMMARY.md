---
phase: 07-live-dynamic-universe-hardening
plan: 02
subsystem: universe
tags: [universe, readiness, keep-until-flat, dataclass, WR-01, WR-02, live-trading]

# Dependency graph
requires:
  - phase: 07-01 (v1.7)
    provides: Readiness tri-state enum (PENDING/READY/FAILED) — the record's readiness field
  - phase: 06-dynamic-universe-membership (v1.7)
    provides: Universe.apply + UniverseDelta + leaving-set surface (the seam being refactored)
provides:
  - TrackedInstrument mutable record (instrument+readiness+leaving) — the single source of membership truth
  - Universe._entries record map replacing the desync-prone _instruments map + _leaving set (WR-01 bug class eliminated)
  - is_ready/mark_ready/mark_failed per-symbol readiness surface (WR-02 gate vocabulary)
  - apply keep-until-flat (D-13): removed records survive; add-branch clobber-guarded (D-14)
  - discard_instrument single atomic three-field teardown (D-13)
  - construction-time members default READY — the oracle-inertness lever
affects: [07-03, 07-04, 07-05, strategy-readiness-gate, admission-gate, detach-on-flat]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Single mutable record map (LEAN Security model) replacing parallel symbol-keyed structures (D-02)"
    - "Keep-until-flat: apply mutates membership only; teardown deferred to an explicit discard (D-13)"

key-files:
  created:
    - tests/unit/universe/test_universe_readiness.py
  modified:
    - itrader/universe/universe.py
    - tests/unit/universe/test_universe_apply.py

key-decisions:
  - "TrackedInstrument is @dataclass(slots=True), NOT frozen / NOT kw_only — readiness+leaving mutate; instrument held BY REFERENCE (D-02)"
  - "_entries built from members (map.get or default ladder), all READY — every member carries a record even when instrument_map is empty (admission-harness construction), fixing a would-be KeyError on mark_leaving"
  - "apply no longer pops removed symbols (D-13 keep-until-flat); the empty-delta oracle-dark fast path is unchanged"
  - "is_ready is defensive (.get -> False for absent); mark_ready/mark_failed/mark_leaving/clear_leaving index directly (fail-loud, no softening)"

patterns-established:
  - "Membership readiness + leaving are one record's fields, never parallel maps (WR-01 desync structurally impossible)"

requirements-completed: [WR-01, WR-02]

# Metrics
duration: 6min
completed: 2026-07-06
---

# Phase 7 Plan 02: Readiness-Aware Universe (TrackedInstrument record map) Summary

**`Universe` now holds ONE `_entries: dict[str, TrackedInstrument]` record map (instrument + readiness + leaving) replacing the desync-prone `_instruments` map + `_leaving` set — WR-01 keep-until-flat re-expressed on the new model (`apply` stops popping removed symbols, `discard_instrument` is the single atomic teardown), with construction-time members defaulting `READY` so the backtest oracle path is never gated.**

## Performance

- **Duration:** ~6 min
- **Started:** 2026-07-06T18:08:49Z
- **Completed:** 2026-07-06T18:14:41Z
- **Tasks:** 2
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments
- `TrackedInstrument` mutable `@dataclass(slots=True)` co-located in `universe.py` (added to `__all__`): the frozen `Instrument` held BY REFERENCE (D-02) plus mutable `readiness: Readiness = PENDING` and `leaving: bool = False`.
- `Universe.__init__` builds the single `_entries` record map from `members` (resolving each via `instrument_map` or the `_DEFAULT_*` paper ladder), every construction-time entry `READY` — the oracle-inertness lever (RESEARCH Pitfall 2). The old `_instruments` map and `_leaving` set are gone (`self._instruments`/`self._leaving` grep-zero).
- Readiness surface: `is_ready(sym)` (defensive `.get` → `False` for an absent symbol), `mark_ready`, `mark_failed` — the WR-02 per-symbol gate vocabulary.
- `apply` re-expressed for WR-01 keep-until-flat: the `for sym in removed: pop(...)` loop is DELETED (membership shrinks only, record survives); the add-branch is clobber-guarded (D-14) — a genuinely new symbol gets a fresh `PENDING` record, the re-add of a still-held (leaving) symbol only clears `leaving` and keeps its readiness (no re-warmup). The empty-delta oracle-dark fast path is untouched.
- `discard_instrument(sym)` = `self._entries.pop(sym, None)` — the ONLY pop, the single atomic three-field teardown (D-13).
- `mark_leaving`/`leaving_symbols`/`clear_leaving` (D-15) now operate through `_entries[sym].leaving`, orthogonal to readiness; `leaving_symbols()` is derived fresh from the records each call.
- New `test_universe_readiness.py` (8 tests) exercises the D-02/13/14/15 contract against the REAL `apply`→record path (closing the 06-REVIEW "hand-built event" gap).

## Task Commits

Each task was committed atomically:

1. **Task 1: RED readiness + keep-until-flat suite** - `7e251dc0` (test)
2. **Task 2: TrackedInstrument + _entries refactor + WR-01 lifecycle** - `eef4bcd7` (feat)

**Plan metadata:** _(final docs commit)_

## Files Created/Modified
- `itrader/universe/universe.py` (modified, 4-space) - `TrackedInstrument` record + `_entries` map + readiness/keep-until-flat lifecycle (191→296 lines)
- `tests/unit/universe/test_universe_readiness.py` (created, 4-space) - 8 readiness/keep-until-flat tests against the real apply→record path
- `tests/unit/universe/test_universe_apply.py` (modified, 4-space) - `test_apply_removes_symbol` updated to the keep-until-flat contract (record survives removal; gone only after `discard_instrument`)

## Decisions Made
- Followed the plan's D-02/13/14/15 design exactly. One refinement (below): `_entries` is built from `members` rather than strictly from `instrument_map`, so every construction-time member carries a record even when the caller passes an empty `instrument_map`.
- Indentation: 4 spaces throughout (the `universe` package and its tests are 4-space).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] `_entries` built from `members`, not strictly `instrument_map`**
- **Found during:** Task 2
- **Issue:** The plan text says build `_entries` "from `instrument_map`". But `tests/unit/order/test_leaving_symbol_admission.py` constructs `Universe(members=["BTCUSDT"], instrument_map={})` — a member with NO instrument entry — then calls `mark_leaving("BTCUSDT")`. Building strictly from `instrument_map` would leave that member without a record, so `mark_leaving` (now `_entries[sym].leaving = True`) would `KeyError`.
- **Fix:** Build `_entries` by iterating `members`, resolving each symbol's `Instrument` via `instrument_map.get(sym) or _default_instrument(sym)`, all `READY`. Every member is guaranteed a record (the D-02 single-source-of-truth spirit); non-members still `KeyError` on `instrument()` (`test_instrument_unknown_symbol_raises_keyerror` preserved). Production is unchanged: `backtest_runner`/`live_trading_system` assert `set(members) == set(instruments)` at wiring, so every member resolves to its real instrument and no default ladder is used — oracle byte-exact.
- **Files modified:** `itrader/universe/universe.py`
- **Commit:** `eef4bcd7`

**2. [Rule 1 - Bug] Updated `test_apply_removes_symbol` to the keep-until-flat contract**
- **Found during:** Task 2
- **Issue:** `test_universe_apply.py::test_apply_removes_symbol` asserted `pytest.raises(KeyError)` on `instrument("A")` after removal — the OLD drop-on-remove behavior, directly invalidated by the WR-01 keep-until-flat change (`apply` no longer pops).
- **Fix:** The test now asserts the removed record survives (`instrument("A").symbol == "A"`) and only `KeyError`s after an explicit `discard_instrument("A")`. Directly caused by this task's `apply` contract change (in-scope).
- **Files modified:** `tests/unit/universe/test_universe_apply.py`
- **Commit:** `eef4bcd7`

## Threat Surface

Threat register mitigations from the plan are all satisfied and asserted:
- **T-07-02-DESYNC** (Tampering): single `_entries` record; `discard_instrument` tears all three fields in one pop — no parallel map to drift.
- **T-07-02-STALE** (Info Disclosure): `apply` stops popping; the record survives until flat, so a still-held orphan never `KeyError`s (`test_apply_remove_keeps_record_only_members_shrinks`).
- **T-07-02-ORACLE** (DoS): construction-time members default `READY` (`test_construction_members_default_ready`); oracle byte-exact re-confirmed (134 / `46189.87730727451`).

No NEW security-relevant surface introduced (no endpoints, auth paths, file/schema access).

## Known Stubs
None — the readiness surface is real and wired to the record. The WR-02 strategy-gate CONSUMER (keying admission on `is_ready`) is a downstream plan (07-03+); this plan is the foundational state model only, which is the plan's declared scope.

## Issues Encountered
None.

## User Setup Required
None.

## Verification
- `poetry run pytest tests/unit/universe -q` → **62 passed** (readiness 8/8 GREEN).
- `poetry run mypy itrader/universe/universe.py` → clean.
- Universe consumers regression-clean: `test_leaving_symbol_admission.py`, `test_min_order_size_resolution.py`, `test_liquidation.py` → **19 passed**.
- Milestone gate: oracle byte-exact + determinism double-run (`tests/integration/test_backtest_oracle.py`) → **3 passed**.
- `self._instruments`/`self._leaving` grep-zero; `self._entries.pop` appears ONLY in `discard_instrument`; `class TrackedInstrument` present; file 296 lines (> 200 min).

## Self-Check: PASSED

- FOUND: itrader/universe/universe.py
- FOUND: tests/unit/universe/test_universe_readiness.py
- FOUND: .planning/phases/07-live-dynamic-universe-hardening/07-02-SUMMARY.md
- FOUND commit: 7e251dc0
- FOUND commit: eef4bcd7

---
*Phase: 07-live-dynamic-universe-hardening*
*Completed: 2026-07-06*
