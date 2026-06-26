---
phase: quick-260626-dnq
plan: 01
subsystem: core/money + strategy serialization
tags: [perf, hot-path, byte-exact, decimal, to_dict]
requires: [perf/results/scalene-w1.json]
provides:
  - "to_money Decimal fast-path (identity return for already-Decimal inputs)"
  - "Strategy.to_dict targeted isolating copy (no copy.deepcopy at serve site)"
affects:
  - itrader/core/money.py
  - itrader/strategy_handler/base.py
tech-stack:
  added: []
  patterns: ["type(x) is T identity fast-path", "recursive structural list/dict isolating copy"]
key-files:
  created: []
  modified:
    - itrader/core/money.py
    - itrader/strategy_handler/base.py
decisions:
  - "to_money fast-path uses type(x) is Decimal (identity, not isinstance) — conservative against Decimal subclasses"
  - "_isolating_copy recursive list/dict copy replaces copy.deepcopy at the to_dict serve site only; import copy retained (line 245 default-value copy still uses it)"
  - "snapshot local explicitly annotated dict[str, Any] to keep return strict-clean (no-any-return) since _isolating_copy returns Any"
metrics:
  duration: ~8 min
  completed: 2026-06-26
---

# Phase quick-260626-dnq: Byte-Exact Perf Hot-Path Fixes (to_money + to_dict) Summary

Two surgical, byte-exact W1 hot-path optimizations ranked by the latest Scalene profile: a `to_money()` Decimal identity fast-path (~2.7% CPU) and replacing `copy.deepcopy` in `Strategy.to_dict()` with a targeted recursive isolating copy (~5% CPU) — both proven output-identical under the SMA_MACD oracle.

## What Was Done

### Task 1 — `to_money` Decimal fast-path (`itrader/core/money.py`, 4-space indent)
Added a `if type(x) is Decimal: return x` guard as the first statement of `to_money`, before the existing `return Decimal(str(x))`. Identity check (`type(x) is Decimal`, not `isinstance`) is deliberate: only an exact-`Decimal` input is returned unchanged; any Decimal subclass falls through to the conservative string path. The D-04 docstring, `quantize`, `ONE`, scale tables, and `__all__` were untouched. Commit `932bf29`.

### Task 2 — targeted isolating copy in `to_dict` (`itrader/strategy_handler/base.py`, TAB indent)
- Verified the snapshot value domain first (STEP 1): every value is an immutable scalar (str/int/float/bool/None) or a flat list (`tickers`, `subscribed_portfolios`) — no custom mutable leaf objects (guaranteed by `_json_safe`).
- Added a module-level `_isolating_copy(val)` helper near `_json_safe`: recursive structural copy over `type(val) is list` / `type(val) is dict`, returning scalars unchanged. For this value domain it reproduces `deepcopy`'s per-call nested-container isolation at any depth, byte-identically, without the memo/introspection overhead.
- Replaced `snapshot = copy.deepcopy(self._to_dict_static_cache)` with `snapshot: dict[str, Any] = _isolating_copy(self._to_dict_static_cache)`.
- Updated the WR-01 comment block to describe the deepcopy→isolating-copy change; WR-02/D-06 comments preserved.
- `import copy` retained (line 245 default-value copy still uses it).
- Commit `be34f25`.

### Task 3 — combined byte-exact oracle + mypy gate (no new edits)
Ran the authoritative SMA_MACD oracle plus the to_dict snapshot pin and mypy --strict. All green (details below).

## Verification Gate Results

| Gate | Command | Result |
|------|---------|--------|
| Byte-exact oracle | `pytest tests/integration/test_backtest_oracle.py` | PASS (3/3 — 134 trades / 46189.87730727451 unchanged) |
| to_dict snapshot pin | `pytest tests/unit/strategy/test_to_dict_snapshot.py` | PASS (6/6, incl. nested-container isolation) |
| Money unit tests | `pytest tests/unit -k money` | PASS (23/23) |
| to_money round-trip | inline (`is` for Decimal; equal for str/int/float) | PASS |
| Nested-isolation probe | inline (mutate `d1['tickers']`, assert `d2` clean) | PASS |
| mypy (file scope) | `mypy itrader/core/money.py itrader/strategy_handler/base.py` | PASS (2 files) |
| mypy (full strict) | `mypy` | PASS (166 files) |
| Whitespace/indent | `git diff` leading-char scan | PASS (money.py spaces-only; base.py tabs-only) |

All pytest/mypy invocations ran with `PYTHONPATH="$PWD"` against the worktree source (confirmed `itrader.core.money.__file__` resolves to the worktree), using the main checkout's `.venv` because the worktree's fresh `.venv` had no deps installed.

## Deviations from Plan

**1. [Rule 3 - Blocking] mypy `no-any-return` on the new serve site**
- **Found during:** Task 3 (mypy gate).
- **Issue:** `_isolating_copy` is recursively heterogeneous and returns `Any`; the previous `copy.deepcopy` was typed via a TypeVar so `return snapshot` was `dict[str, Any]`. After the swap, `return snapshot` returned `Any` → `no-any-return` under strict.
- **Fix:** Pinned the concrete type at the assignment: `snapshot: dict[str, Any] = _isolating_copy(...)`. No behavior change.
- **Files modified:** `itrader/strategy_handler/base.py`
- **Commit:** `be34f25` (folded into Task 2)

**2. [Environment, not a code deviation] Test runner**
- The worktree's Poetry `.venv` was freshly created and empty (`make`/`poetry run pytest` failed with `ModuleNotFoundError: pydantic`). Used the main checkout's `.venv` binaries with `PYTHONPATH="$PWD"` set to the worktree — the documented `.venv`-shadowing mitigation — confirming worktree source was imported. No source change.

**3. [Doc accuracy] Snapshot test count**
- The plan referenced "all 7 tests" in `test_to_dict_snapshot.py`; the file actually contains 6 tests. All 6 pass. No action needed.

## Known Stubs

None.

## Self-Check: PASSED
- `itrader/core/money.py` — FOUND, modified, committed `932bf29`
- `itrader/strategy_handler/base.py` — FOUND, modified, committed `be34f25`
- Commit `932bf29` — FOUND in git log
- Commit `be34f25` — FOUND in git log
