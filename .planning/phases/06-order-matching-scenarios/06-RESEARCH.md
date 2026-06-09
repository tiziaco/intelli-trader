# Phase 6: Order Matching Scenarios - Research

**Researched:** 2026-06-09
**Domain:** Golden-coverage test authoring on the Phase 4 E2E harness for the existing resting-order book / bracket-OCO / trigger-gap matching engine
**Confidence:** HIGH (every claim below grounded in read source; no library uncertainty — this is an internal-codebase coverage phase)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** ONE generic parametrized scripted-emitter in `tests/e2e/strategies/` — emits a configured `SignalIntent` (action, sl, tp, exit_fraction) on configured bars. One mechanism reused across all scenarios; generalizes Phase 4's `SingleMarketBuy`.
- **D-02:** LIMIT/STOP entry price via contrived-bar authoring — the entry rests at the decision-bar close (`signal_event.price`); the scenario sets that close to the desired trigger and authors the FOLLOWING bars. NO signal-contract change.
- **D-03:** Emitter mirrors production: `order_type` is per strategy instance (from config; `SignalEvent.order_type = strategy.order_type`). The per-bar script only picks action + sl/tp/exit_fraction. Bracket SL/TP children get STOP/LIMIT from the assembler regardless of entry type.
- **D-04:** Script keyed by the current bar's DATE (`bars.index[-1] == "YYYY-MM-DD"`), NOT completed-bar count.
- **D-05:** The harness plays the OPERATOR role and calls the REAL `OrderHandler.modify_order`/`cancel_order` (genuine round-trip). Mirrors live's `TradingInterface`. REJECTED: strategy back-reference; raw `OrderEvent(MODIFY/CANCEL)` queue injection.
- **D-06:** Seam = a tiny oracle-inert `on_tick` hook on the backtest run (`run(on_tick=None)`, default `None` = byte-exact). `ScenarioSpec` gains an optional `actions` timeline (bar-date → modify/cancel); the harness translates it into `on_tick` calls.
- **D-07:** Scheduled action names its target by PREDICATE (ticker + status, or "the sole resting order"), resolved at the target bar via the EXISTING query API (`get_active_orders`/`get_orders_by_ticker`), then `modify_order`/`cancel_order(order.id, ...)`. `Order.id` is a non-deterministic UUIDv7 — never referenced literally.
- **D-08:** New OPT-IN orders-snapshot golden artifact for outcomes with no trade row. Final order-mirror snapshot queried post-run, frozen with deterministic business columns only (ticker, order_type, action, final status, price, quantity, filled_quantity, business time); bracket linkage as a logical ENTRY/SL/TP role, not raw UUIDs; `order_id`/`event_id`/`created_at`/`updated_at` EXCLUDED. Rows in a deterministic sort order.
- **D-09:** Snapshot is OPT-IN, like `equity.csv` — frozen only where order state is the assertion (MATCH-04/05/06/07/08). Pure fill scenarios (MATCH-01/02/03) rely on `trades.csv` + `summary.json`.
- **D-10:** MATCH-08 asserts AS-IS — the far-from-market limit stays resting in the snapshot, zero trades, run completes cleanly. No run-end order disposition on the backtest path (`expire_order()`/`EXPIRED` exist but are unwired).
- **D-11:** One leaf folder per distinct fill-shape (~12-15 scenarios). One hand-verifiable assertion per leaf; parallel-safe.
- **D-12:** Batched-at-end verification — generate ALL scenarios in parallel first, then hand-verify + freeze in ~4 grouped sittings by requirement cluster.
- **D-13:** Foundational plan first = shared infra + ONE proof scenario (MATCH-01) end-to-end, hand-verified, before the parallel wave.
- **D-14:** All Phase 6 scenarios run zero-fee / zero-slippage (`exchange=None`, like the Phase 4 canary).
- **D-15:** Brackets declare SL/TP via explicit Decimal levels (`intent.stop_loss`/`take_profit` — explicit levels used verbatim, `sltp_policy` ignored).

### Claude's Discretion
- Exact orders-snapshot column set and the ENTRY/SL/TP role-derivation rule (subject to D-08).
- Exact `on_tick` hook signature and how `ScenarioSpec.actions` entries are shaped (subject to D-06/D-07).
- The deterministic sort key for snapshot rows.
- Contrived `bars.csv` authoring per scenario (subject to D-02/D-11).
- Exact `tests/e2e/matching/` sub-directory names/depth (subject to Phase 4 D-14 subsystem grouping).
- Whether MODIFY scenarios need separate re-price vs re-size leaves (subject to D-11 one-shape-per-leaf).

### Deferred Ideas (OUT OF SCOPE)
- Explicit per-intent limit/stop ENTRY price (and per-intent `order_type`) on the signal contract. Owner-gated; future milestone. Phase 6 works around it via contrived bars.
- Run-end resting-order disposition / time-in-force. `Order.expire_order()`/`OrderStatus.EXPIRED` exist but unwired on the backtest path. Owner-gated, own phase.
- Strategy-driven order management (cancel/modify/contingent styles). Deliberately NOT supported by the pure-alpha contract.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support (engine fact + what to author + what to freeze) |
|----|-------------|------------------------------------------------------------------|
| MATCH-01 | MARKET next-bar-open fills (regression of v1.0 path) | Engine: resting MARKET fills unconditionally at the next bar's `open` (`matching_engine._evaluate`, `OrderType.MARKET → return open_`). Author: emitter `order_type=MARKET`, BUY one bar, full SELL a later bar. Freeze: `trades.csv` + `summary.json` (no snapshot — D-09). This IS the D-13 proof scenario. |
| MATCH-02 | LIMIT entry: in-bar touch vs favorable gap-through | Engine: BUY LIMIT — `open_ <= trigger → fill at open` (gap-through, better); `low <= trigger → fill at trigger` (touch). Two leaves (D-11). Author: set decision-bar close = limit price; next bar either gaps below open (gap-through) or has low ≤ trigger but open > trigger (touch). Freeze: `trades.csv` + `summary.json`. |
| MATCH-03 | STOP entry: pessimistic gap-down/gap-up fills | Engine: SELL STOP — `low <= trigger → fill at min(open, trigger)`; BUY STOP — `high >= trigger → fill at max(open, trigger)`. NOTE: a STOP *entry* (not a bracket child) needs `order_type=STOP` on the emitter. Two leaves (gap-down, gap-up). Freeze: `trades.csv` + `summary.json`. |
| MATCH-04 | Bracket OCO full lifecycle: children dormant while parent rests, arm on parent fill, sibling OCO-cancel on fill | Engine: pass-1 fills parent (leaves book) → pass-2 unlocks children same/later bar; one leg fills, sibling emits `CancelDecision` → `FillEvent(CANCELLED)`. Author: MARKET (or any) entry + `sl=`/`tp=` Decimal levels; later bar triggers exactly one leg. Freeze: orders-snapshot (filled leg FILLED, sibling CANCELLED, parent FILLED) + `trades.csv`. |
| MATCH-05 | Same-bar double trigger → STOP-beats-LIMIT priority | Engine: `_pick_bracket_winner` returns the STOP leg when both SL(stop) and TP(limit) are candidates same bar. Author: one bar whose high ≥ TP AND low ≤ SL. Freeze: orders-snapshot (SL FILLED, TP CANCELLED). |
| MATCH-06 | Gap clean-through a stop/limit; gap past BOTH bracket legs | Engine: gap-through fills at the pessimistic (stop) / better (limit) price; a bar that gaps past both legs still fills exactly ONE leg (STOP wins via `_pick_bracket_winner`, sibling OCO-cancelled). Three leaves (D-11: clean-through-stop, clean-through-limit, gap-past-both). Freeze: orders-snapshot + trades where a leg fills. |
| MATCH-07 | MODIFY (re-price/re-size) and CANCEL of a resting order via the order round-trip | Engine: harness `on_tick` calls `OrderHandler.modify_order(order.id, new_price=, new_quantity=)` / `cancel_order(order.id)`; manager → `OrderEvent(MODIFY/CANCEL)` → `SimulatedExchange.on_order` mutates/removes the resting book; CANCEL emits `FillEvent(CANCELLED)`. Author: rest a far-from-market order, `actions` timeline modifies/cancels at a named bar. Freeze: orders-snapshot (CANCEL → CANCELLED; MODIFY → new price/qty then fill or rest). |
| MATCH-08 | Limit far from market never fills; handled at run end | Engine: order never triggers, stays resting; run completes cleanly; D-10 → final mirror status is `PENDING` (no `ACTIVE` enum exists, no run-end expiry). Author: limit far from every authored bar's range. Freeze: orders-snapshot (status PENDING, filled_quantity 0), zero trades. |
</phase_requirements>

## Summary

Phase 6 is a pure golden-coverage phase. The `MatchingEngine` (`itrader/execution_handler/matching_engine.py`) already implements every behavior under test — next-bar-open market fills, limit touch-vs-gap-through, pessimistic stop gap fills, parent-filled child gating (CR-01), STOP-beats-LIMIT same-bar priority, and OCO sibling-cancel. Phase 6 authors ~12-15 contrived-bar scenarios that exercise these paths and `--freeze`-locks them. The only new code is shared TEST infra (D-13): a generic scripted-emitter, an oracle-inert `on_tick` hook on `TradingSystem.run`, an `actions` timeline on `ScenarioSpec`, and an orders-snapshot golden serializer + diff.

The Phase 4 harness (`tests/e2e/conftest.py`) is mature and directly extensible: `run_scenario` does build→run→read→assemble→diff-what's-frozen with a `--freeze` flag that is mechanically restricted to one scenario at a time. The harness already threads `spec.start`/`spec.end` into `CsvPriceStore` so each leaf's contrived `bars.csv` is pinned to its own window, and reads `system.order_handler` is reachable for the operator calls. The snapshot serializer joins the existing `itrader.reporting.frames` family (same `to_csv(float_format=FLOAT_FORMAT)` → `read_csv` round-trip diff contract).

**Primary recommendation:** Build the four shared-infra pieces in the D-13 foundational plan exactly as the existing harness patterns dictate (extend `_build_and_run` to accept and invoke `on_tick`; extend `_freeze`/`_diff` with an opt-in `orders.csv`; add `tests/e2e/strategies/scripted_emitter.py`; extend `ScenarioSpec` with `actions`). Author each scenario's `bars.csv` so every fill price is a round number hand-derivable from the engine's exact trigger/gap formulas (documented per-MATCH below). Use `OrderType.STOP` / `OrderType.LIMIT` on the emitter config for STOP/LIMIT *entry* scenarios (MATCH-02/03), and explicit Decimal `sl`/`tp` for bracket scenarios (MATCH-04/05/06).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Contrived bar authoring | Test data (`bars.csv`) | `CsvPriceStore` (read path) | The scenario controls every OHLC value; the store loads it unchanged. |
| Signal emission timing | Test strategy (scripted-emitter) | `StrategiesHandler` (fan-out) | Pure-alpha contract: strategy decides *when*, handler stamps price/time/policy. |
| Order creation / bracket assembly | `OrderManager` (production) | `OrderHandler` (interface) | Phase 6 exercises the real path; authors only supply intent + sl/tp. |
| Order matching / fills / OCO | `MatchingEngine` (production, under test) | `SimulatedExchange` (fee/slippage off) | The system under test — Phase 6 covers, never modifies it. |
| Operator MODIFY/CANCEL (MATCH-07) | Harness `on_tick` → `OrderHandler` API | `OrderManager` validation + matching book | Mirrors live `TradingInterface`; genuine round-trip. |
| Result assertion | `run_scenario` harness diff | `itrader.reporting.{frames,summary}` + new snapshot serializer | Exact no-tolerance diff against frozen goldens. |

## Standard Stack

This phase introduces **no new external packages**. It uses only the existing test/runtime stack. The "stack" here is the internal API surface the planner must target.

### Core (internal APIs the new infra targets)
| Component | Location | Purpose | Exact signature / contract |
|-----------|----------|---------|-----------------------------|
| `run_scenario` fixture | `tests/e2e/conftest.py:372` | Build→run→read→assemble→diff per leaf | `run_scenario(here: Path)`; calls `_build_and_run(spec)` then `_freeze`/`_diff`. Extend `_build_and_run` to thread `on_tick`; extend `_freeze`/`_diff` for `orders.csv`. |
| `_build_and_run(spec)` | `tests/e2e/conftest.py:147` | Wires `TradingSystem`, runs, returns `(system, portfolio)` | Returns `system` (so `system.order_handler` is reachable). `system.run(print_summary=False)` is the call to extend with `on_tick`. |
| `ScenarioSpec` | `tests/e2e/smoke/single_market_buy/scenario.py:119` | Per-leaf frozen dataclass (`start,end,timeframe,ticker,starting_cash,data,strategies,portfolios,exchange`) | Add `actions: list[...] = ()` (default empty = oracle-inert). Each leaf copies this dataclass (it is defined per-leaf, NOT shared — see Pitfall 1). |
| `TradingSystem.run` | `itrader/trading_system/backtest_trading_system.py:219` | Backtest entrypoint | Current sig: `run(self, print_summary: bool = True) -> None`. Add `on_tick: Optional[Callable] = None`, default None = byte-exact. |
| `TradingSystem._run_backtest` | `itrader/trading_system/backtest_trading_system.py:192` | The `for time_event in self.time_generator` loop | Hook lands here: after `process_events()` + `record_metrics`, call `on_tick(self, time_event)` if not None (see Code Examples). |
| `OrderHandler.modify_order` | `itrader/order_handler/order_handler.py:121` | Operator re-price/re-size | `modify_order(order_id, new_price=None, new_quantity=None, portfolio_id=None, reason=...) -> bool`. Pass `order.id` (UUID) as `order_id`. |
| `OrderHandler.cancel_order` | `itrader/order_handler/order_handler.py:158` | Operator cancel | `cancel_order(order_id, portfolio_id=None, reason=...) -> bool`. Pass `order.id`. |
| `OrderHandler.get_active_orders` | `itrader/order_handler/order_handler.py:258` | Predicate resolution (D-07) | `get_active_orders(portfolio_id=None) -> List[Order]` (PENDING + PARTIALLY_FILLED). |
| `OrderHandler.get_orders_by_ticker` | `itrader/order_handler/order_handler.py:290` | Predicate resolution (D-07) | `get_orders_by_ticker(ticker, portfolio_id=None) -> List[Order]`. |
| `OrderHandler.get_orders_by_status` | `itrader/order_handler/order_handler.py:240` | Snapshot / predicate | `get_orders_by_status(status: OrderStatus, portfolio_id=None) -> List[Order]`. |
| `Order` entity | `itrader/order_handler/order.py:33` | Snapshot source fields | See Snapshot section below for the exact deterministic-vs-excluded field split. |
| `itrader.reporting.frames` | `itrader/reporting/frames.py` | Serializer family the snapshot joins | `build_trade_log(portfolio)`, `TRADE_COLUMNS`; the snapshot serializer mirrors this style. |
| `itrader.reporting.summary` | `itrader/reporting/summary.py` | `FLOAT_FORMAT="%.10f"`, `build_summary` | Snapshot CSV uses the SAME `FLOAT_FORMAT` so the round-trip diff is apples-to-apples. |

### Supporting (emitter construction primitives)
| API | Location | Use |
|-----|----------|-----|
| `Strategy.buy()/sell()` | `itrader/strategy_handler/base.py:131,149` | Sugar: `buy(ticker, sl=, tp=, exit_fraction=)` → `SignalIntent` (sl/tp via `to_money`). |
| `BaseStrategyConfig` | `itrader/strategy_handler/config.py:38` | Carries `order_type: OrderType` (default MARKET), `sizing_policy` (REQUIRED), `direction`, `allow_increase`, `max_positions`. Frozen. The emitter sets `order_type` here to choose MARKET/LIMIT/STOP entries (D-03). |
| `FractionOfCash` / `FixedQuantity` | `itrader/core/sizing.py` | Sizing policy. The canary uses `FractionOfCash(Decimal("0.95"))`. For hand-derivable fixed-qty scenarios, `FixedQuantity` may make math cleaner (Claude's discretion). |
| `OrderType` enum | `itrader/core/enums/order.py` | `MARKET / LIMIT / STOP`. Set on `BaseStrategyConfig.order_type`. |

**Installation:** None. No `npm`/`pip` install. (No Package Legitimacy Audit needed — no external packages added.)

## Architecture Patterns

### System Architecture Diagram (the Phase 6 scenario path)

```
ScenarioSpec (leaf scenario.py)
  ├─ data={ticker: bars.csv}  ─────────────────►  CsvPriceStore (loads contrived bars, pinned to spec.start/end)
  ├─ strategies=[ScriptedEmitter(...)]
  ├─ actions=[Action(bar_date, kind, predicate, ...)]  (MATCH-07 only)
  └─ exchange=None  (zero-fee/zero-slippage)
                   │
   run_scenario ───┤
                   ▼
   _build_and_run(spec) ──► TradingSystem(exchange="csv", start/end, csv_paths)
                              │
                              ▼  system.run(print_summary=False, on_tick=harness_hook)
   ┌──────────────────────────────────────────────────────────────────────┐
   │ _run_backtest loop, per time_event:                                    │
   │   queue.put(TimeEvent) → process_events():                             │
   │     TIME  → feed.generate_bar_event → BarEvent                         │
   │     BAR   → execution.on_market_data → MatchingEngine.on_bar           │
   │              (resting orders fill/OCO-cancel → FillEvent)              │
   │           → strategies.calculate_signals → emitter fires SignalIntent  │
   │     SIGNAL→ order_handler.on_signal → OrderManager → OrderEvent(NEW)   │
   │     ORDER → execution.on_order → MatchingEngine.submit (rests)         │
   │     FILL  → portfolio.on_fill + order_handler.on_fill (mirror reconcile)│
   │   record_metrics(time_event.time)                                      │
   │   on_tick(system, time_event)  ◄── harness resolves actions by bar-date│
   │        → OrderHandler.modify_order/cancel_order(order.id, ...)         │
   └──────────────────────────────────────────────────────────────────────┘
                              │ (after run)
                              ▼
   _assemble → trades / equity / summary  (+ NEW: orders-snapshot from order mirror query)
                              ▼
   _freeze (--freeze)  OR  _diff (exact, no-tolerance)  vs leaf golden/
```

### Recommended scenario leaf structure (clone of the canary)
```
tests/e2e/matching/<cluster>/<scenario_name>/
├── __init__.py
├── bars.csv          # contrived OHLCV (Open time, Open, High, Low, Close, Volume)
├── scenario.py       # ScenarioSpec SCENARIO + VERIFY hand-derivation docstring
├── test_scenario.py  # one line: run_scenario(HERE)
└── golden/
    ├── trades.csv     # always (may be empty for never-fill / cancel)
    ├── summary.json   # always
    └── orders.csv     # OPT-IN (MATCH-04/05/06/07/08) — presence = assertion
```

### Pattern 1: Oracle-inert `on_tick` hook
**What:** A default-`None` callable invoked once per tick after event processing. `None` = byte-exact current behavior (guarded by `test_backtest_oracle.py`).
**When to use:** MATCH-07 operator injection. All other scenarios leave `actions=()` so `on_tick` is never wired.
**Example:** see Code Examples below.

### Pattern 2: Predicate-resolved operator target (D-07)
**What:** The `actions` timeline names its target by `(ticker, status)` or "the sole resting order", resolved at the target bar via `get_active_orders`/`get_orders_by_ticker`, then `modify_order(order.id, ...)`.
**Why:** `Order.id` is a UUIDv7 — never literal. `InMemoryOrderStorage.get_order_by_id` REQUIRES a `uuid.UUID` key (`if not isinstance(order_id, uuid.UUID): return None`), so the operator MUST pass the resolved `order.id`, not a synthetic int.

### Pattern 3: Snapshot from the order mirror, business columns only (D-08)
**What:** After `run()`, query `order_handler.get_orders_by_ticker(ticker, portfolio_id)` (or `get_orders_by_status` per status) to get every `Order`, serialize the deterministic business columns, derive a logical ENTRY/SL/TP role from `parent_order_id`/`child_order_ids` WITHOUT emitting UUIDs.

### Anti-Patterns to Avoid
- **Referencing `Order.id` literally in a scenario or golden** — it is a non-deterministic UUIDv7. Resolve by predicate (D-07); exclude from goldens (D-08).
- **Authoring a ticker other than `BTCUSD` without widening supported symbols** — `SimulatedExchange.validate_order` rejects any ticker not in `_supported_symbols`; `ExecutionHandler.init_exchanges` only adds `BTCUSD` to the default `*USDT` preset (see Pitfall 1). A different ticker silently REFUSES every order.
- **Editing `tests/e2e/conftest.py` or the shared emitter in a parallel leaf plan** — shared infra is committed FIRST (D-13); parallel leaves edit ONLY their own folder.
- **Injecting raw `OrderEvent(MODIFY/CANCEL)` onto the queue** — skips `OrderManager` validation (rejected by D-05). Use the `OrderHandler` API.
- **Blind multi-scenario `--freeze`** — the fixture mechanically refuses `--freeze` when >1 test is selected (`conftest.py:393`).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Per-scenario strategy class | ~10 near-duplicate strategy subclasses | ONE `ScriptedEmitter` (D-01) parametrized by date→action/sl/tp | Phase 4 already proved the single-strategy pattern; avoids 10x duplication. |
| Golden diff machinery | A new compare function | The harness `_diff_frame`/`_roundtrip` mechanic | Exact no-tolerance `assert_frame_equal` already battle-tested; the snapshot reuses it. |
| Trade-log/summary serialization | A parallel serializer | `itrader.reporting.{frames,summary}` (already wired into `_assemble`) | One serialization path — oracle and harness cannot drift (D-16). |
| Operator MODIFY/CANCEL plumbing | A test-only modify path | `OrderHandler.modify_order`/`cancel_order` (the real API) | D-05 faithfulness: genuine round-trip through `OrderManager` + matching book. |
| Order-mirror queries for the snapshot | A new accessor | `get_orders_by_ticker`/`get_orders_by_status`/`get_active_orders` | The full query surface already exists (D-07 needs no new methods). |
| Float-vs-Decimal diff normalization | Manual rounding | `_roundtrip(frame, columns)` with `FLOAT_FORMAT` | Normalizes both sides to the same 10-dp float repr (conftest.py:321). |

**Key insight:** Every mechanism Phase 6 needs except the four named shared-infra pieces already exists and is exercised by the Phase 4 canary. The phase's risk is in *contrived-bar authoring correctness* (hand-derivation), not in building machinery.

## Engine behavior reference (hand-derivation source for VERIFY notes)

These are the EXACT formulas from `matching_engine._evaluate` (`itrader/execution_handler/matching_engine.py:137-182`). Author bars so each fill price is a round number.

| Order | Side | Trigger condition | Fill price |
|-------|------|-------------------|------------|
| MARKET | any | always (next bar it sees) | `open` |
| STOP | SELL (stop-loss on long) | `low <= trigger` | `min(open, trigger)` — pessimistic gap-down |
| STOP | BUY (stop entry / cover) | `high >= trigger` | `max(open, trigger)` — pessimistic gap-up |
| LIMIT | SELL (take-profit) | `open >= trigger` | `open` (gap-through, better) |
| LIMIT | SELL (take-profit) | else `high >= trigger` | `trigger` (in-bar touch) |
| LIMIT | BUY (limit entry) | `open <= trigger` | `open` (gap-through, better) |
| LIMIT | BUY (limit entry) | else `low <= trigger` | `trigger` (in-bar touch) |

**Two-pass `on_bar` (matching_engine.py:184):**
- Pass 1: parents/standalone (`parent_order_id is None`) fill independently and leave the book.
- Pass 2: bracket children whose parent NO LONGER rests. A child whose parent still rests is **dormant** (CR-01 gate).
- A parent filling THIS bar unlocks its children against the SAME bar's high/low (`fills` list keeps parents-before-children order).
- Per bracket, at most ONE child fills per bar; if both STOP and LIMIT are candidates, STOP wins (`_pick_bracket_winner`, matching_engine.py:302).
- When a leg fills, all other siblings of that bracket are OCO-cancelled (`CancelDecision`) — even if they did not trigger.

**Entry price provenance (D-02):** `OrderManager._build_primary_order` (order_manager.py:509) sets a LIMIT/STOP entry's `price` from `signal_event.price`, which `StrategiesHandler` sets to `to_money(bar.close)` of the DECISION bar (strategies_handler.py:141). So a LIMIT/STOP *entry* rests at the decision-bar close. To author a specific entry trigger, set that bar's `Close` to the trigger and shape the following bars.

**Bracket SL/TP prices (D-15):** `_assemble_bracket_and_emit` (order_manager.py:556) reads `signal_event.stop_loss`/`take_profit` (the explicit Decimal levels from `intent`); when either is `>0` the `sltp_policy` is ignored entirely (order_manager.py:613). SL child = `new_stop_order`, TP child = `new_limit_order`, both with the inverted action, both linked `parent_order_id = primary.id`.

**Fill stamping (next-bar-open):** `SimulatedExchange._emit_fill` stamps `FillEvent.time = bar.time` of the matching bar (simulated.py:179). An order decided at tick T fills with `time = T+1tf`. `attach_slippage` (summary.py:42) computes `fill_price - decision-bar close` into `slippage_entry`/`slippage_exit` columns — frozen in `trades.csv`, so VERIFY notes must hand-derive them (the canary derives 6.0/6.0).

## Orders-snapshot golden (D-08/D-09) — concrete column + role design

**`Order` entity fields** (`itrader/order_handler/order.py:44-80`):

| Field | Type | Snapshot disposition |
|-------|------|----------------------|
| `ticker` | str | INCLUDE (business) |
| `type` | `OrderType` (MARKET/LIMIT/STOP) | INCLUDE as `.name` (business) |
| `action` | str ("BUY"/"SELL") | INCLUDE (business) |
| `status` | `OrderStatus` | INCLUDE as `.name` — final status (business) |
| `price` | Decimal | INCLUDE (business; serialize via `FLOAT_FORMAT`) |
| `quantity` | Decimal | INCLUDE (business) |
| `filled_quantity` | Decimal | INCLUDE (business) |
| `time` | datetime (event-derived business time) | INCLUDE (business time; deterministic) |
| `parent_order_id` | `OrderId` (UUID) or None | EXCLUDE raw — DERIVE role from it |
| `child_order_ids` | list[UUID] | EXCLUDE raw — DERIVE role from it |
| `id` | UUIDv7 | **EXCLUDE** (non-deterministic) |
| `created_at` / `updated_at` | datetime | **EXCLUDE** (D-08 — though note these are event-derived from `time`, D-08 still excludes them) |
| `filled_at` / `cancelled_at` | datetime | EXCLUDE (event-derived but D-08 excludes lifecycle timestamps) |
| `event_id` | (on OrderEvent, not Order) | N/A — Order entity has no `event_id` |

**ENTRY/SL/TP role derivation (no UUID leak):** for each order in the snapshot set:
- `parent_order_id is None` AND `child_order_ids` non-empty → role = **ENTRY** (the bracket parent).
- `parent_order_id is None` AND no children → role = **STANDALONE** (a non-bracket order, e.g. MATCH-07/08 single resting order).
- `parent_order_id is not None` AND `type == STOP` → role = **SL**.
- `parent_order_id is not None` AND `type == LIMIT` → role = **TP**.

This yields a stable `role` column from the entity's own type + linkage flags, never emitting a UUID. (A non-bracket STOP/LIMIT *entry* — MATCH-02/03 — has no children and no parent → STANDALONE; those scenarios freeze trades, not the snapshot, per D-09, so the role taxonomy is unambiguous in practice.)

**Deterministic sort key (Claude's discretion, recommend):** sort by `(role, type.name, action, price)` — all business fields, fully deterministic, independent of UUID/insertion order. (`role` ordering ENTRY < SL < TP < STANDALONE gives a readable, stable layout.)

**Snapshot source query:** after `run()`, `order_handler.get_orders_by_ticker(spec.ticker, portfolio_id)` returns ALL orders for the ticker (terminal orders stay in storage — `InMemoryOrderStorage` keeps filled/cancelled/rejected for audit, in_memory_storage.py:31). This is the complete mirror for the snapshot.

**Status precision (D-10 correction):** there is **NO `OrderStatus.ACTIVE`**. The enum is `PENDING PARTIALLY_FILLED FILLED CANCELLED REJECTED EXPIRED` (order.py enum, core/enums/order.py:33). MATCH-08's "stays ACTIVE/resting" is `OrderStatus.PENDING` in the mirror. The snapshot must freeze `PENDING` for the never-filled order — the planner/author must write `PENDING`, not `ACTIVE`, in the golden.

## Common Pitfalls

### Pitfall 1: Non-BTCUSD ticker silently REFUSES every order
**What goes wrong:** A scenario authored on e.g. `ETHUSD` or a synthetic ticker gets `FillEvent(REFUSED)` for every order, zero trades, and a confusing empty golden.
**Why it happens:** `SimulatedExchange.validate_order` (simulated.py:382) checks `event.ticker in self._supported_symbols`. The default preset is `{"BTCUSDT","ETHUSDT","ADAUSDT","DOTUSDT","SOLUSDT"}` (exchange.py:107). `ExecutionHandler.init_exchanges` (execution_handler.py:109) adds ONLY `BTCUSD` to the instance set.
**How to avoid:** Use `BTCUSD` as the ticker for all Phase 6 scenarios (matches the canary). If a scenario genuinely needs another ticker, the supported set would need widening — flag to the planner as out-of-scope plumbing. **Recommendation: every leaf uses `BTCUSD`.**
**Warning signs:** Empty `trades.csv` + an order stuck `REJECTED` in the mirror.

### Pitfall 2: `--freeze` refuses >1 selected test
**What goes wrong:** `pytest tests/e2e --freeze` fails immediately.
**Why it happens:** Deliberate (conftest.py:393) — enforces one-scenario-at-a-time hand-verify discipline (D-12).
**How to avoid:** Freeze with a `-k`/path selector narrowing to exactly one scenario, after hand-verifying its VERIFY note. The D-12 batched-at-end workflow freezes per-cluster, one leaf at a time.

### Pitfall 3: STOP/LIMIT *entry* needs `order_type` on the config, not on the intent
**What goes wrong:** Author tries to make a LIMIT/STOP entry by passing something on `buy()`/`sell()` — there is no such field (`SignalIntent` has NO `order_type`, NO entry price — sizing.py:243 TODO).
**Why it happens:** `order_type` is per strategy INSTANCE (`SignalEvent.order_type = strategy.order_type`, strategies_handler.py:138, sourced from `BaseStrategyConfig.order_type`).
**How to avoid:** The emitter sets `order_type=OrderType.LIMIT` (or `STOP`) in its `BaseStrategyConfig` for MATCH-02/03 entry scenarios. The entry then rests at the decision-bar close (D-02). Bracket children (MATCH-04/05/06) get their STOP/LIMIT types from the assembler regardless of entry type — a MARKET-entry bracket still works (D-03).

### Pitfall 4: `filterwarnings=["error"]` + strict markers
**What goes wrong:** Any unexpected warning fails the test; an undeclared marker fails collection.
**Why it happens:** `pyproject.toml` sets `filterwarnings=["error"]`, `--strict-markers`, `--strict-config`. Only `unit/integration/slow/...` markers declared; `e2e` is registered and folder-auto-marked (Phase 4 E2E-01).
**How to avoid:** Author bars/strategies warning-clean (the canary is). Use pydantic v2 decorators only. New leaves under `tests/e2e/matching/` inherit the `e2e` auto-mark — do not hand-add markers.

### Pitfall 5: Module-scoped scenario import collision
**What goes wrong:** Two leaves with the same folder name in different parents could shadow each other.
**Why it happens / avoided:** Already handled — `_load_spec` (conftest.py:107) derives a unique `sys.modules` name from the full leaf path. Authors just need DISTINCT leaf paths; same-named leaves in different clusters are safe.

### Pitfall 6: The decision bar vs the fill bar (off-by-one)
**What goes wrong:** VERIFY note attributes a fill to the wrong bar.
**Why it happens:** Next-bar-open convention — an order DECIDED at tick T fills at the OPEN of the bar stamped T+1tf (bar_feed.py rule 5). The last dataset bar can never fill (rule 7).
**How to avoid:** In every VERIFY note, draw the bar table and explicitly mark decision bar → fill bar (the canary does this). Ensure a scenario that must fill leaves at least one bar AFTER the trigger bar.

## Code Examples

### `on_tick` hook on the run loop (D-06)
```python
# itrader/trading_system/backtest_trading_system.py
# run() — add the parameter, thread it down (oracle-inert: default None)
def run(self, print_summary: bool = True,
        on_tick: Optional[Callable[["TradingSystem", Any], None]] = None) -> None:
    self._initialise_backtest_session()
    self._run_backtest(on_tick=on_tick)
    if print_summary:
        self._print_metrics_summary()

# _run_backtest — invoke after process_events + record_metrics (post-bar, mirrors
# the live loop yielding control to an external actor each iteration, D-06)
def _run_backtest(self, on_tick: Optional[Callable] = None) -> None:
    for time_event in self.time_generator:
        self.clock.set_time(time_event.time)
        self.global_queue.put(time_event)
        self.event_handler.process_events()
        for portfolio in self.portfolio_handler.get_active_portfolios():
            portfolio.record_metrics(time_event.time)
        if on_tick is not None:                 # default None = byte-exact (oracle-dark)
            on_tick(self, time_event)
```
**Oracle-darkness:** `on_tick=None` adds one `if … is not None` per tick and changes no bytes — `test_backtest_oracle.py` (which calls `scripts/run_backtest.py::main`, never passing `on_tick`) stays green. (Source: existing loop, backtest_trading_system.py:203-214.)

### Harness translating `actions` → operator calls (D-07)
```python
# tests/e2e/conftest.py — inside _build_and_run, build the on_tick from spec.actions
def _make_on_tick(spec, portfolio_id):
    actions = getattr(spec, "actions", ())
    if not actions:
        return None  # oracle-inert: no actions → no hook
    by_date = {}  # "YYYY-MM-DD" → list[Action]
    for a in actions:
        by_date.setdefault(a.bar_date, []).append(a)
    def on_tick(system, time_event):
        key = time_event.time.strftime("%Y-%m-%d")
        for a in by_date.get(key, []):
            # D-07 predicate resolution via the EXISTING query API
            candidates = system.order_handler.get_orders_by_ticker(a.ticker, portfolio_id)
            resting = [o for o in candidates if o.status == OrderStatus.PENDING]
            order = resting[0]  # "the sole resting order" predicate (assert len==1 in author note)
            if a.kind == "cancel":
                system.order_handler.cancel_order(order.id, portfolio_id)
            elif a.kind == "modify":
                system.order_handler.modify_order(
                    order.id, new_price=a.new_price, new_quantity=a.new_quantity,
                    portfolio_id=portfolio_id)
    return on_tick
```
**Note:** `order.id` (UUIDv7) is passed — `InMemoryOrderStorage.get_order_by_id` requires a `uuid.UUID` (in_memory_storage.py:96). Resolving by predicate then passing `order.id` is the only correct path. (Exact `Action` dataclass shape is Claude's discretion per D-06.)

### Orders-snapshot serializer (D-08), joining the frames family
```python
# itrader/reporting/frames.py (or a sibling reporting module) — mirror build_trade_log style
ORDER_SNAPSHOT_COLUMNS = [
    "role", "ticker", "order_type", "action", "status",
    "price", "quantity", "filled_quantity", "time",
]

def _order_role(order) -> str:
    if order.parent_order_id is None:
        return "ENTRY" if order.child_order_ids else "STANDALONE"
    return "SL" if order.type is OrderType.STOP else "TP"

def build_orders_snapshot(orders) -> pd.DataFrame:
    rows = [{
        "role": _order_role(o),
        "ticker": o.ticker,
        "order_type": o.type.name,
        "action": o.action,
        "status": o.status.name,        # PENDING for never-filled (NOT "ACTIVE")
        "price": float(o.price),         # Decimal→float at the serialization edge
        "quantity": float(o.quantity),
        "filled_quantity": float(o.filled_quantity),
        "time": o.time,
    } for o in orders]
    frame = pd.DataFrame(rows, columns=ORDER_SNAPSHOT_COLUMNS)
    if not frame.empty:
        frame = frame.sort_values(["role", "order_type", "action", "price"]).reset_index(drop=True)
    return frame
```
Then `_freeze`/`_diff` gain an opt-in `orders.csv` branch identical to the `equity.csv` opt-in (conftest.py:314/359): write only on `--freeze`, diff only if present. The snapshot CSV uses `FLOAT_FORMAT` so `_roundtrip` normalizes both sides.

## Runtime State Inventory

> This is a test-authoring phase — no rename/migration. Inventory included for completeness.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — in-memory order storage + in-memory portfolio per run; no persistent datastore on the backtest path. | None — verified: `OrderStorageFactory.create('backtest')` → `InMemoryOrderStorage` (backtest_trading_system.py:131). |
| Live service config | None — offline backtest, no external services. | None — verified: `exchange="csv"` resolves to the in-process `SimulatedExchange`. |
| OS-registered state | None — pytest-driven, no OS registration. | None. |
| Secrets/env vars | None — no credentials on the offline CSV path. | None. |
| Build artifacts | None new — no package rename; `tests/e2e/` is pure test code. | None. |

## Environment Availability

> This phase is pure Python test code with no new external dependencies.

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| pytest | running scenarios | ✓ | ^8.4.2 (pyc shows 9.0.3 cache) | — |
| pandas | frame diff + bars | ✓ | ^2.3.3 | — |
| Phase 4 harness | `run_scenario`, `--freeze` | ✓ | committed (`tests/e2e/conftest.py`) | — |
| `MatchingEngine` etc. | system under test | ✓ | committed | — |

**Missing dependencies with no fallback:** None.
**Missing dependencies with fallback:** None.

## Validation Architecture

> `nyquist_validation` not found as `false` in config — section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest ^8.4.2 |
| Config file | `pyproject.toml [tool.pytest.ini_options]` |
| Quick run command | `poetry run pytest tests/e2e/matching/<cluster>/<scenario> -v` (single leaf) |
| Full suite command | `make test-e2e` (or `poetry run pytest tests/e2e -v`) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MATCH-01 | market next-bar-open | e2e scenario | `pytest tests/e2e/matching/entries/market_next_open -x` | ❌ Wave 0 |
| MATCH-02 | limit touch + gap-through (2 leaves) | e2e scenario | `pytest tests/e2e/matching/entries/limit_* -x` | ❌ Wave 0 |
| MATCH-03 | stop gap-down + gap-up (2 leaves) | e2e scenario | `pytest tests/e2e/matching/entries/stop_* -x` | ❌ Wave 0 |
| MATCH-04 | bracket OCO lifecycle | e2e scenario (+orders.csv) | `pytest tests/e2e/matching/brackets/oco_lifecycle -x` | ❌ Wave 0 |
| MATCH-05 | STOP-beats-LIMIT same bar | e2e scenario (+orders.csv) | `pytest tests/e2e/matching/brackets/stop_beats_limit -x` | ❌ Wave 0 |
| MATCH-06 | gap clean-through (3 leaves) | e2e scenario (+orders.csv) | `pytest tests/e2e/matching/gaps/* -x` | ❌ Wave 0 |
| MATCH-07 | modify/cancel round-trip | e2e scenario (+orders.csv, +actions) | `pytest tests/e2e/matching/operator/* -x` | ❌ Wave 0 |
| MATCH-08 | far limit never fills | e2e scenario (+orders.csv) | `pytest tests/e2e/matching/never_fill -x` | ❌ Wave 0 |
| oracle | shared infra stays oracle-dark | integration guard | `pytest tests/integration/test_backtest_oracle.py -x` | ✅ exists |

### Sampling Rate
- **Per task commit:** the single leaf's `pytest tests/e2e/matching/<leaf>` (sub-second).
- **Per wave merge:** `make test-e2e` (all leaves) + `pytest tests/integration/test_backtest_oracle.py` (oracle-dark guard for shared infra).
- **Phase gate:** full e2e suite green + oracle green before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `tests/e2e/strategies/scripted_emitter.py` — the generic D-01 emitter (date-keyed, parametrized action/sl/tp/exit_fraction, configurable `order_type`).
- [ ] `on_tick` hook on `TradingSystem.run`/`_run_backtest` (D-06) — default None, oracle-dark.
- [ ] `ScenarioSpec.actions` field + `Action` dataclass shape (D-06) — added per-leaf (the spec is defined per-leaf, not shared; the foundational plan defines the canonical copy-template).
- [ ] orders-snapshot serializer (`build_orders_snapshot` + `ORDER_SNAPSHOT_COLUMNS`) in `itrader.reporting` + `_freeze`/`_diff` opt-in `orders.csv` wiring in `conftest.py` (D-08).
- [ ] MATCH-01 proof scenario authored + hand-verified + frozen (D-13).
- [ ] The D-13 foundational plan must re-run `tests/integration/test_backtest_oracle.py` to prove the `on_tick` change is byte-exact.

## Security Domain

> `security_enforcement` not configured as `false`. This phase adds only offline test code with no auth/session/network/crypto/input surface; ASVS categories are not engaged.

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | — (offline backtest, no auth) |
| V3 Session Management | no | — |
| V4 Access Control | no | — |
| V5 Input Validation | no | Contrived CSVs are trusted test fixtures; `CsvPriceStore` already validates the kline header (`MalformedDataError`). |
| V6 Cryptography | no | — |

No threat patterns engaged: the only "untrusted input" is hand-authored test data the author controls. The relevant *correctness* guard (not security) is `filterwarnings=["error"]` + the oracle-dark gate.

## State of the Art

Not applicable — this is an internal-codebase coverage phase, not a library-selection task. No external "current vs old approach" axis exists. The relevant currency facts:
- The matching engine is the post-M5b/Phase-4 implementation (Decimal-native, two-pass `on_bar`, CR-01 parent-filled gate) — all committed and current.
- The Phase 4 E2E harness is the current, committed scenario framework; Phase 5 (strategy interface hardening) is complete, so `BaseStrategyConfig`/`SignalIntent` are the current contracts.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Recommended snapshot column set / sort key (`role,type,action,price`) is acceptable | Snapshot golden | Low — explicitly Claude's discretion (D-08); planner/author may adjust. |
| A2 | `on_tick` invoked AFTER `process_events`+`record_metrics` (post-bar) is the right placement | Code Examples | Low — mirrors live external-actor timing (D-06); placement is discretion. Author must confirm the modify/cancel lands before the NEXT bar's matching, which post-bar placement guarantees. |
| A3 | `Action` dataclass exact shape is the author's to define | `actions` timeline | Low — D-06 explicitly leaves shape to discretion. |
| A4 | `FixedQuantity` may yield cleaner hand-derivation than `FractionOfCash` for some leaves | Supporting stack | Low — sizing policy choice is discretion; either is valid and hand-derivable. |

**Note:** All HIGH-impact claims (engine fill formulas, API signatures, supported-symbol gap, no-`ACTIVE`-status, UUID-keyed storage) are VERIFIED against read source, not assumed.

## Open Questions (RESOLVED)

1. **Does any MATCH leaf require a STOP-entry that is also a bracket parent?** — **RESOLVED: No.**
   - What we know: MATCH-03 is a STOP *entry* (standalone, `order_type=STOP`). MATCH-04/05/06 brackets typically use a MARKET entry + SL/TP children (D-03 confirms a MARKET-entry bracket works).
   - **Resolution:** Plans 03/04/05 use MARKET-entry brackets (snapshot golden) and Plan 02 keeps MATCH-03 as standalone STOP entries (trades golden). No leaf uses a STOP-entry that is also a bracket parent — cleanest separation, fewest moving parts per leaf (D-11).

2. **MODIFY re-price vs re-size — one leaf or two?** — **RESOLVED: Two (plus one cancel) = three operator leaves.**
   - What we know: D-06 discretion ("Whether MODIFY scenarios need separate re-price vs re-size leaves"). The engine's `modify` handles both via `dataclasses.replace` (matching_engine.py:103).
   - **Resolution:** Plan 05 authors three operator leaves per D-11 one-shape-per-leaf — `cancel`, `modify_reprice`, `modify_resize` — each driven by its own `actions` timeline.

## GAP FINDINGS (highest-value for the planner)

These are places where the locked decisions or requirement wording assume behavior the source does NOT literally have. The planner must address each:

1. **No `OrderStatus.ACTIVE` exists (affects D-10 / MATCH-08).** The enum is `PENDING PARTIALLY_FILLED FILLED CANCELLED REJECTED EXPIRED` (core/enums/order.py:33). CONTEXT D-10 says the order "stays ACTIVE/resting" — in the mirror this is `OrderStatus.PENDING`. The MATCH-08 snapshot golden must freeze `PENDING`, and VERIFY notes must say PENDING, not ACTIVE. **Not a blocker — a naming precision the author must get right or the golden will be wrong.**

2. **`OrderHandler.modify_order`/`cancel_order` declare `order_id: int` but storage is UUID-keyed.** The signatures type `order_id` as `int` (order_handler.py:121/158), but `InMemoryOrderStorage.get_order_by_id` returns `None` for any non-`uuid.UUID` key (in_memory_storage.py:96). The operator MUST pass the resolved `order.id` (a real UUID) — which works at runtime (the `int` annotation is a known carry-over, see the `cast(int, ...)` bridges in order_manager.py:224). **Not a blocker for the harness (it passes `order.id`), but the planner should NOT introduce literal int ids.** `mypy --strict` is scoped to `itrader` only (`files=["itrader"]`), so the harness passing a UUID where the annotation says `int` is not gate-checked — but the planner should pass `order.id` regardless.

3. **Ticker is effectively hardwired to `BTCUSD` on the backtest path.** `validate_order` rejects unsupported symbols; only `BTCUSD` is added to the default preset (execution_handler.py:109). Every Phase 6 leaf must use `BTCUSD`. Using another ticker silently REFUSES all orders (Pitfall 1). **Not a blocker — a constraint the planner must encode: all leaves use `BTCUSD`.**

4. **`ScenarioSpec` is defined PER-LEAF, not in a shared module.** The canary defines `ScenarioSpec`/`PortfolioSpec` inside its own `scenario.py` (scenario.py:104-138). Adding `actions` means the foundational plan must establish the canonical copy-template that every Phase 6 leaf clones (or the dataclasses must be promoted to a shared module). **The planner must decide: promote `ScenarioSpec`+`Action` to a shared `tests/e2e/` module (cleaner, but touches the shared-infra contract), OR keep per-leaf and define the `actions`-bearing copy-template in the D-13 foundational plan.** This is a real structural decision the harness's per-leaf design surfaces. Recommendation: promote `ScenarioSpec`/`PortfolioSpec`/`Action` to a shared `tests/e2e/scenario_spec.py` during the foundational plan (D-13) — it is shared infra by nature, committed first, parallel-safe thereafter.

5. **`SimulatedExchange.validate_order` rejects `quantity > max_order_size` / `< min_order_size`.** The default limits come from the preset (`_max_order_size`/`_min_order_size`, simulated.py:99-100). For `FractionOfCash(0.95)` on $10k at low contrived prices (e.g. ~100), quantity ≈ 95 units — well within typical limits, and the canary passes. But a scenario with a very low contrived price + large cash could size a quantity that trips `max_order_size`. **The author must keep contrived prices in a range where the resulting quantity stays within the preset limits** (the canary's prices 100-150 are safe). Flag: if a leaf needs extreme prices, verify against `get_exchange_preset('default').limits`.

## Sources

### Primary (HIGH confidence — read source this session)
- `tests/e2e/conftest.py` — `run_scenario`, `_build_and_run`, `_freeze`/`_diff`, `_roundtrip`, `--freeze` enforcement.
- `tests/e2e/strategies/single_market_buy.py` — emitter template to generalize.
- `tests/e2e/smoke/single_market_buy/{scenario.py,test_scenario.py,bars.csv}` — copy-template + VERIFY note + contrived-bar format.
- `tests/integration/test_backtest_oracle.py` — the oracle-dark guard + exact-diff mechanic.
- `itrader/trading_system/backtest_trading_system.py` — `run()` (:219), `_run_backtest` (:192) loop, `system.order_handler` reachability.
- `itrader/order_handler/order_handler.py` — `modify_order`/`cancel_order`/query API signatures.
- `itrader/order_handler/order_manager.py` — `_build_primary_order` (:509), `_assemble_bracket_and_emit` (:556), `on_fill` reconcile (:136), `modify_order` (:1089), `cancel_order` (:1177), query pass-through (:1255).
- `itrader/execution_handler/matching_engine.py` — `_evaluate` formulas, two-pass `on_bar`, `_pick_bracket_winner`, OCO `CancelDecision`.
- `itrader/execution_handler/exchanges/simulated.py` — `_emit_fill`, `on_order`, `validate_order`, `on_market_data` (CancelDecision→FillEvent).
- `itrader/execution_handler/execution_handler.py` — `init_exchanges` BTCUSD widening (:109).
- `itrader/order_handler/order.py` — `Order` entity fields, factory methods, `is_terminal`.
- `itrader/order_handler/storage/in_memory_storage.py` — UUID-keyed `get_order_by_id`, query methods.
- `itrader/core/sizing.py` — `SignalIntent` (no order_type/entry price).
- `itrader/strategy_handler/{base.py,config.py,strategies_handler.py}` — `buy()/sell()`, `BaseStrategyConfig.order_type`, `SignalEvent.order_type=strategy.order_type` (:138).
- `itrader/reporting/{frames.py,summary.py}` — `build_trade_log`/`TRADE_COLUMNS`, `FLOAT_FORMAT`, `attach_slippage`.
- `itrader/price_handler/{feed/bar_feed.py,store/csv_store.py}` — bar-timing contract (7 rules), `csv_paths` passthrough.
- `itrader/core/enums/order.py` — `OrderStatus` enum, `VALID_ORDER_TRANSITIONS`, `OrderCommand`.
- `itrader/config/exchange.py` — default `supported_symbols`.

### Secondary / Tertiary
- None — no web sources needed; this is an internal-codebase phase.

## Metadata

**Confidence breakdown:**
- Harness seam & extension points: HIGH — read the full `conftest.py` + canary leaf.
- Matching engine behavior: HIGH — exact formulas read from `_evaluate`.
- Order lifecycle / operator API: HIGH — read both handler and manager signatures + storage keying.
- Snapshot design: HIGH on field availability (read `Order`), MEDIUM on exact column/sort choice (Claude's discretion).
- Gap findings: HIGH — each verified against source line.

**Research date:** 2026-06-09
**Valid until:** 2026-07-09 (stable internal codebase; re-verify only if `matching_engine.py`, `order_manager.py`, or `tests/e2e/conftest.py` change).
