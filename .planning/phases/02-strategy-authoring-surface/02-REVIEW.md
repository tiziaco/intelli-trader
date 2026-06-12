---
phase: 02-strategy-authoring-surface
reviewed: 2026-06-12T00:00:00Z
depth: standard
files_reviewed: 18
files_reviewed_list:
  - itrader/core/exceptions/strategy.py
  - itrader/core/exceptions/__init__.py
  - itrader/strategy_handler/base.py
  - itrader/strategy_handler/strategies/SMA_MACD_strategy.py
  - itrader/strategy_handler/strategies/empty_strategy.py
  - itrader/strategy_handler/signal_record.py
  - itrader/strategy_handler/strategies_handler.py
  - itrader/config/__init__.py
  - scripts/run_backtest.py
  - tests/unit/strategy/test_strategy_config.py
  - tests/unit/strategy/test_strategy.py
  - tests/unit/strategy/test_signal_store.py
  - tests/e2e/strategies/scripted_emitter.py
  - tests/e2e/strategies/single_market_buy.py
  - tests/integration/test_backtest_oracle.py
  - tests/integration/test_backtest_smoke.py
  - tests/integration/test_universe_spans.py
  - tests/integration/test_reservation_inertness.py
findings:
  critical: 0
  warning: 4
  info: 3
  total: 7
status: issues_found
---

# Phase 2: Code Review Report

**Reviewed:** 2026-06-12T00:00:00Z
**Depth:** standard
**Files Reviewed:** 18
**Status:** issues_found

## Summary

Adversarial review of the strategy-authoring-surface refactor: the `Strategy(name, config)`
pydantic constructor was replaced by a `**kwargs` class-attr introspection engine
(`_apply_params` using `get_type_hints` + an enum-coercion table + `setattr`), with
`init()`/`validate()`/`reconfigure()` lifecycle hooks and a new `SignalRecord` sink.

The high-risk areas called out for this phase were checked and **held up**:

- **Indentation convention is correct everywhere.** `base.py` and `strategies_handler.py`
  are tab-indented; `core/exceptions/strategy.py`, `signal_record.py`, and all tests are
  4-space. No mixed-indentation defect.
- **Money is string-path Decimal.** Every `FractionOfCash(Decimal("0.95"))` literal is the
  string path; `buy()`/`sell()` enter the Decimal domain only via `to_money`. No
  `Decimal(float)` anywhere in the reviewed surface.
- **The `self.timeframe` enum→timedelta resolution + reconfigure fallback** (the #1
  byte-exactness trap) is implemented correctly: the loop stashes the enum on `_timeframe`,
  the timeframe branch reads `_timeframe` (never the now-timedelta `self.timeframe`), and a
  partial reconfigure preserves the prior timeframe. Verified by direct execution.
- **Unknown/missing-required rejection** (`UnknownParamError` / `MissingParamError`) works as
  documented; all 23 unit tests pass and mypy `--strict` is clean on the engine.

The findings below are latent defects in the introspection engine and a documented-contract
gap in the `SignalRecord` snapshot — none break the golden oracle path, but two are real
correctness/robustness traps for the *next* strategy author who is not on the golden path.

## Warnings

### WR-01: Mutable class-attr default is aliased across all instances (shared-state hazard)

**File:** `itrader/strategy_handler/base.py:117-124`
**Issue:** When a declared param is resolved from its class-attr default, the engine does a
bare `setattr(self, nm, default)` where `default = getattr(type(self), nm, _MISSING)`. If a
subclass declares a **mutable** default — e.g. `tickers: list[str] = ["BTCUSD"]` or a
`max_positions` list — every instance constructed without that kwarg shares the *same* object.
Mutating one instance's value leaks into all others (the classic mutable-default-argument bug,
re-expressed through class attributes). Confirmed by direct execution: two instances of a
strategy with `tickers: list = ['BTC']` and no kwarg share one list, and `a.tickers.append('ETH')`
leaks into `b.tickers`.

None of the reviewed strategies trip this on the golden path (they all pass `tickers`/
`sizing_policy` as kwargs), but `EmptyStrategy`/`SMAMACDStrategy` author conventions invite a
mutable class default, and the engine is the shared base every future strategy inherits.
**Fix:** Defensively copy mutable defaults when falling back to a class attr:
```python
elif default is not _MISSING:
    # copy mutable defaults so a class-attr list/dict/set is not aliased
    # across instances (shared-state hazard).
    val = copy.deepcopy(default) if isinstance(default, (list, dict, set)) else default
```
(or document, loudly, that class-attr defaults MUST be immutable and reject mutable defaults at
construction).

### WR-02: `to_dict()` config snapshot silently omits timeframe, tickers, and all subclass knobs

**File:** `itrader/strategy_handler/base.py:180-207` (consumed at `strategies_handler.py:126`)
**Issue:** `SignalRecord.config` is documented (signal_record.py:67-70) as "a plain params
snapshot dict captured from the strategy's declared attrs (`strategy.to_dict()`)". But `to_dict()`
hand-lists a fixed subset and **omits `timeframe`/`timeframe_alias`, `tickers`, `max_window`,
`warmup`, and every subclass-specific tuning knob** (`short_window`, `long_window`, `fast_window`,
`slow_window`, `signal_window`, …). Verified: `to_dict().keys()` for `SMAMACDStrategy` returns only
`{strategy_id, strategy_name, order_type, is_active, sizing_policy, direction, allow_increase,
max_positions, sltp_policy, subscribed_portfolios}`.

The persisted "params snapshot" therefore cannot reproduce the strategy — the two parameters most
needed to interpret a signal (which timeframe, which tickers) and all the alpha-defining windows
are absent. This is oracle-dark (config never influences fills), so it is not a BLOCKER, but the
SIG-02 "queryable snapshot" contract is not actually met, and the signal_store test
(`record.config == strategy.to_dict()`) only proves self-consistency, not completeness.
**Fix:** Make `to_dict()` introspect the declared surface so the snapshot is faithful:
```python
declared = {nm: getattr(self, nm) for nm in get_type_hints(type(self))}
# serialize the timeframe via the stashed alias (self.timeframe is a timedelta),
# enums via .value, policies via repr — then merge with the identity/runtime fields.
```
At minimum add `timeframe_alias` and `tickers` to the returned dict.

### WR-03: `generate_signal` precondition crash — relocated warmup guard leaves the pure function fragile

**File:** `itrader/strategy_handler/strategies/SMA_MACD_strategy.py:52-95`
**Issue:** The in-strategy guard `if len(bars) < self.max_window: return None` was removed (D-15)
and relocated to the handler's `strategy.warmup` short-circuit. `generate_signal` now assumes it
is only ever called with enough bars and reaches `MACDhist.iloc[-2]` unconditionally. Called with
a sub-warmup frame it raises `IndexError: single positional indexer is out-of-bounds` (verified
with a 10-bar frame) rather than returning `None`.

On the golden path this is safe because `SMAMACDStrategy` sets `warmup=100` and the only production
caller (`StrategiesHandler.calculate_signals`, line 103) enforces it. But the contract is now
"caller must pre-gate," and the engine offers `warmup=0` as a default — any SMA-style strategy
authored with a low/zero warmup but legitimately sparse early data will crash mid-run instead of
no-op'ing. The backtest error policy is fail-fast, so a single such tick aborts the whole run.
**Fix:** Either keep a cheap defensive guard at the top of `generate_signal`
(`if len(bars) < self.long_window: return None`), or have the framework derive the warmup
threshold from the declared windows instead of trusting a hand-set `warmup` that can silently be 0.

### WR-04: Reconfigure preserves prior instance value over a *changed* class-attr default

**File:** `itrader/strategy_handler/base.py:113-118`
**Issue:** On a partial `reconfigure`, a declared field that is omitted from kwargs falls back to
the **prior instance value** (`getattr(self, nm)`, line 116) *before* it would fall back to the
class default (line 117). This is the documented "partial reconfigure keeps prior value" semantic
(RESEARCH Open Question 1), so it is intentional — but it is also a footgun: a field that the
author believes is "reset to default on reconfigure" silently keeps a previously-supplied value,
and there is no way through `reconfigure` to *clear* an optional field back to its class default
(e.g. set `sltp_policy` back to `None` after it was supplied once). A caller must know the prior
value to overwrite it.

This is behavior-correct against the stated decision and oracle-dark, so it is a WARNING, not a
blocker — but the asymmetry (kwargs override; omission freezes the last value, never the default)
deserves an explicit test and a one-line note in the `reconfigure` docstring, because the next
author will reasonably expect omitted-on-reconfigure to mean "use the default."
**Fix:** Add a test pinning "omit-on-reconfigure keeps prior, not default," and document the
non-resettability explicitly in `reconfigure.__doc__`. If resettability is desired, accept an
explicit sentinel (e.g. `reconfigure(sltp_policy=None)` already works — only document that the
*omission* path differs).

## Info

### IN-01: Dead `tuple`-pair branch in `get_strategies_universe`

**File:** `itrader/strategy_handler/strategies_handler.py:186-189`
**Issue:** `if strategy.tickers and isinstance(strategy.tickers[0], tuple)` guards a pairs-trading
branch the code comment itself says "never legitimately fires for a config-built strategy — it
remains only for legacy callers." The declared contract is `tickers: list[str]`, so `tickers[0]`
is always a `str` and the branch is dead on every supported path.
**Fix:** Remove the dead branch (and the `pair`/`sym` comprehension) once the legacy-caller claim is
confirmed unused, or convert it to an explicit typed pairs API rather than runtime `isinstance`
sniffing on the first element.

### IN-02: `SignalRecord.config` test asserts self-consistency, not snapshot fidelity

**File:** `tests/unit/strategy/test_signal_store.py:176`, `tests/integration/test_backtest_oracle.py:304`
**Issue:** `assert record.config == strategy.to_dict()` compares the stored snapshot against a
*later* `to_dict()` call on the same live strategy. Because `to_dict()` is deterministic and the
strategy is immutable between the two calls in these tests, this passes trivially — but it proves
nothing about whether the snapshot captured the *intended* params (it inherits the WR-02 omission).
If subscriptions or knobs changed between capture and assertion, the test would also break for the
wrong reason (`subscribed_portfolios` is part of `to_dict()`).
**Fix:** Assert the snapshot against an explicit expected dict (or at least against the specific
fields that matter — `strategy_name`, `direction`, `sizing_policy`), independent of a re-derived
`to_dict()`.

### IN-03: Module-level constants duplicated across integration tests

**File:** `tests/integration/test_backtest_oracle.py:33-34`, `tests/integration/test_reservation_inertness.py:37-38`
**Issue:** `_REPO_ROOT` / `_RUN_BACKTEST` and the `_load_run_backtest_module()` importlib helper are
copy-pasted near-verbatim across the two integration tests (and the golden pins are re-imported from
`run_backtest.py` in three places). Minor duplication; fine for now but a single shared
`tests/integration/_oracle_harness.py` would prevent the two copies from drifting.
**Fix:** Extract the `_load_run_backtest_module` helper and repo-root constants into one shared
conftest/helper module.

---

_Reviewed: 2026-06-12T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
