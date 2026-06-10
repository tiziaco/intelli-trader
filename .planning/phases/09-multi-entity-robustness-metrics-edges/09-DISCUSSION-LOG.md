# Phase 9: Multi-Entity, Robustness & Metrics Edges - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-10
**Phase:** 9-Multi-Entity, Robustness & Metrics Edges
**Areas discussed:** Multi-entity capture, ROBUST-01/02 data source, Determinism mechanism, Degenerate metrics

---

## Multi-entity capture (MULTI-01 / MULTI-03 / MULTI-04)

| Option | Description | Selected |
|--------|-------------|----------|
| Opt-in per-portfolio snapshot | One new opt-in, `exists()`-gated frame (row per portfolio: final_cash / final_equity / trade_count / realised_pnl), mirroring cash_operations.csv. MULTI-04 reuses cash_operations.csv; MULTI-01 rides existing trades.csv. | ✓ |
| Per-portfolio golden subdirs | Extend _assemble to freeze a full trades.csv/summary.json per portfolio (golden/PORTFOLIO-A/...); most faithful but heaviest layout change. | |
| You decide | — | |

**User's choice:** Opt-in per-portfolio snapshot (option 1).
**Notes:** User first leaned toward option 2 and asked whether it would change the
`PortfolioHandler` class. Verified against code: NO — both options are test-harness
(`conftest.py`) only; the harness already builds N portfolios, and the read surface
(`get_portfolio` / `get_active_portfolios` / `get_portfolio_count`) already exists.
Clarified that option 2 needs no new serializer (reuses build_trade_log/build_summary)
while option 1 adds one compact serializer. User then chose option 1 as the lighter,
more direct isolation evidence. MULTI-04 contended-cash determinism locked as a derived
constraint (registration order + FIFO dispatch → first reserves, second
cash_reservation REJECTED).

---

## ROBUST-01 (sparse bar) + ROBUST-02 (heterogeneous spans) data source

| Option | Description | Selected |
|--------|-------------|----------|
| Real data, sliced | Real ETH/SOL/AAVE via csv_paths, sliced to tiny hand-verifiable windows (AAVE 2021-07-15 listing edge; real SOL sparse window). Honors Phase 3's deferred real E2E; exercises the real ingestion path. | ✓ |
| Contrived synthetic spans | Engineer fresh contrived bars with planted listing/end/gap dates; fully hand-derivable but largely re-proves Phase 3's synthetic integration test. | |
| You decide | — | |

**User's choice:** Real data, sliced (option 1).
**Notes:** Before asking, verified the real dataset spans to confirm a usable sliced
window exists. Found three real robustness edges: AAVE lists mid-run (2021-07-15);
BTC ends 2026-06-03 vs the others 2026-01-08 (differing ends); SOL is missing ~418
bars over its span (real sparse-bar source for ROBUST-01). Real-sliced therefore
serves both ROBUST-01 and ROBUST-02 with no contrivance.

---

## Determinism mechanism (ROBUST-04)

| Option | Description | Selected |
|--------|-------------|----------|
| Dedicated double-run test | One new test parametrized over the Phase 9 e2e scenarios: run each twice in-process, assert the two RAW outputs identical to each other (independent of golden). | ✓ |
| Per-leaf --double-run mode | Thread a --double-run flag into run_scenario so every leaf can run twice and self-compare; more pervasive. | |
| Golden lock suffices | Treat the existing exact golden-regression as the determinism proof; add no new mechanism. | |

**User's choice:** Dedicated double-run test (option 1).
**Notes:** Chosen to catch within-process non-determinism (state leakage, dict
ordering, RNG misuse) that a golden-vs-golden diff cannot. Single addition, no
per-leaf change.

---

## Degenerate metrics (ROBUST-03)

| Option | Description | Selected |
|--------|-------------|----------|
| 3 leaves + explicit no-NaN guard | Separate no-trade / flat / losing leaves, each freezing summary.json metrics block, PLUS explicit assert-no-NaN/inf on metrics. | ✓ |
| Fold leaves, equality-only | Fewer leaves; rely solely on frozen-golden exact-equality to catch NaN. | |
| You decide | — | |

**User's choice:** 3 leaves + explicit no-NaN guard (option 1).
**Notes:** metrics.py is already NaN/div-by-zero guarded and the summary.json metrics
block is already frozen + exact-diffed (NaN fails equality naturally). User chose the
explicit no-NaN/inf assertion anyway because "no NaN" IS the ROBUST-03 contract — it
documents intent and prevents a hand-verifier silently freezing a NaN.

---

## Claude's Discretion

- Exact per-portfolio snapshot column set / file name / opt-in gate point (subject to D-01).
- Exact real-data slice windows + tickers per ROBUST-01/02 leaf (subject to D-03).
- Double-run test parametrization surface + comparison mechanic (subject to D-04).
- Exact contrived bars.csv per MULTI leaf; tests/e2e/{multi,robust}/ sub-dir names/depth.
- Canary choice + wave composition within MULTI / ROBUST clusters (subject to D-06).
- Leaf↔requirement mapping (~8 leaves, one-shape-per-leaf).

## Deferred Ideas

- Full per-portfolio golden subdirs (set aside in favor of the lighter snapshot).
- Per-leaf --double-run mode in run_scenario (set aside in favor of one dedicated test).
- Shorts / pair trading / margin / leverage → N+2 (v1.2).
- Production screener / ranking / rebalance → v1.4.
- RNG-driven REFUSED (simulate_failures) — still deliberately unused.
