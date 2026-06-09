---
phase: 08-m5c-cross-validation-final-oracle
verified: 2026-06-08T16:00:00Z
status: passed
score: 9/9 must-haves verified
overrides_applied: 0
---

# Phase 8: m5c-cross-validation-final-oracle Verification Report

**Phase Goal:** Finish the Decimal cleanup of the backtest run path, cross-validate iTrader's SMA_MACD golden backtest against external reference engines, and freeze the final numerical oracle — satisfying the program-level D-13 definition-of-done.
**Verified:** 2026-06-08T16:00:00Z
**Status:** PASSED
**Re-verification:** No — initial verification

---

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | SMA_MACD runs end-to-end via `make backtest` producing a non-trivial trade log and multi-point equity curve | VERIFIED | Live run produced trade_count=134, final_equity=46189.87730727451, 3076 equity points — matches frozen golden exactly |
| 2 | `make typecheck` (mypy --strict over itrader/) exits 0 | VERIFIED | "Success: no issues found in 151 source files" — confirmed live |
| 3 | No float money on the golden path: Portfolio.total_* properties return Decimal; no residual float() on money members | VERIFIED | All five properties (total_market_value, total_equity, total_unrealised_pnl, total_realised_pnl, total_pnl) declared `-> Decimal` in portfolio.py; two remaining float() calls are on a config config-limit value (line 189) and a ratio return (line 397), neither a money member |
| 4 | Single UUIDv7 scheme: every result-bearing ID flows from idgen/uuid-utils; no result-bearing uuid4/uuid1 | VERIFIED | `grep -rn 'uuid4\|uuid1' itrader/` yields exactly one hit: `portfolio_handler.py:88 _generate_correlation_id()` — confirmed to be a log/error-event correlation id used exclusively in `_generate_correlation_id` and called only from `_operation_context`/`start_operation`, never on order/fill/trade/portfolio-state IDs |
| 5 | Deterministic: two consecutive `make backtest` runs produce byte-identical output/ artifact sets | VERIFIED | Ran `make backtest` twice, `diff -r run_a run_b` produced no output — confirmed byte-identical |
| 6 | Full live test suite is green at the real collected count (not hardcoded 274) | VERIFIED | `pytest --collect-only -q` reports 724 tests collected; `make test` reports 724 passed, 0 failures in 8.98s, under filterwarnings=["error"] / --strict-markers / --strict-config |
| 7 | Run-path integration test (tests/integration/test_backtest_oracle.py) passes against the frozen oracle | VERIFIED | `pytest tests/integration/test_backtest_oracle.py -v` — 2 passed (test_oracle_behavioral_identity + test_oracle_numeric_values), byte-exact frame-equal diff with no float tolerance |
| 8 | tests/golden/CROSS-VALIDATION.md exists as committed cross-validation evidence with per-divergence root-cause dispositions | VERIFIED | File exists at tests/golden/CROSS-VALIDATION.md; contains 6 occurrences of "root-cause"; full report with 4 divergences root-caused (D-1/2/3 sortino = entry-bar equity-marking convention; D-4 win_rate = nautilus NETTING fill arithmetic), all dispositioned LEGITIMATE-DIFFERENCE, owner-approved 2026-06-08 |
| 9 | tests/golden/FINAL-ORACLE.md declares the final authoritative oracle (D-11) with the DoD evidence block | VERIFIED | File exists; contains declaration, frozen values table (trade_count=134, final_equity=46189.87730727451, 3076 equity points), M5-C re-freeze lineage, cross-validation reference, complete 8-check D-13 DoD evidence block all marked PASS, and owner sign-off ("Owner: tiziaco Date: 2026-06-08 Signal: approved") |

**Score:** 9/9 truths verified

---

## Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `tests/golden/FINAL-ORACLE.md` | Terminal freeze declaration + DoD evidence | VERIFIED | Exists; contains "FINAL" declaration, trade_count, frozen metric values, DoD checklist, owner sign-off |
| `tests/golden/summary.json` | Frozen authoritative metrics + trade count | VERIFIED | Exists; trade_count=134, final_equity=46189.87730727451, complete metrics dict |
| `tests/golden/trades.csv` | Frozen authoritative trade log (135 lines = 1 header + 134 trades) | VERIFIED | 135 lines confirmed |
| `tests/golden/equity.csv` | Frozen authoritative equity curve (3077 lines = 1 header + 3076 rows) | VERIFIED | 3077 lines confirmed |
| `tests/golden/CROSS-VALIDATION.md` | Cross-validation evidence with root-cause dispositions | VERIFIED | Exists with full reconciliation table, 4 per-divergence root-causes, owner sign-off |
| `tests/golden/REFREEZE-M5C-DECIMAL.md` | M5-C re-freeze lineage note | VERIFIED | Exists, owner-approved SHIFT noted |
| `tests/integration/test_backtest_oracle.py` | Permanent byte-exact regression gate | VERIFIED | Passes 2/2 tests against frozen golden |

---

## Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `tests/integration/test_backtest_oracle.py` | `tests/golden/summary.json` | byte-exact frame-equal diff of fresh run_backtest output vs frozen golden | WIRED | Test passed live; imports run_backtest module in-process, diffs output/ vs tests/golden/ with no tolerance |
| `scripts/run_backtest.py` | `Portfolio.total_equity (Decimal)` | build_summary serializes Decimal at float boundary into summary.json/equity.csv | WIRED | Confirmed: `float(portfolio.total_equity)` in build_summary is the serialization boundary; the Decimal flows end-to-end through the engine |

---

## D-13 Definition-of-Done Gate — Live Evidence Table

All eight checks run live against the actual codebase during this verification:

| # | DoD Criterion | Command | Observed Result | Status |
|---|---------------|---------|-----------------|--------|
| 1 | End-to-end run: non-trivial trade log + multi-point equity curve | `make backtest` | trade_count=134; final_equity=46189.87730727451; 3076 equity points; output/{trades.csv,equity.csv,summary.json} written | PASS |
| 2 | Type cleanliness (mypy --strict) | `make typecheck` | "Success: no issues found in 151 source files", exit 0 | PASS |
| 3 | No float money on golden path | inspect `Portfolio.total_*` + grep `float(` in portfolio.py | All five `total_*` return `-> Decimal`; two float() hits are on config limit (not money) and ratio (not money); comment at line 207-237 confirms no-float-cast is intentional | PASS |
| 4 | Single UUIDv7 scheme on result path | `grep -rn 'uuid4\|uuid1' itrader/ --include='*.py'` | One hit: `portfolio_handler.py:88 _generate_correlation_id()` — log/error-path only; all order/fill/trade IDs use `idgen.generate_order_id()` (uuid-utils UUIDv7) | PASS |
| 5 | Determinism: two runs byte-identical | `make backtest` x2 + `diff -r run_a run_b` | No differences — byte-identical trades.csv / equity.csv / summary.json | PASS |
| 6 | Full live suite green at real collected count | `pytest --collect-only -q` + `make test` | 724 collected; 724 passed in 8.98s, 0 failures, under filterwarnings=["error"] / --strict-markers / --strict-config | PASS |
| 7 | Run-path integration test against frozen oracle | `pytest tests/integration/test_backtest_oracle.py -v` | 2 passed (test_oracle_behavioral_identity + test_oracle_numeric_values) in 3.03s | PASS |
| 8 | Cross-validation evidence present (SC#1) | `test -f tests/golden/CROSS-VALIDATION.md && grep -qi 'root-cause'` | File exists; 6 occurrences of "root-cause"; 4 full per-divergence analyses with LEGITIMATE-DIFFERENCE dispositions | PASS |

---

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|-------------------|--------|
| `tests/golden/summary.json` | trade_count, final_equity, metrics | `scripts/run_backtest.py::build_summary` → `Portfolio.total_equity` (Decimal) → `float()` at serialization boundary | Live backtest run produces identical values to frozen oracle | FLOWING |
| `tests/golden/equity.csv` | total_equity per bar | `scripts/run_backtest.py` → portfolio snapshot per bar | 3076 rows matching frozen golden | FLOWING |
| `tests/golden/trades.csv` | entry_date, exit_date, side, realised_pnl | `scripts/run_backtest.py` → trade log from portfolio | 134 rows matching frozen golden | FLOWING |

---

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| `make backtest` produces trade_count=134 | Live run observed | trade_count=134, final_equity=46189.87730727451 | PASS |
| `make typecheck` exits 0 | Live run observed | "no issues found in 151 source files" | PASS |
| 724 tests pass under strict filterwarnings | `make test` observed | 724 passed, 0 failures | PASS |
| Integration test passes byte-exact | `pytest tests/integration/test_backtest_oracle.py -v` | 2 passed | PASS |
| Determinism | `diff -r run_a run_b` | no differences | PASS |

---

## Probe Execution

No declared probe scripts for this phase. The D-13 gate checks above serve as the functional equivalent.

---

## Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| M5-10 | 08-09-PLAN.md | Final numerical reference frozen + cross-validated | SATISFIED | CROSS-VALIDATION.md present with root-cause dispositions; FINAL-ORACLE.md declares freeze; integration test passes byte-exact |

---

## Anti-Patterns Found

Scan of Python files modified in phase 08 commits (itrader/order_handler/order_validator.py, itrader/portfolio_handler/metrics/metrics_manager.py, itrader/trading_system/backtest_trading_system.py, scripts/run_backtest.py, scripts/crossval/*.py):

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | — | No TBD/FIXME/XXX/TODO/HACK/PLACEHOLDER debt markers found in any modified file | — | — |

The float() calls in metrics_manager.py (lines 288, 337-338, 412-423, 527-536) are conversion of Decimal equity snapshots to float for numpy/scipy statistical computation (sharpe, sortino, drawdown). These are at the statistical-ratio input boundary, NOT on money members, and are consistent with the plan's documented D-06 scope. Not a stub.

The float() calls in portfolio.py (line 189: config limit, line 397: ratio return) are correctly scoped — neither is a money result member.

---

## Human Verification Required

None. All D-13 DoD criteria are verifiable by automated command execution and were verified live. The owner sign-off was recorded during the phase execution (Task 3 checkpoint) and is present in tests/golden/FINAL-ORACLE.md §6.

---

## Gaps Summary

No gaps. All 9 must-have truths verified against the live codebase:

- The frozen golden oracle artifacts exist and are byte-identical to a fresh live run.
- All five Portfolio.total_* properties are typed `-> Decimal`.
- mypy --strict passes 151 source files with zero issues.
- 724 tests pass under pytest strictness.
- The run-path integration test (byte-exact, no tolerance) passes 2/2.
- Cross-validation evidence is substantive: full per-divergence root-cause analysis, 4 LEGITIMATE-DIFFERENCE dispositions, owner-approved.
- FINAL-ORACLE.md is a substantive declaration with the complete D-13 evidence block and recorded owner sign-off.
- Determinism confirmed live: two consecutive runs produce bit-identical artifacts.
- Single UUIDv7 scheme confirmed: one non-result-bearing uuid4 hit in the correlation-ID function; all result-path IDs use uuid-utils.

The program-level D-13 definition of done is fully satisfied.

---

_Verified: 2026-06-08T16:00:00Z_
_Verifier: Claude (gsd-verifier)_
