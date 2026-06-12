# Testing Patterns

**Analysis Date:** 2026-06-12

## Test Framework

**Runner:**
- pytest ^8.4.2
- Config: `pyproject.toml` `[tool.pytest.ini_options]`
- `minversion = "8.0"`, `testpaths = ["tests"]`

**Assertion Library:**
- pytest built-in assertions
- `pandas.testing.assert_frame_equal` for DataFrame diffs (used in oracle/e2e)

**Coverage:**
- pytest-cov ^7.1.0 — HTML report at `htmlcov/`
- pytest-html ^4.2.0 — HTML test reports

**Run Commands:**
```bash
make test              # full suite (unit + e2e; excludes slow/integration by default)
make test-unit         # -m "unit"  →  tests/unit/
make test-integration  # -m "integration"  →  tests/integration/ (slow)
make test-e2e          # tests/e2e/
make test-portfolio    # tests/unit/portfolio/
make test-orders       # tests/unit/order/
make test-execution    # tests/unit/execution/
make test-events       # tests/unit/events/
make test-strategy     # tests/unit/strategy/
make test-cov          # coverage → opens htmlcov/index.html

# Single file / case:
poetry run pytest tests/unit/order/test_order.py -v
poetry run pytest tests/unit/order/test_order.py -k "test_name" -v
```

## Test File Organization

**Location:**
- Tests are NOT co-located with source. They live in a separate `tests/` root.
- Structure mirrors `itrader/` package within `tests/unit/`.

**Naming:**
- `test_<module>.py` — `test_order_manager.py`, `test_matching_engine.py`, `test_cash_manager.py`.

**Structure:**
```
tests/
├── conftest.py                  # Root: folder-derived TYPE markers + global_queue + bar fixtures
├── README.md
├── golden/                      # Frozen oracle assets (trades.csv, equity.csv, summary.json)
│   ├── CROSS-VALIDATION.md
│   ├── FINAL-ORACLE.md
│   └── REFREEZE-*.md
├── unit/                        # One collaborating component each
│   ├── conftest.py              # Layer anchor (minimal)
│   ├── config/                  # Pydantic config models
│   ├── core/                    # enums, clock, money, bar, sizing, portfolio_read_model
│   ├── outils/                  # id_generator, time_parser
│   ├── events/                  # event dataclasses / schemas
│   ├── order/                   # order handler / manager / validator / storage
│   ├── execution/               # execution handler, matching engine
│   │   └── exchanges/           # simulated exchange
│   ├── portfolio/               # portfolio handler + cash/position/transaction/metrics
│   │   ├── positions/
│   │   └── transaction/
│   ├── price/                   # bar_feed, csv_store
│   ├── reporting/               # metrics, plots, cash_operations
│   ├── strategy/                # strategy config, signal store
│   └── universe/
├── integration/                 # Cross-component cascades, smoke, golden oracle
│   ├── conftest.py              # golden-path fixtures + backtest_engine factory
│   ├── test_backtest_oracle.py
│   ├── test_backtest_smoke.py
│   ├── test_event_wiring.py
│   ├── test_execution_handler_routing.py
│   ├── test_reservation_inertness.py
│   └── test_universe_spans.py
└── e2e/                         # Full-engine scenario runs vs frozen golden files
    ├── conftest.py              # run_scenario fixture (the entire harness)
    ├── scenario_spec.py         # Shared ScenarioSpec / PortfolioSpec / Action dataclasses
    ├── strategies/              # Shared test-only strategy implementations
    ├── smoke/single_market_buy/ # Canary scenario
    ├── matching/                # Order-matching scenarios (entries, brackets, gaps, operator)
    ├── sizing/                  # Sizing policy scenarios
    ├── sltp/                    # Stop-loss / take-profit scenarios
    ├── cost/                    # Fee and slippage scenarios
    ├── admission/               # Order admission rule scenarios
    ├── cash/                    # Cash reservation/release scenarios
    ├── multi/                   # Multi-portfolio / multi-ticker / multi-strategy scenarios
    └── robust/                  # Edge-case robustness scenarios
```

## Marker System

Markers are **folder-derived** — applied automatically by `tests/conftest.py::pytest_collection_modifyitems`. Never hand-add the type marker to a test.

| Folder | Markers Applied |
|--------|----------------|
| `tests/unit/` | `unit` |
| `tests/integration/` | `integration`, `slow` |
| `tests/e2e/` | `e2e` (NOT `slow`) |

Registered in `pyproject.toml` (the `--strict-markers` single source of truth):
- `unit`, `integration`, `slow`, `e2e`

**Exception:** Some early unit tests carry an explicit `pytestmark = pytest.mark.unit` at module level (e.g. `tests/unit/core/test_money.py`, `tests/unit/core/test_clock.py`) to ensure `--strict-markers` is satisfied regardless of conftest ordering — keep this only for wave-0 scaffolds; new tests rely on folder-derived marking.

## Test Structure

**Pure function style (majority of unit tests):**
```python
def test_zero_model_returns_decimal_zero():
    fee = ZeroFeeModel().calculate_fee(Decimal("100"), Decimal("250"))
    assert isinstance(fee, Decimal)
    assert fee == Decimal("0")
```

**Fixture-based setup:**
```python
@pytest.fixture
def cm():
    """A CashManager seeded with $100000 on a mock portfolio."""
    portfolio = MockPortfolio()
    return CashManager(portfolio, 100000.0)

def test_cash_manager_initialization(cm):
    assert cm.balance == Decimal("100000.00")
```

**Harness class (for complex multi-object setups):**
```python
class _Harness:
    """OrderHandler + storage + one funded portfolio."""
    def __init__(self):
        self.queue = Queue()
        self.ptf_handler = PortfolioHandler(self.queue)
        self.storage = OrderStorageFactory.create("test")
        self.handler = OrderHandler(self.queue, self.ptf_handler, self.storage)
        self.portfolio_id = self.ptf_handler.add_portfolio(1, "p", "default", 100000)
```

**Test class style (used in simulated exchange, order lifecycle):**
```python
class TestSimulatedExchangeInitialization:
    def setup_method(self):
        self.queue = Queue()
        self.base_time = datetime.now()

    def test_default_initialization(self):
        exchange = SimulatedExchange(self.queue)
        assert exchange.global_queue is self.queue
```

**Teardown pattern (queue draining):**
```python
yield SimpleNamespace(...)
while not queue.empty():
    queue.get_nowait()
```

## Cross-Cutting Fixtures (Root `tests/conftest.py`)

```python
@pytest.fixture
def global_queue():
    """A fresh FIFO event queue per test."""
    return queue.Queue()

@pytest.fixture
def make_bar_struct():
    """Factory: build a bare Bar value object with Decimal(str(x)) fields."""
    return _bar_struct

@pytest.fixture
def make_bar():
    """Factory: build a one-ticker BarEvent (dict[str, Bar] payload)."""
    return _bar_event

@pytest.fixture
def make_bar_event():
    """Alias of make_bar."""
    return _bar_event
```

All positional bar args use `(open_, high, low, close)` with Decimal-via-string conversion — never raw floats.

## Integration Fixtures (`tests/integration/conftest.py`)

```python
@pytest.fixture
def golden_trades_path():
    return pathlib.Path(__file__).resolve().parent.parent / "golden" / "trades.csv"

@pytest.fixture
def backtest_engine():
    """Factory that builds a CSV-fed backtest TradingSystem (deferred import)."""
    def _make(ticker="BTCUSD", timeframe="1d", ...):
        from itrader.trading_system.backtest_trading_system import TradingSystem
        return TradingSystem(exchange="csv", ...)
    return _make
```

## Mocking

**Framework:** `unittest.mock` (stdlib) — `Mock`, `MagicMock`, `patch`, `patch.dict`.

**Simple dependency mock:**
```python
from unittest.mock import Mock

logger = Mock()
order_manager = OrderManager(order_storage, logger, market_execution="immediate")
```

**Structural stub class:**
```python
class _StubReadModel:
    """Minimal read model for the resolver."""
    def __init__(self, available=Decimal("10000.00"), equity=Decimal("50000")):
        self._available = available

    def available_cash(self, portfolio_id):
        return self._available
```

**Module-level stub with `patch.dict` (for heavy import isolation):**
```python
_STUB_MODULES = {
    name: MagicMock()
    for name in [
        "itrader.strategy_handler.strategies_handler",
        "itrader.order_handler.order_handler",
        ...
    ]
}
with patch.dict(sys.modules, _STUB_MODULES):
    from itrader.events_handler.full_event_handler import EventHandler
```
This pattern (in `tests/unit/events/test_dispatch_registry.py` and `tests/integration/test_event_wiring.py`) prevents heavy handler modules from being imported at collection time.

**`monkeypatch` for env vars and attribute spying:**
```python
def test_log_level_env_honored(monkeypatch, clean_root_logger):
    monkeypatch.setenv("ITRADER_LOG_LEVEL", "DEBUG")
    ...

def test_non_executed_fill_skips_operation_context(env, monkeypatch, status):
    calls = []
    original = env.ptf._operation_context
    def spy(operation_name):
        calls.append(operation_name)
        return original(operation_name)
    monkeypatch.setattr(env.ptf, "_operation_context", spy)
```

**What to Mock:**
- Logger instances (`Mock()` — prevents structlog setup side effects).
- Read-model protocols when testing managers in isolation (use structural stub classes, not `Mock()`).
- Heavy handler modules that trigger expensive imports (use `patch.dict(sys.modules, ...)`).
- Environment variables for config/logging tests (use `monkeypatch.setenv`/`delenv`).

**What NOT to Mock:**
- The `global_queue` — use the real `queue.Queue()` (provided by the root fixture).
- Domain business logic — use real components; only mock the queue and cross-domain read-models.
- The `itrader` singletons (`config`, `idgen`) — they initialize on import; accept that side effect.

## Fixtures and Factories

**Shared bar factories (root conftest):**
```python
# Usage in tests:
def test_something(make_bar):
    bar = make_bar(open_=100, high=105, low=99, close=104, ticker="BTCUSD")
    # bar is a BarEvent with dict[str, Bar] payload, all Decimal(str(x))
```

**Drain helper (simulated exchange tests):**
```python
def drain_fills(queue: Queue) -> list[FillEvent]:
    fills = []
    while not queue.empty():
        fills.append(queue.get_nowait())
    return fills
```

**Golden fixtures (integration conftest):**
- `golden_dir`, `golden_trades_path`, `golden_equity_path`, `golden_summary_path` resolve to `tests/golden/`.

**Test data:**
- Contrived, hand-written CSV files live alongside their scenario — e.g. `tests/e2e/smoke/single_market_buy/bars.csv`.
- The golden-master oracle uses a real committed dataset at `data/BTCUSD_1d_ohlcv_2018_2026.csv`.

## E2E Scenario Pattern

Each E2E scenario lives in its own leaf directory with exactly three files:
1. `scenario.py` — declares a module-level `SCENARIO` (a `ScenarioSpec` instance).
2. `test_scenario.py` — one test function that calls `run_scenario(HERE)`. No assertions or diffing logic.
3. `golden/` — committed golden files: always `trades.csv` + `summary.json`; optionally `equity.csv`, `orders.csv`, `cash_operations.csv`, `portfolios.csv`.

```python
# test_scenario.py pattern (copy-template for all E2E leaves):
import pathlib
HERE = pathlib.Path(__file__).resolve().parent

def test_single_market_buy(run_scenario):
    run_scenario(HERE)
```

```python
# scenario.py pattern:
from tests.e2e.scenario_spec import ScenarioSpec, PortfolioSpec
from tests.e2e.strategies.single_market_buy import SingleMarketBuy

SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-06",
    timeframe="1d",
    ticker="BTCUSD",
    starting_cash=10_000,
    data={"BTCUSD": HERE / "bars.csv"},
    strategies=[SingleMarketBuy("1d", ["BTCUSD"], fire_on_bar=2, exit_on_bar=4)],
    portfolios=[PortfolioSpec(user_id=1, name="canary_pf", cash=10_000)],
    exchange=None,  # zero-fee / no-slippage defaults
)
```

The `run_scenario` fixture (defined in `tests/e2e/conftest.py`) owns the full build → run → read → assemble → diff pipeline. Goldens never auto-heal; regenerate with `--freeze` (one scenario at a time, after hand-verification).

## Coverage

**Requirements:** No minimum enforced in `pyproject.toml`. Coverage is advisory.

**View Coverage:**
```bash
make test-cov          # runs with --cov, opens htmlcov/index.html
```

## Test Types Summary

**Unit Tests (`tests/unit/`, ~744 test functions):**
- Scope: drives ONE collaborating component in isolation per D-15.
- May import several classes from the same domain and use a real `global_queue`.
- Does NOT assert cross-component cascades or run a full `TradingSystem`.

**Integration Tests (`tests/integration/`, ~12 test functions, `slow`):**
- Scope: cross-component interaction — cross-domain, cross-manager, full event cascade, run-path smoke, golden oracle.
- Uses the `backtest_engine` factory fixture to construct a full `TradingSystem`.
- The oracle test (`test_backtest_oracle.py`) runs `scripts/run_backtest.py` in-process, compares fresh output against `tests/golden/` with EXACT `assert_frame_equal` (no float tolerance).

**E2E Tests (`tests/e2e/`, ~48 test functions):**
- Scope: full-engine runs over tiny (~6–10 bar) contrived datasets vs committed golden files.
- Organized by behavioral category: `smoke/`, `matching/`, `sizing/`, `sltp/`, `cost/`, `admission/`, `cash/`, `multi/`, `robust/`.
- The ONLY test assertion is: does the fresh output match the golden? Presence of a golden file = assertion.

## Common Patterns

**Async Testing:** Not used — the engine is synchronous.

**Error Testing:**
```python
# Typed exception with message match:
with pytest.raises(SizingPolicyViolation, match="RiskPercent requires stop_loss"):
    resolver.resolve_size(...)

# Exception without match:
with pytest.raises(ValidationError):
    ZeroFeeModel().calculate_fee(Decimal("-1"), Decimal("250"))

# Checking exception fields:
with pytest.raises(ConfigurationError) as exc_info:
    OrderStorageFactory.create("unknown")
assert "unknown" in str(exc_info.value)
```

**Decimal Money Testing:**
```python
# Always assert Decimal equality against Decimal literals:
assert cm.balance == Decimal("100000.00")
assert fee == Decimal("100") * Decimal("250") * Decimal("0.001")

# Check isinstance to verify Decimal-native contract:
assert isinstance(fee, Decimal)
```

**Parametrize:**
```python
@pytest.mark.parametrize("status", ["EXECUTED", "CANCELLED", "REFUSED"])
def test_on_fill_status_routing(env, status):
    ...
```

**Deferred TradingSystem import (test isolation):**
```python
def _make(...):
    # Import deferred so --collect-only succeeds without the full engine.
    from itrader.trading_system.backtest_trading_system import TradingSystem
    return TradingSystem(...)
```

## Golden Master Discipline

**Oracle freeze re-baseline points:** Only at M2 and M5 milestone boundaries. The numerical oracle in `tests/golden/` is never auto-regenerated; each refreeze requires an explicit `REFREEZE-*.md` hand-derivation note committed alongside the new golden files.

**E2E freeze discipline:** `--freeze` refuses to run with more than one test selected, enforcing one-at-a-time hand-verified freezes. Goldens prove stability, not correctness — correctness is established before the freeze by the VERIFY docstring in `scenario.py`.

**Diff mechanic:** `pandas.testing.assert_frame_equal` with `check_exact=True`, `check_like=True`, NO float tolerance. Both fresh and golden are round-tripped through `to_csv(float_format="%.10f")` → `read_csv` so dtypes and float precision are normalized before comparison.

---

*Testing analysis: 2026-06-12*
