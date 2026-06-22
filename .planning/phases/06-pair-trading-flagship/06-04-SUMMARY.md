---
phase: 06
plan: 04
subsystem: strategy_handler
tags: [pair-trading, flagship, stability-snapshot, determinism, phase-gate, wave-3, PAIR-01]
requires:
  - "itrader/strategy_handler/strategies/eth_btc_pair_strategy.py::EthBtcPairStrategy (Plan 06-02 — β/z alpha)"
  - "itrader/strategy_handler/strategies_handler.py::_dispatch_pair (Plan 06-01 — two-leg dispatch + short/margin registration gate)"
  - "itrader/trading_system/backtest_trading_system.py::BacktestTradingSystem (csv_paths multi-symbol + run())"
  - "itrader/reporting/frames.py::build_trade_log / build_equity_curve (deterministic run artifacts)"
provides:
  - "tests/integration/test_pair_flagship_snapshot.py — GREEN STABILITY snapshot + determinism double-run for the ETH/BTC flagship"
  - "tests/golden/pair/trades.csv — generated STABILITY snapshot of the flagship trade log (NOT a hand-verified oracle)"
  - "tests/golden/pair/equity.csv — generated STABILITY snapshot of the flagship equity curve (NOT a hand-verified oracle)"
affects: []
tech-stack:
  added: []
  patterns:
    - "STABILITY snapshot in a NEW tests/golden/pair/ dir — explicitly NOT the SMA_MACD oracle (D-11, additive capstone)"
    - "_csv_roundtrip seam: serialise the FRESH frame to CSV bytes and read it back so fresh+committed snapshot share identical dtypes (mirrors test_backtest_oracle.py reading both sides from CSV) — robust exact diff on the deterministic columns"
    - "Generate-on-first-run / diff-on-subsequent-run snapshot mechanic with pandas frame-equal (check_exact, NOT byte-compare)"
key-files:
  created:
    - "tests/golden/pair/trades.csv"
    - "tests/golden/pair/equity.csv"
  modified:
    - "tests/integration/test_pair_flagship_snapshot.py"
decisions:
  - "Starting capital raised to $500k so a single UNLEVERED fixed-1-ETH / β-BTC pair fits the margin lock with drawdown headroom across 2021-2026 (BTC short leg notional peaks near 0.53 × $125k ≈ $66k + the ~$4.8k ETH leg ≈ $71k/pair). At $100k the fail-fast backtest aborted mid-run on the engine solvency assertion (InsufficientFundsError). No engine change — β-weighting and the Phase 2-4 accounting core are untouched (Rule 3 blocking-config fix)"
  - "The closed-position trade-log `side` column is the POSITION side (LONG/SHORT), not the order action (BUY/SELL) — PAIR-01 both-legs assertion checks LONG and SHORT present"
  - "Determinism double-run compares ALL columns (not just the deterministic keys) via the _csv_roundtrip serialised form — the stronger byte-identity claim"
metrics:
  duration: ~20 min
  completed: 2026-06-22
---

# Phase 6 Plan 04: ETH/BTC Pair Flagship STABILITY Snapshot + Phase Gate Summary

The PAIR-01 capstone: ran the `EthBtcPairStrategy` end-to-end through the full
backtest run path (`csv_paths={ETHUSD, BTCUSD}`, short selling + margin enabled,
2021-01-01..2026-01-08) and locked it against a regression STABILITY snapshot in a
NEW `tests/golden/pair/` directory — explicitly NOT a correctness oracle (D-11), and
the SMA_MACD golden master is untouched. Both a long leg and a short leg settle
through the Phase 2-4 accounting core with NO new branches; the run produces **94
closed round trips** (47 ETH + 47 BTC), well above the non-trivial lower bound. The
determinism double-run is byte-identical. Phase gate PASSED: full suite 1193 passed,
`mypy --strict` clean (165 files), SMA_MACD oracle byte-exact (134 /
46189.87730727451).

## What Was Built

### Task 1 — flagship run + STABILITY snapshot (`test_pair_flagship_snapshot.py`, 4 spaces) — commit ec523e9
- Replaced the two Wave-0 `pytest.skip` stub bodies (the STABILITY-lock / NOT-a-
  correctness-oracle docstring is preserved and expanded — D-11).
- `_build_flagship_system`: constructs `BacktestTradingSystem(exchange="csv",
  csv_paths={"ETHUSD": data/ETHUSD_1d_ohlcv.csv, "BTCUSD":
  data/BTCUSD_1d_ohlcv_2018_2026.csv}, start_date="2021-01-01",
  end_date="2026-01-08")`. Sets `sh._allow_short_selling = True` /
  `sh._enable_margin = True` **before** `add_strategy` (the LONG_SHORT registration
  gate, strategies_handler:361), registers `EthBtcPairStrategy(timeframe="1d")` on
  one portfolio, and sets the portfolio `trading_rules` + `admission_manager` +
  `order_validator` margin flags (mirrors the partial_cover e2e wiring). The Universe
  (ETHUSD + BTCUSD instruments) is derived from the data by the runner during
  `run()` — no manual `set_universe` needed.
- `_run_flagship`: runs end-to-end (`system.run(print_summary=False)`) and reads
  result state AFTER the run (queue-only rule) — the closed-position trade log and
  the metrics-snapshot equity curve via `reporting.frames`.
- `test_pair_flagship_snapshot_matches`: asserts ≥ 20 round trips (D-06; the run
  produces 94), asserts BOTH a LONG and a SHORT position side settled (PAIR-01),
  then GENERATES `tests/golden/pair/{trades,equity}.csv` on the first run and on
  subsequent runs diffs the fresh output against the committed snapshot with
  `pdt.assert_frame_equal(check_exact=True, check_like=True)` on the deterministic
  columns (trades entry/exit/side, equity timestamp/total_equity).
- `_csv_roundtrip` seam: the committed snapshot is loaded via `pd.read_csv`, so the
  FRESH frame is serialised to CSV bytes and read back through the SAME path — this
  reconciles a tz-aware datetime column (fresh) vs an object column (read back) and a
  Decimal `0E-16` repr vs `0.0`, so the exact diff compares on-disk identity, not
  in-memory dtype artifacts (the oracle test reads BOTH sides from CSV for the same
  reason).
- NO run-end force-close added — open legs at run end stay open and mark-to-market
  in final equity (D-15). The SMA_MACD oracle (`tests/golden/{trades,equity}.csv`) is
  byte-untouched (`git status` clean on those paths).

### Task 2 — determinism double-run + phase gate (`test_pair_flagship_snapshot.py`, 4 spaces) — included in commit ec523e9
- `test_pair_flagship_determinism_double_run`: runs the flagship twice in-process
  (fresh system each run, same seed/clock) and asserts the two outputs are identical
  on ALL columns via the `_csv_roundtrip` serialised form (the stronger byte-identity
  claim, not just the deterministic keys). β enters the Decimal domain only via
  `to_money` so the run is reproducible (Pitfall 4); no new nondeterminism.
- Phase gate run and PASSED (verification only, no further file change).

## Verification Results

- `poetry run pytest tests/integration/test_pair_flagship_snapshot.py -q` — 2 passed
  (snapshot diff stability + determinism double-run byte-identical).
- `poetry run pytest tests/integration/test_pair_flagship_snapshot.py -k determinism`
  — 1 passed, 1 deselected (the `-k determinism` selector still matches).
- `poetry run pytest tests/integration/test_backtest_oracle.py -q` — 3 passed
  (SMA_MACD oracle byte-exact: 134 trades / final_equity 46189.87730727451 —
  additive capstone, NO re-baseline).
- `poetry run mypy` — Success: no issues found in 165 source files (strict; no
  `itrader` source touched this plan).
- Full suite (`poetry run pytest tests`) — **1193 passed** (worktree: `poetry run
  pytest tests` not `make test`, per the .env-abort gotcha; orchestrator re-runs
  `make test` in the main checkout after merge).
- Indentation: `test_pair_flagship_snapshot.py` 4 spaces (no tab-indented lines).
- SMA_MACD oracle CSVs byte-unchanged: `git status tests/golden/trades.csv
  tests/golden/equity.csv` shows no modification (T-06-11 mitigated).

## Run Diagnostics (Manual-Only verifications, 06-VALIDATION.md)

- **Coint p-value logged as a diagnostic, NEVER gated (D-10 RESOLVED).** The run logs
  `pair beta fit (frozen) beta=0.5317387756064644 coint_pvalue=0.711180177288049
  beta_warmup=250 tickers=['ETHUSD','BTCUSD']`. The p-value (0.711, far above 0.05 —
  ETH/BTC does not pass strict cointegration) does NOT block the run; the rolling
  z-score delivers the 94 round trips. T-06-15 mitigated.
- **Single-sided-liquidation re-entry (D-07 × D-12) — DID NOT FIRE this run.** No
  forced-liquidation / margin-call events appear in the run logs, and the closed
  trade log is perfectly balanced (47 ETH + 47 BTC = 94, one ETH leg and one BTC leg
  per round trip). The $500k starting capital keeps every unlevered pair solvent, so
  no leg is liquidated mid-pair and the stale-close → spurious-reopen edge case is
  never exercised in this snapshot. T-06-14 disposition stands: accepted + documented,
  bounded to once per round trip by crossing-stateful firing; the dispatch-layer guard
  remains a tracked DEFERRED follow-up (NOT built this phase). The snapshot captures
  whatever happens — here, nothing to capture.
- **Open legs at run end (D-15).** In this window the final pair reverted and closed
  cleanly, so zero legs remain open at `end_date`. No run-end force-close exists in
  code regardless; the mark-to-market path is engine-default and unchanged.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Raised starting capital $100k → $500k to complete the run**
- **Found during:** Task 1 (first end-to-end run)
- **Issue:** With `$100k` starting cash and the strategy's `entry_units=1` ETH +
  β-weighted BTC short, a single pair's margin lock peaks near `$71k` (BTC short leg
  ≈ 0.53 × $125k + the ~$4.8k ETH leg). After a losing trade reduced equity, a new
  pair's lock (`$53k`) exceeded the available buying power (`$37k`), and the engine's
  real solvency assertion raised `InsufficientFundsError`. The backtest is fail-fast,
  so the run aborted mid-window rather than producing a snapshot.
- **Fix:** Raised `_CASH` to `$500k` so a single unlevered pair fits with drawdown
  headroom across the whole window. This is a RUN-CONFIG fix (test wiring only) — NO
  engine code changed, β-weighting and the Phase 2-4 accounting core are untouched.
- **Files modified:** `tests/integration/test_pair_flagship_snapshot.py`
- **Commit:** ec523e9

**2. [Rule 1 - Bug] Both-legs assertion checked the wrong column vocabulary**
- **Found during:** Task 1 (first GREEN attempt)
- **Issue:** The PAIR-01 both-legs assertion checked for `"SELL"`/`"BUY"` in the trade
  log `side` column, but `build_trade_log` emits the POSITION side (`LONG`/`SHORT`),
  not the order action — so the assertion failed even though both legs settled.
- **Fix:** Assert `"SHORT" in sides` and `"LONG" in sides` (the position-side
  vocabulary). The short leg settling end-to-end IS the flagship demonstration.
- **Files modified:** `tests/integration/test_pair_flagship_snapshot.py`
- **Commit:** ec523e9

## Authentication Gates

None.

## Known Stubs

None. Both Wave-0 collectible stubs in this file
(`test_pair_flagship_snapshot_matches`, `test_pair_flagship_determinism_double_run`)
are now fully implemented and GREEN. The generated snapshot artifacts
(`tests/golden/pair/{trades,equity}.csv`) are real run output, not placeholders.

## Threat Flags

None — this plan adds only a test + generated snapshot CSVs; no new network/auth/
file/schema surface (offline CSV, no user input). The threat-register mitigations are
all honoured: T-06-11 (snapshot written ONLY to the NEW `tests/golden/pair/` dir; the
SMA_MACD oracle is byte-unchanged), T-06-12 (Decimal end-to-end + determinism
double-run byte-identical), T-06-13 (the docstring + this SUMMARY explicitly label
the snapshot a STABILITY lock, NOT a correctness oracle), T-06-15 (coint logged, not
gated). T-06-14 stays `accept` (re-entry did not fire — recorded above).

## Self-Check: PASSED

- FOUND: tests/integration/test_pair_flagship_snapshot.py
- FOUND: tests/golden/pair/trades.csv
- FOUND: tests/golden/pair/equity.csv
- FOUND commit ec523e9 (Task 1 + Task 2)
