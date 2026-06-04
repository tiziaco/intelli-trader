---
phase: 01-m1-ignition-lock-the-oracle
reviewed: 2026-06-04T00:00:00Z
depth: standard
files_reviewed: 16
files_reviewed_list:
  - itrader/config/__init__.py
  - itrader/outils/time_parser.py
  - itrader/price_handler/data_provider.py
  - itrader/strategy_handler/SMA_MACD_strategy.py
  - itrader/trading_system/backtest_trading_system.py
  - itrader/order_handler/order_manager.py
  - itrader/order_handler/order_validator.py
  - itrader/execution_handler/execution_handler.py
  - itrader/portfolio_handler/portfolio_handler.py
  - itrader/portfolio_handler/position.py
  - scripts/run_backtest.py
  - test/conftest.py
  - test/test_smoke/test_backtest_smoke.py
  - test/test_integration/test_backtest_oracle.py
  - Makefile
  - .gitignore
findings:
  critical: 2
  warning: 9
  info: 6
  total: 17
status: issues_found
---

# Phase 1: Code Review Report

**Reviewed:** 2026-06-04T00:00:00Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** issues_found

## Summary

This is the M1 ignition phase: make the `SMA_MACD` backtest import, run end-to-end on the
golden CSV, and freeze an oracle. The integration wiring (csv venue alias, BTCUSD symbol
admission, quantity=0 sizing seam) is coherent and well-documented against the deferred-items
ledger. The float-for-money coercion at the fill boundary is the explicitly-accepted DEF-01-A
bridge (flagged Info per instructions).

However, the adversarial pass surfaced two correctness issues that can silently corrupt the
oracle the phase is supposed to freeze, plus a cluster of swallowed-exception and implicit-`None`
return defects in the price-data path that turn data bugs into silently-wrong (not loud) results
— directly contrary to the "trusted-but-verify / fail loud" intent stated in `_load_csv_data`.

The two most serious findings (CR-01, CR-02) both undermine the determinism guarantee that is
the entire point of this phase: a sizing seam that can mis-route a long-only exit, and a megaframe
construction that mis-aligns symbol keys when any frame is dropped. Both should be resolved before
the oracle is blessed, because a frozen-but-wrong oracle regression-locks the bug.

## Critical Issues

### CR-01: Long-only exit sizing can fall through to entry sizing (mis-sized SELL)

**File:** `itrader/order_handler/order_manager.py:267`
**Issue:** The exit branch guards on `open_position.net_quantity > 0`:

```python
if signal_event.action == "SELL" and open_position is not None and open_position.net_quantity > 0:
    signal_event.quantity = open_position.net_quantity
else:
    # Entry (or SELL with no open long): fraction-of-cash sizing.
    signal_event.quantity = (0.95 * portfolio.cash) / price
```

`Position.net_quantity` is defined as `abs(self.buy_quantity - self.sell_quantity)`
(`position.py:93`). It is therefore **never negative** and is `0` for a flat/closed position.
The intent — "size the SELL to fully close the open long" — is only reached when the position
object is both present AND has residual quantity. But the `position_manager.get_position(ticker)`
returned object can be a stale/zeroed position (e.g. a position that has already netted to zero but
not yet been moved to closed, depending on manager timing), in which case `net_quantity == 0`, the
guard is false, and a SELL exit is re-sized via the **entry** fraction-of-cash formula
`(0.95 * cash) / price`. That produces a SELL whose quantity is unrelated to the open long, which
either over-sells (creating an unintended short — which the long-only reference strategy never
wants) or under-sells (leaving the long open). Either path silently changes the trade log the
oracle freezes.

The docstring explicitly claims "Without this the exit SELL would be sized independently and never
net the long to zero" — but the `> 0` guard re-introduces exactly that failure mode for any
edge-case position state where `net_quantity` is 0 while the position is still considered "open".

**Fix:** Key the branch on action + open-long presence, not on a quantity that cannot be negative,
and fail loudly if a SELL exit finds no sizable long rather than silently entering:

```python
open_position = portfolio.get_open_position(signal_event.ticker)
if signal_event.action == "SELL":
    if open_position is None or open_position.net_quantity <= 0:
        return OperationResult.failure_result(
            f"SELL signal for {signal_event.ticker} with no open long to close",
            operation_type="create_primary_order",
        )
    signal_event.quantity = open_position.net_quantity
else:
    signal_event.quantity = (0.95 * portfolio.cash) / price
```

### CR-02: `to_megaframe` mis-aligns symbol keys when a frame is skipped

**File:** `itrader/price_handler/data_provider.py:350-357`
**Issue:**

```python
df_list = []
for symbol in self.available_symbols:
    df = self.get_resampled_bars(time, symbol, tf_delta, window)
    df.name = symbol
    if df.index.tz is not None:        # <-- conditionally appends
        df_list.append(df)
megaframe = pd.concat(df_list, axis=1, keys=self.prices.keys())  # <-- uses ALL keys
```

`df_list` is built conditionally (only tz-aware frames are appended), but `pd.concat` is given
`keys=self.prices.keys()` — the **full, unfiltered** key set. If any symbol's frame is skipped
(tz-naive, or `get_resampled_bars` returned a short/empty frame), the number of frames in `df_list`
no longer matches the number of keys, so pandas either raises `ValueError: Length mismatch` or — worse
— silently pairs frames with the *wrong* symbol keys, mislabeling one symbol's OHLCV under another
symbol's name. For a screener/multi-symbol path this produces silently-wrong data feeding strategy
decisions. Even in the single-symbol golden path, the key/frame coupling is fragile and incorrect by
construction.

**Fix:** Track keys alongside frames so they cannot drift:

```python
df_list, keys = [], []
for symbol in self.available_symbols:
    df = self.get_resampled_bars(time, symbol, tf_delta, window)
    df.name = symbol
    if df.index.tz is not None:
        df_list.append(df)
        keys.append(symbol)
megaframe = pd.concat(df_list, axis=1, keys=keys)
```

## Warnings

### WR-01: Bare `except:` swallows everything in `get_last_close` / `get_bar`

**File:** `itrader/price_handler/data_provider.py:227`, `itrader/price_handler/data_provider.py:253`
**Issue:** Both methods use a bare `except:` (no exception type). This catches `KeyboardInterrupt`,
`SystemExit`, and `MemoryError`, and masks the real cause (e.g. a malformed index, a tz mismatch,
a missing column) behind a generic "not found" log and a `None` return. In a phase whose whole goal
is "fail loud, never silently wrong," these are exactly the swallows that turn a data defect into a
mysterious downstream `NoneType` crash far from the cause.
**Fix:** Catch the specific lookup error and let everything else propagate:

```python
try:
    return self.prices[ticker].iloc[-1]['close']
except (KeyError, IndexError):
    self.logger.error('Price data for %s not found', ticker)
    return None
```

### WR-02: Implicit `None` returns on the error path of price getters

**File:** `itrader/price_handler/data_provider.py:231`, `itrader/price_handler/data_provider.py:257`, `itrader/price_handler/data_provider.py:280-282`
**Issue:** `get_last_close`, `get_bar`, and `get_bars` log an error on the "ticker not found"
branch but then fall off the end of the function, implicitly returning `None`. Callers that index
into the result (e.g. `prices[ticker].loc[...]`, `.iloc[-1]`, arithmetic on a price) get an opaque
`TypeError: 'NoneType' is not subscriptable` instead of a clear failure. `get_bars` in particular is
typed `-> pd.DataFrame` but returns `None`, which violates its own contract and the project's
fail-loud intent.
**Fix:** Either raise a clear `NotFoundError`/`KeyError` with the ticker, or return an explicit empty
frame; do not silently return `None` from a `-> pd.DataFrame` method.

### WR-03: MACD trigger reads `iloc[-2]` without guaranteeing two values

**File:** `itrader/strategy_handler/SMA_MACD_strategy.py:68`
**Issue:** The buy/sell triggers read `MACDhist.iloc[-1]` and `MACDhist.iloc[-2]`. `MACDhist` is
`MACD(...).macd_diff().dropna()`. The bar-count guard at the top is `len(bars) < self.max_window`
(100), but `macd_diff` consumes `SLOW + WIN` (12 + 3) leading bars to NaN before producing values,
and `dropna()` removes them. On the first eligible bar this generally leaves >2 values, but the guard
does not *prove* `len(MACDhist) >= 2`; any change to windows or a short/gappy resampled frame yields
`IndexError` from `iloc[-2]`. Similarly `short_sma`/`long_sma` are `.dropna()`-ed and then indexed at
`iloc[-1]` with no length check.
**Fix:** Add an explicit guard before the triggers:

```python
if len(MACDhist) < 2 or short_sma.empty or long_sma.empty:
    return
```

### WR-04: `round_timestamp_to_frequency` double-applies timezone

**File:** `itrader/outils/time_parser.py:170-174`
**Issue:**

```python
rounded_timestamp = datetime.fromtimestamp(rounded_timestamp_unix)   # naive, LOCAL tz
...
rounded_timestamp = my_timezone.localize(rounded_timestamp)          # asserts it is config.TIMEZONE
```

`datetime.fromtimestamp` (no `tz=`) interprets the epoch seconds in the machine's **local**
timezone and returns a naive datetime; `localize` then *reinterprets* those wall-clock numbers as
`config.TIMEZONE`. On any host whose local tz differs from `config.TIMEZONE`, the result is wrong by
the offset between them — a non-deterministic, host-dependent timestamp, which is poison for a
determinism-locked engine. Not on the daily golden path today, but a latent correctness/determinism
bug.
**Fix:** Build the timestamp in UTC and convert:

```python
rounded = datetime.fromtimestamp(rounded_timestamp_unix, tz=timezone.utc)
return rounded.astimezone(pytz.timezone(config.TIMEZONE))
```

### WR-05: `available_symbols` returns `dict_keys`, typed as `list`

**File:** `itrader/price_handler/data_provider.py:83-85`
**Issue:** `available_symbols` is annotated `-> list` but returns `self.prices.keys()` (a live
`dict_keys` view). It is used in `in` membership checks (fine) but also fed to `to_megaframe`'s
`keys=self.prices.keys()` and could be passed to APIs expecting an indexable list. A live view also
reflects later mutations of `self.prices`, which can surprise callers iterating it.
**Fix:** `return list(self.prices.keys())`.

### WR-06: Fraction-of-cash entry sizing ignores the per-position exposure limit

**File:** `itrader/order_handler/order_manager.py:272`
**Issue:** Entry sizing is `(0.95 * portfolio.cash) / price`, i.e. ~95% of cash into a single
position. The validator's `_check_portfolio_exposure_limits` (`order_validator.py:407`) defines a
20% max-single-position exposure but emits only a **WARNING**, so a 95%-of-cash entry passes
validation and the warning is logged-and-ignored. The sizing logic and the stated risk limit are in
direct conflict; for a multi-position strategy this silently over-concentrates. Acceptable for the
long-only single-symbol oracle, but the mismatch is a latent risk-control defect worth recording.
**Fix:** Either make the sizing respect `max_single_position_exposure`, or document explicitly that
the 95% sizing is intentional for the single-symbol reference run and the 20% check is advisory only.

### WR-07: Cash check skipped whenever ticker already has a position, even for adds

**File:** `itrader/order_handler/order_validator.py:459-460`
**Issue:** `_check_cash_availability` only validates funds when `signal.ticker not in
portfolio.positions`. The intent is "don't cash-check a closing SELL," but the condition keys on
*ticker presence*, not on whether the signal actually closes the position. A BUY that *adds* to an
existing long for a ticker already in `positions` bypasses the cash/cost check entirely, allowing an
over-budget add to slip through to the exchange (where it may then be rejected, producing a REFUSED
fill and noise). For the long-only reference strategy adds don't occur, but the gate is logically
wrong.
**Fix:** Gate on the closing-side test already implemented in `_is_closing_position`, not on bare
ticker membership:

```python
position = portfolio.positions.get(signal.ticker)
if position is None or not self._is_closing_position(signal, position):
    # run cash/cost checks
```

### WR-08: `get_resampled_bars` head/tail window can return a short frame silently

**File:** `itrader/price_handler/data_provider.py:317-326`
**Issue:** In the resample branch it returns `resample_ohlcv(...).head(window)`; in the same-tf
branch it returns a label slice `self.get_bars(ticker, start_dt, time)` with no guarantee of exactly
`window` rows. Near the start of the dataset (or after a gap) this yields fewer than `window` bars,
which the strategy's `len(bars) < self.max_window` guard catches — but only if the frame is non-empty
and indexable. Combined with WR-02 (`get_bars` can return `None`), a `None` or short frame flows into
`SMAIndicator`/`MACD` and produces either an exception or a silently-truncated indicator. The window
math (`start_dt = time - (timeframe * window) + timeframe`) also assumes contiguous bars; a missing
bar shifts the slice.
**Fix:** Validate the returned frame length/non-None before handing it to indicators, or have
`get_resampled_bars` raise when it cannot produce a usable window.

### WR-09: `set_timeframe` can produce `None` timeframe string

**File:** `itrader/price_handler/data_provider.py:368-370` (with `time_parser.py:107`)
**Issue:** `set_timeframe` sets `self.timeframe = timedelta_to_str(min_timeframe)`.
`timedelta_to_str` returns `None` for a zero/empty delta (`time_parser.py:107`). A `None` timeframe
then flows into `to_timedelta(self.timeframe)` in `get_resampled_bars`/`load_data`, where the regex
`re.match(..., None)` raises `TypeError`. Not triggered on the golden 1d path (min is a real
timedelta), but it is an unguarded `None` propagation that the M1-03 fail-loud work in `to_timedelta`
does not cover (that fix handles bad units, not `None` input).
**Fix:** Assert/raise in `set_timeframe` when `timedelta_to_str` returns `None`.

## Info

### IN-01: Accepted float-for-money coercion bridge (DEF-01-A)

**File:** `itrader/portfolio_handler/portfolio_handler.py:267`, `itrader/portfolio_handler/position.py:84`, `itrader/portfolio_handler/position.py:86`
**Issue:** `float(fill_event.commission)` and `float(self.buy_commission)` / `float(self.sell_commission)`
coerce Decimal money into float to keep the float-based transaction/position math consistent. This is
a float-for-money usage, which CLAUDE.md normally classifies as a correctness defect — but it is the
explicitly KNOWN and accepted DEF-01-A bridge to M4 (per `deferred-items.md`), so it is recorded as
Info, not Critical. **Must be reconciled when M4 moves money to Decimal end-to-end.**
**Fix:** No action this phase; track the M4 reconciliation.

### IN-02: Flat-config module loaded by file path at import time

**File:** `itrader/config/__init__.py:58-72`
**Issue:** The package executes the shadowed flat `config.py` via `importlib.util` by absolute file
path to re-export `FORBIDDEN_SYMBOLS`/`TIMEZONE`/`Config`. This works but is fragile (path-dependent,
re-executes module side effects, bypasses normal import caching) and is explicitly a minimal M1-01
bridge deferred to M2-06.
**Fix:** No action this phase; the real config collapse is M2-06. Recorded for tracking.

### IN-03: SMA strategy uses stdlib logging instead of the project structlog convention

**File:** `itrader/strategy_handler/SMA_MACD_strategy.py:8-9`
**Issue:** `logger = logging.getLogger('TradingSystem')` deviates from the project convention
(`get_itrader_logger().bind(component="...")`). The module-level logger is also unused in the body.
**Fix:** Drop the unused logger or align with the structlog convention.

### IN-04: Large commented-out dead code blocks

**File:** `itrader/strategy_handler/SMA_MACD_strategy.py:78-84`, `itrader/strategy_handler/strategies_handler.py:54-58`, `itrader/strategy_handler/strategies_handler.py:73-74`
**Issue:** The SHORT-signal block in the strategy and the `on_portfolio_update` block in the handler
are commented out. The long-only short-block is load-bearing context for CR-01's "long-only" claim,
so a comment pointer is fine, but the dead handler method and "TEMPORARY" assign_symbol path are
noise.
**Fix:** Remove or convert to a short explanatory comment.

### IN-05: `check_timeframe` computes a float modulus from integer-minute frequency

**File:** `itrader/outils/time_parser.py:31`, `itrader/outils/time_parser.py:37`
**Issue:** `frequency_minutes = frequency.total_seconds() // 60` yields a float; `current_minutes %
frequency_minutes` then does float modulo. Correct for clean daily/hourly frequencies but float
modulo invites edge rounding for sub-minute or fractional frequencies. Minor; outside the golden
path.
**Fix:** Use integer seconds throughout (`int(frequency.total_seconds())`).

### IN-06: `print()` used for backtest duration instead of the bound logger

**File:** `itrader/trading_system/backtest_trading_system.py:107`
**Issue:** `print("Backtest duration:", duration)` bypasses the structlog logger used everywhere else
in the class (`self.logger`). Minor consistency issue.
**Fix:** `self.logger.info('Backtest duration: %s', duration)`.

---

_Reviewed: 2026-06-04T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
