---
phase: 06-pair-trading-flagship
reviewed: 2026-06-22T00:00:00Z
depth: standard
iteration: 2
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
  critical: 0
  warning: 0
  info: 1
  total: 1
status: clean
---

# Phase 6: Code Review Report (Iteration 2 — re-review)

**Reviewed:** 2026-06-22
**Depth:** standard
**Files Reviewed:** 7
**Status:** clean (one accepted Info carried forward; no open issues)

## Summary

Re-review of the Phase 6 pair-trading flagship after the fixer applied 10 of the 12
iteration-1 findings (CR-01, CR-02, WR-01..WR-06, IN-01, IN-04) and deliberately
deferred IN-02 (snapshot generate-and-pass policy) and IN-03 (log-array dedup) as
out of safe scope. I re-read every file in scope, traced the changed code against
its callers (`StrategiesHandler._dispatch_pair` → `evaluate_pair` → `_entry` →
`SignalIntent`/`SignalEvent`), and verified the engine-order assumptions the fixes
rely on (`__init__`/`reconfigure` run `validate()` then `_run_init()`, and
`_run_init` only ever grows `max_window` via `max(derived, class_value)` — derived=0
for a handle-free pair, so the WR-01 equality invariant holds at runtime).

**All 10 applied fixes are correct and introduce no new defects.** Highlights:

- **CR-01 (negative/non-finite β):** `_fit_beta` now raises on `not math.isfinite(beta)
  or beta <= 0` at the fit boundary (eth_btc_pair_strategy.py:142). β can no longer
  reach `to_money` as `NaN`/negative, so no poisoned/negative quantity flows into the
  Decimal money domain. The guard fires before `_coint_pvalue` is called.
- **WR-06 (entry_units sign/zero):** `validate()` now calls
  `_require_positive("EthBtcPairStrategy", "entry_units", self.entry_units)`
  (eth_btc_pair_strategy.py:89). `_require_positive` confirmed present in
  `core/sizing.py:71`. A zero/negative reconfigure is rejected at construction.
- **WR-01 (β-fit-window slide):** `validate()` now pins `max_window ==
  beta_warmup + z_lookback` exactly (eth_btc_pair_strategy.py:98). Verified the
  invariant survives `_run_init` (handle-free → `derived=0` → `max(0,280)=280`).
- **WR-04 (non-finite z):** the guard is now `pd.isna(curr_raw) or not
  np.isfinite(curr_raw)` (eth_btc_pair_strategy.py:256) — `±inf` from a zero-variance
  spread window no longer fires a spurious entry.
- **WR-02 / WR-03 / WR-05 / CR-02 / IN-01:** documentation/precondition fixes applied
  in the correct docstrings (single-call-per-tick precondition on `evaluate_pair`,
  strict-inequality band convention on `_crosses_into`/`_crosses_inside`, the
  pair-path close-only safety note resting on `_in_pair`, the corrected determinism
  justification in both the strategy and the double-run test).
- **IN-04:** `_dispatch_pair` now guards `len(strategy.tickers) != 2` with a clear
  message before the tuple-unpack (strategies_handler.py:278).

Money discipline (Decimal end-to-end via `to_money`, never `Decimal(float)`),
queue-only cross-domain contract (strategy emits intents; handler fans out
`SignalEvent`s), determinism (no wall-clock, seeded RNG untouched), and per-file
indentation (source = tabs, tests = 4 spaces — verified clean, no mixed-indent diff)
all hold. The two regression locks are not endangered by any change: the pair path
is gated behind an `isinstance(strategy, PairStrategy)` branch that `continue`s out
of the single-leg loop, so the SMA_MACD oracle path is byte-untouched, and the
committed `tests/golden/pair/{trades,equity}.csv` snapshot remains the lock for the
pair run.

No Critical or Warning findings remain. One Info item (IN-02) is carried forward
**as accepted**, not reopened — recorded below only for traceability.

## Info

### IN-02 (accepted — carried forward, NOT reopened): snapshot generates-and-passes on first run

**File:** `tests/integration/test_pair_flagship_snapshot.py:195-200`
**Status:** Deliberately deferred by the fixer as out of safe scope; re-confirmed
accepted. The generate-and-pass branch is the documented "Don't Hand-Roll" golden
pattern (mirrors `test_backtest_oracle.py`), and the real baseline IS committed at
`tests/golden/pair/{trades,equity}.csv` (verified present), so the silent-acceptance
window only opens if that directory is wiped. I found **no new or stronger reason to
reopen** — the committed CSVs mitigate the footgun and the pattern is consistent with
the rest of the suite. Listed here purely so the deferral stays visible.
**Fix (if ever pursued):** fail (not pass) on first generation behind an explicit
opt-in regen env var. Not required for this phase.

_Note: IN-03 (the `_fit_beta` / `_coint_pvalue` log-array duplication) was also
deliberately deferred. It is a fit-once, two-line duplication with no correctness or
determinism impact; re-confirmed as a safe deferral and not counted as an open issue._

---

_Reviewed: 2026-06-22_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
_Iteration: 2 (re-review after 10 fixes applied, 2 deferred)_
