---
gsd_state_version: 1.0
milestone: v1.3
milestone_name: Engine Surface Completion
status: executing
last_updated: "2026-06-12T12:35:37.739Z"
last_activity: 2026-06-12 -- 02-02 complete (strategy authoring surface: kwargs engine + hooks; config layer deleted; suite intentionally RED pending 02-03)
progress:
  total_phases: 9
  completed_phases: 1
  total_plans: 4
  completed_plans: 3
  percent: 75
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-12 — milestone v1.3 Engine Surface Completion started)

**Core value:** A single backtest run of `SMA_MACD` on the golden BTCUSD CSV produces correct, deterministic, cross-validated numbers — now extended with complete signal/order contracts, a real composition/config interface, and a declared-indicator + authoring surface, BEFORE N+2 builds margin/shorts on these same surfaces.
**Current focus:** Phase 02 — strategy-authoring-surface

## Current Position

Phase: 02 (strategy-authoring-surface) — EXECUTING
Plan: 3 of 3
Status: Ready to execute (02-03 migrates test/script construction sites in lockstep + runs the byte-exact gate)
Last activity: 2026-06-12 -- 02-02 complete (kwargs introspection engine + init/validate/reconfigure hooks; SMAMACDStrategy/EmptyStrategy migrated to class attrs; config/strategy.py deleted; SignalRecord.config -> dict; mypy --strict itrader/ clean; suite intentionally RED pending 02-03)

## Milestone Gate (v1.3 — applies per phase, per re-baseline tag)

**Two re-baseline disciplines run side by side. Each phase declares which it is:**

**Byte-exact phases (1-4: Engine Hygiene, Strategy Authoring Surface, Declared-Indicator
Framework, Composition & Config Interface)** — re-baseline NOTHING. Each must hold:

- `pytest tests/integration` byte-exact oracle: **134 trades / `final_equity 46189.87730727451`**
- `pytest tests/e2e -m e2e` **58/58 green** (no leaf re-baselined); full suite green
- **`mypy --strict` clean** across all source files
- No new float-for-money; single UUIDv7 ID scheme (no second `uuid4()` on the run path)
- Determinism double-run byte-identical

**Owner-gated phases (5: Signal Contract & Reconcile (FRAGILE); 6: Order Lifecycle & TIF)** —
result-changing. The new golden master is frozen **ONLY** after explicit owner sign-off with full
attribution, validated by external cross-validation (`backtesting.py`/`backtrader`). `mypy --strict`
clean and determinism double-run byte-identical still hold.

- **FRAGILE-zone rule (Phase 5):** SIG-03 (`action`→`Side` + snapshot threading) and RECON-01
  (`on_fill`/`should_release` streamline) both touch the FRAGILE fill-reconciliation /
  reservation-release path (`order_manager.py` `reconcile/`). They are CO-PHASED so `reconcile/` is
  touched **once** under a single re-baseline + cross-validation, not twice. The idempotent
  release-on-every-terminal-reconciliation invariant must hold (EXECUTED→FILLED, CANCELLED→CANCELLED,
  REFUSED→REJECTED).

- **Re-baseline separation:** owner-gated (result-changing) and byte-exact requirements are kept in
  SEPARATE phases so a byte-exact phase's golden gate is a clean pass/fail and each result-changing
  phase owns its re-baseline.

## Phase Map (v1.3 — Phases 1-6)

Execution order: 1 → 2 → 3 → 4 → 5 → 6. Derived from the 10 v1.3 requirements + the co-phasing /
re-baseline hard constraints. (Numbering reset for v1.3, matching v1.1/v1.2; v1.2 phase dirs archived
to `.planning/milestones/v1.2-phases/`, so there is no directory collision.)

| Phase | Name | Requirements | Re-baseline | Depends on |
|-------|------|--------------|-------------|------------|
| 1 | Engine Hygiene | HYG-01 | Byte-exact (no run-path touch) | — |
| 2 | Strategy Authoring Surface | STRAT-01 | Byte-exact | 1 |
| 3 | Declared-Indicator Framework | IND-01 | Byte-exact | 2 |
| 4 | Composition & Config Interface | COMP-01, COMP-02 | Byte-exact | 3 (consumes P2 `init()`) |
| 5 | Signal Contract & Reconcile (FRAGILE) | SIG-01, SIG-02, SIG-03, RECON-01 | Owner-gated (single re-baseline + cross-validation) | 4 |
| 6 | Order Lifecycle & Time-in-Force | LIFE-01 | Owner-gated | 5 |

**Sequencing rationale:** STRAT-01 (P2) ships before COMP-02 (P4) because its re-runnable idempotent
`init()` is the seam `StrategiesHandler.update_config` consumes; IND-01 (P3) sits between (auto-warmup
re-derived on `init()` re-run). The FRAGILE signal/reconcile core (P5) lands after the composition/config
infra (P4); LIFE-01 (P6) is self-contained and last. N+2 (margin/shorts) extends the completed SIG/COMP
surfaces, which is why v1.3 lands first.

## Performance Metrics

**Velocity (v1.2):**

- Total plans completed: 24
- Average duration: — min
- Total execution time: 0.0 hours

*Updated after each plan completion. v1.0/v1.1 velocity is archived in the respective MILESTONE-AUDIT.md.*

## Accumulated Context

### Decisions

Active decisions live in PROJECT.md Key Decisions. Load-bearing program constraints still in force for v1.3:

- Money = Decimal end-to-end; float money is a correctness defect (HYG-01 closes the latent `validate_transaction_data` float boundary).
- IDs = single UUIDv7 scheme via `uuid-utils`.
- **Two re-baseline disciplines (v1.3):** byte-exact phases (1-4) hold the v1.1 E2E golden suite + BTCUSD oracle (134 trades / `final_equity 46189.87730727451`) byte-for-byte; owner-gated phases (5-6) re-baseline only after explicit owner sign-off + external cross-validation. Result-changing and byte-exact requirements are kept in SEPARATE phases.
- **Co-phasing (HARD):** SIG-01/02/03 + RECON-01 land in ONE FRAGILE reconcile phase (Phase 5) — SIG-03 and RECON-01 both touch the FRAGILE fill-reconciliation / reservation-release path, so `reconcile/` is touched once under one re-baseline, not twice.
- **Sequencing seam:** STRAT-01 (P2) before COMP-02 (P4) — the re-runnable idempotent `init()` is what `StrategiesHandler.update_config` consumes (re-validate → re-run `init()` → re-derive warmup).
- **Phase numbering reset to 1 for v1.3** (matching v1.1/v1.2). The v1.2 phase working dirs were archived to `.planning/milestones/v1.2-phases/`, so there is no directory collision. The `999.x` backlog entries are FUTURE milestones (N+2/N+3/N+4), left intact in ROADMAP.md `## Backlog`.
- **Deferred OUT of v1.3:** FL-13 (live-system test coverage) → 999.3; FL-06 (SQL injection) → 999.2. Both pushed down to their owning milestone (live/persistence), not the backtest engine surface.
- [v1.3 Phase 02 / 02-01]: `core/exceptions/strategy.py` added — `UnknownParamError`/`MissingParamError` subclass the house `ValidationError` (never bare `ValueError`, RESEARCH §Don't Hand-Roll); engine call-shapes `UnknownParamError(sorted(kwargs))` (stores `self.names`, `field="strategy_params"`) and `MissingParamError(name)` (stores `self.name`, `field=name`) are satisfiable. Re-exported via the barrel. Zero run-path touch — byte-exact (oracle 134/46189.87730727451, e2e 58/58). Plan-02 engine imports these symbols.

(v1.2 per-plan decisions are archived in `milestones/v1.2-ROADMAP.md` and the phase records under `milestones/v1.2-phases/`. The v1.2 Phase-6 decomposition decisions below are retained because Phase 5 of v1.3 builds directly on the `reconcile/` collaborator they created.)

- [v1.2 Phase 06 / 06-05]: D-10 step 5 (FRAGILE, LAST): extracted reconcile/ — ReconcileManager (TAB, no queue) owns on_fill moved VERBATIM as ONE indivisible intact unit; should_release/try/finally/release-in-finally interplay byte-for-byte unchanged; the two cross-bucket seams rewired with NO sibling edge — WR-05 orphaned-child cancel via self.cancel_order coordinator callback, fill-anchored children via injected coordinator-owned BracketManager; golden byte-exact (134/46189.87730727451), determinism double-run byte-identical. This is the clean, bounded enabling surface v1.3 RECON-01 was designed to refactor.
- [v1.2 Phase 06 / 06-03]: AdmissionManager owns the 9-method signal→order pipeline (process_signal + create_orders_from_signal INTACT, plus _estimate_commission/_get_signal_exchange/_build_primary_order/_enforce_direction_admission/_enforce_position_admission/_resolve_signal_quantity/_reject_unsized_signal) — the surface v1.3 SIG-01/02/03 + W1-11 snapshot threading touch.
- [v1.2 Phase 06 / 06-01]: BracketBook is single owner of the pending-bracket map; _PendingBracket moved to brackets/bracket_book.py with action kept `str` — v1.3 SIG-03 retypes `_PendingBracket.action` to `Side` here.
- [v1.2 Phase 02 / 2026-06-11] D-07 gap-discovery delta: the W2-10/DEC-02 "latent `Decimal < float` TypeError" on the below-minimum validation path was a MISDIAGNOSIS — Decimal-vs-float COMPARISON works in Py3; only arithmetic raises and there is none on `_min/_max_order_size`. (Retained as standing context for any v1.3 validator-path touch in SIG-03 / W4-04.)
- [Phase ?]: [v1.3 Phase 02 / 02-02]: Strategy authoring surface landed — base Strategy __init__ is now (**kwargs) with a stdlib get_type_hints introspection engine, a 3-entry _COERCE enum table (timeframe/order_type/direction), and init()/validate()/reconfigure() hooks (D-02/D-06/D-09/D-10/D-12). ALL engine knobs MUST be annotated (get_type_hints returns only annotated names; deviation from the RESEARCH skeleton). reconfigure falls back to prior INSTANCE value for omitted required fields (OQ1). Pydantic config layer (config/strategy.py, BaseStrategyConfig) fully deleted (D-01); SignalRecord.config retyped to dict (D-04). Suite intentionally RED at 10 construction sites pending 02-03 (all-or-broken D-05); mypy --strict itrader/ clean.

### Pending Todos

None yet.

### Blockers/Concerns

- **Two-discipline guardrail (milestone-wide):** byte-exact phases (1-4) must re-run the SMA_MACD golden master byte-exact (zero drift) and keep `pytest tests/e2e -m e2e` 58/58 green; owner-gated phases (5-6) re-baseline only after explicit owner sign-off + external cross-validation, with full attribution.
- **FRAGILE zone (Phase 5):** `order_manager.py` fill-reconciliation / reservation-release (`reconcile/`, `admission/`) — touched once under one re-baseline for SIG-03 + RECON-01 co-phased; the idempotent terminal-release invariant must hold. The v1.2 Phase-6 intact-move into `reconcile/` is the designed enabling surface.
- **Owner-gate dependency:** Phases 5 and 6 cannot freeze a new golden without explicit owner sign-off — plan them so the result-change is fully attributed before re-baseline.
- **Indentation hazard:** tabs in handler modules (`order_handler/`, `strategy_handler/`); 4 spaces in `config/`/`core/`/`price_handler/feed/`/events package — match the file, never normalize (a mixed-indentation edit breaks a tab file). Phases 2-5 touch tab-indented strategy/order modules.
- New requirements discovered during execution are added to REQUIREMENTS.md with traceability, not silently folded into a running phase.

### Quick Tasks Completed

(v1.0 quick tasks archived in `milestones/v1.0-MILESTONE-AUDIT.md`; v1.1/v1.2 per-phase plan
records archived under `milestones/v1.1-phases/` and `milestones/v1.2-phases/`.)

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260610-sjp | Close FL-01 & FL-02 fix-list residuals + reconcile FIX-LIST.md status | 2026-06-10 | 4db1907 | [260610-sjp-close-fl01-fl02](./quick/260610-sjp-close-fl01-fl02/) |
| Phase 02 P02 | ~25 min | 3 tasks | 7 files |

## Bookkeeping

- **v1.1 phase dirs archived:** the v1.1 phase working directories were moved to
  `.planning/milestones/v1.1-phases/` (done before the v1.2 phase-number reset, so renumbering
  v1.2 to Phases 1-6 produced no directory collision).

- **v1.2 phase dirs archived (2026-06-12, at milestone close):** the six v1.2 phase working
  directories (`01`–`06`) were moved to `.planning/milestones/v1.2-phases/`. Only the `999.x`
  backlog seed dirs remain alongside the new v1.3 phase dirs in `.planning/phases/`.

- **v1.3 phase numbering reset to 1:** new phase working dirs will be `01-*`…`06-*`. The `999.x`
  backlog dirs are FUTURE milestones (N+2/N+3/N+4) and are NOT renumbered.

## Deferred Items

Program-level items out of scope for v1.3, with their target milestone:

| Category | Item | Status | Target |
|----------|------|--------|--------|
| Live coverage | `LiveTradingSystem`/`TradingInterface` test coverage (FL-13) | Deferred | N+4 Live Readiness (Backlog 999.3) |
| Persistence/security | SQL injection + hardcoded creds in `SqlHandler` (FL-06) | Deferred | N+3 Persistence (Backlog 999.2) |
| D-margin | Margin/liquidation model, shorts, leverage, levered Kelly, trailing stop, real pair trading | Deferred | N+2 (Backlog 999.4) |
| D-compliance | Compliance layer (long_only/short_only enforcement) | Deferred | N+2 (with shorts) |
| D-sql | SQL persistence backends (order/price/reporting/config) | Deferred | N+3 (Backlog 999.2) |
| D-screener | Production screener / ranking / rebalance loop (minimal `membership` shipped v1.1) | Deferred | N+4 (Backlog 999.3) |
| D-live | Live mode (streaming, TradingInterface modify/cancel, live threading, secrets) | Deferred | N+4 |
| D-multiasset | Multi-currency accounting, trading calendars, corporate actions (forex/equities/ETF) | Deferred | indefinite (crypto-first) |
| D-oanda | OANDA + non-crypto adapters | Deferred | with D-multiasset |
| Indicators | IND-02 incremental/stateful indicator backends (behind the IND-01 stable interface) | Deferred | future (post-v1.3) |
| Tooling | `pytz` → stdlib `zoneinfo` migration; broad `except Exception` narrowing | Captured (no commitment) | opportunistic / backlog |
| OUT | `my_strategies/*` (relocated to separate repo by user) | Out-of-band | — |

v1.0/v1.1/v1.2 milestone-close acknowledgments are recorded in the respective MILESTONE-AUDIT.md
files under `milestones/`. The four v1.2 quick tasks flagged only by the `gsd-sdk` SDK-port filename
bug were verified canonically complete (`status: complete`) and accepted at v1.2 close.

## Session Continuity

Last session: 2026-06-12T12:35:16.570Z
Resume file: None

## Operator Next Steps

- **v1.3 Engine Surface Completion roadmap created** (Phases 1-6, all 10 requirements mapped, 0 orphans).
- Plan the first phase with `/gsd:plan-phase 1` (Phase 1 — Engine Hygiene, byte-exact, SAFE, no run-path touch — a clean low-risk opener).
- Owner sign-off is required before Phases 5-6 freeze a new golden master (result-changing, owner-gated re-baseline + external cross-validation).
