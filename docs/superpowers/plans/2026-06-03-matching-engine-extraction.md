# Matching Engine Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move order *matching* (resting-order book, trigger evaluation, OCO) out of `OrderManager` into a new pure `MatchingEngine` composed by `SimulatedExchange`, leaving the order handler as venue-agnostic management.

**Architecture:** A dependency-free `MatchingEngine` holds resting `OrderEvent`s and decides fills from intrabar high/low (pessimistic gaps + OCO). `SimulatedExchange` composes it, applies fee/slippage, and emits `FillEvent`s. `OrderManager` only translates signals, tags brackets, stores a mirror, and reconciles via `on_fill`. Components talk only through the global queue.

**Tech Stack:** Python 3.13, Poetry, pytest/unittest, pandas (bar data), dataclasses, structlog.

**Spec:** `docs/superpowers/specs/2026-06-03-matching-engine-extraction-design.md`

**Conventions:**
- Handler modules use **tab indentation**; `config/` and some newer modules use spaces. Match the file you edit. `core/enums/` and `events_handler/event.py` use **tabs**; `portfolio_handler/` uses **spaces**.
- Tests are `unittest`-style classes, run by path (`make test-orders`, `make test-execution`). `pyproject.toml` sets `filterwarnings=["error", ...]` and `--strict-markers` — a stray warning fails the test.
- Run a single test: `poetry run pytest path::Class::test -v`.

---

## File Structure

**Create:**
- `itrader/execution_handler/matching_engine.py` — pure resting-order book + trigger/OCO logic. Holds `OrderEvent`s, returns `FillDecision`/`CancelDecision`.
- `test/test_execution_handler/test_matching_engine.py` — pure unit tests.

**Modify:**
- `itrader/core/enums/order.py` — add `OrderCommand` enum + `order_command_map`.
- `itrader/core/enums/__init__.py` — export them.
- `itrader/events_handler/event.py` — `FillStatus.CANCELLED`; `OrderEvent` `command`/`parent_order_id` + fixed `new_order_event`; `FillEvent.order_id` + `new_fill`; `BarEvent.get_last_high`/`get_last_low`.
- `itrader/execution_handler/simulated.py` (`exchanges/simulated.py`) — compose `MatchingEngine`; add `on_order`/`on_market_data`; extract `_emit_fill`; add `execution_timing`.
- `itrader/execution_handler/execution_handler.py` — `on_order` routes to `exchange.on_order`; add `on_market_data`.
- `itrader/order_handler/order_manager.py` — bracket tagging; emit `OrderEvent`s for all legs with `command`; `on_fill`; **delete** matching code.
- `itrader/order_handler/order_handler.py` — drop `process_orders_on_market_data`; add `on_fill`.
- `itrader/portfolio_handler/portfolio_handler.py` — `on_fill` guards on `EXECUTED`.
- `itrader/events_handler/full_event_handler.py` — `BAR`→`execution_handler.on_market_data`; `FILL`→portfolio + order_handler.
- `test/test_order_handler/test_stop_limit_orders.py` — rewrite for the new flow.

---

## Task 1: Add `OrderCommand` enum

**Files:**
- Modify: `itrader/core/enums/order.py`
- Modify: `itrader/core/enums/__init__.py`
- Test: `test/test_order_handler/test_order_command_enum.py`

- [ ] **Step 1: Write the failing test**

Create `test/test_order_handler/test_order_command_enum.py`:

```python
import unittest
from itrader.core.enums import OrderCommand, order_command_map


class TestOrderCommand(unittest.TestCase):
	def test_members_exist(self):
		self.assertEqual({m.name for m in OrderCommand}, {"NEW", "CANCEL", "MODIFY"})

	def test_map_resolves_strings(self):
		self.assertIs(order_command_map["NEW"], OrderCommand.NEW)
		self.assertIs(order_command_map["CANCEL"], OrderCommand.CANCEL)
		self.assertIs(order_command_map["MODIFY"], OrderCommand.MODIFY)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest test/test_order_handler/test_order_command_enum.py -v`
Expected: FAIL — `ImportError: cannot import name 'OrderCommand'`.

- [ ] **Step 3: Add the enum**

In `itrader/core/enums/order.py`, after the `OrderType`/`OrderStatus` definitions (tab indentation), add:

```python
# Order Command Enum (NEW order, CANCEL resting order, MODIFY resting order)
OrderCommand = Enum("OrderCommand", "NEW CANCEL MODIFY")

# Order Command Mapping
order_command_map = {
	"NEW": OrderCommand.NEW,
	"CANCEL": OrderCommand.CANCEL,
	"MODIFY": OrderCommand.MODIFY
}
```

In `itrader/core/enums/__init__.py`, add to the order-enums import block and `__all__`:

```python
from .order import (
    OrderType,
    OrderStatus,
    OrderCommand,
    order_type_map,
    order_status_map,
    order_command_map,
    VALID_ORDER_TRANSITIONS
)
```

Add `'OrderCommand'` and `'order_command_map'` to the `__all__` list.

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest test/test_order_handler/test_order_command_enum.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add itrader/core/enums/order.py itrader/core/enums/__init__.py test/test_order_handler/test_order_command_enum.py
git commit -m "feat: add OrderCommand enum for order intent (NEW/CANCEL/MODIFY)"
```

---

## Task 2: Add `BarEvent.get_last_high` / `get_last_low`

**Files:**
- Modify: `itrader/events_handler/event.py` (after `get_last_open`, ~line 111)
- Test: `test/test_events/test_bar_event_ohlc.py`

- [ ] **Step 1: Write the failing test**

Create `test/test_events/test_bar_event_ohlc.py`:

```python
import unittest
import pandas as pd
from datetime import datetime
from itrader.events_handler.event import BarEvent


class TestBarEventOHLC(unittest.TestCase):
	def setUp(self):
		bars = {'BTCUSDT': pd.DataFrame(
			{'open': [30], 'high': [60], 'low': [20], 'close': [40], 'volume': [1000]})}
		self.bar = BarEvent(time=datetime(2024, 1, 1), bars=bars)

	def test_get_last_high(self):
		self.assertEqual(self.bar.get_last_high('BTCUSDT'), 60.0)

	def test_get_last_low(self):
		self.assertEqual(self.bar.get_last_low('BTCUSDT'), 20.0)

	def test_missing_ticker_returns_none(self):
		self.assertIsNone(self.bar.get_last_high('ETHUSDT'))
		self.assertIsNone(self.bar.get_last_low('ETHUSDT'))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest test/test_events/test_bar_event_ohlc.py -v`
Expected: FAIL — `AttributeError: 'BarEvent' object has no attribute 'get_last_high'`.

- [ ] **Step 3: Implement the accessors**

In `itrader/events_handler/event.py`, immediately after `get_last_open` (uses tabs), add:

```python
	def get_last_high(self, ticker) -> float:
		"""Get the high price for the ticker from the current bar."""
		if ticker not in self.bars:
			return None
		high_data = self.bars[ticker]['high']
		if hasattr(high_data, 'iloc'):
			return float(high_data.iloc[-1])
		elif hasattr(high_data, '__getitem__') and hasattr(high_data, '__len__'):
			return float(high_data[-1])
		else:
			return float(high_data)

	def get_last_low(self, ticker) -> float:
		"""Get the low price for the ticker from the current bar."""
		if ticker not in self.bars:
			return None
		low_data = self.bars[ticker]['low']
		if hasattr(low_data, 'iloc'):
			return float(low_data.iloc[-1])
		elif hasattr(low_data, '__getitem__') and hasattr(low_data, '__len__'):
			return float(low_data[-1])
		else:
			return float(low_data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest test/test_events/test_bar_event_ohlc.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add itrader/events_handler/event.py test/test_events/test_bar_event_ohlc.py
git commit -m "feat: add get_last_high/get_last_low accessors to BarEvent"
```

---

## Task 3: Fix `OrderEvent` (type/id) and add `command` / `parent_order_id`

**Files:**
- Modify: `itrader/events_handler/event.py` (`OrderEvent` dataclass + `new_order_event`, ~lines 223-284)
- Test: `test/test_events/test_order_event_schema.py`

- [ ] **Step 1: Write the failing test**

Create `test/test_events/test_order_event_schema.py`:

```python
import unittest
from datetime import datetime
from itrader.events_handler.event import OrderEvent
from itrader.core.enums import OrderType, OrderCommand
from itrader.order_handler.order import Order


class TestOrderEventSchema(unittest.TestCase):
	def _order(self, order_type):
		return Order(
			time=datetime(2024, 1, 1), type=order_type, status=None,
			ticker='BTCUSDT', action='SELL', price=42.0, quantity=2.0,
			exchange='default', strategy_id=1, portfolio_id=1,
		)

	def test_preserves_real_order_type(self):
		oe = OrderEvent.new_order_event(self._order(OrderType.STOP))
		self.assertIs(oe.order_type, OrderType.STOP)

	def test_preserves_order_id(self):
		order = self._order(OrderType.LIMIT)
		oe = OrderEvent.new_order_event(order)
		self.assertEqual(oe.order_id, order.id)

	def test_command_defaults_to_new(self):
		oe = OrderEvent.new_order_event(self._order(OrderType.MARKET))
		self.assertIs(oe.command, OrderCommand.NEW)

	def test_command_can_be_overridden(self):
		oe = OrderEvent.new_order_event(self._order(OrderType.STOP), command=OrderCommand.CANCEL)
		self.assertIs(oe.command, OrderCommand.CANCEL)

	def test_parent_order_id_copied(self):
		order = self._order(OrderType.STOP)
		order.parent_order_id = 999
		oe = OrderEvent.new_order_event(order)
		self.assertEqual(oe.parent_order_id, 999)
```

Note: `Order(... status=None ...)` is valid — `add_state_change`/`new_*` factories normally set PENDING, but the dataclass accepts any value and these tests only read schema fields.

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest test/test_events/test_order_event_schema.py -v`
Expected: FAIL — `test_preserves_real_order_type` gets `OrderType.MARKET` (current `getattr` bug); `command`/`parent_order_id` raise `AttributeError`.

- [ ] **Step 3: Update imports and the `OrderEvent` dataclass**

In `itrader/events_handler/event.py`, change the enum import (line 8) to include `OrderCommand`:

```python
from ..core.enums import OrderType, OrderCommand
```

In the `OrderEvent` dataclass, append two fields after `order_id` (tabs):

```python
	order_id: str = None
	parent_order_id: Optional[int] = None
	command: 'OrderCommand' = OrderCommand.NEW
	type = EventType.ORDER
```

(Keep the existing `type = EventType.ORDER` as the last line; just insert the two new fields above it.)

- [ ] **Step 4: Fix `new_order_event`**

Replace the body of `new_order_event` with the corrected attribute reads + `command` param:

```python
	@classmethod
	def new_order_event(cls, order, command: 'OrderCommand' = OrderCommand.NEW):
		"""
		Generate a new OrderEvent from an Order.

		Reads the order's real type (`order.type`) and id (`order.id`),
		and optional bracket linkage / command intent.
		"""
		return cls(
			order.time,
			order.ticker,
			order.action,
			order.price,
			order.quantity,
			order.exchange,
			order.strategy_id,
			order.portfolio_id,
			order_type=getattr(order, 'type', OrderType.MARKET),
			stop_price=getattr(order, 'stop_price', None),
			order_id=getattr(order, 'id', None),
			parent_order_id=getattr(order, 'parent_order_id', None),
			command=command,
		)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `poetry run pytest test/test_events/test_order_event_schema.py -v`
Expected: PASS (5 tests).

- [ ] **Step 6: Run the broader event/transaction suites for regressions**

Run: `poetry run pytest test/test_events/ test/test_transaction/ -v`
Expected: PASS. (These build `new_order_event` from a MARKET order; behavior is unchanged for market orders.)

- [ ] **Step 7: Commit**

```bash
git add itrader/events_handler/event.py test/test_events/test_order_event_schema.py
git commit -m "fix: OrderEvent preserves real type/id; add command and parent_order_id (B1)"
```

---

## Task 4: Add `FillStatus.CANCELLED` and `FillEvent.order_id`

**Files:**
- Modify: `itrader/events_handler/event.py` (`FillStatus`, `fill_status_map`, `FillEvent`, `new_fill`)
- Test: `test/test_events/test_fill_event_schema.py`

- [ ] **Step 1: Write the failing test**

Create `test/test_events/test_fill_event_schema.py`:

```python
import unittest
from datetime import datetime
from itrader.events_handler.event import OrderEvent, FillEvent, FillStatus
from itrader.core.enums import OrderType


class TestFillEventSchema(unittest.TestCase):
	def _order_event(self):
		return OrderEvent(
			time=datetime(2024, 1, 1), ticker='BTCUSDT', action='BUY',
			price=40.0, quantity=1.0, exchange='default', strategy_id=1,
			portfolio_id=1, order_type=OrderType.MARKET, order_id=7,
		)

	def test_executed_fill_carries_order_id(self):
		fill = FillEvent.new_fill('EXECUTED', 0.5, self._order_event())
		self.assertEqual(fill.order_id, 7)
		self.assertIs(fill.status, FillStatus.EXECUTED)

	def test_cancelled_status_supported(self):
		fill = FillEvent.new_fill('CANCELLED', 0.0, self._order_event())
		self.assertIs(fill.status, FillStatus.CANCELLED)
		self.assertEqual(fill.order_id, 7)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest test/test_events/test_fill_event_schema.py -v`
Expected: FAIL — `'CANCELLED'` not in `fill_status_map` (raises ValueError); `fill.order_id` AttributeError.

- [ ] **Step 3: Extend `FillStatus`, the map, and `FillEvent`**

In `itrader/events_handler/event.py`:

Line 11 — add CANCELLED:

```python
FillStatus = Enum("FillStatus", "EXECUTED REFUSED CANCELLED")
```

`fill_status_map` (lines 22-25) — add the entry:

```python
fill_status_map = {
	"EXECUTED": FillStatus.EXECUTED,
	"REFUSED": FillStatus.REFUSED,
	"CANCELLED": FillStatus.CANCELLED,
}
```

`FillEvent` dataclass — append `order_id` after `portfolio_id` (tabs):

```python
	portfolio_id: str
	order_id: Optional[int] = None
	type = EventType.FILL
```

- [ ] **Step 4: Update `new_fill` to copy `order_id`**

Replace the `return cls(...)` in `new_fill` with:

```python
		return cls(
			order.time,
			fill_status,
			order.ticker,
			order.action,
			order.price,
			order.quantity,
			commission,
			order.portfolio_id,
			order_id=getattr(order, 'order_id', None),
		)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `poetry run pytest test/test_events/test_fill_event_schema.py -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add itrader/events_handler/event.py test/test_events/test_fill_event_schema.py
git commit -m "feat: add FillStatus.CANCELLED and FillEvent.order_id for reconciliation"
```

---

## Task 5: `MatchingEngine` — book management (submit/cancel/modify)

**Files:**
- Create: `itrader/execution_handler/matching_engine.py`
- Test: `test/test_execution_handler/test_matching_engine.py`

- [ ] **Step 1: Write the failing test**

Create `test/test_execution_handler/test_matching_engine.py`:

```python
import unittest
import pandas as pd
from datetime import datetime

from itrader.execution_handler.matching_engine import MatchingEngine, FillDecision, CancelDecision
from itrader.events_handler.event import OrderEvent, BarEvent
from itrader.core.enums import OrderType, OrderCommand


def make_order_event(order_type, action, price, order_id,
                     ticker='BTCUSDT', quantity=1.0, parent_order_id=None):
	return OrderEvent(
		time=datetime(2024, 1, 1), ticker=ticker, action=action, price=price,
		quantity=quantity, exchange='default', strategy_id=1, portfolio_id=1,
		order_type=order_type, order_id=order_id, parent_order_id=parent_order_id,
		command=OrderCommand.NEW,
	)


def make_bar(open_, high, low, close, ticker='BTCUSDT'):
	bars = {ticker: pd.DataFrame(
		{'open': [open_], 'high': [high], 'low': [low], 'close': [close], 'volume': [1]})}
	return BarEvent(time=datetime(2024, 1, 1), bars=bars)


class TestMatchingEngineBook(unittest.TestCase):
	def setUp(self):
		self.engine = MatchingEngine()

	def test_submit_then_cancel(self):
		oe = make_order_event(OrderType.STOP, 'SELL', 30.0, order_id=1)
		self.engine.submit(oe)
		self.assertTrue(self.engine.has_order(1))
		self.assertTrue(self.engine.cancel(1))
		self.assertFalse(self.engine.has_order(1))

	def test_cancel_unknown_returns_false(self):
		self.assertFalse(self.engine.cancel(123))

	def test_modify_price_and_quantity(self):
		oe = make_order_event(OrderType.LIMIT, 'SELL', 50.0, order_id=2, quantity=1.0)
		self.engine.submit(oe)
		self.assertTrue(self.engine.modify(2, new_price=55.0, new_quantity=3.0))
		resting = self.engine.get_order(2)
		self.assertEqual(resting.price, 55.0)
		self.assertEqual(resting.quantity, 3.0)

	def test_modify_unknown_returns_false(self):
		self.assertFalse(self.engine.modify(999, new_price=1.0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest test/test_execution_handler/test_matching_engine.py -v`
Expected: FAIL — `ModuleNotFoundError: itrader.execution_handler.matching_engine`.

- [ ] **Step 3: Create the engine skeleton**

Create `itrader/execution_handler/matching_engine.py` (spaces — it is a new module; pick spaces for clarity, keep it internally consistent):

```python
"""
Pure order-matching engine for simulated execution.

Holds resting OrderEvents (stop/limit, and next-bar market orders) and decides
which fill on each bar using intrabar high/low, with pessimistic gap fills and
exchange-enforced OCO between bracket siblings.

This module has NO dependency on the event queue, fee/slippage models, or
logging side-effects. It takes OrderEvents and BarEvents in and returns plain
decision objects out, so it is fully deterministic and unit-testable.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from itrader.events_handler.event import OrderEvent, BarEvent
from itrader.core.enums import OrderType


@dataclass
class FillDecision:
    """One resting order has matched and should be filled."""
    order_event: OrderEvent
    fill_quantity: float
    fill_price: float
    reason: str


@dataclass
class CancelDecision:
    """One resting order should be cancelled (OCO sibling of a fill)."""
    order_event: OrderEvent
    reason: str


class MatchingEngine:
    """Resting-order book + trigger/OCO evaluation."""

    def __init__(self):
        self._resting: Dict[int, OrderEvent] = {}

    # --- book management ---

    def submit(self, order_event: OrderEvent) -> None:
        """Add a resting order (stop/limit, or a next-bar market order)."""
        self._resting[order_event.order_id] = order_event

    def cancel(self, order_id: int) -> bool:
        """Remove a resting order. Returns True if it was present."""
        return self._resting.pop(order_id, None) is not None

    def modify(self, order_id: int, new_price: Optional[float] = None,
               new_quantity: Optional[float] = None) -> bool:
        """Mutate a resting order's price/quantity. Returns True if present."""
        order = self._resting.get(order_id)
        if order is None:
            return False
        if new_price is not None:
            order.price = new_price
        if new_quantity is not None:
            order.quantity = new_quantity
        return True

    def has_order(self, order_id: int) -> bool:
        return order_id in self._resting

    def get_order(self, order_id: int) -> Optional[OrderEvent]:
        return self._resting.get(order_id)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest test/test_execution_handler/test_matching_engine.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add itrader/execution_handler/matching_engine.py test/test_execution_handler/test_matching_engine.py
git commit -m "feat: MatchingEngine book management (submit/cancel/modify)"
```

---

## Task 6: `MatchingEngine.on_bar` — STOP triggers with pessimistic gap fills

**Files:**
- Modify: `itrader/execution_handler/matching_engine.py`
- Test: `test/test_execution_handler/test_matching_engine.py` (add a class)

- [ ] **Step 1: Write the failing test**

Append to `test/test_execution_handler/test_matching_engine.py`:

```python
class TestMatchingEngineStopTriggers(unittest.TestCase):
	def setUp(self):
		self.engine = MatchingEngine()

	def test_sell_stop_triggers_when_low_pierces(self):
		# stop-loss on a long: SELL stop at 30, bar low 20 -> fills
		self.engine.submit(make_order_event(OrderType.STOP, 'SELL', 30.0, order_id=1))
		fills, cancels = self.engine.on_bar(make_bar(open_=35, high=36, low=20, close=25))
		self.assertEqual(len(fills), 1)
		self.assertEqual(fills[0].fill_price, 30.0)   # filled at stop (no gap)
		self.assertFalse(self.engine.has_order(1))    # removed from book

	def test_sell_stop_does_not_trigger_when_low_above(self):
		self.engine.submit(make_order_event(OrderType.STOP, 'SELL', 30.0, order_id=1))
		fills, cancels = self.engine.on_bar(make_bar(open_=40, high=45, low=35, close=42))
		self.assertEqual(fills, [])
		self.assertTrue(self.engine.has_order(1))

	def test_sell_stop_gap_fills_at_open(self):
		# bar gaps below the stop: open 25 < stop 30 -> realistic fill at open (worse)
		self.engine.submit(make_order_event(OrderType.STOP, 'SELL', 30.0, order_id=1))
		fills, cancels = self.engine.on_bar(make_bar(open_=25, high=27, low=18, close=20))
		self.assertEqual(fills[0].fill_price, 25.0)   # min(open, stop)

	def test_buy_stop_triggers_when_high_pierces(self):
		# stop on a short: BUY stop at 50, bar high 60 -> fills at stop
		self.engine.submit(make_order_event(OrderType.STOP, 'BUY', 50.0, order_id=2))
		fills, cancels = self.engine.on_bar(make_bar(open_=45, high=60, low=44, close=58))
		self.assertEqual(fills[0].fill_price, 50.0)

	def test_buy_stop_gap_fills_at_open(self):
		# bar gaps above the stop: open 55 > stop 50 -> fill at open (worse)
		self.engine.submit(make_order_event(OrderType.STOP, 'BUY', 50.0, order_id=2))
		fills, cancels = self.engine.on_bar(make_bar(open_=55, high=62, low=54, close=60))
		self.assertEqual(fills[0].fill_price, 55.0)   # max(open, stop)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest test/test_execution_handler/test_matching_engine.py::TestMatchingEngineStopTriggers -v`
Expected: FAIL — `AttributeError: 'MatchingEngine' object has no attribute 'on_bar'`.

- [ ] **Step 3: Implement `_evaluate` and a minimal `on_bar`**

Add to `MatchingEngine` (spaces):

```python
    # --- matching ---

    def _evaluate(self, order: OrderEvent, bar: BarEvent) -> Optional[float]:
        """Return the fill price if `order` triggers on `bar`, else None."""
        ticker = order.ticker
        if ticker not in bar.bars:
            return None
        open_ = bar.get_last_open(ticker)
        high = bar.get_last_high(ticker)
        low = bar.get_last_low(ticker)

        if order.order_type == OrderType.MARKET:
            # next-bar market order: unconditional fill at the open
            return open_

        if order.order_type == OrderType.STOP:
            if order.action == 'SELL':              # stop-loss on a long
                if low <= order.price:
                    return min(open_, order.price)  # pessimistic gap-down
            else:                                   # BUY stop (cover short)
                if high >= order.price:
                    return max(open_, order.price)  # pessimistic gap-up

        elif order.order_type == OrderType.LIMIT:
            if order.action == 'SELL':              # take-profit on a long
                if high >= order.price:
                    return order.price
            else:                                   # BUY limit (cover short)
                if low <= order.price:
                    return order.price

        return None

    def on_bar(self, bar: BarEvent) -> Tuple[List[FillDecision], List[CancelDecision]]:
        """Evaluate all resting orders against `bar`; return (fills, cancels)."""
        fills: List[FillDecision] = []
        cancels: List[CancelDecision] = []

        for order in list(self._resting.values()):
            try:
                price = self._evaluate(order, bar)
            except Exception:
                # A single malformed resting order must not drop the whole bar.
                continue
            if price is None:
                continue
            fills.append(FillDecision(
                order_event=order,
                fill_quantity=order.quantity,
                fill_price=price,
                reason=self._fill_reason(order),
            ))

        for fill in fills:
            self._resting.pop(fill.order_event.order_id, None)

        return fills, cancels

    @staticmethod
    def _fill_reason(order: OrderEvent) -> str:
        if order.order_type == OrderType.STOP:
            return "stop triggered"
        if order.order_type == OrderType.LIMIT:
            return "limit triggered"
        return "market fill"
```

Note: OCO and same-bar priority are added in Task 8 — `on_bar` here returns empty `cancels` and fills each candidate independently. The stop tests above don't use brackets, so they pass now.

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest test/test_execution_handler/test_matching_engine.py -v`
Expected: PASS (book tests + 5 stop tests).

- [ ] **Step 5: Commit**

```bash
git add itrader/execution_handler/matching_engine.py test/test_execution_handler/test_matching_engine.py
git commit -m "feat: MatchingEngine STOP triggers via intrabar low/high with gap fills (B3)"
```

---

## Task 7: `MatchingEngine.on_bar` — LIMIT triggers and multi-order

**Files:**
- Modify: `test/test_execution_handler/test_matching_engine.py` (add a class)

(No production change needed — `_evaluate` already handles LIMIT. This task locks the behavior with tests.)

- [ ] **Step 1: Write the test**

Append:

```python
class TestMatchingEngineLimitTriggers(unittest.TestCase):
	def setUp(self):
		self.engine = MatchingEngine()

	def test_sell_limit_triggers_when_high_pierces(self):
		# take-profit on a long: SELL limit at 50, bar high 60 -> fills at limit
		self.engine.submit(make_order_event(OrderType.LIMIT, 'SELL', 50.0, order_id=1))
		fills, _ = self.engine.on_bar(make_bar(open_=45, high=60, low=44, close=58))
		self.assertEqual(fills[0].fill_price, 50.0)

	def test_sell_limit_does_not_trigger_when_high_below(self):
		self.engine.submit(make_order_event(OrderType.LIMIT, 'SELL', 50.0, order_id=1))
		fills, _ = self.engine.on_bar(make_bar(open_=40, high=48, low=39, close=47))
		self.assertEqual(fills, [])

	def test_buy_limit_triggers_when_low_pierces(self):
		self.engine.submit(make_order_event(OrderType.LIMIT, 'BUY', 30.0, order_id=2))
		fills, _ = self.engine.on_bar(make_bar(open_=35, high=36, low=25, close=28))
		self.assertEqual(fills[0].fill_price, 30.0)

	def test_independent_orders_on_same_bar_both_fill(self):
		# two unrelated orders (no bracket link) both trigger -> both fill
		self.engine.submit(make_order_event(OrderType.STOP, 'SELL', 30.0, order_id=1))
		self.engine.submit(make_order_event(OrderType.LIMIT, 'SELL', 55.0, order_id=2))
		fills, cancels = self.engine.on_bar(make_bar(open_=40, high=60, low=20, close=50))
		self.assertEqual(len(fills), 2)
		self.assertEqual(cancels, [])

	def test_ignores_ticker_not_in_bar(self):
		self.engine.submit(make_order_event(OrderType.STOP, 'SELL', 30.0, order_id=1, ticker='ETHUSDT'))
		fills, _ = self.engine.on_bar(make_bar(open_=40, high=60, low=20, close=50))  # BTCUSDT only
		self.assertEqual(fills, [])
		self.assertTrue(self.engine.has_order(1))
```

- [ ] **Step 2: Run test to verify it passes**

Run: `poetry run pytest test/test_execution_handler/test_matching_engine.py::TestMatchingEngineLimitTriggers -v`
Expected: PASS (5 tests).

- [ ] **Step 3: Commit**

```bash
git add test/test_execution_handler/test_matching_engine.py
git commit -m "test: MatchingEngine LIMIT triggers and multi-order independence"
```

---

## Task 8: `MatchingEngine` — OCO brackets and same-bar pessimistic priority

**Files:**
- Modify: `itrader/execution_handler/matching_engine.py` (rewrite `on_bar`)
- Test: `test/test_execution_handler/test_matching_engine.py` (add a class)

- [ ] **Step 1: Write the failing test**

Append:

```python
class TestMatchingEngineOCO(unittest.TestCase):
	def setUp(self):
		self.engine = MatchingEngine()
		# A bracket: entry id 100; SL and TP are children (parent_order_id=100).
		self.sl = make_order_event(OrderType.STOP, 'SELL', 30.0, order_id=11, parent_order_id=100)
		self.tp = make_order_event(OrderType.LIMIT, 'SELL', 55.0, order_id=12, parent_order_id=100)

	def test_tp_fill_cancels_sl_sibling(self):
		self.engine.submit(self.sl)
		self.engine.submit(self.tp)
		# TP triggers (high 60 >= 55), SL does not (low 40 > 30)
		fills, cancels = self.engine.on_bar(make_bar(open_=50, high=60, low=40, close=58))
		self.assertEqual(len(fills), 1)
		self.assertEqual(fills[0].order_event.order_id, 12)
		self.assertEqual(len(cancels), 1)
		self.assertEqual(cancels[0].order_event.order_id, 11)
		self.assertFalse(self.engine.has_order(11))
		self.assertFalse(self.engine.has_order(12))

	def test_same_bar_both_pierced_prefers_stop(self):
		self.engine.submit(self.sl)
		self.engine.submit(self.tp)
		# wide bar pierces BOTH: low 20 <= 30 (SL) and high 60 >= 55 (TP)
		fills, cancels = self.engine.on_bar(make_bar(open_=45, high=60, low=20, close=40))
		self.assertEqual(len(fills), 1)
		self.assertEqual(fills[0].order_event.order_id, 11)      # pessimistic: STOP fills
		self.assertEqual(cancels[0].order_event.order_id, 12)    # TP cancelled

	def test_non_triggered_sibling_still_cancelled(self):
		# Only TP rests + an SL that does not trigger; TP fills -> SL cancelled anyway.
		self.engine.submit(self.sl)
		self.engine.submit(self.tp)
		fills, cancels = self.engine.on_bar(make_bar(open_=50, high=56, low=45, close=55))
		self.assertEqual(fills[0].order_event.order_id, 12)
		self.assertEqual([c.order_event.order_id for c in cancels], [11])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest test/test_execution_handler/test_matching_engine.py::TestMatchingEngineOCO -v`
Expected: FAIL — current `on_bar` fills both legs and returns no cancels.

- [ ] **Step 3: Rewrite `on_bar` with bracket resolution**

Replace the `on_bar` method (keep `_evaluate`, `_fill_reason`) with:

```python
    def on_bar(self, bar: BarEvent) -> Tuple[List[FillDecision], List[CancelDecision]]:
        """
        Evaluate all resting orders against `bar`.

        - Candidates are orders whose trigger price is reached this bar.
        - For bracket siblings (same non-None parent_order_id), at most one
          fills per bar; if both a STOP and a LIMIT are candidates, the STOP
          wins (pessimistic same-bar priority).
        - When a bracket leg fills, all other resting orders in that bracket
          are cancelled (OCO), even if they did not trigger this bar.
        """
        # 1. Collect candidate fills (price reached).
        candidates: Dict[int, float] = {}
        for order in list(self._resting.values()):
            try:
                price = self._evaluate(order, bar)
            except Exception:
                # One malformed resting order must not drop the whole bar.
                continue
            if price is not None:
                candidates[order.order_id] = price

        if not candidates:
            return [], []

        # 2. Resolve, per bracket, which single order fills.
        chosen: Dict[int, float] = {}   # order_id -> fill_price
        seen_brackets = set()
        for order_id, price in candidates.items():
            order = self._resting[order_id]
            bracket = order.parent_order_id
            if bracket is None:
                chosen[order_id] = price            # standalone, fills independently
                continue
            if bracket in seen_brackets:
                continue                            # already chose a leg for this bracket
            seen_brackets.add(bracket)
            winner_id = self._pick_bracket_winner(bracket, candidates)
            chosen[winner_id] = candidates[winner_id]

        # 3. Build fills and OCO cancels.
        fills: List[FillDecision] = []
        cancels: List[CancelDecision] = []
        cancelled_ids = set()

        for order_id, price in chosen.items():
            order = self._resting[order_id]
            fills.append(FillDecision(
                order_event=order,
                fill_quantity=order.quantity,
                fill_price=price,
                reason=self._fill_reason(order),
            ))
            bracket = order.parent_order_id
            if bracket is not None:
                for sibling in list(self._resting.values()):
                    if (sibling.parent_order_id == bracket
                            and sibling.order_id != order_id
                            and sibling.order_id not in cancelled_ids):
                        cancels.append(CancelDecision(sibling, "OCO - sibling filled"))
                        cancelled_ids.add(sibling.order_id)

        # 4. Remove filled + cancelled orders from the book.
        for fill in fills:
            self._resting.pop(fill.order_event.order_id, None)
        for cancel in cancels:
            self._resting.pop(cancel.order_event.order_id, None)

        return fills, cancels

    def _pick_bracket_winner(self, bracket: int, candidates: Dict[int, float]) -> int:
        """Among candidate legs of a bracket, prefer a STOP (pessimistic)."""
        leg_ids = [oid for oid in candidates
                   if self._resting[oid].parent_order_id == bracket]
        for oid in leg_ids:
            if self._resting[oid].order_type == OrderType.STOP:
                return oid
        return leg_ids[0]
```

- [ ] **Step 4: Run the full engine suite**

Run: `poetry run pytest test/test_execution_handler/test_matching_engine.py -v`
Expected: PASS — all classes (book, stop, limit, OCO).

- [ ] **Step 5: Commit**

```bash
git add itrader/execution_handler/matching_engine.py test/test_execution_handler/test_matching_engine.py
git commit -m "feat: MatchingEngine exchange-enforced OCO with pessimistic same-bar priority (B5)"
```

---

## Task 9: `SimulatedExchange` — compose engine, extract `_emit_fill`, add `on_order` routing

**Files:**
- Modify: `itrader/execution_handler/exchanges/simulated.py`
- Test: `test/test_execution_handler/test_exchanges/test_simulated_exchange.py` (add a class)

- [ ] **Step 1: Write the failing test**

Append a new class to `test/test_execution_handler/test_exchanges/test_simulated_exchange.py` (match the file's existing setup — it constructs `SimulatedExchange(queue)` and connects; reuse its helper/fixtures style). Add at the end of the file:

```python
class TestSimulatedExchangeRouting(unittest.TestCase):
	def setUp(self):
		from queue import Queue
		from itrader.execution_handler.exchanges.simulated import SimulatedExchange
		from itrader.core.enums import OrderType, OrderCommand
		from itrader.events_handler.event import OrderEvent, FillStatus
		self.Queue = Queue
		self.OrderType = OrderType
		self.OrderCommand = OrderCommand
		self.OrderEvent = OrderEvent
		self.FillStatus = FillStatus
		self.queue = Queue()
		self.exchange = SimulatedExchange(self.queue)
		self.exchange.connect()
		# Ensure the symbol validates on the default preset used by tests.
		self.exchange.update_config(supported_symbols={'BTCUSDT'})

	def _oe(self, order_type, action='BUY', price=40.0, order_id=1, command=None, parent_order_id=None):
		return self.OrderEvent(
			time=__import__('datetime').datetime(2024, 1, 1), ticker='BTCUSDT',
			action=action, price=price, quantity=1.0, exchange='default',
			strategy_id=1, portfolio_id=1, order_type=order_type, order_id=order_id,
			parent_order_id=parent_order_id,
			command=command or self.OrderCommand.NEW,
		)

	def test_new_market_order_fills_immediately(self):
		self.exchange.on_order(self._oe(self.OrderType.MARKET))
		fills = [self.queue.get() for _ in range(self.queue.qsize())]
		self.assertEqual(len(fills), 1)
		self.assertIs(fills[0].status, self.FillStatus.EXECUTED)

	def test_new_stop_order_rests_no_fill(self):
		self.exchange.on_order(self._oe(self.OrderType.STOP, action='SELL', price=30.0, order_id=2))
		self.assertEqual(self.queue.qsize(), 0)
		self.assertTrue(self.exchange.matching_engine.has_order(2))

	def test_cancel_command_removes_and_emits_cancelled(self):
		self.exchange.on_order(self._oe(self.OrderType.STOP, action='SELL', price=30.0, order_id=3))
		self.exchange.on_order(self._oe(self.OrderType.STOP, action='SELL', price=30.0, order_id=3,
		                                command=self.OrderCommand.CANCEL))
		self.assertFalse(self.exchange.matching_engine.has_order(3))
		fills = [self.queue.get() for _ in range(self.queue.qsize())]
		self.assertEqual(len(fills), 1)
		self.assertIs(fills[0].status, self.FillStatus.CANCELLED)
		self.assertEqual(fills[0].order_id, 3)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest "test/test_execution_handler/test_exchanges/test_simulated_exchange.py::TestSimulatedExchangeRouting" -v`
Expected: FAIL — `AttributeError: 'SimulatedExchange' object has no attribute 'on_order'` / `matching_engine`.

- [ ] **Step 3: Compose the engine and add config in `__init__`**

In `itrader/execution_handler/exchanges/simulated.py`, add the import near the top (with the other `itrader` imports):

```python
from itrader.execution_handler.matching_engine import MatchingEngine
from itrader.core.enums import OrderType, OrderCommand
```

In `__init__`, after `self.global_queue = global_queue` (line ~54), add:

```python
		# Resting-order book / matching engine
		self.matching_engine = MatchingEngine()
		# Execution timing for market orders: "immediate" or "next_bar"
		self.execution_timing = "immediate"
```

- [ ] **Step 4: Extract `_emit_fill` and refactor `execute_order` to use it**

In `execute_order`, replace the block from `# Calculate execution fee` through `self.global_queue.put(fill_event)` and the metrics/log lines (current lines ~153-184) so that the fee/slippage/emit logic lives in a reusable method. Add this new method and call it from `execute_order`:

```python
	def _emit_fill(self, event: OrderEvent, fill_price: float, fill_quantity: float):
		"""Apply fee + slippage to a matched fill and enqueue a FillEvent(EXECUTED)."""
		commission = self.fee_model.calculate_fee(
			quantity=fill_quantity, price=fill_price,
			side=event.action.lower(), order_type="market")
		slippage_factor = self.slippage_model.calculate_slippage_factor(
			quantity=fill_quantity, price=fill_price,
			side=event.action.lower(), order_type="market")
		executed_price = fill_price * slippage_factor

		fill_event = FillEvent.new_fill('EXECUTED', commission, event)
		fill_event.price = executed_price
		fill_event.quantity = fill_quantity
		self.global_queue.put(fill_event)

		self._orders_executed += 1
		self._total_volume += executed_price * fill_quantity
		self.logger.info('Order executed: %s %s %.4f @ $%.4f (slippage: %.4f%%)',
						event.action, event.ticker, fill_quantity, executed_price,
						(slippage_factor - 1.0) * 100)
		return executed_price, commission, slippage_factor
```

Then in `execute_order`, replace the fee/slippage/fill block with a call to it (keep the surrounding validation/connection/failure-sim and the `ExecutionResult` return). The success branch becomes:

```python
			executed_price, commission, slippage_factor = self._emit_fill(
				event, event.price, event.quantity)
			executed_quantity = event.quantity

			return ExecutionResult(
				success=True,
				status=ExecutionStatus.SUCCESS,
				order_id=f"SIM_{self._orders_executed}_{int(execution_time.timestamp())}",
				exchange_order_id=f"SIMEX_{self._orders_executed}",
				executed_price=executed_price,
				executed_quantity=executed_quantity,
				remaining_quantity=0.0,
				commission=commission,
				execution_time=execution_time,
				error_code=ExecutionErrorCode.NO_ERROR,
				metadata={
					'slippage_applied': (slippage_factor - 1.0) * 100,
					'original_price': event.price,
					'execution_latency_ms': random.uniform(5, 25),
					'exchange_name': self._exchange_name
				}
			)
```

- [ ] **Step 5: Add the `on_order` router**

Add this method to `SimulatedExchange`:

```python
	def on_order(self, event: OrderEvent):
		"""
		Route an order event by command and type.

		- CANCEL: remove the resting order, emit FILL(CANCELLED).
		- MODIFY: mutate the resting order.
		- NEW MARKET (immediate): fill now via execute_order.
		- NEW STOP/LIMIT, or NEW MARKET (next_bar): rest in the matching engine.
		"""
		if event.command == OrderCommand.CANCEL:
			self.matching_engine.cancel(event.order_id)
			self.global_queue.put(FillEvent.new_fill('CANCELLED', 0.0, event))
			return

		if event.command == OrderCommand.MODIFY:
			self.matching_engine.modify(event.order_id, event.price, event.quantity)
			return

		# NEW
		if event.order_type == OrderType.MARKET and self.execution_timing == "immediate":
			self.execute_order(event)
		else:
			self.matching_engine.submit(event)
```

- [ ] **Step 6: Run routing + existing exchange tests**

Run: `poetry run pytest test/test_execution_handler/test_exchanges/test_simulated_exchange.py -v`
Expected: PASS — the new routing class **and** all pre-existing `execute_order` tests (behavior unchanged because `execute_order` now calls `_emit_fill`).

- [ ] **Step 7: Commit**

```bash
git add itrader/execution_handler/exchanges/simulated.py test/test_execution_handler/test_exchanges/test_simulated_exchange.py
git commit -m "feat: SimulatedExchange composes MatchingEngine; on_order routes NEW/CANCEL/MODIFY (B2)"
```

---

## Task 10: `SimulatedExchange.on_market_data` — match resting orders, emit fills + OCO cancels

**Files:**
- Modify: `itrader/execution_handler/exchanges/simulated.py`
- Test: `test/test_execution_handler/test_exchanges/test_simulated_exchange.py`

- [ ] **Step 1: Write the failing test**

Append to `TestSimulatedExchangeRouting` (same file):

```python
	def _bar(self, open_, high, low, close):
		import pandas as pd
		from itrader.events_handler.event import BarEvent
		bars = {'BTCUSDT': pd.DataFrame(
			{'open': [open_], 'high': [high], 'low': [low], 'close': [close], 'volume': [1]})}
		return BarEvent(time=__import__('datetime').datetime(2024, 1, 1), bars=bars)

	def test_on_market_data_fills_resting_stop(self):
		self.exchange.on_order(self._oe(self.OrderType.STOP, action='SELL', price=30.0, order_id=5))
		self.exchange.on_market_data(self._bar(open_=35, high=36, low=20, close=25))
		fills = [self.queue.get() for _ in range(self.queue.qsize())]
		self.assertEqual(len(fills), 1)
		self.assertIs(fills[0].status, self.FillStatus.EXECUTED)
		self.assertEqual(fills[0].order_id, 5)

	def test_on_market_data_emits_oco_cancel(self):
		self.exchange.on_order(self._oe(self.OrderType.STOP, 'SELL', 30.0, order_id=6, parent_order_id=100))
		self.exchange.on_order(self._oe(self.OrderType.LIMIT, 'SELL', 55.0, order_id=7, parent_order_id=100))
		self.exchange.on_market_data(self._bar(open_=50, high=60, low=40, close=58))  # TP fills
		events = [self.queue.get() for _ in range(self.queue.qsize())]
		statuses = {e.order_id: e.status for e in events}
		self.assertIs(statuses[7], self.FillStatus.EXECUTED)
		self.assertIs(statuses[6], self.FillStatus.CANCELLED)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest "test/test_execution_handler/test_exchanges/test_simulated_exchange.py::TestSimulatedExchangeRouting::test_on_market_data_fills_resting_stop" -v`
Expected: FAIL — `AttributeError: ... has no attribute 'on_market_data'`.

- [ ] **Step 3: Implement `on_market_data`**

Add to `SimulatedExchange`:

```python
	def on_market_data(self, bar):
		"""Match resting orders against a new bar; emit EXECUTED fills and OCO cancels."""
		fills, cancels = self.matching_engine.on_bar(bar)
		for decision in fills:
			self._emit_fill(decision.order_event, decision.fill_price, decision.fill_quantity)
		for cancel in cancels:
			self.global_queue.put(FillEvent.new_fill('CANCELLED', 0.0, cancel.order_event))
```

- [ ] **Step 4: Run the exchange suite**

Run: `poetry run pytest test/test_execution_handler/ -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add itrader/execution_handler/exchanges/simulated.py test/test_execution_handler/test_exchanges/test_simulated_exchange.py
git commit -m "feat: SimulatedExchange.on_market_data matches resting orders (B3/B4)"
```

---

## Task 11: `ExecutionHandler` — route to `on_order`, add `on_market_data`

**Files:**
- Modify: `itrader/execution_handler/execution_handler.py`
- Test: `test/test_execution_handler/test_execution_handler_routing.py`

- [ ] **Step 1: Write the failing test**

Create `test/test_execution_handler/test_execution_handler_routing.py`:

```python
import unittest
import pandas as pd
from datetime import datetime
from queue import Queue

from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.events_handler.event import OrderEvent, BarEvent, FillStatus
from itrader.core.enums import OrderType, OrderCommand


class TestExecutionHandlerRouting(unittest.TestCase):
	def setUp(self):
		self.queue = Queue()
		self.handler = ExecutionHandler(self.queue)
		exchange = self.handler.exchanges['simulated']
		exchange.connect()
		exchange.update_config(supported_symbols={'BTCUSDT'})

	def _oe(self, order_type, action='BUY', price=40.0, order_id=1):
		return OrderEvent(
			time=datetime(2024, 1, 1), ticker='BTCUSDT', action=action, price=price,
			quantity=1.0, exchange='simulated', strategy_id=1, portfolio_id=1,
			order_type=order_type, order_id=order_id, command=OrderCommand.NEW)

	def test_market_order_routed_and_filled(self):
		self.handler.on_order(self._oe(OrderType.MARKET))
		fills = [self.queue.get() for _ in range(self.queue.qsize())]
		self.assertEqual(len(fills), 1)
		self.assertIs(fills[0].status, FillStatus.EXECUTED)

	def test_market_data_routed_to_exchange(self):
		self.handler.on_order(self._oe(OrderType.STOP, action='SELL', price=30.0, order_id=2))
		bars = {'BTCUSDT': pd.DataFrame(
			{'open': [35], 'high': [36], 'low': [20], 'close': [25], 'volume': [1]})}
		self.handler.on_market_data(BarEvent(time=datetime(2024, 1, 1), bars=bars))
		fills = [self.queue.get() for _ in range(self.queue.qsize())]
		self.assertEqual(len(fills), 1)
		self.assertEqual(fills[0].order_id, 2)
```

Note: orders use `exchange='simulated'` so the handler routes to the `simulated` exchange (`exchanges` dict key).

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest test/test_execution_handler/test_execution_handler_routing.py -v`
Expected: FAIL — `on_order` currently calls `exchange.execute_order` (a STOP would wrongly fill), and `on_market_data` does not exist.

- [ ] **Step 3: Update `ExecutionHandler.on_order` and add `on_market_data`**

In `itrader/execution_handler/execution_handler.py`, replace the body of `on_order` so it delegates to `exchange.on_order` (the router), and add `on_market_data`:

```python
	def on_order(self, event: OrderEvent):
		"""Route an order event to the configured exchange's order router."""
		try:
			exchange = self.exchanges.get(event.exchange)
			if not exchange:
				self.logger.error('Unknown exchange specified: %s for order %s %s',
								event.exchange, event.ticker, event.action)
				return
			exchange.on_order(event)
		except Exception as e:
			self.logger.error('Unexpected error routing order for %s %s: %s',
							 event.ticker, event.action, str(e), exc_info=True)

	def on_market_data(self, bar):
		"""Drive resting-order matching on each exchange with a new bar."""
		for name, exchange in self.exchanges.items():
			if exchange is None:
				continue
			try:
				exchange.on_market_data(bar)
			except Exception as e:
				self.logger.error('Error matching resting orders on %s: %s',
								 name, str(e), exc_info=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest test/test_execution_handler/test_execution_handler_routing.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add itrader/execution_handler/execution_handler.py test/test_execution_handler/test_execution_handler_routing.py
git commit -m "feat: ExecutionHandler routes orders via exchange.on_order and adds on_market_data"
```

---

## Task 12: `OrderManager` — bracket tagging + emit OrderEvents for all legs

**Files:**
- Modify: `itrader/order_handler/order_manager.py` (`create_orders_from_signal`, `_create_stop_loss_order`, `_create_take_profit_order`)
- Test: `test/test_order_handler/test_order_manager.py` (add a class)

Context: After this task, `process_signal` returns `OperationResult`s whose `order_events` include **all** legs (primary + SL + TP), each tagged. The order handler already enqueues every `result.order_events` (`order_handler.py:112-116`), so no handler change is needed for emission.

- [ ] **Step 1: Write the failing test**

Append to `test/test_order_handler/test_order_manager.py` (reuse the file's existing fixtures if present; otherwise this self-contained class works):

```python
class TestOrderManagerBracketEmission(unittest.TestCase):
	def setUp(self):
		from queue import Queue
		from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
		from itrader.order_handler.order_handler import OrderHandler
		from itrader.order_handler.storage import OrderStorageFactory
		from itrader.events_handler.event import SignalEvent
		from itrader.core.enums import OrderType
		import pandas as pd
		from datetime import datetime
		self.SignalEvent = SignalEvent
		self.OrderType = OrderType
		self.queue = Queue()
		self.ptf_handler = PortfolioHandler(self.queue)
		self.storage = OrderStorageFactory.create('test')
		self.handler = OrderHandler(self.queue, self.ptf_handler, self.storage)
		self.portfolio_id = self.ptf_handler.add_portfolio(1, 'p', 'default', 100000)

	def _signal(self, stop_loss=0.0, take_profit=0.0):
		return self.SignalEvent(
			time=__import__('datetime').datetime(2024, 1, 1), order_type='MARKET',
			ticker='BTCUSDT', action='BUY', price=40.0, quantity=1.0,
			stop_loss=stop_loss, take_profit=take_profit, strategy_id=1,
			portfolio_id=self.portfolio_id, strategy_setting={})

	def test_bracket_legs_emitted_and_linked(self):
		self.handler.on_signal(self._signal(stop_loss=30.0, take_profit=55.0))
		events = [self.queue.get() for _ in range(self.queue.qsize())]
		order_events = [e for e in events if getattr(e, 'order_type', None) is not None
		                and e.type.name == 'ORDER']
		types = sorted(e.order_type.name for e in order_events)
		self.assertEqual(types, ['LIMIT', 'MARKET', 'STOP'])
		primary = next(e for e in order_events if e.order_type == self.OrderType.MARKET)
		children = [e for e in order_events if e.order_type != self.OrderType.MARKET]
		for child in children:
			self.assertEqual(child.parent_order_id, primary.order_id)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest "test/test_order_handler/test_order_manager.py::TestOrderManagerBracketEmission" -v`
Expected: FAIL — currently SL/TP create no `order_events` (they only rest in storage) and `parent_order_id` is unset.

- [ ] **Step 3: Tag brackets and emit events for SL/TP**

In `order_manager.py`, `create_orders_from_signal`, capture the primary order id and pass it to the SL/TP creators. Change the SL/TP calls (lines ~558-565) to:

```python
				# Primary order id for bracket linkage
				primary_order_ids = primary_order_result.affected_order_ids
				parent_id = primary_order_ids[0] if primary_order_ids else None

				# 2. Create stop-loss order if specified
				if signal_event.stop_loss > 0:
					sl_result = self._create_stop_loss_order(signal_event, exchange, parent_id)
					results.append(sl_result)

				# 3. Create take-profit order if specified
				if signal_event.take_profit > 0:
					tp_result = self._create_take_profit_order(signal_event, exchange, parent_id)
					results.append(tp_result)
```

In `_create_stop_loss_order`, change the signature and tag + emit. Replace the method body's order-creation/return with:

```python
	def _create_stop_loss_order(self, signal_event: SignalEvent, exchange: str,
	                            parent_id: int = None) -> OperationResult:
		try:
			sl_order = Order.new_stop_order(
				time=signal_event.time,
				ticker=signal_event.ticker,
				action='BUY' if signal_event.action == 'SELL' else 'SELL',
				price=signal_event.stop_loss,
				quantity=signal_event.quantity,
				exchange=exchange,
				strategy_id=signal_event.strategy_id,
				portfolio_id=signal_event.portfolio_id
			)
			sl_order.parent_order_id = parent_id
			self.order_storage.add_order(sl_order)
			order_event = OrderEvent.new_order_event(sl_order)
			self.logger.debug(f'Stop-loss order created: {sl_order.ticker} at {sl_order.price}')
			return OperationResult.success_result(
				f"Stop-loss order created: {sl_order.ticker} at {sl_order.price}",
				order_events=[order_event],
				operation_type="create_stop_loss",
				affected_order_ids=[sl_order.id]
			)
		except Exception as e:
			return OperationResult.failure_result(
				f"Error creating stop-loss order: {e}",
				error_details=str(e), operation_type="create_stop_loss")
```

Apply the identical change to `_create_take_profit_order` (signature `(..., parent_id: int = None)`, set `tp_order.parent_order_id = parent_id`, and add `order_events=[OrderEvent.new_order_event(tp_order)]` to its success result).

Ensure `OrderEvent` is imported in `order_manager.py` (it already is, line 20).

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest "test/test_order_handler/test_order_manager.py::TestOrderManagerBracketEmission" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add itrader/order_handler/order_manager.py test/test_order_handler/test_order_manager.py
git commit -m "feat: OrderManager tags SL/TP brackets and emits OrderEvents for all legs (B5)"
```

---

## Task 13: `OrderManager` cancel/modify emit command events

**Files:**
- Modify: `itrader/order_handler/order_manager.py` (`modify_order`, `cancel_order`)
- Test: `test/test_order_handler/test_order_manager.py`

- [ ] **Step 1: Write the failing test**

Append to `test/test_order_handler/test_order_manager.py` (reuse `TestOrderManagerBracketEmission.setUp` style):

```python
class TestOrderManagerCommands(unittest.TestCase):
	def setUp(self):
		from queue import Queue
		from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
		from itrader.order_handler.order_handler import OrderHandler
		from itrader.order_handler.storage import OrderStorageFactory
		from itrader.events_handler.event import SignalEvent
		self.SignalEvent = SignalEvent
		self.queue = Queue()
		self.ptf_handler = PortfolioHandler(self.queue)
		self.storage = OrderStorageFactory.create('test')
		self.handler = OrderHandler(self.queue, self.ptf_handler, self.storage)
		self.portfolio_id = self.ptf_handler.add_portfolio(1, 'p', 'default', 100000)

	def _rest_a_stop(self):
		# Create a resting stop directly in storage via the manager's creator path.
		from itrader.order_handler.order import Order
		order = Order.new_stop_order(
			time=__import__('datetime').datetime(2024, 1, 1), ticker='BTCUSDT',
			action='SELL', price=30.0, quantity=1.0, exchange='default',
			strategy_id=1, portfolio_id=self.portfolio_id)
		self.storage.add_order(order)
		return order

	def test_cancel_emits_cancel_command(self):
		order = self._rest_a_stop()
		ok = self.handler.cancel_order(order.id, self.portfolio_id)
		self.assertTrue(ok)
		events = [self.queue.get() for _ in range(self.queue.qsize())]
		order_events = [e for e in events if e.type.name == 'ORDER']
		self.assertEqual(len(order_events), 1)
		from itrader.core.enums import OrderCommand
		self.assertIs(order_events[0].command, OrderCommand.CANCEL)
		self.assertEqual(order_events[0].order_id, order.id)

	def test_modify_emits_modify_command(self):
		order = self._rest_a_stop()
		ok = self.handler.modify_order(order.id, new_price=28.0, portfolio_id=self.portfolio_id)
		self.assertTrue(ok)
		events = [self.queue.get() for _ in range(self.queue.qsize())]
		order_events = [e for e in events if e.type.name == 'ORDER']
		from itrader.core.enums import OrderCommand
		self.assertIs(order_events[0].command, OrderCommand.MODIFY)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest "test/test_order_handler/test_order_manager.py::TestOrderManagerCommands" -v`
Expected: FAIL — events currently carry `command=NEW` (default in `new_order_event`).

- [ ] **Step 3: Pass the command when building cancel/modify events**

In `order_manager.py`, import `OrderCommand`:

```python
from ..core.enums import OrderType, OrderStatus, OrderCommand
```

In `cancel_order`, change the event creation (line ~868) to:

```python
				order_event = OrderEvent.new_order_event(order, command=OrderCommand.CANCEL)
```

In `modify_order`, change the event creation (line ~812) to:

```python
				order_event = OrderEvent.new_order_event(order, command=OrderCommand.MODIFY)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest "test/test_order_handler/test_order_manager.py::TestOrderManagerCommands" -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add itrader/order_handler/order_manager.py test/test_order_handler/test_order_manager.py
git commit -m "fix: cancel/modify emit command OrderEvents, not phantom NEW orders (B2)"
```

---

## Task 14: Reconciliation — `OrderManager.on_fill` and `OrderHandler.on_fill`

**Files:**
- Modify: `itrader/order_handler/order_manager.py` (add `on_fill`)
- Modify: `itrader/order_handler/order_handler.py` (add `on_fill`)
- Test: `test/test_order_handler/test_order_manager.py`

- [ ] **Step 1: Write the failing test**

Append to `test/test_order_handler/test_order_manager.py` (reuse `TestOrderManagerCommands.setUp` style — copy its `setUp` and `_rest_a_stop` into this class):

```python
class TestOrderManagerReconciliation(unittest.TestCase):
	def setUp(self):
		from queue import Queue
		from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
		from itrader.order_handler.order_handler import OrderHandler
		from itrader.order_handler.storage import OrderStorageFactory
		self.queue = Queue()
		self.ptf_handler = PortfolioHandler(self.queue)
		self.storage = OrderStorageFactory.create('test')
		self.handler = OrderHandler(self.queue, self.ptf_handler, self.storage)
		self.portfolio_id = self.ptf_handler.add_portfolio(1, 'p', 'default', 100000)

	def _rest_a_stop(self):
		from itrader.order_handler.order import Order
		order = Order.new_stop_order(
			time=__import__('datetime').datetime(2024, 1, 1), ticker='BTCUSDT',
			action='SELL', price=30.0, quantity=1.0, exchange='default',
			strategy_id=1, portfolio_id=self.portfolio_id)
		self.storage.add_order(order)
		return order

	def _fill(self, order, status):
		from itrader.events_handler.event import FillEvent
		oe_like = type('OE', (), {})()  # not needed; build via new_fill from order-like
		from itrader.events_handler.event import OrderEvent
		from itrader.core.enums import OrderType
		oe = OrderEvent(time=order.time, ticker=order.ticker, action=order.action,
		                price=order.price, quantity=order.quantity, exchange=order.exchange,
		                strategy_id=order.strategy_id, portfolio_id=order.portfolio_id,
		                order_type=OrderType.STOP, order_id=order.id)
		return FillEvent.new_fill(status, 0.0, oe)

	def test_executed_fill_marks_order_filled(self):
		from itrader.core.enums import OrderStatus
		order = self._rest_a_stop()
		self.handler.on_fill(self._fill(order, 'EXECUTED'))
		stored = self.storage.get_order_by_id(order.id, self.portfolio_id)
		self.assertEqual(stored.status, OrderStatus.FILLED)

	def test_cancelled_fill_marks_order_cancelled(self):
		from itrader.core.enums import OrderStatus
		order = self._rest_a_stop()
		self.handler.on_fill(self._fill(order, 'CANCELLED'))
		stored = self.storage.get_order_by_id(order.id, self.portfolio_id)
		self.assertEqual(stored.status, OrderStatus.CANCELLED)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest "test/test_order_handler/test_order_manager.py::TestOrderManagerReconciliation" -v`
Expected: FAIL — `OrderHandler` has no `on_fill`.

- [ ] **Step 3: Implement `OrderManager.on_fill`**

Add to `OrderManager` (uses `FillStatus`; import it):

At the top of `order_manager.py` add:

```python
from ..events_handler.event import BarEvent, OrderEvent, SignalEvent, FillEvent, FillStatus
```

(Extend the existing event import line rather than duplicating.)

Add the method:

```python
	def on_fill(self, fill_event: FillEvent) -> None:
		"""
		Reconcile the order mirror against an exchange fill.

		EXECUTED -> mark the order FILLED; CANCELLED -> mark CANCELLED.
		Then deactivate it from the active book (kept in all_orders for audit).
		"""
		order_id = getattr(fill_event, 'order_id', None)
		if order_id is None:
			return
		order = self.order_storage.get_order_by_id(order_id, fill_event.portfolio_id)
		if order is None:
			return
		try:
			if fill_event.status == FillStatus.EXECUTED:
				order.add_fill(order.remaining_quantity, fill_event.price,
				               fill_event.time, "exchange fill")
			elif fill_event.status == FillStatus.CANCELLED:
				order.cancel_order("OCO / cancellation")
			self.order_storage.update_order(order)
			self.order_storage.deactivate_order(order.id, order.portfolio_id)
		except Exception as e:
			self.logger.error('Error reconciling fill for order %s: %s', order_id, e)
```

- [ ] **Step 4: Implement `OrderHandler.on_fill` (delegate)**

Add to `OrderHandler` in `order_handler.py` (tabs):

```python
	def on_fill(self, fill_event):
		"""Reconcile the order mirror from an exchange fill event."""
		self.order_manager.on_fill(fill_event)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `poetry run pytest "test/test_order_handler/test_order_manager.py::TestOrderManagerReconciliation" -v`
Expected: PASS (2 tests).

- [ ] **Step 6: Commit**

```bash
git add itrader/order_handler/order_manager.py itrader/order_handler/order_handler.py test/test_order_handler/test_order_manager.py
git commit -m "feat: OrderManager.on_fill reconciles order mirror from exchange fills"
```

---

## Task 15: Delete matching logic from `OrderManager` / `OrderHandler`

**Files:**
- Modify: `itrader/order_handler/order_manager.py` (delete methods + state)
- Modify: `itrader/order_handler/order_handler.py` (delete `process_orders_on_market_data`)

- [ ] **Step 1: Delete the matching methods in `OrderManager`**

Remove these methods entirely (they are now the exchange's job): `process_orders_on_market_data`, `process_market_orders_immediately`, `queue_market_orders_for_next_bar`, `_process_queued_market_orders`, `_check_and_trigger_conditional_orders`, `_process_market_orders`, `_should_trigger_order`, `_get_fill_reason`, `_process_order_fills`, `_generate_order_events`, `_cleanup_filled_orders`, `_deactivate_filled_order`, `_handle_oco_order_fill`.

In `__init__`, delete the now-unused state lines:

```python
		self.processed_fills = []
		self.pending_events = []
		self.queued_market_orders = []  # For next_bar execution
```

- [ ] **Step 2: Remove the immediate/next-bar block from `create_orders_from_signal`**

In `create_orders_from_signal`, delete the entire step-4 block (lines ~567-583: the `if (signal_event.order_type.upper() == 'MARKET' and self.market_execution == "immediate" ...)` / `elif ... "next_bar" ...`). Market execution timing now lives in the exchange; `OrderManager` just emits the `OrderEvent(NEW)` (already done in `_create_primary_order`). Leave the rest of the method intact.

- [ ] **Step 3: Delete `OrderHandler.process_orders_on_market_data`**

Remove the `process_orders_on_market_data` method from `order_handler.py` (lines ~73-90).

- [ ] **Step 4: Verify nothing else references the deleted symbols**

Run:

```bash
grep -rn "process_orders_on_market_data\|queue_market_orders_for_next_bar\|process_market_orders_immediately\|_handle_oco_order_fill\|_should_trigger_order" itrader/
```

Expected: only matches inside `full_event_handler.py` (fixed in Task 17) — no other production references. If any other reference appears, update it.

- [ ] **Step 5: Run the order-handler suite (expect known failures in old stop/limit test)**

Run: `poetry run pytest test/test_order_handler/ -v`
Expected: New manager tests PASS. `test_stop_limit_orders.py` will FAIL (it calls the deleted `process_orders_on_market_data`) — that file is rewritten in Task 18. Other order tests should pass; if a test referenced deleted internals, note it for Task 18.

- [ ] **Step 6: Commit**

```bash
git add itrader/order_handler/order_manager.py itrader/order_handler/order_handler.py
git commit -m "refactor: remove matching/self-fill logic from OrderManager (B4)"
```

---

## Task 16: Portfolio `on_fill` guards on EXECUTED

**Files:**
- Modify: `itrader/portfolio_handler/portfolio_handler.py` (`on_fill`, ~line 236, **spaces**)
- Test: `test/test_portfolio_handler/test_on_fill_status_guard.py`

- [ ] **Step 1: Write the failing test**

Create `test/test_portfolio_handler/test_on_fill_status_guard.py`:

```python
import unittest
from datetime import datetime
from queue import Queue

from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.events_handler.event import OrderEvent, FillEvent
from itrader.core.enums import OrderType


class TestOnFillStatusGuard(unittest.TestCase):
	def setUp(self):
		self.queue = Queue()
		self.ptf = PortfolioHandler(self.queue)
		self.pid = self.ptf.add_portfolio(1, 'p', 'default', 100000)

	def _fill(self, status):
		oe = OrderEvent(time=datetime(2024, 1, 1), ticker='BTCUSDT', action='BUY',
		                price=40.0, quantity=1.0, exchange='default', strategy_id=1,
		                portfolio_id=self.pid, order_type=OrderType.MARKET, order_id=1)
		return FillEvent.new_fill(status, 0.0, oe)

	def test_cancelled_fill_creates_no_transaction(self):
		portfolio = self.ptf.get_portfolio(self.pid)
		before = portfolio.cash if hasattr(portfolio, 'cash') else None
		result = self.ptf.on_fill(self._fill('CANCELLED'))
		self.assertFalse(result)  # ignored
		# No position opened for BTCUSDT
		self.assertNotIn('BTCUSDT', getattr(portfolio.position_manager, 'positions', {}))
```

Note: if `portfolio.position_manager.positions` is not the exact accessor, adjust to the project's position lookup; the key assertion is that a CANCELLED fill opens no position. Confirm the accessor with `grep -rn "def positions\|self.positions" itrader/portfolio_handler/` before finalizing the assert.

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest test/test_portfolio_handler/test_on_fill_status_guard.py -v`
Expected: FAIL — `on_fill` currently transacts regardless of status (returns truthy / opens a position).

- [ ] **Step 3: Add the status guard**

In `portfolio_handler.py` `on_fill` (spaces), add the guard immediately inside the `try:` (after `portfolio_id = int(...)` is fine, but before building the transaction). Add an import for `FillStatus` at the top of the file (`from itrader.events_handler.event import FillStatus` — confirm import path/style used in this module) and insert:

```python
                if fill_event.status != FillStatus.EXECUTED:
                    self.logger.debug(
                        "Ignoring non-executed fill",
                        status=str(fill_event.status),
                        ticker=fill_event.ticker,
                        correlation_id=correlation_id,
                    )
                    return False
```

Place it right after `portfolio = self.get_portfolio(portfolio_id)` so cancelled/refused fills short-circuit before transacting.

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest test/test_portfolio_handler/test_on_fill_status_guard.py -v`
Expected: PASS.

- [ ] **Step 5: Run the full portfolio suite for regressions**

Run: `make test-portfolio`
Expected: PASS (existing fills are EXECUTED, so unaffected).

- [ ] **Step 6: Commit**

```bash
git add itrader/portfolio_handler/portfolio_handler.py test/test_portfolio_handler/test_on_fill_status_guard.py
git commit -m "fix: portfolio.on_fill only transacts EXECUTED fills"
```

---

## Task 17: Wire events in `full_event_handler`

**Files:**
- Modify: `itrader/events_handler/full_event_handler.py` (`process_events`, ~lines 70-80)
- Test: `test/test_events/test_event_wiring.py`

- [ ] **Step 1: Write the failing test**

Create `test/test_events/test_event_wiring.py`:

```python
import unittest
from unittest.mock import MagicMock
import queue

from itrader.events_handler.full_event_handler import EventHandler
from itrader.events_handler.event import EventType


class TestEventWiring(unittest.TestCase):
	def setUp(self):
		self.q = queue.Queue()
		self.strategies = MagicMock()
		self.screeners = MagicMock()
		self.portfolio = MagicMock()
		self.order = MagicMock()
		self.execution = MagicMock()
		self.universe = MagicMock()
		self.handler = EventHandler(
			self.strategies, self.screeners, self.portfolio, self.order,
			self.execution, self.universe, self.q)

	def _put(self, event_type):
		ev = MagicMock()
		ev.type = event_type
		self.q.put(ev)
		return ev

	def test_bar_routes_to_execution_market_data(self):
		ev = self._put(EventType.BAR)
		self.handler.process_events()
		self.execution.on_market_data.assert_called_once_with(ev)
		self.order.process_orders_on_market_data.assert_not_called()

	def test_fill_routes_to_portfolio_and_order(self):
		ev = self._put(EventType.FILL)
		self.handler.process_events()
		self.portfolio.on_fill.assert_called_once_with(ev)
		self.order.on_fill.assert_called_once_with(ev)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `poetry run pytest test/test_events/test_event_wiring.py -v`
Expected: FAIL — BAR still calls `order.process_orders_on_market_data`; FILL does not call `order.on_fill`.

- [ ] **Step 3: Update `process_events`**

In `full_event_handler.py`, change the BAR and FILL branches (tabs):

```python
				elif event.type == EventType.BAR:
					self.portfolio_handler.update_portfolios_market_value(event)
					self.execution_handler.on_market_data(event)
					self.strategies_handler.calculate_signals(event)
				elif event.type == EventType.SIGNAL:
					self.order_handler.on_signal(event)
				elif event.type == EventType.ORDER:
					self.execution_handler.on_order(event)
				elif event.type == EventType.FILL:
					self.portfolio_handler.on_fill(event)
					self.order_handler.on_fill(event)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `poetry run pytest test/test_events/test_event_wiring.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add itrader/events_handler/full_event_handler.py test/test_events/test_event_wiring.py
git commit -m "feat: route BAR to execution.on_market_data and FILL to order_handler.on_fill"
```

---

## Task 18: Rewrite `test_stop_limit_orders.py` for the new flow + full regression

**Files:**
- Rewrite: `test/test_order_handler/test_stop_limit_orders.py`
- Test: full suites

The old file drove triggers through `order_handler.process_orders_on_market_data` (deleted). The new end-to-end path is: `OrderManager` emits resting `OrderEvent`s → `ExecutionHandler.on_order` rests them → `ExecutionHandler.on_market_data(bar)` fills them.

- [ ] **Step 1: Replace the file with the new end-to-end flow**

Overwrite `test/test_order_handler/test_stop_limit_orders.py`:

```python
import unittest
import pandas as pd
from datetime import datetime
from queue import Queue

from itrader.order_handler.order_handler import OrderHandler
from itrader.execution_handler.execution_handler import ExecutionHandler
from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.order_handler.storage import OrderStorageFactory
from itrader.events_handler.event import SignalEvent, BarEvent, FillStatus, EventType
from itrader.core.enums import OrderType


class TestStopLimitEndToEnd(unittest.TestCase):
	"""Resting stop/limit orders are matched by the exchange on new bars."""

	def setUp(self):
		self.queue = Queue()
		self.ptf = PortfolioHandler(self.queue)
		self.storage = OrderStorageFactory.create('test')
		self.order_handler = OrderHandler(self.queue, self.ptf, self.storage)
		self.execution = ExecutionHandler(self.queue)
		exchange = self.execution.exchanges['simulated']
		exchange.connect()
		exchange.update_config(supported_symbols={'BTCUSDT'})
		self.pid = self.ptf.add_portfolio(1, 'p', 'simulated', 100000)

	def _signal(self, action, order_type='MARKET', price=40.0, stop_loss=0.0, take_profit=0.0):
		return SignalEvent(
			time=datetime(2024, 1, 1), order_type=order_type, ticker='BTCUSDT',
			action=action, price=price, quantity=1.0, stop_loss=stop_loss,
			take_profit=take_profit, strategy_id=1, portfolio_id=self.pid,
			strategy_setting={})

	def _bar(self, open_, high, low, close):
		bars = {'BTCUSDT': pd.DataFrame(
			{'open': [open_], 'high': [high], 'low': [low], 'close': [close], 'volume': [1]})}
		return BarEvent(time=datetime(2024, 1, 1), bars=bars)

	def _route_orders(self):
		"""Drain ORDER events from the queue into the execution handler."""
		pending = []
		while not self.queue.empty():
			pending.append(self.queue.get())
		for ev in pending:
			if ev.type == EventType.ORDER:
				self.execution.on_order(ev)

	def test_stop_loss_rests_then_fills_on_breach(self):
		# Enter long with a stop-loss at 30; route the resting orders.
		self.order_handler.on_signal(self._signal('BUY', stop_loss=30.0))
		self._route_orders()
		# A bar whose low pierces 30 should fill the stop.
		self.execution.on_market_data(self._bar(open_=38, high=39, low=20, close=25))
		fills = []
		while not self.queue.empty():
			ev = self.queue.get()
			if ev.type == EventType.FILL:
				fills.append(ev)
		executed = [f for f in fills if f.status == FillStatus.EXECUTED]
		# One EXECUTED fill for the SELL stop (the BUY market filled+drained earlier).
		self.assertTrue(any(f.action == 'SELL' for f in executed))

	def test_take_profit_fill_cancels_stop_via_oco(self):
		self.order_handler.on_signal(self._signal('BUY', stop_loss=30.0, take_profit=55.0))
		self._route_orders()
		# Bar pierces the TP (high 60 >= 55) but not the SL (low 40 > 30).
		self.execution.on_market_data(self._bar(open_=50, high=60, low=40, close=58))
		statuses = []
		while not self.queue.empty():
			ev = self.queue.get()
			if ev.type == EventType.FILL:
				statuses.append((ev.action, ev.status))
		# Exactly one EXECUTED (the TP) and one CANCELLED (the SL) among SELL legs.
		self.assertIn(('SELL', FillStatus.EXECUTED), statuses)
		self.assertIn(('SELL', FillStatus.CANCELLED), statuses)

	def test_stop_does_not_fill_when_not_breached(self):
		self.order_handler.on_signal(self._signal('BUY', stop_loss=30.0))
		self._route_orders()
		self.execution.on_market_data(self._bar(open_=40, high=45, low=35, close=42))
		fills = []
		while not self.queue.empty():
			ev = self.queue.get()
			if ev.type == EventType.FILL and ev.action == 'SELL':
				fills.append(ev)
		self.assertEqual(fills, [])
```

- [ ] **Step 2: Run the rewritten file**

Run: `poetry run pytest test/test_order_handler/test_stop_limit_orders.py -v`
Expected: PASS (3 tests).

- [ ] **Step 3: Run the full order + execution + portfolio + events suites**

Run:

```bash
make test-orders
make test-execution
make test-portfolio
make test-events
```

Expected: PASS. If a residual test references a deleted method (e.g. `test_order_handler.py` calling `process_orders_on_market_data` or a removed internal), update it to the new flow using the patterns in this file, then re-run.

- [ ] **Step 4: Run the entire suite**

Run: `make test`
Expected: PASS. Investigate and fix any failure before proceeding (do not skip).

- [ ] **Step 5: Commit**

```bash
git add test/
git commit -m "test: rewrite stop/limit tests for exchange-matched flow; full regression green"
```

---

## Self-Review

**Spec coverage:**
- Extract pure `MatchingEngine` (Approach B) → Tasks 5-8. ✓
- Exchange-enforced OCO, handler declares bracket → Task 8 (engine), Task 12 (tagging). ✓
- Bar routed via queue → execution.on_market_data → exchange → Tasks 10, 11, 17. ✓
- Intrabar high/low + pessimistic gap + stop-before-limit → Tasks 6, 8. ✓
- Schema: OrderEvent type/id fix + command + parent (B1/B2) → Task 3; FillStatus.CANCELLED + FillEvent.order_id → Task 4; BarEvent high/low → Task 2; OrderCommand → Task 1. ✓
- Slim OrderManager, on_fill reconciliation → Tasks 14, 15. ✓
- Portfolio EXECUTED guard → Task 16. ✓
- Remove broad except / per-order matching safety (B6) → Task 6/8 (`on_bar` per-order try). ✓
- Execution timing moves to exchange → Task 9 (`execution_timing`, default immediate). ✓
- Testing TDD-first → every task. ✓

**Out of scope (per spec):** B7 timestamps; live adapters; OTO entry-activation. Not planned. ✓

**Placeholder scan:** No TBD/TODO; all code blocks complete. Two assertions flagged for accessor confirmation (Task 16 positions accessor) include the exact `grep` to verify — acceptable since they name the verification step.

**Type/name consistency:** `MatchingEngine.on_bar -> (List[FillDecision], List[CancelDecision])`, `FillDecision.order_event/fill_quantity/fill_price/reason`, `CancelDecision.order_event/reason`, `OrderEvent.command/parent_order_id/order_id`, `FillEvent.order_id`, `OrderCommand.NEW/CANCEL/MODIFY`, `FillStatus.EXECUTED/CANCELLED` — used consistently across Tasks 3-17. Exchange exposes `on_order`, `on_market_data`, `matching_engine`, `execution_timing`, `_emit_fill` — referenced consistently.
