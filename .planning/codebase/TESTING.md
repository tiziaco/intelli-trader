# Testing Patterns

**Analysis Date:** 2026-06-07

## Test Framework

**Runner:**
- pytest 8.4.2
- Config: `pyproject.toml` `[tool.pytest.ini_options]`

**Assertion Library:**
- pytest built-in assertions (`assert` statements)
- `pandas.testing.assert_frame_equal` for DataFrame comparisons in integration tests
- `pytest.approx` for floating-point tolerance (used sparingly in old portfolio tests)

**Run Commands:**
```bash
make test                # Run all tests (poetry run pytest tests/ -v)
make test-unit           # Only unit-marked tests (-m "unit")
make test-integration    # Only integration-marked tests (-m "integration")
make test-portfolio      # tests/unit/portfolio/ subtree
make test-orders         # tests/unit/order/ subtree
make test-execution      # tests/unit/execution/ subtree
make test-events         # tests/unit/events/ subtree
make test-strategy       # tests/unit/strategy/ subtree
make test-cov            # Coverage -> opens htmlcov/index.html
make test-watch          # pytest-watch file-watch mode
poetry run pytest test/path/test_file.py -v               # single file
poetry run pytest test/path/test_file.py -k "test_name" -v  # single test
```

## Test File Organization

**Location:**
- Separate `tests/` tree — NOT co-located with source
- Mirrors source structure: `itrader/order_handler/` → `tests/unit/order/`
- Integration tests: `tests/integration/`
- Unit tests: `tests/unit/<domain>/`
- Golden/frozen reference files: `tests/golden/` (trades.csv, equity.csv, summary.json)

**Naming:**
- `test_<module>.py` — mirrors the source module name
- Test functions: `test_<what_is_tested>()` — descriptive, behavior-focused

**Directory structure:**
```
tests/
├── conftest.py                    # Root: global_queue fixture, make_bar/make_bar_struct factories, auto-marker hook
├── golden/                        # Frozen oracle CSVs + summary.json (committed, never regenerated in tests)
│   ├── trades.csv
│   ├── equity.csv
│   └── summary.json
├── unit/
│   ├── conftest.py                # Unit-layer anchor (minimal — shared fixtures stay at root)
│   ├── config/
│   ├── core/
│   ├── events/
│   ├── execution/
│   │   └── exchanges/
│   ├── order/
│   ├── outils/
│   ├── portfolio/
│   │   ├── positions/
│   │   └── transaction/
│   ├── price/
│   └── strategy/
└── integration/
    ├── conftest.py                # golden_dir/golden_*_path fixtures, backtest_engine factory
    ├── test_backtest_oracle.py    # Golden-master oracle: full run vs frozen golden
    ├── test_backtest_smoke.py     # Smoke: import → construct → run → nonzero trade
    ├── test_event_wiring.py       # EventHandler routing (mock collaborators)
    ├── test_execution_handler_routing.py
    └── test_reservation_inertness.py  # Reservation gate inertness proof
```

## Test Markers

Markers are registered in `pyproject.toml` `[tool.pytest.ini_options] markers`. Never hand-add markers to test files — auto-marking applies via the root conftest hook.

**Folder-derived auto-marking (D-13/D-15):**
- `tests/unit/**` → `unit` marker applied automatically
- `tests/integration/**` → `integration` + `slow` markers applied automatically
- Source: `tests/conftest.py::pytest_collection_modifyitems`

**Registered markers:**
- `unit` — drives ONE collaborating component (may use real `global_queue` + several classes from its own domain; does NOT assert cross-component cascades)
- `integration` — asserts interaction ACROSS components (cross-domain, full cascade, smoke, oracle)
- `slow` — slow-running full-engine integration runs (auto-applied with `integration`)

**`--strict-markers` is enforced** — any unregistered marker fails collection.

**Explicit `pytestmark` usage:**
Some test files in `tests/unit/core/` and `tests/unit/price/` explicitly set `pytestmark = pytest.mark.unit` as a belt-and-suspenders declaration for Wave-0 scaffolds that predate the auto-marker:
```python
pytestmark = pytest.mark.unit
```

## Test Structure

**Suite Organization — function-style (dominant pattern):**
```python
# Module-level helper (not a fixture) for constructing test objects
def make_order_event(order_type, action, price, order_id, ticker="BTCUSDT", ...):
    return OrderEvent(...)

# Fixtures provide shared state
@pytest.fixture
def engine():
    return MatchingEngine()

# Test functions use descriptive names
def test_sell_stop_triggers_when_low_pierces(engine, make_bar):
    engine.submit(make_order_event(OrderType.STOP, "SELL", 30.0, order_id=1))
    fills, cancels = engine.on_bar(make_bar(open_=35, high=36, low=20, close=25))
    assert len(fills) == 1
    assert fills[0].fill_price == 30.0
```

**Suite Organization — class-style (used in `test_simulated_exchange.py` and `test_order.py`):**
```python
class TestSimulatedExchangeInitialization:
    """Group related tests with shared setup."""

    def setup_method(self):
        """Per-test setup (pytest calls this, no decorator needed)."""
        self.queue = Queue()
        self.base_time = datetime.now()

    def test_default_initialization(self):
        exchange = SimulatedExchange(self.queue)
        assert exchange.global_queue is self.queue
```

**Harness classes (complex setup encapsulation):**
```python
class _Harness:
    """OrderHandler + storage + one funded portfolio."""
    def __init__(self):
        self.queue = Queue()
        self.ptf_handler = PortfolioHandler(self.queue)
        self.storage = OrderStorageFactory.create("test")
        self.handler = OrderHandler(self.queue, self.ptf_handler, self.storage)
        self.portfolio_id = self.ptf_handler.add_portfolio(1, "p", "default", 100000)
    # ... helper methods

@pytest.fixture
def harness():
    h = _Harness()
    yield h
    while not h.queue.empty():   # teardown: drain queue
        h.queue.get_nowait()
```
Source: `tests/unit/order/test_order_manager.py:62`

**`SimpleNamespace` for fixture return values:**
```python
@pytest.fixture
def wiring():
    q = queue.Queue()
    handler = EventHandler(...)
    yield SimpleNamespace(q=q, handler=handler, put=put, strategies=strategies, ...)
    while not q.empty():       # teardown
        q.get_nowait()
```
Source: `tests/integration/test_event_wiring.py:37`

## Mocking

**Framework:** `unittest.mock` (`Mock`, `MagicMock`, `patch`, `patch.object`, `patch.dict`)

**Patterns:**
```python
from unittest.mock import Mock, MagicMock, patch

# Simple Mock for logger (avoiding structlog dependency)
logger = Mock()

# MagicMock for full handler mocks (all attribute access + calls work)
strategies = MagicMock()

# patch.dict for sys.modules stubbing (isolate import side-effects)
_STUB_MODULES = {name: MagicMock() for name in ["itrader.strategy_handler.strategies_handler", ...]}
with patch.dict(sys.modules, _STUB_MODULES):
    from itrader.events_handler.full_event_handler import EventHandler

# patch.object for method/attribute replacement on instances
with patch.object(self.exchange._rng, 'random', return_value=0.3):
    result = self.exchange.execute_order(order_event)

# monkeypatch for environment variables and module attributes
def test_log_level_env_honored(monkeypatch, clean_root_logger):
    monkeypatch.setenv("ITRADER_LOG_LEVEL", "DEBUG")
    monkeypatch.setattr(pd.DataFrame, 'resample', counting_resample)
```

**Preferred: Protocol-shaped fakes over `Mock`:**
Where a structural Protocol is involved (e.g., `PortfolioReadModel`), tests use hand-rolled fake classes instead of `Mock`. This gives compile-time-checkable structural conformance:
```python
class _FakeReadModel:
    """PortfolioReadModel-shaped fake recording reserve/release calls.
    Satisfies the runtime_checkable Protocol structurally (D-16)."""
    def __init__(self, cash=Decimal("100000")):
        self._cash = cash
        self.reserve_calls = []
    def available_cash(self, portfolio_id): return self._cash
    def reserve(self, portfolio_id, order_id, amount): ...
    def release(self, portfolio_id, order_id): ...
    def exchange_for(self, portfolio_id): return "default"
```
Source: `tests/unit/order/test_order_manager.py:267`

**What to mock:**
- Logger instances (use `Mock()` to avoid structlog initialization side-effects)
- Handler collaborators in routing tests (`MagicMock()` for full call capture)
- Random number generators (use `patch.object(exchange._rng, 'random', ...)`)
- Environment variables (use `monkeypatch.setenv/delenv`)

**What NOT to mock:**
- `queue.Queue` — always use real instances; `global_queue` fixture provides fresh ones
- Business-logic managers (`OrderManager`, `MatchingEngine`, `Portfolio`) in unit tests — test them with real instances
- `Decimal` arithmetic — never mock money calculations

## Fixtures

**Root conftest fixtures (`tests/conftest.py`):**

```python
@pytest.fixture
def global_queue():
    """A fresh FIFO event queue per test."""
    return queue.Queue()

@pytest.fixture
def make_bar_struct():
    """Factory fixture: build a bare Bar value object (Decimal fields)."""
    return _bar_struct   # positional: (open_, high, low, close, time=..., volume=1)

@pytest.fixture
def make_bar():
    """Factory fixture: build a one-ticker BarEvent with dict[str, Bar] payload."""
    return _bar_event    # positional: (open_, high, low, close, ticker="BTCUSDT", ...)

@pytest.fixture
def make_bar_event():
    """Alias of make_bar for call sites preferring the explicit name."""
    return _bar_event
```

**Integration conftest fixtures (`tests/integration/conftest.py`):**
```python
@pytest.fixture
def golden_dir():       # Path to tests/golden/
@pytest.fixture
def golden_trades_path()   # tests/golden/trades.csv
@pytest.fixture
def golden_equity_path()   # tests/golden/equity.csv
@pytest.fixture
def golden_summary_path()  # tests/golden/summary.json

@pytest.fixture
def backtest_engine():
    """Factory that defers TradingSystem construction until invoked in a test."""
    def _make(ticker="BTCUSD", timeframe="1d", start_date="2018-01-01",
              end_date="2026-06-03", cash=10_000):
        from itrader.trading_system.backtest_trading_system import TradingSystem
        return TradingSystem(exchange="csv", ...)
    return _make
```

**Fixture scopes:**
- Default (function scope): most fixtures — fresh state per test
- `scope="module"`: expensive runs shared across a module (e.g., `oracle_run` in `test_backtest_oracle.py`, `traced_run` in `test_reservation_inertness.py`)

**Teardown with `yield`:**
```python
@pytest.fixture
def harness():
    h = _Harness()
    yield h
    while not h.queue.empty():   # ensure queue is empty after test
        h.queue.get_nowait()
```

## Golden-Master Oracle Pattern

The integration test suite uses a committed frozen-oracle directory (`tests/golden/`) as the behavioral regression lock. This is a first-class testing pattern in this codebase.

**Structure:**
- `tests/golden/trades.csv` — frozen trade log (entry/exit dates, sides, PnL)
- `tests/golden/equity.csv` — frozen equity curve (timestamps, total equity)
- `tests/golden/summary.json` — frozen summary metrics (trade count, final cash, total PnL)

**Oracle test (`tests/integration/test_backtest_oracle.py`):**
```python
@pytest.fixture(scope="module")
def oracle_run():
    # Run the full 2018->2026 backtest ONCE; load fresh output/ + frozen golden/
    _run_full_backtest()    # writes output/{trades,equity}.csv + summary.json
    fresh_trades = pd.read_csv(_OUTPUT_DIR / "trades.csv")
    golden_trades = pd.read_csv(golden_dir / "trades.csv")
    ...

def test_oracle_behavioral_identity(oracle_run):
    pdt.assert_frame_equal(
        fresh_trades_sorted[_TRADE_IDENTITY_COLUMNS],
        golden_trades_sorted[_TRADE_IDENTITY_COLUMNS],
        check_exact=True,   # NO tolerance — exact behavioral identity
        check_like=True,
    )
```

**Golden rules:**
- Numeric comparisons are `check_exact=True` — no `rtol`/`atol` tolerance
- Re-baseline is allowed at exactly two sanctioned points (after M2, after M5) — never ad hoc
- `pytest.skip()` when `tests/golden/` does not exist — oracle tests are RED until frozen

## Parametrize Pattern

```python
@pytest.mark.parametrize("status", ["EXECUTED", "CANCELLED", "REFUSED"])
def test_terminal_fill_releases_reservation(status):
    """Every terminal reconciliation releases the order's reservation."""
    ...
    manager.on_fill(_fill_for(order, status))
    assert read_model.release_calls == [(order.portfolio_id, order.id)]

@pytest.mark.parametrize("model", [
    ZeroFeeModel(),
    PercentFeeModel(fee_rate=0.001),
    MakerTakerFeeModel(),
])
def test_validate_raises_on_non_positive_quantity(model):
    with pytest.raises(ValidationError):
        model.calculate_fee(Decimal("0"), Decimal("100"))
```

## Async Testing

Not used — the codebase is synchronous (event-driven via `queue.Queue`, not `asyncio`).

## Common Patterns

**Exception testing:**
```python
def test_buy_exceeding_balance_raises_before_position_mutation(portfolio):
    too_big = _txn(TransactionType.BUY, "BTCUSDT", 40000, 10)  # 400k > 150k
    with pytest.raises(InsufficientFundsError):
        portfolio.process_transaction(too_big)
    # Guard: state unchanged after failed call
    assert len(portfolio.positions) == 0
    assert portfolio.cash == Decimal("150000.00")
```

**State-guard after failure:**
After every `pytest.raises` block, assert that no state mutation occurred. This is a consistent pattern throughout portfolio and order tests.

**Decimal equality (no tolerance):**
```python
# CORRECT — exact Decimal comparison
assert fills[0].fill_price == Decimal("30.0")
assert isinstance(fills[0].fill_price, Decimal)

# WRONG — float tolerance masks Decimal correctness bugs
assert fills[0].fill_price == pytest.approx(30.0)
```

**Queue drain after test (for fixtures with teardown):**
```python
@pytest.fixture
def harness():
    h = _Harness()
    yield h
    while not h.queue.empty():   # prevent strict-warnings leak
        h.queue.get_nowait()
```

**Deferred import in integration tests:**
```python
def _make(...):
    # Deferred import: only executed when a test calls the factory
    from itrader.trading_system.backtest_trading_system import TradingSystem
    return TradingSystem(...)
```
Prevents `--collect-only` failures when a dependency is not yet wired.

**`dataclasses.replace` for frozen event variants:**
```python
import dataclasses
partial = dataclasses.replace(
    harness.fill(order, "EXECUTED"), quantity=Decimal("0.4")
)
```
Used instead of mutating frozen events in tests that need varied event fields.

## Coverage

**Requirements:** No minimum enforced in configuration; `filterwarnings = ["error"]` and `--strict-markers` are the quality gates.

**View Coverage:**
```bash
make test-cov   # runs pytest --cov=itrader --cov-report=html; opens htmlcov/index.html
```

**Coverage scope:** `--cov=itrader` — only the package under test, not tests themselves.

## Test Types

**Unit Tests (`tests/unit/`):**
- Drive ONE collaborating component in isolation
- May use a real `global_queue` + several classes from the same domain
- Do NOT assert cross-component event cascades
- Rely on real objects; use `Mock` only for logger and cross-domain boundaries

**Integration Tests (`tests/integration/`):**
- Assert cross-component interaction (cross-domain, cross-manager, full cascade)
- Include the golden-master oracle test (`test_backtest_oracle.py`) — full 2018→2026 SMA_MACD run
- Include smoke test (`test_backtest_smoke.py`) — import → run → nonzero trade
- Include routing tests (`test_event_wiring.py`) — EventHandler dispatch with mocked collaborators
- Include inertness proof (`test_reservation_inertness.py`) — reservation gate provably neutral

**E2E Tests:** Not present — the `test_backtest_oracle.py` module-scoped fixture effectively serves this role for the backtest path.

---

*Testing analysis: 2026-06-07*
