---
phase: 02-results-store-1
plan: 02
subsystem: results-store
tags: [results, serializers, metrics, reporting, persistence]
requires:
  - "itrader/reporting/metrics.py (single formula source — sharpe/sortino/cagr/calmar/max_drawdown/total_return/profit_factor/win_rate)"
  - "itrader/results/records.py (RunMetrics, METRIC_NAMES — 02-01)"
  - "itrader/strategy_handler/base.py (Strategy.to_dict introspection seam)"
  - "itrader/outils/time_parser.py (to_timedelta — pure util)"
provides:
  - "itrader/results/serializers.py::curate_run_settings (curated runs.settings envelope, credential-free)"
  - "itrader/results/serializers.py::curate_portfolio_params (per-strategy run_portfolios.params)"
  - "itrader/results/serializers.py::build_run_metrics (RunMetrics, 11 metrics incl. derived total_return/calmar)"
  - "itrader/results/serializers.py::build_aggregate_equity_curve (multi-portfolio, mixed-timeframe-safe)"
  - "itrader/results/serializers.py::annual_periods (explicit mixed-timeframe annualization basis)"
affects:
  - "02-04 run hook (consumes these serializers to build a RunRecord)"
tech-stack:
  added: []
  patterns:
    - "Pure duck-typed reporting builder — pandas + stdlib + itrader.reporting/results.records/outils only, zero handler imports"
    - "Curated envelope (hand-picked keys), NOT model_dump — credential-leak guard"
    - "{type, params} model envelope for fee/slippage"
    - "outer-join + ffill + bfill aggregate across portfolios"
key-files:
  created:
    - "itrader/results/serializers.py"
    - "tests/unit/results/test_results_serializers.py"
  modified: []
decisions:
  - "fee/slippage envelope built generically from vars(model) (sorted, underscore-stripped, JSON-scalar-narrowed) so any duck-typed model works — no get_fee_info noise"
  - "annual_periods uses to_timedelta (pure util, stdlib-only) per plan action; all-daily resolves to round(31_536_000/86_400)==365==PERIODS so the byte-compatible daily basis is structural, not special-cased"
  - "aggregate curve: ffill().bfill() — ffill carries each portfolio's last equity across coarse-series gaps, bfill fills the leading NaN region with the first observed value (starting cash)"
metrics:
  duration: "~15m"
  completed: "2026-06-29"
  tasks: 3
  files: 2
---

# Phase 02 Plan 02: Results Serializers Summary

Pure serializer layer (`itrader/results/serializers.py`) that turns post-run engine state
into the typed inputs the results store persists — a curated credential-free `runs.settings`
envelope, the per-strategy `run_portfolios.params` envelope, the per-portfolio/aggregate
`RunMetrics` (reusing `reporting/metrics.py` as the single formula source), the
mixed-timeframe-safe multi-portfolio aggregate equity curve, and the explicit annualization
basis. Built TDD (RED → GREEN → GREEN), `mypy --strict` clean, 16/16 unit tests green.

## What Was Built

- **`curate_run_settings(exchange, order_config, *, ...)`** — a hand-picked, flat, JSON-safe
  dict of the 14 result-relevant run knobs (run window, `rng_seed`, fee/slippage
  `{"type","params"}` envelopes, `market_execution`, exchange limits, failure-sim). It is NOT
  a `model_dump` and never reads `Settings.database_url`/`SecretStr` (T-02-03 credential-leak
  guard, proven by a no-credential test).
- **`curate_portfolio_params(strategies)`** — reads `strategy.to_dict()` (the existing JSON-safe
  introspection seam, D-06) and keeps only `_PARAM_KEYS`; single-strategy returns the lone dict,
  multi wraps as `{"strategies": [...]}`.
- **`build_run_metrics(equity_frame, trades_frame, *, periods=PERIODS)`** — all 11 `METRIC_NAMES`
  populated by reusing the `reporting/metrics.py` formulas (D-08, single formula source); the two
  derived metrics (`total_return = final/start - 1`, `calmar = cagr/abs(max_drawdown)`) come from
  the metrics helpers, never reimplemented.
- **`build_aggregate_equity_curve(equity_frames)`** — outer-joins each portfolio's `total_equity`
  on the union timestamp index, `ffill().bfill()` (leading region = that portfolio's starting cash),
  sums across portfolios (D-14). Matched timeframes reduce to the exact per-bar sum; a 1d+1h pair
  ffills with no NaN and no dropped row.
- **`annual_periods(timeframes)`** — finest-timeframe periods-per-year (max across the run);
  `PERIODS=365` for all-daily/empty (D-14 explicit basis).
- Helpers `_json_scalar`, `_enum_value`, `_model_envelope` keep the output JSON-safe at the
  serialization edge (Decimal → float).

## How It Was Verified

- `PYTHONPATH="$PWD" python -m pytest tests/unit/results -q` → **18 passed** (16 new serializer
  tests + 2 pre-existing ABC tests), warning-clean under `filterwarnings=["error"]`.
- `PYTHONPATH="$PWD" python -m mypy --strict itrader` → **Success: no issues found in 177 source files**.
- Purity contract held: `serializers.py` imports only `decimal`/`enum`/`typing` (stdlib), `pandas`,
  `itrader.outils.time_parser` (pure util), `itrader.reporting.metrics`, `itrader.results.records`
  — zero handler imports, no SQL, no engine run.
- TDD gate sequence: `test(02-02)` RED commit precedes both `feat(02-02)` GREEN commits.

> Tooling note: the worktree's local `.venv` is near-empty (6 packages); verification ran on the
> main repo `.venv` python with `PYTHONPATH="$PWD"` so worktree source edits are picked up
> (matches the documented worktree `.venv`-shadowing workaround). GATE-01 is structurally
> unaffected — nothing on the backtest run path imports the new module.

## Deviations from Plan

None — plan executed as written across all three tasks (RED + two GREEN). `build_run_record` was
explicitly left to the 02-04 hook (executor discretion per the Task 3 action).

## Commits

- `dd8b00c` test(02-02): add failing serializer tests + typed stub module (RED)
- `96e69d7` feat(02-02): curated run-settings + per-strategy params serializers (GREEN)
- `657f4ec` feat(02-02): RunMetrics builder + aggregate equity curve + annualization (GREEN)

## Self-Check: PASSED

- FOUND: itrader/results/serializers.py
- FOUND: tests/unit/results/test_results_serializers.py
- FOUND commit: dd8b00c
- FOUND commit: 96e69d7
- FOUND commit: 657f4ec
