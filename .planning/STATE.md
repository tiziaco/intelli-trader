---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: executing
stopped_at: Phase 1 context gathered
last_updated: "2026-06-04T14:07:56.672Z"
last_activity: 2026-06-04
progress:
  total_phases: 8
  completed_phases: 0
  total_plans: 5
  completed_plans: 3
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-04)

**Core value:** A single backtest run of `SMA_MACD` on the golden BTCUSD CSV produces correct, deterministic, cross-validated numbers — the backtest path must import, run, and yield trustworthy results.
**Current focus:** Phase 01 — m1-ignition-lock-the-oracle

## Current Position

Phase: 01 (m1-ignition-lock-the-oracle) — EXECUTING
Plan: 4 of 5
Status: Ready to execute
Last activity: 2026-06-04

Progress: [██████░░░░] 60%

## Performance Metrics

**Velocity:**

- Total plans completed: 0
- Average duration: — min
- Total execution time: 0.0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| - | - | - | - |

**Recent Trend:**

- Last 5 plans: —
- Trend: —

*Updated after each plan completion*
| Phase 01 P01 | 12 | 3 tasks | 4 files |
| Phase 01 P02 | 10 | 2 tasks | 1 files |
| Phase 01 P03 | 13 | 3 tasks | 3 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table. Recent decisions affecting current work:

- Money = Decimal end-to-end (float money is a correctness defect)
- IDs = single UUIDv7 scheme via `uuid-utils`
- Golden-master two-layer oracle: behavioral oracle (trade timing) is law M2→M4; numerical oracle re-baselines only after M2 (Phase 3) and after M5 (Phase 8)
- Position sizing: strategy declares policy + SL/TP, order/risk layer resolves per-portfolio quantity; M1 implements the minimal seam (Phase 1) so M5 extends rather than replaces it (Phase 7)
- [Phase ?]: D-07: csv/offline feed lives inside PriceHandler, skips SqlHandler + CCXT (Phase 1 Plan 2)

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

Last session: 2026-06-04T14:07:56.663Z
Stopped at: Phase 1 context gathered
Resume file: None
