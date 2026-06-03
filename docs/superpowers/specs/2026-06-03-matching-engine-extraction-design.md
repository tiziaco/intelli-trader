# Design: Extract matching into the execution layer

**Date:** 2026-06-03
**Status:** Approved (pending spec review)
**Scope:** Backtest-only. Un-fuse order *management* from order *matching*.

## Problem

`OrderManager` currently *is* the matching engine. It consumes `BAR` events
(`order_handler.process_orders_on_market_data` → `order_manager.process_orders_on_market_data`),
evaluates stop/limit trigger conditions, and "fills" orders internally — while
`SimulatedExchange` *independently* fills the same orders with fee/slippage when
it receives the resulting `OrderEvent`. This produces two sources of truth for
fills and fuses backtest-only simulation logic into the venue-agnostic order
handler.

This blocks the longer-term goal: the order handler should behave identically in
backtest and live, with the only difference being *who matches* — the simulated
exchange (backtest) or the real venue (live: Binance, IBKR, Alpaca), behind a
common exchange interface.

### Bugs this design fixes

- **B1** — `OrderEvent.new_order_event` reads `order.order_type`/`order.order_id`,
  which don't exist on `Order` (the fields are `.type`/`.id`). Every event silently
  downgrades to `MARKET` with `order_id=None`.
- **B2** — `cancel_order`/`modify_order` emit an `OrderEvent` that the execution
  handler executes as a fresh market fill (no command/intent on the event, and the
  simulated exchange assumes market). Cancelling books a phantom trade.
- **B3** — Stop/limit triggers fire only when the **close** crosses the level and
  fill at the close, ignoring intrabar high/low. Optimistic backtest results.
- **B4** — Dual source of truth for fills (OrderManager internal fill vs exchange
  fill); `process_market_orders_immediately()`'s generated events are discarded.
- **B5** — OCO is scoped to the whole ticker+portfolio, cancelling unrelated
  protective orders. `parent_order_id`/`child_order_ids` exist but are unused.
- **B6** — Broad `except Exception: return []` in the matching pipeline silently
  drops a whole bar's fills.

(B7 — `Order` lifecycle timestamps use wall-clock `datetime.now()` instead of bar
time — is explicitly **out of scope** here, tracked as a follow-up.)

## Decisions (locked during brainstorming)

1. **Scope:** Full split, backtest-only. Do not build live-exchange infrastructure
   that can't be exercised in tests.
2. **OCO ownership:** The **exchange enforces** OCO atomically (it holds the book);
   the **order handler declares** the abstract bracket group via
   `parent_order_id`/`child_order_ids`. This matches native venue support
   (Binance OCO/OTOCO, IBKR OCA groups, Alpaca `order_class=bracket/oco`) and is
   disconnect-safe. Each future live adapter maps the abstract bracket to its
   venue primitive.
3. **Bar routing:** `BAR` flows via the event queue to
   `execution_handler.on_market_data(bar)` → `exchange.on_market_data()`. No
   cross-domain direct calls; stays true to the queue-only convention.
4. **Trigger realism:** Matching uses intrabar **high/low**, **pessimistic gap
   fills**, and **pessimistic same-bar stop-before-limit priority**. New tests are
   written for this behavior (the old close-based behavior is a bug, not
   characterized).
5. **Structure:** Extract a dedicated, pure `MatchingEngine` composed by
   `SimulatedExchange` (Approach B), not inline in the exchange and not a
   speculative shared module.

## Architecture

Relocate **matching** (resting-order book + trigger evaluation + gap/OCO rules)
out of `OrderManager` into a new pure `MatchingEngine`, composed by
`SimulatedExchange`. `OrderManager` keeps only **order management**: signal→order
translation, the storage mirror, lifecycle, and bracket *declaration*.

## Components & responsibilities

### `MatchingEngine` (new, pure — `itrader/execution_handler/matching_engine.py`)
Holds the resting-order book.

- `submit(order)` — add a resting STOP/LIMIT (or a `next_bar` MARKET); MARKET in
  `immediate` mode is reported as fill-now.
- `cancel(order_id)` — remove a resting order.
- `modify(order_id, new_price=None, new_quantity=None)` — mutate a resting order.
- `on_bar(bar) -> (List[FillDecision], List[CancelDecision])` — evaluate all
  resting orders for the bar's tickers via intrabar high/low, applying gap-fill
  rules and OCO same-bar pessimistic priority; return fills and the OCO siblings
  to cancel.

Trigger rules (per resting order, using the bar's high/low):

| Order | Action | Triggers when | Fill price |
|-------|--------|---------------|------------|
| STOP (stop-loss long) | SELL | `low <= stop` | `min(open, stop)` (gap-aware) |
| STOP (stop short) | BUY | `high >= stop` | `max(open, stop)` (gap-aware) |
| LIMIT (take-profit long) | SELL | `high >= limit` | `limit` |
| LIMIT (take-profit short) | BUY | `low <= limit` | `limit` |

OCO same-bar rule: if one bar's range pierces both a stop and a limit in the same
bracket, **assume the stop filled first** (pessimistic), fill the stop, and emit a
`CancelDecision` for the limit sibling.

Constraints: **no queue, no fee/slippage, no logging side-effects.** Deterministic
and unit-testable. Returns plain decision objects.

### `SimulatedExchange` (refactored)
Composes a `MatchingEngine`. Keeps fee/slippage/failure-sim/validation/metrics/config.

- `on_order(event)`:
  - validate;
  - `command == NEW`: `MARKET` (immediate) → fill now (fee/slippage) → emit
    `FILL(EXECUTED)`; `STOP`/`LIMIT` (or `next_bar` MARKET) → `engine.submit()`;
  - `command == CANCEL`: `engine.cancel()` → emit `FILL(CANCELLED)`;
  - `command == MODIFY`: `engine.modify()`.
- `on_market_data(bar)`: `engine.on_bar()` → for each `FillDecision` apply
  fee/slippage to the matched fill price, emit `FILL(EXECUTED)`; for each
  `CancelDecision` (OCO sibling) emit `FILL(CANCELLED)`.

**Execution timing moves here.** `immediate` vs `next_bar` is a venue concern: a
`next_bar` market order rests and fills at the next bar's open.

### `ExecutionHandler` (thin)
Gains `on_market_data(event)` delegating to the exchange. `on_order` routes to the
exchange as today.

### `OrderManager` (slimmed ~half)
- Translates a signal into orders: primary (MARKET/LIMIT/STOP) + optional SL (STOP)
  + optional TP (LIMIT).
- **Tags brackets** using `parent_order_id`/`child_order_ids` (fixes B5).
- Stores the order mirror; emits `OrderEvent(NEW)` for **all** legs (primary + SL
  + TP) so they reach the exchange book.
- Gains `on_fill(fill)` to reconcile the mirror against exchange truth: mark
  FILLED on `EXECUTED`, CANCELLED on `CANCELLED`.
- `modify_order`/`cancel_order` emit `OrderEvent(MODIFY/CANCEL)`.

**Deletes:** `process_orders_on_market_data`, `_check_and_trigger_conditional_orders`,
`_process_market_orders`, `_process_queued_market_orders`, `_should_trigger_order`,
`_handle_oco_order_fill`, `_deactivate_filled_order`, internal self-filling via
`add_fill`, and the `queued_market_orders`/`processed_fills` state.

`OrderHandler` (interface) drops `process_orders_on_market_data`, gains `on_fill`.

## Schema changes

- **`OrderEvent`**:
  - Fix `new_order_event` to read `order.type` and `order.id` (B1).
  - Add `command: OrderCommand` (`NEW` | `CANCEL` | `MODIFY`), default `NEW` (B2).
  - Carry bracket linkage (`parent_order_id`) for the exchange's OCO grouping.
- **`FillEvent`**:
  - Add `order_id` for reconciliation.
  - Use `status` correctly: `EXECUTED` for real fills, `CANCELLED` for OCO/cancel
    acknowledgements.
- **`portfolio.on_fill`**: guard to act only on `EXECUTED` fills (ignore
  CANCELLED/REFUSED). Small change; also fixes a latent bug where any fill status
  currently creates a transaction.
- **`BarEvent`**: add `get_last_high(ticker)` / `get_last_low(ticker)` accessors
  (mirror the existing `get_last_close`/`get_last_open` pattern).
- **`Order`**: populate bracket links on SL/TP creation.

## Data flow (new sequences)

**Market + bracket from signal**
1. `SIGNAL` → `OrderManager`: create primary(MARKET) + SL(STOP) + TP(LIMIT), tag
   bracket, store mirror, emit 3 × `OrderEvent(NEW)`.
2. `ORDER(MARKET)` → exchange fills now → `FILL(EXECUTED, order_id)`.
3. `ORDER(STOP/LIMIT)` → exchange rests in `MatchingEngine`.
4. `FILL(EXECUTED)` → portfolio (position) + `OrderManager.on_fill` (mirror FILLED).

**Trigger**
1. `BAR` → `execution_handler.on_market_data` → `engine.on_bar` → fills (+ OCO
   cancels).
2. Exchange applies fee/slippage; emits `FILL(EXECUTED)` and `FILL(CANCELLED)`.
3. Portfolio acts on EXECUTED only; `OrderManager.on_fill` updates the mirror for
   both.

**Cancel / modify (API)**
1. `OrderManager.cancel_order` → `OrderEvent(CANCEL)`.
2. `ORDER(CANCEL)` → exchange `engine.cancel` → `FILL(CANCELLED, order_id)`.
3. `OrderManager.on_fill` → mirror CANCELLED. No phantom fill (fixes B2).

**Event wiring (`full_event_handler.process_events`)**
- `BAR` → `portfolio.update_portfolios_market_value`,
  `execution_handler.on_market_data` (**replaces** `order_handler.process_orders_on_market_data`),
  `strategies_handler.calculate_signals`.
- `FILL` → `portfolio.on_fill` **and** `order_handler.on_fill`.
- Ordering preserved: matching runs before signal generation, so fills enqueue
  before new signals (FIFO-correct).

## Error handling

Remove the broad `except Exception: return []` (B6). The matching loop wraps
**per-order**, so one malformed resting order cannot silently drop a whole bar's
fills — log and continue. Signal validation stays in `OrderManager`
(`EnhancedOrderValidator`); order validation stays in the exchange
(`validate_order`).

## Testing (TDD-first)

- **`MatchingEngine` (pure unit, written first):** all 4 stop/limit × action combos
  via high/low; gap fills (open beyond stop → fill at open); limit fills at limit;
  OCO same-bar pessimistic priority; cancel/modify; no-trigger when level not
  pierced; multi-order/multi-ticker bars.
- **`SimulatedExchange` (integration):** immediate market fill; resting submit;
  `on_bar` fills with fee/slippage applied; OCO sibling `FILL(CANCELLED)`;
  cancel/modify commands; `next_bar` fills at next open.
- **`OrderManager`:** signal → correct `OrderEvent`s (type, id, bracket tags);
  cancel/modify emit correct command events; `on_fill` reconciles the mirror.
- **Regression:** `make test-orders` + `make test-execution`; update tests that
  asserted close-based triggering; keep signal→position end-to-end behaviors green.

## Open sub-decision (for spec review)

OCO-cancel notification reuses `FillEvent(status=CANCELLED)` (one event type, plus
the portfolio status-guard we need anyway) rather than introducing a new
`OrderStatusEvent`. Veto here if a dedicated event is preferred.

## Out of scope (follow-ups)

- B7: bar-time lifecycle timestamps on `Order`.
- Live exchange adapters (IBKR/Alpaca/Binance) and reconciliation against a remote
  venue.
- Entry-triggered bracket activation (OTO semantics — SL/TP active only after the
  entry fills). The bracket grouping added here is the prerequisite.
