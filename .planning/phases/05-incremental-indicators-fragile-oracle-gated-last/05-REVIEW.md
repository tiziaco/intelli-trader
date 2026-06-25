---
phase: 05-incremental-indicators-fragile-oracle-gated-last
reviewed: 2026-06-25T00:00:00Z
depth: standard
files_reviewed: 24
files_reviewed_list:
  - itrader/price_handler/feed/bar_feed.py
  - itrader/price_handler/feed/base.py
  - itrader/price_handler/feed/cache_registration.py
  - itrader/strategy_handler/base.py
  - itrader/strategy_handler/indicators/__init__.py
  - itrader/strategy_handler/indicators/catalog.py
  - itrader/strategy_handler/indicators/handle.py
  - itrader/strategy_handler/pair_base.py
  - itrader/strategy_handler/strategies/SMA_MACD_strategy.py
  - itrader/strategy_handler/strategies/eth_btc_pair_strategy.py
  - itrader/strategy_handler/strategies_handler.py
  - perf/runners/run_w2_sweep.py
  - perf/strategies/a_bracketed_momentum.py
  - perf/strategies/b_limit_maker.py
  - perf/strategies/c_pyramiding_trend.py
  - perf/strategies/d_short_zscore.py
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
  warning: 6
  info: 5
  total: 12
status: resolved
fix:
  applied: 10
  skipped: 2
  mode: "--fix --all --auto"
  iterations: 2
  oracle_byte_exact: true
  final_equity: 46189.87730727451
---

> **FIX STATUS (--fix --all --auto, 2 iterations):** All 10 in-scope code findings
> applied across 9 atomic commits (`f6135af` CR-01+IN-03, `2bb0e16` WR-01,
> `a3e6cba` WR-02, `f51d9d0` WR-03, `357b85e` WR-04, `b3ec303` WR-05, `82fc036`
> WR-06, `d6fdf5e` IN-01, `51884a9` IN-02). IN-04 and IN-05 intentionally skipped
> (reviewer marked "no change required"). Iteration-2 re-review confirmed every
> Critical/Warning RESOLVED with zero new findings. SMA_MACD oracle byte-exact
> at final_equity 46189.87730727451 (3 oracle + 127 strategy/integration + 3
> feed-cache tests green); all new guards are dormant on the golden happy path.

# Phase 05: Code Review Report

**Reviewed:** 2026-06-25
**Depth:** standard
**Files Reviewed:** 24
**Status:** issues_found

## Summary

Phase 05 converts the strategy indicators to O(1) stateful recurrences (Model B
push contract), removes the per-tick `feed.window()` slice in favour of an
`update(ticker, bar) -> is_ready -> generate_signal` flow, and replaces the
per-tick `searchsorted` in `BacktestBarFeed.window()` with a monotonic int64
forward cursor. The byte-exact SMA_MACD oracle (final_equity
46189.87730727451) constrains every change.

The hot-path correctness work is sound and I verified it directly:

- The per-symbol state swap/restore (`Strategy._activate_ticker`) aliases the
  live `(state, buffer)` into `_handle_state_store` via `fresh_state()` /
  `load_state`, so `is_ready` reads the *live* mutated state object — the
  save-on-switch / mint-on-first / load-stored arms all preserve independent
  per-symbol readiness. No state cross-contamination between tickers in the same
  tick.
- The monotonic forward cursor in `window()`: `while iv_i8[pos] <= cutoff_i8`
  reproduces `searchsorted(side="right")` exactly on monotonic non-decreasing
  cutoffs (including the `cutoff == last_cut` equal case), and a backwards/jumped
  cutoff safely full-rebuilds via `searchsorted`. The tz-aware assert restores a
  loud-fail backstop on both branches. Look-ahead safety and determinism are
  preserved.
- The four indicator recurrences (SMA running-sum, factored EMA, MACD, RSI)
  match the convergence-test contracts.

Findings are concentrated in **edge-case robustness currently masked by the
golden config**: a non-finite indicator input that silently poisons a recurrence
(the one BLOCKER), an empty-frame crash at wiring, an unguarded list index in a
perf coverage strategy, and several silent-failure / unsafe-default issues. None
of the BLOCKER/WARNING items perturb SMA_MACD at its pinned config — they are
dormant on the happy path — but each is a real defect that fires on the next
strategy or dataset.

## Critical Issues

### CR-01: Indicator recurrences silently propagate NaN/Inf, poisoning all downstream output while `is_ready` stays GREEN

**File:** `itrader/strategy_handler/indicators/catalog.py:113` (`_SMAState.update`), `:152` (`_EMAState.update`), `:238` (`_RSIState.update`)

**Issue:** None of the four stateful recurrences validate their input. A single
`NaN` or `Inf` close — a real data-quality event (a malformed CSV row, a gap
filled with `inf`, an upstream `0/0`) — permanently poisons the O(1) state and
is unrecoverable for the rest of the run:

- `_SMAState`: `self._sum += x` (line 115). Once `x` is `NaN`, `self._sum` is
  `NaN` forever — subtracting the finite evicted value (line 118) never clears
  it, so `self.value` is `NaN` for every later bar.
- `_EMAState`: `self.value += alpha * (x - self.value)` (line 156) propagates
  `NaN`/`Inf` identically and never recovers.
- `_MACDHistState`: inherits the poisoning through `_fast`/`_slow`/`_signal`.

The fatal part is the silent gate: `is_ready` checks only `count >= n` (line 130
/ 164 / 267), so it stays `True` on a poisoned state. `StrategiesHandler.
calculate_signals` then passes the gate (`base.py:141`) and calls
`generate_signal`, which reads a `NaN` indicator. Every `crossover`/`is_above`
comparison against `NaN` is `False`, so the strategy **silently stops trading
with no error**. It is also a determinism hazard: `NaN != NaN`, so a poisoned run
is not even self-consistent for the byte-exact equality the oracle depends on.

This contradicts the project's loud-rejection error policy that is applied
*everywhere else on the decision path* — `base.py` IN-02 rejects malformed
`tickers`, `eth_btc_pair_strategy._fit_beta` (line 143) rejects a non-finite β,
and `evaluate_pair` (line 257) rejects a non-finite z. The indicator layer — the
layer most exposed to raw market data — is the only one with no non-finite guard.

**Fix:** Reject non-finite input at the recurrence boundary so a bad bar fails
loudly at the source instead of silently zeroing out all future signals:

```python
import math

def update(self, x: float) -> None:
    if not math.isfinite(x):
        raise ValueError(
            f"{type(self).__name__} received non-finite input {x!r} — "
            "a NaN/Inf close permanently poisons the O(1) recurrence "
            "(silent dead strategy / non-deterministic run)")
    # ... existing body
```

Apply to all four `*State.update`. If a non-finite close is meant to be a
"skip this tick" case instead, the skip must be made explicit in
`Strategy.update` / the handler — but today `update` is called unconditionally
once the bar is present, so the guard must live in the recurrence.

## Warnings

### WR-01: `BacktestBarFeed.__init__` crashes with a bare IndexError on an empty store frame

**File:** `itrader/price_handler/feed/bar_feed.py:246-252`

**Issue:** The wiring loop does
`self._spans[ticker] = (frame.index[0], frame.index[-1])` (line 248). If
`store.read_bars(ticker)` returns an empty frame — a real possibility for a
sparse universe or a mis-keyed CSV — `frame.index[0]` raises a bare `IndexError`
with no diagnostic naming the offending ticker. `_resampled_frame` (line 359)
has the same exposure if a `resample` yields an empty result.

**Fix:** Guard the empty case with a typed, ticker-named error:

```python
frame = _readonly_master(store.read_bars(ticker))
if frame.empty:
    raise MissingPriceDataError(ticker, "store returned an empty frame for ticker")
self._frames[(ticker, self._base_alias)] = frame
self._spans[ticker] = (frame.index[0], frame.index[-1])
```

### WR-02: `c_pyramiding_trend` reads `recent_closes()[-1]` without a length guard

**File:** `perf/strategies/c_pyramiding_trend.py:71-73`

**Issue:**
```python
closes = self.recent_closes(ticker)
close = float(closes[-1])               # <- unguarded
prev = float(closes[-2]) if len(closes) >= 2 else close
```
`[-2]` is guarded but `[-1]` is not. The strategy has SMA(20)/SMA(50)
indicators, so `is_ready` gates at 50 bars and `recent_closes` is non-empty by
then on the happy path — but the safety depends on a cross-module invariant
(`is_ready` implies `recent_closes` non-empty). The asymmetric guard (`[-2]`
checked, `[-1]` not) signals uncertainty about that invariant; if `max_window`
were ever 0 for an indicator-bearing strategy, or warmup and the close buffer
diverged, this is an `IndexError`.

**Fix:** Guard both up front, matching `run_w2_sweep._TrivialBuyStrategy` and
`d_short_zscore` which both `if len(closes) < N: return None` first:

```python
closes = self.recent_closes(ticker)
if len(closes) < 2:
    return None
close = float(closes[-1])
prev = float(closes[-2])
```

### WR-03: `_zscore` helper emits Inf/NaN on a zero-variance window; the guard lives one frame away in the caller

**File:** `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py:171-175`

**Issue:** `_zscore` returns `(spread - rolling_mean) / rolling_std` with no
zero-std handling. A zero-variance window yields `±inf`/`NaN`. The caller
`evaluate_pair` *does* guard the final value (line 257, the WR-04 non-finite
check), but the reusable helper itself produces the hazard silently. A future
caller or subclass that reuses `_zscore` and forgets the caller-side guard
inherits exactly the spurious-entry defect the WR-04 comment describes. Safety is
silently caller-dependent, against the engine's guard-at-source philosophy.

**Fix:** Either move the non-finite handling into `_zscore` so the contract is
local, or add a prominent "may return non-finite; callers MUST guard" line to
its docstring (it currently gives no such warning).

### WR-04: The "β fits the first `beta_warmup` dataset bars" guarantee is enforced only on the subclass, not the `PairStrategy` base

**File:** `itrader/strategy_handler/pair_base.py:99-130` (`PairStrategy.validate`) vs `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py:96-105`

**Issue:** `EthBtcPairStrategy.validate` (WR-01 there) asserts
`max_window == beta_warmup + z_lookback` *exactly*, because β is fit once over
`win_A[:beta_warmup]` and a larger `max_window` would slide the fit window off
dataset-start once history accrues, quietly changing β. But the base
`PairStrategy.validate` only asserts `max_window >= beta_warmup + z_lookback`
(line 124). A second pair subclass that sets `max_window` larger and forgets to
re-assert exact-equality silently fits β on a sliding window — a correctness
defect with no error. The integrity of the frozen-β alpha rests on every future
subclass remembering to override.

**Fix:** Pull the invariant into the base: tighten `PairStrategy.validate` to
`==`, or have `pair_base._run_init` (which already sizes the buffer to exactly
`beta_warmup + z_lookback`, line 149) own the "β fits the oldest `beta_warmup`
of a fixed-width buffer" contract so it cannot be re-litigated per subclass. If
the base intentionally allows `>`, document why.

### WR-05: `run_w2_sweep` opens JSON files with no explicit encoding and overstates its determinism contract

**File:** `perf/runners/run_w2_sweep.py:217`, `:236`; docstring `:11`, `_SEED` `:37`

**Issue:** `_write_w2_baseline` and `_check_w2` use bare `open(path, "w")` /
`open(baseline_path)` with no `encoding=`; under a non-UTF-8 locale the baseline
JSON round-trip can corrupt or fail. Separately, the module docstring claims
"Determinism: seed 42 throughout" and `_SEED = 42`, but the seed is only passed
to `make_synthetic_ohlcv`; the backtest's reproducibility depends on
`performance.rng_seed` (default 42) which `_wire_system` never sets explicitly.
If that default ever changes, the "throughout" claim silently breaks and the W2
baseline drifts — a perf-gate integrity issue, not a perf-speed one.

**Fix:** Use `open(..., encoding="utf-8")` for both read and write; either
explicitly set/assert the backtest `rng_seed` in `_wire_system` or soften the
docstring to "synthetic-frame seed 42; backtest determinism via the default
`performance.rng_seed`."

### WR-06: `cache_registration.derive` silently floors invalid (<1) consumer depths instead of rejecting them

**File:** `itrader/price_handler/feed/cache_registration.py:84` (`derive_required_depths`), `:118` (`derive`)

**Issue:** `RawBarConsumer.required_history_depth` is documented `>= 1` (line
61), but `derive` never validates it: `max(NEWEST_BAR_ONLY, *depths)` silently
floors a consumer declaring `0` or a negative depth to `1`. A consumer that
mis-declares its history requirement (a real bug in the consumer) is masked —
the shared cache is undersized and the consumer reads missing/stale bars with no
error. The engine rejects malformed declarations loudly elsewhere
(`base.py` IN-02); a malformed depth should too.

**Fix:** Validate each declared depth at derive time:

```python
def derive_required_depths(consumers):
    depths = set()
    for c in consumers:
        d = c.required_history_depth
        if d < 1:
            raise ValueError(
                f"raw-bar consumer {c!r} declared required_history_depth={d} "
                "(must be >= 1)")
        depths.add(d)
    return sorted(depths)
```

## Info

### IN-01: `_RowBar.__getattr__` turns a typo'd `input_col` into a deep, confusing KeyError

**File:** `itrader/strategy_handler/base.py:47-50`

**Issue:** `_RowBar.__getattr__` returns `self._row[name]` for any attribute not
in `__slots__`. A typo'd declared `input_col` (e.g. `"clse"`) raises a pandas
`KeyError` from inside the legacy `evaluate` replay, far from the declaration
site. Low impact (legacy/test-only seam) but a debugging footgun.

**Fix:** Catch the `KeyError` and re-raise naming the column and that it is the
declared `input_col`.

### IN-02: Redundant `Decimal(str(bar.close))` where `bar.close` is already Decimal

**File:** `perf/strategies/b_limit_maker.py:74`, `perf/strategies/a_bracketed_momentum.py:86`

**Issue:** `Bar.close` is already a `Decimal` (Bar struct, D-14). `Decimal(str(
bar.close))` round-trips through `str` needlessly. Value-identical, but obscures
intent — `b_limit_maker` puts it next to `Decimal(str(self.ma[-1]))` where
`self.ma[-1]` IS a float (correct there), so two visually-identical lines mean
different things and only one conversion is necessary.

**Fix:** Use `bar.close` directly; reserve `Decimal(str(...))` for genuine float
values (`self.ma[-1]`).

### IN-03: `assert`-for-invariant inside the indicator hot path is stripped under `-O`

**File:** `itrader/strategy_handler/indicators/catalog.py:193`, `:197`

**Issue:** `_MACDHistState.update` uses `assert fast_v is not None and slow_v is
not None` / `assert signal_v is not None` for the "seeded from bar 0" invariant.
Under `-O`/`PYTHONOPTIMIZE` these vanish and a regression would surface as a
confusing `TypeError` on `None - None`. The codebase elsewhere deliberately uses
explicit `raise` for runtime contracts (handle.py WR-01, base.py `_intent`,
`_emit_intent` WR-02) to survive `-O`. The asserts are true by construction so
impact is nil — recorded for convention consistency. (The documented debug-only
re-entrancy assert at `base.py:576` is intentional and fine.)

**Fix:** Leave as pure internal invariants, or convert to a narrow `raise` to
match the file's own discipline.

### IN-04: `_offset_alias` `functools.cache` is process-global, never-evicting shared state

**File:** `itrader/price_handler/feed/bar_feed.py:86-87`

**Issue:** `@functools.cache` keyed by `timedelta` never evicts and is shared
across every `BacktestBarFeed` instance and test. The distinct-timeframe count
is tiny, so this is not a leak of concern (and perf is out of v1 scope); recorded
only because it introduces process-global mutable state. Behaviorally correct
(the map is pure, and the function correctly does NOT cache its ValueError since
`functools.cache` never caches exceptions).

### IN-05: `derive`'s default empty-tuple argument is a borderline mutable-default pattern

**File:** `itrader/price_handler/feed/cache_registration.py:87`

**Issue:** `def derive(consumers: Iterable[RawBarConsumer] = ()) -> int`. An
empty tuple is immutable so this is safe, but the project's `base.py:223-227`
established a strict "deep-copy any non-immutable default" rule; using a literal
`()` default is fine here but worth a glance against that convention. No change
required — documenting that it was checked and is safe.

---

_Reviewed: 2026-06-25_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
