# Phase 8 — M5c Cross-Validation & Final Oracle — Plan Outline

**Phase goal:** Prove `SMA_MACD` numbers on the golden BTCUSD CSV are trustworthy by cross-validating against `backtesting.py` + `backtrader` (+ optional non-gating Nautilus), then freeze the final authoritative numerical oracle and verify the program definition-of-done.

**Requirement:** M5-10 (single locked requirement — carried by every plan). D-13 DoD gate threads through the whole phase.

**Hard sequencing constraint (D-07):** the golden-path Decimal cleanup (D-06) must land and re-freeze (`REFREEZE-M5C-DECIMAL`, D-08) BEFORE any cross-validation runs — so float-rounding divergence is never misattributed to a reference engine. All cross-validation plans depend on the Decimal-cleanup wave.

| Plan ID | Objective | Wave | Depends On | Requirements |
|---------|-----------|------|------------|--------------|
| 08-01 | Golden-path Decimal cleanup: retype `Portfolio.total_*` properties → `Decimal` (drop `float(...)` casts, keep aggregation in Decimal), clean `MetricsManager` money coercions (money fields Decimal end-to-end; float boundary moved to the statistical-ratio metric *input*, not the Portfolio property), and convert `EnhancedOrderValidator` golden-path cash checks to native Decimal. (D-06) | 1 | — | M5-10 |
| 08-02 | Caller fan-out + mypy --strict propagation sweep: fix every `float + Decimal` mixed-arithmetic / type-expectation site surfaced by the 08-01 retype across reporting / validator / `run_backtest` consumers; `make typecheck` clean and full suite green under `filterwarnings=["error"]`. (D-06 / D-13) | 2 | 08-01 | M5-10 |
| 08-03 | Oracle regeneration + conditional `REFREEZE-M5C-DECIMAL`: `make backtest` against clean Decimal numbers; diff regenerated `output/` vs frozen `tests/golden/*`; if the value shifts, write the named expected-diff re-freeze note (owner sign-off) and re-freeze the golden artifacts; if byte-exact inert, document no-shift. These clean numbers are the cross-validation baseline. (D-07 / D-08) | 3 | 08-02 | M5-10 |
| 08-04 | Add pinned dev-deps (`backtesting`, `backtrader`, optional `nautilus-trader`) to the poetry dev group + engine import/run smoke gate — validate `import backtrader` runs end-to-end on numpy 2.x / Python 3.13 (select fork/shim fallback HERE if it fails) before any harness is built; confirm engines are dev-group-only and never imported under `tests/`. (D-10) | 4 | 08-03 | M5-10 |
| 08-05 | Shared `ta`-indicator precompute + gating force-match engine modules: compute SMA(50)/SMA(100)/MACD-hist(6,12,3) once via iTrader's exact `ta` calls and inject the identical arrays into both engines (D-03); `backtesting.py` via `FractionalBacktest` (fractional-units landmine) and `backtrader` via a custom float sizer; replicate next-bar-open fills + the filter-gates-both-entry-and-exit quirk verbatim (D-01). (D-01 / D-03 / D-10) | 5 | 08-04 | M5-10 |
| 08-06 | Optional Nautilus non-gating module: own module behind a try-guard so install/config friction degrades gracefully (report "not reconciled — {reason}", never stall the freeze). Implemented last; force-match approximated to D-01. (D-12) | 5 | 08-04 | M5-10 |
| 08-07 | `scripts/cross_validate.py` orchestrator + reconciliation: run all engines force-matched, recompute headline metrics through iTrader's own `reporting/metrics.py` (apples-to-apples, not engine-native annualization), build the trade-level-primary + metric-level-secondary reconciliation table (D-02/D-04), emit committed `tests/golden/CROSS-VALIDATION.md`. (D-02 / D-04 / D-10) | 6 | 08-05, 08-06 | M5-10 |
| 08-08 | Per-divergence root-cause (D-05) + conditional bug-fix re-freeze: trace every divergence to a root cause; iTrader-bug → fix + named `REFREEZE-M5C-<bug>` (owner sign-off); legitimate reference-engine semantic difference → document, keep iTrader numbers. Record dispositions in `CROSS-VALIDATION.md`. (D-05) | 7 | 08-07 | M5-10 |
| 08-09 | Freeze final oracle (D-11) + full D-13 definition-of-done gate: the post-cleanup-and-any-fix `tests/golden/*` is the final authoritative oracle; verify DoD — `make backtest` non-trivial trade log + equity curve, `make typecheck` clean, no float money on golden path, single UUIDv7 scheme, deterministic double-run byte-identical, full live suite green (verify real count, ~716, not hardcoded 274), run-path integration test green against the FINAL oracle. (D-11 / D-13) | 8 | 08-08 | M5-10 |

## Sequencing notes

- **D-07 enforced:** plans 08-04 through 08-09 (all cross-validation + freeze work) depend transitively on 08-03 (the Decimal re-freeze). Cross-validation never runs against unclean numbers.
- **Decimal cleanup split into three waves (08-01 → 08-02 → 08-03)** rather than one plan: the retype (08-01), the mypy/caller fan-out sweep it triggers (08-02, RESEARCH risk #4 "Decimal retype fan-out"), and the oracle regen + owner-gated re-freeze (08-03) are distinct concerns with a shared-file dependency chain — combining them would exceed the per-plan context budget and fuse a checkpoint (re-freeze owner sign-off) with implementation.
- **08-05 and 08-06 are same-wave parallel** (Wave 5): they create disjoint files (per-engine modules) and both depend only on 08-04's installed deps. Nautilus (08-06) is non-gating, so 08-07 can proceed even if 08-06 degrades.
- **08-08 isolated** (Wave 7): it is conditionally result-changing (a real iTrader bug fix + named re-freeze + owner sign-off) and must not be fused with the reconciliation reporting in 08-07.
- **08-09 is the terminal DoD gate** (Wave 8): the final freeze + program definition-of-done verification.
- **Source-audit note:** M5-10 is the single locked requirement and is carried by every plan. The DoD gate (D-13) and re-freeze discipline (D-08/D-11) span the phase. Deferred per CONTEXT and NOT planned: `TradingInterface` Decimal cleanup (→ D-live), Nautilus-as-gating, permanent multi-engine CI gate, wall-clock leaks in domain code, multi-strategy/multi-symbol cross-validation.

## OUTLINE COMPLETE
**Plan count: 9** (waves 1–8; 08-05/08-06 parallel in wave 5).
