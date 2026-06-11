---
phase: 09-multi-entity-robustness-metrics-edges
plan: 04
subsystem: tests/e2e
tags: [e2e, robustness, degenerate-metrics, no-nan, determinism, golden-master, oracle-dark]
requires:
  - tests/e2e/conftest.py harness (Phase 4-8 + Plan 09-01 portfolios.csv opt-in + 09-02 pair key + 09-03 spec.data registration)
  - tests/e2e/robust/_assert_finite.py::assert_metrics_finite (Plan 09-01, D-05)
  - tests/e2e/robust/test_determinism.py (Plan 09-01, ROBUST-04 double-run scaffold)
  - tests/e2e/scenario_spec.py (ScenarioSpec/PortfolioSpec)
  - tests/e2e/strategies/scripted_emitter.py (date-keyed, FixedQuantity sizing)
  - itrader.reporting.metrics (degenerate guards) + itrader.reporting.summary.build_metrics_block
provides:
  - ROBUST-03a no_trade leaf (zero closed trades, all metrics 0.0 finite)
  - ROBUST-03b flat leaf (+10 win / -10 loss round-trips net zero, profit_factor 1.0 FINITE)
  - ROBUST-03c losing leaf (single -10 round-trip, profit_factor 0.0 all-loss finite)
  - test_metrics_finite.py explicit no-NaN/no-inf assertion over the three degenerate leaves (D-05)
  - ROBUST-04 finalized: full nine-leaf double-run determinism test, skip guard removed
affects:
  - Phase 9 metrics-edges cluster (ROBUST-03/04) complete; no downstream plan consumes these leaves
tech-stack:
  added: []
  patterns:
    - degenerate-metrics leaf = contrived flat/win-loss/loss bars + hand-verified VERIFY note + frozen summary.json metrics block
    - explicit finiteness assert over the live metrics dict (D-05) layered on top of the exact golden diff (Pitfall 5)
    - empty-script ScriptedEmitter = the simplest zero-trade shape (no REJECTED order to reason about)
key-files:
  created:
    - tests/e2e/robust/no_trade/__init__.py
    - tests/e2e/robust/no_trade/scenario.py
    - tests/e2e/robust/no_trade/test_scenario.py
    - tests/e2e/robust/no_trade/bars.csv
    - tests/e2e/robust/no_trade/golden/trades.csv
    - tests/e2e/robust/no_trade/golden/summary.json
    - tests/e2e/robust/flat/__init__.py
    - tests/e2e/robust/flat/scenario.py
    - tests/e2e/robust/flat/test_scenario.py
    - tests/e2e/robust/flat/bars.csv
    - tests/e2e/robust/flat/golden/trades.csv
    - tests/e2e/robust/flat/golden/summary.json
    - tests/e2e/robust/losing/__init__.py
    - tests/e2e/robust/losing/scenario.py
    - tests/e2e/robust/losing/test_scenario.py
    - tests/e2e/robust/losing/bars.csv
    - tests/e2e/robust/losing/golden/trades.csv
    - tests/e2e/robust/losing/golden/summary.json
    - tests/e2e/robust/test_metrics_finite.py
  modified:
    - tests/e2e/robust/test_determinism.py
decisions:
  - "ROBUST-03a no_trade uses an EMPTY ScriptedEmitter script {} (generate_signal returns None every tick -> no order ever emitted) rather than over_cash_reject's REJECTED-order shape — the simplest zero-trade path with no rejected order to reason about"
  - "ROBUST-03b/c keep profit_factor FINITE by construction (A3 load-bearing): flat = a +10 WIN + a -10 LOSS (gross_loss>0 -> PF 1.0, NOT the all-win inf branch); losing = a single -10 LOSS (gross_profit=0 -> PF 0.0 all-loss branch). FixedQuantity(1) makes per-trade PnL integer-exact"
  - "ROBUST-04 finalized: the Plan-01 not-yet-authored skip guard removed now all nine leaves exist; a missing scenario.py now _load_spec-fails loudly (correct once every leaf is expected)"
metrics:
  duration_min: 6
  completed: 2026-06-10
  tasks: 3
  files: 20
---

# Phase 9 Plan 04: Degenerate-Metrics Leaves + ROBUST-04 Finalization Summary

Authored the three ROBUST-03 degenerate-metrics leaves (no_trade / flat / losing),
each freezing its `summary.json` metrics block AND guarded by an explicit
no-NaN/no-inf assertion (D-05), then finalized ROBUST-04 across all nine Phase 9
leaves by removing the Plan-01 not-yet-authored skip guard. These leaves cover the
EXISTING `reporting/metrics.py` degenerate-input guards (no NaN, no div-by-zero in
Sharpe/drawdown/profit-factor) end-to-end — no production change. Full e2e tree
green; BTCUSD oracle byte-exact.

## What Was Built

### Task 1 — three ROBUST-03 degenerate-metrics leaves (hand-verified + frozen)
- **no_trade (ROBUST-03a):** an `ScriptedEmitter` with an EMPTY script `{}` over a
  flat constant-100 `bars.csv` — `generate_signal` returns `None` every tick, so NO
  order is ever emitted (the simplest zero-trade shape, no REJECTED order to reason
  about, contrast over_cash_reject). EMPTY `trades.csv` (`trade_count=0`); every
  metric is the empty/flat-guard 0.0 (sharpe zero-std, sortino zero-downside, cagr
  start==final, max_drawdown flat, profit_factor empty-frame, win_rate empty) — all
  FINITE. `final_cash = final_equity = 10_000`.
- **flat (ROBUST-03b):** TWO round-trips on one portfolio via `FixedQuantity(1)` — a
  +10 WIN (buy @100 / sell @110) then a -10 LOSS (buy @110 / sell @100), net 0.
  Because BOTH a positive and a negative trade exist, `profit_factor = gross_profit
  / gross_loss = 10/10 = 1.0` — FINITE, NOT the all-win `inf` branch (the
  load-bearing A3 constraint). `win_rate = 0.5`; sharpe/sortino/cagr/max_drawdown
  finite over the dip-and-return curve. `final_equity = 10_000`.
- **losing (ROBUST-03c):** a single net-NEGATIVE round-trip via `FixedQuantity(1)` —
  buy @110 / sell @100 -> PnL -10. With no winning trade, `profit_factor` takes the
  all-LOSS branch -> 0.0 (finite; the all-win `inf` branch is structurally
  unreachable). `win_rate = 0.0`; `max_drawdown` finite negative; sharpe/sortino/cagr
  finite. `final_equity = 9_990`.
- Each leaf's module docstring is its full VERIFY hand-derivation (bars, which bar
  fires, next-bar-open fill prices, exact PnL, the EXACT metrics block, and WHICH
  guard fires / WHY each metric is finite). Frozen ONE leaf at a time via `--freeze`,
  hand-verified against the derivation before locking.

### Task 2 — explicit no-NaN/no-inf metrics assertion (D-05)
- `tests/e2e/robust/test_metrics_finite.py` parametrized over EXACTLY the three
  degenerate leaves. Imports `assert_metrics_finite` from `tests.e2e.robust._assert_finite`
  and the harness internals `_load_spec`/`_build_and_run`/`_assemble` from
  `tests.e2e.conftest` (mirrors `test_determinism.py`'s import shape; `*rest` unpack
  stays in sync with the Plan-01 `portfolio_ids` arity). Each case re-runs the leaf
  in-process, extracts the live `summary["metrics"]`, and calls
  `assert_metrics_finite` — making "no NaN/no inf" the EXPLICIT documented ROBUST-03
  contract (catches a NaN a hand-verifier might otherwise silently freeze, since
  exact equality alone fails confusingly on `nan != nan` — Pitfall 5).

### Task 3 — ROBUST-04 finalized across all nine leaves
- `tests/e2e/robust/test_determinism.py`: removed the Plan-01 not-yet-authored skip
  guard (`if not scenario_path.exists(): pytest.skip(...)`) now that all nine Phase 9
  leaves exist. `PHASE9_LEAVES` already listed all nine statically; the
  parametrization now runs the FULL nine-leaf double-run set unconditionally. A
  missing `scenario.py` now `_load_spec`-fails loudly — correct once every leaf is
  expected to exist. Docstring/comments updated to reflect the completed wave.

## Hand-Verification

Each leaf's docstring VERIFY note hand-derives the fills (if any), realised PnL, and
the EXACT metrics block. The frozen goldens matched each derivation to the printed
precision before locking:
- no_trade: empty trades.csv, metrics all 0.0, no `Infinity`.
- flat: two LONG round-trips (+10 / -10), `total_realised_pnl 0.0`,
  `profit_factor 1.0`, `win_rate 0.5`, `final_equity 10_000.0`.
- losing: one LONG round-trip `realised_pnl -10.0`, `profit_factor 0.0`,
  `win_rate 0.0`, `final_equity 9_990.0`.

## Deviations from Plan

None — plan executed exactly as written. The "no_trade via empty script vs REJECTED
order" choice was explicitly left to author discretion by the plan (`<action>`: "NO
order, not a REJECTED one — author's discretion which produces zero trades
cleanly"); the empty script is the cleaner zero-trade path.

## Known Stubs

None.

## Verification

- `poetry run pytest tests/e2e/robust/no_trade tests/e2e/robust/flat tests/e2e/robust/losing -m e2e` — 3 passed.
- `poetry run pytest tests/e2e/robust/test_metrics_finite.py -m e2e -x` — 3 passed.
- `poetry run pytest tests/e2e/robust/test_determinism.py -m e2e` — 9 passed (all
  nine Phase 9 leaves double-run byte-identical, no skips).
- `make test-e2e` — 58 passed (full e2e tree green, including all Phase 9 leaves;
  previously 49 passed + 3 skipped → the 3 ROBUST-03 leaves + 3 determinism cases +
  3 metrics-finite cases are now all active).
- `make test-integration` — 12 passed (BTCUSD oracle byte-exact; the new leaves are
  oracle-dark — the oracle runs its own `TradingSystem`, not this harness).
- `grep -L Infinity tests/e2e/robust/{no_trade,flat,losing}/golden/summary.json` —
  all three listed (no `inf` serialized).

## Self-Check: PASSED

All 19 created files + the modified `test_determinism.py` verified present on disk;
all three task commits (b28ef1c, 1c896d0, 480a74b) verified in git history.
