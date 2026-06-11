---
phase: 09-multi-entity-robustness-metrics-edges
plan: 02
subsystem: tests/e2e
tags: [e2e, multi-ticker, multi-strategy, cash-contention, golden-master, oracle-dark]
requires:
  - tests/e2e/conftest.py harness (Phase 4-8 + Plan 09-01 portfolios.csv opt-in)
  - tests/e2e/scenario_spec.py (ScenarioSpec/PortfolioSpec)
  - tests/e2e/strategies/scripted_emitter.py (multi-ticker tickers list)
  - itrader.reporting.frames.build_trade_log (pair column spans tickers)
  - itrader.reporting.cash_operations.build_cash_operations (RESERVATION lens)
  - itrader.reporting.orders.build_orders_snapshot (REJECTED loser row)
provides:
  - MULTI-01 two_tickers leaf (one emitter, two tickers, trades.csv spans both)
  - MULTI-02 two_strategies leaf (two emitters, one portfolio, both fill)
  - MULTI-04 contended_cash leaf (deterministic winner fills, loser cash_reservation REJECTED, no orphan)
  - conftest commission-merge key now includes `pair` (multi-ticker round-trip safe)
affects:
  - Plans 03-04 robust leaves continue on the same harness; the commission-merge
    `pair` key unblocks any future multi-ticker round-trip leaf
tech-stack:
  added: []
  patterns:
    - one-shape-per-leaf contrived-bars + hand-verified VERIFY note (the e2e house style)
    - opt-in exists()-gated golden serializer (orders.csv + cash_operations.csv placeholders)
    - registration-order determinism (D-02): spec.strategies[0] wins, [1] loses
key-files:
  created:
    - tests/e2e/multi/two_tickers/__init__.py
    - tests/e2e/multi/two_tickers/scenario.py
    - tests/e2e/multi/two_tickers/test_scenario.py
    - tests/e2e/multi/two_tickers/bars.csv
    - tests/e2e/multi/two_tickers/bars_eth.csv
    - tests/e2e/multi/two_tickers/golden/trades.csv
    - tests/e2e/multi/two_tickers/golden/summary.json
    - tests/e2e/multi/two_strategies/__init__.py
    - tests/e2e/multi/two_strategies/scenario.py
    - tests/e2e/multi/two_strategies/test_scenario.py
    - tests/e2e/multi/two_strategies/bars.csv
    - tests/e2e/multi/two_strategies/bars_eth.csv
    - tests/e2e/multi/two_strategies/golden/trades.csv
    - tests/e2e/multi/two_strategies/golden/summary.json
    - tests/e2e/multi/contended_cash/__init__.py
    - tests/e2e/multi/contended_cash/scenario.py
    - tests/e2e/multi/contended_cash/test_scenario.py
    - tests/e2e/multi/contended_cash/bars.csv
    - tests/e2e/multi/contended_cash/bars_eth.csv
    - tests/e2e/multi/contended_cash/golden/trades.csv
    - tests/e2e/multi/contended_cash/golden/summary.json
    - tests/e2e/multi/contended_cash/golden/orders.csv
    - tests/e2e/multi/contended_cash/golden/cash_operations.csv
  modified:
    - tests/e2e/conftest.py
decisions:
  - "MULTI-04: spec.ticker = the LOSER's ticker (BTCUSD) so the spec.ticker-scoped orders.csv captures EXACTLY the one REJECTED loser row; the WINNER trades a DIFFERENT ticker (ETHUSDT) so its lifecycle lands in the portfolio-wide trades.csv + cash_operations.csv"
  - "MULTI-04 used two tickers (author's discretion explicitly allowed by the plan) + a bars_eth.csv not in the plan's files list — the two-ticker shape gives the cleanest 'exactly one REJECTED row' orders.csv"
metrics:
  duration_min: 5
  completed: 2026-06-10
  tasks: 3
  files: 24
---

# Phase 9 Plan 02: Multi-Ticker & Multi-Strategy Breadth Summary

Closed the MULTI cluster's three remaining leaves (MULTI-03 was the Plan-01 canary):
one strategy spanning two tickers (MULTI-01), two strategies coexisting on one
portfolio (MULTI-02), and two strategies deterministically contending for one
portfolio's cash (MULTI-04). Each is a one-shape-per-leaf contrived-bars scenario,
hand-verified against a VERIFY note then frozen. No production change; one
backward-compatible, oracle-dark harness fix unblocked the first multi-ticker
round-trip.

## What Was Built

### Task 1 — MULTI-01 two_tickers (one strategy, two tickers)
- ONE `ScriptedEmitter("1d", ["BTCUSD", "ETHUSDT"], FixedQuantity(10))` over ONE
  portfolio. `generate_signal` is invoked per ticker, so the one date-keyed script
  (`BUY 2020-01-02`, `SELL 2020-01-04`) opens+closes an independent round-trip on
  EACH ticker.
- Frozen `trades.csv` carries BOTH `pair` rows in the same frame (the MULTI-01
  proof that `build_trade_log` spans every traded ticker):
  - `BTCUSD`: avg_bought 120, avg_sold 140, realised_pnl 200.
  - `ETHUSDT`: avg_bought 210, avg_sold 230, realised_pnl 200.
- `summary.json`: final_cash 10_400, final_equity 10_400, trade_count 2,
  total_realised_pnl 400. Default trades+summary only (no opt-in).

### Task 2 — MULTI-02 two_strategies (two strategies, one portfolio)
- TWO `ScriptedEmitter` instances — one on BTCUSD, one on ETHUSDT — both subscribed
  to ONE ample-cash portfolio. Combined reservation 3_000 << 10_000, so NO cap and
  NO contention: both fill. This is the clean CONTRAST to MULTI-04.
- Frozen `trades.csv` carries both round-trips (numerically identical to MULTI-01 by
  construction; the DISTINGUISHING fact is the SHAPE — `spec.strategies` holds TWO
  emitter instances). Default trades+summary only.

### Task 3 — MULTI-04 contended_cash (two strategies contend, D-02)
- TWO emitters on ONE portfolio, both BUY on the SAME decision bar (2020-01-02),
  but the portfolio cannot fund both. Registration order is the determinism contract
  (D-02): `spec.strategies[0]` (WINNER, ETHUSDT, FixedQuantity 95) reserves 9_500
  FIRST and round-trips (PnL 1_900); `spec.strategies[1]` (LOSER, BTCUSD,
  FixedQuantity 50) reaches the synchronous cash-reservation gate SECOND with only
  500 available → `InsufficientFundsError` → audited PENDING→REJECTED
  (`triggered_by="cash_reservation"`), no orphan.
- `spec.ticker = "BTCUSD"` (the loser's ticker) scopes `orders.csv` to EXACTLY the
  one REJECTED loser row, sized quantity 50 (cash_reservation fires AFTER sizing —
  contrast ADMIT-03's gate-before-sizing quantity=0).
- Frozen goldens (all four, opt-in placeholders committed before freeze):
  - `orders.csv`: `STANDALONE,BTCUSD,MARKET,BUY,REJECTED,...,50,...,0` (one row).
  - `cash_operations.csv`: winner `ORDER-001 RESERVATION 9500`,
    `RELEASE_RESERVATION 9500`, `ORDER-002 TRANSACTION_DEBIT -9500`,
    `ORDER-003 TRANSACTION_CREDIT 11400` — and NO loser row (no orphan).
  - `trades.csv`: the winner's ETHUSDT round-trip (total_bought 9_500, total_sold
    11_400, PnL 1_900); the loser never opens a position.
  - `summary.json`: final_cash 11_900, trade_count 1, total_realised_pnl 1_900.

## Hand-Verification

Each leaf's module docstring is its full VERIFY hand-derivation (bars, which bar
fires, fill prices, reservation/cash trail, resulting frozen numbers). A human
confirms the frozen golden matches the derivation before the freeze locks. The
frozen MULTI-04 ledger (RESERVATION 9_500, no loser row) and the REJECTED orders.csv
row (sized 50) matched the derivation to the printed precision before locking.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] conftest commission-merge key now includes `pair`**
- **Found during:** Task 1 (the first multi-ticker round-trip in a single
  `trades.csv`).
- **Issue:** The harness commission merge keyed on `(entry_date, exit_date, side)`
  with `validate="one_to_one"` (WR-03). MULTI-01's two round-trips share an identical
  `(entry_date, exit_date, side)` across DIFFERENT tickers (BTCUSD+ETHUSDT both LONG,
  same entry/exit bars), so the key is non-unique and the one_to_one merge tripped a
  pandas `MergeError` before any golden could be written.
- **Fix:** Added `pair` (= `Position.ticker`, the trade frame's existing ticker
  column, frames.py:35 / Position.to_dict :264) to both `commission_rows` and the
  merge `on=[...]`. Backward-compatible and oracle-dark: single-ticker leaves already
  have a unique `pair`, so their merged commission column is identical; the BTCUSD
  integration oracle re-ran byte-exact (12 passed) and all 41 prior e2e leaves stayed
  green.
- **Files modified:** tests/e2e/conftest.py
- **Commit:** 9a0ec2a

### Authored deviation (within plan discretion)

**MULTI-04 two-ticker shape + bars_eth.csv (not in the plan's files list).** The
plan's Task 3 `<action>` explicitly allows "two tickers, author's discretion". Using
the WINNER on ETHUSDT and the LOSER on BTCUSD = `spec.ticker` gives the cleanest
"exactly one REJECTED row" in `orders.csv` (the spec.ticker-scoped query captures
only the loser), so I added a `bars_eth.csv` for the winner. The winner's round-trip
still lands in the portfolio-wide `trades.csv` and its lifecycle in the
portfolio-wide `cash_operations.csv`. All acceptance criteria are met.

## Known Stubs

None.

## Verification

- `poetry run pytest tests/e2e/multi/two_tickers -m e2e -x` — 1 passed.
- `poetry run pytest tests/e2e/multi/two_strategies -m e2e -x` — 1 passed.
- `poetry run pytest tests/e2e/multi/contended_cash -m e2e -x` — 1 passed.
- `poetry run pytest tests/e2e -m e2e` — 45 passed, 5 skipped (the three new leaves +
  the determinism trio now active; remaining 5 skips are the Plan 03-04 robust leaves
  not yet authored).
- `poetry run pytest tests/e2e/robust/test_determinism.py -m e2e -k "two_tickers or
  two_strategies or contended_cash"` — 3 passed (all double-run reproducible).
- `make test-integration` — 12 passed (BTCUSD oracle byte-exact; the conftest
  commission-merge `pair` key is oracle-dark).

## Self-Check: PASSED

All 24 created files verified present on disk; all three task commits (9a0ec2a,
c7771d8, 96250a1) verified in git history.
