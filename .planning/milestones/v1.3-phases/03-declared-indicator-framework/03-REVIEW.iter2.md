---
phase: 03-declared-indicator-framework
reviewed: 2026-06-12T00:00:00Z
depth: standard
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
  warning: 4
  info: 5
  total: 9
status: issues_found
---

# Phase 03: Code Review Report

**Reviewed:** 2026-06-12
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Reviewed the declared-indicator framework: the `indicators/` subsystem (typed adapter
catalog + positional handle), the comparison `primitives`, the `Strategy` ABC's
param-introspection/coercion engine, the reference `SMAMACDStrategy`, the handler's
warmup/fan-out path, and the supporting unit/integration/e2e tests.

Adversarial checks performed and **cleared** (no defect):

- **Byte-exact golden paths preserved.** The SMA per-indicator slice
  (`bars[start_dt:][input_col]`, `fillna=True` as 3rd positional, `start_dt = now -
  timeframe*window`) and the MACDHist full-window/`fillna=False` compute reproduce
  `SMA_MACD_strategy.py` lines 61-65/75-76 verbatim. Verified empirically that at the
  warmup boundary (100-bar window) the SMA(100) slice yields a 100-point series (not 1)
  and SMA(50) yields 51 — so `crossover`/`is_above` reading `[-1]`/`[-2]` never index
  out of bounds, and the firing tick is value-identical to legacy.
- **Warmup short-circuit equivalence.** Old `if len(bars) < self.max_window(==100)`
  ⇒ new `if len(data) < strategy.warmup(==100)`. Since the feed caps `len(data)` at
  `max_window`, both gate identically (`run iff len == 100`).
- **Indentation.** Every source file is pure-tab; every reviewed test file is internally
  consistent (`test_indicators.py`/`test_primitives.py` are deliberately tab-indented per
  their D-05 docstring note; the rest are 4-space). No mixed-indentation diff.
- **Look-ahead safety.** `self.now = window.index[-1]` (last completed bar); handles
  repopulate over the completed-bar window only; SMA's `start_dt` arithmetic looks
  backward. No leak.
- **Money policy.** Indicator values are `ta` float64 by design (not money); the only
  money entries (`buy`/`sell` SL/TP, handler price stamp) go through `to_money` (string
  path). No `Decimal(float)`.

Remaining findings are robustness/quality, listed below. No blockers.

## Warnings

### WR-01: `IndicatorHandle.__getitem__` guards with `assert` — silently disabled under `-O`

**File:** `itrader/strategy_handler/indicators/handle.py:55-56`
**Issue:** The read-before-repopulate guard is an `assert`:
```python
assert self._values is not None, "repopulate() before reading the handle"
return float(self._values.iloc[idx])
```
Python run with `-O` (or `PYTHONOPTIMIZE`) strips `assert` statements. With the guard
gone, `self._values` is `None` and the next line raises `AttributeError: 'NoneType'
object has no attribute 'iloc'` — a confusing failure far from the real cause (a handle
read before `repopulate`). Asserts are for invariants the developer believes can never
fail, not for guarding a real runtime ordering contract that the docstring explicitly
calls a contract.
**Fix:** Raise an explicit error so the contract holds regardless of optimization level:
```python
if self._values is None:
    raise RuntimeError("repopulate() must run before reading the handle")
return float(self._values.iloc[idx])
```

### WR-02: `_at` scalar detection misses numpy scalars — silent wrong-path indexing

**File:** `itrader/strategy_handler/primitives.py:36-40`
**Issue:**
```python
def _at(series_or_scalar: Any, idx: int) -> float:
    if isinstance(series_or_scalar, (int, float)):
        return float(series_or_scalar)
    return float(series_or_scalar[idx])
```
The scalar broadcast only recognizes native Python `int`/`float`. A `numpy.float64` /
`numpy.int64` (the natural type produced by `np.array(...)[i]`, `series.mean()`, etc.)
is **not** an instance of Python `float`/`int`, so it falls through to
`series_or_scalar[idx]`. For a 0-d numpy scalar that raises
`IndexError`/`TypeError`; for a numpy array it silently indexes a different element than
the author intended (e.g. `crossover(hist, threshold_array)` would compare against
`threshold_array[-2]`/`[-1]` instead of broadcasting). The reference path passes a
literal `0`, so the golden is unaffected — but the primitive is a public surface and the
silent mis-broadcast is a latent correctness trap for the next author.
**Fix:** Detect by "has `__getitem__` / is sequence-like" rather than a whitelist, or
broaden the scalar check to cover numbers generically:
```python
import numbers
def _at(series_or_scalar: Any, idx: int) -> float:
    if isinstance(series_or_scalar, numbers.Number):  # covers numpy scalars too
        return float(series_or_scalar)
    return float(series_or_scalar[idx])
```

### WR-03: `bool` is silently accepted as a scalar threshold in `_at`

**File:** `itrader/strategy_handler/primitives.py:38`
**Issue:** Because `bool` subclasses `int`, `crossover(hist, True)` is silently treated as
the scalar `1.0` instead of being rejected. A boolean threshold is almost certainly an
author error (passing a comparison result where a level was meant), but it is coerced to
`1.0`/`0.0` with no signal. This compounds WR-02: the type whitelist is both too narrow
(misses numpy) and too wide (admits `bool`).
**Fix:** Either explicitly reject `bool` (`isinstance(x, bool)` first → raise) or rely on
the `numbers.Number` form from WR-02 plus a `bool` guard if strictness is desired. Low
severity but trivial to harden.

### WR-04: `to_dict()` config snapshot can hold non-JSON-serializable policy/intent values

**File:** `itrader/strategy_handler/base.py:281-335`
**Issue:** `to_dict()` is documented as a serialization-edge dict (the IN-03 comment cites
`json.dumps(strategy.to_dict())` as the contract) and it correctly stringifies
`strategy_id`/`subscribed_portfolios` and `repr()`s `sizing_policy`/`sltp_policy`. But the
*generic* introspection loop (lines 292-303) emits any other declared attr by `getattr`
as-is. Today the only non-trivial declared types are enums (handled) and policies
(handled), so this is latent — but the moment an author declares a typed attr whose value
is e.g. a `Decimal`, `datetime`, or a custom object, `to_dict()` returns a dict that is
NOT round-trippable through `json.dumps`, breaking the stated SIG-02 queryability
contract that IN-03/WR-01 went out of their way to guarantee. The serialization guarantee
is asserted for the *known* fields but not enforced for the *introspected* surface the
method exists to capture.
**Fix:** In the introspection loop, coerce unknown value types at the edge — e.g. fall
back to `repr(val)` (or `str(val)`) for any value that is not already a JSON-native type
(`str`/`int`/`float`/`bool`/`None`/`list`/`dict`), mirroring how the bespoke fields are
serialized. At minimum, add a test that `json.dumps(strategy.to_dict())` succeeds so the
documented contract is regression-locked.

## Info

### IN-01: `_apply_params` deep-copies list/dict/set defaults but not other mutable types

**File:** `itrader/strategy_handler/base.py:131`
**Issue:** The mutable-default-alias guard `copy.deepcopy(default) if isinstance(default,
(list, dict, set))` covers the three common containers, but a declared default of another
mutable type (e.g. a custom dataclass instance, a `collections.deque`, a numpy array)
would still be aliased across instances. The declared-policy objects (`FractionOfCash`,
etc.) are effectively immutable so the current surface is safe; flagging because the guard
is type-list-based rather than mutability-based and the comment presents it as the general
fix for "the classic mutable-default bug."
**Fix:** Consider `copy.deepcopy` for any non-(str/int/float/bool/None/Enum/frozen) class
attr, or document that only list/dict/set defaults are alias-safe.

### IN-02: `tickers` declared `list[str]` but no validation that it is non-empty / well-formed

**File:** `itrader/strategy_handler/base.py:67`, `strategies_handler.py:74`
**Issue:** A strategy constructed with `tickers=[]` (or a stray `tickers="BTCUSD"` — a
str, which is iterable char-by-char) passes `_apply_params` (no coercion on `tickers`),
and `calculate_signals` then iterates `for ticker in strategy.tickers` — a bare string
would iterate single characters and request windows for `"B"`, `"T"`, … silently
producing nothing rather than failing loudly. Not reachable on the golden/test path, but
the introspection engine's "reject unknown/missing loudly" philosophy is not extended to
malformed-but-present values.
**Fix:** Add a `validate()`-time or `_apply_params`-time check that `tickers` is a
non-empty list of `str` (reject a bare `str`).

### IN-03: `evaluate` mutates instance state (`self.bars`, `self.now`) — not re-entrant

**File:** `itrader/strategy_handler/base.py:254-259`
**Issue:** `evaluate` stashes `self.bars`/`self.now` on the instance before dispatch. In
the single-threaded backtest loop this is fine (single-writer contract), and live mode
processes on one daemon thread — but a single `Strategy` instance subscribed to evaluate
concurrently (or re-entered) would race on this shared mutable state. Worth a one-line
note that `evaluate` is not re-entrant, consistent with how the threading contracts are
documented elsewhere.
**Fix:** Documentation only (no code change needed under the current single-writer
contract); optionally assert single-threaded use in live mode.

### IN-04: `min_timeframe` type widened to `timedelta | None` but downstream type is `timedelta`

**File:** `itrader/strategy_handler/strategies_handler.py:45`
**Issue:** `StrategiesHandler.min_timeframe` is now `timedelta | None` (clean "no
strategies" sentinel — good), whereas the sibling `ScreenersHandler.min_timeframe` stays
`timedelta` seeded to `timedelta(weeks=100)`. Verified no TradingSystem/scripts consumer
reads `strategies_handler.min_timeframe`, so there is no live `None`-deref risk today. The
inconsistency between the two handlers' contracts is a maintenance smell only.
**Fix:** None required; note the intentional divergence or align the two handlers if a
shared consumer is ever introduced.

### IN-05: Dead commented-out SHORT-signal block left in the reference strategy

**File:** `itrader/strategy_handler/strategies/SMA_MACD_strategy.py:73-78`
**Issue:** The SHORT-signal branch is left as a commented-out block. It is explicitly
labelled "deferred to the margin/shorts milestone" and the `add_strategy` guard rejects
non-LONG_ONLY, so this is intentional scaffolding rather than accidental dead code.
Flagging per the commented-out-code check; acceptable to keep given the explicit deferral
marker.
**Fix:** Keep with the deferral comment, or move the planned shape into the phase plan
rather than the source.

---

_Reviewed: 2026-06-12_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
