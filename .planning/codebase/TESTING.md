<!-- last_mapped_commit: 6b15b25 -->
# Testing Patterns

**Analysis Date:** 2026-06-30

## Test Framework

**Runner:**
- pytest ^9.0.3 (dev group). Config: `pyproject.toml [tool.pytest.ini_options]` (`minversion = "8.0"`, `testpaths = ["tests"]`).
- Discovery: `python_files = ["test_*.py", "*_test.py"]`, `python_classes = ["Test*"]`, `python_functions = ["test_*"]`.

**Assertion Library:**
- Plain `assert` (pytest rewriting). DataFrame equality via `pandas.testing.assert_frame_equal` (no-tolerance, exact) — the golden/oracle mechanic.

**Strictness (correctness gate — `pyproject.toml`):**
- `addopts = ["-ra", "--strict-markers", "--strict-config", "--disable-warnings", "-v"]`.
- `filterwarnings = ["error", "ignore::UserWarning", "ignore::DeprecationWarning"]` — an unexpected warning fails the suite (e.g. an undisposed SQLAlchemy `Engine` trips a `ResourceWarning`, so every engine/backend fixture disposes in a `finally`).
- `--strict-markers`: only `unit`, `integration`, `slow`, `e2e` are registered (in `pyproject.toml::markers` — the SINGLE registration home). Using any other marker fails collection.

**Run Commands:**
```bash
make test              # poetry run pytest tests/ -v   (all)
make test-unit         # -m "unit"
make test-integration  # -m "integration"
make test-e2e          # -m "e2e"
make test-cov          # --cov=itrader --cov-report=html --cov-report=term-missing
poetry run pytest tests/unit/order/test_order.py -k "test_name" -v   # single case
```
- `make test` exports `ITRADER_DISABLE_LOGS=true`; for `caplog` warn-assertion tests use `poetry run pytest tests` instead.
- In a git worktree, `make test` aborts on a missing `.env` — run `poetry run pytest tests` there, re-run `make test` in the main checkout.

## Test File Organization

**Location (separate, type-grouped tree — NOT co-located):**
- Test root is `tests/` (NOT `test/`).
- `tests/unit/<domain>/` — drives ONE collaborating component (D-15 unit boundary). Domains: `order/`, `portfolio/`, `execution/`, `events/`, `strategy/`, `core/`, `config/`, `price_handler/`, `reporting/`, `outils/`, `universe/`, and the v1.6 `storage/` + `results/`.
- `tests/integration/` — asserts interaction ACROSS components (cross-domain, full cascade, oracle). v1.6 added `tests/integration/storage/` (SQL-spine round-trips, migrations, cross-backend parity).
- `tests/e2e/<scenario>/<leaf>/` — tiny (~10-bar) full-engine runs vs frozen goldens; each leaf is self-contained.
- `tests/golden/` — committed frozen-oracle ARTIFACTS (`trades.csv`, `equity.csv`, `summary.json`); collects 0 tests. The byte-exact SMA_MACD oracle test itself lives at `tests/integration/test_backtest_oracle.py`.

**Naming:**
- `test_<module>.py` mirrors the source module. ~327 test files; ~191 are function-based, 5 use `Test*` classes.

**Package-collision gotcha:**
- `tests/unit/<x>` dirs are intentionally **package-less** (NO `__init__.py`). An empty `__init__.py` in both `tests/unit/<x>` and `tests/integration/<x>` creates two top-level `<x>` packages and breaks full-suite collection. e2e leaves DO carry `__init__.py` (the harness derives a unique module name per leaf).

## Test Structure

**Marker auto-application (D-13/D-15 — `tests/conftest.py`):**
The TYPE marker is derived from the FOLDER by `pytest_collection_modifyitems`, never decorated by hand:
```python
def pytest_collection_modifyitems(config, items):
    for item in items:
        parts = pathlib.Path(str(item.fspath)).parts
        if "unit" in parts:
            item.add_marker(pytest.mark.unit)
        if "integration" in parts:
            item.add_marker(pytest.mark.integration)
            item.add_marker(pytest.mark.slow)   # integration is also slow
        if "e2e" in parts:
            item.add_marker(pytest.mark.e2e)     # e2e is NOT slow (D-15)
```
`pyproject.toml` REGISTERS markers; `conftest.py` only APPLIES them (`--strict-markers` source of truth lives in one place).

**Layered conftests:**
- `tests/conftest.py` — cross-cutting fixtures (`global_queue`, `make_bar`/`make_bar_struct`/`make_bar_event`) + the marker hook.
- `tests/unit/conftest.py` — layer anchor (docstring only).
- `tests/integration/conftest.py` — `golden_dir`/`golden_*_path` fixtures + the `backtest_engine` factory.
- `tests/integration/storage/conftest.py` — v1.6 DB substrate (`pg_engine`, `engine`, `pg_backend`).
- `tests/e2e/conftest.py` — the shared `run_scenario` harness.

**Predominant style — function-based with leading-underscore builders:**
```python
def _make_order(**overrides):
    """Build a fully-populated Order with unique UUIDv7 ids (overridable per field)."""
    base = dict(time=_BT, type=OrderType.LIMIT, ..., portfolio_id=PortfolioId(uc.uuid7()))
    base.update(overrides)
    return Order(**base)

def test_order_round_trip_field_wise_equal(pg_backend):
    """OPS-01 — a full Order round-trips D-10 field-wise EQUAL."""
    storage = SqlOrderStorage(pg_backend)
    order = _make_order()
    ...
```
Legacy `Test*` classes with `setup_method`/helper methods exist (`tests/unit/order/test_order.py::TestOrderLifecycle`) but new tests are flat functions.

## Mocking

**Framework:** `unittest.mock` (`Mock`, `MagicMock`) and pytest `monkeypatch`, used sparingly (handful of files, mostly `tests/unit/order/` and `tests/unit/core/`).

**Preferred substitution — REAL collaborators over mocks:**
- Unit tests use a real `global_queue` and real domain classes; the suite favors lightweight builders and a real `:memory:` SQLite spine over mocking the persistence layer.
- v1.6 storage tests construct a real `SqlResultsStore` / `SqlOrderStorage` over an in-process SQLite (or testcontainers Postgres) engine rather than mocking SQLAlchemy.

**What to Mock:**
- Wall-clock / external-process boundaries and the occasional collaborator a unit test must not drive (`Mock` in order-manager tests).

**What NOT to Mock:**
- The event queue, money/Decimal math, the SQL backend (use `:memory:` SQLite), or the engine composition path (e2e uses the REAL `build_backtest_system` factory — no parallel config schema).

## Fixtures and Factories

**Shared value-object factories (`tests/conftest.py`):**
- `global_queue` — a fresh `queue.Queue` per test.
- `make_bar` / `make_bar_event` / `make_bar_struct` — build a one-ticker `BarEvent` / bare `Bar`; every numeric field enters Decimal via `Decimal(str(x))`.

**Engine / backtest factories (deferred-import pattern):**
- `backtest_engine` (`tests/integration/conftest.py`) — returns a CALLABLE so `BacktestTradingSystem` construction is deferred until invoked; the import lives inside the inner function so `--collect-only` succeeds.

**v1.6 DB substrate (`tests/integration/storage/conftest.py`):**
- `pg_engine` — SESSION-scoped testcontainers `PostgresContainer("postgres:16")` `Engine` (D-10). Heavy `testcontainers`/`docker` imports are deferred into the body; ANY startup failure converts to `pytest.skip` (D-11) so a Dockerless run stays green. Disposes the engine + stops the container in `finally`.
- `engine` — function-scoped, `indirect`-parametrizable: `"sqlite"` → fresh `sqlite+pysqlite:///:memory:`, `"postgres"` → the session `pg_engine`. Cross-backend parity tests parametrize:
  ```python
  @pytest.mark.parametrize("engine", ["sqlite", "postgres"], indirect=True)
  def test_roundtrip(engine): ...
  ```
- `pg_backend` — function-scoped `SqlBackend` bound to the SAME container DB via the `SqlSettings` verbatim-URL escape hatch (`url=SecretStr(container_url)`) so no second container spins; disposed in `finally` (Pitfall 4 — undisposed engine → `ResourceWarning` under `filterwarnings=["error"]`).

**Results-store fixture (`tests/unit/results/test_sql_results_store.py`):**
```python
@pytest.fixture
def store() -> Any:
    backend = SqlBackend(SqlSettings())          # in-process SQLite :memory:
    results_store = SqlResultsStore(backend)
    try:
        yield results_store
    finally:
        backend.dispose()
```

**Test data:** leading-underscore module-level builders with `**overrides` (`_metrics`, `_portfolio`, `_run`, `_frame`, `_run_id`). Money/ids minted via `Decimal(str(...))` and `idgen._uuid7()` / `uuid_utils.compat.uuid7()`.

## Coverage

**Requirements:** None enforced (no fail-under threshold). HTML report via:
```bash
make test-cov          # --cov=itrader --cov-report=html --cov-report=term-missing -> htmlcov/index.html
```

## Test Types

**Unit (`tests/unit/`):** one collaborating component; real `global_queue` allowed; in-process SQLite for storage. ~majority of the ~327 files.

**Integration (`tests/integration/`):** cross-component cascade, run-path smoke, the byte-exact SMA_MACD oracle (`test_backtest_oracle.py`), and the v1.6 SQL-spine suite (`tests/integration/storage/` — round-trips, Alembic migrations, cross-backend parity). Auto-marked `integration` + `slow`.

**E2E (`tests/e2e/`):** ~10-bar full-engine scenarios vs frozen `golden/` subfolders, run through the shared `run_scenario` harness (build → run → read-after-run → assemble via `itrader.reporting.summary` → diff with no-tolerance `assert_frame_equal`). Each leaf = `scenario.py` (`ScenarioSpec` + a VERIFY note) + `bars.csv` + `golden/`. Goldens NEVER auto-heal — regen only via the off-by-default `--freeze` flag, one hand-verified scenario at a time.

**Cross-validation oracles (gating):** `backtesting.py` 0.6.5 and `backtrader` 1.9.78.123 (`tests/golden/CROSS-VALIDATION.md`); `nautilus-trader` 1.227.0 is a non-gating reconciliation oracle.

## Common Patterns

**Round-trip / byte-determinism (v1.6 persistence):**
```python
def test_codec_roundtrip(store):
    frame = _frame()
    decoded = store._decode_frame(store._encode_frame(frame))
    assert_frame_equal(decoded, frame)          # value-equal, dtype-stable

def test_codec_byte_determinism(store):
    assert store._encode_frame(_frame()) == store._encode_frame(_frame())
```

**Backend-gated money assertions:** money/exact-Decimal arms run on the Postgres `pg_backend` fixture only (SQLite `Numeric` decays to float — Pitfall 2); backend-free arms (determinism) always run.

**Error Testing:**
```python
def test_get_artifact_unknown_run_raises(store):
    with pytest.raises(ResultsNotFound):
        store.get_artifact(uuid.uuid4())
```
~53 files use `pytest.raises`.

**Import-quarantine via subprocess (`tests/unit/storage/test_import_quarantine.py`):**
- Runs a probe in a FRESH interpreter (`subprocess.run([sys.executable, "-c", _PROBE])`) because sibling tests already import SQLAlchemy in-session, so an in-process `sys.modules` check is unreliable. Asserts the backtest storage arm pulls no `sqlalchemy` and no `cached_sql_storage` wrapper, printing a `QUARANTINE_OK` sentinel.

**Migrations testing (`tests/integration/storage/test_migrations.py`):** applies the Alembic operational-baseline chain on testcontainers Postgres, asserts the built tables + `alembic_version` stamp, then reverses (`downgrade base`) and drops `alembic_version` so the shared session container stays clean for sibling tests.

---

*Testing analysis: 2026-06-30*
