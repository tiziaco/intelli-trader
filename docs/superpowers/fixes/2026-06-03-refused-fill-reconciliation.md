# Fix: rejected immediate-market orders leave the order mirror stuck PENDING

> Paste this whole file into a clean Claude Code session (or run `/superpowers` TDD). It is self-contained.

## Background (the architecture)

In iTrader, order *matching* lives in the execution layer. When a MARKET order is created
from a signal, `OrderManager` stores it as `PENDING` and emits an `OrderEvent(NEW)`. The
`SimulatedExchange.execute_order(event)` either fills it (emits `FillEvent` with
`FillStatus.EXECUTED`) or returns a failure `ExecutionResult`. A `FILL` event is the only
thing that drives `OrderManager.on_fill(...)`, which reconciles the stored order's status
(the "order mirror") against exchange truth.

## The bug

`SimulatedExchange.execute_order` has three failure paths that return an `ExecutionResult`
WITHOUT emitting any `FillEvent`:
- validation rejected (`itrader/execution_handler/exchanges/simulated.py` ~line 116, status REJECTED)
- exchange not connected (~line 131, status FAILED)
- simulated random failure (~line 152, status FAILED)

Because no `FillEvent` is emitted on these paths, `OrderManager.on_fill` is never called for
a rejected immediate-market order, so the stored order is **stuck `PENDING` in the active
book forever**. The reconciliation contract ("the exchange is the source of truth for an
order's terminal state") has a hole.

Additionally, `OrderManager.on_fill`'s current `REFUSED` handling (the `else` branch) just
logs and leaves the order active — so even if a REFUSED fill arrived, the mirror would stay
PENDING. We want a rejected order to become terminal `REJECTED`.

## The fix (two parts)

1. `SimulatedExchange`: emit a `FillEvent(REFUSED)` on each of the three failure paths so the
   order handler can reconcile.
2. `OrderManager.on_fill`: handle `FillStatus.REFUSED` by marking the order `REJECTED`
   (terminal) and deactivating it.

`PortfolioHandler.on_fill` already ignores non-EXECUTED fills (a guard added earlier), so a
REFUSED fill correctly produces no transaction/position — no change needed there.

Retry, if ever wanted, is a higher-level concern that submits a NEW order; a rejected attempt
is terminal.

## Relevant facts (already verified)

- `Order.reject_order(reason)` exists (`itrader/order_handler/order.py:344`) and transitions
  `PENDING -> REJECTED` (a valid transition in `VALID_ORDER_TRANSITIONS`).
- `FillStatus` is `Enum("FillStatus", "EXECUTED REFUSED CANCELLED")` and `fill_status_map`
  already maps `"REFUSED"`. `FillEvent.new_fill('REFUSED', 0.0, event)` copies `order_id`.
- `SimulatedExchange` already imports `FillEvent`, `OrderEvent`. `OrderManager.on_fill` already
  imports `FillStatus`.
- Files use **TAB indentation** (simulated.py, order_manager.py, test files). Match exactly.
- Tests run via Poetry; `pyproject.toml` sets `filterwarnings=["error"]` and `--strict-markers`
  (a stray warning fails the test; do not add markers).

## Implementation (TDD — do the steps in order)

### Step 1 — Failing test for the exchange emitting REFUSED

Append to the `TestSimulatedExchangeRouting` class in
`test/test_execution_handler/test_exchanges/test_simulated_exchange.py` (it already has
`setUp` and the `_oe` helper). A market order for a symbol the exchange does NOT support
fails validation:

```python
	def test_rejected_market_order_emits_refused_fill(self):
		# 'ETHUSDT' is not in supported_symbols (setUp only allows BTCUSDT) -> validation reject.
		self.exchange.on_order(self._oe(self.OrderType.MARKET, order_id=99,
		                                command=self.OrderCommand.NEW))
		# sanity: BTCUSDT market fills; now send an unsupported-symbol order directly.
		bad = self.OrderEvent(
			time=__import__('datetime').datetime(2024, 1, 1), ticker='ETHUSDT',
			action='BUY', price=40.0, quantity=1.0, exchange='default', strategy_id=1,
			portfolio_id=1, order_type=self.OrderType.MARKET, order_id=100,
			command=self.OrderCommand.NEW)
		# drain the first (successful) fill, then exercise the rejection
		while not self.queue.empty():
			self.queue.get()
		self.exchange.on_order(bad)
		fills = [self.queue.get() for _ in range(self.queue.qsize())]
		self.assertEqual(len(fills), 1)
		self.assertIs(fills[0].status, self.FillStatus.REFUSED)
		self.assertEqual(fills[0].order_id, 100)
```

Run it — it FAILS (no fill emitted on rejection today):
`poetry run pytest "test/test_execution_handler/test_exchanges/test_simulated_exchange.py::TestSimulatedExchangeRouting::test_rejected_market_order_emits_refused_fill" -v`

### Step 2 — Emit REFUSED on the failure paths

In `itrader/execution_handler/exchanges/simulated.py`, add a small helper near `_emit_fill`:

```python
	def _emit_rejection(self, event: OrderEvent, reason: str) -> None:
		"""Enqueue a FillEvent(REFUSED) so the order mirror can reconcile a rejected order."""
		self.logger.debug('Emitting REFUSED fill for %s %s: %s', event.action, event.ticker, reason)
		self.global_queue.put(FillEvent.new_fill('REFUSED', 0.0, event))
```

Then in `execute_order`, immediately BEFORE each of the three failure `return ExecutionResult(...)`
statements (the validation-invalid path, the not-connected path, and the simulated-failure
path — they are the early returns that occur BEFORE the success `_emit_fill` call), add a call
to `_emit_rejection(event, <reason>)`. Use the error message already computed on each path,
e.g.:
- validation reject: `self._emit_rejection(event, validation_result.error_message or "validation failed")`
- not connected: `self._emit_rejection(event, "exchange not connected")`
- simulated failure: `self._emit_rejection(event, error_msg)`

Do NOT add an emission inside the final `except` block (that path may run after a fill was
already emitted; avoid double-emitting). Leave the success path untouched.

Re-run the Step 1 test — it should PASS. Then run the whole exchange suite and fix any
pre-existing test that asserted "no fill on a failed order" by updating it to expect a single
REFUSED fill:
`poetry run pytest test/test_execution_handler/ -v`

### Step 3 — Failing test for on_fill REFUSED -> REJECTED

In `test/test_order_handler/test_order_manager.py`, REPLACE the existing
`test_refused_fill_leaves_order_active` method (in `TestOrderManagerReconciliation`) with:

```python
	def test_refused_fill_marks_order_rejected(self):
		# A REFUSED fill marks the order REJECTED (terminal) and removes it from the active book.
		from itrader.core.enums import OrderStatus
		order = self._rest_a_stop()
		self.handler.on_fill(self._fill(order, 'REFUSED'))
		stored = self.storage.get_order_by_id(order.id, self.portfolio_id)
		self.assertEqual(stored.status, OrderStatus.REJECTED)
		active_ids = [o.id for o in self.storage.get_active_orders(self.portfolio_id)]
		self.assertNotIn(order.id, active_ids)
```

Run it — it FAILS (today REFUSED leaves the order PENDING/active):
`poetry run pytest "test/test_order_handler/test_order_manager.py::TestOrderManagerReconciliation::test_refused_fill_marks_order_rejected" -v`

### Step 4 — Handle REFUSED in on_fill

In `itrader/order_handler/order_manager.py`, in `on_fill`, change the status handling so
REFUSED is an explicit terminal branch. Replace:

```python
			elif fill_event.status == FillStatus.CANCELLED:
				order.cancel_order("exchange cancellation")
			else:
				# REFUSED or any other status: leave the order active for retry/alerting.
				self.logger.warning('Unhandled fill status %s for order %s; order left active',
				                    fill_event.status, order_id)
				return
```

with:

```python
			elif fill_event.status == FillStatus.CANCELLED:
				order.cancel_order("exchange cancellation")
			elif fill_event.status == FillStatus.REFUSED:
				order.reject_order("exchange rejection")
			else:
				# Truly unknown status: leave the order active and alert.
				self.logger.warning('Unhandled fill status %s for order %s; order left active',
				                    fill_event.status, order_id)
				return
```

(The trailing `update_order` + `deactivate_order` lines stay as-is; they now also run for the
REFUSED→REJECTED case.)

Re-run the Step 3 test — it should PASS.

### Step 5 — Full regression

```bash
poetry run pytest -q
```
All tests must pass (0 failures). If a portfolio test regresses, confirm
`PortfolioHandler.on_fill` still early-returns on non-EXECUTED status (it should — that guard
already exists). Fix any test that assumed the old REFUSED-leaves-active behavior.

### Step 6 — Commit

```bash
git add itrader/execution_handler/exchanges/simulated.py itrader/order_handler/order_manager.py test/
git commit -m "fix: emit FILL(REFUSED) on rejected market orders; reconcile mirror to REJECTED"
```

## Acceptance criteria
- A rejected immediate-market order emits exactly one `FillEvent(REFUSED)` carrying its `order_id`.
- `OrderManager.on_fill` marks a REFUSED order `REJECTED` and removes it from the active book.
- No position/transaction is created for a REFUSED fill (portfolio guard already handles this).
- Full suite green.
