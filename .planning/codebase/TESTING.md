# Testing Patterns

**Analysis Date:** 2026-06-08

## Test Framework

**Runner:**
- pytest 8.4.2 (`minversion = "8.0"`)
- Config: `pyproject.toml` → `[tool.pytest.ini_options]` (single source of truth; there is no separate `pytest.ini`/`tox.ini`).

**Assertion Library:**
- pytest plain `assert` everywhere. `pytest.approx` for float-tolerant comparisons (17 uses, concentrated in `tests/unit/reporting/test_metrics.py`). `pandas.testing` (`pdt`) for DataFrame equality in the oracle test.

**Plugins:**
- pytest-cov 5.0.0 (coverage), pytest-watch 4.2.0 (watch mode), pytest-html 4.2.0 (HTML reports).

**Run Commands:**
```bash
make test              # poetry run pytest tests/ -v  (full suite)
make test-unit         # -m "unit"
make test-integration  # -m "integration"
make test-portfolio    # tests/unit/portfolio/
make test-orders       # tests/unit/order/
make test-execution    # tests/unit/execution/
make test-events       # tests/unit/events/
make test-strategy     # tests/unit/strategy/
make test-cov          # --cov=itrader --cov-report=html --cov-report=term-missing
make test-watch        # pytest-watch

poetry run pytest tests/unit/order/test_order_manager.py -v
poetry run pytest tests/unit/order/test_order_manager.py -k "initialization" -v
```

**Strictness (important gotchas):**
- `addopts`: `-ra --strict-markers --strict-config --disable-warnings -v`.
- `filterwarnings = ["error", "ignore::UserWarning", "ignore::DeprecationWarning"]` — an unexpected warning (other than UserWarning/DeprecationWarning) fails the test.
- `--strict-markers` + `--strict-config`: every marker used must be registered in `pyproject.toml`; any config typo fails collection.

## Test File Organization

**Location:**
- Separate `tests/` tree (NOT co-located with source). 61 `test_*.py` files.
- Two-layer split by FOLDER, which drives the marker (D-13/D-15):
  - `tests/unit/<domain>/` → marker `unit` (drives ONE collaborating component).
  - `tests/integration/` → markers `integration` + `slow` (cross-component / full engine).
- `tests/golden/` holds frozen-oracle assets: `trades.csv`, `equity.csv`, `summary.json`.

**Discovery config:**
- `testpaths = ["tests"]`, `python_files = ["test_*.py", "*_test.py"]`, `python_classes = ["Test*"]`, `python_functions = ["test_*"]`.

**Naming:**
- Files mirror source modules: `test_<module>.py`.
- Tests are predominantly module-level functions `test_<behavior>()`; only ~10 `class Test*` classes exist. Prefer functions.

**Domain layout (under `tests/unit/`):**
```
order/  portfolio/  execution/  events/  core/  config/
reporting/  price/  strategy/  universe/  outils/
```

## Marker Auto-Application (do NOT hand-mark)

Markers are registered ONCE in `pyproject.toml` and applied automatically by folder.

```python
# tests/conftest.py
def pytest_collection_modifyitems(config, items):
    for item in items:
        parts = pathlib.Path(str(item.fspath)).parts
        if "unit" in parts:
            item.add_marker(pytest.mark.unit)
        if "integration" in parts:
            item.add_marker(pytest.mark.integration)
            item.add_marker(pytest.mark.slow)
```

- Conftest only *applies* markers; it never *registers* them (registration lives in `pyproject.toml [tool.pytest.ini_options] markers`).
- Place a test in the right folder; do not add `@pytest.mark.unit`/`integration` by hand.

## Conftest Layering

- `tests/conftest.py` — root: marker auto-marking + cross-cutting fixtures (`global_queue`, `make_bar`, `make_bar_struct`, `make_bar_event`).
- `tests/unit/conftest.py` — unit-layer anchor / docstring only (home for future unit-only fixtures).
- `tests/integration/conftest.py` — golden-path fixtures (`golden_dir`, `golden_trades_path`, `golden_equity_path`, `golden_summary_path`, `backtest_engine`).

## Test Structure

**Function style with section comments:**
```python
# --- OrderManager initialization -------------------------------------------

def test_order_manager_initialization():
    """Test OrderManager initialization. (D-18 layering note)"""
    order_storage = InMemoryOrderStorage()
    logger = Mock()
    om = OrderManager(order_storage, logger, market_execution="immediate")
    assert om.market_execution == "immediate"
    assert not hasattr(om, "order_handler")
```

**Patterns:**
- Arrange / act / assert, separated by blank lines. Section dividers `# --- ... ---` group related tests within a file.
- Test docstrings often cite the locked decision tag the test enforces (e.g. `D-18`, `T-06-13`).

## Fixtures and Factories

**Fixture fixtures** (`@pytest.fixture`, 48 defs):
```python
@pytest.fixture
def cm():
    """A CashManager seeded with $100000 on a mock portfolio."""
    return CashManager(MockPortfolio(), 100000.0)

@pytest.fixture
def engine():
    return MatchingEngine()
```

**Shared factory fixtures (root conftest)** — return callables so construction is deferred:
```python
@pytest.fixture
def make_bar():           # build a one-ticker BarEvent (dict[str, Bar] Decimal payload)
    return _bar_event

@pytest.fixture
def backtest_engine():    # factory returns a callable; TradingSystem imported lazily inside
    def _make(...): ...
    return _make
```

**Module-level helper factories** — common in execution/order tests:
```python
def make_order_event(order_type, action, price, order_id, ticker="BTCUSDT", quantity=1.0, ...):
    # Decimal end-to-end: enter via Decimal(str(x)) exactly as production does
    return OrderEvent(time=datetime(2024, 1, 1), ..., price=Decimal(str(price)), ...)
```

**Harness classes** — bundle a wired subgraph for handler-level tests:
```python
class _Harness:
    """OrderHandler + storage + one funded portfolio."""
    def __init__(self):
        self.queue = Queue()
        self.ptf_handler = PortfolioHandler(self.queue)
        self.storage = OrderStorageFactory.create("test")
        self.handler = OrderHandler(self.queue, self.ptf_handler, self.storage)
```

**Money in test data:** always enter via `Decimal(str(x))` (matches the production money path). The shared bar helpers do this for `open/high/low/close/volume`.

## Mocking

**Framework:** `unittest.mock` (`Mock`, `MagicMock`) — 37 references. `monkeypatch` rare (2 files).

**Patterns:**
```python
from unittest.mock import Mock
logger = Mock()                       # loggers are mocked freely
class MockPortfolio:                  # lightweight hand-rolled stub when a Mock is too loose
    def __init__(self):
        self.portfolio_id = 12345
```

**What to mock:**
- Loggers (`Mock()`), and external/lightweight collaborators where a real one adds no value.

**What NOT to mock:**
- The event queue — use a real `queue.Queue` (root `global_queue` fixture). Unit tests are allowed a real queue and several real classes from their own domain.
- The matching engine, portfolios, storage backends (`InMemoryOrderStorage`, `OrderStorageFactory.create("test")`) — use the real in-memory implementations.

## Error Testing

```python
with pytest.raises(InvalidTransactionError) as exc_info:
    cm.deposit(60000.0, "Large deposit")
assert "exceed maximum balance limit" in str(exc_info.value)

with pytest.raises(ValidationError):
    ZeroFeeModel().calculate_fee(Decimal("-1"), Decimal("250"))
```
- 115 `pytest.raises` uses. Assert on the typed exception class; substring-check the message when the message is contract-relevant.

## Parametrization

- `@pytest.mark.parametrize` used in 5 files (`test_order_manager.py`, `test_exceptions.py`, `test_fee_models.py`, `test_slippage_models.py`, `test_event_immutability.py`) — mostly for tabular model/enum cases.

## Test Types

**Unit tests** (`tests/unit/`):
- Drive ONE collaborating component; may use a real queue + several classes from the same domain; do NOT assert cross-domain cascades.

**Integration tests** (`tests/integration/`, also `slow`):
- Assert cross-component interaction: `test_event_wiring.py`, `test_execution_handler_routing.py`, `test_reservation_inertness.py`, `test_backtest_smoke.py`.

**Golden-master oracle** (`tests/integration/test_backtest_oracle.py`):
- Runs the full SMA_MACD backtest over the pinned 2018→2026 window in-process via `scripts/run_backtest.py::main`, writing fresh `output/{trades,equity}.csv` + `summary.json`.
- Asserts the fresh output equals the committed `tests/golden/` artifacts EXACT (no float tolerance — exactness catches regressions; runs are bit-reproducible).
- Loads both sides into pandas DataFrames and asserts `frame-equal` on deterministic columns (NOT a byte compare). Trades keyed by `(entry_date, exit_date, side)`; equity by `timestamp`; summary by `trade_count` + numeric keys.

**E2E:** not separate from the integration/oracle layer.

## Coverage

- No enforced threshold. Generate locally with `make test-cov` (`--cov=itrader --cov-report=html --cov-report=term-missing`); HTML lands in `htmlcov/index.html`.

---

*Testing analysis: 2026-06-08*
