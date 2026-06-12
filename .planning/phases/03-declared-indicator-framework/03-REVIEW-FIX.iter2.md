---
phase: 03-declared-indicator-framework
fixed_at: 2026-06-12T00:00:00Z
review_path: .planning/phases/03-declared-indicator-framework/03-REVIEW.md
iteration: 1
findings_in_scope: 9
fixed: 7
skipped: 2
status: partial
---

# Phase 03: Code Review Fix Report

**Fixed at:** 2026-06-12
**Source review:** .planning/phases/03-declared-indicator-framework/03-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 9 (fix_scope: all — Warnings + Info)
- Fixed: 7 (WR-01, WR-02, WR-03, WR-04, IN-01, IN-02, IN-03)
- Skipped (intentional / won't-fix): 2 (IN-04, IN-05)

**Gate results (full, after all fixes):**
- `poetry run pytest -q` → **891 passed** under `filterwarnings=["error"]` (baseline 890 + 1 new `json.dumps` regression test added for WR-04).
- `poetry run mypy itrader` → **Success: no issues found** (clean; re-run with cleared cache to confirm).
- Golden oracle `tests/integration/test_backtest_oracle.py` → **3 passed** after EVERY fix and at the end. Byte-exact golden (134 trades / final_equity 46189.87730727451) **preserved** — none of the 7 fixes moved it.

> Note: All work was performed in an isolated git worktree on branch `gsd-reviewfix/03-69726`, fast-forwarded onto `v1.3/phase-3-indicator-framework` on cleanup. Tests/mypy were run with `PYTHONPATH="$PWD"` to defeat the editable-install `.venv` shadowing (per worktree-venv-shadowing memory note).

## Fixed Issues

### WR-01: `IndicatorHandle.__getitem__` guards with `assert` — silently disabled under `-O`

**Files modified:** `itrader/strategy_handler/indicators/handle.py`
**Commit:** d8dd1ba
**Applied fix:** Replaced `assert self._values is not None, ...` with an explicit `if self._values is None: raise RuntimeError("repopulate() must run before reading the handle")`. The read-before-repopulate contract now holds at every optimization level (`-O`/`PYTHONOPTIMIZE` strips asserts). Tab-indented; matched the file.

### WR-02 / WR-03: `_at` scalar detection misses numpy scalars and silently accepts `bool`

**Files modified:** `itrader/strategy_handler/primitives.py`
**Commit:** 0dddd25
**Applied fix:** In `_at`, (WR-03) reject `bool` FIRST (`isinstance(x, bool)` → `TypeError`) so `crossover(hist, True)` fails loudly instead of coercing to `1.0`; (WR-02) then detect scalars via `numbers.Number` (covers `numpy.float64`/`numpy.int64`) instead of a native `int`/`float` whitelist. A pandas `Series` / list-backed `IndicatorHandle` is not a `numbers.Number`, so it correctly keeps the positional-index path; the reference literal `0` stays scalar. Added `import numbers` and `cast` (mypy --strict flagged `float(Number)`; resolved with `float(cast(Any, ...))` at the conversion edge). 22/22 `test_primitives.py` pass; golden unchanged.

### WR-04: `to_dict()` config snapshot can hold non-JSON-serializable introspected values

**Files modified:** `itrader/strategy_handler/base.py`, `tests/unit/strategy/test_strategy.py`
**Commit:** ee40bd9
**Applied fix:** Added a module-level `_is_json_native(val)` helper and, in the generic introspection loop, coerce any non-JSON-native declared value to `repr(val)` at the serialization edge (mirroring the bespoke policy fields). The bespoke field handling (enum `.value`, policy `repr`, `timeframe_alias`, UUID stringification) is untouched. Added a `test_to_dict_is_json_serializable` regression test asserting `json.dumps(strategy.to_dict())` succeeds, regression-locking the documented IN-03 contract. Test file is 4-space indented (matched); base.py is tab (matched). mypy clean.

### IN-01: `_apply_params` deep-copies list/dict/set defaults but not other mutable types

**Files modified:** `itrader/strategy_handler/base.py`
**Commit:** 7eb0f0e
**Applied fix:** Replaced the `isinstance(default, (list, dict, set))` whitelist with a mutability-based guard: a class-attr default is passed through as-is only when it is a known immutable scalar (`None`/`str`/`int`/`float`/`bool`/`Enum`), otherwise it is `copy.deepcopy`-d. This makes a declared default of a `deque`/numpy array/custom mutable object alias-safe too. Deep-copying an effectively-immutable declared policy (e.g. `FractionOfCash`) yields an equal fresh copy — harmless. All 61 strategy unit tests pass; golden unchanged.

### IN-02: `tickers` declared `list[str]` but no validation that it is non-empty / well-formed

**Files modified:** `itrader/strategy_handler/base.py`
**Commit:** 84955ee
**Applied fix:** Added a check at the end of `_apply_params` (runs on construction AND reconfigure, against the resolved instance value so it covers both the kwarg and class-default paths): reject a bare `str`, a non-`list`, an empty list, or a list containing non-`str` elements with a `ValueError`. Placed in `_apply_params` rather than the overridable `validate()` hook so subclasses (like `SMAMACDStrategy`, which overrides `validate()` without `super()`) cannot accidentally bypass it. All e2e/integration fixtures construct `tickers` as a proper non-empty `list[str]`, so 59 e2e/universe tests + 61 strategy tests pass; golden unchanged.

### IN-03: `evaluate` mutates instance state — not re-entrant

**Files modified:** `itrader/strategy_handler/base.py`
**Commit:** 939b618
**Applied fix:** Documentation only (no behavior change). Added a one-line note to the `evaluate` docstring that it is NOT re-entrant — it mutates shared instance state (`self.bars`/`self.now` + registered handles) under the single-writer contract (synchronous backtest loop; one live daemon thread). Consistent with how the threading contracts are documented elsewhere. mypy clean; golden unchanged.

## Skipped Issues

### IN-04: `min_timeframe` type widened to `timedelta | None` but sibling handler stays `timedelta`

**File:** `itrader/strategy_handler/strategies_handler.py:45`
**Reason:** won't-fix (intentional divergence, no code change). The review itself records "**Fix:** None required" and verified no `TradingSystem`/scripts consumer reads `strategies_handler.min_timeframe`, so there is no live `None`-deref risk. The `timedelta | None` sentinel is a deliberate "no strategies registered" signal (cleaner than the sibling `ScreenersHandler`'s `timedelta(weeks=100)` magic seed). Aligning the two handlers is only warranted if a shared consumer is ever introduced — none exists today. Per fix-guidance: NO CODE CHANGE.
**Original issue:** The inconsistency between the two handlers' `min_timeframe` contracts is a maintenance smell only.

### IN-05: Dead commented-out SHORT-signal block in the reference strategy

**File:** `itrader/strategy_handler/strategies/SMA_MACD_strategy.py:73-78`
**Reason:** won't-fix / keep-with-rationale (DO NOT REMOVE). The SHORT-signal branch is intentional deferred scaffolding, explicitly labelled "deferred to the margin/shorts milestone", and the `add_strategy` guard rejects non-`LONG_ONLY` directions — so it is not accidental dead code. The review concludes it is "acceptable to keep given the explicit deferral marker." Removing it would discard the planned shape for the next milestone. Per fix-guidance: keep with the deferral comment.
**Original issue:** Commented-out SHORT block flagged by the commented-out-code check; acceptable to keep given the explicit deferral marker.

---

_Fixed: 2026-06-12_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
