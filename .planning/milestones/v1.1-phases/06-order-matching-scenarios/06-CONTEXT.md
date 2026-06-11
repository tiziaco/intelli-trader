# Phase 6: Order Matching Scenarios - Context

**Gathered:** 2026-06-09
**Status:** Ready for planning

<domain>
## Phase Boundary

Give the resting-order book, bracket/OCO lifecycle, and trigger/gap matching
their **first end-to-end golden coverage** — each a tiny, hand-verified,
contrived-bar scenario authored on the **Phase 4 E2E harness**, then
`--freeze` regression-locked. Eight requirements (MATCH-01..08): MARKET
next-bar-open fills, LIMIT touch vs favorable-gap-through, STOP gap fills,
full bracket OCO lifecycle, same-bar STOP-beats-LIMIT priority, gap
clean-through (incl. past both bracket legs), MODIFY/CANCEL round-trips, and a
far-from-market limit that never fills.

**In scope:**
- ~12-15 self-contained leaf scenarios under `tests/e2e/matching/`, one per
  **distinct fill-shape**, each with contrived `bars.csv` + scripted emitter +
  VERIFY hand-derivation + frozen golden set.
- New SHARED infra (committed FIRST, before the parallel wave): a generic
  parametrized **scripted-emitter** strategy in `tests/e2e/strategies/`; an
  oracle-inert **`on_tick` hook** on the backtest run + an optional `actions`
  timeline on `ScenarioSpec`; an **orders-snapshot** golden serializer + diff
  wiring.
- The MODIFY/CANCEL operator path (MATCH-07) driven by the harness calling the
  REAL `OrderHandler.modify_order`/`cancel_order`.

**Out of scope (own phases / behavior-preserving):**
- Fee/slippage interaction with fills, sizing policies, percent-based SL/TP
  pricing — **Phase 7 (COST/SIZE/SLTP)**. Phase 6 runs zero-fee/zero-slippage.
- Scale-in/scale-out, max_positions, re-entry, cash reservation edges —
  **Phase 8**.
- Multi-ticker/strategy/portfolio, robustness, per-scenario determinism sweep —
  **Phase 9** (ROBUST-04 owns the cross-scenario double-run check).
- Re-baselining the BTCUSD golden oracle — v1.1 is behavior-preserving; every
  Phase-6 shared-infra change must be **oracle-dark** (guarded by
  `tests/integration/test_backtest_oracle.py`). The `on_tick` hook defaults to
  `None` (byte-exact); scenarios never touch the oracle run.

</domain>

<decisions>
## Implementation Decisions

### Test-strategy & price control
- **D-01:** **One generic parametrized scripted-emitter** in
  `tests/e2e/strategies/` — emits a configured `SignalIntent` (action, sl, tp,
  exit_fraction) on configured bars. One hand-verifiable mechanism reused
  across all scenarios (generalizes Phase 4's `SingleMarketBuy`); satisfies
  D-04 (shared, referenced not inlined) and avoids ~10x near-duplicate strategy
  classes.
- **D-02:** **LIMIT/STOP entry price via contrived-bar authoring** — the entry
  rests at the decision-bar close (`signal_event.price`); the scenario sets
  that close to the desired trigger and authors the FOLLOWING bars for
  touch / favorable-gap-through / never-fill. **No signal-contract change** —
  tests the engine exactly as it ships; all MATCH entry shapes are expressible
  since the scenario controls every bar. (SL/TP bracket legs are already
  explicitly priceable via the intent — see D-09.)
- **D-03:** **Emitter mirrors production: `order_type` is per strategy
  instance** (from config; `SignalEvent.order_type = strategy.order_type`,
  strategies_handler.py:138). The per-bar script only picks action + sl/tp/
  exit_fraction. Bracket SL/TP **children** get their STOP/LIMIT types from the
  bracket assembler regardless of the entry type, so a MARKET-entry bracket
  still works.
- **D-04:** **Script keyed by the current bar's DATE** (`bars.index[-1] ==
  "YYYY-MM-DD"`), NOT completed-bar count. More self-documenting against
  `bars.csv`, and sidesteps the `len(bars)`-depends-on-`max_window`/warmup
  gotcha the canary docstring had to explain.

### MODIFY/CANCEL injection (MATCH-07)
- **D-05:** **The harness plays the OPERATOR role** and calls the REAL
  `OrderHandler.modify_order`/`cancel_order` — the genuine round-trip
  (`modify_order` → `OrderEvent(MODIFY)` → exchange → `FillEvent`), faithful to
  MATCH-07 "via the order round-trip". Mirrors live's `TradingInterface`.
  REJECTED: a strategy back-reference (breaks pure-alpha D-12); raw
  `OrderEvent(MODIFY/CANCEL)` queue injection (skips `OrderManager` validation).
- **D-06:** **Seam = a tiny oracle-inert `on_tick` hook** on the backtest run
  (`run(on_tick=None)`, default `None` = byte-exact current behavior).
  `ScenarioSpec` gains an optional **`actions` timeline** (bar-date → modify/
  cancel); the harness translates it into `on_tick` calls. Mirrors how the live
  loop yields control to an external actor each iteration.
- **D-07:** **Scheduled action names its target by PREDICATE** (ticker +
  status, or "the sole resting order"), resolved at the target bar via the
  EXISTING query API (`get_active_orders`/`get_orders_by_ticker`), then
  `modify_order`/`cancel_order(order.id, ...)`. Production-faithful (operator
  lists open orders before amending); reuses the order-mirror query surface; no
  new plumbing. (`Order.id` is a non-deterministic UUIDv7 — never referenced
  literally.)

### Golden artifact scope
- **D-08:** **New OPT-IN orders-snapshot golden artifact** for outcomes with no
  trade row — OCO sibling-cancel (MATCH-04), cancel (MATCH-07), never-fill
  (MATCH-08), bracket child states (MATCH-05/06). A final order-mirror snapshot
  queried post-run, frozen with **deterministic business columns only**
  (ticker, order_type, action, final status, price, quantity, filled_quantity,
  business time); bracket linkage expressed as a **logical ENTRY/SL/TP role**,
  not raw UUID `parent_order_id`/`child_order_ids`; `order_id`/`event_id`/
  `created_at`/`updated_at` (UUID/wall-clock) EXCLUDED. Rows in a deterministic
  sort order (not by UUID). Follows D-05 presence=assertion + D-08 exact-diff
  from Phase 4; keeps the one-line per-folder test.
- **D-09:** **Snapshot is OPT-IN, like `equity.csv`** — frozen only where order
  state is the assertion (MATCH-04/05/06/07/08). Pure fill scenarios
  (MATCH-01/02/03) rely on `trades.csv` + `summary.json`, which already capture
  the fill fully. Minimal, intentional goldens.
- **D-10:** **MATCH-08 asserts AS-IS** — the far-from-market limit stays
  `ACTIVE`/resting in the snapshot, zero trades, run completes cleanly. There
  is no run-end order disposition on the backtest path (`expire_order()`/
  `EXPIRED` exist but are unwired); v1.1 is behavior-preserving, so "handled at
  run end" = graceful completion with the order still resting (see Deferred).

### Granularity & verify-batching
- **D-11:** **One leaf folder per distinct fill-shape** (~12-15 scenarios):
  MATCH-02 → limit-touch + favorable-gap-through; MATCH-03 → stop gap-down +
  gap-up; MATCH-06 → clean-through-stop + clean-through-limit + gap-past-both-
  legs. One hand-verifiable assertion per leaf (D-01/D-05); parallel-safe (each
  leaf edits only its own folder).
- **D-12:** **Batched-at-end verification** — generate ALL scenarios in
  parallel (isolated worktrees) first, decoupled from human review, then
  hand-verify + freeze in **~4 grouped sittings by requirement cluster**
  (entries MATCH-01/02/03; brackets+OCO+priority MATCH-04/05; gaps MATCH-06;
  modify/cancel/never-fill MATCH-07/08). Cluster grouping honors the roadmap's
  "not 12-at-once" without gating generation on the verifier.

### Sequencing, cost isolation & bracket SLTP
- **D-13:** **Foundational plan first = shared infra + ONE proof scenario.** A
  first non-parallel plan builds & commits ALL shared infra (scripted-emitter,
  `on_tick` hook + `ScenarioSpec.actions`, orders-snapshot serializer + diff
  wiring) AND authors the simplest scenario (MATCH-01 market next-bar-open
  regression) through it end-to-end, hand-verified — proving the wiring once
  before the parallel scenario wave. Honors the roadmap precondition (shared
  infra committed first; parallel leaves must not edit shared files).
- **D-14:** **All Phase 6 scenarios run zero-fee / zero-slippage**
  (`exchange=None`, like the Phase 4 canary). Matching isolated from cost;
  fills are clean and hand-derivable (fill = trigger/open, no cost noise). Cost
  interaction is Phase 7's explicit mandate — MATCH stays orthogonal to COST.
- **D-15:** **Brackets declare SL/TP via explicit Decimal levels**
  (`intent.stop_loss`/`take_profit` — the D-13 PRIMARY path: explicit levels
  used verbatim, `sltp_policy` ignored). Directly hand-derivable; exercises the
  matching/OCO lifecycle MATCH-04/05/06 targets. Percent-based `sltp_policy`
  (`PercentFromDecision`/`PercentFromFill`) is Phase 7's (SLTP) mandate — no
  overlap.

### Claude's Discretion
- Exact orders-snapshot column set and the ENTRY/SL/TP role-derivation rule
  (subject to D-08: deterministic business fields, no UUIDs, logical linkage).
- Exact `on_tick` hook signature and how `ScenarioSpec.actions` entries are
  shaped (subject to D-06/D-07: oracle-inert default, predicate-resolved).
- The deterministic sort key for snapshot rows.
- Contrived `bars.csv` authoring per scenario (subject to D-02/D-11:
  hand-derivable, one fill-shape per leaf, real `CsvPriceStore` path).
- Exact `tests/e2e/matching/` sub-directory names/depth (subject to Phase 4
  D-14 subsystem grouping).
- Whether MODIFY scenarios need separate re-price vs re-size leaves (subject to
  D-11 one-shape-per-leaf).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### The harness this phase builds on (Phase 4 — read FIRST)
- `.planning/phases/04-e2e-harness-framework/04-CONTEXT.md` — the full harness
  decision set (D-01 per-folder one-line test → shared `run_scenario` fixture;
  D-02/D-03 `ScenarioSpec` reuses real config; D-04 shared strategies library;
  D-05 diff-what's-frozen; D-06 trades.csv+summary.json default, equity opt-in;
  D-08 exact no-tolerance diff; D-11 CONTRIVED bars not real slices; D-13
  `--freeze` + per-scenario VERIFY note; D-14 subsystem grouping; D-16 shared
  reporting assembly).
- `tests/e2e/conftest.py` — the `run_scenario` harness + `--freeze` mechanism +
  exact-diff machinery (the orders-snapshot diff + `on_tick` driving extend
  this).
- `tests/e2e/strategies/single_market_buy.py` — the scripted-emitter TEMPLATE
  to generalize (D-01); fires by bar-count today (Phase 6 switches to
  date-keying, D-04).
- `tests/e2e/smoke/single_market_buy/scenario.py` — the `ScenarioSpec` +
  VERIFY-note copy-template; the new `actions` field extends this spec.
- `tests/integration/test_backtest_oracle.py` — the byte-exact oracle gate the
  shared-infra changes (esp. `on_tick`) must stay dark against; the
  identity-vs-numeric exact-diff mechanic the snapshot diff reuses.

### Matching engine + order lifecycle (the system under test)
- `itrader/execution_handler/matching_engine.py` — resting book, intrabar
  trigger/gap fills, two-pass `on_bar` (parent-filled CR-01 gate, dormant
  children), same-bar OCO + STOP-beats-LIMIT priority (`_pick_bracket_winner`),
  OCO sibling-cancel (`CancelDecision`, ~283-298), last-bar no-fill edge.
- `itrader/execution_handler/exchanges/simulated.py` — turns `CancelDecision`
  → `FillEvent(CANCELLED)`; applies fee/slippage (off in Phase 6); emits fills.
- `itrader/order_handler/order_manager.py` — `_create_primary_order` (~515-555,
  LIMIT/STOP entry price = `signal_event.price`); `_assemble_bracket_and_emit`
  (~557+, SL/TP child prices from `signal.stop_loss`/`take_profit`, D-13
  precedence); `on_fill` reconcile (~136-232, orphaned-children cleanup);
  `modify_order` (~1089), `cancel_order` (~1177); query API (~1255-1279).
- `itrader/order_handler/order_handler.py` — `modify_order`/`cancel_order`
  (the operator API D-05 calls); `get_active_orders`/`get_orders_by_ticker`/
  `get_orders_by_status`/`get_order_by_id` (the predicate-resolution surface
  D-07).
- `itrader/order_handler/order.py` — `Order` entity: `id` = UUIDv7 (non-det,
  exclude from goldens), `status`/`type`/`action`/`price`/`quantity`/
  `filled_quantity`, `parent_order_id`/`child_order_ids`, `is_terminal`,
  `expire_order()`/`EXPIRED` (unwired — D-10).

### Signal / intent contract
- `itrader/core/sizing.py` — `SignalIntent` (~212): `ticker, action,
  stop_loss, take_profit, exit_fraction, quantity` — NO order_type, NO entry
  price (D-02/D-03 constraints; deferred feature).
- `itrader/strategy_handler/strategies_handler.py` — `SignalEvent`
  construction; `order_type = strategy.order_type` (~138, the per-instance
  constraint D-03).
- `itrader/strategy_handler/base.py` — `buy()`/`sell()` sugar (sl/tp via
  `to_money`); the scripted-emitter subclasses `Strategy`.
- `itrader/strategy_handler/config.py` — `BaseStrategyConfig` (Phase 5; carries
  `order_type`, `sizing_policy`, `direction`, `allow_increase`).

### Run loop + composition (where on_tick lands)
- `itrader/trading_system/backtest_trading_system.py` — `_run_backtest` (~192,
  the `for time_event in time_generator` loop the `on_tick` hook extends);
  `run()` (~219); exposes `order_handler` for the harness operator calls.
- `itrader/reporting/frames.py` — `build_trade_log`/`build_equity_curve`,
  `TRADE_COLUMNS`/`EQUITY_COLUMNS`; the orders-snapshot serializer (D-08) joins
  this family.
- `itrader/trading_system/trading_interface.py` — the LIVE operator bridge D-05
  mirrors (modify/cancel external-actor pattern).

### Phase / requirements / roadmap
- `.planning/ROADMAP.md` §"Phase 6: Order Matching Scenarios" — goal + 4
  success criteria + the parallelization REMINDER (Phase 4 shared infra
  committed first; parallel plans must not edit shared files; hand-verify in
  deliberate batches).
- `.planning/REQUIREMENTS.md` — MATCH-01..08 (lines ~43-50).
- `itrader/price_handler/store/csv_store.py` — `CsvPriceStore` + `csv_paths`
  passthrough (the contrived-CSV data seam, Phase 3/4).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **`run_scenario` harness + `--freeze`** (`tests/e2e/conftest.py`) — the
  full build-run-diff machinery; extended with `on_tick` driving + the
  orders-snapshot diff.
- **`SingleMarketBuy` + its `scenario.py`/`bars.csv`/VERIFY note** — the literal
  copy-template each Phase 6 leaf clones; `SingleMarketBuy` generalizes into the
  scripted-emitter (D-01).
- **Order-mirror query API** (`get_active_orders`/`get_orders_by_ticker`/...) —
  already present; D-07 predicate resolution needs no new methods.
- **Reporting builders** (`itrader.reporting.frames`/`.metrics` + the D-16
  shared summary assembly) — the orders-snapshot serializer mirrors their style
  and joins the same shared serialization path.
- **`MatchingEngine` already implements** OCO sibling-cancel, STOP-beats-LIMIT
  priority, parent-filled gating, gap fills, last-bar no-fill — Phase 6 COVERS
  these, it does not build them.

### Established Patterns
- **Self-contained, parallel-safe leaf folders** (own folder/test/golden) — the
  basis for D-11 fine slicing and the parallel wave.
- **Diff-what's-frozen / presence=assertion / exact no-tolerance diff** — the
  orders snapshot (D-08) follows the same contract.
- **Oracle-dark / behavior-preserving** — `on_tick` default `None` keeps the
  BTCUSD oracle byte-exact (guarded by `test_backtest_oracle.py`).
- **Queue-only reads after run** — the harness reads order mirror + portfolio
  AFTER `run()`; the operator `on_tick` calls are the one sanctioned mid-run
  external-actor seam (modify/cancel is an external API, not a cross-handler
  call).

### Integration Points
- New scripted-emitter (`tests/e2e/strategies/`) ← referenced by every
  scenario's `scenario.py`.
- `on_tick` hook: `TradingSystem._run_backtest`/`run` (production, default-None)
  ↔ `run_scenario` (harness translates `ScenarioSpec.actions` → operator calls
  on `system.order_handler`).
- Orders-snapshot serializer (`itrader.reporting`) ← imported by `run_scenario`
  for the opt-in golden diff.
- `tests/e2e/matching/` leaves ← built on all the above in the parallel wave.

</code_context>

<specifics>
## Specific Ideas

- **Faithfulness over convenience drove every choice.** The user repeatedly
  steered to "test the engine as it ships": contrived-bars over a new entry-
  price field (D-02), the harness playing the real operator over a strategy
  back-channel (D-05), assert MATCH-08 as-is rather than wiring run-end expiry
  (D-10). Coverage phase = exercise existing behavior, not add capability.
- **The pure-alpha (D-12) stance is a deliberate, valued advantage**, not a
  limitation, for a correctness-first deterministic backtest engine — it is
  what makes the golden-master discipline and config-swappable execution
  possible. Order amendment is intentionally an operator concern; strategies
  never amend (even trailing stops are routed engine-side in N+2).
- **Date-keyed scripting** was chosen specifically so VERIFY notes cross-check
  trivially against `bars.csv` dates.

</specifics>

<deferred>
## Deferred Ideas

- **Explicit per-intent limit/stop ENTRY price (and per-intent `order_type`) on
  the signal contract** (`SignalIntent` → `SignalEvent` →
  `Order.new_limit_order`/`new_stop_order`). A real missing PRODUCTION feature:
  strategies cannot place a limit/stop entry at an arbitrary price (hardwired to
  the decision-bar close), and `order_type` is fixed per strategy instance.
  Owner-gated; future milestone. (Phase 6 works around it via contrived bars.)
- **Run-end resting-order disposition / time-in-force.** At backtest end,
  resting orders simply remain `ACTIVE` (no expiry/cancel). `Order.expire_order()`
  / `OrderStatus.EXPIRED` exist but are unwired on the backtest path. Wiring it
  is a result-changing behavior addition — owner-gated, own phase.
- **Strategy-driven order management** (cancel/modify/contingent/order-centric
  styles). Deliberately NOT supported by the pure-alpha contract; most peer
  frameworks (backtrader, nautilus, backtesting.py) allow it. CONTEXT only — not
  a Phase 6 change; revisit only if pivoting to market-making/execution-algo
  styles.

None of these block Phase 6 — discussion otherwise stayed within scope.

</deferred>

---

*Phase: 6-Order Matching Scenarios*
*Context gathered: 2026-06-09*
