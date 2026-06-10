---
phase: 09-multi-entity-robustness-metrics-edges
plan: 03
subsystem: tests/e2e
tags: [e2e, robustness, real-data-slicing, sparse-bar, union-window, golden-master, oracle-dark]
requires:
  - tests/e2e/conftest.py harness (Phase 4-8 + Plan 09-01 portfolios.csv opt-in + Plan 09-02 pair commission key)
  - tests/e2e/scenario_spec.py (ScenarioSpec/PortfolioSpec)
  - tests/e2e/strategies/scripted_emitter.py (date-keyed, FixedQuantity sizing)
  - itrader.universe.membership (is_active / active_membership span primitive, Phase 3)
  - itrader.strategy_handler.strategies_handler (event.bars.get(ticker) is None -> continue sparse guard)
  - TradingSystem(csv_paths=...) D-03 passthrough
provides:
  - ROBUST-01 sparse_bar leaf (real sliced SOL, position live across the 2023-06-24/25 gap, no fill, no crash)
  - ROBUST-02 union_window leaf (real sliced AAVE 2021-07-15 listing over the union window, no pre-listing fill, no look-ahead)
  - conftest spec.data ticker-registration seam (additive superset of simulated._supported_symbols)
affects:
  - Plan 04 robust leaves (no_trade/flat/losing) continue on the same harness; the spec.data
    ticker-registration seam unblocks any future non-default-ticker leaf
tech-stack:
  added: []
  patterns:
    - real-data slicing via csv_paths (small committed CSV beside scenario.py, hand-verified post-slice bar dates)
    - additive supported-symbol registration mirroring test_universe_spans wiring (never re-derive/wipe)
    - VERIFY-note-before-freeze on real prices (load-bearing facts hand-checked, exact PnL machine-frozen)
key-files:
  created:
    - tests/e2e/robust/sparse_bar/__init__.py
    - tests/e2e/robust/sparse_bar/scenario.py
    - tests/e2e/robust/sparse_bar/test_scenario.py
    - tests/e2e/robust/sparse_bar/sol_sliced.csv
    - tests/e2e/robust/sparse_bar/eth_sliced.csv
    - tests/e2e/robust/sparse_bar/golden/trades.csv
    - tests/e2e/robust/sparse_bar/golden/summary.json
    - tests/e2e/robust/union_window/__init__.py
    - tests/e2e/robust/union_window/scenario.py
    - tests/e2e/robust/union_window/test_scenario.py
    - tests/e2e/robust/union_window/btc_sliced.csv
    - tests/e2e/robust/union_window/aave_sliced.csv
    - tests/e2e/robust/union_window/golden/trades.csv
    - tests/e2e/robust/union_window/golden/summary.json
  modified:
    - tests/e2e/conftest.py
decisions:
  - "ROBUST-01 targets SOL's genuine 2-day gap (2023-06-24/25, both present in ETH) — the ONLY SOL window where a position can be open before AND after the gap (Pitfall 1); ETH loaded data-only as the dense co-asset keeping the union ping grid ticking across the gap"
  - "ROBUST-02 uses FixedQuantity(1)/FixedQuantity(10) + 1M cash so BTC and AAVE never contend for cash — keeps the listing edge the only moving part; AAVE pre-listing BUY (07-12) is STRUCTURALLY unfillable (no AAVE bar -> generate_signal never called) rather than rejected"
  - "Rule-3 conftest seam: register spec.data tickers on simulated._supported_symbols (additive superset, mirrors test_universe_spans.py:140-149) — never re-derives/wipes, so the PATTERNS A2 BTCUSD-admission warning does not apply; oracle-dark + all prior leaves unaffected"
metrics:
  duration_min: 8
  completed: 2026-06-10
  tasks: 2
  files: 15
---

# Phase 9 Plan 03: ROBUST Span Leaves on Real Sliced Data Summary

Authored the two ROBUST span leaves on REAL committed data, SLICED to tiny
hand-verifiable windows via the Phase 3 `csv_paths` passthrough (D-03): the SOL
sparse/absent-bar leaf (ROBUST-01) and the AAVE mid-run-listing union-window leaf
(ROBUST-02). Phase 3 proved both mechanics on synthetic fixtures; this exercises
them on the REAL ingestion path with no production change — the slices are small
committed CSVs pointed at by `data={ticker: HERE/"x.csv"}`. Honors Phase 3's
explicit deferral of the "real ETH/SOL/AAVE E2E" to this phase.

## What Was Built

### Task 1 — ROBUST-01 sparse_bar (real sliced SOL across the genuine 2-day gap)
- Sliced `data/SOLUSD_1d_ohlcv.csv` to 2023-06-22..06-28 into `sol_sliced.csv` —
  MISSING the 2023-06-24/06-25 rows (SOL's genuine clean 2-day gap, both present
  in ETH per Pitfall 1). Sliced `data/ETHUSD_1d_ohlcv.csv` over the SAME window
  into `eth_sliced.csv` (DENSE — carries 06-24/06-25). ETH is loaded data-ONLY:
  no ETH strategy, just the dense co-asset whose dates keep the union ping grid
  ticking ACROSS the gap so the absent-SOL ticks actually occur.
- ONE `ScriptedEmitter` trades SOLUSD only (`FractionOfCash(0.95)`): BUY 06-22
  (fills 06-23 open 16.6289935), SELL 06-26 (fills 06-27 open 16.2695400). The SOL
  position is LIVE across 06-24/06-25 (entry 06-23, exit 06-27 — both straddle).
- Frozen goldens (hand-verified): one SOLUSD round-trip, `total_bought
  9498.857469…`, `total_sold 9293.529494…`, `realised_pnl -205.3279751…` (a small
  real-data LOSS), `trade_count 1`, `final_equity 9794.672024903335`,
  `profit_factor 0.0` (all-loss branch, finite). NO SOL fill on 06-24/06-25; the
  run completed with no crash.

### Task 2 — ROBUST-02 union_window (real sliced AAVE mid-run listing)
- Sliced `data/AAVEUSD_1d_ohlcv.csv` (lists 2021-07-15) over 2021-07-15..07-20
  into `aave_sliced.csv` (first row IS the listing day) and
  `data/BTCUSD_1d_ohlcv_2018_2026.csv` over 2021-07-10..07-20 into `btc_sliced.csv`
  (full kline schema, trades throughout). The run window STARTS 2021-07-10 —
  before AAVE's listing — so the union grid has pre-listing days where AAVE is
  absent.
- TWO `ScriptedEmitter`s on ONE 1M-cash portfolio, `FixedQuantity(1)` (BTC) /
  `FixedQuantity(10)` (AAVE) so they never contend for cash. BTC round-trips
  (BUY 07-10 → fills 07-11 open 33502.87; SELL 07-13 → fills 07-14 open 32729.12)
  proving the union window RUNS. AAVE: a 07-12 PRE-listing BUY (NEVER fires — no
  AAVE bar delivered, `generate_signal` not called) + a 07-15 listing-day BUY
  (fills 07-16 open 271.03) + a 07-18 SELL (fills 07-19 open 254.06).
- Frozen goldens (hand-verified): BTC round-trip `realised_pnl -773.75`, AAVE
  round-trip `entry_date 2021-07-16` (>= the listing, NO look-ahead) `realised_pnl
  -169.70`, `trade_count 2`, `total_realised_pnl -943.45`, `final_equity
  999056.55`, `profit_factor 0.0`. NO AAVE fill before 2021-07-15; no crash.

## Hand-Verification

Each leaf's module docstring is its full VERIFY hand-derivation (the post-slice bar
dates verified against the raw committed CSVs, which bar fires, next-bar-open fill
prices, sizing math, the gap/listing date, why no fill occurs on the absent/
pre-listing bars, and the resulting frozen numbers). Tz note (Assumption A2): the
store tz-converts to Europe/Paris (`02:00+02:00` summer DST stamps in the goldens),
but the emitter `tz_convert("UTC")`s the decision-bar date back, so every date key
is UTC and matches the CSV stamps — hand-verified post-slice. A human confirmed the
frozen goldens match each derivation to the printed precision before the freeze
locked.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] conftest spec.data ticker-registration seam**
- **Found during:** Task 1 (the first leaf using a non-default ticker, SOLUSD).
- **Issue:** The simulated exchange only admits `validate_symbol` for its
  `_supported_symbols` set = the default `*USDT` majors (`{BTCUSDT, ETHUSDT,
  ADAUSDT, DOTUSDT, SOLUSDT}`) plus BTCUSD (added in `execution_handler.init_exchanges`).
  Every prior e2e leaf used only BTCUSD + ETHUSDT, so the gap was dormant. SOLUSD
  (Task 1) and AAVEUSD (Task 2) are NOT in that set, so every order on them would
  silently REFUSE — leaving empty positions and a vacuously-passing (wrong) golden.
  The harness had NO seam to register arbitrary tickers; the `spec.exchange`
  ExchangeConfig path deliberately does NOT re-derive `_supported_symbols`
  (PATTERNS A2 warns that re-deriving from config would WIPE the post-construction
  BTCUSD admission).
- **Fix:** Added an ADDITIVE registration in `_build_and_run` (after the exchange
  block, before strategy wiring):
  `simulated._supported_symbols = set(simulated._supported_symbols) | {t.upper() for t in spec.data}`.
  This MIRRORS the integration-test wiring (`test_universe_spans.py:140-149`) which
  does the identical instance-set mutation. It is strictly a SUPERSET union — it
  never re-derives or wipes (so the PATTERNS A2 concern does not apply) — so every
  prior leaf is unaffected: BTCUSD is already added, ETHUSDT is already in the
  default set, so re-adding them is a no-op.
- **Files modified:** tests/e2e/conftest.py
- **Commit:** 856d8bf (committed with Task 1, the task that first needed it)
- **Oracle-dark verification:** `make test-integration` (12 passed, including
  `test_universe_spans`) — the BTCUSD oracle runs its own `TradingSystem`
  (`scripts/run_backtest.py`), not this harness, so the seam cannot touch it; all
  49 active e2e leaves stayed green.

### Authored deviations (within plan discretion)

**ROBUST-02 one-shape-per-leaf (the differing-end-date fold was NOT crammed in).**
The plan's Task 2 `<action>` and the VALIDATION undersampled-edge constraint
explicitly favor authoring the mid-run-listing edge cleanly and leaving
differing-end-dates as an optional fold "only if it stays hand-verifiable". I
authored ONLY the listing edge (one shape); the differing-end-date edge (BTC ends
2026-06-03 vs the majors 2026-01-08) is left out of scope for this slice to keep
the leaf trivially hand-verifiable.

**ROBUST-02 FixedQuantity sizing (not FractionOfCash) + 1M cash.** Two emitters on
one portfolio with `FractionOfCash(0.95)` would have the first BUY tie up nearly
all cash and REJECT the second — confusing the union-window proof with a cash
contention. `FixedQuantity(1)`/`FixedQuantity(10)` on 1M cash keeps the listing
edge the only moving part. Both quantities are exact / hand-derivable.

## Known Stubs

None. The three skipped determinism cases (no_trade/flat/losing) are the Plan 04
ROBUST-03 leaves not yet authored — the determinism test skips them at run time by
design (they land in Plan 04 and will turn green automatically), not a stub.

## Verification

- `poetry run pytest tests/e2e/robust/sparse_bar -m e2e -x` — 1 passed
  (diff-against-frozen; ROBUST-01 acceptance criteria met).
- `poetry run pytest tests/e2e/robust/union_window -m e2e -x` — 1 passed
  (ROBUST-02 acceptance criteria met).
- `poetry run pytest tests/e2e/robust/test_determinism.py -m e2e -k "sparse_bar or
  union_window"` — 2 passed (both double-run reproducible).
- `make test-e2e` — 49 passed, 3 skipped (the two new leaves + their determinism
  cases active; remaining 3 skips are the Plan 04 ROBUST-03 leaves).
- `make test-integration` — 12 passed (BTCUSD oracle byte-exact; the conftest
  ticker-registration seam is oracle-dark).
- Slice integrity: `sol_sliced.csv` has NO 2023-06-24/06-25 rows; `eth_sliced.csv`
  has both. `aave_sliced.csv` first data row is 2021-07-15; `btc_sliced.csv` spans
  the full 07-10..07-20 window. (Verified during slicing against the raw CSVs.)

## Self-Check: PASSED

All 14 created files + the modified conftest verified present on disk; both task
commits (856d8bf, 04d127e) verified in git history.
