---
gsd_state_version: 1.0
milestone: v1.2
milestone_name: Consolidation
status: planning
last_updated: "2026-06-11T08:26:13.167Z"
last_activity: 2026-06-11
progress:
  total_phases: 10
  completed_phases: 1
  total_plans: 2
  completed_plans: 2
  percent: 10
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-11 — milestone v1.2 Consolidation started)

**Core value:** A single backtest run of `SMA_MACD` on the golden BTCUSD CSV produces correct, deterministic, cross-validated numbers — now extended to a trustworthy, regression-locked engine across the *entire* feature surface (v1.1 shipped).
**Current focus:** Phase 999.2 — nplus2 persistence and performance

## Current Position

Phase: 999.2
Plan: Not started
Status: Ready to plan
Last activity: 2026-06-11

## Milestone Gate (v1.2 — applies to EVERY phase)

**Behavior-preserving — re-baselines NOTHING.** Every phase must hold:

- `pytest tests/integration` byte-exact oracle: **134 trades / `final_equity 46189.87730727451`**
- `pytest tests/e2e -m e2e` **58/58 green** (no leaf re-baselined); full suite green
- **`mypy --strict` clean** across all source files
- No new float-for-money; single UUIDv7 ID scheme (no second `uuid4()` on the run path)
- **FRAGILE-zone rule:** any touch of `order_manager.py` fill-reconciliation / reservation-release
  requires the golden-master re-run; the terminal-status / `should_release` / `finally`-release
  interplay must never change. Phase 6 (MOD-01) is the dedicated, isolated, LAST phase — nothing
  else ships in it.

## Phase Map (v1.2 — Phases 1-6)

Execution order: 1 → 2 → 3 → 4 → 5 → 6. Derived from V1.2-CLEANUP-REVIEW §6 batches.
(Numbering reset for v1.2, matching v1.1; v1.1 phase dirs archived to `.planning/milestones/v1.1-phases/`.)

| Phase | Name | Requirements | Cleanup-review batch |
|-------|------|--------------|----------------------|
| 1 | Dead Code & Doc Hygiene | DEAD-01, DEAD-02 | Batch 1 |
| 2 | Locked-Decision Conformance | DEC-01, DEC-02, DEC-03 | Batch 2 (⚠ W2-10) |
| 3 | Hot-Path Performance | PERF-01, PERF-02, PERF-03 | Batches 3 + 4 |
| 4 | Type Modeling | TYPE-01..05 | Batches 5 + 6 (⚠ W2-01) + SYN-02 |
| 5 | Naming & Encapsulation | NAME-01..04 | Batch 7 (⚠ throughout) |
| 6 | Order-Manager Decomposition | MOD-01 | Batch 8 — FRAGILE, isolated, LAST |

## Performance Metrics

**Velocity (v1.1):**

- Total plans completed: 33
- Average duration: — min
- Total execution time: 0.0 hours

*Updated after each plan completion. v1.0 velocity is archived in `milestones/v1.0-MILESTONE-AUDIT.md`.*

## Accumulated Context

### Decisions

Active decisions live in PROJECT.md Key Decisions. Load-bearing program constraints still in force for v1.2:

- Money = Decimal end-to-end; float money is a correctness defect (v1.2 DEC-01/DEC-02 close two remaining boundary violations).
- IDs = single UUIDv7 scheme via `uuid-utils` (v1.2 DEC-03 retires the lingering `uuid4()` second scheme).
- v1.2 is **behavior-preserving** — the v1.0 final golden oracle (134 trades / `final_equity 46189.87730727451`) is NOT re-baselined; this milestone re-baselines nothing. Any result-changing finding is owner-gated and deferred to the next milestone (Engine Surface Completion, Backlog 999.5).
- **Phase numbering reset to 1 for v1.2** (matching v1.1; previously drafted as Phases 10-15). The v1.1 phase working dirs were archived to `.planning/milestones/v1.1-phases/`, so there is no directory collision.
- **MOD-01 isolation (HARD):** the `order_manager.py` god-module split is its own dedicated, isolated, LAST phase (Phase 6) — pure code-motion, byte-exact, nothing else bundled in.
- **Pulled FORWARD into v1.2** (out of the 999.5 backlog seed): SYN-02 `BaseStrategyConfig` relocation → Phase 4 / TYPE-05; W1-12 MACD-guard reorder → Phase 3 / PERF-03; FL-01/FL-02 stale-text correction → Phase 1 / DEAD-02.
- **Deferred to 999.5 (NOT in v1.2):** W2-02 `Order.action: Side` + W1-11 snapshot threading → SIG; W4-02/03/05/06/07 + SYN-03/SYN-05 composition → COMP; W1-05 incremental indicators → IND; W4-09 `create_order` gating → LIFE. W4-04 validator-overlap is DOCUMENTED in v1.2 (DEAD-02) but only refactored if SIG touches it.

(v1.1 per-plan decisions are archived in `milestones/v1.1-ROADMAP.md` and the phase records under `milestones/v1.1-phases/`.)

- [Phase ?]: D-03 trim-to-truth: removed obsolete screener_event_handler Known-Bug from CONCERNS.md; trimmed ROADMAP 999.5-(d) to one FL-01/FL-02 closure line (net reduction, 260610-sjp kept)
- [Phase ?]: D-01/D-02: four conventions documented in CONVENTIONS.md + CLAUDE.md pointer; W4-04 validator overlap documented justified-by-decision (code NOT removed)

### Pending Todos

None yet.

### Blockers/Concerns

- **Behavior-preserving guardrail (milestone-wide):** every v1.2 phase must re-run the SMA_MACD golden master byte-exact (zero drift) and keep `pytest tests/e2e -m e2e` 58/58 green. No phase re-baselines the oracle.
- **FRAGILE zone:** `order_manager.py` fill-reconciliation / reservation-release (CONCERNS.md Fragile Areas) — golden-master re-run mandatory on any touch; terminal-status / `should_release` / `finally`-release interplay must not change. Phase 6 handles the split in isolation.
- **BEHAVIOR-SENSITIVE cleanup-review items to gate carefully:** W2-10 (Phase 2 — confirm the golden run never routes the below-minimum comparison before fixing), W2-01 (Phase 4 — int→string enum value change; grep tests/serialization for int-value assertions first), the Phase 5 naming renames (oracle re-run after each).
- **Indentation hazard:** tabs in handler modules; 4 spaces in `config/`/`core/`/`price_handler/feed/`/events package — match the file, never normalize (a mixed-indentation edit breaks a tab file).
- New requirements discovered during execution are added to REQUIREMENTS.md with traceability, not silently folded into a running phase.

### Quick Tasks Completed

(v1.0 quick tasks archived in `milestones/v1.0-MILESTONE-AUDIT.md`.)

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260610-sjp | Close FL-01 & FL-02 fix-list residuals + reconcile FIX-LIST.md status | 2026-06-10 | 4db1907 | [260610-sjp-close-fl01-fl02](./quick/260610-sjp-close-fl01-fl02/) |
| Phase 01 P01 | 2 | 3 tasks | 5 files |
| Phase 01 P02 | 2 | 3 tasks | 4 files |

## Bookkeeping

- **v1.1 phase dirs archived:** the v1.1 phase working directories were moved to
  `.planning/milestones/v1.1-phases/` (done before the v1.2 phase-number reset, so renumbering
  v1.2 to Phases 1-6 produced no directory collision).

## Deferred Items

Program-level items out of scope for v1.2, with their target milestone:

| Category | Item | Status | Target |
|----------|------|--------|--------|
| Engine surface | Signal entry price/`order_type` (SIG), composition/config API (COMP), declared-indicator framework (IND), TIF/run-end expire (LIFE) | Deferred | Engine Surface Completion (Backlog 999.5) |
| D-margin | Margin/liquidation model, shorts, leverage, levered Kelly, trailing stop, real pair trading | Deferred | N+2 (Backlog 999.4) |
| D-compliance | Compliance layer (long_only/short_only enforcement) | Deferred | N+2 (with shorts) |
| D-sql | SQL persistence backends (order/price/reporting/config) | Deferred | N+3 (Backlog 999.2) |
| D-screener | Production screener / ranking / rebalance loop (minimal `membership` shipped v1.1) | Deferred | N+4 (Backlog 999.3) |
| D-live | Live mode (streaming, TradingInterface modify/cancel, live threading, secrets) | Deferred | N+4 |
| D-multiasset | Multi-currency accounting, trading calendars, corporate actions (forex/equities/ETF) | Deferred | indefinite (crypto-first) |
| D-oanda | OANDA + non-crypto adapters | Deferred | with D-multiasset |
| OUT | `my_strategies/*` (relocated to separate repo by user) | Out-of-band | — |

v1.0 milestone-close acknowledgments (12 advisory/UAT/verification items) are recorded in `milestones/v1.0-MILESTONE-AUDIT.md`.

### v1.1 milestone-close acknowledgments (2026-06-10)

The pre-close artifact audit flagged 4 items that were verified **already complete** and are
recorded here as accepted at close. The repo is canonically clean (bundled `audit.cjs` → 0 open);
these remain flagged **only** by a `gsd-sdk` v1.42.3 SDK-port bug — that port reads a literal
`SUMMARY.md` and so cannot see the mandated `${quick_id}-SUMMARY.md` files (the canonical scanner
handles both). Each carries `status: complete` frontmatter.

| Category | Item | Status |
|----------|------|--------|
| quick_task | 260605-ih3 — fix WR-01 weekly/DST check_timeframe anchoring | complete (SDK-port false positive) |
| quick_task | 260608-a59 — demote by-design signal-rejection logs to warning | complete (SDK-port false positive) |
| quick_task | 260608-qe2 — pre-close enum cleanup (TradingDirection/SystemStatus canonical homes) | complete (SDK-port false positive) |
| quick_task | 260610-sjp — close FL-01 & FL-02 + reconcile FIX-LIST | complete (SDK-port false positive) |

Optional tracked hygiene (non-blocking): formal Nyquist Wave-0 incomplete on phases 3,4,5,6,7,9 /
absent on 2,8; empty `requirements_completed` SUMMARY frontmatter on phases 1,4,5,7,9. See
`milestones/v1.1-MILESTONE-AUDIT.md`.

## Session Continuity

Last session: 2026-06-11T08:26:13.159Z
Resume file: .planning/phases/02-locked-decision-conformance/02-CONTEXT.md

## Operator Next Steps

- Plan the first v1.2 phase with `/gsd:plan-phase 1` (Dead Code & Doc Hygiene).
