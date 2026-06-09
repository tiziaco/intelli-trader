---
phase: 08-m5c-cross-validation-final-oracle
plan: 02
subsystem: trading_system
tags: [decimal, money, mypy, serialization-boundary, fan-out, D-06, D-13, M5-10]

# Dependency graph
requires:
  - phase: 08-m5c-cross-validation-final-oracle
    plan: 01
    provides: "Portfolio.total_market_value/total_equity/total_unrealised_pnl/total_realised_pnl/total_pnl typed -> Decimal with Decimal-native aggregation"
provides:
  - "Caller fan-out reconciled: every itrader/ consumer of the retyped Portfolio.total_* members is Decimal-clean (mypy --strict 151 files green, no float+Decimal mixed arithmetic)"
  - "Decimal->float serialization boundary explicitly documented in code at both consumer sites (backtest summary log + summary.json generator) — money stays Decimal up to the serialization/presentation edge"
  - "make backtest proven end-to-end against the 08-01 Decimal numbers: 134 trades, final_equity 46189.87730727451, three output artifacts serialized"
affects: [08-03-oracle-refreeze]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Decimal->float at the serialization/presentation edge ONLY: float(portfolio.total_equity) / float(portfolio.cash) are direct edge reads (no arithmetic before the cast), never money round-trips earlier in the path"
    - "Frame-edge float casts (build_equity_curve / build_trade_log astype(float)) are the boundary for CSV money columns; run_backtest reads already-float frame columns, not Portfolio properties, for total_realised_pnl"

key-files:
  created: []
  modified:
    - "itrader/trading_system/backtest_trading_system.py - comment documenting the Decimal->float presentation edge at the final_equity logging kwarg (retype otherwise inert here)"
    - "scripts/run_backtest.py - comments documenting the single money Decimal->float serialization boundary for summary.json (final_cash/final_equity) and the already-float frame read for total_realised_pnl"

key-decisions:
  - "The 08-01 retype was INERT at both cross-file consumers: mypy --strict was already clean (151 files) and there was no float+Decimal mixed arithmetic at any consumer. The float() wraps at both sites were already correct Decimal->float edge conversions. This plan's substantive change is documenting that boundary in code, not fixing type errors (08-01 Fan-Out Notes confirmed: the callers already accept Decimal)."
  - "No test files were edited: there were zero isinstance(..., float) type-contract failures and zero Decimal==float mismatches (08-01 updated its own test files in-wave). The only suite failure is the sanctioned design-failing oracle numeric test (D-08), which is surfaced not fixed."

requirements-completed: [M5-10]

# Metrics
duration: 4min
completed: 2026-06-08
---

# Phase 8 Plan 02: Decimal Caller Fan-Out + Propagation Sweep Summary

**Swept the cross-file consumers of the 08-01 `Portfolio.total_*` Decimal retype (`backtest_trading_system.py` end-of-run log + `scripts/run_backtest.py` oracle generator), confirmed the retype was fully inert there (mypy --strict already clean, no mixed arithmetic), documented the Decimal->float serialization boundary in code at both sites, and proved `make backtest` still runs end-to-end and the full suite is green except the one sanctioned design-failing oracle numeric test deferred to 08-03.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-06-08T14:00:45Z
- **Completed:** 2026-06-08T14:05:00Z
- **Tasks:** 3
- **Files modified:** 2 (both source; 0 test files needed editing)

## Accomplishments
- **mypy --strict clean over all 151 `itrader/` source files** after the 08-01 retype — the caller fan-out is fully reconciled. Confirmed the only cross-file consumer in `itrader/trading_system/` is `backtest_trading_system.py:247` (`float(portfolio.total_equity)`, a logging kwarg / Decimal->float edge conversion — no mixed arithmetic). Confirmed `sizing_resolver.py:123` `self._read_model.total_equity(portfolio_id)` resolves to the already-Decimal `PortfolioReadModel` Protocol method (NOT the Portfolio property) — UNAFFECTED.
- **`make backtest` runs end-to-end** against the 08-01 Decimal numbers: 134 trades, `final_equity = 46189.87730727451` (byte-exact with the 08-01-reported value), serializing `output/{trades.csv,equity.csv,summary.json}` without error. `summary.json` `final_equity` and `final_cash` deserialize as JSON floats (the Decimal->float boundary sits at the serialization edge); `trade_count = 134` (non-trivial run preserved).
- **Full suite green except the one sanctioned oracle failure**: 723 passed, 1 failed (`test_oracle_numeric_values` on the `total_equity` equity-curve column, 0.61769% diff). `test_oracle_behavioral_identity` PASSES. mypy --strict re-confirmed clean.
- **Documented the Decimal->float serialization/presentation boundary in code** at both consumer sites (the structural half of D-13: money stays Decimal end-to-end up to the edge, converted there via the existing `float()` / `FLOAT_FORMAT` pattern).

## Task Commits

1. **Task 1 (mypy fan-out sweep, backtest_trading_system.py):** `d9b8789` (docs)
2. **Task 2 (serialization boundary, run_backtest.py + make backtest proof):** `eb89da9` (docs)
3. **Task 3 (phase-gate: full suite + mypy):** no production/test edits required — verified green (see below). No commit (no file change).
4. **Plan metadata:** (final docs commit)

## Files Created/Modified
- `itrader/trading_system/backtest_trading_system.py` — Added a comment at the `final_equity=float(portfolio.total_equity)` logging kwarg (L247) clarifying it is a Decimal->float presentation edge, not money arithmetic. The retype was otherwise inert here (mypy clean).
- `scripts/run_backtest.py` — Added comments to `build_summary` documenting that `final_cash`/`final_equity` are the single money Decimal->float serialization boundary for `summary.json` (direct `float(Decimal)` edge reads, no arithmetic before the cast), and that `total_realised_pnl` reads the already-float trades-frame column (not a Portfolio property, unaffected by the retype).

## Inert-vs-Edited Consumer Audit (plan `<output>` requirement)

| Consumer site | Status | Action taken |
|---------------|--------|--------------|
| `backtest_trading_system.py:247` `float(portfolio.total_equity)` | INERT (mypy clean, edge conversion) | Documented the boundary in a comment |
| `scripts/run_backtest.py:141` `float(portfolio.total_equity)` | INERT (direct edge read) | Documented the boundary in a comment |
| `scripts/run_backtest.py:140` `float(portfolio.cash)` | INERT (cash was already Decimal pre-08-01) | Documented the boundary in a comment |
| `scripts/run_backtest.py:114` `equity["total_equity"].astype(float)` | UNAFFECTED (reads build_equity_curve float-edge frame column) | Confirm only — no edit |
| `scripts/run_backtest.py:133` `float(trades["realised_pnl"].sum())` | UNAFFECTED (reads build_trade_log float-edge frame column) | Confirm + comment |
| `itrader/order_handler/sizing_resolver.py:123` `self._read_model.total_equity(...)` | UNAFFECTED (Protocol method, already Decimal) | Confirm only — no edit |
| `itrader/reporting/frames.py:83` `astype(float)` over EQUITY_COLUMNS | UNAFFECTED (08-03's equity-curve precision surface) | Confirm only — no edit |

## Decisions Made
- **The retype was inert at both cross-file consumers.** mypy --strict was already clean (0 errors, 151 files) before any edit, and there was no `float + Decimal` mixed arithmetic at any consumer — the `float()` wraps were already correct Decimal->float edge conversions. This matches the 08-01 Fan-Out Notes ("the float-wrapping callers all accept Decimal — so 08-02's sweep is about removing now-redundant float boundaries, not fixing type errors"). The substantive deliverable here is documenting the serialization boundary in code, fulfilling each task's `done` criterion ("the serialization boundary is documented in code comments as 'Decimal->float at the serialization edge'").
- **No test files were edited (Task 3).** There were zero `isinstance(..., float)` type-contract failures (08-01 updated its own `tests/unit/portfolio/test_money_decimal.py` and `test_metrics_manager.py` in-wave) and zero incidental `Decimal == float`/dtype-warning failures. The single suite failure is the sanctioned design-failing oracle numeric test — surfaced, not fixed, per Task 3's "any VALUE shift ... is an 08-03 oracle concern, not a test edit; surface it instead."

## Deviations from Plan

None — plan executed as written. Both consumer sites were inert (as the 08-01 Fan-Out Notes predicted), so Tasks 1-2 were document-the-boundary edits and Task 3 required no edits. No 08-01-owned file (`portfolio.py` / `metrics_manager.py` / `order_validator.py`) was touched; `tests/golden/*` was NOT touched.

## Issues Encountered

**Sanctioned design-failing oracle test (D-08, deferred to 08-03 — NOT a regression)**
- `tests/integration/test_backtest_oracle.py::test_oracle_numeric_values` FAILS on the `total_equity` equity-curve column (0.61769% diff on intermediate rows). `test_oracle_behavioral_identity` PASSES.
- This is the exact, expected, sanctioned result-change documented in the 08-01 SUMMARY (D-08) and the prior-wave context handed to this plan: "the oracle numeric test currently fails on the equity-curve column by design (sanctioned D-08 result-change); it will be re-frozen in 08-03. Do NOT try to 'fix' that oracle failure — it is expected." The behavioral oracle is byte-identical and `final_equity` is byte-exact at 46189.87730727451.
- **Per Task 3's instruction this is surfaced, not fixed** — any VALUE shift is an 08-03 oracle re-freeze concern (`REFREEZE-M5C-DECIMAL`), never a test edit in this plan. No money assertion was loosened to absorb it.
- **Verify-gate note for the orchestrator:** Task 3's literal automated grep (`! grep -qE "failed|error"`) trips on this one design-failing test. This is the same gate posture 08-01 took (08-01 deliberately scoped its verification to `make test-portfolio` / `make test-orders`, excluding the oracle, for this exact reason). The full suite is otherwise green (723 passed) and mypy --strict is clean — the structural half of the D-13 definition-of-done is met. The remaining red is exclusively the 08-03-owned oracle re-freeze.

**No Wave-1 (08-01) regression detected:** mypy surfaced zero errors in `portfolio.py` / `metrics_manager.py` / `order_validator.py`; the suite surfaced zero failures traceable to those files. 08-01 left its files complete.

## Test Count

Real collected test count: **724** (723 passed, 1 design-failing oracle). The plan referenced "716 collected" as a then-current figure; the actual current count is 724 (not the legacy 274). Recorded here per Task 3's instruction not to hardcode a stale count.

## Handoff to 08-03
- `tests/golden/*` was NOT touched — the clean Decimal numbers are handed to 08-03 for regeneration + the conditional `REFREEZE-M5C-DECIMAL` note.
- The equity-curve `total_equity` precision diff (behavioral identity preserved, `final_equity` byte-exact at 46189.87730727451) is the single artifact 08-03 must re-freeze.
- mypy --strict clean (151 files) + full suite green minus the one oracle test = the structural precondition for the 08-03 re-freeze and cross-validation against clean numbers (D-07) is satisfied.

## Self-Check: PASSED

- Files: `itrader/trading_system/backtest_trading_system.py`, `scripts/run_backtest.py`, `08-02-SUMMARY.md` — all FOUND on disk
- Commits: `d9b8789` (Task 1), `eb89da9` (Task 2) — verified present in git history
- mypy --strict: Success, 151 files; full suite: 723 passed / 1 sanctioned-design-failure
- Scope guard: no 08-01-owned file modified; `tests/golden/*` untouched

---
*Phase: 08-m5c-cross-validation-final-oracle*
*Completed: 2026-06-08*
