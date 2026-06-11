---
phase: 09-multi-entity-robustness-metrics-edges
plan: 01
subsystem: tests/e2e
tags: [e2e, multi-portfolio, determinism, robustness, golden-master, oracle-dark]
requires:
  - tests/e2e/conftest.py harness (Phase 4-8)
  - tests/e2e/scenario_spec.py (ScenarioSpec/PortfolioSpec)
  - tests/e2e/strategies/scripted_emitter.py
  - itrader.reporting.summary.build_summary / frames.build_trade_log
provides:
  - PORTFOLIO_SNAPSHOT_COLUMNS + per-portfolio portfolios.csv opt-in serializer (D-01)
  - assert_metrics_finite no-NaN/no-inf guard helper (D-05)
  - parametrized in-process double-run determinism test scaffold (D-04, ROBUST-04)
  - MULTI-03 fanout_portfolios canary + frozen two-row asymmetric portfolios.csv
affects:
  - Plans 02-04 leaves consume the new portfolios.csv opt-in + assert_metrics_finite + determinism test
tech-stack:
  added: []
  patterns:
    - opt-in exists()-gated golden serializer (clone of cash_operations.csv lifecycle)
    - harness-internal import (tests.e2e.conftest is a real importable module)
key-files:
  created:
    - tests/e2e/robust/__init__.py
    - tests/e2e/robust/_assert_finite.py
    - tests/e2e/robust/test_determinism.py
    - tests/e2e/multi/__init__.py
    - tests/e2e/multi/fanout_portfolios/__init__.py
    - tests/e2e/multi/fanout_portfolios/scenario.py
    - tests/e2e/multi/fanout_portfolios/test_scenario.py
    - tests/e2e/multi/fanout_portfolios/bars.csv
    - tests/e2e/multi/fanout_portfolios/golden/portfolios.csv
    - tests/e2e/multi/fanout_portfolios/golden/trades.csv
    - tests/e2e/multi/fanout_portfolios/golden/summary.json
  modified:
    - tests/e2e/conftest.py
decisions:
  - "D-01: per-portfolio snapshot keyed on stable PortfolioSpec.name, harness-local, out of TRADE_COLUMNS, opt-in via portfolios.csv exists() gate"
  - "D-04: determinism test imports harness internals directly from tests.e2e.conftest (not a separate _harness.py)"
  - "D-06: foundational plan lands the shared conftest edit first + re-proves BTCUSD oracle byte-exact before parallel waves"
metrics:
  duration_min: 4
  completed: 2026-06-10
  tasks: 3
  files: 12
---

# Phase 9 Plan 01: Multi-Entity Foundation + Determinism Scaffolding Summary

Foundational, non-parallel Phase 9 scaffolding: an opt-in per-portfolio summary
snapshot serializer (`portfolios.csv`) wired into the shared e2e harness, a no-NaN
guard helper, a parametrized in-process double-run determinism test, and the
MULTI-03 `fanout_portfolios` canary proving per-portfolio cash isolation — all
oracle-dark, with the BTCUSD golden re-run byte-exact.

## What Was Built

### Task 1 — per-portfolio snapshot serializer + opt-in wiring (conftest.py)
- Added `PORTFOLIO_SNAPSHOT_COLUMNS = [portfolio, final_cash, final_equity,
  trade_count, realised_pnl]` plus `_PORTFOLIO_IDENTITY_COLUMNS` /
  `_PORTFOLIO_SORT_KEYS`, beside the existing `COMMISSION_COLUMN` /
  `_CASH_OPS_*` constants. Deliberately harness-local — NEVER merged into
  `itrader.reporting.frames.TRADE_COLUMNS` (oracle-dark, Pitfall 3).
- Extended the signature-sync chain in lockstep:
  - `_build_and_run` now returns `(system, portfolio, portfolio_ids[0], portfolio_ids)`.
  - `_assemble` accepts `portfolio_ids` and returns a 6-tuple adding
    `portfolios_frame`, built per portfolio from the EXISTING `build_trade_log` +
    `build_summary` read surface (no production change). Rows keyed on the stable
    `PortfolioSpec.name` (NEVER the UUIDv7 PortfolioId — Pitfall 2);
    `total_realised_pnl` → `realised_pnl`.
  - `_freeze` / `_diff` accept `portfolios_frame` and add an `exists()`-gated
    `portfolios.csv` block cloning the `cash_operations.csv` lifecycle.
  - `run_scenario._run` updated both unpackings.

### Task 2 — no-NaN helper + double-run determinism scaffold (tests/e2e/robust/)
- `robust/_assert_finite.py::assert_metrics_finite(metrics)` — stdlib
  `math.isfinite` over the metrics dict; raises with a "ROBUST-03" message naming
  the offending key(s) (D-05).
- `robust/test_determinism.py::test_double_run_identical` — parametrized over the
  nine Phase 9 leaf names, imports `_load_spec`/`_build_and_run`/`_assemble`
  directly from `tests.e2e.conftest`, runs each leaf twice in-process and asserts
  trades/equity/summary identical. Uses `*rest` to stay in sync with the Task-1
  arity extension. Collects clean before the wave leaves exist; skips
  not-yet-authored leaves at run time (D-04, ROBUST-04).

### Task 3 — MULTI-03 fanout_portfolios canary + byte-exact oracle re-run
- ONE `ScriptedEmitter` over BTCUSD subscribed to TWO portfolios with ASYMMETRIC
  cash (`pf_a` 10_000, `pf_b` 5_000) on the contrived smoke `bars.csv`. Both see
  the same BUY (2020-01-02 decision → fill @120) / full SELL (2020-01-04 → fill
  @140), but `FractionOfCash(0.95)` sizing deploys different quantities, so the
  two `portfolios.csv` rows differ exactly 2:1.
- Frozen `golden/portfolios.csv` (hand-verified against the VERIFY note):
  - `pf_a, 11666.6666666667, 11666.6666666667, 1, 1666.6666666667`
  - `pf_b, 5833.3333333333, 5833.3333333333, 1, 833.3333333333`
- `make test-integration` re-run byte-exact (BTCUSD oracle behavioral + numeric
  identity green) — the snapshot did not leak into `TRADE_COLUMNS`.

## Hand-Verification (MULTI-03 canary)

| Portfolio | start cash | qty (0.95·cash/114) | total_bought (×120) | total_sold (×140) | realised_pnl | final_cash |
|-----------|-----------:|--------------------:|--------------------:|------------------:|-------------:|-----------:|
| pf_a | 10_000 | 250/3 = 83.333… | 10_000.00 | 11_666.666… | 1_666.666… | 11_666.666… |
| pf_b |  5_000 | 125/3 = 41.666… |  5_000.00 |  5_833.333… |   833.333… |  5_833.333… |

The differing rows ARE the cash-isolation assertion (each portfolio's CashManager
reserves/settles its own cash). The frozen `portfolios.csv` matched this derivation
to the printed precision before locking.

## Verification

- `poetry run pytest tests/e2e/smoke -m e2e -x` — 1 passed (existing single-portfolio
  leaf unaffected; no `portfolios.csv` written for it, opt-in holds).
- `poetry run pytest tests/e2e/robust/test_determinism.py --collect-only -q` — 9
  collected clean.
- `poetry run pytest tests/e2e/multi/fanout_portfolios -m e2e -x` — 1 passed
  (diff-against-frozen).
- `poetry run pytest tests/e2e/robust/test_determinism.py -k fanout_portfolios` — 1
  passed (canary double-run reproducible).
- `make test-integration` — 12 passed (BTCUSD oracle byte-exact).
- `grep -c PORTFOLIO_SNAPSHOT_COLUMNS conftest.py` = 4 (≥3); `grep -c
  'TRADE_COLUMNS.*portfolio'` = 0; no tabs introduced.

## Deviations from Plan

None — plan executed exactly as written. The freeze additionally wrote the
always-on `trades.csv` + `summary.json` for the canary (expected harness behavior);
`summary.json` reflects `portfolios[0]` (pf_a) and matches the smoke canary's
single round-trip. `profit_factor: Infinity` in that summary is the all-win
single-trade case for pf_a's curve — the ROBUST-03 finiteness contract applies to
the dedicated degenerate leaves (Plan 04), not this canary.

## Known Stubs

None. `test_double_run_identical` skips the eight not-yet-authored Phase 9 leaves
at run time by design (they land in Plans 02-04 and will turn green automatically);
this is the intended foundational-plan-first wiring (D-06), not a stub.

## Self-Check: PASSED

All created files verified present on disk; all three task commits (fd9672d,
c3f15d0, 3100806) verified in git history.
