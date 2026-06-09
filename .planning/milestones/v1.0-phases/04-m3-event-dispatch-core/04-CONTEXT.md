# Phase 4: M3 — Event & Dispatch Core - Context

**Gathered:** 2026-06-05
**Status:** Ready for planning

<domain>
## Phase Boundary

The **event & dispatch core** phase. Make events immutable, fully-linked facts; replace the racy
fused dispatch loop with a race-free routing registry; and apply the domain-exception hierarchy +
unified logging consistently — all **behavior-preserving** against the post-M2 oracle, across four
locked requirements (M3-01…M3-04):

1. **Event schema redesign (M3-01, #11)** — events are `frozen=True` facts carrying a unique
   `event_id` + `created_at`, required (non-`Optional`) linkage IDs, enum-typed `action`/`order_type`,
   `type` as a real field, and a dedicated error `EventType`.
2. **Race-free dispatch (M3-02, #1/#2, FR2, KB1)** — `get_nowait()`+`queue.Empty` replaces the
   `empty()`/`get(False)` TOCTOU; routing separated from ordering via a
   `dict[EventType, list[Callable]]` registry; unknown types raise `NotImplementedError`.
3. **Errors & logging (M3-03, #7 domain part, #37, KB24)** — domain-exception hierarchy used
   consistently (no bare `ValueError`/`NotImplemented`/swallowed `None`), logging unified, portfolio
   exceptions constructed with correct-typed arguments.
4. **Golden-master gate (M3-04)** — behavioral oracle unchanged AND the post-M2 numerical oracle
   reproduced **byte-exact**. No sanctioned drift this phase; any diff = STOP/investigate, never
   re-baseline.

**Golden-master position:** Both oracle layers are active byte-exact suite assertions since Phase 3
(D-16/D-18) — "full suite green at every commit" IS the M3-04 gate. No D-17-style start-reference
capture is needed (nothing is allowed to drift, unlike M2a/M2b).

**Boundary with adjacent milestones (do NOT pull forward):**
- **M4 (Phase 5)** owns: event/execution money fields → Decimal (M4-07), cash-through-`CashManager`
  (#22), atomic transactions (#16), order-handler layering (#9/#6). M3 keeps event money fields
  **float** and preserves every existing Decimal→float boundary coercion exactly.
- **M5a (Phase 6)** owns: `Bar` struct replacing the per-tick pandas payload (#3/FR1). M3 freezes
  `BarEvent` structurally but does NOT touch its `bars: dict[str, pd.DataFrame]` payload or the
  `get_last_*` accessor ladders.
- **M5b (Phase 7)** owns: sizing-policy completion (M5-06 — the final fate of `SignalEvent.quantity`),
  reporting/presentation split (#38, incl. `engine_logger.py` deletion), `calculate_signal` contract.
- **D-live** owns: live dispatcher dead-letter behavior (the `_on_handler_error` override),
  `trading_interface` rework beyond minimal conformance, `BINANCE_Live` beyond a one-line logger swap.
- **D-screener** owns: actually consuming `ScreenerEvent`s (M3 registers an explicit empty route).

</domain>

<decisions>
## Implementation Decisions

### Event schema (M3-01, #11)
- **D-01: Frozen dataclass base.** A `frozen=True`/`slots=True`/`kw_only=True` `Event` base dataclass
  carries `event_id`, `created_at`, `time`, and `type` as a **real field**; all concrete events
  subclass it. Python 3.13 dataclass inheritance with slots works via kw_only. isinstance-able for
  dispatch, mypy --strict friendly.
- **D-02: event_id = uuid7 default_factory; created_at = business time.** `event_id` auto-generates
  via `uuid_utils` uuid7 (same scheme as entity IDs; oracle excludes ID values per M1 D-12).
  `created_at` **defaults to the event's business `time`** — fully deterministic in backtest, zero
  Clock plumbing into the ~15 construction sites. No wall clock on the engine path (M2-05 holds).
- **D-03: Drop `SignalEvent.verified` — typed outcome instead.** The validator/risk-manager verdict
  flows through the order pipeline as typed state (see D-13), never as event mutation. The signal
  stays a pure immutable strategy fact.
- **D-04: Event money fields stay float until M4.** Preserve the existing Decimal→float→Decimal
  boundary coercions (e.g. `OrderEvent.new_order_event`) exactly — zero numeric-drift risk for the
  byte-exact gate. M4-07 retypes.
- **D-05: New dedicated `Side`/`Action` enum (BUY/SELL) in `core/enums`** types `action` on
  Signal/Order/Fill events; `SignalEvent.order_type` becomes `OrderType` (already exists). Portfolio
  maps Action→TransactionType at its boundary, exactly like FillStatus→OrderStatus today (Phase 3
  D-04 distinct-vocabularies precedent). Follow the Phase 3 `_missing_`/`from_string` enum pattern.
- **D-06: ErrorEvent hierarchy (user-proposed, FastAPI-style).** A **concrete, instantiable**
  `ErrorEvent` base (source/domain, error_type, message, severity, correlation_id, details) + a
  per-domain child `PortfolioErrorEvent`; ALL carry `type=EventType.ERROR` (one registry entry;
  consumers isinstance for domain specifics). Mirrors the `core/exceptions` hierarchy shape. Future
  domain error events (Execution/Order) added only when a domain actually emits them. This replaces
  the current PortfolioErrorEvent's `type = EventType.UPDATE` hack.
- **D-07: Dict payloads — type what's cheap.** Tighten `PortfolioUpdateEvent.portfolios` if an
  existing shape fits; `strategy_setting` may stay a documented `dict[str, Any]`. NO new DTO classes
  invented purely for typing (M4/M5 re-own those shapes).
- **D-08: PING family → TimeEvent family.** Rename `PingEvent` → `TimeEvent`, `EventType.PING` →
  `EventType.TIME`, `PingGenerator` → `TimeGenerator`, `simulation/ping_generator.py` →
  `simulation/time_generator.py` (git mv). Nautilus-precedent naming ("the clock advanced to T"),
  pairs with `core.clock.Clock`; kills the factually-wrong PingEvent docstring. `TICK` is RESERVED
  for future live market-data ticks (deferred). Oracle-safe: event names appear nowhere in the oracle.
- **D-09: Events package split.** `events_handler/events/` package: `base.py` (Event), `market.py`
  (Time/Bar/PortfolioUpdate), `signal.py`, `order.py`, `fill.py`, `error.py` (ErrorEvent hierarchy) —
  with `__init__` re-exports keeping consumer import paths short (Phase 3 D-11 reorg precedent).
  `EventType` relocates to `core/enums` (closing Phase 3's D-05 deferral); `event_type_map` deleted.

### Linkage IDs (M3-01)
- **D-10: `SignalEvent.quantity: float | None = None`.** `None` means "order/risk layer sizes me"
  (kills the `0` sentinel); explicit caller-supplied quantity preserved (and its regression test
  `test_zero_quantity_signal`). Full removal deliberately NOT done — M5-06 owns the sizing-policy
  schema and may replace the field then.
- **D-11: Brackets via create-all-then-emit.** Restructure `process_signal`: build parent + SL/TP
  Order entities FIRST (all UUIDv7 ids exist), populate `parent.child_order_ids` (today declared at
  `order.py:74` but never populated), THEN emit complete OrderEvents parent-first. Queue arrival
  sequence is unchanged → behavior-preserving. Events carry two-directional linkage:
  `child_order_ids: tuple[OrderId, ...] = ()` on non-brackets, `parent_order_id` on children.
- **D-12: Required IDs via minimal conformance.** In-scope sites construct events from entities (ids
  guaranteed). The D-live `trading_interface` gets the minimal fix to keep importing/type-checking
  (generate the UUIDv7 at the call site or via small entity construction) — no deeper live rework.
  `FillEvent` gains `fill_id` (generated by the exchange at fill construction) + `strategy_id`
  (copied from the originating OrderEvent); `order_id` required on both OrderEvent and FillEvent.
- **D-13: Order entity AS the pipeline state (no OrderSpec type).** After sizing resolves the
  Decimal quantity, create the `Order` entity (PENDING) immediately; the validator/risk-manager
  check the **entity**; acceptance → store + emit events (D-11); rejection → transition to REJECTED
  via the existing audited `add_state_change` path (deterministic event-derived timestamps, M2-09).
  FIX/Nautilus lifecycle shape: rejections become auditable state changes instead of vanishing.
  The resolved quantity lives Decimal-native on the entity (the WR-05 signal float coercion dies
  with the signal mutation). Sizing failures (invalid price) still short-circuit BEFORE entity
  creation, preserving the narrow sizing-before-validation gate. NOTE: rejected signals now leave a
  REJECTED order in storage (not in the oracle, but storage-count test assertions may need touching).

### Dispatch registry (M3-02)
- **D-14: EventHandler-owned explicit route dict.** The full `dict[EventType, list[Callable]]` is
  built in `EventHandler.__init__` — the entire dispatch order is ONE reviewable literal. List order
  IS the documented execution order (BAR: portfolios→execution→strategies; FILL: portfolio→order
  mirror). Handlers stay passive — no registration API (#2: no pub-sub decoupling).
- **D-15: Drain via `get_nowait()` + `queue.Empty` → break.** No `empty()` precheck (kills the
  TOCTOU and the `event is None` deref).
- **D-16: Layered error flow + `_on_handler_error` policy seam.** Business errors stay DATA below
  the dispatcher (FillEvent(REFUSED), ErrorEvents, typed results — the run continues); unexpected
  handler exceptions route through a `_on_handler_error(event, handler)` seam whose backtest
  implementation **re-raises** (fail-fast, today's behavior, oracle-safe). Live publish-and-continue
  becomes a later override (D-live). Mirrors the Phase 3 D-06 replaceable-seam precedent. The ERROR
  route gets a real consumer that logs ErrorEvents with bound structlog context.
- **D-17: Explicit empty routes for consumerless types; unknown → raise.** `SCREENER` (D-screener)
  and `UPDATE` (live API path) register with an explicit empty list + comment naming the deferral.
  Unregistered/unknown types raise `NotImplementedError` (fixes KB1's `NotImplemented`). This also
  fixes a latent crash found during discussion: `PortfolioErrorEvent` (type=UPDATE) IS queued on
  failure (`portfolio_handler.py:116`) but the current chain has no UPDATE branch → dispatcher
  would raise. Under the new design it carries EventType.ERROR and routes to the log consumer.

### Exceptions & logging (M3-03, #37, KB24)
- **D-18: Full in-scope adoption + prune.** Replace bare raises across the in-scope (backtest-path)
  package with the proper domain-exception subclass, adding missing order/data exception modules;
  fix the KB24 wrong-arg constructions (`PortfolioNotFoundError`, `PortfolioConfigurationError`).
  DELETE the dead weight: `core/exceptions/execution.py`'s 12 classes (execution failure is data by
  design — FillEvent/ExecutionErrorCode), the unused `ConcurrencyError` family + dead imports
  (D-13 mechanical-delete precedent: verify zero importers first). Deferred modules
  (CCXT/OANDA/live/SQL) keep their raises.
- **D-19: Root exception renamed `ITradingSystemError` → `ITraderError`.** Package-named per Python
  convention (requests.RequestException style). Cheapest now: ~zero `except` sites reference it
  before M3's adoption makes it load-bearing.
- **D-20: Full in-scope logging cleanup.** Route in-scope stdlib loggers (`SMA_MACD_strategy.py`,
  `sltp_models.py`) through `get_itrader_logger().bind(component=...)`; `BINANCE_Live.py` one-line
  swap at most (D-live); leave `engine_logger.py` alone (M5b deletes it). Make `json_logs`
  config-driven (logger.py:182 hardcode); guard the import-time root-handler clearing
  (logger.py:100); fix falsy `if value:` checks that drop legitimate 0/"" values.
- **D-21: Log-level policy (user-raised).** Per-tick/per-event flow (TIME/BAR dispatch, signal
  evaluation, fill matching) → DEBUG; lifecycle facts (init, portfolio created, run start/finish) →
  INFO. Default backtest terminal goes quiet; `Settings.log_level` (exists since Phase 3) restores
  the firehose. The dispatcher's per-ping INFO log is demoted in the rewrite. Terminal-rendering
  redesign (custom processors, progress display) is DEFERRED — presentation work, not M3.

### Verification (M3-04)
- **D-22: Gate = existing byte-exact suite assertions green at every commit.** Behavioral identity
  + numerical oracle (check_exact since Phase 3 D-16) stay active throughout. Any diff = STOP /
  investigate / COVERAGE-INDEX §E — never a re-baseline (M3 is not a sanctioned re-baseline point).
- **D-23: Three new test groups.** (1) Dispatch-ordering regression test asserting the load-bearing
  route lists as data (BAR: portfolios→execution→strategies; FILL: portfolio→order-mirror);
  (2) event immutability tests (mutation raises FrozenInstanceError; linkage IDs required at
  construction); (3) error-flow tests (ErrorEvent routes to the log consumer; handler exception
  re-raises through the seam; unknown EventType raises NotImplementedError).
- **D-24: Sequencing = planner discretion.** The four workstreams (events / dispatch / exceptions /
  logging) order freely under the standing constraints: suite + both oracle layers green at every
  commit, each workstream bisectable (Phase 3 precedent). No terminal gate this phase.

### Claude's Discretion
- Exact `Event` base field definitions, `type` field mechanics (init=False per-class default vs
  other), and the `EventType` class-enum + `from_string`/`_missing_` details (follow Phase 3 D-04).
- ErrorEvent field set and the severity vocabulary; whether `to_dict` survives.
- Exact split of classes across the `events_handler/events/` modules and the `__init__` re-export
  surface.
- The new order/data exception module contents and `error_code` scheme; which swallowed-`None`
  sites convert to raises vs typed results (within #7's business-outcome-vs-bug rule).
- `EnhancedOrderValidator`/risk-manager signature changes for entity-based validation (D-13) and
  the storage-count test adjustments for REJECTED orders.
- FillEvent extras beyond the requirement (e.g. an `exchange` field) — planner judgment; slippage
  separation stays M5.
- Per-module mypy override list adjustments as modules enter strict scope.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Authoritative analysis (source of truth — do NOT re-derive requirements)
- `.planning/REFACTOR-BRIEF.md` — program goal/scope, locked decisions, golden-master discipline
- `.planning/COVERAGE-INDEX.md` — items→milestone contract; M3 row: findings 1, 2, 7*, 11, 37 +
  KB1, KB24, FR2; §E logs any gap-discovery deltas
- `.planning/PROJECT.md` — milestone breakdown, two-point re-baseline rule (M3 is NOT one),
  Out-of-Scope tags
- `.planning/REQUIREMENTS.md` — **M3-01…M3-04** (the locked WHAT for this phase)
- `.planning/ROADMAP.md` — Phase 4 goal + 4 success criteria

### Architecture findings driving this phase
- `.planning/codebase/ARCHITECTURE-REVIEW.md` — **#1** (dispatch TOCTOU + fused routing/ordering;
  the registry design), **#2** (in-house registry, no event-bus library — locked Out-of-Scope),
  **#11** (event schema redesign — the per-event audit and 7-point cross-cutting approach),
  **#7** (domain errors in-package; business outcomes as typed results; FastAPI edge → D-live),
  **#37** (exception hierarchy half-adopted + logging split — the findings D-18…D-20 resolve).
  Boundary refs (do NOT pull forward): **#3/FR1** (Bar struct — M5a), **#39** (execution DTOs — M4),
  **#22/#16** (cash/transactions — M4), **#9/#6** (order-handler layering — M4).
- `.planning/codebase/CONCERNS.md` — KB1 (`raise NotImplemented`), KB24 (wrong-arg portfolio
  exceptions), FR2 (`empty()`/`get(False)` race).

### Phase carry-forward (constrains M3)
- `.planning/phases/03-m2b-config-types-storage-seam-oracle-re-freeze/03-CONTEXT.md` — **D-04**
  (enum `_missing_`/`from_string` pattern; lifecycle vocabularies stay DISTINCT), **D-05**
  (EventType left inline FOR M3 — this phase closes it), **D-11** (subdomain-package reorg
  precedent for the events split), **D-16/D-18** (byte-exact oracle assertions now active).
- `.planning/phases/02-m2a-identity-money-determinism/02-CONTEXT.md` — **D-09** (injected clock;
  perf-telemetry wall-clock carve-out), **D-12** (NewType ID aliases; oracle excludes ID values),
  **D-15** (tolerance window CLOSED — byte-exact now), Claude-discretion note on
  `SignalEvent.verified` as the known immutability blocker (resolved here by D-03/D-13).

### Existing patterns to mirror / golden assets
- `itrader/core/enums/order.py`, `itrader/core/enums/portfolio.py` — the Phase 3 class-enum
  pattern (`_missing_` case-insensitive parse) for the new Side enum + relocated EventType.
- `itrader/core/clock.py` — the injected Clock family TimeEvent naming pairs with.
- `itrader/core/ids.py` — NewType alias pattern for any new `FillId`/`EventId` aliases.
- `itrader/order_handler/order.py` — `Order.child_order_ids` (`:74`, never populated),
  `add_state_change` validated path (the D-13 rejection route), `VALID_ORDER_TRANSITIONS`.
- `tests/integration/` oracle tests — behavioral identity + byte-exact numeric assertions (the
  M3-04 gate; do not modify their assertions).
- `data/BTCUSD_1d_ohlcv_2018_2026.csv` + the committed golden oracle — frozen at M2b end-state,
  reproduced exactly this phase.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `itrader/events_handler/event.py` (457 lines) — the 8 event classes to redesign;
  Ping/Bar/PortfolioUpdate/Screener already frozen+slots (Phase 2), Signal/Order/Fill mutable.
- `itrader/events_handler/full_event_handler.py:62-85` — the if/elif chain the registry replaces;
  the load-bearing BAR ordering (`update_portfolios_market_value` → `on_market_data` →
  `calculate_signals`) and FILL ordering (`portfolio.on_fill` → `order_handler.on_fill`).
- `itrader/core/exceptions/{base,portfolio,execution}.py` — hierarchy to adopt/prune/rename.
- `itrader/logger.py` — `json_logs` hardcode (`:182`), import-time handler clear (`:100`).

### Established Patterns
- Queue-only cross-domain communication; handler/manager split; `on_<event>` callbacks.
- **Tabs** in handler modules; **spaces** in config/ and newer modules — the new events package and
  exception modules are new code → spaces; match files being edited in place.
- `make typecheck` (mypy --strict) gate live; `filterwarnings=["error"]`, strict markers/config.
- Phase 3 commit discipline: pure-move commits separate from logic commits, bisectable, suite green
  at every commit.

### Integration Points
- Event construction sites (D-01/D-02/D-12): `strategy_handler/base.py:79` (SignalEvent),
  `order_manager.py:353,401,446,516,572` (OrderEvents), `exchanges/simulated.py:215,232,252,267`
  (FillEvents via `new_fill`), `universe/dynamic.py:77` + `screeners_handler.py:37` (BarEvent),
  `ping_generator.py:45,53` (TimeEvent rename), `portfolio_handler.py:393` (PortfolioUpdateEvent),
  `portfolio_handler.py:102-116` (`_publish_error_event` → ErrorEvent), `trading_interface.py:69,118`
  (D-live minimal conformance), `BINANCE_Live.py:109` (D-live).
- Signal mutation sites to remove (D-03/D-13): `order_validator.py:123-148` (verified),
  `advanced_risk_manager.py:34-64` (verified), `variable_sizer.py:32` (verified),
  `order_manager.py:276,289` (`_resolve_signal_quantity` in-place quantity writes).
- Bracket flow restructure (D-11): `order_manager.py` `_create_primary_order` /
  `_create_stop_loss_order` / `_create_take_profit_order` → create-all-then-emit.
- Dispatch rewrite (D-14…D-17): `full_event_handler.py` + both TradingSystems' wiring.
- EventType consumers: `event_type_map` deleted; `from itrader.events_handler.event import`
  sites repointed to the new package re-exports.
- Logging (D-20/D-21): `SMA_MACD_strategy.py:9`, `sltp_models.py:7`, `logger.py:100,182`,
  the dispatcher's per-ping INFO log.

</code_context>

<specifics>
## Specific Ideas

- User proposed the **ErrorEvent hierarchy** explicitly (concrete base + per-domain children,
  FastAPI-style) — locked as D-06; they noted it mirrors how they structure exception handling in
  FastAPI applications.
- User questioned `OrderSpec`'s value ("would I use it? would I audit it?") which led to the
  stronger **Order-entity-as-pipeline-state** decision (D-13) — they explicitly preferred the
  FIX/Nautilus lifecycle shape where rejections are auditable state changes.
- User dislikes the `ITradingSystemError` name (C#-style I-prefix) → renamed `ITraderError` (D-19).
- User asked "what does PingEvent do / shouldn't it be TICK?" → after seeing industry naming
  (Nautilus TimeEvent, Zipline clock, QuantStart heartbeat), locked the **TimeEvent family** rename
  (D-08) and reserved **TICK** for future live market-data ticks.
- User raised backtest log noise ("I'm logging everything, even ping events") → log-level policy
  (D-21) folded into M3; terminal-rendering redesign deferred.
- User wanted `on_handler_error` future-proofing for live mode → policy seam with fail-fast default
  (D-16), after clarifying that business errors never reach the dispatcher (they're data).

</specifics>

<deferred>
## Deferred Ideas

- **`TickEvent` for live market-data ticks** — name reserved; introduced when live mode lands
  (D-live). The TimeEvent rename deliberately avoids colliding with it.
- **Live dead-letter dispatch** — `_on_handler_error` override that publishes ErrorEvent +
  continues, instead of re-raising → **D-live**. The seam (D-16) exists for exactly this.
- **`SignalEvent.quantity` final fate** — may be replaced by a strategy-declared sizing-policy
  field when M5-06 completes the sizing seam → **M5b (Phase 7)**.
- **Terminal-rendering redesign** (custom structlog processors/renderers, progress display, rich
  run summaries) → presentation work near **M5b**'s reporting split (#38); M3 only sets log levels.
- **`engine_logger.py` deletion** → **M5b (M5-07)**; M3 leaves it untouched.
- **Event money fields → Decimal + frozen execution DTOs (`fill_id` on result objects)** →
  **M4 (M4-07)**.
- **`Bar` struct replacing the BarEvent pandas payload + `get_last_*` ladders** → **M5a (M5-02)**.
- **`FillEvent` slippage-vs-price separation** → **M5a** fee/slippage correctness (M5-04).

</deferred>

---

*Phase: 4-m3-event-dispatch-core*
*Context gathered: 2026-06-05*
