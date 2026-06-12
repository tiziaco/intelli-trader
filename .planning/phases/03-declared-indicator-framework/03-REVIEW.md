---
phase: 03-declared-indicator-framework
reviewed: 2026-06-12T00:00:00Z
depth: standard
iteration: 3
files_reviewed: 6
files_reviewed_list:
  - itrader/strategy_handler/base.py
  - itrader/strategy_handler/indicators/handle.py
  - itrader/strategy_handler/primitives.py
  - tests/unit/strategy/test_indicators.py
  - tests/unit/strategy/test_primitives.py
  - tests/unit/strategy/test_strategy.py
findings:
  critical: 0
  warning: 0
  info: 0
  total: 0
status: clean
---

# Phase 03: Code Review Report

**Reviewed:** 2026-06-12
**Depth:** standard
**Iteration:** 3 (final)
**Files Reviewed:** 6
**Status:** clean

## Summary

Iteration 3 (final) of a fix→re-review loop. Scope is the 6 files touched by the iter-2
fixes in commits `f6e15a9` (WR-04 made recursive — `_is_json_native` narrowed to leaves,
new `_json_safe` helper walking list/tuple/dict and repr-coercing non-native leaves, routed
through `to_dict`) and `33963b8` (3 regression tests). The mandate was to adversarially
confirm both fixes are correct, introduced no NEW defect, and that the `to_dict` recursion
has no remaining `json.dumps` gap — verified empirically on the nested and doubly-nested
cases.

**Result: clean.** Both fixes are sound and no new genuinely-actionable defect was found.
Verification was empirical, not by inspection alone:

- **`_json_safe` recursion (WR-01 iter-2) — no remaining `json.dumps` gap.** Drove the
  helper through `list[Decimal]`, `list[list[Decimal]]` (doubly-nested), `dict[str,datetime]`,
  `list[dict[str,Decimal]]`, `tuple[Decimal]`, `dict[str,tuple[datetime]]`, `set[Decimal]`
  (repr-coerced whole, since `set` is not a walked branch), `bytes`, tuple-keyed dicts, and
  the real `SMAMACDStrategy.to_dict()`. Every result survives `json.dumps`. The one
  pass-through leaf that is not strictly round-trippable, `float("nan")`, is accepted by
  `json.dumps` under its default `allow_nan=True`, so the documented contract holds.

- **WR-01 handle guard (`handle.py`) — correct.** A never-repopulated `IndicatorHandle`
  raises `RuntimeError("repopulate() must run before reading the handle")` on `__getitem__`
  unconditionally (not an `assert`, so it survives `-O`/PYTHONOPTIMIZE), and `__len__` stays
  `0`. Confirmed empirically.

- **bool/numpy-scalar hardening (`primitives.py::_at`) — correct.** `True`/`False`
  thresholds raise `TypeError` before the `numbers.Number` scalar check; `np.float64` /
  `np.int64` broadcast correctly through the scalar path. Confirmed empirically.

All 54 tests across the three test files pass under the strict warning filter; the
orchestrator's empirical gates (byte-exact oracle 134 trades / 46189.87730727451, 895
passed, mypy --strict clean) are not disturbed by anything in this review.

## Accepted / Informational (NOT actionable)

These were examined adversarially and confirmed to be non-defects or already adjudicated.
Listed for traceability only — none warrant a fix or another iteration.

- **`np.bool_` (np.True_) threshold — accepted (IN-01 residual).** `np.bool_` is neither a
  Python `bool` nor a `numbers.Number`, so `_at` takes the positional-index path and raises
  `IndexError: invalid index to scalar variable` loudly at the index edge. This matches the
  pre-fix behavior and the adjudicated IN-01 residual decision (raise loudly at the edge).

- **`_json_safe` dict-key `str(k)` collision — non-actionable, not a regression.** A dict
  whose keys stringify to the same value (e.g. `{1: 'a', '1': 'b'}`) collapses under
  `{str(k): ...}`. This is unreachable from any declared strategy class attribute (it would
  require an author literal mixing int-and-str colliding keys), is not introduced by the
  iter-2 fix (pre-fix `to_dict` did not walk dicts at all and `json.dumps` applies the same
  `str(k)` coercion), and does not affect the golden. Noted for completeness only.

- **`_json_safe` on a self-referential container — non-reachable.** A container that
  references itself would `RecursionError`. Not reachable from a declared strategy attribute;
  informational only.

- **IN-04 (min_timeframe divergence)** — already adjudicated, accepted.
- **IN-05 (deferred SHORT-block scaffolding)** — already adjudicated, accepted.

## Narrative Findings (AI reviewer)

No Critical, Warning, or Info findings. The iter-2 fixes are correct, complete, and
introduced no new defect. Convergence reached.

---

_Reviewed: 2026-06-12_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
