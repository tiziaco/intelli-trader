---
phase: 01-instrument-value-object
reviewed: 2026-06-15T00:00:00Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - itrader/config/exchange.py
  - itrader/core/instrument.py
  - itrader/core/money.py
  - itrader/execution_handler/exchanges/simulated.py
  - itrader/trading_system/backtest_runner.py
  - itrader/trading_system/compose.py
  - itrader/trading_system/live_trading_system.py
  - itrader/universe/__init__.py
  - itrader/universe/instruments.py
  - itrader/universe/membership.py
  - itrader/universe/universe.py
  - tests/unit/core/test_instrument.py
  - tests/unit/core/test_money.py
  - tests/unit/execution/test_min_order_size_resolution.py
  - tests/unit/universe/test_derive_instruments.py
  - tests/unit/universe/test_universe.py
findings:
  critical: 0
  warning: 1
  info: 0
  total: 1
status: issues_found
---

# Phase 01: Code Review Report (Iteration 2)

**Reviewed:** 2026-06-15
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

Re-review of the iteration-1 fix pass (WR-01..WR-05, IN-02..IN-05). The
money-discipline, byte-exact, indentation, and mypy-strict concerns flagged for
heavy scrutiny all hold up:

- **Money / Decimal end-to-end** — clean. No `Decimal(float)` anywhere. The new
  `_CASH_SCALES` derivation in `money.py` is string-path Decimal literals only;
  `_infer_price_scale` enters Decimal via `Decimal(f"1e-{capped}")` (D-04 string
  path); every fee/slippage default routes a Decimal unchanged. `float()`
  appears only at logging / serialization / probability-boundary edges
  (`failure_rate`, `get_exchange_info`, `to_kwargs`) — all documented.
- **Byte-exact discipline** — clean. BTCUSD is `_DECLARED` with `_BTC_8DP`
  (8dp) and inference is never consulted for it; `derive_membership` is now
  `sorted(set(...))` (single-symbol universe is its own sort, oracle unaffected);
  the ping grid `reduce(pd.Index.union, ...)` over one symbol returns that index
  unchanged. The `set(membership) != set(instruments)` invariant is correct
  (`set(dict)` == keys) and cannot false-positive within one interpreter.
- **`frac.isdigit()` guard** (`instruments.py:141`) — correct: rejects empty
  fraction (`"12."`), scientific notation, and trailing garbage; verified
  `"12."` -> `''` -> skipped, `"12.0"` -> 1dp.
- **`_pick[T]`** (PEP 695 generic) and `Engine.universe: Optional[Universe]`
  are mypy-strict clean on Python 3.13.
- **Indentation** — `core/`, `config/`, `universe/` use 4 spaces;
  `trading_system/` (`backtest_runner.py`, `compose.py`) uses tabs;
  `live_trading_system.py` uses 4 spaces (mypy-deferred module). All consistent
  with the file being edited.

One WARNING remains: the `ConfigurationError` raises added by the WR-03 fix pass
in `backtest_runner.py` mis-pass the message as the `config_key` positional,
malforming the diagnostic and the structured `config_key` attribute.

## Warnings

### WR-01: `ConfigurationError` raised with message in the `config_key` slot

**File:** `itrader/trading_system/backtest_runner.py:82` (and `:105`)
**Issue:**
`ConfigurationError.__init__` is `(config_key=None, config_value=None,
reason=None)` and builds its message as
`"Configuration error" [+ " for '{config_key}'"] [+ ": {reason}"]`
(`core/exceptions/base.py:31-42`). The established call convention everywhere
else is keyword/positional-by-slot — e.g. `ConfigurationError(reason=str(e))`
(`order_manager.py:194`, `portfolio.py:178`, `simulated.py:739`),
`ConfigurationError(config_key=..., reason=...)` (`bar_feed.py:230`), or
`ConfigurationError("db_url", None, "...")` (`storage_factory.py:46`).

Both new raises (the WR-03 desync assert at `:82`, and the empty-store guard at
`:105`) pass the entire human-readable message as the first positional argument,
so it lands in `config_key`:

```python
raise ConfigurationError(
    "Universe membership desync: derive_membership and "
    "derive_instruments produced different symbol sets "
    f"(members={sorted(set(membership))}, "
    f"instruments={sorted(set(instruments))})")
```

renders as:

```
Configuration error for 'Universe membership desync: ... (members=[...], instruments=[...])'
```

Two concrete defects:
1. The diagnostic is awkwardly nested ("Configuration error for '<a full
   sentence>'") — the desync detail is jammed into a slot meant for a config
   key name.
2. `exc.config_key` is now set to the whole prose sentence and `exc.reason` is
   `None`. Any structured consumer that reads `config_key` / `reason` (the
   pattern the exception class exists to support) gets garbage.

Not a crash and the text is still ultimately visible, so backtest output and the
byte-exact oracle are unaffected — hence WARNING, not BLOCKER.

**Fix:** pass the message as `reason` (matching the dominant convention):

```python
raise ConfigurationError(
    reason=(
        "Universe membership desync: derive_membership and "
        "derive_instruments produced different symbol sets "
        f"(members={sorted(set(membership))}, "
        f"instruments={sorted(set(instruments))})"))
```

and likewise at `:105`:

```python
raise ConfigurationError(
    reason=(
        "Backtest store has no symbols — cannot derive the ping clock "
        "(empty data directory or bad store path)"))
```

---

_Reviewed: 2026-06-15_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
