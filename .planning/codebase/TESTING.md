# Testing Patterns

**Analysis Date:** 2026-06-10

## Test Framework

**Runner:**
- pytest ^9.0.3 (dev dependency in `pyproject.toml`; `minversion = "8.0"`)
- Config: `pyproject.toml` `[tool.pytest.ini_options]`
- `testpaths = ["tests"]`; discovery globs `test_*.py` / `*_test.py`, classes `Test*`, functions `test_*`.

**Assertion Library:**
- Plain `assert` statements (pytest rewriting). No separate assertion library.
- `pandas.testing.assert_frame_equal` (imported as `pdt`) for golden-frame diffs in `tests/e2e/conftest.py`.

**Coverage / Reporting:**
- pytest-cov ^7.1.0 (HTML at `htmlcov/`), pytest-html ^4.2.0.

**Run Commands:**
```bash
make test               # poetry run pytest tests/ -v  (full suite)
make test-unit          # -m "unit"
make test-integration   # -m "integration"
make test-e2e           # -m "e2e"
make test-cov           # --cov=itrader --cov-report=html --cov-report=term-missing; opens htmlcov/index.html

# Domain-scoped shortcuts (folder-targeted, not marker-based):
make test-portfolio     # tests/unit/portfolio/
make test-events        # tests/unit/events/
make test-orders        # tests/unit/order/
make test-execution     # tests/unit/execution/
make test-strategy      # tests/unit/strategy/

# Single file / case:
poetry run pytest tests/unit/order/test_order.py -v
poetry run pytest tests/unit/order/test_order.py -k "test_name" -v
```

**Strictness gotcha:**
- `addopts` includes `--strict-markers` and `--strict-config`. Every marker used MUST be declared in `pyproject.toml` `markers`. Only `unit`, `integration`, `slow`, `e2e` are declared.
- `filterwarnings = ["error", "ignore::UserWarning", "ignore::DeprecationWarning"]` — any other unexpected warning fails the suite.

## Test File Organization

**Location:**
- Separate `tests/` tree (NOT co-located with source). Mirrors source domains.
- Three layers: `tests/unit/`, `tests/integration/`, `tests/e2e/`. Plus `tests/golden/` (committed frozen oracle CSV/JSON).
- `tests/unit/` is sub-divided by domain: `order/`, `portfolio/`, `execution/`, `core/`, `config/`, `events/`, `price/`, `strategy/`, `reporting/`, `universe/`, `outils/`.

**Naming:**
- Source-mirroring: `test_<module>.py` (e.g. `test_order_manager.py`, `test_cash_manager.py`).
- ~113 `test_*.py` files total.

**Markers are FOLDER-DERIVED, not hand-applied (D-13/D-15):**
- `tests/conftest.py::pytest_collection_modifyitems` auto-marks each collected item by its path:
  - file under `tests/unit/` → `unit`
  - file under `tests/integration/` → `integration` + `slow`
  - file under `tests/e2e/` → `e2e` (NOT `slow` — e2e runs are tiny ~10-bar full-engine runs and stay in the default suite)
- `pyproject.toml` is the SINGLE marker-registration home; conftest only applies, never registers.

**Layer boundary (D-15):**
- `unit` = drives ONE collaborating component (may use a real `global_queue` + several classes from its own domain).
- `integration` = asserts interaction ACROSS components (cross-domain, cross-manager, or full cascade / smoke / oracle).
- `e2e` = full-engine run on a `(strategy, data)` pair vs frozen goldens.

## Conftest Layering

- `tests/conftest.py` — cross-cutting: folder-derived marker hook + the `global_queue` fixture + shared bar helpers (`make_bar`, `make_bar_struct`, `make_bar_event`).
- `tests/unit/conftest.py` — unit-layer anchor.
- `tests/integration/conftest.py` — golden-file path fixtures (`golden_dir`, `golden_trades_path`, `golden_equity_path`, `golden_summary_path`) + the `backtest_engine` factory fixture.
- `tests/e2e/conftest.py` — the shared `run_scenario` harness (build → run → read → assemble → diff) and the `--freeze` golden-regen flag.

## Test Structure

**Two coexisting authoring styles:**

1. **Class-based** (`Test*` classes with `setup_method` + `create_test_*` helpers) — `tests/unit/order/test_order.py`:
```python
class TestOrderLifecycle:
    """Test order lifecycle management and state transitions."""

    def setup_method(self):
        self.base_time = datetime.now()

    def create_test_order(self, **kwargs) -> Order:
        defaults = {'time': self.base_time, 'type': OrderType.MARKET, ...}
        defaults.update(kwargs)
        return Order(**defaults)

    def test_order_properties(self):
        order = self.create_test_order(quantity=100.0, price=150.0)
        assert order.remaining_quantity == 100.0
```

2. **Function-based with fixtures** (preferred in newer modules) — `tests/unit/portfolio/test_cash_manager.py`:
```python
@pytest.fixture
def cm():
    """A CashManager seeded with $100000 on a mock portfolio."""
    portfolio = MockPortfolio()
    return CashManager(portfolio, 100000.0)

def test_deposit_valid_amount(cm):
    result = cm.deposit(5000.0, "Test deposit")
    assert result
    assert cm.balance == initial_balance + Decimal("5000.00")
```

**Patterns:**
- Every test has a one-line docstring describing intent.
- Money assertions compare against `Decimal("...")` literals, never floats.
- `pytest.raises` for error-path assertions (heavily used in `tests/unit/core/`, e.g. `test_sizing.py`, `test_portfolio_read_model.py`).
- `@pytest.mark.parametrize` used in ~8 files for table-driven cases.

## Mocking

**Framework:** `unittest.mock` (`Mock`, `MagicMock`, `@patch`) + pytest `monkeypatch`.

**Patterns:**
- Hand-rolled stub classes for collaborators with a narrow surface:
```python
class MockPortfolio:
    """Mock portfolio for testing."""
    def __init__(self):
        self.portfolio_id = 12345
```
- `MagicMock` (~30 uses), `Mock(` (~3 uses), `monkeypatch` (~16 uses) across the suite.

**What to Mock:**
- Narrow collaborator surfaces a unit needs (e.g. a portfolio handle behind a manager).

**What NOT to Mock:**
- The `global_queue` — use the real `queue.Queue` via the `global_queue` fixture.
- The full engine in e2e/integration — the harness wires a REAL `TradingSystem` (no parallel/reinvented config schema).
- Money math — assert real `Decimal` values, never a mocked computation.

## Fixtures and Factories

**Shared bar factories** (`tests/conftest.py`):
- `make_bar_struct` → a bare `Bar` value object (every field via `Decimal(str(x))`).
- `make_bar` / `make_bar_event` → a one-ticker `BarEvent` with a `dict[str, Bar]` payload, keeping the positional `(open, high, low, close)` signature.

**Engine factory** (`tests/integration/conftest.py`):
- `backtest_engine` returns a callable `_make(...)` so `TradingSystem` construction is DEFERRED (the import lives inside the inner function so `--collect-only` stays clean).

**Test Data:**
- Per-scenario CSVs live in the leaf folder (`tests/e2e/<group>/<scenario>/bars.csv`, plus `bars_eth.csv` etc. for multi-ticker leaves).
- Frozen oracle: `tests/golden/trades.csv`, `tests/golden/equity.csv`, `tests/golden/summary.json`.

## E2E Golden-Scenario Harness (the dominant integration mechanism)

`tests/e2e/` holds ~50 scenario leaves grouped by theme: `matching/`, `smoke/`, `robust/`, `multi/`, `cash/`, `cost/`, `admission/`, `sltp/`, `sizing/`.

**Per-leaf contract — an author edits ONLY their own leaf folder:**
- `scenario.py` — exposes a module-level `SCENARIO = ScenarioSpec(...)` (frozen dataclass carrying `start`/`end`/`timeframe`/`ticker`/`data`/`strategies`/`portfolios`/`exchange`). Its module docstring IS the hand-derivation `VERIFY` note explaining WHY each frozen number is what it is.
- `test_scenario.py` — the ONLY allowed body delegates to the harness:
```python
HERE = pathlib.Path(__file__).resolve().parent

def test_single_market_buy(run_scenario):
    run_scenario(HERE)
```
- `golden/` — committed expected `trades.csv` + `summary.json` (always); `equity.csv`, `orders.csv`, `cash_operations.csv`, `portfolios.csv` are OPT-IN (presence = assertion, D-05).

**Harness (`run_scenario` in `tests/e2e/conftest.py`) flow:** load spec → wire a real `TradingSystem` → run (`print_summary=False`) → read portfolio state AFTER the run (queue-only) → assemble frames via the SHARED `itrader.reporting.*` serializers → diff against `golden/` with EXACT no-tolerance `assert_frame_equal`.

**`--freeze` discipline (OFF by default):** writes goldens instead of diffing. Mechanically refused when >1 test is selected — freeze ONE hand-verified scenario at a time. Goldens never auto-heal.

## Coverage

**Requirements:** None enforced (no `[tool.coverage]` section in `pyproject.toml`, no threshold gate).

**View Coverage:**
```bash
make test-cov   # HTML report to htmlcov/index.html (auto-opens)
```

## Test Types

**Unit Tests** (`tests/unit/`, marker `unit`):
- One component, fast, fixture-driven. May use a real `global_queue` and same-domain classes.

**Integration Tests** (`tests/integration/`, markers `integration` + `slow`):
- Cross-component: `test_event_wiring.py`, `test_execution_handler_routing.py`, `test_universe_spans.py`, `test_backtest_smoke.py`, and the golden-master `test_backtest_oracle.py` (byte-exact vs `tests/golden/`).

**E2E Tests** (`tests/e2e/`, marker `e2e`):
- Tiny full-engine `(strategy, data)` runs diffed against per-leaf frozen goldens. Stay in the default `make test` suite (not `slow`).

**Cross-Validation** (`tests/golden/CROSS-VALIDATION.md`, `scripts/cross_validate.py`):
- The numerical oracle is cross-validated against `backtesting.py` 0.6.5 and `backtrader` (gating) plus `nautilus-trader` (non-gating).

## Common Patterns

**Money Testing:**
```python
assert cm.balance == Decimal("100000.00")
assert operations[0].amount == Decimal("5000.00")
```

**Error Testing:**
```python
with pytest.raises(InsufficientFundsError):
    cm.withdraw(...)
```

**Async Testing:**
- Not used — the codebase is synchronous (backtest for-loop; live mode uses threads, not asyncio). No `async def` / `await` in the test suite.

---

*Testing analysis: 2026-06-10*
