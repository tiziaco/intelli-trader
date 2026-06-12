---
gsd_state_version: 1.0
milestone: v1.3
milestone_name: Engine Surface Completion
status: planning
last_updated: "2026-06-12T10:12:12.581Z"
last_activity: 2026-06-12
progress:
  total_phases: 0
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-12 — milestone v1.2 Consolidation shipped)

**Core value:** A single backtest run of `SMA_MACD` on the golden BTCUSD CSV produces correct, deterministic, cross-validated numbers — now on a clean, decomposed engine after the v1.2 consolidation (cleanup-review + CONCERNS debt cleared byte-exact).
**Current focus:** No active milestone. Next candidate: Engine Surface Completion (Backlog 999.5) — promote with `/gsd:new-milestone`.

## Current Position

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-06-12 — Milestone v1.3 started

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

- Total plans completed: 54
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
- [Phase 02 / 2026-06-11] D-07 gap-discovery delta (owner-flagged, bounded, NOT silently folded): the W2-10/DEC-02/SC-2 "latent `Decimal < float` TypeError" on the below-minimum validation path was a MISDIAGNOSIS — Decimal-vs-float COMPARISON works in Py3; only arithmetic raises and there is none on `_min/_max_order_size`. DEC-02 reframed as float-for-money consistency; SC-2 (ROADMAP) + DEC-02 (REQUIREMENTS) wording corrected. Evidence: the green `tests/e2e/cash/release_refused` leaf (Decimal-vs-float `> _max` REFUSED).
- [Phase ?]: Phase 05 NAME-01: events_queue to global_queue (D-02) + canonical count_orders_by_status across 5 sites (D-01); oracle-dark, byte-exact, mypy strict clean
- [Phase 05]: Phase 05 NAME-03: D-06 _routes->routes plain public field (no property/get_routes); D-07 SimulatedExchange.register_symbol() closes the execution_handler.py:109 direct-mutation gap (byte-identical set-union, no float); D-08 update_config confirmed complete (no field reachable solely by direct mutation) — oracle-dark, byte-exact, mypy strict clean
- [Phase ?]: Phase 05 NAME-02: D-03 strategy PascalCase (SMAMACDStrategy/EmptyStrategy) + SMA_MACDConfig FAST/SLOW/WIN->fast_window/slow_window/signal_window (defaults 6/12/3, value-equal); D-04 all run-path importers updated, no alias; module filenames + SMA_MACDConfig class name kept; load-bearing golden re-run byte-exact (134/46189.87730727451), e2e 58/58, mypy strict clean
- [Phase ?]: Phase 05 NAME-04: rewrote 6 private-internals test consumers to public query APIs (routes / get_order_by_id / count_orders_by_status / emitted PortfolioErrorEvent.correlation_id / register_symbol+get_supported_symbols); correlation-id test adjudicated to observable-effect (not white-box, D-09); cash_manager white-box writes untouched; golden byte-exact, e2e 58/58, mypy strict clean
- [Phase ?]: [Phase 06 / 06-01] D-10 step 1: BracketBook introduced IN PLACE as single owner of the pending-bracket map (D-04/D-05); _PendingBracket moved verbatim to brackets/bracket_book.py (D-03, action str kept); all 8 _pending_brackets sites routed through arm/get/consume/refresh_quantity; dict-compat dunders + read-only _pending_brackets property keep test_sltp_policy.py untouched (Pitfall 2 option a); NO collaborator code moved; golden byte-exact (134/46189.87730727451), e2e 58/58, mypy strict clean.
- [Phase 06 / 06-02]: D-10 step 2: extracted brackets/ — _bracket_levels + _ONE moved to stateless brackets/levels.py (D-08, imported by BOTH the assembly path and the fill-anchored path so neither admission nor reconcile needs a brackets-collaborator ref); BracketManager (TAB, no queue) owns _assemble_bracket_and_emit + _create_fill_anchored_children, constructed once in OrderManager.__init__ with the injected coordinator-owned BracketBook (D-04 star), 3 call sites delegate; now-dead imports removed move-inherently (SLTPPolicy/assert_never/PercentFromDecision/PercentFromFill/_PendingBracket); golden byte-exact (134/46189.87730727451), e2e 58/58, mypy strict clean; order_handler.py + order_handler/__init__.py byte-unchanged.
- [Phase 06 / 06-03]: D-10 step 3: extracted admission/ — AdmissionManager (TAB, no queue) owns the 9-method signal→order pipeline (process_signal + create_orders_from_signal INTACT per D-07, plus _estimate_commission/_get_signal_exchange/_build_primary_order/_enforce_direction_admission/_enforce_position_admission/_resolve_signal_quantity/_reject_unsized_signal), constructed once in OrderManager.__init__ with the injected coordinator-owned BracketBook + BracketManager (D-04 star, D-08 — no reconcile/lifecycle ref); the two public entry points are 1-line delegations (public surface + external ctor unchanged); move-inherent dead imports removed (OrderType/Side/OrderTriggerSource/InsufficientFundsError/SizingPolicyViolation/TradingDirection); test_admission_rules white-box commission_estimator injection retargeted to order_manager.admission_manager (new home); golden byte-exact (134/46189.87730727451), e2e 58/58, unit 152, mypy strict (168 files); order_handler.py + order_handler/__init__.py byte-unchanged.
- [Phase ?]: [Phase 06 / 06-04]: D-10 step 4: extracted lifecycle/ — LifecycleManager (TAB, no queue) owns modify_order + cancel_order moved VERBATIM (D-07), constructed once in OrderManager.__init__ with the injected coordinator-owned BracketBook (D-04 star, D-08 — no reconcile/admission ref); the two verbs are 1-line delegations (public surface + external ctor unchanged); on_fill's WR-05 orphaned-child cancel routes through the delegation unchanged (reconcile->lifecycle seam deferred to plan 05); move-inherent dead imports removed (OrderCommand/OrderOperationType); golden byte-exact (134/46189.87730727451), e2e 58/58, unit 152, mypy strict (170 files); order_handler.py + barrel byte-unchanged. LAST extraction before the FRAGILE reconcile step.
- [Phase 06 / 06-05]: D-10 step 5 (FRAGILE, LAST): extracted reconcile/ — ReconcileManager (TAB, no queue) owns on_fill moved VERBATIM as ONE indivisible intact unit (D-07, criterion 2); should_release/try/finally/release-in-finally interplay byte-for-byte unchanged (T-05-17, WR-03/WR-04); the two cross-bucket seams rewired with NO sibling edge — WR-05 orphaned-child cancel via self.cancel_order coordinator callback (D-04 star, no LifecycleManager ref, no circular import), fill-anchored children via injected coordinator-owned BracketManager (D-08, BracketManager type under TYPE_CHECKING only); on_fill a 1-line delegation (public surface + external ctor unchanged); move-inherent dead imports removed (to_money/FillStatus); golden byte-exact (134/46189.87730727451), e2e 58/58, determinism double-run byte-identical (D-11), unit 152, full suite 851, mypy strict (172 files); order_handler.py + barrel byte-unchanged. All 5 D-01 buckets extracted — order_manager.py is the thin coordinator (__init__ + 5 entry delegations + 7 read delegators).

### Pending Todos

None yet.

### Blockers/Concerns

- **Behavior-preserving guardrail (milestone-wide):** every v1.2 phase must re-run the SMA_MACD golden master byte-exact (zero drift) and keep `pytest tests/e2e -m e2e` 58/58 green. No phase re-baselines the oracle.
- **FRAGILE zone:** `order_manager.py` fill-reconciliation / reservation-release (CONCERNS.md Fragile Areas) — golden-master re-run mandatory on any touch; terminal-status / `should_release` / `finally`-release interplay must not change. Phase 6 handles the split in isolation.
- **BEHAVIOR-SENSITIVE cleanup-review items to gate carefully:** W2-10 (Phase 2 — RE-ADJUDICATED by D-07: the below-minimum comparison was never broken; the golden run DOES route through `validate_order` via `_admit_order` and stays byte-exact — the change is float→Decimal of equal magnitude, so comparisons return the same bool; CLOSED in Phase 2), W2-01 (Phase 4 — int→string enum value change; grep tests/serialization for int-value assertions first), the Phase 5 naming renames (oracle re-run after each).
- **Indentation hazard:** tabs in handler modules; 4 spaces in `config/`/`core/`/`price_handler/feed/`/events package — match the file, never normalize (a mixed-indentation edit breaks a tab file).
- New requirements discovered during execution are added to REQUIREMENTS.md with traceability, not silently folded into a running phase.

### Quick Tasks Completed

(v1.0 quick tasks archived in `milestones/v1.0-MILESTONE-AUDIT.md`.)

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260610-sjp | Close FL-01 & FL-02 fix-list residuals + reconcile FIX-LIST.md status | 2026-06-10 | 4db1907 | [260610-sjp-close-fl01-fl02](./quick/260610-sjp-close-fl01-fl02/) |
| Phase 01 P01 | 2 | 3 tasks | 5 files |
| Phase 01 P02 | 2 | 3 tasks | 4 files |
| Phase 05 P01 | 2 | 3 tasks | 5 files |
| Phase 05 P02 | 8 | 3 tasks | 3 files |
| Phase 05 P03 | 6 | 3 tasks | 8 files |
| Phase 05 P04 | 10 | 3 tasks | 6 files |
| Phase 06 P01 | 3 | 2 tasks | 4 files |
| Phase 06 P02 | 6 | 2 tasks | 4 files |
| Phase 06 P03 | 9 | 2 tasks | 4 files |
| Phase 06 P04 | 6 | 2 tasks | 3 files |
| Phase 06 P05 | 9 | 2 tasks | 3 files |

## Bookkeeping

- **v1.1 phase dirs archived:** the v1.1 phase working directories were moved to
  `.planning/milestones/v1.1-phases/` (done before the v1.2 phase-number reset, so renumbering
  v1.2 to Phases 1-6 produced no directory collision).

- **v1.2 phase dirs archived (2026-06-12, at milestone close):** the six v1.2 phase working
  directories (`01`–`06`) were moved to `.planning/milestones/v1.2-phases/`. Only the `999.x`
  backlog seed dirs remain in `.planning/phases/`.

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

### v1.2 milestone-close acknowledgments (2026-06-12)

The pre-close artifact audit flagged 4 quick tasks that were verified **already complete** (each
carries `status: complete` frontmatter, with a real `${quick_id}-SUMMARY.md`). They are flagged
**only** by the same `gsd-sdk` SDK-port filename bug recorded at the v1.1 close — it reads a literal
`SUMMARY.md` and cannot see the mandated `${quick_id}-SUMMARY.md` files. Acknowledged and accepted at
v1.2 close; no open work.

| Category | Item | Status |
|----------|------|--------|
| quick_task | 260605-ih3 — fix WR-01 weekly/DST `check_timeframe` anchoring | complete (SDK-port false positive) |
| quick_task | 260608-a59 — demote by-design signal-rejection logs to warning | complete (SDK-port false positive) |
| quick_task | 260608-qe2 — pre-close enum cleanup (`TradingDirection`/`SystemStatus` canonical homes; config `ExchangeVenue`/`ConfigOrderType` renames) | complete (SDK-port false positive) |
| quick_task | 260610-sjp — close FL-01 & FL-02 + reconcile FIX-LIST | complete (SDK-port false positive) |

Non-blocking tech debt carried forward: **DEF-02-02** (`simulated.py` diagnostic dicts emit raw
`Decimal` instead of serialization-edge `float()` — cosmetic, no consumer breaks; fold into any
future touch of the exchange serialization helpers); SUMMARY `requirements-completed` frontmatter
omits 6 REQ-IDs (DEAD-01/02, PERF-01/03, NAME-01, MOD-01 — bookkeeping only, coverage intact);
Nyquist Wave-0 not run for v1.2 (behavioral net = golden oracle + 58 e2e + mypy strict). See
`milestones/v1.2-MILESTONE-AUDIT.md`.

## Session Continuity

Last session: 2026-06-11T21:29:45.753Z
Resume file: None

## Operator Next Steps

- **v1.2 Consolidation SHIPPED 2026-06-12** (all 6 phases, 23 plans, 18/18 requirements; tagged `v1.2`).
- No active milestone. Start the next one with `/clear` then `/gsd:new-milestone` — the next candidate is **Engine Surface Completion** (Backlog Phase 999.5: SIG/COMP/IND/LIFE), to be promoted ahead of N+2.
