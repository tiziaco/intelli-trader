# Phase 8: M5c — Cross-Validation & Final Oracle - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-06-08
**Phase:** 8-m5c-cross-validation-final-oracle
**Areas discussed:** Decimal cleanup scope, Engine alignment, Reconciliation gate, Tolerance, Divergence policy, Decimal re-freeze sequencing, Cross-validation harness, Nautilus inclusion

---

## Decimal cleanup scope

User-raised: noted that an end-of-Phase-6 map-codebase run surfaced Decimal/float bugs in CONCERNS.md (some prices not Decimal) and asked whether to include them.

| Option | Description | Selected |
|--------|-------------|----------|
| Golden-path only | Fix Portfolio.total_* float properties + MetricsManager Decimal→float coercion + golden-path validator cash checks; before cross-val; named re-freeze. Defer TradingInterface (live-mode). | ✓ |
| All float leaks incl. live | Also fix TradingInterface float signatures / price=0.0 — pulls D-live work in. | |
| Defer entirely | Keep Phase 8 strictly cross-validation; freeze with the float boundary intact. | |

**User's choice:** Golden-path only
**Notes:** Justified as not-scope-creep — ROADMAP SC#3 requires "no float money," and Phase 8 is the last place to close it. Fix before cross-validation so float-rounding divergence isn't misattributed to reference engines. TradingInterface leak is live-mode (D-live), deferred. → CONTEXT D-06/D-07/D-08/D-09.

---

## Engine alignment

| Option | Description | Selected |
|--------|-------------|----------|
| Force-match exactly | Configure both reference engines to iTrader's exact rules (next-bar-open fills, 95% sizing, long-only, zero fees, same params); replicate the SMA-filter-gates-both quirk. Divergence = real finding. | ✓ |
| Match what each engine supports | Align cleanly-exposed knobs; accept fill-timing gaps; reconcile at metric level. | |
| Natural mode + explain | Run each engine idiomatically; explain all divergence. | |

**User's choice:** Force-match exactly
**Notes:** → CONTEXT D-01. Caveat surfaced: indicator-library differences can still shift a trade ±1 bar.

---

## Reconciliation gate

| Option | Description | Selected |
|--------|-------------|----------|
| Trade-level primary + metric confirm | Same trade count + entry/exit bars (rare ±1-bar shifts traced to a cause); metrics agree within a tight band. | ✓ |
| Metric-level only | Reconcile headline metrics within tolerance; no trade-for-trade. | |
| Exact trade-for-trade | Identical trades + bars, zero shifts. | |

**User's choice:** Trade-level primary + metric confirm
**Notes:** → CONTEXT D-02/D-03. Exact-trade-for-trade rejected as possibly unachievable without indicator reimplementation.

---

## Tolerance

| Option | Description | Selected |
|--------|-------------|----------|
| Tiered: tight default, wider if a trade shifts | ~≤1% on headline metrics when trades match; wider only for a fully-attributed ±1-bar shift. | ✓ |
| Flat 1% | All metrics within 1%, no exceptions. | |
| Flat 5% | All metrics within 5%. | |

**User's choice:** Tiered
**Notes:** → CONTEXT D-04. Headline set = summary.json metrics (final_equity, trade_count, cagr, max_drawdown, profit_factor, sharpe, sortino, win_rate).

---

## Divergence policy

| Option | Description | Selected |
|--------|-------------|----------|
| Root-cause decides, fix only if iTrader is wrong | Trace every gap; iTrader bug → fix → named re-freeze; legit engine difference → document, keep iTrader's numbers. Default: iTrader correct unless proven otherwise. | ✓ |
| iTrader is authoritative — explain only | iTrader's numbers freeze unchanged; all divergence documented as structural. | |
| Reference engines are ground truth | Calibrate iTrader to match the references. | |

**User's choice:** Root-cause decides, fix only if iTrader is wrong
**Notes:** → CONTEXT D-05. Reference-as-ground-truth rejected (engines have their own quirks).

---

## Decimal re-freeze sequencing

| Option | Description | Selected |
|--------|-------------|----------|
| Separate named re-freeze, before cross-val | Decimal cleanup lands first as REFREEZE-M5C-DECIMAL with its own diff note; cross-val runs against clean numbers; any bug-fix gets its own re-freeze. | ✓ |
| One consolidated final re-freeze | Apply all changes, freeze once with a combined note. | |
| Cleanup must be byte-exact inert | Attempt as behavior-preserving refactor; re-freeze only if precision shifts values. | |

**User's choice:** Separate named re-freeze, before cross-val
**Notes:** → CONTEXT D-08. Follows Phase 6/7 one-attributable-diff-per-change discipline.

---

## Cross-validation harness

| Option | Description | Selected |
|--------|-------------|----------|
| One-time validation + committed report | Reference engines as dev deps; scripts/cross_validate.py produces a committed report; frozen oracle stays the permanent regression gate. | ✓ |
| Permanent CI gate | Wire the three-engine comparison into make test. | |
| Throwaway, report only | Ad-hoc run, no committed harness code. | |

**User's choice:** One-time validation + committed report
**Notes:** → CONTEXT D-10/D-11. Permanent-CI rejected (dev-dep weight, reference maintenance).

---

## Nautilus inclusion

User-raised: asked whether to also cross-validate against Nautilus Trader as the more professional framework.

| Option | Description | Selected |
|--------|-------------|----------|
| Optional non-gating third reference | Keep backtesting.py + backtrader gating (locked M5-10); add Nautilus to the harness/report, reconciled + explained, but not a pass/fail gate. | ✓ |
| Full gating third engine | Nautilus as a first-class gating reference, must pass the tolerance gate. | |
| Two engines only, defer Nautilus | Stick to locked scope; note Nautilus as deferred. | |

**User's choice:** Optional non-gating third reference
**Notes:** → CONTEXT D-12. Nautilus acknowledged as most production-grade + closest architectural mirror to iTrader; non-gating so its richer model / force-match difficulty can't stall the definition-of-done freeze.

---

## Claude's Discretion

- Cross-validation report artifact location/format (suggested `tests/golden/CROSS-VALIDATION.md`); re-freeze note naming.
- Reference-engine versions to pin in the poetry dev group.
- Faithfulness of SMA/MACD reimplementation in each reference engine vs absorbing indicator difference under D-03.
- Single-script vs per-engine-module harness shape; Nautilus instrument/venue/bar-spec config.
- Exact float→Decimal retype boundaries in Portfolio / MetricsManager / EnhancedOrderValidator and the resulting representation change in summary.json / equity.csv.

## Deferred Ideas

- TradingInterface Decimal cleanup (live-mode) → D-live.
- Nautilus as a gating engine → future validation effort.
- Permanent multi-engine CI gate → revisit if continuous external regression is ever needed.
- Wall-clock leaks in domain code (datetime.now() in MetricsManager/PositionManager/SimulatedExchange) → future hardening pass (not a golden-output defect).
- Multi-strategy / multi-symbol cross-validation → out of program scope.
