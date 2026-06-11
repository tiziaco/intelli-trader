# Requirements: iTrader — v1.2 Consolidation

**Defined:** 2026-06-11
**Core Value:** A single backtest run of `SMA_MACD` on `data/BTCUSD_1d_ohlcv_2018_2026.csv`
produces correct, deterministic, cross-validated numbers.

**Milestone framing:** v1.2 is a **behavior-preserving consolidation** milestone — clear the
v1.1 cleanup-review backlog (`.planning/codebase/V1.2-CLEANUP-REVIEW.md`, 46 findings) and the
`CONCERNS.md` dead/fragile/tangled debt so the next milestone's engine-surface features build
on a clean, decomposed foundation. Every requirement is **byte-exact against the golden master**
(134 trades / `final_equity 46189.87730727451`). Result-changing and new-framework items are
explicitly deferred (see Out of Scope + v-next). Each requirement cites its cleanup-review
finding IDs for traceability.

## Definition of Done (milestone-level)

- `pytest tests/integration` byte-exact oracle held: 134 trades / `final_equity 46189.87730727451`
- `pytest tests/e2e -m e2e` 58/58 green (no leaf re-baselined)
- full suite green; `mypy --strict` clean across all source files
- no new float-for-money; single UUIDv7 ID scheme (no second `uuid4()` scheme on the run path)
- `order_manager.py` decomposed with no semantics change (pure code-motion, golden byte-exact)

## v1.2 Requirements

Requirements for this milestone. Each maps to exactly one roadmap phase.

### Dead Code & Doc Hygiene (DEAD)

- [x] **DEAD-01**: The dead ABCs (`AbstractPortfolioHandler`/`AbstractPortfolio`/`AbstractPosition`
  + orphan `get_last_close`), the unused `OrderBase`, and the dead `import numpy as np` in
  `portfolio.py` are deleted with no importer breakage. [W3-11, W3-09, W4-10]
- [ ] **DEAD-02**: Stale docs are corrected and conventions documented — CONCERNS.md
  `screener_event_handler` item closed (file already deleted); ROADMAP 999.5-(d) FL-01/FL-02 text
  updated to "done"; the config-enum-in-`config/` exception, the broad-`except` run-mode policy
  (backtest fail-fast vs live publish-and-continue), and the tab/space indentation hazard are
  documented in CONVENTIONS/CLAUDE; the dual-layer validator overlap is documented as
  justified-by-decision (not removed). [W1-10, SYN-01, W2-13, W4-04-doc]

### Locked-Decision Conformance (DEC)

- [ ] **DEC-01**: `modify_order`/`cancel_order` public API price/quantity params are typed
  `Optional[Decimal]`, not `Optional[float]` — no float-for-money at a domain boundary. [W4-01]
- [ ] **DEC-02**: `_min/_max_order_size` are carried as `Decimal` end-to-end; the latent
  `Decimal < float` `TypeError` on the below-minimum validation path is removed; golden run
  byte-exact. [W2-10]
- [ ] **DEC-03**: Correlation IDs use the single UUIDv7 `idgen` scheme (or a deterministic
  counter); `uuid.uuid4()` is removed from the run path. [W4-08 / W1-06]

### Hot-Path Performance (PERF)

- [ ] **PERF-01**: In-memory portfolio storage no longer copies the snapshot list / position
  dicts per tick under the D-19 single-writer contract; `snapshot_count()` / `get_latest_snapshot()`
  accessors replace the never-firing per-tick trim copy; copies for a future live backend stay
  behind an explicit `*_snapshot()` variant. [W1-15, W1-02, W1-01]
- [ ] **PERF-02**: Redundant `Decimal(str(Decimal))` re-wraps on the mark-to-market/equity path
  and duplicated per-tick work (`open_position_count` ×2, `is_connected` ×2–3, active-portfolio
  recompute, premature `on_fill` guard allocation, load-time copy) are eliminated. [W1-08, W1-03,
  W1-14, W1-13, W1-07, W1-09]
- [ ] **PERF-03**: MACD is computed inside the SMA guard (not unconditionally before it), and
  `BacktestBarFeed` serves prebuilt `Bar`s instead of 5 `Decimal(str(...))` conversions per symbol
  per tick; values bit-identical, oracle byte-exact. (Incremental/stateful indicators are NOT in
  scope — deferred to the indicator framework.) [W1-12, W1-04]

### Type Modeling (TYPE)

- [ ] **TYPE-01**: `FillDecision`, `CancelDecision`, `OperationResult`, `SignalProcessingResult`,
  and `_PendingBracket` are `frozen=True, slots=True, kw_only=True` facts. [W2-03, W2-04, W2-12]
- [ ] **TYPE-02**: Fee/slippage model dispatch compares enum members with `assert_never`
  exhaustiveness (not `.value` strings); `rebalance_frequency` is validated at the Pydantic
  boundary; the `PortfolioConfig.portfolio_id` false affordance is removed or documented. [W2-08,
  W2-09, W2-11]
- [ ] **TYPE-03**: Closed string vocabularies become enums in `core/enums/` — `ErrorSeverity`,
  `OrderOperationType`, `OrderTriggerSource`, and `market_execution` — with the canonical
  class-based form (`_missing_` + `<domain>_<type>_map` where they cross a boundary). [W2-07,
  W2-05, W2-06, SYN-05-enum]
- [ ] **TYPE-04**: `OrderStatus`/`OrderCommand` are class-based string-valued enums with
  `_missing_`, consistent with every other enum; `order_status_map` `.value` lookups work; golden
  byte-exact (int→string value change audited against serialization/tests). [W2-01]
- [ ] **TYPE-05**: The `BaseStrategyConfig` base contract lives in `itrader/config/strategy.py`
  (re-exported via `config/__init__.py`), consistent with `ExchangeConfig`/`PortfolioConfig`/
  `SystemConfig`; pure code-motion + import updates, oracle-dark. [SYN-02]

### Naming & Encapsulation (NAME)

- [ ] **NAME-01**: `OrderHandler` names its queue `global_queue` (constructor param + attribute),
  not `events_queue`; the count-by-status operation has a single precise name across façade and
  storage. [W3-03, W3-10]
- [ ] **NAME-02**: Strategy classes are PascalCase (`SMAMACDStrategy` / `EmptyStrategy`) and
  strategy-config windows are `fast_window`/`slow_window`/`signal_window` (not `FAST`/`SLOW`/`WIN`);
  all importers (scripts/tests/crossval/e2e) updated; golden byte-exact. [W3-01, W3-02]
- [ ] **NAME-03**: `EventHandler` routes are reachable through a public name/accessor (not
  `_routes`); `SimulatedExchange` exposes `register_symbol()` + a complete `update_config` seam,
  and production code no longer mutates `_supported_symbols`/`_min_order_size` directly. [W3-08,
  W3-04]
- [ ] **NAME-04**: Tests assert through public query APIs, not `_by_id`/`_storage`/`_routes`/
  `_generate_correlation_id` internals (unblocks backend swaps). [W3-05, W3-07, W3-06]

### Order-Manager Decomposition (MOD)

- [ ] **MOD-01**: `order_manager.py` (1279-line god-module) is decomposed into `admission/`,
  `brackets/`, and `reconcile/` collaborators under `order_handler/` (mirroring the
  `portfolio_handler/` manager layout), as **pure code-motion with no semantics change**; the
  terminal-status / `should_release` / `finally`-release interplay is unchanged; golden master
  byte-exact. Dedicated, isolated, late phase. [SYN-06, CONCERNS god-module / Fragile Areas]

## v-next Requirements (Engine Surface Completion — deferred, next milestone)

Acknowledged but deferred — these are the **result-changing / new-framework** items the cleanup
review explicitly held out of v1.2. Tracked, not in this roadmap.

### Signal Contract (SIG)

- **SIG-01**: Per-intent limit/stop ENTRY price + per-intent `order_type` on the signal contract
  (`SignalIntent` → `SignalEvent` → `Order.new_limit_order`/`new_stop_order`). [999.5-(a)]
- **SIG-02**: `Order.action`/`_PendingBracket.action` retyped `str` → `Side`; position-snapshot
  threading through admission→sizing. [W2-02, W1-11 — fragile, coupled to SIG-01]

### Composition / Config Interface (COMP)

- **COMP-01**: Promote `ScenarioSpec` into an engine-level composition API; construction-time
  `ExchangeConfig`/`OrderConfig` threading; uniform per-handler runtime config-update surface;
  composition-root cleanups. [999.5-(b), W4-02/03/05/06/07, SYN-03, SYN-05-config]

### Indicator Framework (IND)

- **IND-01**: Declared-indicator abstraction on the strategy base with auto-derived warmup;
  optional incremental/stateful recompute. [999.5-(c), W1-05]

### Order Lifecycle (LIFE)

- **LIFE-01**: Run-end resting-order disposition / time-in-force (`Order.expire_order()` +
  `OrderStatus.EXPIRED` wired on the backtest path); `create_order` second-path gating decision.
  [999.5-(d), W4-09]

## Out of Scope

Explicitly excluded. Documented to prevent scope creep.

| Feature | Reason |
|---------|--------|
| Signal entry price / `order_type` (SIG-01) | Result-changing; deferred to the Engine Surface Completion milestone (owner choice, behavior-preserving v1.2) |
| Composition/config API (COMP-01) | New contract work, L-effort; explicitly deferred by the cleanup review (999.5-(b)) |
| Declared-indicator framework (IND-01) | Genuine model shift (stateless→stateful); deferred (999.5-(c)) |
| TIF / run-end expire wiring (LIFE-01) | Result-changing; deferred under the behavior-preserving choice (999.5-(d)) |
| PostgreSQL order storage | Owner-excluded; live/persistence concern (N+3), `NotImplementedError` placeholder stays |
| "da modificare / da testare / da spostare" Italian TODOs | Owner-excluded; quarantined deferred subsystems (providers/screeners/my_strategies), off the run path |
| `portfolio_read_model.py` relocation | Adjudicated KEEP in `core/` (SYN-04) — moving it would force the forbidden order→portfolio cross-domain import; no action |

## Traceability

Which phases cover which requirements. Populated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| DEAD-01 | Phase 1 | Complete |
| DEAD-02 | Phase 1 | Pending |
| DEC-01 | Phase 2 | Pending |
| DEC-02 | Phase 2 | Pending |
| DEC-03 | Phase 2 | Pending |
| PERF-01 | Phase 3 | Pending |
| PERF-02 | Phase 3 | Pending |
| PERF-03 | Phase 3 | Pending |
| TYPE-01 | Phase 4 | Pending |
| TYPE-02 | Phase 4 | Pending |
| TYPE-03 | Phase 4 | Pending |
| TYPE-04 | Phase 4 | Pending |
| TYPE-05 | Phase 4 | Pending |
| NAME-01 | Phase 5 | Pending |
| NAME-02 | Phase 5 | Pending |
| NAME-03 | Phase 5 | Pending |
| NAME-04 | Phase 5 | Pending |
| MOD-01 | Phase 6 | Pending |

**Coverage:**
- v1.2 requirements: 18 total
- Mapped to phases: 18 ✓ (Phases 1-6; each requirement maps to exactly one phase)
- Unmapped: 0 ✓

**Phase rollup:**
- Phase 1 — Dead Code & Doc Hygiene: DEAD-01, DEAD-02 (2)
- Phase 2 — Locked-Decision Conformance: DEC-01, DEC-02, DEC-03 (3)
- Phase 3 — Hot-Path Performance: PERF-01, PERF-02, PERF-03 (3)
- Phase 4 — Type Modeling: TYPE-01, TYPE-02, TYPE-03, TYPE-04, TYPE-05 (5)
- Phase 5 — Naming & Encapsulation: NAME-01, NAME-02, NAME-03, NAME-04 (4)
- Phase 6 — Order-Manager Decomposition: MOD-01 (1) — dedicated, isolated, last phase

---
*Requirements defined: 2026-06-11*
*Last updated: 2026-06-11 — roadmap renumbered (v1.2 Consolidation, Phases 1-6; numbering reset matching v1.1); 18/18 requirements mapped*
