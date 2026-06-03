# Testing Patterns

**Analysis Date:** 2026-06-03

## Test Framework

**Runner:**
- pytest 8.3.3+
- Config: `pyproject.toml` under `[tool.pytest.ini_options]`

**Assertion Library:**
- `unittest.TestCase` assertions (`assertEqual`, `assertIsInstance`, `assertRaises`, etc.) — primary style in most files
- pytest-native `assert` statements — used in newer test files (`test_order.py`, `test_order_validator.py`, `test_simulated_exchange.py`)

**Run Commands:**
```bash
poetry run pytest test/ -v            # Run all tests
make test                             # Same via Makefile
make test-unit                        # Only -m "unit" marked tests
make test-integration                 # Only -m "integration" marked tests
make test-portfolio                   # test/test_portfolio_handler/
make test-orders                      # test/test_order_handler/
make test-execution                   # test/test_execution_handler/
make test-events                      # test/test_events/
make test-strategy                    # test/test_strategy/
make test-cov                         # Coverage + open htmlcov/index.html
make test-watch                       # pytest-watch (continuous)
poetry run pytest test/path/test_file.py -v           # Single file
poetry run pytest test/path/test_file.py -k "name" -v # Single test
```

## Test File Organization

**Location:** All tests are in a top-level `test/` directory — NOT co-located with source.

**Naming:**
- Files: `test_<module>.py` — mirrors the source module name
- Classes: `Test<SubjectDescription>` (e.g., `TestOrderLifecycle`, `TestMatchingEngineStopTriggers`)
- Functions: `test_<behavior_being_tested>` — descriptive names

**Directory structure mirrors source packages:**
```
test/
├── test_events/                    # → itrader/events_handler/
│   ├── test_events.py
│   ├── test_event_wiring.py
│   ├── test_bar_event_ohlc.py
│   ├── test_fill_event_schema.py
│   └── test_order_event_schema.py
├── test_execution_handler/         # → itrader/execution_handler/
│   ├── test_execution_handler.py
│   ├── test_execution_handler_routing.py
│   ├── test_matching_engine.py
│   └── test_exchanges/
│       └── test_simulated_exchange.py
├── test_order_handler/             # → itrader/order_handler/
│   ├── test_order.py
│   ├── test_order_handler.py
│   ├── test_order_manager.py
│   ├── test_order_storage.py
│   ├── test_order_validator.py
│   ├── test_on_signal.py
│   ├── test_stop_limit_orders.py
│   └── test_order_command_enum.py
├── test_portfolio_handler/         # → itrader/portfolio_handler/
│   ├── test_portfolio.py
│   ├── test_portfolio_handler.py
│   ├── test_portfolio_update.py
│   ├── test_cash_manager.py
│   ├── test_metrics_manager.py
│   ├── test_position_manager.py
│   ├── test_transaction_manager.py
│   └── test_on_fill_status_guard.py
├── test_positions/                 # Position model tests
├── test_strategy/                  # Strategy tests
└── test_transaction/               # Transaction model tests
```

No `conftest.py` files exist anywhere — all fixtures are defined locally within each test file.

## Test Structure

**Legacy style (unittest.TestCase) — most files:**
```python
import unittest
from datetime import datetime
from unittest.mock import Mock

from itrader.portfolio_handler.portfolio_handler import PortfolioHandler
from itrader.events_handler.event import FillEvent, FillStatus


class TestOnFillStatusGuard(unittest.TestCase):

    def setUp(self):
        """Set up shared test state — runs before each test method."""
        self.queue = Queue()
        self.ptf = PortfolioHandler(self.queue)
        self.pid = self.ptf.add_portfolio(1, 'p', 'default', 100000)

    def test_executed_fill_is_processed(self):
        result = self.ptf.on_fill(self._fill('EXECUTED'))
        self.assertTrue(result)
        portfolio = self.ptf.get_portfolio(self.pid)
        self.assertEqual(len(portfolio.positions), 1)

if __name__ == "__main__":
    unittest.main()
```

**Class-level shared setup (for expensive objects shared across all methods):**
```python
class TestExecutionHandlerUpdates(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        """Runs once before any test in the class."""
        cls.queue = Queue()
        cls.execution_handler = ExecutionHandler(cls.queue)

    def setUp(self):
        """Runs before each test method — for per-test state."""
        self.order_event = OrderEvent(...)
```

**Newer pytest style (no TestCase base) — newer test files:**
```python
import pytest
from unittest.mock import Mock

class TestOrderLifecycle:

    def setup_method(self):
        """pytest equivalent of setUp — runs before each test."""
        self.base_time = datetime.now()

    def create_test_order(self, **kwargs) -> Order:
        """Builder helper — creates test objects with sane defaults."""
        defaults = {
            'time': self.base_time,
            'type': OrderType.MARKET,
            'status': OrderStatus.PENDING,
            'ticker': 'AAPL',
            'action': 'BUY',
            'price': 150.0,
            'quantity': 100.0,
            'exchange': 'NYSE',
            'strategy_id': 1,
            'portfolio_id': 1
        }
        defaults.update(kwargs)
        return Order(**defaults)

    def test_order_creation_with_state_tracking(self):
        order = self.create_test_order()
        assert order.status == OrderStatus.PENDING
        assert order.created_at is not None
```

**Choose style to match the file:** If the existing file uses `unittest.TestCase`, keep using it. If it uses plain pytest classes with `setup_method`, keep that pattern.

## Mocking

**Framework:** `unittest.mock` from the standard library — `Mock`, `MagicMock`, `patch`

**Dependency injection mock (most common):**
```python
from unittest.mock import Mock

class TestEnhancedOrderValidator:
    def setup_method(self):
        self.portfolio_handler = Mock()
        mock_portfolio = Mock()
        mock_portfolio.cash = 20000.0
        mock_portfolio.positions = {}
        mock_portfolio.exchange = "NYSE"
        self.portfolio_handler.get_portfolio.return_value = mock_portfolio
        
        self.validator = EnhancedOrderValidator(self.portfolio_handler)
```

**Module-level patch for import-side-effect isolation:**
```python
from unittest.mock import MagicMock, patch

_STUB_MODULES = {
    name: MagicMock()
    for name in [
        'itrader.strategy_handler.strategies_handler',
        'itrader.screeners_handler.screeners_handler',
    ]
}
with patch.dict(sys.modules, _STUB_MODULES):
    from itrader.events_handler.full_event_handler import EventHandler
```

**Concrete MockPortfolio classes** (used when `Mock()` is too loose):
```python
class MockPortfolio:
    """Mock portfolio for testing."""
    def __init__(self):
        self.portfolio_id = idgen.generate_portfolio_id()
```

**What to mock:**
- `portfolio_handler` when testing components that call `get_portfolio()`
- `logger` when testing components where logging would add noise
- Entire handler modules (via `patch.dict(sys.modules, ...)`) when the module has import-time side effects
- External services (no real HTTP/DB calls in the test suite)

**What NOT to mock:**
- `Queue()` — use a real `queue.Queue()` for integration-style tests
- `itrader.idgen` — use the real ID generator; tests rely on unique IDs
- Domain logic classes under test — test them directly

## Fixtures and Factories

No pytest `@fixture` decorators exist in the codebase. Test data is provided via:

**Builder helper methods (pytest-style classes):**
```python
def create_test_order(self, **kwargs) -> Order:
    defaults = {
        'time': self.base_time,
        'type': OrderType.MARKET,
        'status': OrderStatus.PENDING,
        'ticker': 'AAPL',
        'action': 'BUY',
        'price': 150.0,
        'quantity': 100.0,
        'exchange': 'NYSE',
        'strategy_id': 1,
        'portfolio_id': 1
    }
    defaults.update(kwargs)
    return Order(**defaults)
```

**Inline factory functions (module-level helpers):**
```python
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
```

**Location:** All test data builders are local to each test file. No shared fixtures directory.

## Error / Exception Testing

**unittest.TestCase style:**
```python
with self.assertRaises(InvalidTransactionError) as context:
    self.cash_manager.deposit(60000.0, "Large deposit")
self.assertIn("exceed maximum balance limit", str(context.exception))
```

**pytest style:**
```python
with pytest.raises(ValueError, match="Unknown configuration key"):
    exchange.update_config(unknown_param=True)
```

Use `self.assertRaises` in `unittest.TestCase` subclasses. Use `pytest.raises` in plain pytest-style test classes.

## Integration Test Pattern

End-to-end tests wire real handler instances around a real `Queue`, send events in, and drain the queue to assert on outputs:

```python
class TestStopLimitEndToEnd(unittest.TestCase):
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

    def _route_orders(self):
        """Drain ORDER events from the queue into the execution handler."""
        pending = []
        while not self.queue.empty():
            pending.append(self.queue.get())
        for ev in pending:
            if ev.type == EventType.ORDER:
                self.execution.on_order(ev)

    def _drain_fills(self):
        fills = []
        while not self.queue.empty():
            ev = self.queue.get()
            if ev.type == EventType.FILL:
                fills.append(ev)
        return fills
```

This pattern appears in `test/test_order_handler/test_stop_limit_orders.py` and `test/test_order_handler/test_order_manager.py`. Use it for any test that exercises multiple handlers together.

## Thread-Safety Testing

Tests in `test_portfolio_handler/test_cash_manager.py` verify concurrent operations with `threading`:

```python
def test_concurrent_deposits(self):
    results = []
    errors = []

    def deposit_worker():
        try:
            result = self.cash_manager.deposit(100.0, "Concurrent deposit")
            results.append(result)
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=deposit_worker) for _ in range(10)]
    for t in threads: t.start()
    for t in threads: t.join()

    self.assertEqual(len(errors), 0)
    self.assertEqual(len(results), 10)
```

## Coverage

**Requirements:** No enforced minimum. Coverage is optional/manual.

**View Coverage:**
```bash
make test-cov      # Runs pytest-cov and opens htmlcov/index.html
```

**Coverage tool:** `pytest-cov` 5.0+. Output directory: `htmlcov/` (gitignored).

## Markers

All markers are declared in `pyproject.toml`. Using an undeclared marker fails with `--strict-markers`:

| Marker | Purpose | Run command |
|--------|---------|-------------|
| `unit` | Pure unit tests | `make test-unit` |
| `integration` | Integration tests | `make test-integration` |
| `slow` | Slow tests | `poetry run pytest -m slow` |
| `portfolio` | Portfolio tests | `make test-portfolio` |
| `events` | Event handling tests | `make test-events` |
| `orders` | Order processing tests | `make test-orders` |
| `execution` | Execution tests | `make test-execution` |
| `strategy` | Strategy tests | `make test-strategy` |

**Important:** No test file currently uses `@pytest.mark.<marker>` decorators — the markers exist for filtering but are not applied to individual tests yet. Running `make test-unit` produces zero results; `make test` runs everything.

## Warning Policy

`pyproject.toml` sets `filterwarnings = ["error", "ignore::UserWarning", "ignore::DeprecationWarning"]`. Any unexpected Python warning becomes a test failure. When adding new dependencies or calling deprecated APIs, explicitly suppress the warning in `filterwarnings` or fix the root cause.

## Test Types

**Unit Tests (most files):**
- Test a single class or function in isolation
- External dependencies injected via `Mock()`
- Examples: `test_order.py`, `test_cash_manager.py`, `test_order_validator.py`, `test_matching_engine.py`

**Integration Tests:**
- Wire multiple real handlers together with a real `Queue`
- Examples: `test_stop_limit_orders.py`, `test_portfolio_handler.py`, `test_order_manager.py`

**E2E Tests:** Not present. The system has no automated end-to-end test runner covering a full backtest loop.

**Schema/Contract Tests:**
- Verify event dataclass fields and types match expected structure
- Examples: `test_events/test_fill_event_schema.py`, `test_events/test_order_event_schema.py`

---

*Testing analysis: 2026-06-03*
