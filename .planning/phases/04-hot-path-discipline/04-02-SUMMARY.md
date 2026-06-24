---
phase: 04-hot-path-discipline
plan: 02
subsystem: strategy_handler
tags: [perf, PERF-04, memoization, type-hints, byte-exact]
requires:
  - "itrader/strategy_handler/base.py::Strategy.to_dict / _apply_params (the two get_type_hints call sites)"
provides:
  - "itrader/strategy_handler/base.py::_declared_hints — module-level @cache memoized get_type_hints per concrete Strategy subclass (D-05)"
  - "tests/unit/strategy/test_type_hints_equivalence.py — equivalence + cache-identity + subclass-keying drift lock (D-07)"
  - "tests/unit/strategy/test_strategy.py::test_to_dict_snapshot_regression_full_surface — full to_dict snapshot lock (D-07)"
affects:
  - "any caller of Strategy.to_dict / _apply_params (no behavior change — byte-identical output, just memoized)"
tech-stack:
  added: []
  patterns:
    - "functools.cache memoization of a constant-per-class resolution keyed on type(self)"
key-files:
  created:
    - tests/unit/strategy/test_type_hints_equivalence.py
  modified:
    - itrader/strategy_handler/base.py
    - tests/unit/strategy/test_strategy.py
decisions:
  - "D-05: memoize get_type_hints per concrete strategy class via a module-level @functools.cache _declared_hints helper; route BOTH to_dict (hot, per-signal) and _apply_params (cold) through it; resolution memoized NOT removed (names-only MRO walk risks snapshot key-ordering in a byte-exact phase — deferred)"
  - "D-07: lock behavior-preservation with a dedicated equivalence test (_declared_hints == get_type_hints, same keys AND order) + cache-identity (is) + subclass-keying (no bleed), plus a full to_dict snapshot regression"
metrics:
  duration: ~12m
  completed: 2026-06-24
  tasks: 2
  files_changed: 3
  commits: 2
---

# Phase 4 Plan 02: Cache get_type_hints in to_dict (PERF-04) Summary

Memoized the per-signal `get_type_hints(type(self))` MRO walk in `Strategy.to_dict` (hot path,
hotspot #6 ~2% W1 / ~14% W2) behind a module-level `@functools.cache def _declared_hints(cls)`, routed
both `to_dict` (hot) and `_apply_params` (cold) through it, and locked byte-identical output with a
dedicated equivalence + cache-identity + subclass-keying drift test plus a full `to_dict` snapshot
regression — oracle byte-exact (134 / 46189.87730727451), `mypy --strict` clean, full suite green.

## What Was Built

**Task 1 — `_declared_hints` @cache helper + both call sites routed (D-05)** [`aeab4d8`]
- Added `from functools import cache` and a module-level `@cache def _declared_hints(cls: type["Strategy"]) -> dict[str, Any]:` returning `get_type_hints(cls)`, placed near the other module-level helpers (after `_json_safe`), TAB-indented to match the file.
- Swapped both call sites: `to_dict` (`for nm in _declared_hints(type(self)):`, the per-signal hot loop) and `_apply_params` (`hints = _declared_hints(type(self))`, cold). `type(self)` keys the cache on the concrete subclass so each class resolves exactly once.
- Resolution is **memoized, not removed** (D-05): neither site uses the resolved types (both only iterate keys; enum coercion is driven by `_COERCE`), but a names-only MRO walk would risk snapshot key-ordering in this byte-exact phase, so removal is deferred.
- Updated the three in-code comments that referenced `get_type_hints(type(self))` to cite `_declared_hints(type(self))` so the call-site grep is unambiguous.

**Task 2 — equivalence + snapshot drift locks (D-07)** [`03d1209`]
- New `tests/unit/strategy/test_type_hints_equivalence.py` (4-space, `pytestmark = pytest.mark.unit`): (1) equivalence — `_declared_hints(cls) == get_type_hints(cls)` with same keys AND `list(...)` order against the un-cached oracle; (2) cache-identity — two calls return the same object (`is`); (3) subclass keying — a second subclass with an extra annotation resolves to its own dict, no cross-class bleed.
- `tests/unit/strategy/test_strategy.py`: added `test_to_dict_snapshot_regression_full_surface` asserting the full declared-surface key set + order + values for the reference `SMAMACDStrategy` (declared knobs first in MRO-annotation order, then identity/runtime fields; `strategy_id` asserted as the stringified per-run UUIDv7), plus the `json.dumps` round-trip.

## Acceptance Criteria

- `grep -c "_declared_hints" base.py` = 6 (>= 3 required: definition + both call sites + comments).
- `grep -c "get_type_hints(type(self))" base.py` = 0 (both sites routed; comments updated).
- `git diff base.py` introduces no space-indented lines (clean TAB diff).
- `mypy itrader/strategy_handler/base.py` clean; `mypy itrader` clean (165 source files).
- Gate (a): `tests/integration/test_backtest_oracle.py` green (134 / 46189.87730727451), byte-exact across a double-run.
- `tests/unit/strategy/test_type_hints_equivalence.py` + `tests/unit/strategy/test_strategy.py` green (22 passed).
- Full suite: 1248 passed.

## Deviations from Plan

None — plan executed exactly as written. The only judgment call (Claude's Discretion per the plan) was helper placement (after `_json_safe`, before `_COERCE`) and updating three comment references to `get_type_hints(type(self))` so the `== 0` call-site grep criterion is satisfied cleanly.

## Notes

- This plan realizes the PERF-04 *correctness-preserving* win only; the gate (b) W1 re-freeze is Plan 03's responsibility (per the plan's success criteria).
- `functools.cache` is thread-safe (locks internally) for live mode; no manual invalidation is needed (annotations are fixed at import; the strategy-class count is bounded). The shared cached dict is read-only-safe — both sites only iterate keys, never mutate/`.pop` (T-04-04 accepted).

## Self-Check: PASSED

- Files verified present: `itrader/strategy_handler/base.py`, `tests/unit/strategy/test_type_hints_equivalence.py`, `.planning/phases/04-hot-path-discipline/04-02-SUMMARY.md`.
- Commits verified in git log: `aeab4d8` (Task 1), `03d1209` (Task 2).
