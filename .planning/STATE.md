---
gsd_state_version: 1.0
milestone: v1.1
milestone_name: "Backtest Trustworthiness: Breadth"
status: ready_to_plan
last_updated: 2026-06-09T15:06:03.029Z
last_activity: 2026-06-09
progress:
  total_phases: 12
  completed_phases: 4
  total_plans: 9
  completed_plans: 9
  percent: 33
stopped_at: Phase 04 complete (3/3) — ready to discuss Phase 999.2
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-09)

**Core value:** A single backtest run of `SMA_MACD` on the golden BTCUSD CSV produces correct, deterministic, cross-validated numbers — the backtest path must import, run, and yield trustworthy results.
**Current focus:** Phase 999.2 — nplus2 persistence and performance

## Current Position

Phase: 999.2 of 3 (nplus2 persistence and performance)
Plan: Not started
Status: Ready to plan
Last activity: 2026-06-09

## Performance Metrics

**Velocity (v1.1):**

- Total plans completed: 12
- Average duration: — min
- Total execution time: 0.0 hours

*Updated after each plan completion. v1.0 velocity is archived in `milestones/v1.0-MILESTONE-AUDIT.md`.*

## Accumulated Context

### Decisions

Active decisions live in PROJECT.md Key Decisions (including the five v1.1 decisions: crypto-first; dedicated `tests/e2e/` + `e2e` marker; hand-verify-once-then-regression-lock; normalize data via committed script not loader logic; minimal real universe). v1.0 per-plan decisions are archived in `milestones/v1.0-MILESTONE-AUDIT.md` and the v1.0 phase records under `milestones/v1.0-phases/`.

Load-bearing program constraints still in force for v1.1:

- Money = Decimal end-to-end; float money is a correctness defect.
- IDs = single UUIDv7 scheme via `uuid-utils`.
- v1.1 is **behavior-preserving** — the v1.0 final golden oracle (134 trades / `final_equity 46189.87730727451`) is NOT re-baselined; any result-changing finding is owner-gated, never silently folded in.
- [Phase ?]: D-06 volume check relaxed to non-negative (NaN/negative still raise): zero-volume bars on SOLUSD(11)/AAVEUSD(35) are a provider missing-data sentinel, not true zeros; OHLC is real and bar volume is inert on the v1.1 run path
- [Phase ?]: is_active/active_membership added alongside derive_membership (D-03); span model inclusive both ends (D-01); active_membership returns set[str]
- [Phase ?]: [Phase 03 P02]: feed is the single span-aware observability owner (D-04) — silent for pre-listing/post-end, warns only on a true mid-life gap; span bounds cached as tz-aware pd.Timestamp; bar/fill path untouched (oracle-dark)
- [Phase ?]: [Phase 03 P03]: optional csv_paths passthrough on TradingSystem.__init__ (default None = byte-identical golden behavior, oracle-dark); UNIV-02 engine-proven on synthetic fixtures (no crash, no look-ahead over the union window) — real ETH/SOL/AAVE E2E deferred to Phase 9 (D-06)

### Pending Todos

None yet.

### Blockers/Concerns

- **Behavior-preserving guardrail:** the Phase 5 strategy-interface refactor must re-run the SMA_MACD golden master byte-exact (zero drift). Phase 1 cleanup and all later phases must not re-baseline the oracle.
- **E2E oracle discipline:** each new scenario's expected fills/PnL are hand-verified once, then frozen as a regression lock (a lock proves stability, not correctness — verification happens before the freeze).
- New requirements discovered during execution are added to REQUIREMENTS.md with traceability, not silently folded into a running phase.

### Quick Tasks Completed

None this milestone. (v1.0 quick tasks archived in `milestones/v1.0-MILESTONE-AUDIT.md`.)

## Deferred Items

Program-level items out of scope for v1.1, with their target milestone:

| Category | Item | Status | Target |
|----------|------|--------|--------|
| D-margin | Margin/liquidation model, shorts, leverage, levered Kelly, trailing stop, real pair trading | Deferred | v1.2 |
| D-compliance | Compliance layer (long_only/short_only enforcement) | Deferred | v1.2 (with shorts) |
| D-sql | SQL persistence backends (order/price/reporting/config) | Deferred | v1.3 |
| D-screener | Production screener / ranking / rebalance loop (minimal `membership` IS in v1.1 Phase 3) | Deferred | v1.4 |
| D-live | Live mode (streaming, TradingInterface modify/cancel, live threading, secrets) | Deferred | v1.4 |
| D-multiasset | Multi-currency accounting, trading calendars, corporate actions (forex/equities/ETF) | Deferred | indefinite (crypto-first) |
| D-oanda | OANDA + non-crypto adapters | Deferred | with D-multiasset |
| OUT | `my_strategies/*` (relocated to separate repo by user) | Out-of-band | — |

v1.0 milestone-close acknowledgments (12 advisory/UAT/verification items) are recorded in `milestones/v1.0-MILESTONE-AUDIT.md`.
| Phase 02 P01 | 2min | 3 tasks | 5 files |
| Phase 03 P01 | 4 | 2 tasks | 3 files |
| Phase 03 P02 | 4 | 3 tasks | 3 files |
| Phase 03 P03 | 12min | 2 tasks | 2 files |
| Phase 04 P03 | 25min | 2 tasks | 11 files |

## Session Continuity

Last session: 2026-06-09T14:53:21.159Z
Resume file: None

## Operator Next Steps

- Phase 04 (e2e-harness-framework) is COMPLETE — the shared harness + e2e marker + the ONE hand-verified canary leaf are committed.
- `/clear`, then `/gsd:plan-phase 5` — plan the next phase (the canary leaf is the copy-template for Phase 6-9 scenario authors).
