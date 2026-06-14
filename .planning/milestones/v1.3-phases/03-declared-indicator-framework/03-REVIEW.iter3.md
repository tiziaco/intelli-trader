---
phase: 03-declared-indicator-framework
reviewed: 2026-06-12T00:00:00Z
depth: standard
iteration: 2
files_reviewed: 16
files_reviewed_list:
  - itrader/strategy_handler/base.py
  - itrader/strategy_handler/indicators/__init__.py
  - itrader/strategy_handler/indicators/catalog.py
  - itrader/strategy_handler/indicators/handle.py
  - itrader/strategy_handler/primitives.py
  - itrader/strategy_handler/strategies/SMA_MACD_strategy.py
  - itrader/strategy_handler/strategies/empty_strategy.py
  - itrader/strategy_handler/strategies_handler.py
  - tests/e2e/strategies/scripted_emitter.py
  - tests/e2e/strategies/single_market_buy.py
  - tests/integration/test_universe_spans.py
  - tests/unit/strategy/test_indicators.py
  - tests/unit/strategy/test_primitives.py
  - tests/unit/strategy/test_signal_store.py
  - tests/unit/strategy/test_strategy.py
findings:
  critical: 0
  warning: 2
  info: 1
  total: 3
status: issues_found
---

# Phase 03: Code Review Report (Iteration 2 — fix verification)

**Reviewed:** 2026-06-12
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Iteration-2 adversarial re-review of the fixer's commits `d8dd1ba..939b618`
(6 commits closing prior WR-01..WR-04 + IN-01..IN-03). Primary job: prove the
fixes introduced no NEW defects and confirm prior findings are genuinely resolved.

**Empirical gates run (all green):**

- **Byte-exact golden oracle holds.** `tests/integration/test_backtest_oracle.py`
  passes (3/3) — the 134-trade / `46189.87730727451` lock is unmoved. None of the
  six fixes touch the SMA/MACDHist compute or the `_at` reference path (literal `0`
  stays scalar), so the golden is provably untouched.
- **`mypy --strict` clean** on `primitives.py`, `handle.py`, `base.py`
  (`Success: no issues found in 3 source files`) — the `cast(Any, ...)` at the
  `numbers.Number` conversion edge keeps the strict gate green; no regression.
- **Full strategy + e2e + integration suites green** — `tests/unit/strategy/`
  (62 passed incl. smoke), `tests/e2e` + `tests/integration/test_universe_spans.py`
  (59 passed). No `filterwarnings=error` trip.

**Prior-finding disposition:**

| Prior | Status | Notes |
|-------|--------|-------|
| WR-01 (assert→raise) | RESOLVED | `RuntimeError` raised unconditionally; `-O`/PYTHONOPTIMIZE-safe. Correct. |
| WR-02 (numpy scalar) | RESOLVED (scope) | `numbers.Number` catches `np.float64`/`np.int64`; verified `pd.Series`/`IndicatorHandle`/`np.array` are NOT `numbers.Number`, so they keep the index path. 0-d-array residual noted below (= old behavior, not a regression). |
| WR-03 (bool threshold) | RESOLVED | `bool` rejected with `TypeError` BEFORE the scalar check. |
| WR-04 (to_dict JSON) | PARTIAL | Scalar non-native coerced to `repr`; nested `list`/`dict`-of-non-native still breaks `json.dumps` — see WR-01 below. |
| IN-01 (deepcopy widening) | RESOLVED / inert | Mutability-based guard is correct; verified NO declared default actually hits the deepcopy branch today (all scalar/Enum/None/required), so the golden construction path is untouched. |
| IN-02 (tickers validation) | RESOLVED | Rejects bare-`str`/empty/non-`list[str]`; verified every Strategy-derived fixture passes a real `list[str]` (`tickers=list(...)`), so no legitimate fixture is rejected. |
| IN-03 (re-entrancy doc) | RESOLVED | Docstring-only; no behavior change. |
| IN-04 / IN-05 | ACCEPTED (won't-fix) | Per re-review context — intentional divergence / deferred-shorts scaffolding. Not re-raised. |

Two genuinely-unresolved/new quality findings remain (both latent, neither blocks
the golden). No blockers.

## Narrative Findings (AI reviewer)

## Warnings

### WR-01: WR-04 fix is incomplete — nested `list`/`dict`-of-non-native still breaks `json.dumps(to_dict())`

**File:** `itrader/strategy_handler/base.py:29-33` (`_is_json_native`), `342-350`
**Issue:** The fix coerces a *scalar* non-JSON-native declared value to `repr()`, but
`_is_json_native` classifies by the **top-level container type only**:
```python
return val is None or isinstance(val, (str, int, float, list, dict))
```
A declared attr whose value is a `list`/`dict` *containing* a non-native element
(e.g. `list[Decimal]`, `dict[str, datetime]`) passes the `_is_json_native` gate
because the container itself is a `list`/`dict`, is emitted as-is, and
`json.dumps(strategy.to_dict())` STILL raises `TypeError: Object of type Decimal is
not JSON serializable`. Verified empirically:
```
list passes native check: True   -> json FAILS: Object of type Decimal is not JSON serializable
dict passes native check: True   -> json FAILS: Object of type datetime is not JSON serializable
```
The documented contract WR-04 set out to guarantee ("`json.dumps(to_dict())` never
raises for the introspected surface") is therefore only half-enforced. The new
regression test (`test_to_dict_is_json_serializable`) exercises only
`SMAMACDStrategy`, whose declared attrs are all scalar/enum/policy — so it passes
while giving **false confidence** that the nested case is covered.

This is **latent, not reachable on the golden/test path** today (the only declared
`list`/`dict` attr is `tickers: list[str]`, whose contents are JSON-native), i.e.
the same reachability and severity as the original WR-04 — a partial close, not a
regression.
**Fix:** Either make the coercion recursive (walk `list`/`dict` contents and `repr`
non-native leaves) or, more simply, route the whole snapshot through a
`json.dumps(..., default=repr)`-style edge so the guarantee is structural rather
than type-list-based. Then extend the regression test with a synthetic strategy
declaring a `list`-of-`Decimal` / `dict`-of-`datetime` attr so the nested case is
actually regression-locked:
```python
def _json_safe(v: Any) -> Any:
    if _is_json_native(v) and not isinstance(v, (list, dict)):
        return v
    if isinstance(v, list):
        return [_json_safe(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _json_safe(x) for k, x in v.items()}
    return repr(v)
```

### WR-02: Hardening fixes WR-01/WR-02/WR-03 added behavior but no regression tests — not locked

**File:** `tests/unit/strategy/test_primitives.py`, `tests/unit/strategy/test_indicators.py`
**Issue:** Three of the four source fixes introduced new runtime behavior with **no
direct test asserting it**:
- WR-01 (`handle.py:60-61`): the read-before-repopulate `RuntimeError` — no test asserts
  `pytest.raises(RuntimeError)` on a fresh handle. `test_indicators.py` only covers
  `__len__ == 0` pre-repopulate, never the `__getitem__` guard.
- WR-02 (`primitives.py:50-54`): the `numbers.Number` / numpy-scalar path — no test
  passes a `np.float64` threshold (`test_primitives.py` scalar tests use literal
  `int`/`float` only).
- WR-03 (`primitives.py:43-44`): the `bool`-rejection `TypeError` — no test asserts
  `crossover(hist, True)` raises.

Only WR-04 got a regression test. Because these behaviors guard real contracts
(the `-O`-safe ordering guarantee, the numpy mis-broadcast trap, the bool footgun),
a future refactor could silently revert them with the suite still green. The fixer's
own commit messages cite these as the value delivered; without assertions they are
not regression-locked.
**Fix:** Add three targeted tests (tab-indented, matching the files' D-05 convention):
```python
def test_handle_getitem_before_repopulate_raises():
	handle = IndicatorHandle(SMA, "close", (3,))
	with pytest.raises(RuntimeError):
		_ = handle[-1]

def test_crossover_rejects_bool_threshold():
	with pytest.raises(TypeError):
		crossover([1.0, 2.0], True)

def test_crossover_numpy_scalar_threshold_broadcasts():
	import numpy as np
	assert crossover([-1.0, 1.0], np.float64(0.0)) is True
```

## Info

### IN-01: `_at` 0-d numpy array still raises `IndexError` (accepted residual, not a regression)

**File:** `itrader/strategy_handler/primitives.py:50-55`
**Issue:** The WR-02 fix catches `np.float64`/`np.int64` scalars (the common
`series.mean()` / `arr[i]` producers) via `numbers.Number`, but a **0-d numpy array**
(`np.array(3.0)`, `np.asarray(scalar)`) is NOT a `numbers.Number` (verified:
`isinstance(np.array(3.0), numbers.Number) == False`) and falls through to
`series_or_scalar[idx]`, raising `IndexError`. Likewise `np.bool_` is neither caught
by the `bool` guard (`isinstance(np.bool_(True), bool) == False`) nor a
`numbers.Number`, so it also raises at the index edge.

This is **identical to the pre-fix behavior for those subcases** (the original WR-02
explicitly noted "for a 0-d numpy scalar that raises IndexError/TypeError"), so it is
not a regression and these inputs fail loudly rather than silently mis-broadcasting —
acceptable. Flagged only so the residual is documented; the reference path
(literal `0`) and the common numpy-scalar path are correctly handled.
**Fix:** None required. Optionally normalize via `np.ndim(x) == 0` → scalar if a
future author wants 0-d-array tolerance; not worth the surface today.

---

## Verification notes (cleared — no defect)

- **IN-01 deepcopy widening is inert on the current surface.** Enumerated every
  declared `get_type_hints` default: all are scalar/Enum/None or required
  (`timeframe`/`tickers`/`sizing_policy`), so the `copy.deepcopy(default)` branch is
  never taken today. The golden construction path is unchanged (oracle test green).
- **IN-02 rejects no legitimate fixture.** `tickers` is a required `list[str]`;
  `scripted_emitter`, `single_market_buy`, and `test_universe_spans` all pass
  `tickers=list(...)`. The screener / `my_strategies` `tickers=` hits are a different
  class hierarchy (not `Strategy._apply_params`) and are unaffected.
- **WR-02/WR-03 path discrimination verified empirically:** `pd.Series`,
  `IndicatorHandle`, and 1-d `np.array` are all `isinstance(..., numbers.Number)
  == False` → correct index path; `np.float64`/`np.int64` → correct scalar path;
  `bool` → `TypeError`. The reference literal `0` stays the scalar path.

---

_Reviewed: 2026-06-12 (iteration 2)_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
