# Testing Patterns

**Analysis Date:** 2026-06-27

## Test Framework

**Runner:**
- pytest ^9.0.3 (`minversion = "8.0"`)
- Config: `pyproject.toml [tool.pytest.ini_options]`
- Plugins: `pytest-cov` ^7.1.0 (coverage), `pytest-html` ^4.2.0 (HTML report)

**Assertion Library:**
- Plain `assert` for scalar/enum checks.
- `pandas.testing.assert_frame_equal` (imported as `pdt`) for golden/oracle frame diffs — EXACT, no tolerance (D-08/D-13).

**Discovery (`pyproject.toml`):**
- `testpaths = ["tests"]` — root is `tests/`, NOT `test/`.
- `python_files = ["test_*.py", "*_test.py"]`, `python_classes = ["Test*"]`, `python_functions = ["test_*"]`.

**Strictness (test gotcha):**
- `filterwarnings = ["error", "ignore::UserWarning", "ignore::DeprecationWarning"]` — an unexpected warning fails the test.
- `--strict-markers` + `--strict-config` — every marker must be declared; unregistered marker = error.
- `addopts` also includes `-ra`, `--disable-warnings`, `-v`.

**Run Commands:**
```bash
make test              # full suite: poetry run pytest tests/ -v
make test-unit         # -m "unit"
make test-integration  # -m "integration"
make test-e2e          # -m "e2e"
make test-cov          # --cov=itrader --cov-report=html --cov-report=term-missing -> htmlcov/index.html
make test-portfolio    # path shortcut: tests/unit/portfolio/
make test-orders       # path shortcut: tests/unit/order/
make test-execution    # path shortcut: tests/unit/execution/
make test-events       # path shortcut: tests/unit/events/
make test-strategy     # path shortcut: tests/unit/strategy/

poetry run pytest tests/unit/order/test_order.py -v            # single file
poetry run pytest tests/unit/order/test_order.py -k "name" -v  # single case
```

**Gotcha (from project memory):** `make test` exports `ITRADER_DISABLE_LOGS=true`, which fails `caplog` warn-assertion tests; in worktrees it also aborts on a missing `.env`. Use `poetry run pytest tests` directly as the gate when those bite.

## Markers (TYPE axis, D-13)

Markers are registered in EXACTLY ONE place — `pyproject.toml markers` — and only
four exist: **`unit`, `integration`, `slow`, `e2e`**. They are **folder-derived**,
applied automatically by `tests/conftest.py::pytest_collection_modifyitems` (never
hand-added on a test):

| Folder | Markers applied | Meaning (D-15 boundary) |
|--------|-----------------|--------------------------|
| `tests/unit/` | `unit` | Drives ONE collaborating component (may use a real `global_queue` + several classes from its own domain). |
| `tests/integration/` | `integration` + `slow` | Asserts interaction ACROSS components (full cascade / smoke / oracle). |
| `tests/e2e/` | `e2e` (NOT `slow`) | Tiny (~10-bar) full-engine runs vs frozen goldens — stays in default `make test`. |

The domain-specific `make` targets (`test-portfolio`, etc.) are path shortcuts, not
marker selectors.

## Test File Organization

**Location:** Separate `tests/` tree, mirroring source by domain — NOT co-located.

```
tests/
├── conftest.py              # root: folder-derived markers + global_queue, make_bar* fixtures
├── unit/                    # 106 test files — per-domain subdirs
│   ├── conftest.py          # unit layer anchor
│   ├── order/  portfolio/  execution/  events/  strategy/
│   ├── core/  config/  price_handler/  reporting/  universe/  outils/
├── integration/             # 11 test files — cross-component + oracle
│   ├── conftest.py          # golden_* path fixtures + backtest_engine factory
│   ├── test_backtest_oracle.py   # SMA_MACD byte-exact oracle (the law)
│   ├── _oracle_harness.py        # shared repo-root/loader constants (IN-03)
│   └── pair_exit_safety/
├── e2e/                     # 60 test files — per-leaf scenario harness
│   ├── conftest.py          # run_scenario contract + --freeze flag
│   └── <scenario>/<leaf>/   # scenario.py + golden/ subdir per leaf
└── golden/                  # frozen oracle ARTIFACTS only (trades/equity.csv, summary.json) — 0 tests
```

**Naming:** `test_<module>.py` mirroring source; test classes `Test<Name>`; functions `test_<behavior>`.

**Counts (current):** 177 test files total — 106 unit, 11 integration, 60 e2e.

## Test Structure

**Function-style (most common):**
```python
def test_order_manager_initialization():
    """Test OrderManager initialization.

    D-18: the manager owns the storage and takes NO OrderHandler back-reference.
    """
    order_storage = InMemoryOrderStorage()
    logger = Mock()
    om = OrderManager(order_storage, logger, market_execution="immediate")
    assert om.market_execution is MarketExecution.IMMEDIATE
    assert not hasattr(om, "order_handler")
```

**Class-style (grouped, with `setup_method`):**
```python
class TestEnhancedOrderValidator:
    """Docstring cites the decision tag the suite locks (D-13)."""
    def setup_method(self):
        self.portfolio_handler = Mock()
        self.portfolio_handler.available_cash.return_value = Decimal("20000.00")
        self.validator = EnhancedOrderValidator(self.portfolio_handler)
```

**Local harness helper (per-file, NOT a shared fixture):**
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

**Patterns:**
- Docstrings cite the decision tag (`D-NN` / `WR-NN`) the test locks — load-bearing, preserve.
- Money values entered via `Decimal(str(x))` in tests too (never `Decimal(float)`).
- Indentation in `tests/` is 4 SPACES throughout (matches `tests/conftest.py`), even though many `itrader/` handler modules use tabs.

## Fixtures and Factories

**Cross-cutting (root `tests/conftest.py`):**
- `global_queue` — a fresh `queue.Queue()` per test.
- `make_bar` / `make_bar_event` — build a one-ticker `BarEvent` with a `dict[str, Bar]` payload (positional `(open, high, low, close)`).
- `make_bar_struct` — build a bare `Bar` value object; all fields via `Decimal(str(x))`.

**Integration (`tests/integration/conftest.py`):**
- `golden_dir`, `golden_trades_path`, `golden_equity_path`, `golden_summary_path` — resolve to committed `tests/golden/`.
- `backtest_engine` — a FACTORY callable (returns `_make(...)`) so `BacktestTradingSystem` construction is DEFERRED until a test invokes it (the import lives inside the inner body so `--collect-only` survives un-wired branches).

**Local data builders:** many files define a per-file `_Harness` class or `create_test_order(**kwargs)` helper with a `defaults` dict updated by kwargs, instead of a shared fixture. ~72 `@pytest.fixture` definitions total across the suite.

## Mocking

**Framework:** `unittest.mock.Mock` (~31 files use mock/monkeypatch).

**Patterns:**
```python
# Stub the narrow Protocol surface, NOT concrete attributes (D-16):
self.portfolio_handler = Mock()
self.portfolio_handler.available_cash.return_value = Decimal("20000.00")
self.portfolio_handler.get_position.return_value = None  # flat
self.portfolio_handler.open_position_count.return_value = 5

# A bare logger stub where logging is incidental:
logger = Mock()
```

**What to Mock:**
- The `PortfolioReadModel` Protocol's six methods when testing `OrderManager`/validators in isolation.
- The logger when it is incidental to the unit under test.

**What NOT to Mock:**
- The event queue — use a real `queue.Queue` (`global_queue` fixture). Unit tests drive a real queue + real same-domain classes.
- The full engine in integration/e2e — those build a REAL `BacktestTradingSystem` via the same composition factory the run path uses (no parallel/reinvented config).
- Money/Decimal math — never stubbed.

## Golden-Master / Oracle Testing (the law)

**Integration oracle — `tests/integration/test_backtest_oracle.py`:**
- Runs the FULL 2018→2026 `SMA_MACD` backtest in-process via the committed generator (`scripts/run_backtest.py::main`), writing fresh `output/{trades,equity}.csv` + `summary.json`.
- Loads BOTH the fresh `output/` and committed `tests/golden/` and asserts EQUAL on deterministic columns with NO float tolerance (D-16, exact).
- Trade identity: `(entry_date, exit_date, side)` + `pair`; equity by `timestamp`; summary by `trade_count` (+ numeric keys `final_cash`/`final_equity`/`total_realised_pnl`, re-frozen exact at M2b/M5b).
- Module-scoped fixture `oracle_run` runs the slow backtest ONCE; `pytest.skip` if `tests/golden/` is not yet frozen.

**E2E scenario harness — `tests/e2e/conftest.py::run_scenario`:**
- Each leaf folder owns a `scenario.py` (a `ScenarioSpec`) + a `golden/` subdir. Authors edit ONLY their leaf, never the shared conftest — parallel-safe by construction.
- Contract: import spec → build real engine via `build_backtest_system(spec)` → run → read portfolio state post-run (queue-only, D-07) → assemble `trades`/`equity`/`summary` via the SHARED `itrader.reporting.summary` path → diff vs `golden/` with exact `assert_frame_equal`, diffing ONLY golden files present (presence = assertion).
- Results stay in memory; disk debugging uses `tmp_path` only, never the committed `golden/`.
- **`--freeze` flag** (`pytest_addoption`, OFF by default): regenerates goldens. Discipline — freeze ONE scenario at a time AFTER hand-verifying its fills/PnL, commit with a VERIFY note. Each `scenario.py` carries a `================ VERIFY ================` block with the hand-derived math. A regression-lock proves stability, not correctness.

## Determinism / Robustness Tests

- E2E robustness leaves run each scenario TWICE in-process and assert all six artifacts identical via `assert_frame_equal` (`tests/e2e/robust/test_determinism.py`, ROBUST-04) — proves seeded-RNG + injected-clock reproducibility independent of golden correctness.

## Coverage

**Requirements:** None enforced (no fail-under threshold).

**View Coverage:**
```bash
make test-cov   # writes htmlcov/index.html and prints term-missing
```

## Common Patterns

**Parametrization (~12 files):**
```python
@pytest.mark.parametrize("leaf_dir", PHASE9_LEAVES, ids=lambda p: p.name)
def test_double_run_identical(leaf_dir):
    ...
```

**Error testing (~48 `pytest.raises` sites):**
```python
with pytest.raises(InsufficientFundsError):
    handler.on_signal(signal)
```
For execution-layer rejections, assert on the emitted `FillEvent(REFUSED)` (rejections flow as events, not exceptions), not on a raised exception.

**Frame equality (golden diffs):**
```python
import pandas.testing as pdt
pdt.assert_frame_equal(fresh.sort_values(KEYS).reset_index(drop=True),
                       golden.sort_values(KEYS).reset_index(drop=True))
```

**Test types:**
- **Unit** — one component in isolation, real `global_queue`, mocked read-model Protocol where needed.
- **Integration** — cross-component cascade + the full-engine SMA_MACD oracle (`slow`).
- **E2E** — tiny full-engine `(strategy, data)` scenarios vs frozen goldens.

---

*Testing analysis: 2026-06-27*
