---
phase: 06-pair-trading-flagship
reviewed: 2026-06-22T00:00:00Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - itrader/strategy_handler/pair_base.py
  - itrader/strategy_handler/strategies/eth_btc_pair_strategy.py
  - itrader/strategy_handler/strategies_handler.py
  - tests/integration/test_pair_exit_safety.py
  - tests/integration/test_pair_flagship_snapshot.py
  - tests/unit/strategy/test_pair_dispatch.py
  - tests/unit/strategy/test_pair_strategy.py
findings:
  critical: 2
  warning: 6
  info: 4
  total: 12
status: issues_found
---

# Phase 6: Code Review Report

**Reviewed:** 2026-06-22
**Depth:** standard
**Files Reviewed:** 7
**Status:** issues_found

## Summary

Reviewed the Phase 6 pair-trading flagship: the `PairStrategy` two-leg base, the
concrete `EthBtcPairStrategy` (β-fit / z-score / crossing alpha), the
`StrategiesHandler._dispatch_pair` branch, and the four test modules. The
two-leg dispatch, β-weighted entry construction, and the close-only/safe-when-flat
exit property are well-documented and largely sound. The β/z math reproduces the
inline statsmodels oracle in `test_pair_strategy.py`, and the snapshot already
generated a plausible trade log (47 LONG / 47 SHORT round trips with the expected
short-ETH/long-BTC-on-z>0 orientation).

However the review surfaced two correctness defects that can produce wrong or
non-reproducible behavior, plus several robustness and test-rigor gaps. The most
serious is a **negative-β path that silently produces a negative entry quantity**
(latent NaN/negative-quantity bug, dormant only because ETH/BTC β≈0.53), and a
**determinism risk in the `coint()` diagnostic** that the double-run test does not
actually protect against because of the auto-generate-on-first-run snapshot
mechanic. Details below.

## Critical Issues

### CR-01: Negative β silently produces a negative β-weighted entry quantity

**File:** `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py:214` (and `pair_base.py:165-190`)
**Issue:** β is the raw OLS slope of `log(ETH)` on `log(BTC)` and is `float`-typed
with no sign guard. The entry leg-B quantity is computed as:

```python
qty_B = self.entry_units * to_money(beta)   # β·N
```

`to_money(beta)` is `Decimal(str(beta))`, which faithfully preserves a **negative**
slope. A negative `qty_B` then flows into `_entry(ticker_B, Side.BUY, qty_B)`, which
does `quantity=to_money(quantity)` — so a `SignalIntent` is constructed with a
**negative `quantity`**. `SignalIntent.__post_init__` only validates `exit_fraction`,
not `quantity`, so the negative value passes through to the `SignalEvent` and into
the sizing resolver / admission layer, where a negative quantity is undefined
behavior (a SELL-shaped magnitude carried on a BUY action, or a downstream sign
error in notional/margin math). For two genuinely cointegrated, positively-correlated
assets β is positive, but OLS does NOT guarantee `β > 0` for an arbitrary pair, and
nothing in `_fit_beta`, `validate()`, or `_entry` rejects it. The defect is dormant
ONLY because the pinned ETH/BTC β≈0.53; a reconfigure to another pair (the strategy
is explicitly designed to be reusable — `entry_units`, `tickers`, knobs are all
overridable) can hit it.

A closely related sub-case: if `_fit_beta` returns `nan`/`inf` (degenerate warmup
window, e.g. a constant-price leg making `add_constant` rank-deficient), `to_money(nan)`
yields `Decimal("nan")` and `qty_B` becomes `Decimal("NaN")`, poisoning the Decimal
money domain (every downstream comparison with `NaN` is False, breaking admission gates).

**Fix:** Guard the fitted β at the boundary and use `abs(beta)` for the magnitude
(the long/short *direction* is already chosen by the z-sign, so β should only ever
contribute a positive *weight*):

```python
def _fit_beta(self, win_A, win_B) -> float:
    log_A = np.log(win_A["close"].to_numpy(dtype=float)[: self.beta_warmup])
    log_B = np.log(win_B["close"].to_numpy(dtype=float)[: self.beta_warmup])
    X = sm.add_constant(log_B)
    beta = float(sm.OLS(log_A, X).fit().params[1])
    if not math.isfinite(beta) or beta <= 0:
        raise ValueError(
            f"degenerate hedge ratio for {self.tickers}: β={beta!r} "
            f"(expected finite and > 0; a non-positive/NaN β cannot weight a leg)"
        )
    return beta
```

If a negative β is a legitimate regime for some future pair, then `qty_B` must use
`abs(beta)` AND the BUY/SELL sides must flip accordingly — but the current code does
neither, so it is wrong for β<0 today.

### CR-02: `coint()` diagnostic introduces uncontrolled RNG; determinism double-run cannot catch it

**File:** `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py:112-122,161` and `tests/integration/test_pair_flagship_snapshot.py:223-246`
**Issue:** `_coint_pvalue` calls `statsmodels.tsa.stattools.coint(...)`. The
Engle-Granger `coint` MacKinnon p-value path is deterministic for fixed inputs, but
`coint` does NOT consume the engine's injected seeded `random.Random` — it is wholly
outside the determinism seam the project relies on (`performance.rng_seed`). The
docstring asserts the run is reproducible "because β enters the Decimal domain only
via to_money," which is the wrong justification: β/p-value reproducibility depends on
statsmodels internals, not on `to_money`. More importantly, the p-value is only
**logged**, so even if it were non-deterministic it would not affect trade output —
but the strategy comment and the determinism test docstring both assert a determinism
guarantee that is not actually established by the cited mechanism.

The deeper problem is the **test does not protect determinism the way it claims.**
`test_pair_flagship_snapshot_matches` GENERATES the snapshot on first run and returns
green (line 184-189), and `tests/golden/pair/{trades,equity}.csv` is already committed
— so on a developer machine the snapshot diff runs, but in any environment where the
two committed CSVs differ from a fresh statsmodels/numpy/BLAS build (different platform
BLAS, numpy minor version) the test fails with no determinism signal, while
`test_pair_flagship_determinism_double_run` (two in-process runs) passes trivially
because both runs share the same BLAS. The determinism claim ("byte-identical") is
therefore only verified WITHIN a process, not the cross-run reproducibility the project
mandates, and the snapshot is platform-fragile (it is a float-derived statsmodels OLS
slope feeding every quantity).

**Fix:** (1) Drop the misleading determinism justification in both docstrings — state
that determinism rests on the seeded RNG + fixed BLAS/statsmodels, and that β is a
deterministic OLS fit on fixed data. (2) Either compute the coint p-value once and
cache it identically to β (it already is — fit-once), or remove it from the run path
entirely and compute it in a separate diagnostic test, so a future statsmodels change
to `coint`'s internals cannot perturb the run. (3) The cross-platform fragility of a
float-OLS-derived snapshot should be acknowledged with a tolerance band or a
`pytest.mark.skipif`/regen guard, OR the diff columns reduced to integer/categorical
keys (entry/exit/side) only — `total_equity` exact-match on a β-scaled float run is
the brittlest possible assertion.

## Warnings

### WR-01: β fit window slides until the first sufficient tick — fit input is not the documented "first 250 bars of the dataset"

**File:** `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py:107-110,158-160`
**Issue:** The docstring says β is fit "over the FIRST `beta_warmup` completed bars
only." But `_fit_beta` slices `[: self.beta_warmup]` of the **handed window**, and the
window is the trailing `max_window`(=280)-bar slice that the feed returns each tick.
β is cached on the first tick where `len(win) >= beta_warmup + z_lookback` (280). On
that tick the window is the first 280 bars of available data, so `[:250]` happens to be
the first 250 dataset bars — correct by coincidence of the gate equalling `max_window`.
But this is fragile: if `max_window` were ever set larger than `beta_warmup + z_lookback`,
the feed would hand a longer trailing window once enough history accrued, and on the
fit tick `[:250]` would be the first 250 bars *of that longer window* — NOT the first
250 dataset bars — quietly changing β. The "first N bars" guarantee is implicit in
`max_window == beta_warmup + z_lookback`, not enforced.
**Fix:** Either assert `max_window == beta_warmup + z_lookback` in `validate()` (not
just `>=`, which `pair_base.py:122` allows), or fit β off a window anchored to dataset
start rather than `[:beta_warmup]` of a trailing slice. At minimum, document that the
"first N bars" property depends on the exact-equality of `max_window`.

### WR-02: `_prev_z` is mutated before the crossing test, breaking idempotency / re-evaluation safety

**File:** `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py:182-183`
**Issue:** `evaluate_pair` does `self._prev_z = curr_z` (line 183) *before* using the
captured `prev_z` for the crossing decision. This is correct for a single linear pass,
but it makes `evaluate_pair` non-idempotent: if the handler ever calls it twice for the
same tick (e.g. a retry, a re-dispatch, or a future multi-portfolio refactor that
re-evaluates), the second call sees `prev_z == curr_z` and can never detect the
crossing — silently dropping a signal. `Strategy.evaluate` is documented as
NOT re-entrant (base.py:296), but the pair path bypasses `evaluate` entirely
(`_dispatch_pair` calls `evaluate_pair` directly), so that single-writer contract is
asserted nowhere for the pair path. The mutation-on-read of `_prev_z`/`_in_pair`/
`_entry_z_sign` is hidden engine state with no guard.
**Fix:** Document the single-call-per-tick precondition on `evaluate_pair` (mirror the
`IN-03` non-re-entrant note in base.py), and consider guarding against double-evaluation
of the same `asof` (e.g. stash the last-evaluated timestamp and no-op on a repeat).

### WR-03: Equality-boundary z exactly at the threshold is silently swallowed

**File:** `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py:130-140`
**Issue:** `_crosses_into` requires `abs(prev) <= t and abs(curr) > t`; `_crosses_inside`
requires `abs(prev) >= t and abs(curr) < t`. A bar where `abs(curr) == entry_z` exactly
is NOT an entry (strict `>`), and a bar where `abs(curr) == exit_z` exactly is NOT an
exit (strict `<`). Because z is `to_money(float(...))` (a Decimal carrying a long float
repr), exact equality is astronomically unlikely on real data, so this is not a live bug
on the flagship — but the asymmetry (`>` for entry vs `<` for exit) means a value sitting
exactly on `exit_z` keeps the position open indefinitely until z moves strictly inside,
which is a defensible-but-undocumented design choice. Worth a one-line comment so it is
not mistaken for an off-by-one later.
**Fix:** Add a comment documenting the strict-inequality band semantics (a z resting
exactly on a threshold is treated as "still outside"), or unify the boundary convention.

### WR-04: `_zscore` divides by rolling std with no zero/NaN guard

**File:** `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py:124-128,178-181`
**Issue:** `(spread - rolling_mean) / rolling_std` divides by `rolling_std`. For a
flat/constant spread window the rolling std is `0`, yielding `inf`/`-inf` (or `NaN` for
0/0). The `pd.isna(curr_raw)` guard at line 179 catches `NaN` but NOT `inf`. An `inf`
z then becomes `to_money(float('inf'))` = `Decimal("Infinity")`, and `abs(curr_z) > entry_z`
is True — firing a spurious entry on a degenerate (zero-variance) window. Unlikely on
log ETH/BTC, but the strategy is reusable and a low-volatility / stablecoin-like leg
makes a flat-spread window realistic.
**Fix:** Guard for non-finite z before the crossing logic:

```python
if pd.isna(curr_raw) or not np.isfinite(curr_raw):
    return None
```

### WR-05: Exit path emits LONG_SHORT-direction quantity-free closes; the close-only safety property is proven only for SHORT_ONLY

**File:** `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py:195-207` and `tests/integration/test_pair_exit_safety.py`
**Issue:** The whole exit design rests on "a quantity-free `exit_fraction=1` close
resolves as close-existing / no-op-when-flat." `test_pair_exit_safety.py` proves this
**only for a `SHORT_ONLY` strategy** (line 67), and its no-op-when-flat proof leans on
the `SHORT_ONLY` direction gate rejecting a flat BUY (`admission_manager.py:441`). The
pair strategy fans its exits out with `direction=LONG_SHORT` (strategies_handler.py:236,
inherited). A `LONG_SHORT` direction does NOT have the same flat-BUY rejection arm, so
the engine-level guarantee the test locks may NOT hold on the actual pair path. The
strategy's own `_in_pair` flag is the only thing preventing a flat-state close on the
pair path — and that flag is in-memory strategy state, exactly the thing the
"engine-level guarantee" was meant to back up. The safety test therefore validates a
different direction than the flagship uses.
**Fix:** Add an integration test that drives the close-only/safe-when-flat property
through a `LONG_SHORT` (pair-shaped) strategy, or document explicitly that on the pair
path safety rests on the strategy's `_in_pair` flag rather than the admission gate.

### WR-06: `entry_units` is annotated but its sign/zero is unvalidated

**File:** `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py:78` and `pair_base.py:97-128`
**Issue:** `entry_units: Decimal = Decimal("1")` is a reconfigurable knob feeding both
leg quantities (`n = self.entry_units`, `qty_B = self.entry_units * to_money(beta)`).
A reconfigure to `entry_units=Decimal("0")` produces a zero-quantity entry (a no-op
order or a downstream `SizingPolicyViolation` deep in the resolver), and a negative
value produces a negative quantity (same defect class as CR-01). `validate()` checks
the pair contract and the z thresholds but never `entry_units > 0`.
**Fix:** Add `_require_positive("EthBtcPairStrategy", "entry_units", self.entry_units)`
(or an inline `> 0` check raising `ValueError`) to the overridden `validate()`.

## Info

### IN-01: Misleading determinism comment in the snapshot test docstring

**File:** `tests/integration/test_pair_flagship_snapshot.py:228-229`
**Issue:** "β enters the Decimal domain only via to_money so the run is reproducible
(Pitfall 4)" — `to_money` makes the *Decimal entry* reproducible, but β reproducibility
comes from the deterministic OLS fit on fixed data, not from `to_money`. The comment
conflates two distinct guarantees (see CR-02).
**Fix:** Reword to attribute reproducibility to the deterministic OLS fit + fixed
seed/BLAS.

### IN-02: Snapshot generates-and-passes on first run, masking a never-verified baseline

**File:** `tests/integration/test_pair_flagship_snapshot.py:184-189`
**Issue:** On a missing snapshot the test writes the CSVs and returns green. This is the
documented "Don't Hand-Roll" pattern, but it means a CI that wipes `tests/golden/pair/`
(or a fresh clone where the snapshot was gitignored) would auto-pass with a brand-new,
unverified baseline rather than failing. The committed CSVs mitigate this, but the
generate-and-pass branch is a silent-acceptance footgun.
**Fix:** Consider failing (not passing) on first generation, requiring an explicit
opt-in env var to regenerate (mirrors common golden-master discipline).

### IN-03: `_coint_pvalue` recomputes the log arrays already computed by `_fit_beta`

**File:** `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py:107-108,119-120`
**Issue:** Both `_fit_beta` and `_coint_pvalue` independently recompute
`np.log(win[...][:beta_warmup])` for both legs. Minor duplication; only runs once
(fit-once), so not a perf concern, but it is two copies of the same windowing/slicing
logic that can drift (e.g. if one is later changed to use a different warmup slice).
**Fix:** Compute `log_A`/`log_B` once in `evaluate_pair` and pass them in, or have
`_coint_pvalue` accept the already-sliced arrays.

### IN-04: `_dispatch_pair` tuple-unpacks `strategy.tickers` assuming exactly two

**File:** `itrader/strategy_handler/strategies_handler.py:275`
**Issue:** `ticker_A, ticker_B = strategy.tickers` relies on `PairStrategy.validate()`
having enforced len-2 at construction. That holds for the supported path, but if a
`PairStrategy` subclass ever overrides `validate()` without calling `super().validate()`
(the base only SHOULD-calls it, pair_base.py:108), this line raises a bare
`ValueError: too many/not enough values to unpack` at dispatch time rather than a clear
contract error. Low risk given the documented convention, noted for robustness.
**Fix:** Optionally assert `len(strategy.tickers) == 2` in `_dispatch_pair` with a
clear message, or rely on the documented super() convention (acceptable as-is).

---

_Reviewed: 2026-06-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
