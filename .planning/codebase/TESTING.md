# Testing Patterns

**Analysis Date:** 2026-06-14

## Test Framework

**Runner:**
- `pytest` `^9.0.3` (dev group). `minversion = "8.0"`.
- Config: `pyproject.toml [tool.pytest.ini_options]`.

**Assertion Library:**
- Plain `assert` (pytest rewriting). DataFrame goldens use `pandas.testing.assert_frame_equal` (`check_exact=True`, `check_like=True`, **no float tolerance**).

**Mocking:**
- `unittest.mock` (`Mock`, `MagicMock`) and pytest's `monkeypatch` fixture. No `pytest-mock`/`mocker` in deps.

**Run Commands:**
```bash
make test               # poetry run pytest tests/ -v   (full suite)
make test-unit          # pytest tests/ -v -m "unit"
make test-integration   # pytest tests/ -v -m "integration"
make test-e2e           # pytest tests/ -v -m "e2e"
make test-cov           # --cov=itrader --cov-report=html --cov-report=term-missing; opens htmlcov/index.html

# Domain shortcuts (path filters, NOT marker selectors):
make test-portfolio     # pytest tests/unit/portfolio/ -v
make test-orders        # pytest tests/unit/order/ -v
make test-execution     # pytest tests/unit/execution/ -v
make test-events        # pytest tests/unit/events/ -v
make test-strategy      # pytest tests/unit/strategy/ -v

# Single file / case:
poetry run pytest tests/unit/order/test_order.py -v
poetry run pytest tests/unit/order/test_order.py -k "test_name" -v
```

**Strictness gotchas (`pyproject.toml`):**
- `addopts`: `-ra --strict-markers --strict-config --disable-warnings -v`.
- `filterwarnings = ["error", "ignore::UserWarning", "ignore::DeprecationWarning"]` — an *unexpected* warning fails the suite.
- `--strict-markers` + `--strict-config`: every marker must be declared in `markers`; only `unit`, `integration`, `slow`, `e2e` are registered. Marker registration lives in EXACTLY ONE home (`pyproject.toml`); conftest only *applies*, never registers.

## Test File Organization

**Location:**
- Test root is `tests/` (NOT `test/`). `testpaths = ["tests"]`.
- Type-grouped subtrees: `tests/unit/<domain>/`, `tests/integration/`, `tests/e2e/`, `tests/golden/`.
- 134 `test_*.py` files; ~877 test functions.

**Naming:**
- `python_files = ["test_*.py", "*_test.py"]`, `python_classes = ["Test*"]`, `python_functions = ["test_*"]`.
- Tests mirror source: `test_<module>.py`.

**Structure (TYPE axis — D-13/D-15, folder-derived markers):**
```
tests/
├── conftest.py            # root: folder-derived TYPE markers + global_queue + bar factories
├── unit/                  # drives ONE collaborating component  -> @unit
│   ├── conftest.py        # unit layer anchor (no shared fixtures)
│   ├── config/ core/ events/ execution/{exchanges/} order/ outils/
│   ├── portfolio/{positions/,transaction/} price/ price_handler/ reporting/ strategy/ universe/
├── integration/           # cross-component cascade / oracle  -> @integration (+ @slow)
│   ├── conftest.py        # golden path fixtures + backtest_engine factory
│   ├── _oracle_harness.py
│   └── test_backtest_oracle.py, test_backtest_smoke.py, test_event_wiring.py, ...
├── e2e/                   # tiny full-engine (strategy, data) runs vs goldens -> @e2e (NOT slow)
│   ├── conftest.py        # the run_scenario harness (build→run→read→assemble→diff)
│   ├── strategies/        # shared scenario strategies (e.g. SingleMarketBuy)
│   └── <group>/<leaf>/    # scenario.py + test_scenario.py + bars.csv + golden/
└── golden/               # frozen BTCUSD oracle: trades.csv, equity.csv, summary.json + REFREEZE-*.md
```

**Marker auto-application** (`tests/conftest.py::pytest_collection_modifyitems`):
- file under `tests/unit/` → `unit`
- file under `tests/integration/` → `integration` + `slow`
- file under `tests/e2e/` → `e2e` (NOT `slow`, by design — D-15)

The `make test-portfolio`/`-orders`/etc. targets are **path shortcuts, not marker selectors**.

## Test Structure

**Two authoring styles coexist:**
- Class-based (10 `Test*` classes) with `setup_method` + helper factories:
```python
class TestOrderLifecycle:
    def setup_method(self):
        self.base_time = datetime.now()

    def create_test_order(self, **kwargs) -> Order:
        defaults = {'time': self.base_time, 'type': OrderType.MARKET, ...}
        defaults.update(kwargs)
        return Order(**defaults)

    def test_valid_state_transitions(self):
        order = self.create_test_order()
        assert order.add_fill(order.quantity, order.price, datetime.now())
        assert order.status == OrderStatus.FILLED
```
- Plain functions consuming fixtures (the majority — ~877 functions vs 10 classes):
```python
def test_single_market_buy(run_scenario):
    run_scenario(HERE)
```

## Mocking

**Frameworks:** `unittest.mock` (`Mock`, `MagicMock`) and pytest `monkeypatch`.

**Patterns:**
```python
# Lightweight collaborator stub (tests/unit/order/test_order_manager.py)
logger = Mock()

# monkeypatch to assert a hot-path invariant (tests/unit/price/test_bar_feed.py)
def test_zero_resample_calls_on_per_tick_path(daily_store, monkeypatch):
    monkeypatch.setattr(pd.DataFrame, 'resample', counting_resample)
    # ... assert resample was never called per tick
```

**What to Mock:**
- Cross-domain collaborators a unit doesn't own (`Mock()` for a logger/handler dependency).
- Hot-path methods to *count* calls and lock performance invariants (`monkeypatch.setattr` on `pd.DataFrame.resample`, `Bar.from_row`).

**What NOT to Mock:**
- The `global_queue` — use the real `queue.Queue` from the `global_queue` fixture.
- The full engine in e2e/integration — those run the **real** `BacktestTradingSystem` end-to-end against committed CSV data and frozen goldens. No money/exchange mocks.
- Value objects (`Bar`, events) — build real instances via the shared factory fixtures.

## Fixtures and Factories

**Root cross-cutting fixtures** (`tests/conftest.py`):
- `global_queue` — a fresh `queue.Queue` per test.
- `make_bar_struct` — factory for a bare `Bar` (every field via `Decimal(str(x))`).
- `make_bar` / `make_bar_event` — factory for a one-ticker `BarEvent` (`dict[str, Bar]` payload), keeping the positional `(open, high, low, close)` signature.

**Integration fixtures** (`tests/integration/conftest.py`):
- `golden_dir`, `golden_trades_path`, `golden_equity_path`, `golden_summary_path` — paths to `tests/golden/`.
- `backtest_engine` — factory (callable) that builds a CSV-fed `BacktestTradingSystem`; import is **deferred into the inner function body** so `--collect-only` stays clean.

**E2E harness** (`tests/e2e/conftest.py`):
- `run_scenario(request)` — the SINGLE shared harness. Returns `_run(here)` that imports the leaf's `scenario.py` `SCENARIO`, builds the real system via `build_backtest_system(spec)`, runs it, assembles trades/equity/summary/orders/cash_ops/portfolios via the shared `itrader.reporting` path, and diffs ONLY the golden files present.
- Deferred imports keep `--collect-only` clean (~45 fixtures defined across `tests/unit/`).

**Test data:**
- Per-e2e-leaf hand-written `bars.csv` + a `golden/` subdir (presence = assertion).
- The committed BTCUSD oracle: `tests/golden/{trades,equity}.csv`, `summary.json`.

## Coverage

**Requirements:** None enforced (no coverage gate / no fail-under).

**View Coverage:**
```bash
make test-cov   # pytest --cov=itrader --cov-report=html --cov-report=term-missing; opens htmlcov/index.html
```

## Test Types

**Unit (`tests/unit/`, `@unit`):**
- Drives ONE collaborating component (D-15 boundary). May use the real `global_queue` and several classes from its own domain; does NOT assert cross-component cascades.

**Integration (`tests/integration/`, `@integration` + `@slow`):**
- Asserts interaction ACROSS components — the full cascade, run-path smoke, event-wiring, and the golden-master **oracle** (`test_backtest_oracle.py`, `_oracle_harness.py`).

**E2E (`tests/e2e/`, `@e2e`, NOT slow):**
- Tiny (~10-bar) full-engine runs on a `(strategy, data)` pair vs frozen goldens. One leaf = `scenario.py` (a frozen `ScenarioSpec` exposing module-level `SCENARIO`) + `test_scenario.py` (a one-line delegate to `run_scenario(HERE)`) + `bars.csv` + `golden/`.
- Scenario groups: `admission/`, `cash/`, `cost/`, `matching/{brackets,entries,gaps,operator,never_fill}`, `multi/`, `robust/`, `sizing/`, `sltp/`, `smoke/`.

**Cross-validation oracles (gating):**
- `backtesting.py` `0.6.5` and `backtrader` `1.9.78.123` gate metric cross-validation (`tests/golden/CROSS-VALIDATION.md`); `nautilus-trader` `1.227.0` is a non-gating reconciliation oracle.

## Golden-Master Discipline

- **Exact diff, NO tolerance:** `assert_frame_equal(..., check_exact=True, check_like=True)`. Identity columns (which trade/which bar) are asserted first, then the auto-derived numeric remainder; a float tolerance would mask real regressions.
- **Round-trip normalization:** the fresh frame is serialized through the SAME `to_csv(float_format=FLOAT_FORMAT)` → `read_csv` path the golden was written with, so the diff compares frozen bytes, not engine dtype/precision artifacts (`_roundtrip` in `tests/e2e/conftest.py`).
- **`--freeze` flag (OFF by default):** goldens NEVER auto-heal. `--freeze` WRITES goldens and is **mechanically refused** when more than one test is selected — freeze ONE hand-verified scenario at a time (Pitfall 5). Each freeze is gated by a hand-written VERIFY note in the leaf's `scenario.py` docstring (mirrors `tests/golden/REFREEZE-*.md`).
- **Presence = assertion:** a leaf that froze only `trades.csv` + `summary.json` asserts only those; `equity.csv`/`orders.csv`/`cash_operations.csv`/`portfolios.csv` are opt-in and diffed only if committed.

## Common Patterns

**Error Testing** (39 files use `pytest.raises`):
```python
with pytest.raises(InsufficientFundsError) as exc_info:
    cash_manager.withdraw(...)
# inspect exc_info.value for structured fields when relevant
```

**Parametrize** (10 files): `@pytest.mark.parametrize` for table-driven cases.

**Money in tests:**
- Always enter Decimal via `Decimal(str(x))` (the `_bar_struct` factory does this) — never `Decimal(float)`.

**Determinism in tests:**
- Rely on the seeded RNG (`performance.rng_seed`, default 42) and injected clock; never use wall-clock-dependent assertions on engine output. Portfolio IDs are non-deterministic UUIDv7 — key golden snapshots on the STABLE `PortfolioSpec.name`, never the `PortfolioId` (Pitfall 2).

---

*Testing analysis: 2026-06-14*
