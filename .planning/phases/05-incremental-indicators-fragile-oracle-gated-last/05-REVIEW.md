---
phase: 05-incremental-indicators-fragile-oracle-gated-last
reviewed: 2026-06-25T00:00:00Z
depth: standard
files_reviewed: 25
files_reviewed_list:
  - itrader/price_handler/feed/bar_feed.py
  - itrader/price_handler/feed/base.py
  - itrader/price_handler/feed/cache_registration.py
  - itrader/strategy_handler/base.py
  - itrader/strategy_handler/indicators/catalog.py
  - itrader/strategy_handler/indicators/handle.py
  - itrader/strategy_handler/indicators/__init__.py
  - itrader/strategy_handler/strategies_handler.py
  - itrader/strategy_handler/pair_base.py
  - itrader/strategy_handler/strategies/eth_btc_pair_strategy.py
  - itrader/strategy_handler/strategies/SMA_MACD_strategy.py
  - perf/strategies/a_bracketed_momentum.py
  - perf/strategies/b_limit_maker.py
  - perf/strategies/c_pyramiding_trend.py
  - perf/strategies/d_short_zscore.py
  - perf/runners/run_w2_sweep.py
  - scripts/crossval/limit_entry_strategy.py
  - tests/e2e/strategies/scripted_emitter.py
  - tests/e2e/strategies/single_market_buy.py
  - tests/integration/test_bar_cache_registration.py
  - tests/unit/strategy/test_causal_guard.py
  - tests/unit/strategy/test_indicator_convergence.py
  - tests/unit/strategy/test_indicator_reset.py
  - tests/unit/strategy/test_indicators.py
  - tests/unit/strategy/test_pair_dispatch.py
findings:
  critical: 1
  warning: 3
  info: 2
  total: 6
status: issues_found
---

# Phase 5: Code Review Report

**Reviewed:** 2026-06-25
**Depth:** standard
**Files Reviewed:** 25
**Status:** issues_found

## Summary

Phase 5 converts all four indicators (SMA/EMA/MACD/RSI) to hand-written O(1) stateful float64 recurrences, introduces a shared recent-bars feed layer, and restructures the strategy-handler loop to `update(ticker, bar) → is_ready → generate_signal`. The architecture is sound: look-ahead safety is correctly enforced, per-symbol fan-out state isolation is correct, the deque-based SMA ring correctly evicts via manual `popleft()`, and the money boundary is properly respected (Decimal end-to-end for money, float64 for analytics).

One CRITICAL finding: a production-code `assert` in `_readonly_master` (bar_feed.py) guards the read-only buffer invariant but will be silently stripped under `-O`/PYTHONOPTIMIZE — directly contrary to the project's own stated policy and causing a silent safety regression in optimized builds.

Three WARNINGs cover: (1) `_MACDHistState.update()` asserting two invariants that, if wrong, would raise a confusing `TypeError` instead of a clear invariant-violation; (2) `_raw_bar_consumers` property setting an undeclared instance attribute (`_raw_bar_consumers_store`) via `setattr`, which mypy strict and IDEs cannot validate; (3) the stale "three engine fields" comment repeated four times in `base.py` when `_COERCE` contains only two entries.

Two INFO items cover minor style drift in the perf strategies (space-indented in a tabs codebase) and dead guard code in `EthBtcPairStrategy.evaluate_pair`.

---

## Critical Issues

### CR-01: Production `assert` guards the read-only buffer invariant — stripped under `-O`

**File:** `itrader/price_handler/feed/bar_feed.py:173`

**Issue:** `_readonly_master` sets `buffer.flags.writeable = False` to enforce the D-09 look-ahead invariant (per-tick window views inherit a read-only buffer, so an in-place mutation raises `ValueError` instead of silently poisoning a future tick). The correctness of this flag is verified by `assert np.shares_memory(buffer, master.to_numpy(copy=False))` — but `assert` is stripped under `-O`/`PYTHONOPTIMIZE`. If the assertion is stripped and the buffer is NOT sharing memory (e.g. after a future numpy or pandas internal change), `buffer.flags.writeable = False` would mark the WRONG buffer, silently leaving the master frame's buffer writeable. A strategy could then mutate a window view and corrupt the next tick's data — the exact correctness defect D-09 was designed to prevent.

This directly contradicts the project's own policy documented in `handle.py` (line 128):

> "WR-01: a real runtime ordering contract ... must raise unconditionally — an `assert` is stripped under `-O`/PYTHONOPTIMIZE, turning the violation into a confusing ... far from the cause."

**Fix:** Replace the `assert` with an explicit `if`/`raise`:

```python
# bar_feed.py  ~line 173
if not np.shares_memory(buffer, master.to_numpy(copy=False)):
    raise RuntimeError(
        "to_numpy(copy=False) did not alias the frame's own buffer after "
        "consolidation — read-only flag would not take effect (D-09 fallback)"
    )
buffer.flags.writeable = False
```

---

## Warnings

### WR-01: `_MACDHistState.update()` uses bare `assert` for runtime invariants

**File:** `itrader/strategy_handler/indicators/catalog.py:193,197`

**Issue:** Two `assert` statements inside `_MACDHistState.update()` express invariants that must hold for `self.value` to be computed correctly:

```python
assert fast_v is not None and slow_v is not None  # line 193
assert signal_v is not None                       # line 197
```

Under `-O`/PYTHONOPTIMIZE both are stripped. If either `fast_v` or `signal_v` were `None` (e.g. after a future refactor of `_EMAState`), line 198 `self.value = macd_line - signal_v` would raise `TypeError: unsupported operand type(s)` with no reference to the violated invariant — the exact diagnostic problem the project's own policy (`handle.py` WR-01) documents. The invariants ARE mathematically guaranteed today (EMA seeds from bar 0), but the expressed intent is that these are runtime guards, not performance assertions, and they should survive optimization.

**Fix:** Replace both with explicit checks:

```python
# catalog.py ~line 191-198
if fast_v is None or slow_v is None:
    raise RuntimeError(
        "_MACDHistState: EMA values must be non-None after bar 0 — "
        "recurrence seeded incorrectly (P5-D11 invariant)"
    )
macd_line = fast_v - slow_v
self._signal.update(macd_line)
signal_v = self._signal.value
if signal_v is None:
    raise RuntimeError(
        "_MACDHistState: signal EMA must produce a value after the first "
        "update — seed-from-first invariant violated (P5-D11)"
    )
self.value = macd_line - signal_v
```

---

### WR-02: `_raw_bar_consumers` property stores state via dynamic `setattr` — invisible to type checkers

**File:** `itrader/price_handler/feed/base.py:135-138`

**Issue:** The `_raw_bar_consumers` property lazy-initializes its backing store by writing an undeclared attribute name (`_raw_bar_consumers_store`) directly onto `self` via assignment:

```python
registry = getattr(self, "_raw_bar_consumers_store", None)
if registry is None:
    registry = []
    self._raw_bar_consumers_store = registry   # dynamic setattr
return registry
```

Because `_raw_bar_consumers_store` is not declared in any `__init__` or as a class annotation, `mypy --strict` cannot type-check it, and IDEs see it as untyped. Additionally, the property is named `_raw_bar_consumers` while the backing store is `_raw_bar_consumers_store` — any subclass or future caller that tries to access `self._raw_bar_consumers_store` directly bypasses the lazy-init guarantee. The `register_raw_bar_consumer` method correctly calls through the property (so it works), but the pattern is fragile.

**Fix:** Declare the backing store in `BarFeed.__init__` (or add a note that subclasses need no `super().__init__` because the ABC has no `__init__`). The simplest fix is to initialize `_raw_bar_consumers_store` in a dedicated `__init__` on `BarFeed`, or to use a `ClassVar` default:

```python
# base.py — add __init__ to BarFeed ABC
def __init__(self) -> None:
    self._raw_bar_consumers_store: list[RawBarConsumer] = []
```

This makes the attribute visible to mypy and removes the `getattr` workaround.

---

### WR-03: Stale "three engine fields" comment — `_COERCE` has only two entries

**File:** `itrader/strategy_handler/base.py:101,117,137,179`

**Issue:** The comment at line 101 reads:

```python
# D-08: ONLY these three engine fields coerce a str off their annotation to an
# enum (via the enum's case-insensitive _missing_).
_COERCE: dict[str, type[Enum]] = {
    "timeframe": Timeframe,
    "direction": TradingDirection,
}
```

The dict has exactly **two** entries. The same stale count ("three enum fields") is repeated three more times in the method docstrings (lines 117, 137, 179). The likely history is that `order_type` was a third coerced field before D-01 retired the per-instance `order_type` attr. With the retired entry not cleaned up from the comments, a future author adding a third coerce field might assume the dict is correct and skip counting. More seriously, the class docstring at line 117 says "coercing the three enum fields" — a reader auditing the coercion logic who counts two will distrust the codebase.

**Fix:** Update all four occurrences from "three" to "two":
- Line 101: `# D-08: ONLY these two engine fields coerce ...`
- Line 117: `coercing the two enum fields` (Strategy class docstring)
- Line 137: `The two bare annotations` → unrelated, check separately
- Line 179: `The two _COERCE enum fields coerce ...` (_apply_params docstring)

---

## Info

### IN-01: Perf strategies use 4-space indentation in a tabs-convention file context

**File:** `perf/strategies/a_bracketed_momentum.py:61-96`, `perf/strategies/b_limit_maker.py:49-86`, `perf/strategies/c_pyramiding_trend.py:43-81`, `perf/strategies/d_short_zscore.py:53-108`

**Issue:** The strategy handler domain (`strategy_handler/**`) uses tabs per the CLAUDE.md convention. The four perf strategy files use 4-space indentation throughout. These files import and subclass `Strategy` from `itrader/strategy_handler/base.py`. While they live in `perf/` (not `itrader/`), they are subject to the same convention as a strategy subclass and the mixed convention in the repository could confuse a contributor normalizing indentation.

**Fix:** No immediate fix required if `perf/` has its own convention. Document in `perf/README.md` or add a comment at the top of each file noting the 4-space convention as intentional for the `perf/` directory. If bringing into the main codebase, convert to tabs to match `strategy_handler/**`.

---

### IN-02: Dead length guard in `EthBtcPairStrategy.evaluate_pair` — always bypassed by `is_pair_ready`

**File:** `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py:225-228`

**Issue:** `evaluate_pair` begins with:

```python
required = self.beta_warmup + self.z_lookback
if len(win_A) < required or len(win_B) < required:
    return None
```

This guard can never be True when called through `StrategiesHandler._dispatch_pair`, because `_dispatch_pair` calls `strategy.is_pair_ready()` first (line 308 of `strategies_handler.py`), and `is_pair_ready()` returns True only when `_pair_bar_count >= beta_warmup + z_lookback` — at which point `_buffers_as_windows()` always materializes exactly `beta_warmup + z_lookback` rows (the deque is at capacity). The guard is dead code on the production path. It does provide a useful safety net if `evaluate_pair` is called directly in tests, but the comment at `evaluate_pair` does not mention this.

**Fix:** Either remove the guard and document that the precondition is enforced by `is_pair_ready()` in the caller, or add a comment explaining it is a direct-call safety net:

```python
# Safety guard for direct test invocation; on the production path
# is_pair_ready() in _dispatch_pair guarantees len == required.
```

---

_Reviewed: 2026-06-25_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
