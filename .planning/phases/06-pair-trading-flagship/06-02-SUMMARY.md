---
phase: 06
plan: 02
subsystem: strategy_handler
tags: [pair-trading, flagship, log-ols-beta, z-score, crossing-firing, wave-2, PAIR-01]
requires:
  - "itrader/strategy_handler/pair_base.py::PairStrategy (evaluate_pair seam, _entry explicit-quantity constructor, LONG_SHORT + log-price defaults)"
  - "itrader/core/money.py::to_money (the only Decimal entry — Decimal(str(x)))"
  - "itrader/core/sizing.py::SignalIntent (quantity / exit_fraction / leverage fields)"
  - "statsmodels.api.OLS + statsmodels.tsa.stattools.coint"
provides:
  - "itrader/strategy_handler/strategies/eth_btc_pair_strategy.py::EthBtcPairStrategy — concrete ETH/BTC pair strategy: frozen log-OLS β, rolling z-score band crossing firing, β-weighted explicit-quantity entries, quantity-free exits, logged coint diagnostic"
  - "Pure β/z helpers (_fit_beta, _coint_pvalue, _zscore, _crosses_into, _crosses_inside) — hand-tested directly"
  - "GREEN β/z unit tests in tests/unit/strategy/test_pair_strategy.py (Wave-0 stubs replaced)"
affects:
  - "tests/unit/strategy/test_pair_strategy.py (Wave-0 -k beta / -k zscore stubs → real GREEN tests)"
tech-stack:
  added: []
  patterns:
    - "log-OLS hedge-ratio β fit-once-then-freeze (cached on the instance; never re-fit) — D-05"
    - "Engle-Granger coint p-value LOGGED as diagnostic, never gates the run — D-10 RESOLVED"
    - "Crossing-stateful firing with an internal _in_pair flag + tracked entry-z sign (exit covers the correct side) — D-12/D-13"
    - "β-weighted explicit-quantity ENTRIES via _entry; quantity-free exit_fraction=1 EXITS (RESEARCH Pitfall 1)"
    - "β → Decimal only via to_money (Decimal(str(x))) — Pitfall 4"
key-files:
  created:
    - "itrader/strategy_handler/strategies/eth_btc_pair_strategy.py"
  modified:
    - "tests/unit/strategy/test_pair_strategy.py"
decisions:
  - "D-04/D-05: β = slope of OLS(log close_ETH on log close_BTC) over the first beta_warmup completed bars, fit once and frozen for the rest of the run"
  - "D-06: spread = log(ETH) − β·log(BTC); z = (spread − rolling_mean)/rolling_std over z_lookback (pandas ddof=1)"
  - "D-10 RESOLVED: coint p-value computed on the warmup window and logged as a diagnostic — never gates"
  - "D-13: entry fires only on |z| crossing INTO the band while flat; exit only on |z| crossing back inside while in-pair"
  - "Pitfall 1: exits carry NO quantity (exit_fraction=Decimal('1')); only entries carry explicit β-weighted quantity"
  - "entry-z sign tracked on _entry_z_sign so the exit covers the correct leg side (z>0 entry shorts A/longs B → exit buys A/sells B; mirror for z<0)"
  - "z_lookback=30, beta_warmup=250, max_window=280 (=beta_warmup+z_lookback, Pitfall 3); entry_z=2, exit_z=0.5"
  - "timeframe is a REQUIRED kwarg, NOT a class attr (base annotates it as a resolved timedelta — a str class-attr conflicts under mypy --strict); supplied as timeframe='1d' at construction"
metrics:
  duration: ~15 min
  completed: 2026-06-22
---

# Phase 6 Plan 02: ETH/BTC Reference Pair Strategy (β/z Alpha) Summary

Landed the flagship alpha: `EthBtcPairStrategy`, a market-neutral log-spread
mean-reversion strategy on top of the Wave-1 `PairStrategy` base. β is a frozen
log-OLS hedge ratio fit once over the warmup window; the rolling z-score band
trigger fires on crossings against an internal in-pair flag; entries carry
β-weighted explicit quantities (short rich / long cheap) and exits are
quantity-free (clamp-to-flat). The Engle-Granger coint p-value is logged as a
diagnostic only (D-10). Hand-computed β/z unit tests are GREEN; `mypy --strict`
clean (165 files); TABS in source, 4 spaces in tests.

## What Was Built

### Task 1 — RED β/z unit tests (`test_pair_strategy.py`, 4 spaces) — commit 5fa6ccb
- Replaced the two Wave-0 `pytest.skip` stub bodies with real hand-computed tests.
- `test_beta_log_ols_fixture` (`-k beta`): a PERFECT log-linear fixture where
  `log(A) = 1.0 + 0.5·log(B)`, so the OLS slope is exactly 0.5. The expected β is
  computed inline by statsmodels (the test is the oracle, D-11); the strategy's
  `_fit_beta` must reproduce it within 1e-9, and β is asserted to be a float
  (consumed via `to_money` downstream — Pitfall 4).
- `test_zscore_rolling_and_crossing` (`-k zscore`): a hand-built spread series
  `[1,2,3,2,1,0,-1,5]`, lookback 4 → last window `[1,0,-1,5]`, inline reference
  mean 1.25 / std(ddof=1) ≈ 2.62995564 / z ≈ 1.42587956. Asserts `_zscore` matches
  to 1e-12, the first `lookback-1` entries are NaN, and the crossing helpers
  (`_crosses_into` / `_crosses_inside`) fire only on the transition bar.
- RED confirmed as an **ImportError** on the not-yet-existing strategy module
  (the documented RED state per the plan's Task-1 action).

### Task 2 — ETH/BTC pair strategy (`eth_btc_pair_strategy.py`, TABS) — commit ace06f5
- `EthBtcPairStrategy(PairStrategy)`: `tickers = ["ETHUSD","BTCUSD"]`,
  `direction = LONG_SHORT`, `entry_z = Decimal("2")`, `exit_z = Decimal("0.5")`,
  `z_lookback = 30`, `beta_warmup = 250`, `max_window = 280` (= beta_warmup +
  z_lookback, Pitfall 3), `leverage = Decimal("1")`, `use_log_prices = True`
  (inherited). `sizing_policy = FractionOfCash(Decimal("0.95"))` placeholder (the
  entry path bypasses it via explicit β-weighted quantity).
- `validate()` calls `super().validate()` (two tickers, `exit_z < entry_z`,
  `max_window >= beta_warmup + z_lookback`). `init()` is handle-free and resets
  the fit-once cache (`_beta`), the `_in_pair` flag, `_prev_z`, and `_entry_z_sign`
  so a reconfigure is idempotent.
- Pure helpers: `_fit_beta` (log-OLS slope over the first `beta_warmup` bars),
  `_coint_pvalue` (Engle-Granger p over the same window), `_zscore` (rolling
  mean/std, ddof=1), `_crosses_into` / `_crosses_inside` (crossing predicates).
- `evaluate_pair`: gates on `len(window) >= beta_warmup + z_lookback`; fits +
  **freezes** β on the first eligible tick and logs the coint p-value as a
  diagnostic (D-10 — never gates); each tick computes the log-spread z-score and
  fires on a crossing. **Entry** (flat, crosses into band): short the rich leg /
  long the cheap leg, β-weighted explicit quantity (`_entry` via `to_money`), set
  `_in_pair` + record the entry-z sign. **Exit** (in-pair, crosses back inside):
  quantity-free `buy()/sell()` inverse of the tracked entry side, clear `_in_pair`.
- β enters the Decimal domain ONLY via `to_money(beta)` (Pitfall 4 — verified by
  grep: no `Decimal(float_var)`).
- **Deviation (Rule 3 — blocking):** removed a `timeframe = "1d"` class attr that
  tripped `mypy --strict` (`str` vs the base's `timedelta` annotation). `timeframe`
  is a required kwarg supplied at construction, mirroring `SMA_MACD_strategy`.

## Verification Results

- `poetry run pytest tests/unit/strategy/test_pair_strategy.py -q` — 2 passed
  (β + z-score GREEN).
- `poetry run pytest tests/unit/strategy -q` — 96 passed, 3 skipped (the 3 skips
  are the Plan 06-03 `test_pair_dispatch.py` Wave-0 stubs, not this plan).
- `poetry run mypy` — Success: no issues found in 165 source files (strict).
- Functional smoke (REPL): β fits + freezes (logged with coint p-value diagnostic);
  the run does not crash; the entry/exit intent contract holds.
- Grep gates: `sm.OLS` + `coint` present; `to_money` present; NO `Decimal(float_var)`;
  NO queue/portfolio access in code (pure-alpha). Indentation: 161 tab lines, 0
  space-indented code lines (TABS clean); tests are 4 spaces.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Removed `timeframe = "1d"` class attr (mypy type conflict)**
- **Found during:** Task 2 (mypy gate)
- **Issue:** Declaring `timeframe = "1d"` as a class attr conflicts with the base
  `Strategy` annotation `timeframe: timedelta` (the base resolves the str kwarg to
  a timedelta in `_apply_params`), so `mypy --strict` flagged an incompatible
  assignment.
- **Fix:** Removed the class attr; `timeframe` is supplied as a required kwarg at
  construction (`timeframe="1d"`), exactly as `SMA_MACD_strategy` does. Added a
  NOTE comment documenting why.
- **Files modified:** `itrader/strategy_handler/strategies/eth_btc_pair_strategy.py`
- **Commit:** ace06f5

## Authentication Gates

None.

## Known Stubs

None in production code. `EthBtcPairStrategy` is fully implemented (β fit/freeze,
z-score, crossing firing, entries/exits, coint diagnostic). The `entry_units`
default (`Decimal("1")`) is an overridable knob, not a stub. The flagship
end-to-end snapshot + determinism double-run wiring is delivered by later Phase 6
plans (06-03 dispatch tests, the flagship-snapshot plan) per the planned wave split.

## Threat Flags

None. No new security-relevant surface — offline CSV, no network, no user input.
The threat-register mitigations (T-06-04 look-ahead-safe frozen β + completed-bar
windows; T-06-05 β via `to_money` only; T-06-06 quantity-free exits) are all
implemented as the plan specified.

## Self-Check: PASSED

- FOUND: itrader/strategy_handler/strategies/eth_btc_pair_strategy.py
- FOUND: tests/unit/strategy/test_pair_strategy.py
- FOUND commit 5fa6ccb (Task 1 RED), ace06f5 (Task 2 GREEN)
