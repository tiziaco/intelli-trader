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
  warning: 0
  info: 0
  total: 0
status: clean
---

# Phase 1: Code Review Report

**Reviewed:** 2026-06-15T00:00:00Z
**Depth:** standard
**Files Reviewed:** 16
**Status:** clean

## Summary

This is iteration 3 (final) of the auto fix+re-review loop for the INST-01/INST-02/INST-03
instrument value-object work. All prior findings (WR-01..WR-05, IN-02..IN-05) and the
`ConfigurationError`-argument bug in `backtest_runner.py` were resolved in earlier passes.

I re-reviewed the current state adversarially against the phase's weighted concerns —
Decimal-end-to-end money, byte-exact oracle preservation, the tab/space indentation hazard,
and `mypy --strict` cleanliness — and focused specifically on the two `backtest_runner.py`
`ConfigurationError` raises. **No findings remain and none were newly introduced.**

### Verification performed

- **The two `ConfigurationError(reason=...)` raises are correct.** Both calls
  (`backtest_runner.py:82` membership-desync guard, `backtest_runner.py:106` empty-store
  guard) pass the message via `reason=`, which is the third parameter of
  `ConfigurationError.__init__(config_key=None, config_value=None, reason=None)` in
  `core/exceptions/base.py:31`. Confirmed at runtime: the message renders as
  `"Configuration error: <reason>"` and the `.reason` attribute is populated. Using the
  keyword (not positional) is the right call here — a positional first arg would have
  mis-bound the message to `config_key`, producing `"Configuration error for '<message>'"`.

- **`mypy --strict` clean.** Full gate over all 185 source files: `Success: no issues found`.
  In-scope modules individually clean as well.

- **Phase test suite green.** All 44 tests across `test_instrument.py`, `test_money.py`,
  `test_min_order_size_resolution.py`, and the `tests/unit/universe/` tree pass.

- **No `Decimal(float)` violations.** Every `Decimal(...)` construction in the in-scope
  modules is either a string-literal path (`Decimal("0.001")`, `Decimal(f"1e-{capped}")`,
  the `to_money` `Decimal(str(x))` path) or a docstring warning against the anti-pattern.
  `money.py` precision flows off the `Instrument` scale Decimal; no float coercion enters
  the money domain.

- **Indentation conventions honored.** The 4-space files (`core/instrument.py`,
  `core/money.py`, all of `universe/`, `config/exchange.py`) carry zero tab-indented lines;
  the tab files (`trading_system/backtest_runner.py`, `trading_system/compose.py`) carry
  zero 4-space body-indented lines. No mixed-indentation hazard introduced.

- **Byte-exact oracle guards intact.** BTCUSD is DECLARED 8dp price/quantity in
  `_DECLARED` (`instruments.py:106`) anchored to the single `_BTC_8DP` constant, so
  inference never runs on the oracle symbol; `min_order_size` is left undeclared (`None`),
  so `resolve_min_order_size("BTCUSD")` falls through to the venue `ExchangeLimits(0.001)`
  fallback byte-identically (verified by `test_btcusd_resolves_to_oracle_protecting_fallback`).
  The ping-grid `reduce(pd.Index.union, ...)` returns the single-symbol index unchanged.

### Notes (non-findings)

The following were considered and judged NOT defects:

- **Import-path inconsistency for `ConfigurationError`.** `backtest_runner.py` imports it
  from `itrader.core.exceptions` (the package barrel) while `simulated.py` imports from
  `itrader.core.exceptions.base`. Both resolve to the identical class (verified
  `A is B == True`). This is a stylistic divergence the project's "match the file you edit"
  convention explicitly permits, not a correctness or maintainability defect.

- **`_infer_price_scale` edge handling.** Cells like `"12."` (empty fractional part) and
  `"1.0e-5"` (scientific notation) are correctly skipped via the `frac.isdigit()` guard
  (WR-02 fix), and the whole-number-only case is caught by the `capped <= 0` guard — no
  false 0dp inference. This path is never exercised on the oracle (BTCUSD is declared).

- **WR-03 desync assertion** (`backtest_runner.py:81`) compares `set(membership)` against
  `set(instruments)`; since `derive_instruments` composes `derive_membership` over the same
  inputs, the invariant holds today and fails loudly if a future non-idempotent
  `derive_membership` desyncs the two. Defensive and correct.

All reviewed files meet quality standards. No issues found.

---

_Reviewed: 2026-06-15T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
