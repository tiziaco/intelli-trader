---
phase: 04-e2e-harness-framework
plan: 03
subsystem: testing
tags: [e2e, canary, harness, golden-master, freeze, hand-verified, D-01, D-04, D-10, D-11, D-12, D-13, E2E-02, E2E-03, E2E-04]
requires:
  - "tests/e2e/conftest.py::run_scenario (Plan 02 shared harness fixture + --freeze)"
  - itrader.strategy_handler.base.Strategy (ABC: generate_signal, buy() sugar, max_window warmup gate)
  - itrader.core.sizing (FractionOfCash, SignalIntent, TradingDirection)
  - itrader.price_handler.store.csv_store.CsvPriceStore (real CSV path, required Binance-kline header)
  - itrader.trading_system.backtest_trading_system.TradingSystem (the real engine the harness wires)
provides:
  - "tests/e2e/strategies/single_market_buy.py::SingleMarketBuy (shared contrived strategy — one MARKET buy + one full MARKET exit by completed-bar count)"
  - "tests/e2e/smoke/single_market_buy/ (the ONE hand-verified canary leaf — copy-template for Phase 6-9 authors)"
  - "tests/e2e/data/ (committed shared reusable-input dir, D-10)"
  - "frozen + HAND-VERIFIED-LOCKED golden/{trades.csv,summary.json} (regression-lock for the full CsvPriceStore->feed->signal->order->fill path)"
affects:
  - "tests/e2e/conftest.py (Rule-1 fix: _roundtrip the fresh frame through CSV before diffing — see Deviations)"
  - "future: Phase 6-9 scenario authors copy this leaf folder verbatim as their starting template"
tech-stack:
  added: []
  patterns:
    - "Self-contained canary leaf: own strategy ref + scenario.py (ScenarioSpec + VERIFY note) + one-liner test + contrived bars.csv + golden/ (D-12 copy-template)"
    - "D-01 one-liner leaf test: def test_x(run_scenario): run_scenario(HERE) — no diff body, the harness owns the diff"
    - "D-04 shared strategy library: contrived strategy lives in tests/e2e/strategies/ and is REFERENCED (not inlined) by scenario.py"
    - "D-11 contrived round-number bars: hand-picked opens make next-bar-open fill price + held PnL hand-computable (NOT a real-data slice)"
    - "D-13 VERIFY hand-derivation docstring + once-only human sign-off BEFORE freeze (golden proves stability, not correctness)"
    - "Diff self-trust: mutate one golden cell -> FAIL -> revert -> PASS proves the diff is not a no-op (T-04-07)"
key-files:
  created:
    - tests/e2e/strategies/__init__.py
    - tests/e2e/strategies/single_market_buy.py
    - tests/e2e/data/.gitkeep
    - tests/e2e/smoke/__init__.py
    - tests/e2e/smoke/single_market_buy/__init__.py
    - tests/e2e/smoke/single_market_buy/scenario.py
    - tests/e2e/smoke/single_market_buy/test_scenario.py
    - tests/e2e/smoke/single_market_buy/bars.csv
    - tests/e2e/smoke/single_market_buy/golden/trades.csv
    - tests/e2e/smoke/single_market_buy/golden/summary.json
  modified:
    - tests/e2e/conftest.py
decisions:
  - "D-12: exactly ONE contrived, hand-verifiable canary ships (single MARKET buy -> one known round-trip trade), doubling as the Phase 6-9 copy-template"
  - "D-04: the contrived SingleMarketBuy strategy lives in the shared tests/e2e/strategies/ library and is referenced (not inlined) by scenario.py"
  - "D-11: the canary uses leaf-local contrived round-number bars.csv (6 daily bars, opens 100/110/120/130/140/150) so the fill prices and PnL are hand-computable; D-10: the shared tests/e2e/data/ dir is committed for reusable inputs the canary does not use"
  - "D-13/E2E-04: the golden was HAND-VERIFIED for correctness once (committed VERIFY note + human sign-off) BEFORE the freeze lock — a regression-lock proves stability, not correctness"
  - "Strategy fires by COMPLETED-BAR COUNT (max_window set high so len(bars) == count of bars asof): BUY on len==fire_on_bar (2), full exit on len==exit_on_bar (4); each MARKET order fills NEXT-bar-open"
  - "exchange=None on the spec -> zero-fee / no-slippage simulated-exchange defaults (Open Q1 ExchangeConfig fee/slippage threading is Phase 7)"
metrics:
  duration: ~25 min (across both sessions incl. the E2E-04 human checkpoint)
  completed: 2026-06-09
  tasks: 2
  files: 11
---

# Phase 04 Plan 03: Canary E2E Scenario + SingleMarketBuy Strategy Summary

Shipped the ONE contrived, hand-verifiable E2E canary (D-12): a deterministic single MARKET buy followed by one full MARKET exit producing one known round-trip trade through the REAL `CsvPriceStore`->feed->signal->order->fill path on a tiny hand-written `bars.csv`, dogfooding the Plan 02 `run_scenario` harness and serving as the literal copy-template for Phase 6-9 scenario authors. The frozen goldens were hand-verified for correctness once (committed VERIFY note + human E2E-04 sign-off) and then locked as a regression baseline; the diff was proven to catch drift.

## What Was Built

### Task 1 — SingleMarketBuy strategy + self-contained canary leaf + candidate goldens (commit 34bcf9a)
- **`tests/e2e/strategies/single_market_buy.py`** (D-04 shared library): `class SingleMarketBuy(Strategy)` whose `__init__(self, timeframe, tickers, *, fire_on_bar=2, exit_on_bar=4)` calls `super().__init__("single_market_buy", ..., sizing_policy=FractionOfCash(Decimal("0.95")), direction=TradingDirection.LONG_ONLY, allow_increase=False)`. `generate_signal` fires by completed-bar count: `self.buy(ticker)` when `len(bars) == fire_on_bar`, the full exit when `len(bars) == exit_on_bar`, else `None` — exactly ONE round-trip trade. `tests/e2e/strategies/__init__.py` is the empty package marker.
- **`tests/e2e/smoke/single_market_buy/`** — the self-contained canary leaf (`__init__.py`, `tests/e2e/smoke/__init__.py`):
  - `scenario.py` — the `ScenarioSpec` (published as module-level `SCENARIO`) reusing the real engine wiring (`start`/`end`/`timeframe`/`ticker`/`starting_cash`/`data`/`strategies`/`portfolios`/`exchange=None`) plus a minimal `PortfolioSpec(user_id/name/cash)`. The module docstring IS the VERIFY hand-derivation (D-13): contrived bars, which bar fires BUY/SELL, the next-bar-open fill prices, the `FractionOfCash(0.95)` sizing math, and the resulting single trade + final equity — WHY each frozen number is what it is.
  - `test_scenario.py` — the D-01 one-liner ONLY: `def test_single_market_buy(run_scenario): run_scenario(HERE)`. No diff body.
  - `bars.csv` — a contrived 6-bar daily CSV (D-11) with the exact Binance-kline header `Open time,Open,High,Low,Close,Volume`, tz-aware Open time, round-number opens (100/110/120/130/140/150) so the fills and PnL are hand-computable.
  - `golden/trades.csv` + `golden/summary.json` — the candidate goldens WRITTEN by `--freeze`; exactly ONE trade row.
- **`tests/e2e/data/.gitkeep`** (D-10): commits the shared reusable-input dir; the canary uses its leaf-local `bars.csv`, not shared data.

### Task 2 — E2E-04 golden freeze: hand-verified lock + diff self-trust (commit d766392)
- **Human checkpoint (E2E-04, blocking):** the human verified the frozen goldens MATCH the VERIFY hand-derivation and responded **"approved"**. The verified facts: a single LONG BTCUSD trade — buy @120 on 2020-01-03, sell @140 on 2020-01-05, `realised_pnl` 1,666.666…, `final_equity` 11,666.666…, `trade_count` 1.
- **`scenario.py`:** added a `HAND-VERIFIED & LOCKED (E2E-04 / D-13)` stamp at the top of the VERIFY note recording the human sign-off, the load-bearing numbers, and the diff-self-trust proof — so the lock is durable in-tree, not just in planning artifacts. Re-freeze is gated on re-verifying the derivation via the deliberate `--freeze` flag.
- **Diff self-trust proven (T-04-07):** mutated `realised_pnl` in `golden/trades.csv` (1666.666… -> 1777.666…) -> `poetry run pytest tests/e2e/smoke/single_market_buy -x` FAILED -> `git checkout -- golden/trades.csv` restored byte-identical -> re-ran PASS. Tree left clean (mutation not committed).

## How It Was Verified

- **Diff catches drift:** mutated-golden run FAILED (`1 failed`); after `git checkout --` revert the run PASSED (`1 passed`); `diff` against a backup confirmed the restore was byte-identical and `git status` was clean.
- **Canary green (diff-only, post-lock):** `poetry run pytest tests/e2e/smoke/single_market_buy -x -q` -> `1 passed`.
- **e2e bucket green:** `poetry run pytest tests/ -m "e2e" -q` -> `1 passed, 734 deselected` (canary collected under the `e2e` marker).
- **Full suite green:** `poetry run pytest tests/ -q` -> **735 passed, 0 failures** (canary + oracle + units; warning-clean under `filterwarnings=["error"]`).
- **Idempotence:** the diff-only re-runs pass byte-identical (ROBUST-04 in miniature) — no auto-heal, goldens were not rewritten on a non-`--freeze` run.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] `_diff` compared the in-memory fresh frame against the read-from-CSV golden (dtype/precision mismatch)** — committed in Task 1 (34bcf9a)
- **Found during:** Task 1, first diff-only re-run after `--freeze`.
- **Issue:** The Plan 02 harness `_diff` passed the in-memory `trades` frame (tz-aware `Timestamp` dates, full-precision `Decimal`-as-object money) straight into `assert_frame_equal` against the golden loaded via `pd.read_csv` (object dates, 10-dp float money). The two sides could never be byte-equal — the conftest's own comment already documented the intent to round-trip, but the code did not.
- **Fix:** added `_roundtrip(frame, columns)` which serializes the fresh frame through the IDENTICAL `to_csv(..., float_format=FLOAT_FORMAT)` -> `read_csv` path `_freeze` uses, normalizing BOTH sides to the same dtypes/repr before the exact diff. Mirrors the oracle, which reads both sides from CSV.
- **Files modified:** `tests/e2e/conftest.py`
- **Commit:** 34bcf9a

This Rule-1 fix touched the shared Plan 02 harness file. It is corrective (the harness diff was non-functional for any real scenario, not just the canary) and is covered by the full suite + the diff-self-trust proof.

## Authentication Gates
None.

## Known Stubs
None. The canary is fully wired end-to-end through the real engine; the goldens are hand-verified-locked, not placeholders.

## Threat Flags
None — internal test infrastructure, no external inputs/auth/network/secrets. The planned tampering mitigations were applied exactly:
- **T-04-06** (golden frozen without verification): the BLOCKING human-verify checkpoint gated the lock; the frozen trade/PnL was confirmed against the committed VERIFY hand-derivation before commit (human responded "approved").
- **T-04-07** (diff is a no-op): proven false — a mutated golden cell made the canary FAIL, then reverted clean and PASSED.
- **T-04-08** (strategy fires wrong count): `golden/trades.csv` has exactly ONE data row; the VERIFY note derives the single round-trip trade.

## Self-Check: PASSED
- FOUND: tests/e2e/strategies/single_market_buy.py
- FOUND: tests/e2e/smoke/single_market_buy/scenario.py
- FOUND: tests/e2e/smoke/single_market_buy/test_scenario.py
- FOUND: tests/e2e/smoke/single_market_buy/bars.csv
- FOUND: tests/e2e/smoke/single_market_buy/golden/trades.csv
- FOUND: tests/e2e/smoke/single_market_buy/golden/summary.json
- FOUND: tests/e2e/data/.gitkeep
- FOUND: `HAND-VERIFIED & LOCKED` stamp in scenario.py VERIFY note
- FOUND commit 34bcf9a (Task 1)
- FOUND commit d766392 (Task 2)
