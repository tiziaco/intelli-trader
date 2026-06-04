---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
stopped_at: Phase 2 context gathered
last_updated: "2026-06-04T17:46:18.912Z"
last_activity: 2026-06-04
progress:
  total_phases: 8
  completed_phases: 1
  total_plans: 12
  completed_plans: 8
  percent: 13
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-04)

**Core value:** A single backtest run of `SMA_MACD` on the golden BTCUSD CSV produces correct, deterministic, cross-validated numbers — the backtest path must import, run, and yield trustworthy results.
**Current focus:** Phase 02 — m2a-identity-money-determinism

## Current Position

Phase: 02 (m2a-identity-money-determinism) — EXECUTING
Plan: 4 of 7
Status: Ready to execute
Last activity: 2026-06-04

Progress: [███████░░░] 67%

## Performance Metrics

**Velocity:**

- Total plans completed: 5
- Average duration: — min
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01 | 5 | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 01 P01 | 12 | 3 tasks | 4 files |
| Phase 01 P02 | 10 | 2 tasks | 1 files |
| Phase 01 P03 | 13 | 3 tasks | 3 files |
| Phase 01 P04 | 22 | 3 tasks | 8 files |
| Phase 01 P05 | 18 | 3 tasks | 4 files |
| Phase 02 P01 | 6 | 2 tasks | 6 files |
| Phase 02 P02 | 4 | 4 tasks | 6 files |
| Phase 02 P03 | 13 | 3 tasks | 11 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table. Recent decisions affecting current work:

- Money = Decimal end-to-end (float money is a correctness defect)
- IDs = single UUIDv7 scheme via `uuid-utils`
- Golden-master two-layer oracle: behavioral oracle (trade timing) is law M2→M4; numerical oracle re-baselines only after M2 (Phase 3) and after M5 (Phase 8)
- Position sizing: strategy declares policy + SL/TP, order/risk layer resolves per-portfolio quantity; M1 implements the minimal seam (Phase 1) so M5 extends rather than replaces it (Phase 7)
- [Phase ?]: D-07: csv/offline feed lives inside PriceHandler, skips SqlHandler + CCXT (Phase 1 Plan 2)
- Plan 01-04: oracle generator pins dataset/window/cash/params as literals; equity sourced from metrics snapshots (not the broken _prepare_data)
- Plan 01-04: DEF-01-B(3) resolved as sizing-before-validation (narrow gate), preserving test_zero_quantity_signal; long-only SELL exit sizes to close the open long
- Plan 01-04: DEF-01-A resolved with minimal float-coercion at the fill->transaction commission boundary (overlaps M4 #22 — reconcile at M4)
- [Phase ?]: Plan 01-05: blessed BTCUSD SMA_MACD oracle frozen into committed test/golden/ and regression-locked by an exact (no-tolerance, D-13) run-path integration test; Phase 01 complete
- [Phase ?]: Plan 01-05: DEF-01-C (no margin/liquidation model — un-liquidated short liability drives total_equity negative) BLESSED into the M1 oracle as current-behavior-to-preserve, deferred to M5
- [Phase ?]: Plan 02-01: mypy --strict gate (make typecheck) stood up with deferral overrides for 7 D-live/D-sql/D-oanda/D-screener modules (D-05/D-06); gate runs but errors deferred to Plan 07
- [Phase ?]: Plan 02-01: UUID Wave 0 scaffold lands red (asserts stdlib uuid.UUID type); money/clock scaffolds co-located with Plan 02 to avoid same-wave scaffold race
- [Phase ?]: Plan 02-03: single UUIDv7 scheme via uuid_utils.compat.uuid7(); integer type-prefix scheme deleted (D-12/D-13/D-14)
- [Phase ?]: Plan 02-03: InMemoryOrderStorage native-UUID keyed + flat Dict[uuid.UUID, Order] index for O(1) lookup (D-14, PERF2); nested dicts retained, scan elimination deferred to M4-06
- [Phase ?]: Plan 02-03: removed int(portfolio_id) coercion in portfolio_handler.on_fill (Rule 1/3 deviation; file unowned by phase-02 plans) to keep suite green post UUID migration

### Pending Todos

None yet.

### Blockers/Concerns

- Phase 1 first work is Critical #34: the run path does not import today (the only Critical that blocks execution). Everything downstream depends on resolving it, then capturing + committing the reference output.
- Golden-master gates are hard phase-boundary criteria: end of Phase 3 (re-freeze numerical oracle), Phases 4–5 behavior/value-preserving, end of Phase 8 (cross-validate + freeze final oracle).
- New issues found during execution go to COVERAGE-INDEX §E (delta log) with owner approval — never silently folded into the running phase.

## Deferred Items

Items explicitly out of this program's scope (see PROJECT.md Out of Scope / COVERAGE-INDEX §D):

| Category | Item | Status | Deferred At |
|----------|------|--------|-------------|
| D-live | Live mode (Binance streaming, TradingInterface, live threading, secrets) | Deferred | Program start |
| D-sql | SQL persistence backends (order/price/reporting/config) | Deferred | Program start |
| D-screener | Screener / rebalance loop wiring | Deferred | Program start |
| D-compliance | Compliance layer (long_only/short_only) | Deferred | Program start |
| D-oanda | OANDA + Binance adapters | Deferred | Program start |
| OUT | `my_strategies/*` (relocated to separate repo by user) | Out-of-band | Program start |

## Session Continuity

Last session: 2026-06-04T17:45:55.782Z
Stopped at: Phase 2 context gathered
Resume file: None
