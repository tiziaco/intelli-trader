# Testing Patterns

**Analysis Date:** 2026-06-22

## Test Framework

**Runner:**
- pytest ^9.0.3
- Config: `pyproject.toml [tool.pytest.ini_options]`

**Assertion Library:**
- pytest built-in `assert`
- `pandas.testing.assert_frame_equal` (no-tolerance frame diffs in oracle/e2e)

**Run Commands:**
```bash
make test                          # full suite (unit + integration + e2e)
make test-unit                     # -m "unit" only
make test-integration              # -m "integration" only (slow — full backtest)
make test-e2e                      # -m "e2e" only (scenario harness)
make test-cov                      # coverage → opens htmlcov/index.html
make test-portfolio                # tests/unit/portfolio/ path shortcut
make test-orders                   # tests/unit/order/ path shortcut
make test-execution                # tests/unit/execution/ path shortcut
make test-strategy                 # tests/unit/strategy/ path shortcut

poetry run pytest tests/unit/order/test_order.py -v                    # single file
poetry run pytest tests/unit/order/test_order.py -k "test_name" -v    # single case
```

## Test File Organization

**Location:** Tests in `tests/` (NOT `test/`), fully separate from source. Three type-grouped subtrees:
```
tests/
├── conftest.py               # root: cross-cutting fixtures + folder-derived TYPE marker hook
├── unit/
│   ├── conftest.py           # layer anchor (no extra fixtures)
│   ├── config/               # config model tests
│   ├── core/                 # money, ids, bar, clock, sizing, exceptions, enums
│   ├── events/               # event immutability, dispatch, fill/order event schemas
│   ├── execution/            # matching engine, fee/slippage models, simulated exchange
│   │   └── exchanges/        # exchange-specific unit tests
│   ├── order/                # order lifecycle, manager, validator, admission, bracket, trailing
│   ├── outils/               # id generator, time parser
│   ├── portfolio/            # cash, positions, transactions, metrics, margin
│   │   ├── positions/        # open/multiple position tests
│   │   └── transaction/      # transaction init tests
│   ├── price/                # bar feed, csv store
│   ├── price_handler/        # bar feed update config
│   ├── reporting/            # metrics, plots smoke, cash operations
│   ├── strategy/             # strategy base, indicators, signal store, pair dispatch
│   └── universe/             # membership, derivation
├── integration/
│   ├── conftest.py           # golden path fixtures (golden_dir, backtest_engine factory)
│   ├── _oracle_harness.py    # shared importlib loader for scripts/run_backtest.py
│   ├── test_backtest_oracle.py          # full 2018→2026 golden-master regression
│   ├── test_backtest_smoke.py           # SMA_MACD short-window smoke
│   ├── test_event_wiring.py             # EventHandler routing with mocked collaborators
│   ├── test_execution_handler_routing.py
│   ├── test_expire_non_cascade.py
│   ├── test_pair_exit_safety.py
│   ├── test_pair_flagship_snapshot.py
│   ├── test_reservation_inertness.py
│   ├── test_symbol_seeding.py
│   └── test_universe_spans.py
├── e2e/
│   ├── conftest.py           # shared run_scenario harness (build→run→read→assemble→diff)
│   ├── strategies/           # reusable in-test strategy implementations
│   ├── admission/            # max_positions, re_entry, scale_in, scale_out
│   ├── cash/                 # release_cancelled, release_refused, release_rejected
│   ├── cost/                 # percent_fee, maker_taker, fixed_slippage, linear_slippage, etc.
│   ├── forced_liq_long/      # v1.4: forced liquidation LONG scenario
│   ├── forced_liq_short/     # v1.4: forced liquidation SHORT scenario
│   ├── levered_long/         # v1.4: levered long round-trip
│   ├── levered_long_into_liquidation/  # v1.4: leverage triggering liquidation
│   ├── matching/             # brackets, entries, gaps, never_fill, operator (cancel/modify)
│   ├── multi/                # contended_cash, fanout_portfolios, two_strategies, two_tickers
│   ├── partial_cover/        # v1.4: partial short cover
│   ├── robust/               # flat, losing, no_trade, sparse_bar, union_window
│   ├── short_carry/          # v1.4: short with borrow carry
│   ├── short_roundtrip/      # v1.4: pure short round-trip (SELL-to-open → BUY-to-cover)
│   ├── short_scale_in/       # v1.4: short scale-in
│   ├── short_scale_in_partial_cover/   # v1.4: short scale-in + partial cover
│   ├── sizing/               # fixed_quantity, risk_percent, over_cash_reject
│   ├── sltp/                 # from_decision / from_fill × held / sl_hit / tp_hit
│   ├── smoke/                # single_market_buy canary
│   ├── trailing_long/        # v1.4: trailing stop LONG (ratchet)
│   └── trailing_short/       # v1.4: trailing stop SHORT (ratchet)
└── golden/
    ├── trades.csv            # frozen SMA_MACD oracle (BTCUSD 2018→2026)
    ├── equity.csv
    ├── summary.json
    ├── pair/                 # pair-strategy golden artifacts
    └── CROSS-VALIDATION-*.md # external cross-validation records
```

**Naming:** `test_<module>.py` mirrors the source file name.

## Test Structure

**Folder-derived marker (D-13/D-15):**
The root `tests/conftest.py::pytest_collection_modifyitems` hook applies TYPE markers automatically based on folder location. **Never hand-add type markers with `@pytest.mark`** inside test files (this would be redundant and fragile):

```python
# tests/conftest.py auto-marks:
# tests/unit/       → unit
# tests/integration/ → integration + slow
# tests/e2e/        → e2e  (NOT slow — e2e scenarios are tiny ~10-bar runs)
```

**Marker registration:** Only `unit`, `integration`, `slow`, `e2e` are registered in `pyproject.toml`. `--strict-markers` is active — any undeclared marker fails collection.

**Exception:** Some files written early (before the auto-marking hook) carry an explicit `pytestmark = pytest.mark.unit` at the module level. This is harmless duplication but should NOT be added to new test files.

**Function-level test naming:**
```python
def test_<what_is_being_tested>():
    """Short description — optionally cites a decision tag (D-NN)."""
    ...
```

**Class-level test grouping (used selectively in unit tests):**
```python
class TestOrderLifecycle:
    """Group tests for the order lifecycle state machine."""

    def test_order_creation_with_state_tracking(self):
        ...

    def test_valid_state_transitions(self):
        ...
```
Class grouping is used for conceptually cohesive sets (e.g. `TestOrderLifecycle`, `TestTypedFactoryLeverage`). Most tests are standalone module-level functions.

## Mocking

**Framework:** `unittest.mock` (`Mock`, `MagicMock`, `patch`, `patch.dict`).

**When to use `unittest.mock`:**
- `MagicMock` for heavyweight handler collaborators that trigger complex import chains (e.g. `test_event_wiring.py` stubs entire handler modules to isolate `EventHandler`).
- `Mock()` for injected loggers, lightweight single-method dependencies.
- `patch.dict(sys.modules, ...)` to stub module-level imports that would pull in heavy or cyclic dependencies at test collection time.

**Preferred pattern — hand-rolled harness/stub classes:**
Most unit tests use hand-rolled inner classes (named with leading underscore to signal test-private) instead of `unittest.mock`. This is the dominant pattern:

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

```python
class _StubReadModel:
    """Minimal read model for the resolver: available_cash + total_equity only."""

    def __init__(self, available: Decimal = Decimal("10000.00"), ...):
        self._available = available

    def available_cash(self, portfolio_id: PortfolioId) -> Decimal:
        return self._available
```

```python
class _FakeOrder:
    """Hand-rolled order stub for reconcile tests."""
    id = uuid.uuid4()
    status = OrderStatus.PENDING
    filled_quantity = Decimal("0")
```

**Naming convention for test helpers:**
- `_<Name>Harness` — full wiring harness (real queue + real components)
- `_Stub<Name>` — minimal Protocol-conforming stub
- `_Fake<Name>` — lightweight fake with just enough state
- `_Null<Name>` / `_Recording<Name>` — null-object or recording spy

**What NOT to mock:**
- Do not mock the `global_queue` — use `queue.Queue()` directly (the `global_queue` fixture in root conftest).
- Do not mock domain value objects (`Order`, `FillEvent`, `Bar`) — construct them for real.
- Do not mock the `PortfolioReadModel` Protocol with `Mock` when a `_StubReadModel` is available — the Protocol boundary is part of the behavioral contract.

## Fixtures

**Root conftest fixtures (available everywhere):**

```python
@pytest.fixture
def global_queue():
    """A fresh FIFO event queue per test (queue.Queue)."""
    return queue.Queue()

@pytest.fixture
def make_bar_struct():
    """Factory: build a bare Bar value object with Decimal(str(x)) fields."""
    return _bar_struct  # positional (open_, high, low, close, time, volume)

@pytest.fixture
def make_bar():
    """Factory: build a one-ticker BarEvent. Same positional signature."""
    return _bar_event

@pytest.fixture
def make_bar_event():
    """Alias of make_bar."""
    return _bar_event
```

**Integration conftest fixtures (`tests/integration/`):**

```python
@pytest.fixture
def golden_dir():     # → pathlib.Path to tests/golden/
@pytest.fixture
def golden_trades_path():
@pytest.fixture
def golden_equity_path():
@pytest.fixture
def golden_summary_path():

@pytest.fixture
def backtest_engine():
    """Factory: deferred construction of a CSV-fed BacktestTradingSystem.
    Returns a callable _make(ticker, timeframe, start_date, end_date, cash)."""
```

**E2E conftest fixture (`tests/e2e/`):**

```python
@pytest.fixture
def run_scenario(request):
    """Shared harness: load scenario.py → build engine → run → assemble → diff/freeze.
    Returns a callable _run(here: pathlib.Path)."""
```

**Fixture scope:**
- Default (function) scope throughout.
- `scope="module"` used only in integration tests where running the full 2018→2026 oracle once is shared across multiple test functions in the same file (`test_backtest_oracle.py::oracle_run`, `test_reservation_inertness.py`).

## E2E Scenario Pattern

Each scenario under `tests/e2e/<domain>/<scenario_name>/` has exactly two files:

**`scenario.py` — defines `SCENARIO` and strategy:**
```python
# Mandatory: a module-level SCENARIO the harness loads via _load_spec()
SCENARIO = ScenarioSpec(
    start="2020-01-01",
    end="2020-01-06",
    timeframe="1d",
    ticker="BTCUSD",
    starting_cash=_CASH,
    data={_TICKER: HERE / "bars.csv"},
    strategies=[MyStrategy(...)],
    portfolios=[PortfolioSpec(user_id=1, name="my_pf", cash=_CASH)],
    exchange=None,   # or ExchangeConfig(...) for non-zero fee/slippage
)
```

**`test_scenario.py` — single test that delegates to the harness:**
```python
import pathlib
HERE = pathlib.Path(__file__).resolve().parent

def test_<scenario_name>(run_scenario):
    run_scenario(HERE)
```

The leaf adds NO assert/diff logic. All assertions are in the harness (`tests/e2e/conftest.py`).

**`golden/` directory — frozen artifacts (presence = assertion):**
- `trades.csv` — always frozen (required)
- `summary.json` — always frozen (required)
- `equity.csv` — opt-in (only diff'd if the file exists)
- `orders.csv` — opt-in (matching/operator scenarios)
- `cash_operations.csv` — opt-in (cash-edge scenarios)
- `portfolios.csv` — opt-in (multi-portfolio scenarios)

**Freezing goldens (E2E-04 discipline):**
```bash
# Run with --freeze ONLY after hand-verifying arithmetic in scenario.py docstring.
# The --freeze flag is refused when more than ONE test is selected.
poetry run pytest tests/e2e/smoke/single_market_buy/test_scenario.py --freeze
```

**v1.4 scenario subtrees (no `golden/` — inline assertions only):**
The v1.4 scenarios for margin, leverage, shorts, and trailing stops (`forced_liq_long`, `forced_liq_short`, `levered_long`, `levered_long_into_liquidation`, `short_roundtrip`, `short_carry`, `short_scale_in`, `short_scale_in_partial_cover`, `partial_cover`, `trailing_long`, `trailing_short`) use HAND-COMPUTED inline `assert` statements directly on the live portfolio/position/cash state, not the `run_scenario` golden harness. They drive the engine tick-by-tick via a `for time_event in engine.time_generator:` loop and assert on `Decimal`-valued portfolio internals. These tests are marked `e2e` by folder but are NOT diffed against golden CSVs.

## Integration Oracle Pattern

**`tests/integration/test_backtest_oracle.py`:**
- `scope="module"` fixture `oracle_run` runs the FULL 2018→2026 SMA_MACD backtest once (via `scripts/run_backtest.py::main()` imported in-process), writes `output/` artifacts, then compares them to `tests/golden/` artifacts.
- Diff mechanic: `pandas.testing.assert_frame_equal` with `check_exact=True`, NO float tolerance. Sorted by `(entry_date, exit_date, side)` for trades, `(timestamp,)` for equity.
- Module-scoped so the slow full run is shared by the behavioral-identity test and numeric test.

## Golden Freeze Discipline

- Goldens NEVER auto-heal — `--freeze` is the only write path.
- `--freeze` is refused when more than ONE test is selected (enforced mechanically in `run_scenario`).
- A `VERIFY` docstring in `scenario.py` hand-derives the expected fills/PnL before freezing. The golden proves stability; correctness is established once before the freeze.
- Full-backtest oracle re-baselines are named events: `tests/golden/REFREEZE-*.md` records every numerical re-baseline with the decision tag that authorized it.

## Money in Tests

All monetary values in tests use `Decimal` via the string path — never `Decimal(float)`:

```python
# Correct
Decimal("0.95")
Decimal(str(price))
to_money(price)

# Wrong — never do this
Decimal(0.95)   # carries float repr artifact
```

## Error Testing

```python
with pytest.raises(SizingPolicyViolation, match="trail_value"):
    handler.on_signal(bad_signal)

with pytest.raises(ConfigurationError) as exc_info:
    cm.update_config(bad_config)
assert "exceed maximum balance limit" in str(exc_info.value)

with pytest.raises(ValueError) as excinfo:
    reconcile_manager.on_fill(invalid_fill)
```

Always use typed exception classes from `itrader/core/exceptions/`. Never catch bare `Exception` in test assertions.

## Parametrize Usage

`@pytest.mark.parametrize` is used sparingly and only for simple multi-case tables:

```python
@pytest.mark.parametrize("status", ["EXECUTED", "CANCELLED", "REFUSED"])
def test_on_fill_routes_by_status(status):
    ...
```

Most behavioral variation is expressed as separate named test functions (preferred over large parametrize tables) to keep failure messages diagnostic.

## Coverage

**Requirements:** No minimum enforced by configuration — no `--cov-fail-under` set.

**View Coverage:**
```bash
make test-cov   # runs pytest --cov=itrader --cov-report=html --cov-report=term-missing → opens htmlcov/index.html
```

**Known gaps:** Deferred subsystems (`live_trading_system`, `sql_store`, CCXT/OANDA providers, `screeners_handler`, `my_strategies`) carry `ignore_errors = true` in mypy and have minimal test coverage. These are explicitly out of scope.

## Strictness Config

From `pyproject.toml [tool.pytest.ini_options]`:
- `filterwarnings = ["error", "ignore::UserWarning", "ignore::DeprecationWarning"]` — any unexpected warning fails the test. New test code must not emit `FutureWarning` or `RuntimeWarning`.
- `--strict-markers` — only `unit`, `integration`, `slow`, `e2e` are registered; any other marker fails collection.
- `--strict-config` — configuration warnings are errors.
- `--disable-warnings` — suppresses the warnings display (they still FAIL, they just don't print).
- `minversion = "8.0"` — pytest 8+ required.

---

*Testing analysis: 2026-06-22*
