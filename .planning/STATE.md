---
gsd_state_version: 1.0
milestone: v1.3
milestone_name: Engine Surface Completion
status: ready_to_plan
stopped_at: Phase 06 complete (4/4) — ready to discuss Phase 999.2
last_updated: 2026-06-13T17:16:39.161Z
last_activity: 2026-06-13 -- Phase 06 execution started
progress:
  total_phases: 9
  completed_phases: 5
  total_plans: 20
  completed_plans: 20
  percent: 56
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-06-12 — milestone v1.3 Engine Surface Completion started)

**Core value:** A single backtest run of `SMA_MACD` on the golden BTCUSD CSV produces correct, deterministic, cross-validated numbers — now extended with complete signal/order contracts, a real composition/config interface, and a declared-indicator + authoring surface, BEFORE N+2 builds margin/shorts on these same surfaces.
**Current focus:** Phase 999.2 — nplus2 persistence and performance

## Current Position

Phase: 999.2
Plan: Not started
Status: Ready to plan
Last activity: 2026-06-13

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

- Total plans completed: 43
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
- **[LOCKED → Phase 3 / IND-01] Framework-derived warmup (owner directive, closes 02-REVIEW WR-03):** Phase 3's declared-indicator framework MUST auto-derive `warmup`/`max_window` from the declared indicators' lookbacks (`max` over each) and REPLACE the hand-set `warmup`/`max_window` class attrs on `SMAMACDStrategy` — removing the WR-03 footgun (an author can currently set `warmup=0`, the handler short-circuit then under-gates, and `generate_signal` hits `IndexError` on a sub-warmup frame, aborting the fail-fast run). HARD byte-exact constraint: the derived value for `SMAMACDStrategy` MUST equal exactly **100** (= `max(long_window=100, slow_window+signal_window≈15)`), or the oracle drifts off `46189.87730727451`. This is BLOCKED until indicators are declared (can't derive from inline `ta.SMAIndicator`/`ta.MACD` calls in `generate_signal`) — which is precisely why IND-01 owns it. The interim defensive guard was deliberately NOT added in Phase 2 (keeps D-15 handler-side gating clean); WR-03 is deferred from the Phase-2 `--fix` and resolved structurally in Phase 3.

- [v1.3 Phase 03 / 03-01]: Standalone `indicators/` package + flat `primitives.py` landed (D-03/04/05/07/08). `catalog.py` ships SMA/MACDHist/EMA/RSI singleton adapters typed against an `IndicatorAdapter` Protocol, each with `compute(...)` + `min_period(params)`; `[BYTE-EXACT]` SMA sliced input (`bars[start_dt:][col]`, `start_dt = now - timeframe*window`, `fillna=True` — Pitfall 1) and MACDHist full-window (`fillna=False`, no slice). D-08 min_period is first-valid only (SMA/EMA/RSI→w; MACDHist→slow+signal==15 ⇒ reference `max(50,100,15)==100`). `handle.py` holds `IndicatorHandle` (moved OUT of `base.py`, NO base import — one-directional `base → indicators`, no cycle): `[-1]`/`[-2]`→float via `.iloc`, `__len__==0` pre-repopulate, `repopulate`→`adapter.compute`, `min_period()` delegates. `primitives.py` (flat sibling): crossover/crossunder/is_above/is_below with D-02 inclusive-on-current-bar semantics + scalar broadcast via `_at`. Zero run-path touch — byte-exact (oracle 134/46189.87730727451, e2e 58/58, mypy --strict 176 files, 35 new unit tests). Plan 02 imports these symbols and base.py auto-warmup derives from `handle.min_period()`.

(v1.2 per-plan decisions are archived in `milestones/v1.2-ROADMAP.md` and the phase records under `milestones/v1.2-phases/`. The v1.2 Phase-6 decomposition decisions below are retained because Phase 5 of v1.3 builds directly on the `reconcile/` collaborator they created.)

- [v1.2 Phase 06 / 06-05]: D-10 step 5 (FRAGILE, LAST): extracted reconcile/ — ReconcileManager (TAB, no queue) owns on_fill moved VERBATIM as ONE indivisible intact unit; should_release/try/finally/release-in-finally interplay byte-for-byte unchanged; the two cross-bucket seams rewired with NO sibling edge — WR-05 orphaned-child cancel via self.cancel_order coordinator callback, fill-anchored children via injected coordinator-owned BracketManager; golden byte-exact (134/46189.87730727451), determinism double-run byte-identical. This is the clean, bounded enabling surface v1.3 RECON-01 was designed to refactor.
- [v1.2 Phase 06 / 06-03]: AdmissionManager owns the 9-method signal→order pipeline (process_signal + create_orders_from_signal INTACT, plus _estimate_commission/_get_signal_exchange/_build_primary_order/_enforce_direction_admission/_enforce_position_admission/_resolve_signal_quantity/_reject_unsized_signal) — the surface v1.3 SIG-01/02/03 + W1-11 snapshot threading touch.
- [v1.2 Phase 06 / 06-01]: BracketBook is single owner of the pending-bracket map; _PendingBracket moved to brackets/bracket_book.py with action kept `str` — v1.3 SIG-03 retypes `_PendingBracket.action` to `Side` here.
- [v1.2 Phase 02 / 2026-06-11] D-07 gap-discovery delta: the W2-10/DEC-02 "latent `Decimal < float` TypeError" on the below-minimum validation path was a MISDIAGNOSIS — Decimal-vs-float COMPARISON works in Py3; only arithmetic raises and there is none on `_min/_max_order_size`. (Retained as standing context for any v1.3 validator-path touch in SIG-03 / W4-04.)
- [Phase ?]: [v1.3 Phase 02 / 02-02]: Strategy authoring surface landed — base Strategy __init__ is now (**kwargs) with a stdlib get_type_hints introspection engine, a 3-entry _COERCE enum table (timeframe/order_type/direction), and init()/validate()/reconfigure() hooks (D-02/D-06/D-09/D-10/D-12). ALL engine knobs MUST be annotated (get_type_hints returns only annotated names; deviation from the RESEARCH skeleton). reconfigure falls back to prior INSTANCE value for omitted required fields (OQ1). Pydantic config layer (config/strategy.py, BaseStrategyConfig) fully deleted (D-01); SignalRecord.config retyped to dict (D-04). Suite intentionally RED at 10 construction sites pending 02-03 (all-or-broken D-05); mypy --strict itrader/ clean.
- [Phase ?]: [v1.3 Phase 02 / 02-03]: All strategy construction sites migrated from (name, config) to the kwargs class-attr surface (D-05, no shim); strategy unit tests rewritten for the class-attr engine (unknown/missing/override/coerce/no-coerce/validate/idempotent/reconfigure/dict-snapshot). Byte-exact gate GREEN: oracle 134/46189.87730727451, e2e 58/58, mypy --strict clean (172 files), full suite 853 green, determinism double-run identical. missing-required tested via EmptyStrategy (SMA pins sizing_policy); non-coercion via max_positions (short_window collides with validate()). Zero re-baseline.
- [v1.3 Phase 03 / 03-02]: Strategy-base framework landed + full run/test path migrated (D-06/D-08, one lockstep). `base.py` owns `self.indicator(adapter, input, *params) -> IndicatorHandle` (imported from `indicators/`, one-directional, no cycle), the `evaluate(ticker, window)` seam (stashes `self.bars`/`self.now = window.index[-1]`, repopulates handles, dispatches `generate_signal(ticker)`), and `_run_init` (resets `_handles` before `init()`, idempotent — re-run by `reconfigure`). `generate_signal` dropped `bars` (D-06); the `StrategiesHandler.calculate_signals` call-site swapped to `strategy.evaluate(ticker, data)`. `SMAMACDStrategy` is fully primitive-driven (`is_above`/`crossover`/`crossunder` over handles), hand-set `warmup`/`max_window` DELETED -> auto-derived `warmup == max_window == 100`. **DEVIATION from the must_have prose:** `warmup` is UNCONDITIONALLY derived from handle `min_period` (the WR-03 footgun fix — the real D-08 goal), but `max_window = max(derived, type(self).max_window)` — the literal "zero-handle overwrite to 0" claim BREAKS the byte-exact e2e/integration golden (`feed.window(..., max_window=0, ...)` returns `frame.iloc[pos:pos]` = empty against a REAL feed, so count/date-keyed fixtures never fire and `evaluate`'s `window.index[-1]` raises). The fetch width therefore never shrinks below a hand-set value; `evaluate()` also guards an empty window (`self.now = None`, skip repopulate). Byte-exact gate HELD: oracle 134/46189.87730727451, e2e 58/58, full suite 890 green, mypy --strict 176 files, determinism double-run identical.
- [Phase 03]: [v1.3 Phase 03 / 03-03]: Byte-exact phase gate LOCKED with ZERO re-baseline — migrated declared-indicator SMAMACDStrategy is byte-exact against the frozen BTCUSD oracle (134 trades / final_equity 46189.87730727451, EXACT, no tolerance via pdt.assert_frame_equal + exact summary-dict). Pitfall 1 (per-indicator SMA slice) + Pitfall 2 (eager-vs-lazy MACD reorder) proven correct — the oracle is the ONLY proof (no SMA_MACD unit test guards the MACD value). Determinism double-run byte-identical; e2e 58/58; full suite 890 green under filterwarnings=[error]; mypy --strict clean (176 files). Both plan tasks were VERIFICATION-ONLY: Task 1 confirmed to_dict()/SignalRecord.config still carries auto-derived max_window/warmup==100 (get_type_hints introspection; signal_record.py NOT edited, no data migration); Task 2 conditional fix-forward scope (indicators/catalog.py SMA slice, handle.py IndicatorHandle, base.py imports) NEVER triggered — steady-state touched no source. Phase 3 declared-indicator framework (Plans 01-03) complete and numerically trustworthy; ROADMAP Success Criterion 4 satisfied.
- [v1.3 Phase 04 / 04-01]: Three standalone COMP-01 contracts landed (byte-exact-inert, ZERO run-path import — Wave 2 consumes them). **D-15 CommissionEstimator** (`core/commission_estimator.py`, 4 spaces): `@runtime_checkable` Protocol with the primitive `__call__(self, quantity: Decimal, price: Decimal) -> Decimal`, ZERO `itrader` imports (mirrors `portfolio_read_model.py`); structural conformance tested + written append-ready for the Wave-2 (04-02 Task 2) D-15 LATE-BINDING test (post-fee-swap non-zero estimate — adapter doesn't exist yet). **D-05 OrderConfig** (`config/order.py`, 4 spaces): thin Pydantic model, `ConfigDict(extra="forbid")`, `market_execution: MarketExecution = IMMEDIATE`, `default()`. **A1 CONFIRMED TRUE** — pydantic v2 coerces the string `"immediate"` to the `MarketExecution.IMMEDIATE` MEMBER with NO custom validator (Trap 5 coercion-equivalence byte-identical to today's ctor `MarketExecution(market_execution)`); `use_enum_values` deliberately NOT used (would store the str). `MarketExecution` stays in `core/enums/` (config-enum exception). **D-01/D-02 SystemSpec** (`trading_system/system_spec.py`, TABS): `ScenarioSpec`/`PortfolioSpec`/`Action` promoted field-for-field, run-mode-agnostic name (NOT `BacktestSpec`), fields match the e2e harness by name; `actions`+`Action` kept for a single-spec Wave-4 collapse; NOT yet wired into any run path. `mypy --strict` clean 176->179 files; 10 new unit tests green; oracle (134/46189.87730727451) + e2e 58/58 untouched (no run-path touch). COMP-01 remains OPEN (this plan lands only the foundational primitives; the composition-root collapse is Wave 2+).
- [Phase ?]: [v1.3 Phase 04 / 04-02]: Composition-root collapse landed byte-exact. compose_engine (trading_system/compose.py) is the shared mode-agnostic wiring seam — order_storage + signal_store backends injected by the FACTORY (grep "'backtest'"==0, D-14a). FeeModelCommissionEstimator holds the exchange ref, reads fee_model in __call__ (D-15 late binding); the oracle-dark post-fee-swap non-zero test pins it (swap via the LIVE update_config enum API — string coercion is Wave 3). BacktestRunner owns the fail-fast loop, post-bar record_metrics DIRECT call preserved (Trap 4). TradingSystem renamed BacktestTradingSystem (thin holder) + build_backtest_system(spec) factory (D-04); a TradingSystem alias + legacy __init__ + engine-delegating properties keep oracle/integration/e2e/scripts byte-exact by rename only until Wave 4. D-13/Trap 1: hardcoded register_symbol('BTCUSD') removed; COMPLETE set (default preset ∪ {BTCUSD} ∪ spec tickers) seeded into ExchangeConfig.limits at construction (replacement-safe); TEMPORARY no-config fallback unions {BTCUSD} (asserted, Wave 4 removes it). D-16/Trap 3: _resolve_rng_seed reads config.performance.rng_seed off the singleton (seed 42). OrderConfig threaded + commission_estimator retyped (D-05). print_metrics_summary lifted into reporting/summary.py (W4-07). GATE: oracle 134/46189.87730727451 exact, e2e 58/58, mypy --strict 181 files, full suite 854 green, determinism double-run identical.
- [Phase ?]: 04-03: canonical update_config(dict)->None on all 5 config-model handlers; shared config/merge.py deep_merge; pydantic ValidationError wrapped into ConfigurationError; oracle-dark byte-exact held
- [Phase ?]: 04-04: non-config-model update_config landed — StrategiesHandler name-keyed reconfigure delegation (D-09) + BacktestBarFeed raise-only interface-conformance (D-10); both match the core.ConfigurationError single-catch contract; oracle-dark byte-exact (134/46189.87730727451, e2e 58/58, mypy 182)
- [Phase 05 / 05-04]: OWNER-SIGNED LIMIT GOLDEN FROZEN (D-07) — ONE externally cross-validated (backtesting.py 0.6.5 + backtrader 1.9.78.123, gating) LIMIT-entry golden on the real BTCUSD dataset, proving the SIG-01/SIG-02 `buy_limit` authoring surface end-to-end (resting limit fills a LATER bar 2018-09-05 @ 7155.9698 → SL same bar @ 6798.17131; marketable limit fills at OPEN 2018-09-14 @ 6487.39 → SL same bar @ 6471.16155; trade_count 2; final_equity 9503.442073) and exercising RECON-01 entry-fill→bracket reconciliation. Owner (tiziaco, 2026-06-13) signed off with full attribution, explicitly accepting the **A1 LEGITIMATE-DIFFERENCE** (iTrader fills the same-bar protective SL intrabar; BOTH gating engines defer the contingent SL to the next bar and AGREE with each other — 0 BUG, iTrader numbers kept). Golden frozen at `tests/e2e/matching/entries/limit_entry_crossval/golden/{trades.csv,summary.json}` via the e2e `--freeze` harness; the xfail pending-golden marker removed so the leaf is a live green diff-on-drift regression lock; owner sign-off block appended to `tests/golden/CROSS-VALIDATION-LIMIT.md`. The crafted strategy + two LIMIT runners + orchestrator are SCRIPT-ONLY (D-10, never imported under tests/). GATE: the EXISTING SMA_MACD oracle stays byte-exact (134 / 46189.87730727451) — additive NEW golden, no re-baseline of the old one; e2e leaf green. Tasks 1/2 (4729448, c2fdc6f) + Task 3 (75fb676).
- [Phase 04 / 04-05]: BYTE-EXACT PROOF WAVE — phase 4 PROVEN byte-exact (COMP-01 + COMP-02 complete). e2e _build_and_run COLLAPSED onto build_backtest_system(spec): the D-14 post-construction fee/slippage re-init seam + the additive register_symbol loop REMOVED (subsumed by construction-time ExchangeConfig threading + complete symbol seeding, D-01/D-13/D-14). scenario_spec.py UNIFIED onto the promoted SystemSpec (ScenarioSpec = SystemSpec alias + PortfolioSpec/Action re-export — no leaf edited). All scripts/integration TradingSystem sites migrated to BacktestTradingSystem (D-03); the Wave-2 TradingSystem alias REMOVED; the legacy direct-construction __init__ now seeds its own complete ExchangeConfig (routes the backtest path off the ExecutionHandler no-config fallback, which STAYS for the out-of-scope live + unit direct-construction consumers). [Rule 1] Fixed a latent Wave-2 factory bug: add_portfolio used exchange=spec.ticker (unregistered venue → no fills) → corrected to 'csv'; only activated once the e2e path ran through the factory. D-12 scope fence HELD (no ReconfigureEvent / TradingInterface reconfigure bridge; LiveTradingSystem untouched). GATE: oracle 134/46189.87730727451 EXACT, determinism double-run byte-identical, e2e 58/58, full suite 946 green under filterwarnings=[error], mypy --strict clean (182 files). Zero re-baseline.

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
| Phase 02 P03 | ~20 min | 3 tasks | 10 files |
| Phase 03 P01 | ~15 min | 2 tasks | 6 files |
| Phase 03 P02 | ~40 min | 3 tasks | 9 files |
| Phase 03 P03 | ~10 min | 2 tasks | 0 files |
| Phase 04 P01 | 12 | 3 tasks | 5 files |
| Phase 04 P02 | 35 | 3 tasks | 11 files |
| Phase 04 P03 | 40min | 3 tasks | 17 files |
| Phase 04 P04 | 15 | 2 tasks | 4 files |
| Phase 04 P05 | 30 | 3 tasks | 10 files |
| Phase 05 P04 | ~9 min | 3 tasks | 9 files |

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

Last session: 2026-06-13T16:09:44.882Z
Stopped at: Phase 6 context gathered
Resume file: .planning/phases/06-order-lifecycle-time-in-force/06-CONTEXT.md

## Operator Next Steps

- **v1.3 Engine Surface Completion roadmap created** (Phases 1-6, all 10 requirements mapped, 0 orphans).
- Plan the first phase with `/gsd:plan-phase 1` (Phase 1 — Engine Hygiene, byte-exact, SAFE, no run-path touch — a clean low-risk opener).
- Owner sign-off is required before Phases 5-6 freeze a new golden master (result-changing, owner-gated re-baseline + external cross-validation).
