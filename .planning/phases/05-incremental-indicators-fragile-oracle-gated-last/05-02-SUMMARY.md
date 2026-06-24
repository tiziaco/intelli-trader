---
phase: 05-incremental-indicators-fragile-oracle-gated-last
plan: 02
subsystem: strategy
tags: [stateful-indicators, o1-recurrences, ta-dropped, per-symbol-fanout, oracle-rebaseline, perf-05, cross-validation]

# Dependency graph
requires:
  - phase: 05-incremental-indicators-fragile-oracle-gated-last
    provides: "Plan A — BarFeed shared recent-bars seam (newest-bar provision + registration interface), byte-exact plumbing"
provides:
  - "Four hand-written O(1) stateful indicator recurrences (SMA running-sum deque, EMA factored seed-from-first, MACD two factored EMAs+signal, RSI factored-RMA) — ta DROPPED on the runtime path (P5-D11/D12)"
  - "IndicatorState / IndicatorAdapter Protocols — Model B push contract (update/value/is_ready/reset/causal, P5-D07)"
  - "IndicatorHandle update()-driven bounded depth-2 output buffer (P5-D08); [-1]/[-2] read + read-before-warm RuntimeError preserved"
  - "Strategy.update(ticker,bar)/is_ready(ticker)/reset() per-symbol lazy fan-out + causal-guard rejection at indicator() registration (P5-D10/D19/D20)"
  - "SMA_MACD oracle re-baseline CONFIRMED byte-identical (134 / 46189.87730727451), cross-validated, owner-approved"
affects: [05-03, stateful-indicators, per-tick-window-removal, pair-migration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Model B stateful recurrence: O(1) push update(value), is_ready=count>=min_period, reset(), causal flag — Nautilus/LEAN idiom"
    - "EMA factored form y+=alpha*(x-y) seed-from-first (2x closer to ta than expanded); SMA running-sum deque eviction sum+=new-evicted (never re-sum)"
    - "RSI ta-alignment: diff[0]=NaN -> .where(>0,0.0) -> up[0]=0.0 zero-seed at bar 0 (NOT bar-1 first-gain seed) — the Pitfall-1 landmine"
    - "Per-symbol lazy fan-out: one stateful handle-set per ticker minted on first bar; independent readiness; gap=no-update (caller skips)"
    - "Numerically-transparent re-baseline: indicators gate decisions through boolean primitives only, never enter money arithmetic -> zero equity drift"

key-files:
  created:
    - tests/unit/strategy/test_indicator_convergence.py
    - tests/unit/strategy/test_indicator_reset.py
    - tests/unit/strategy/test_causal_guard.py
  modified:
    - itrader/strategy_handler/indicators/catalog.py
    - itrader/strategy_handler/indicators/handle.py
    - itrader/strategy_handler/indicators/__init__.py
    - itrader/strategy_handler/base.py
    - tests/unit/strategy/test_indicators.py

key-decisions:
  - "ta DROPPED on the runtime path (P5-D11): catalog.py imports only collections.deque + typing; ta/pandas survive ONLY as the test-time convergence oracle"
  - "RSI Pitfall-1 zero-seed: ta's diff.where(diff>0,0.0) makes up[0]=dn[0]=0.0 (diff[0]=NaN, NaN>0 is False), so the RMA seeds at bar 0 with 0.0 NOT at bar 1 with the first gain — the only real footgun, caught by the convergence test (28 RSI-point divergence -> 2.84e-14 after fix)"
  - "Re-baseline is byte-identical, not ULP-drift (stronger than P5-D02 anticipated): the SMA_MACD decision logic reads indicators only through boolean is_above/crossover/crossunder; the ~9-orders-of-magnitude boundary margin means no boolean flips, and trade prices/quantities come from bar.close not the indicator floats -> the indicators GATE decisions but never enter the money arithmetic -> final_equity 46189.87730727451 UNCHANGED"
  - "No golden re-freeze technically required (numerically transparent conversion); the freeze gate is a confirm-unchanged, not a rewrite — golden left byte-identical, no no-op churn commit"
  - "MACD convergence asserted past a documented slow-EMA settle offset (5x slow span): ta recomputes over a sliding window each tick (re-seeding) while the stateful EMA seeds once, so the transient region is legitimately different (the oracle reads macd_hist only at bar 100+, drift 1.7e-11)"

patterns-established:
  - "Stateful adapter as stateless factory (new_state) + per-handle IndicatorState: the fan-out keys one set per symbol; the singleton adapter is shared, the state is per-(symbol)"
  - "repopulate() as the Plan-B compatibility seam: drives the stateful state from the legacy evaluate window (mint fresh state, feed input_col value-by-value) preserving the byte-identical firing tick; Plan C removes the window and drives update() per tick"

requirements-completed: [PERF-05]

# Metrics
duration: ~35min
completed: 2026-06-24
---

# Phase 5 Plan 02: O(1) Stateful Indicators + SMA_MACD Oracle Re-baseline (Plan B) Summary

**All four indicators (SMA/EMA/MACD/RSI) are now hand-written O(1) stateful recurrences with `ta` dropped on the runtime path; the SMA_MACD oracle re-baseline was cross-validated and confirmed BYTE-IDENTICAL (134 / 46189.87730727451 unchanged) — the conversion is numerically transparent to the decision path, so the owner-gated freeze was a confirm-unchanged, not a rewrite.**

## Performance

- **Duration:** ~35 min
- **Completed:** 2026-06-24
- **Tasks:** 3 (Task 1 TDD RED→GREEN, Task 2 fan-out, Task 3 owner-gated re-baseline checkpoint)
- **Files modified:** 8 (3 created, 5 modified)

## Accomplishments

### Task 1 — Four O(1) stateful recurrences + ta dropped on the runtime path (P5-D11/D12)

- **`catalog.py` rewritten** to Model B (P5-D07): the four `compute(...)` batch adapters became STATELESS factories (`new_state(params)`) minting per-symbol `_*State` recurrence objects, each with a pure push `update(value)`, a `value` property, `is_ready` (= `count >= min_period`, P5-D06), `reset()` (P5-D19), and a `causal = True` flag (P5-D20). `from ta import ...` is GONE from the runtime path — the module imports only `collections.deque` + `typing`. `ta`/pandas survive ONLY in the convergence test.
  - **SMA** — running-sum `deque(maxlen=window)` eviction, `_sum += new − evicted` (P5-D05); the ring is a LOOKUP for the departing value, NEVER re-summed.
  - **EMA** — factored seed-from-first `value = x if None else value + alpha*(x−value)`, `alpha = 2/(period+1)` (P5-D04 — 2× closer to `ta` than the expanded form).
  - **MACDHist** — factored-EMA(fast) − factored-EMA(slow), then factored-EMA(signal) of that line; `min_period = slow + signal` (==15, byte-identical).
  - **RSI** — factored-RMA `alpha = 1/n` over `close.diff(1)` gain/loss, with the **Pitfall-1 zero-seed** (see Deviations): `up[0] = dn[0] = 0.0` seeded at bar 0.
- **`handle.py`** — `repopulate(...)` became an `update()`-driven bounded depth-2 output buffer (P5-D08). The `[-1]`/`[-2]` positional read, the read-before-warm `RuntimeError` (survives `-O`), `__len__` 0-before-warm, and `min_period` delegation are PRESERVED. `repopulate` is the Plan-B compatibility seam: it mints a fresh state and feeds the legacy window value-by-value, preserving the byte-identical firing tick.
- **Three new tests + re-baselined unit tests:** `test_indicator_convergence.py` (P5-D17, all four vs `ta` batch on the golden CSV, post-warmup `atol=1e-9/rtol=1e-6`), `test_indicator_reset.py` (P5-D19, reset→re-feed == fresh run), `test_causal_guard.py` (P5-D20 + per-symbol fan-out readiness). `test_indicators.py` EMA/RSI/SMA/MACD value tests re-baselined to the stateful recurrence (P5-D12). Convergence margins match RESEARCH: **RSI max_abs 2.84e-14**, EMA/SMA within tol, MACD 1.7e-11 post-bar-100.

### Task 2 — Per-symbol fan-out + readiness + reset + causal guard on `base.py`

- `indicator()` gained the P5-D20 **causal guard** (explicit `RuntimeError` at registration for `causal=False` adapters) and records the declaration recipe in `_handle_specs` — the author surface (`def indicator(self, adapter: IndicatorAdapter, ...)`) is BYTE-IDENTICAL (P5-D21).
- `update(ticker, bar)` extracts each handle's `input_col` from the bar and pushes it through THAT ticker's lazy handle-set (minted on first bar, P5-D10a). `is_ready(ticker)` = `all(h.is_ready)` per symbol (independent across symbols, P5-D10b). `reset()` clears every per-symbol set + the fan-out map (P5-D19). Gap bar = caller skips → no update, state frozen (P5-D10c).

### Task 3 — SMA_MACD oracle re-baseline (P5-D02, owner-gated blocking checkpoint)

- **Behavioral identity GREEN:** `test_oracle_behavioral_identity` passes — 134 trades, all entry/exit/side/pair EXACT, equity timestamp grid (3076 rows) EXACT. The trade SET did NOT move (firing tick preserved at bar 100).
- **Byte-identical, not ULP-drift (stronger than P5-D02 anticipated):** the fresh run reproduced the committed golden BYTE-FOR-BYTE — `final_equity = 46189.87730727451` unchanged, `trades.csv`/`equity.csv`/`summary.json` all identical. `test_oracle_numeric_values` ALSO passes (zero drift). **Rationale:** SMA_MACD reads the indicators only through boolean `is_above`/`crossover`/`crossunder`; the ~9-orders-of-magnitude boundary margin means the indicator-value drift never flips a boolean, and trade prices/quantities come from `bar.close`, not the indicator floats — the indicators GATE decisions but never enter the money arithmetic.
- **Cross-validation PASS (P5-D02 gating, existing `scripts/cross_validate.py` harness — output restored, not committed):** identical to the prior owner-approved run. final_equity: backtesting.py 46027.30 PASS (−0.35%), backtrader 46189.877307 PASS (exact to the cent); trade_count 134 both; cagr/max_drawdown/profit_factor/sharpe/win_rate all PASS ≤1% rel tol. The 3 sortino divergences + nautilus win_rate are the PRE-EXISTING, owner-dispositioned LEGITIMATE-DIFFERENCEs (entry-bar equity-marking convention; nautilus NETTING fill arithmetic) — **NO new divergence introduced**.
- **Determinism (P5-D18):** double-run of `run_backtest.py` byte-identical (summary, trades, equity). `mypy itrader` clean (188 files).
- **No golden re-freeze required:** the conversion is numerically transparent to the decision path, so the freeze gate is a confirm-unchanged — the golden artifacts and the `test_oracle_numeric_values` reference were left byte-identical (no no-op churn commit).

### Owner Sign-Off (P5-D02)

**Owner sign-off: tiziaco (tiziano.iaco@gmail.com), 2026-06-24 — at the blocking-human checkpoint, P5-D02.** The owner independently re-verified the checkpoint state (oracle 3/3 green incl. numeric byte-identical, 32 indicator tests green, mypy `--strict` clean 188 files, working tree clean, golden untouched) and approved the re-baseline.

## Task Commits

1. **RED — failing convergence/reset/causal tests** — `9f085fc` (test)
2. **Task 1 — four O(1) stateful recurrences (ta dropped), re-baselined unit tests** — `19c4757` (feat)
3. **Task 2 — per-symbol fan-out + readiness + reset + causal guard** — `d2b4887` (feat)
4. **Task 3 — oracle re-baseline confirmed byte-identical (golden untouched), this SUMMARY** — final docs commit

## Files Created/Modified

- `itrader/strategy_handler/indicators/catalog.py` (modified) — four O(1) `_*State` recurrences + stateless adapter factories; `IndicatorState`/`IndicatorAdapter` Protocols; `ta` dropped on the runtime path; `causal=True`.
- `itrader/strategy_handler/indicators/handle.py` (modified) — `update()`-driven bounded depth-2 buffer; `repopulate` is the Plan-B compatibility seam; read-before-warm guard preserved.
- `itrader/strategy_handler/indicators/__init__.py` (modified) — export `IndicatorState`.
- `itrader/strategy_handler/base.py` (modified) — `update`/`is_ready`/`reset` per-symbol fan-out + causal guard at `indicator()`; author surface byte-identical.
- `tests/unit/strategy/test_indicators.py` (modified) — re-baselined EMA/RSI/SMA/MACD value tests to the stateful recurrence + new handle update/reset tests.
- `tests/unit/strategy/test_indicator_convergence.py` (created) — P5-D17 ta-convergence, all four, golden CSV, post-warmup.
- `tests/unit/strategy/test_indicator_reset.py` (created) — P5-D19 reset→re-feed == fresh run.
- `tests/unit/strategy/test_causal_guard.py` (created) — P5-D20 non-causal rejection + P5-D10 per-symbol fan-out readiness.

## Decisions Made

- **`ta` dropped on the runtime path (P5-D11)** — `catalog.py` is pure stdlib + typing; `ta`/pandas are test-time-only convergence oracles.
- **RSI Pitfall-1 zero-seed (the only real footgun)** — `ta`'s `diff.where(diff>0, 0.0)` makes `up[0]=dn[0]=0.0` because `diff[0]` is NaN and `NaN > 0` is False; the RMA therefore seeds at bar 0 with `0.0`, NOT at bar 1 with the first gain. Seeding at bar 1 drifted ~28 RSI points early and only slowly reconverged (caught by the convergence test); the bar-0 zero-seed gives max_abs 2.84e-14.
- **The re-baseline is numerically transparent (byte-identical)** — stronger than the P5-D02-anticipated ULP drift; the golden was confirmed unchanged, no re-freeze.
- **MACD convergence settle offset (5× slow span)** — `ta`'s sliding-window re-seed vs the stateful single-seed makes the EMA transient legitimately different pre-warmup; the oracle reads macd_hist only at bar 100+ (drift 1.7e-11).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] RSI recurrence seeded one bar too late (Pitfall-1 alignment)**
- **Found during:** Task 1 GREEN (the convergence test failed at bar 14 with a ~28 RSI-point divergence — the exact symptom RESEARCH Pitfall 1 warned of).
- **Issue:** The initial `_RSIState` followed the RESEARCH §Code-Examples skeleton literally (bar 0 sets `prev_close` and returns; bar 1 seeds `up/dn` from the first gain). But `ta`'s actual series is `diff.where(diff>0, 0.0)` where `diff[0]` is NaN → `NaN > 0` is False → `up[0] = dn[0] = 0.0`. `ta` therefore seeds the RMA at bar 0 with `0.0` (and `min_periods=window` masks output until `window` ewm observations exist), i.e. one bar EARLIER than the skeleton's bar-1 seed. The bar-1 seed decayed too slowly (707 vs `ta`'s 213 at bar 13) and never fully reconverged.
- **Fix:** Seed `_up = _dn = 0.0` at bar 0 (matching `ta`'s `up[0]=0.0`), increment `count` from bar 0, and mask `value` until `count >= window`. This is the correct interpretation of the RESEARCH Pitfall-1 "align to `close.diff(1)`, seed-from-first" note (the "first" value of the WHERE-zeroed series is the `0.0` at bar 0, not the first gain at bar 1).
- **Files modified:** `itrader/strategy_handler/indicators/catalog.py` (`_RSIState`).
- **Verification:** RSI convergence max_abs 2.84e-14 vs `ta` (the exact RESEARCH-measured figure).
- **Committed in:** `19c4757`

**Total deviations:** 1 auto-fixed (Rule 1 — RSI seed alignment, the documented Pitfall-1 landmine). The SMA/EMA/MACD recurrences matched the RESEARCH skeleton verbatim and converged first try.

## Authentication Gates

None.

## Known Stubs

None. All four recurrences are fully implemented O(1) stateful adapters; the per-symbol fan-out surfaces (`update`/`is_ready`/`reset`) are complete and tested. Plan C consumes them from the handler loop (the `evaluate`/`repopulate` compatibility seam stays intact until then).

## Self-Check: PASSED

- All created files exist (`test_indicator_convergence.py`, `test_indicator_reset.py`, `test_causal_guard.py`, this SUMMARY).
- All task commits exist (`9f085fc`, `19c4757`, `d2b4887`).
- Oracle 3/3 green (134 / 46189.87730727451 byte-identical); 32 new/re-baselined indicator tests + 121 strategy unit tests green; `mypy --strict` clean (188 files); determinism double-run byte-identical; `ta` returns 0 lines on the runtime grep; golden untouched (working tree clean).

---
*Phase: 05-incremental-indicators-fragile-oracle-gated-last*
*Completed: 2026-06-24*
