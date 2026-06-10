---
phase: 09-multi-entity-robustness-metrics-edges
verified: 2026-06-10T00:00:00Z
status: human_needed
score: 4/4 must-haves verified
overrides_applied: 0
human_verification:
  - test: "Confirm WR-01 does not undermine ROBUST-04 correctness claim"
    expected: "The determinism test in test_determinism.py asserts byte-identity on trades/equity/summary (indices 0-2) but NOT on orders (index 3), cash_ops (index 4), or portfolios_frame (index 5). For the MULTI-04 contended_cash and MULTI-03 fanout_portfolios leaves, non-determinism in the winner/loser split or per-portfolio snapshot ordering would pass this test green."
    why_human: "The observable behaviour (all 9 leaves pass the double-run test) is real. Whether the untested frames (orders/cash_ops/portfolios) could exhibit non-determinism in practice requires a judgment call: the engine is synchronous and single-threaded in backtest mode, and the registration-order D-02 contract makes the winner/loser split deterministic. The question is whether the project considers the WR-01 gap an acceptable contractual narrowing or a must-fix before the phase is closed."
  - test: "Confirm WR-02 does not violate the ROBUST-03 contract for the four all-win multi-entity leaves"
    expected: "Four summary.json goldens (two_tickers, two_strategies, fanout_portfolios, contended_cash) freeze profit_factor: Infinity. The assert_metrics_finite guard in test_metrics_finite.py is applied ONLY to the three ROBUST-03 degenerate leaves, not to these four all-win multi-entity leaves. The phase's own ROBUST-03 contract states inf is a degenerate-metrics smell to avoid. A human must decide: (a) is Infinity acceptable for clean all-win multi-entity leaves as an explicit carve-out from ROBUST-03 scope, or (b) should the finiteness guard be extended framework-wide, requiring those four leaves to be re-authored with mixed PnL?"
    why_human: "This is a project-level policy decision about what counts as a well-formed golden. The code is internally consistent (the harness accepts Infinity, the test_metrics_finite.py only guards degenerate leaves), but the carve-out is implicit and the REVIEW explicitly flags it as WR-02 WARNING."
---

# Phase 9: Multi-Entity, Robustness & Metrics Edges Verification Report

**Phase Goal:** Close the breadth matrix with multi-ticker / multi-strategy / multi-portfolio runs and the robustness + degenerate-metrics edges, and prove determinism across every new scenario.
**Verified:** 2026-06-10T00:00:00Z
**Status:** human_needed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| #  | Truth | Status | Evidence |
|----|-------|--------|----------|
| 1  | One strategy trading two cryptos (multi-ticker) and multiple strategies running simultaneously each have a hand-verified, frozen E2E scenario | ✓ VERIFIED | `tests/e2e/multi/two_tickers/` (MULTI-01) and `tests/e2e/multi/two_strategies/` (MULTI-02) both exist with frozen goldens, VERIFY notes, and pass `poetry run pytest tests/e2e -m e2e -q` (58 passed) |
| 2  | A strategy fanned out to >1 portfolio shows per-portfolio cash isolation, and two strategies competing for the same portfolio's cash resolve correctly | ✓ VERIFIED | `tests/e2e/multi/fanout_portfolios/golden/portfolios.csv` has two rows with pf_a=11666.6667 and pf_b=5833.3333 (asymmetric 2:1 ratio). `tests/e2e/multi/contended_cash/golden/orders.csv` has exactly one REJECTED BTCUSD row (sized quantity 50, status REJECTED, triggered_by=cash_reservation). `cash_operations.csv` shows RESERVATION 9500 for ETHUSDT winner and no orphan loser row |
| 3  | A sparse/absent bar produces no fill and no crash, and heterogeneous date spans are handled over a union window | ✓ VERIFIED | `tests/e2e/robust/sparse_bar/golden/trades.csv` shows one SOLUSD round-trip with entry 2023-06-23 and exit 2023-06-27 — no fill on 2023-06-24/06-25 (the absent bars). `sol_sliced.csv` confirmed missing those rows; `eth_sliced.csv` has them (dense control). `tests/e2e/robust/union_window/golden/trades.csv` shows AAVE entry 2021-07-16 (first fill after the 2021-07-15 listing — no look-ahead). Both tests pass |
| 4  | No-trade / flat / losing runs produce valid metrics (no NaN, no div-by-zero in Sharpe/drawdown/profit-factor), and a double-run is byte-identical across all new scenarios | ✓ VERIFIED | `tests/e2e/robust/no_trade/golden/summary.json` shows all metrics 0.0 (finite). `flat/golden/summary.json` shows profit_factor 1.0 (finite). `losing/golden/summary.json` shows profit_factor 0.0 (finite). `tests/e2e/robust/test_metrics_finite.py` passes 3/3. `tests/e2e/robust/test_determinism.py` passes 9/9 (all Phase 9 leaves double-run byte-identical). Full `make test-e2e` 58 passed, `make test-integration` 12 passed |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `tests/e2e/conftest.py` | PORTFOLIO_SNAPSHOT_COLUMNS + per-portfolio snapshot + opt-in wiring | ✓ VERIFIED | `PORTFOLIO_SNAPSHOT_COLUMNS` referenced at lines 111, 482, 609, 674. `_build_and_run` returns 4-tuple at line 371. `_assemble` signature at line 374 accepts `portfolio_ids`. No `TRADE_COLUMNS.*portfolio` contamination |
| `tests/e2e/robust/_assert_finite.py` | `def assert_metrics_finite` using `math.isfinite` | ✓ VERIFIED | File exists, defines `assert_metrics_finite(metrics: dict[str, float])` using `math.isfinite`, raises with "ROBUST-03" message |
| `tests/e2e/robust/test_determinism.py` | Parametrized double-run test, 9 Phase 9 leaves | ✓ VERIFIED | `PHASE9_LEAVES` lists all 9 leaves, test imports `_load_spec/_build_and_run/_assemble` from `tests.e2e.conftest`, no skip guard remaining (removed in Plan 04 Task 3), 9/9 pass |
| `tests/e2e/multi/fanout_portfolios/scenario.py` | MULTI-03 canary, two portfolios, asymmetric cash | ✓ VERIFIED | ScenarioSpec with `pf_a` (cash=10_000) and `pf_b` (cash=5_000), full VERIFY note in docstring |
| `tests/e2e/multi/fanout_portfolios/golden/portfolios.csv` | Two rows: pf_a/pf_b with different final values | ✓ VERIFIED | Header + two rows: pf_a=11666.6667, pf_b=5833.3333 — exactly 2:1 ratio proving cash isolation |
| `tests/e2e/multi/two_tickers/scenario.py` | MULTI-01 leaf, one emitter, two tickers | ✓ VERIFIED | ScriptedEmitter over `["BTCUSD", "ETHUSDT"]`, VERIFY note present, golden trades.csv has both pair rows |
| `tests/e2e/multi/two_strategies/scenario.py` | MULTI-02 leaf, two emitters, one portfolio | ✓ VERIFIED | Two ScriptedEmitter instances in `strategies=[]` list, both fill |
| `tests/e2e/multi/contended_cash/scenario.py` | MULTI-04 leaf, two strategies contend | ✓ VERIFIED | strategies[0]=WINNER (ETHUSDT FixedQuantity 95), strategies[1]=LOSER (BTCUSD FixedQuantity 50); D-02 registration-order determinism documented in VERIFY note |
| `tests/e2e/multi/contended_cash/golden/orders.csv` | One REJECTED loser row with sized quantity | ✓ VERIFIED | `STANDALONE,BTCUSD,MARKET,BUY,REJECTED,100.0,50.0,0.0,...` — exactly one row |
| `tests/e2e/robust/sparse_bar/scenario.py` | ROBUST-01 leaf, SOL position live across gap | ✓ VERIFIED | BUY decided 2023-06-22 (fills 06-23), SELL decided 2023-06-26 (fills 06-27) — position open across 06-24/06-25 gap |
| `tests/e2e/robust/union_window/scenario.py` | ROBUST-02 leaf, AAVE mid-run listing | ✓ VERIFIED | AAVE entry 2021-07-16 (after listing 07-15), no pre-listing fill, full VERIFY derivation |
| `tests/e2e/robust/no_trade/scenario.py` | ROBUST-03a: zero closed trades | ✓ VERIFIED | Empty script `{}`, zero trades, all metrics 0.0 |
| `tests/e2e/robust/flat/scenario.py` | ROBUST-03b: ~zero PnL, finite metrics | ✓ VERIFIED | +10 WIN + -10 LOSS round-trips, profit_factor=1.0 (finite) |
| `tests/e2e/robust/losing/scenario.py` | ROBUST-03c: net-negative run, finite metrics | ✓ VERIFIED | Single -10 loss, profit_factor=0.0 (finite) |
| `tests/e2e/robust/test_metrics_finite.py` | Explicit no-NaN/no-inf assertion test | ✓ VERIFIED | Parametrized over 3 degenerate leaves, calls `assert_metrics_finite(summary["metrics"])`, 3/3 pass |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `tests/e2e/conftest.py::_build_and_run` | `tests/e2e/conftest.py::_assemble` | `portfolio_ids` list in 4-tuple return | ✓ WIRED | Line 371: `return system, portfolio, portfolio_ids[0], portfolio_ids`; line 374: `def _assemble(spec, system, portfolio, portfolio_id, portfolio_ids)` |
| `tests/e2e/robust/test_determinism.py` | `tests/e2e/conftest.py` | `from tests.e2e.conftest import _load_spec, _build_and_run, _assemble` | ✓ WIRED | Line 34 confirmed |
| `tests/e2e/multi/fanout_portfolios/golden/portfolios.csv` | `tests/e2e/conftest.py::_diff` | exists()-gated portfolios.csv diff | ✓ WIRED | Line 674 in conftest.py; file exists with two rows; test passes (diff-against-frozen) |
| `tests/e2e/robust/test_metrics_finite.py` | `tests/e2e/robust/_assert_finite.py::assert_metrics_finite` | `from tests.e2e.robust._assert_finite import assert_metrics_finite` | ✓ WIRED | Line 29 confirmed; 3/3 pass |
| `tests/e2e/multi/two_tickers/golden/trades.csv` | `itrader.reporting.frames.build_trade_log` | `pair` column spanning both tickers | ✓ WIRED | Frozen trades.csv has BTCUSD and ETHUSDT pair rows in same frame |
| `tests/e2e/multi/contended_cash/scenario.py` | order manager cash_reservation gate | registration order → FIFO → loser REJECTED | ✓ WIRED | golden/orders.csv has exactly one REJECTED row with sized quantity 50 |

### Data-Flow Trace (Level 4)

All artifacts are test fixtures and scenario definitions — they contain no dynamic data-fetching code (no `useState`, `fetch`, etc.). Data flows from hand-committed contrived CSVs and real-data slices through the `TradingSystem` engine to frozen golden files. The engine's correctness is proved by the passing test results against frozen oracles.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All 58 e2e tests pass | `poetry run pytest tests/e2e -m e2e -q` | 58 passed in 1.05s | ✓ PASS |
| BTCUSD oracle byte-exact | `make test-integration` | 12 passed in 10.21s | ✓ PASS |
| All 9 Phase 9 determinism cases pass | `poetry run pytest tests/e2e/robust/test_determinism.py -m e2e -v` | 9/9 passed | ✓ PASS |
| All 3 degenerate-metrics finiteness cases pass | `poetry run pytest tests/e2e/robust/test_metrics_finite.py -m e2e -v` | 3/3 passed | ✓ PASS |
| SOL sliced CSV missing gap rows | `grep "2023-06-24\|2023-06-25" sol_sliced.csv` | gap-rows-absent-GOOD | ✓ PASS |
| AAVE sliced CSV first row is listing date | `head -2 aave_sliced.csv` | First data row: 2021-07-15 | ✓ PASS |
| no_trade golden trades.csv is header-only | `cat no_trade/golden/trades.csv` | Header-only (0 data rows, trade_count=0) | ✓ PASS |
| pf_a and pf_b have different values | `cat fanout_portfolios/golden/portfolios.csv` | 11666.67 vs 5833.33 (exactly 2:1) | ✓ PASS |
| No degenerate-metrics golden has inf | `grep -L Infinity no_trade,flat,losing/summary.json` | All three listed (no inf in degenerate leaves) | ✓ PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| MULTI-01 | 09-02-PLAN.md | One strategy trading two cryptos end-to-end | ✓ SATISFIED | `tests/e2e/multi/two_tickers/` frozen, passes |
| MULTI-02 | 09-02-PLAN.md | Multiple strategies running simultaneously | ✓ SATISFIED | `tests/e2e/multi/two_strategies/` frozen, passes |
| MULTI-03 | 09-01-PLAN.md | Strategy fanned out to >1 portfolio, cash isolation | ✓ SATISFIED | `tests/e2e/multi/fanout_portfolios/` frozen with two-row asymmetric portfolios.csv |
| MULTI-04 | 09-02-PLAN.md | Two strategies competing for same portfolio's cash | ✓ SATISFIED | `tests/e2e/multi/contended_cash/` frozen; orders.csv proves REJECTED loser with sized quantity |
| ROBUST-01 | 09-03-PLAN.md | Sparse/absent bar: no fill, no crash | ✓ SATISFIED | `tests/e2e/robust/sparse_bar/` frozen; no SOL fill on 2023-06-24/25 |
| ROBUST-02 | 09-03-PLAN.md | Heterogeneous date spans over union window | ✓ SATISFIED | `tests/e2e/robust/union_window/` frozen; AAVE entry 2021-07-16 (no pre-listing look-ahead) |
| ROBUST-03 | 09-04-PLAN.md | No-trade/flat/losing runs produce valid finite metrics | ✓ SATISFIED | Three degenerate leaves frozen with all-finite metrics; `test_metrics_finite.py` enforces contract explicitly |
| ROBUST-04 | 09-01-PLAN.md + 09-04-PLAN.md | Determinism: double-run byte-identical across all new scenarios | ✓ SATISFIED (with WARNING) | `test_determinism.py` 9/9 pass — BUT only trades/equity/summary are compared (WR-01: orders/cash_ops/portfolios frames not compared) |

No orphaned requirements — all 8 Phase 9 requirement IDs are accounted for across the 4 plans.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `tests/e2e/robust/test_determinism.py` | 67-69 | Only compares `a[0]`/`a[1]`/`a[2]` (trades/equity/summary); skips indices 3/4/5 (orders/cash_ops/portfolios_frame) | ⚠️ Warning (WR-01 from code review) | Non-determinism in the Phase-9-specific MULTI frames (orders, cash_ops, portfolios_frame) would NOT be caught. The engine is synchronous in backtest mode, making this a theoretical gap rather than an observed failure, but it weakens the ROBUST-04 claim |
| `tests/e2e/multi/*/golden/summary.json` (4 files) | 8 | `"profit_factor": Infinity` frozen in two_tickers, two_strategies, fanout_portfolios, contended_cash | ⚠️ Warning (WR-02 from code review) | `assert_metrics_finite` is NOT applied to these four all-win leaves. The ROBUST-03 contract explicitly designates `inf` as a degenerate-metrics smell, but the phase authors treated single-portfolio degenerate-run leaves differently from multi-entity all-win leaves. No test failure today, but creates inconsistent enforcement |

No TBD/FIXME/XXX debt markers found in any phase-9-modified files.

### Human Verification Required

#### 1. WR-01: Determinism Test Coverage Scope

**Test:** Review `tests/e2e/robust/test_determinism.py` lines 65-69. Confirm whether the ROBUST-04 requirement is satisfied by comparing only trades/equity/summary (indices 0-2), given that the three new Phase-9 frames — `orders` (index 3), `cash_ops` (index 4), `portfolios_frame` (index 5) — are computed but not asserted.

**Expected:** Either: (a) project accepts the narrowed scope as sufficient because the backtest engine is synchronous/deterministic and the D-02 registration-order contract makes MULTI-04 winner/loser split structurally deterministic, OR (b) project requires the determinism test to be extended to compare all six frames (as WR-01 suggests).

**Why human:** Cannot be determined by static analysis. The gap is real (3 frames skipped), but whether it constitutes a ROBUST-04 contract violation vs. an acceptable narrowing of scope is a project-owner judgment call. The code review already documented the exact fix needed if option (b) is chosen.

#### 2. WR-02: Infinity in Multi-Entity All-Win Golden Summaries

**Test:** Examine `tests/e2e/multi/two_tickers/golden/summary.json`, `tests/e2e/multi/two_strategies/golden/summary.json`, `tests/e2e/multi/fanout_portfolios/golden/summary.json`, and `tests/e2e/multi/contended_cash/golden/summary.json` — all four contain `"profit_factor": Infinity`. Determine whether this is an intentional carve-out from the ROBUST-03 scope or a gap that needs the finiteness guard extended.

**Expected:** Either: (a) `Infinity` is explicitly accepted for clean all-win multi-entity leaves (document the carve-out in the four VERIFY notes so a future re-freezer knows it is intentional), OR (b) those four leaves should be re-authored with mixed PnL so `profit_factor` is finite everywhere, and `assert_metrics_finite` is made framework-wide.

**Why human:** The `reporting/metrics.py` `profit_factor` code returns `inf` for all-win frames by design. Whether that's acceptable in golden files is a project-level policy question about what counts as a well-formed golden. Both options are consistent implementations; the choice determines whether the e2e harness enforces finiteness universally or only for the declared "degenerate edge" leaves.

### Gaps Summary

No blocking gaps — all four success criteria are observably true in the codebase. Tests run and pass. The two WARNING items (WR-01 and WR-02) are carry-forwards from the code review and require a human policy decision about contractual scope, not evidence of missing implementation.

---

_Verified: 2026-06-10T00:00:00Z_
_Verifier: Claude (gsd-verifier)_
