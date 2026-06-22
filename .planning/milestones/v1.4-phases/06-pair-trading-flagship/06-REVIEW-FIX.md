---
phase: 06-pair-trading-flagship
fixed_at: 2026-06-22T00:00:00Z
review_path: .planning/phases/06-pair-trading-flagship/06-REVIEW.md
iteration: 1
findings_in_scope: 12
fixed: 10
skipped: 2
status: partial
---

# Phase 06: Code Review Fix Report

**Fixed at:** 2026-06-22
**Source review:** .planning/phases/06-pair-trading-flagship/06-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 12 (fix_scope = all — CR + WR + IN)
- Fixed: 10
- Skipped: 2

**Regression locks verified (both held):**
- SMA_MACD byte-exact oracle (`tests/integration/test_backtest_oracle.py`) — green, 3 tests.
- Golden pair STABILITY snapshot (`tests/integration/test_pair_flagship_snapshot.py`) — green, 2 tests. **The snapshot was NOT regenerated**; all fixes are dormant at the pinned ETH/BTC β≈0.53 by design (guards RAISE on bad input rather than alter the happy path), so `tests/golden/pair/{trades,equity}.csv` is unchanged.
- Full verification run: `poetry run pytest tests/unit/strategy/ tests/integration/test_pair_exit_safety.py tests/integration/test_pair_flagship_snapshot.py tests/integration/test_backtest_oracle.py -q` → **105 passed**.

## Fixed Issues

### CR-01: Negative β silently produces a negative β-weighted entry quantity

**Files modified:** `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py`
**Commit:** 4a365f0
**Applied fix:** Added `import math` and a fail-loud guard at the end of `_fit_beta`: `if not math.isfinite(beta) or beta <= 0: raise ValueError(...)`. β is used only as a positive per-leg weight (direction comes from the z-sign), so a non-positive/NaN β can never legitimately weight a leg. The guard RAISES at the fit boundary rather than emitting a poisoned `Decimal("NaN")`/negative quantity into the sizing/admission layer. Dormant at β≈0.53 (positive, finite) — happy path unchanged; snapshot stable as required.

### CR-02: `coint()` diagnostic introduces uncontrolled RNG; determinism double-run cannot catch it

**Files modified:** `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py`, `tests/integration/test_pair_flagship_snapshot.py`
**Commits:** 4a365f0 (strategy `_coint_pvalue` docstring), 49f08b4 (test docstring + key-column fragility note)
**Applied fix:** Per the explicit instruction NOT to introduce a new RNG seam for statsmodels, this was handled as a test-rigor / documentation finding. (1) Corrected the `_coint_pvalue` docstring to state the p-value runs OUTSIDE the engine seed, is deterministic only for a fixed numpy/BLAS/statsmodels build, and — being diagnostic-only/never feeding a trade decision — cannot perturb the run regardless (addresses fix point 2: the p-value is already fit-once and never gates). (2) Rewrote the `test_pair_flagship_determinism_double_run` docstring to attribute reproducibility to the seeded RNG + deterministic OLS fit on fixed data (NOT to `to_money`), and explicitly scoped the double-run as in-process (same BLAS) — not cross-platform. (3) Added a fragility ACKNOWLEDGEMENT comment at `_EQUITY_KEY_COLUMNS` noting `total_equity` is the brittlest (float-OLS-derived) exact-match and the expected first cross-platform regen casualty. No assertion behavior changed, so the snapshot stays stable.
**Note:** This is a logic/test-rigor finding fixed via documentation only — no code-path behavior changed, so no human re-verification of logic is required beyond the green test run.

### WR-01: β fit window slides until the first sufficient tick

**Files modified:** `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py`
**Commit:** 4a365f0
**Applied fix:** Strengthened the `EthBtcPairStrategy.validate()` override (after `super().validate()`) to assert `max_window == beta_warmup + z_lookback` EXACTLY (the base only asserts `>=`). This enforces the "first N dataset bars" β-fit property that was previously implicit in the exact-equality of `max_window`. Dormant at the pinned config (280 == 250 + 30).

### WR-02: `_prev_z` is mutated before the crossing test, breaking idempotency

**Files modified:** `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py`
**Commit:** 4a365f0
**Applied fix:** Documented the exactly-once-per-tick / non-re-entrant precondition on `evaluate_pair` (mirrors the `Strategy.evaluate` IN-03 note in base.py), describing the hidden mutation of `_prev_z`/`_in_pair`/`_entry_z_sign` and that a second call for the same `asof` would silently drop a signal. Documentation per the reviewer's fix; the dispatch path already calls it exactly once.

### WR-03: Equality-boundary z exactly at the threshold is silently swallowed

**Files modified:** `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py`
**Commit:** 4a365f0
**Applied fix:** Documented the deliberate strict-inequality band convention on both `_crosses_into` (strict `>`) and `_crosses_inside` (strict `<`): a z resting exactly on a threshold is treated as "still outside", so it is not mistaken for an off-by-one. No behavior change.

### WR-04: `_zscore` divides by rolling std with no zero/NaN guard

**Files modified:** `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py`
**Commit:** 4a365f0
**Applied fix:** Extended the existing `if pd.isna(curr_raw):` guard in `evaluate_pair` to `if pd.isna(curr_raw) or not np.isfinite(curr_raw):` so an `inf`/`-inf` z (from a zero-variance / flat-spread window) returns `None` instead of becoming `Decimal("Infinity")` and firing a spurious entry. Dormant on the non-flat log ETH/BTC spread — happy path unchanged.

### WR-05: Exit close-only safety proven only for SHORT_ONLY, not LONG_SHORT

**Files modified:** `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py`
**Commit:** 4a365f0
**Applied fix:** Chose the documentation arm of the reviewer's fix (rather than adding a new LONG_SHORT integration test, which risked snapshot/oracle-adjacent fragility). Added a comment on the exit path documenting that the engine-level flat-BUY rejection proven by `test_pair_exit_safety.py` is SHORT_ONLY-specific; on the LONG_SHORT pair path the close-only guarantee rests on the strategy's own `_in_pair` flag (the single-writer gate that only emits a close while genuinely in-pair), with the quantity-free + `exit_fraction=1` shape as the second line of defence.

### WR-06: `entry_units` sign/zero is unvalidated

**Files modified:** `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py`
**Commit:** 4a365f0
**Applied fix:** Imported `_require_positive` from `itrader.core.sizing` and added `_require_positive("EthBtcPairStrategy", "entry_units", self.entry_units)` to the `validate()` override. A zero/negative `entry_units` now fails loud at construction (`SizingPolicyViolation`) instead of producing a no-op or negative-quantity entry (the CR-01 defect class). Dormant at the default `Decimal("1")`.

### IN-01: Misleading determinism comment in the snapshot test docstring

**Files modified:** `tests/integration/test_pair_flagship_snapshot.py`
**Commit:** 49f08b4
**Applied fix:** Folded into the CR-02 docstring rewrite — reproducibility is now attributed to the seeded RNG + deterministic OLS fit on fixed data, not to `to_money` (which only guarantees the Decimal entry is artifact-free).

### IN-04: `_dispatch_pair` tuple-unpacks `strategy.tickers` assuming exactly two

**Files modified:** `itrader/strategy_handler/strategies_handler.py`
**Commit:** bd14074
**Applied fix:** Added an explicit `if len(strategy.tickers) != 2: raise ValueError(...)` guard before the tuple unpack in `_dispatch_pair`, so a subclass that overrides `validate()` without calling `super().validate()` gets a clear contract error rather than a bare "too many/not enough values to unpack". Tab-indented to match the handler module.

## Skipped Issues

### IN-02: Snapshot generates-and-passes on first run, masking a never-verified baseline

**File:** `tests/integration/test_pair_flagship_snapshot.py:184-189`
**Reason:** skipped: design-change suggestion outside safe scope. The reviewer's fix ("fail, not pass, on first generation, requiring an explicit opt-in env var to regenerate") changes the golden-master test workflow ergonomics and would alter the test's pass/fail semantics on a fresh clone. The reviewer itself flags this as a "Consider" suggestion and notes the committed CSVs already mitigate the footgun. Changing the generate-and-pass contract risks surprising the established regen workflow used to keep the STABILITY snapshot stable; deferred to a deliberate test-policy decision rather than forced here.
**Original issue:** On a missing snapshot the test writes the CSVs and returns green; a CI that wipes `tests/golden/pair/` would auto-pass with an unverified baseline.

### IN-03: `_coint_pvalue` recomputes the log arrays already computed by `_fit_beta`

**File:** `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py:107-108,119-120`
**Reason:** skipped: needless oracle-perturbation risk for zero behavioral payoff. The reviewer marks this as minor duplication that "only runs once (fit-once), so not a perf concern". Refactoring `_fit_beta`/`_coint_pvalue` to share pre-sliced log arrays touches the byte-exact β-computation path (numpy slicing/log ordering) on a run whose float output feeds a committed STABILITY snapshot and is adjacent to the byte-exact SMA_MACD oracle discipline. Per the critical constraint to prefer fixes dormant at the pinned β and not destabilize regression locks, the cosmetic dedup is not worth perturbing the computation path. Left as-is.
**Original issue:** Both helpers independently recompute `np.log(win[...][:beta_warmup])` for both legs (two copies of the same windowing/slicing logic that could drift).

---

_Fixed: 2026-06-22_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
