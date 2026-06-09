---
phase: 04-e2e-harness-framework
verified: 2026-06-09T00:00:00Z
status: passed
score: 4/4 must-haves verified
overrides_applied: 0
resolved_during_execution:
  - item: "REQUIREMENTS.md E2E-01 tracking checkbox + traceability table marked Complete (clerical oversight; all E2E-01 code evidence was already VERIFIED)."
    resolved: "2026-06-09 — orchestrator applied the documentation fix after verification."
---

# Phase 4: E2E Harness & Framework Verification Report

**Phase Goal:** Stand up the whole-system E2E testing apparatus — the dedicated tree, marker, make target, and shared golden-compare harness — that every scenario wave (Phases 6-9) depends on.
**Verified:** 2026-06-09
**Status:** passed (the single human_needed item — a clerical E2E-01 tracking checkbox — was resolved during execution)
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | A dedicated `tests/e2e/` tree exists, subsystem-grouped, with an `e2e` marker registered in `pyproject.toml`, folder-derived auto-marking, and a working `make test-e2e` target | VERIFIED | `tests/e2e/` exists with `smoke/`, `strategies/`, `data/` subdirs; `pyproject.toml:65` has `"e2e: End-to-end scenario — full engine on a (strategy, data) pair vs frozen goldens (tests/e2e/)"` in the markers list; `tests/conftest.py:58` has `if "e2e" in parts: item.add_marker(pytest.mark.e2e)`; `Makefile:6` has `test-e2e` on `.PHONY` and `Makefile:39` has the `test-e2e` target; `poetry run pytest tests/ -m e2e --collect-only -q` exits 0 with 1 test collected under the e2e marker |
| 2 | A shared harness (`tests/e2e/conftest.py`) runs the full engine on a given `(strategy, data)` pair and diffs trades/equity/summary against that scenario's golden fixtures | VERIFIED | `tests/e2e/conftest.py` exists; imports from `itrader.reporting.summary` at line 68; `_build_and_run` defers `TradingSystem` import inside the function; calls `system.run(print_summary=False)` at line 175; reads `get_portfolio(portfolio_ids[0])` after run at line 179; `_diff` diffs only golden files present (D-05); `_diff_frame` uses `assert_frame_equal(check_exact=True, check_like=True)` with zero `rtol`/`atol`; `--freeze` option registered and gated via `request.config.getoption("--freeze")`; canary runs green in 0.11s |
| 3 | Each scenario is a self-contained leaf folder (purpose-built strategy + frozen golden fixtures) that runs warning-clean under `filterwarnings=["error"]` | VERIFIED | `tests/e2e/smoke/single_market_buy/` is fully self-contained: `bars.csv` (6 contrived bars), `scenario.py` with `SCENARIO = ScenarioSpec(...)`, `test_scenario.py` D-01 one-liner, `golden/trades.csv` (1 data row), `golden/summary.json`; `SingleMarketBuy` strategy in shared `tests/e2e/strategies/`; canary runs green under `filterwarnings=["error"]` |
| 4 | The harness enforces the hand-verify-once-then-freeze discipline: a scenario's oracle is human-verified for correctness before it is committed as a golden fixture | VERIFIED | `scenario.py` module docstring (lines 16-84) contains `HAND-VERIFIED & LOCKED (E2E-04 / D-13)` stamp with verified facts (buy @120 on 2020-01-03, sell @140 on 2020-01-05, realised_pnl 1_666.666…, final_equity 11_666.666…, trade_count 1); `--freeze` is OFF by default; diff self-trust proven in plan execution (mutated golden -> FAIL -> revert -> PASS per 04-03-SUMMARY.md Task 2) |

**Score:** 4/4 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `itrader/reporting/summary.py` | Shared serialization assembly (attach_slippage, build_metrics_block, build_summary, FLOAT_FORMAT, SLIPPAGE_COLUMNS) | VERIFIED | Exists; all 5 exports confirmed importable; zero handler imports; `build_summary` signature uses keyword-only params (ticker/timeframe/start_date/end_date/starting_cash) |
| `tests/e2e/conftest.py` | run_scenario fixture + pytest_addoption('--freeze') + diff-or-freeze loop | VERIFIED | Exists; `run_scenario` fixture at line 338; `pytest_addoption` at line 88; `_freeze` / `_diff` / `_roundtrip` all present |
| `pyproject.toml` | e2e marker registered | VERIFIED | Line 65: `"e2e: End-to-end scenario..."` |
| `tests/conftest.py` | Folder-derived e2e auto-marking branch | VERIFIED | Line 58: `if "e2e" in parts:` adding `pytest.mark.e2e` |
| `Makefile` | test-e2e target (-m e2e) | VERIFIED | Line 39: `test-e2e` target with `poetry run pytest tests/ -v -m "e2e"`; on `.PHONY` at line 6; `make test` unchanged (no `-m` filter) |
| `tests/e2e/strategies/single_market_buy.py` | Contrived Strategy emitting one BUY when `len(bars) == fire_on_bar` | VERIFIED | `class SingleMarketBuy(Strategy)` with `fire_on_bar` and `exit_on_bar`; `max_window = 100` (not 0, necessary for count-based firing) |
| `tests/e2e/smoke/single_market_buy/scenario.py` | ScenarioSpec for the canary + VERIFY hand-derivation docstring | VERIFIED | `SCENARIO = ScenarioSpec(...)` at line 138; HAND-VERIFIED & LOCKED stamp at line 18 |
| `tests/e2e/smoke/single_market_buy/test_scenario.py` | One-liner leaf test delegating to run_scenario | VERIFIED | `def test_single_market_buy(run_scenario): run_scenario(HERE)` — no assert/diff logic |
| `tests/e2e/smoke/single_market_buy/bars.csv` | Contrived tiny CSV in Binance-kline schema | VERIFIED | First line exactly `Open time,Open,High,Low,Close,Volume`; 6 tz-aware bars; round-number opens 100/110/120/130/140/150 |
| `tests/e2e/smoke/single_market_buy/golden/trades.csv` | Frozen hand-verified trade log | VERIFIED | 1 data row; entry_date 2020-01-03, exit_date 2020-01-05, realised_pnl 1666.666…, slippage_entry=6, slippage_exit=6 |
| `tests/e2e/smoke/single_market_buy/golden/summary.json` | Frozen hand-verified summary + metrics block | VERIFIED | Contains `final_equity: 11666.666…`, `trade_count: 1`, `total_realised_pnl: 1666.666…`, full metrics block |
| `scripts/run_backtest.py` | Imports assembly instead of defining it locally | VERIFIED | Line 37: `from itrader.reporting.summary import`; 0 local `def attach_slippage/build_metrics_block/build_summary` definitions |
| `tests/unit/core/test_enums.py` | Dead FillStatus pytest.skip removed | VERIFIED | `grep -c 'pytest.skip'` returns 0 (only comment mention in docstring remains) |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `scripts/run_backtest.py` | `itrader.reporting.summary` | `from itrader.reporting.summary import` | WIRED | Line 37 confirmed; 0 local function redefinitions |
| `tests/e2e/conftest.py` | `itrader.reporting.summary` | `from itrader.reporting.summary import build_summary/...` | WIRED | Line 68 confirmed |
| `tests/e2e/conftest.py` | `itrader.trading_system.backtest_trading_system.TradingSystem` | deferred import inside `_build_and_run` | WIRED | Line 137 inside function body; keeps `--collect-only` clean |
| `tests/conftest.py` | `pytest.mark.e2e` | `pytest_collection_modifyitems` folder-derived `add_marker` | WIRED | Line 58-61 confirmed; `--strict-markers` in `pyproject.toml` enforces registration |
| `tests/e2e/smoke/single_market_buy/test_scenario.py` | `run_scenario` fixture | `def test_single_market_buy(run_scenario): run_scenario(HERE)` | WIRED | Line 15 confirmed; test passes in live run |
| `tests/e2e/smoke/single_market_buy/scenario.py` | `tests/e2e/strategies/single_market_buy.py` | `from tests.e2e.strategies.single_market_buy import SingleMarketBuy` | WIRED | Line 91 confirmed; `SCENARIO.strategies` at line 145 |
| `tests/e2e/smoke/single_market_buy/scenario.py` | `CsvPriceStore` (real path) | `ScenarioSpec.data = {_TICKER: HERE / "bars.csv"}` | WIRED | Line 144 confirmed; bars.csv exists at that path |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `tests/e2e/conftest.py` (`_assemble`) | `trades`, `equity`, `summary` | `build_trade_log(portfolio)`, `build_equity_curve(portfolio)` from a live `TradingSystem.run()` | Yes — real engine run; golden/trades.csv has 1 row matching hand-derived PnL | FLOWING |
| `tests/e2e/conftest.py` (`_diff`) | golden files from `golden/` | `pd.read_csv(trades_golden)`, `json.load(summary_golden)` | Yes — non-empty committed golden fixtures | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Canary e2e test passes in diff-only mode | `poetry run pytest tests/e2e/smoke/single_market_buy -x -q` | `1 passed in 0.11s` | PASS |
| e2e marker collects under `--strict-markers` | `poetry run pytest tests/ -m e2e --collect-only -q` | `1/735 tests collected (734 deselected)` — no "unknown marker" error | PASS |
| `--freeze` option is registered | `poetry run pytest tests/e2e --help \| grep -- --freeze` | Shows `--freeze  WRITE e2e golden fixtures...` | PASS |
| `summary.py` exports are importable | `python -c "from itrader.reporting.summary import ..."` | `%.10f ['slippage_entry', 'slippage_exit']` | PASS |
| `make test` has no `-m` filter | `grep -A2 '^test:' Makefile` | `poetry run pytest tests/ -v` (no `-m`) | PASS |

### Probe Execution

No probe scripts declared in plans or PLAN frontmatter. Step 7c: SKIPPED (no conventional `scripts/*/tests/probe-*.sh` probe files).

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| E2E-01 | 04-02-PLAN.md | Dedicated `tests/e2e/` tree, subsystem-grouped, registered `e2e` marker, folder-derived auto-marking, `make test-e2e` target | SATISFIED | All four components verified in codebase; marker registered in `pyproject.toml:65`, auto-marking in `tests/conftest.py:58`, `make test-e2e` in `Makefile:39`, tree at `tests/e2e/`; NOTE: REQUIREMENTS.md traceability table still shows `Pending` — documentation gap only, not a code gap |
| E2E-02 | 04-01-PLAN.md, 04-02-PLAN.md, 04-03-PLAN.md | Shared harness runs full engine on `(strategy, data)` pair and diffs against golden fixtures | SATISFIED | `tests/e2e/conftest.py` with `run_scenario` fixture wires `TradingSystem`, runs, reads portfolio, assembles via `itrader.reporting.summary`, diffs golden files present |
| E2E-03 | 04-02-PLAN.md, 04-03-PLAN.md | Each scenario is a self-contained leaf folder: purpose-built strategy + frozen golden fixtures, runnable warning-clean under `filterwarnings=["error"]` | SATISFIED | Canary leaf at `tests/e2e/smoke/single_market_buy/` is fully self-contained; passes in `0.11s` under `filterwarnings=["error"]` |
| E2E-04 | 04-03-PLAN.md | Every scenario oracle is hand-verified for correctness once before it is frozen | SATISFIED | Blocking human checkpoint completed; `HAND-VERIFIED & LOCKED` stamp committed in `scenario.py` module docstring; diff self-trust proven (mutate-golden -> FAIL -> revert -> PASS) |

### Anti-Patterns Found

No `TBD`, `FIXME`, or `XXX` markers found in any phase-modified files. No stubs, no empty handler implementations, no return null/return [].

The four warnings from `04-REVIEW.md` are assessed below relative to the phase goal:

| Finding | File | Severity | Impact on Phase Goal |
|---------|------|----------|----------------------|
| WR-01: `attach_slippage` uses a single ticker's closes for all trades (latent multi-ticker bug) | `tests/e2e/conftest.py:189`, `itrader/reporting/summary.py:42-75` | Advisory | Does NOT block phase goal. Phase 4 goal is single-ticker canary; canary is correct. Multi-ticker is Phase 9 (MULTI-01). Fix is forward-looking debt for Phase 6-9 authors. |
| WR-02: `decision_close` fragile for non-exact-index fill timestamps | `itrader/reporting/summary.py:59-61` | Advisory | Does NOT block phase goal. Canary fill dates coincide with bar timestamps exactly; the off-by-one risk is inherited from the oracle and not exercised in Phase 4. |
| WR-03: Summary diff is not round-tripped through JSON while trade/equity diff IS round-tripped through CSV | `tests/e2e/conftest.py:248-263` | Advisory | Does NOT block phase goal. The canary passes correctly; the asymmetry is a precision-gate contract documentation issue. The canary's summary values survive because Python's shortest-float-repr matches json.dump output. |
| WR-04: Whole-`metrics`-dict `==` comparison will spuriously FAIL on NaN metrics | `tests/e2e/conftest.py:251-255` | Advisory | Does NOT block phase goal. Current `itrader.reporting.metrics` is NaN-guarded; all metrics return `0.0` for degenerate curves. Latent for future scenarios. |

All four warnings are forward-looking and do not affect the Phase 4 deliverable (single-ticker canary, correct, passing).

### Human Verification Required

### 1. REQUIREMENTS.md E2E-01 Traceability Update

**Test:** Open `.planning/REQUIREMENTS.md` and update line 27 from `- [ ] **E2E-01**:` to `- [x] **E2E-01**:`, and update the traceability table entry at line 125 from `| E2E-01 | Phase 4 | Pending |` to `| E2E-01 | Phase 4 | Complete |`.

**Expected:** REQUIREMENTS.md reflects E2E-01 as complete, consistent with E2E-02/03/04 which are already marked `[x]` / `Complete`.

**Why human:** This is a documentation tracking change to a planning artifact — not a code verification. The codebase evidence for E2E-01 is entirely VERIFIED (tests/e2e/ tree, e2e marker, folder-derived auto-marking, make test-e2e all exist and work). The mismatch is a tracking oversight where the plan executor checked off E2E-02/03/04 in REQUIREMENTS.md but missed E2E-01. No code change required; human decision on whether to apply the documentation fix before closing the phase.

### Gaps Summary

No blocking gaps. All 4 success criteria are verified against the actual codebase:

- `tests/e2e/` tree: exists, subsystem-grouped (smoke/, strategies/, data/)
- `e2e` marker: registered in `pyproject.toml`, auto-applied by `tests/conftest.py`, `make test-e2e` target confirmed
- Shared harness: `tests/e2e/conftest.py` builds/runs/reads/assembles/diffs using the shared `itrader.reporting.summary` path
- Canary leaf: self-contained, warning-clean, 1 trade, hand-verified-locked with VERIFY note
- `--freeze` is off by default; diff self-trust proven

The single human verification item is a documentation tracking update to REQUIREMENTS.md (E2E-01 status shows Pending while all evidence of completion exists in the codebase). This does not indicate missing functionality — it is a clerical gap in the planning artifact.

The four advisory warnings from the code review (WR-01 through WR-04) are all forward-looking: WR-01 (multi-ticker slippage) becomes relevant only when Phase 6-9 multi-ticker scenarios are authored; WR-02/03/04 are edge cases not exercised by the Phase 4 deliverable. They are debt to carry into Phase 6-9 planning, not blockers for this phase.

---

_Verified: 2026-06-09_
_Verifier: Claude (gsd-verifier)_
