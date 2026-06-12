# Requirements: iTrader — v1.3 Engine Surface Completion

**Defined:** 2026-06-12
**Core Value:** A single backtest run of `SMA_MACD` on `data/BTCUSD_1d_ohlcv_2018_2026.csv`
produces correct, deterministic, cross-validated numbers — now extended with complete
signal/order contracts, a real composition/config interface, and a declared-indicator +
authoring surface, BEFORE N+2 builds margin/shorts on these same surfaces.

**Milestone discipline (per-requirement re-baseline tag):**
- **Byte-exact** — must hold the v1.1 E2E golden suite + BTCUSD integration oracle
  (134 trades / `final_equity 46189.87730727451`) byte-for-byte.
- **Owner-gated** — result-changing; follows the established owner-gated re-baseline discipline
  (new golden frozen only after explicit owner sign-off, with full attribution).

Promotes Backlog Phase 999.5. Full fold-in/defer triage: `notes/v1.3-concerns-triage.md`.
Converged design for IND-01/STRAT-01: `notes/strategy-authoring-surface-999.5c.md`.

## v1 Requirements

Requirements for this milestone. Each maps to exactly one roadmap phase.

### Signal Contract (SIG)

- [ ] **SIG-01**: A strategy can specify a per-intent **limit or stop ENTRY price** on the signal
  contract (no longer hardwired to the decision-bar close), threaded
  `SignalIntent → SignalEvent → Order.new_limit_order`/`new_stop_order`. *Owner-gated.*
  [999.5-(a)]
- [ ] **SIG-02**: A strategy can specify the **entry `order_type` per intent** (MARKET / LIMIT /
  STOP) rather than fixed per strategy instance; includes the Phase 8 per-bar `order_type`
  override left unwired in the e2e emitter. *Owner-gated.* [999.5-(a)]
- [ ] **SIG-03**: `Order.action` and `_PendingBracket.action` are typed **`Side`** (not `str`),
  and the position snapshot is threaded once through admission→sizing (removing the double
  `get_position()`). FRAGILE — coupled to SIG-01/02; W4-04 validator-overlap doc updated if the
  validator path is touched. *Owner-gated (rides the SIG re-baseline).* [W2-02, W1-11, W4-04]

### Order Reconciliation (RECON)

- [ ] **RECON-01**: Streamline the `on_fill` reconciliation + `should_release` release-in-`finally`
  flow for clarity, **preserving the financial-integrity invariant** (idempotent release on every
  terminal reconciliation — EXECUTED→FILLED, CANCELLED→CANCELLED, REFUSED→REJECTED). Behavior-risk
  → owner-gated re-baseline + external cross-validation (`backtesting.py`/`backtrader`). **Planned
  in the SAME FRAGILE phase as SIG-03** so `reconcile/` is touched once under a shared re-baseline,
  not twice. The v1.2 Phase-6 intact-move into `reconcile/` was explicitly designed as the clean,
  bounded enabling surface for this refactor. *Owner-gated.* [v1.2 06-CONTEXT Deferred Ideas]

### Composition / Config Interface (COMP)

- [ ] **COMP-01**: The system is composed through an **engine-level composition API** (promote the
  `tests/e2e/scenario_spec.py` `ScenarioSpec` shape): declarative multi-strategy / multi-portfolio
  wiring, faithful **construction-time `ExchangeConfig` threading** (`TradingSystem` →
  `ExecutionHandler` → `SimulatedExchange`, replacing the Phase 7 D-14 post-construction conftest
  re-init seam), a new **`OrderConfig`** model threaded into `OrderManager` (no more loose
  stringly-typed ctor params), and a formalized `csv_paths` passthrough. Folds composition-root
  cleanups W4-02/03/05/06/07. *Byte-exact.* [999.5-(b), SYN-05]
- [ ] **COMP-02**: **Every** handler/manager exposes a uniform runtime **`update_config`** with one
  consistent signature (merge → `model_validate` → atomic-swap; unified return/error contract):
  `OrderHandler`/`OrderManager`, `StrategiesHandler`, `ExecutionHandler`, `PortfolioHandler`,
  `SimulatedExchange`, `BacktestBarFeed`. Config can be changed at runtime in a **live scenario** —
  applied between event cycles, thread-safe, never a mid-cycle attribute poke. (Today only 3
  modules have it, with 2 inconsistent signatures.) For `StrategiesHandler` this consumes
  STRAT-01's re-runnable `init()` (re-validate → re-run `init()` → re-derive warmup). *Byte-exact.*
  [999.5-(b), SYN-03]

### Indicator Framework & Strategy Authoring (IND / STRAT)

- [ ] **IND-01**: A **declared-indicator framework** on the strategy base — indicators registered
  in `init()` (declaration only: `func + input + params`), evaluated lazily per-tick from the
  pushed window using the same `ta` calls as today, with **auto-derived `warmup`/`max_window`**
  (base inspects registered recipes; authors stop hand-setting `max_window`). Declaration-only:
  stateless recompute stays **byte-exact by construction**; incremental/stateful is opt-in *later*
  behind the stable interface. Free-function `crossover`/`crossunder` over series (look-ahead-safe).
  *Byte-exact.* [999.5-(c), W1-05]
- [ ] **STRAT-01**: A **class-attribute strategy authoring surface** replacing the per-strategy
  frozen pydantic config + manual field-copy: engine-facing names with defaults on the base
  (`timeframe`, `tickers`, `sizing_policy`, `order_type`, `direction`, `allow_increase`,
  `max_positions`, `sltp_policy`), alpha knobs as annotated class attrs on the subclass, **all
  overridable at construction via `**kwargs`**, with the base **rejecting unknown kwargs loudly**
  (`UnknownParamError`). `generate_signal` still reads real typed instance attrs (D-12 preserved).
  Model-B pre-eval reads (`self.short_sma[-1]`). Drops the old frozen-config mutation guard →
  a sanctioned-reconfigure-method-only discipline replaces it. Separable from IND-01 — may ship
  first as a smaller byte-exact slice. *Byte-exact.* [999.5-(c)]

### Order Lifecycle (LIFE)

- [ ] **LIFE-01**: **Run-end resting-order disposition / time-in-force** is wired on the backtest
  path — `Order.expire_order()` + `OrderStatus.EXPIRED` (which exist but are unwired) dispose of
  orders left resting at run end instead of leaving them PENDING. Includes the `create_order`
  second-path gating decision (route the unvalidated 2nd signal→order path through validation, or
  document/remove it). *Owner-gated* (result-changing). [999.5-(d), W4-09]

### Engine Hygiene (HYG)

- [ ] **HYG-01**: A small **engine-hygiene slice** (SAFE, no golden re-run): rewrite
  `test_position_manager` private `pm._storage` asserts to public query APIs (W3-07 — owed from
  v1.2 NAME-04, missed); remove the stale mypy override for the deleted `screener_event_handler.py`
  (`pyproject.toml`); delete the dead `TOLERANCE = 1e-3` float constant
  (`portfolio_handler/portfolio.py`); retype `PortfolioValidator.validate_transaction_data` off
  `float` (close the latent Decimal-money-policy violation). **Plus the three v1.2 Phase-6 review
  residues:** drop the dead `StrategyId` import (`order_handler/order_manager.py:20`); consolidate
  the duplicated `_ONE = Decimal("1")` (`brackets/levels.py` + `sizing_resolver.py`) — or document
  the deliberate duplication; soften the misleading `TYPE_CHECKING` guard doc in
  `reconcile/reconcile_manager.py`. *Byte-exact (no run-path touch).* [triage §B items 1–4; v1.2
  06-REVIEW WR-01/IN-01/IN-02]

## Future Requirements

Acknowledged but deferred — tracked, not in this roadmap.

### Indicators (IND)

- **IND-02**: Optional **incremental/stateful** indicator backends behind the IND-01 stable
  interface (O(1) per-tick update for intraday/live/many-ticker scale). Deferred because recursive
  float accumulators (EMA/MACD `ewm(adjust=True)` vs naive recursion) risk a structural
  byte-exactness break during warmup — must be validated value-identical to the stateless twin or
  accept a re-baseline. [W1-05 incremental half]

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| `LiveTradingSystem` / `TradingInterface` test coverage (FL-13) | High-value but the *live* surface; v1.3 = Engine Surface (backtest). Deferred to **999.3 Live Readiness** for an owner (triage §B7). |
| SQL injection + hardcoded creds in `SqlHandler` (FL-06) | Real defect, but the module is quarantined — not on any active path. Belongs with persistence/SQL work → **999.2** (triage §B8). |
| Margin / liquidation model, shorts, leverage, levered Kelly, perp funding, engine-native trailing stop, real long/short pair trading | The matching-engine / risk milestone — extends exactly the surfaces v1.3 completes. → **N+2 (999.4)**. |
| `pytz` → stdlib `zoneinfo` migration | Mostly cosmetic on UTC crypto; no known bug. Don't expand v1.3 scope — backlog/todo (triage §B6). |
| Broad `except Exception` (32 sites) narrowing | By-design at the event-loop boundary per CLAUDE.md; narrow opportunistically as handlers are touched, not a v1.3 commitment (triage §B9). |
| `my_strategies/*` coverage | Decided out-of-scope; targeted for a separate repo (triage §B10). |
| SL/TP redesign (indicator-based exits) | Percent-offset SL/TP stays; only the indicator *recipe* is kept strategy-decoupled so a future phase can consume it. |
| PostgreSQL order storage | Live/persistence concern (999.2); `NotImplementedError` placeholder stays. |
| `portfolio_read_model.py` relocation | Adjudicated KEEP in `core/` (SYN-04) — moving it forces the forbidden order→portfolio cross-domain import; no action. |

## Traceability

Which phases cover which requirements. Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| HYG-01 | Phase 1 — Engine Hygiene | Pending |
| STRAT-01 | Phase 2 — Strategy Authoring Surface | Pending |
| IND-01 | Phase 3 — Declared-Indicator Framework | Pending |
| COMP-01 | Phase 4 — Composition & Config Interface | Pending |
| COMP-02 | Phase 4 — Composition & Config Interface | Pending |
| SIG-01 | Phase 5 — Signal Contract & Reconcile (FRAGILE) | Pending |
| SIG-02 | Phase 5 — Signal Contract & Reconcile (FRAGILE) | Pending |
| SIG-03 | Phase 5 — Signal Contract & Reconcile (FRAGILE) | Pending |
| RECON-01 | Phase 5 — Signal Contract & Reconcile (FRAGILE) | Pending |
| LIFE-01 | Phase 6 — Order Lifecycle & Time-in-Force | Pending |

**Coverage:**
- v1 requirements: 10 total
- Mapped to phases: 10 ✓ (all mapped; no orphans, no duplicates)
- Unmapped: 0 ✓

**Phase grouping rationale:**
- **Byte-exact phases (1-4):** HYG-01 (1), STRAT-01 (2), IND-01 (3), COMP-01/COMP-02 (4) — each
  holds the v1.1 E2E golden suite + BTCUSD oracle byte-exact; a clean pass/fail golden gate.
- **Owner-gated phases (5-6):** SIG-01/02/03 + RECON-01 (5), LIFE-01 (6) — result-changing; each
  owns its re-baseline (owner sign-off + cross-validation), kept SEPARATE from the byte-exact
  phases so each golden gate is unambiguous.

**Co-phasing note (HONORED):** SIG-01/02/03 + **RECON-01** land in **one FRAGILE reconcile phase**
(Phase 5) under a single owner-gated re-baseline + cross-validation pass — `reconcile/` is touched
once, not twice. SIG-03 (`action`→`Side` + snapshot threading) and RECON-01 (`on_fill`/`should_release`
streamline) both touch the FRAGILE fill-reconciliation / reservation-release path, so they are NOT split.

**Sequencing rationale:** STRAT-01 (Phase 2) ships before COMP-02 (Phase 4) because STRAT-01's
re-runnable idempotent `init()` is the seam `StrategiesHandler.update_config` consumes; IND-01
(Phase 3) sits between them (auto-warmup is re-derived on `init()` re-run). The FRAGILE signal/reconcile
core (Phase 5) lands after the composition/config infra (Phase 4) is in place; LIFE-01 (Phase 6) is
self-contained and last. N+2 (margin/shorts) builds on the completed SIG/COMP surfaces.

---
*Requirements defined: 2026-06-12 after milestone v1.3 scoping (promotes Backlog 999.5).*
*Last updated: 2026-06-12 — Traceability populated at roadmap creation; all 10 requirements mapped to 6 phases.*
