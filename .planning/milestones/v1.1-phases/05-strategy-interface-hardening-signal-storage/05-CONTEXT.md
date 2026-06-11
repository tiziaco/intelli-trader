# Phase 5: Strategy Interface Hardening & Signal Storage - Context

**Gathered:** 2026-06-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Put a **pydantic config contract** on the strategy base class, make
`order_type` the `OrderType` enum **end-to-end**, and persist **typed,
queryable signal records** — all **byte-exact** against the SMA_MACD golden
master (134 trades / `final_equity 46189.87730727451`). Done EARLY, before the
Phase 6-9 scenario strategies are written against the base class, and informed
by the Phase 1 codebase map.

**In scope:**
- `BaseStrategyConfig` (pydantic) holding the engine-facing declarations +
  per-strategy params subclasses with validators (HARD-01, HARD-02).
- `order_type` → `OrderType` enum on the base, signal, and call sites; the
  stringly-typed `"market"` removed (HARD-03 / FL-04). Plus the FL-02
  `portfolio_id: int` annotation retype on Signal/Order/Fill events.
- A pluggable **signal storage seam** (ABC + in-memory backend + factory) and a
  typed, queryable `SignalRecord` (SIG-01, SIG-02).
- Relocating `SMA_MACD_strategy.py` + `empty_strategy.py` into a new
  `itrader/strategy_handler/strategies/` package (deferred from Phase 4).
- **CLAR-02 opportunistic cleanup along the touched strategy path:** move
  `__str__`/`__repr__` to the base; make the **framework enforce the warmup
  guard** (handler short-circuits before `generate_signal` when the window has
  fewer than `max_window` bars) so concrete strategies hold only config + alpha.
- Re-prove the golden master byte-exact after every change (oracle-dark).

**Out of scope (routed to future milestones — see Deferred Ideas):**
- Migrating the sizing/SLTP vocabulary to a serializable **discriminated
  union** → v1.3 (Persistence), when SQL round-trip forces it.
- A **structured `(step, unit)` bar-spec value object** replacing `timedelta`
  time-math → roadmap (pairs with the M2-deferred weekly/DST anchoring +
  multi-asset trading-calendar work).
- A **declared-indicator framework** (auto-derived warmup, stateful
  incremental indicators à la nautilus/LEAN/backtrader) → roadmap.
- A **hard signal→order FK** (Order stores the `SignalId`) → v1.3.
- Re-baselining the golden numbers (v1.1 is behavior-preserving; any
  result-changing finding is owner-gated).
- `my_strategies/*` (OUT — user-relocated IP); shorts / non-LONG_ONLY (v1.2).

</domain>

<decisions>
## Implementation Decisions

### Config Model Shape & Constructor Contract (HARD-01/HARD-02/HARD-03)
- **D-01:** **Nautilus-style config object as the single constructor arg.**
  `Strategy(config: BaseStrategyConfig)`; the base stores `self.config` as the
  single source of truth. Engine-facing attrs (timeframe, tickers, order_type,
  direction, allow_increase, max_positions, sizing_policy, sltp_policy) are read
  from it. Chosen over keeping loose kwargs because it matches the repo's
  typed/single-source-of-truth ethos, matches the in-repo cross-val oracle
  (nautilus `StrategyConfig` → `self.config`), and gives SIG-01's "config
  snapshot" for free (`self.config` is the snapshot). Cost accepted: touches
  `run_backtest.py` + the strategy test call sites; must re-prove byte-exact.
- **D-02:** **Per-strategy params via subclass.**
  `SMA_MACDConfig(BaseStrategyConfig)` adds `short_window`/`long_window`/`FAST`/
  `SLOW`/`WIN` and the cross-field validators (`short_window < long_window`,
  positivity). One inheritance chain — NOT a parallel `params` submodel. This is
  the template every Phase 6-9 scenario strategy author follows.
- **D-03:** **`BaseStrategyConfig` is frozen** (`model_config` frozen=True) —
  matches the frozen-value-object convention and makes the snapshot immutable.
- **D-04:** **`order_type` is the `OrderType` enum field** on the config
  (default `OrderType.MARKET`); the stringly-typed `"market"` is removed from
  `base.py`/`SMA_MACD_strategy.py` and the `OrderType(strategy.order_type)`
  boundary parse in `strategies_handler.py` collapses (HARD-03 / FL-04). The
  FL-02 `portfolio_id: int` annotation is retyped on the event facts.

### Sizing/SLTP ↔ pydantic boundary
- **D-05:** **Keep the frozen dataclasses; pydantic tolerates them.**
  `BaseStrategyConfig` uses `ConfigDict(arbitrary_types_allowed=True, frozen=True)`;
  `sizing_policy`/`sltp_policy` stay the frozen dataclass unions in
  `core/sizing.py` (they already self-validate via `__post_init__` →
  `SizingPolicyViolation`). Zero change to `SignalEvent`/`OrderManager`/
  `SizingResolver` — lowest oracle-drift risk, smallest scope. **Rationale for
  not migrating now:** the genuinely correct end-state is a *serializable
  discriminated union* (needed only at v1.3 for SQL round-trip); forcing that
  rewrite onto the byte-exact path inside a *hardening* phase degrades system
  quality (risk) more than it improves it, and v1.1 SIG-02 only needs in-memory
  queryability. Routed to v1.3 (see Deferred Ideas).

### Timeframe validation & conversion
- **D-06:** **Typed `Timeframe` enum/`Literal` at the config boundary; convert
  via `to_timedelta` in the base (unchanged).** The config field is the
  supported fixed-duration vocabulary (e.g. `1m`/`5m`/`15m`/`1h`/`4h`/`1d`/
  `1w`), validated loudly at construction (HARD-01) and stored human-readable;
  the base computes `self.timeframe = to_timedelta(config.timeframe)` exactly as
  today (byte-exact). Types the declaration boundary now without touching
  `check_timeframe`/`_aligned`/`feed.window`. **The real calendar/anchoring fix
  — a structured `(step, unit)` bar-spec value object — is routed to a roadmap
  item** (it intersects the M2-deferred weekly/DST anchoring follow-up and the
  multi-asset trading-calendar work, and rewrites the time core on the byte-exact
  path — out of Phase 5 scope).

### Signal Storage Architecture (SIG-01/SIG-02)
- **D-07:** **Full pluggable seam mirroring `order_handler/storage/`** — ABC +
  in-memory backend + `SignalStorageFactory`. Maximum consistency with the
  existing order-storage pattern and ready for the v1.3 Postgres backend.
- **D-08:** **Dedicated frozen `SignalRecord` entity** — distinct from the
  in-flight `SignalEvent` (the Order-vs-OrderEvent separation). Carries the
  SIG-01 fields (strategy id, ticker, action, time, sizing/sltp declarations) +
  the config snapshot, so the event schema can evolve without breaking
  stored-signal queries.
- **D-09:** **Per-intent capture (pre-fan-out).** One `SignalRecord` per
  non-`None` `generate_signal` result, captured *before* the per-portfolio
  fan-out → **no `portfolio_id`** on the record. Validated against the code:
  the `Order` entity carries `strategy_id` + `portfolio_id` + `ticker` + `time`
  and is built directly from the signal, so portfolio reconciliation is a clean
  **natural-key join** `(strategy_id, ticker, time)` → orders → per-portfolio,
  done downstream at the order layer. One strategy emits at most one intent per
  ticker per bar, so the key is unique. (NOTE: the Order does NOT store the
  signal's `event_id` today — the relation is a natural-key join, not a hard FK;
  a hard `signal_id` FK is routed to v1.3.)
- **D-10:** **`SignalRecord` carries a UUIDv7 `SignalId`** — new `core/ids.py`
  type + `idgen.generate_signal_id`, mirroring `StrategyId`/`OrderId`.
  Consistent with the single-UUIDv7 scheme, gives a query handle, enables the
  v1.3 hard FK without re-keying historical records. (Per-intent capture happens
  before any `SignalEvent` exists, so there is no `event_id` to reuse — the
  record needs its own identity.)
- **D-11:** **Config snapshot stored by reference** — store the frozen
  `self.config` object directly on the record; serialize (`model_dump`) only at
  the storage/query edge. Lossless, cheap, and sidesteps the
  `arbitrary_types_allowed` round-trip concern for v1.1's in-memory backend (a
  future SQL backend serializes at its own boundary).
- **D-12:** **Wiring:** `StrategiesHandler` owns an injected `SignalStore` (the
  way `OrderManager` owns `OrderStorage`) and writes a record when an intent
  fires; the store is read **post-run** via a `TradingSystem` accessor — the
  queue-only contract is preserved (the store is a sink/read-model, not a
  cross-domain handler call). Query API: `get_all` / `by_strategy` / `by_ticker`.

### Strategy Relocation (deferred from Phase 4)
- **D-13:** **Move `SMA_MACD_strategy.py` + `empty_strategy.py` into a new
  `itrader/strategy_handler/strategies/` package.** `base.py` +
  `strategies_handler.py` (the infrastructure) stay at the top level; concrete
  strategies live in `strategies/` — parallels the existing `my_strategies/`
  (supported reference vs user IP). Stays inside the production package (no
  inverted dependency — `run_backtest.py` still imports from `itrader/`, never
  `tests/`). Update the **4 real import sites** (`scripts/run_backtest.py:45`,
  `tests/integration/test_backtest_smoke.py:18`, `tests/unit/strategy/
  test_strategy.py:40`, `tests/integration/test_reservation_inertness.py:69`);
  the `scripts/crossval/*` mentions are verbatim-quote comments (optional
  stale-path touch-up). Re-prove byte-exact.

### Strategy Interface Simplification (CLAR-02 cleanup along the touched path)
- **D-14:** **Move `__str__`/`__repr__` to the base** (derive from `name` +
  `config.timeframe`); concrete strategies drop their copies. Zero result-path
  risk.
- **D-15:** **Framework-enforced warmup guard.** The hand-written
  `if len(bars) < self.max_window: return None` in each strategy is removed; the
  **handler** short-circuits (`if len(data) < strategy.max_window: continue`)
  *before* calling `generate_signal`, so `generate_signal` is only ever invoked
  with enough data. This is the nautilus "only called when `.initialized`" /
  LEAN `SetWarmUp`/`IsWarmingUp` contract — warmup is a framework concern, not a
  per-strategy chore. **Behaviorally identical** to the current in-strategy
  guard (no signal either way) → must be proven oracle-dark by the golden gate.
  Optional: a small `last_time(bars)` / window helper on the base to trim the
  `bars.index[-1]` + slice plumbing.

### Claude's Discretion
- Exact `BaseStrategyConfig` field set/shape and validator wiring (subject to
  D-01..D-06 — frozen pydantic, single source of truth, enum order_type, typed
  Timeframe, arbitrary_types for sizing).
- How `max_window` is exposed on the config/strategy (it is param-derived,
  e.g. `max([long_window, 100])` for SMA_MACD) — subject to D-15 (the handler
  reads it for the warmup short-circuit).
- The precise `SignalRecord` field set and `SignalStore` ABC method surface
  (subject to D-07..D-12 — mirror order storage, per-intent, SignalId,
  snapshot-by-reference, post-run read).
- Where the `Timeframe` enum/`Literal` lives (`core/enums/` vs config module)
  and the exact supported vocabulary list (subject to D-06).
- Whether/where the `last_time`/window helper lands (subject to D-15).
- Whether the base-class migration also touches the e2e test strategies in this
  phase or leaves them as a Phase-6 follow-up (they adopt the new config base;
  `my_strategies/*` is OUT).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase / requirements / decisions
- `.planning/ROADMAP.md` §"Phase 5: Strategy Interface Hardening & Signal
  Storage" — goal + 4 success criteria.
- `.planning/REQUIREMENTS.md` — **HARD-01** (pydantic BaseStrategyConfig),
  **HARD-02** (per-strategy params model + validators), **HARD-03** (`order_type`
  enum end-to-end), **HARD-04** (behavior-preserving / byte-exact, D-12 pure
  alpha intact), **SIG-01** (typed signal records), **SIG-02** (queryable).
- `.planning/PROJECT.md` Key Decisions + "Current Milestone: v1.1" — the
  behavior-preserving / crypto-first / hand-verify-once decisions.
- `.planning/STATE.md` Blockers/Concerns — the byte-exact guardrail for the
  Phase 5 refactor.

### The strategy interface being hardened
- `itrader/strategy_handler/base.py` — the `Strategy` ABC (the `__init__` kwargs
  → config refactor target; D-12 pure-alpha contract; `buy`/`sell` sugar;
  `to_dict`; the `__str__`/`__repr__` move target).
- `itrader/strategy_handler/SMA_MACD_strategy.py` — the oracle strategy
  (becomes `SMA_MACDConfig` subclass; warmup-guard + `__str__`/`__repr__` removal;
  relocation target). The `short_window < long_window` validator codifies its
  defaults (50/100, FAST 6/SLOW 12/WIN 3).
- `itrader/strategy_handler/empty_strategy.py` — second relocation target.
- `itrader/strategy_handler/strategies_handler.py` — `calculate_signals` (the
  `OrderType(strategy.order_type)` boundary parse collapses; the per-portfolio
  fan-out is the per-intent vs per-event capture boundary; the injected
  `SignalStore` write site + the framework warmup short-circuit land here).
- `itrader/events_handler/events/signal.py` — `SignalEvent` (FL-02
  `portfolio_id: int` retype; the entity-vs-event distinction `SignalRecord`
  mirrors).
- `itrader/outils/time_parser.py` — `to_timedelta` (d/h/m/w fixed units, rejects
  month; the D-06 conversion stays here) + `check_timeframe`/`_aligned` (the
  weekly/DST anchoring caveat that the routed bar-spec redesign addresses).

### Config + sizing vocabulary
- `itrader/config/` — the pydantic v2 + `pydantic-settings` models
  `BaseStrategyConfig` joins; `SystemConfig`/`PortfolioConfig`/`ExchangeConfig`
  patterns to follow (`ConfigDict`, validators, frozen).
- `itrader/core/sizing.py` — `FractionOfCash`/`FixedQuantity`/`RiskPercent`
  (`SizingPolicy`), `PercentFromFill`/`PercentFromDecision` (`SLTPPolicy`),
  `SignalIntent`, `TradingDirection`; the frozen dataclasses held under
  `arbitrary_types_allowed` (D-05) and the v1.3 discriminated-union target.
- `itrader/core/enums/` — `OrderType` (HARD-03 target), `Side`,
  `TradingDirection`; the home for a possible `Timeframe` enum (D-06).
- `itrader/core/ids.py` — `StrategyId`/`OrderId` UUIDv7 pattern the new
  `SignalId` (D-10) mirrors; `itrader/outils/id_generator.py` / `idgen`
  (`generate_strategy_id`/`generate_order_id` → add `generate_signal_id`).

### Signal storage analog (mirror this)
- `itrader/order_handler/storage/` — `base.py` (`OrderStorage` ABC),
  `in_memory_storage.py` (flat-dict O(1), predicate-filter queries),
  `storage_factory.py` (`OrderStorageFactory`). The `SignalStore` seam (D-07)
  mirrors this exactly. Also `itrader/order_handler/order.py` (the `Order`
  entity — distinct from `OrderEvent`; carries `strategy_id`/`portfolio_id`/
  `ticker`/`time`, the D-09 natural-key join target) and
  `order_manager.py::on_signal`/`_build_*` (order-from-signal construction).

### Byte-exact oracle gate (re-run after every change)
- `tests/integration/test_backtest_oracle.py` — the exact-diff golden gate
  (134 trades / `final_equity 46189.87730727451`); guards every Phase 5 change
  as oracle-dark.
- `tests/golden/FINAL-ORACLE.md` + `tests/golden/{trades,equity}.csv` +
  `summary.json` — the frozen reference.
- `scripts/run_backtest.py` — the oracle generator + a relocation import site
  (D-13).

### Cleanup standard + fix-list (CLAR-02)
- `.planning/codebase/CLEANUP-STANDARD.md` — the 4-gate opportunistic-cleanup
  checklist D-13/D-14/D-15 execute under (path / eligibility / golden-path /
  bookkeeping).
- `.planning/codebase/FIX-LIST.md` — **FL-04** (`order_type: str = "market"` on
  `base.py:27,38,64` — HARD-03's core target), **FL-02** (`portfolio_id: int`
  annotation carry-over on signal/order/fill events — HARD-03 retype).
- `.planning/codebase/CONVENTIONS.md` / `CONCERNS.md` — naming/visibility
  conventions and post-refactor concerns.

### Prior-phase context (forward pointers)
- `.planning/phases/04-e2e-harness-framework/04-CONTEXT.md` — Phase 4 deferred
  the SMA_MACD relocation here (D-13); the e2e `tests/e2e/strategies/` library
  and `ScenarioSpec`-reuses-real-config decision the hardened base class must
  keep compatible.

### External pattern references (consulted during discussion)
- nautilus-trader `StrategyConfig` subclass → `self.config` (D-01); registered
  indicators auto-updated before the handler, `.initialized` readiness (the
  routed declared-indicator framework + the D-15 warmup contract).
- QuantConnect/LEAN `SetWarmUp`/`IsWarmingUp` (the framework-warmup contract
  behind D-15) + automatic indicator update (the routed indicator framework).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`order_handler/storage/` (ABC + in-memory + factory)** — the exact template
  the `SignalStore` seam (D-07) copies, including the flat-dict + predicate-filter
  query style.
- **`Order` entity (`order.py`)** — the entity-vs-event separation `SignalRecord`
  mirrors (D-08); it carries `strategy_id`/`portfolio_id`/`ticker`/`time`, which
  is what makes the D-09 per-intent natural-key join work.
- **`core/ids.py` + `idgen`** — `StrategyId`/`OrderId` UUIDv7 pattern the new
  `SignalId` (D-10) follows directly.
- **`core/sizing.py` frozen dataclasses** — already self-validating; held as-is
  under `arbitrary_types_allowed` (D-05).
- **`to_timedelta` (`outils/time_parser.py`)** — reused unchanged for the D-06
  conversion; the config only validates/types the string in front of it.
- **The pydantic `config/` models** — `ConfigDict`/validator/frozen patterns
  `BaseStrategyConfig` follows.

### Established Patterns
- **Pure-alpha D-12 contract** — pydantic validation at construction only;
  `generate_signal` stays pure pandas (no queue, no portfolio knowledge). The
  config refactor and the framework warmup guard must preserve this.
- **Handler thin / manager fat; queue-only cross-domain** — `StrategiesHandler`
  stamps/fans-out/enqueues; the `SignalStore` is an injected sink read post-run
  (D-12), not a cross-domain call.
- **Entity vs event** — `Order` (mutable mirror) vs `OrderEvent` (frozen fact);
  `SignalRecord` (D-08) vs `SignalEvent`.
- **Behavior-preserving / oracle-dark** — every change re-runs
  `test_backtest_oracle.py` byte-exact (HARD-04).
- **Folder = supported-vs-IP** — `strategies/` (reference) vs `my_strategies/`
  (user IP, OUT) after D-13.

### Integration Points
- `Strategy(config)` (new) ← `SMA_MACDConfig`/`EmptyStrategyConfig` build configs;
  `scripts/run_backtest.py` + the 3 strategy tests construct via config (D-01).
- `StrategiesHandler.calculate_signals` → writes `SignalRecord` to the injected
  `SignalStore` per intent (D-09/D-12), enforces the warmup short-circuit (D-15),
  and drops the `OrderType(...)` boundary parse (D-04).
- `TradingSystem` ← constructs/injects the `SignalStore`, exposes a post-run
  accessor (D-12); imports the relocated `SMA_MACD_strategy` (D-13).
- `core/enums` / `core/ids` / `idgen` ← new `Timeframe` enum (D-06) + `SignalId`
  + `generate_signal_id` (D-10).

</code_context>

<specifics>
## Specific Ideas

- **Match the in-repo oracle (nautilus-trader) for the config shape.** The user
  explicitly wanted the "state of the art" / correct structure; the config-object
  + per-strategy-subclass pattern was chosen because it is exactly what
  nautilus-trader (already a dependency / cross-val oracle) does, and it fits the
  repo's typed ethos.
- **Future-proof by naming + routing, not by forcing early.** The user repeatedly
  asked "what's the most correct thing for the whole system long-term?" The
  answer adopted throughout: name the correct end-state (discriminated-union
  sizing; structured bar-spec value object; declared-indicator framework) and
  ROUTE it to the milestone that needs it — do the minimal, oracle-safe step in
  this hardening phase. Injecting cross-cutting rewrites onto the byte-exact path
  inside a hardening phase degrades system quality (risk) more than it improves
  it.
- **The interface should not be error-prone.** The user flagged the duplicated
  `__str__`/`__repr__`, the hand-written `len(bars) < max_window` guard, and the
  `last_time = bars.index[-1]` plumbing as error-prone boilerplate. Both
  nautilus and LEAN confirm warmup is a framework concern — hence D-14/D-15 fold
  the safe simplifications into this phase (the interface-hardening phase is the
  right home), oracle-dark.

</specifics>

<deferred>
## Deferred Ideas

- **Serializable discriminated-union sizing/SLTP vocabulary** → **v1.3
  (Persistence)**, oracle-gated. Add `kind` tags so `FractionOfCash`/
  `FixedQuantity`/`RiskPercent`/`PercentFromFill`/`PercentFromDecision`
  round-trip losslessly through SQL/JSONB. Needed only when SQL persistence of
  the signal config snapshot forces real deserialization; v1.1 uses
  `arbitrary_types_allowed` + in-memory (D-05). Touches `core/sizing.py` +
  `SignalEvent`/`OrderManager`/`SizingResolver` on the byte-exact path.
- **Structured `(step, unit)` bar-spec value object** (replacing raw `timedelta`
  time-math) → **roadmap**. The real calendar/anchoring fix (à la nautilus
  `BarSpecification` / `BarAggregation`): distinguishes fixed-duration from
  calendar units, fixes the weekly/DST anchoring gap. Pairs with the M2-deferred
  `check_timeframe`/`_aligned` weekly anchoring follow-up and the multi-asset
  trading-calendar work; rewrites the time core on the byte-exact path. v1.1
  only types the boundary with a `Timeframe` enum (D-06).
- **Declared-indicator framework** (auto-derived warmup + stateful incremental
  indicators, à la nautilus `register_indicator_for_bars` / LEAN `SetWarmUp` /
  backtrader auto-min-period) → **roadmap**. Would let strategy authors stop
  hand-setting `max_window` entirely. Note: a genuine model shift — iTrader's
  `generate_signal(ticker, bars)` is stateless recompute-from-window
  (backtesting.py-like), not stateful-incremental. v1.1 only relocates the
  warmup guard to the framework (D-15).
- **Hard signal→order FK** (the `Order` stores the originating `SignalId`) →
  **v1.3**. v1.1 relies on the `(strategy_id, ticker, time)` natural-key join
  (D-09); the `SignalId` (D-10) is in place so the FK can be added later without
  re-keying.

### Reviewed Todos (not folded)
None — no pending todos matched this phase.

</deferred>

---

*Phase: 5-Strategy Interface Hardening & Signal Storage*
*Context gathered: 2026-06-09*
