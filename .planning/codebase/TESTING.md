# Testing Patterns

**Analysis Date:** 2026-07-07

## Test Framework

**Runner:**
- pytest ^8.4.2 (`minversion = "8.0"`)
- Config: `pyproject.toml [tool.pytest.ini_options]`
- Discovery: `testpaths = ["tests"]`, `python_files = ["test_*.py", "*_test.py"]`, `python_classes = ["Test*"]`, `python_functions = ["test_*"]`
- The test root is `tests/` (NOT `test/`).

**Assertion Library:**
- Plain `assert` (pytest rewriting). Frame comparisons use `pandas.testing.assert_frame_equal` (aliased `pdt`) with `check_exact=True`, NO float tolerance.

**Strictness (test gotcha):**
- `addopts` includes `--strict-markers` and `--strict-config`; `filterwarnings = ["error", "ignore::UserWarning", "ignore::DeprecationWarning"]`. Any unexpected warning fails the suite. Every marker used must be declared in `pyproject.toml`.
- Async config is REQUIRED under `--strict-config`: `asyncio_mode = "auto"`, `asyncio_default_fixture_loop_scope = "function"` (pytest-asyncio). The plugin registers its own `asyncio` marker (exempt from `--strict-markers`).
- Resource discipline: under `filterwarnings=["error"]`, an unclosed transport session (`ResourceWarning`) or a never-awaited/never-cancelled task (`RuntimeWarning`) escalates to a FAILURE. Every stream task must be cancellable and every client closed in teardown (Pitfall 4).

**Run Commands:**
```bash
make test              # full suite, -m "not live"
make test-unit         # -m "unit"
make test-integration  # -m "integration and not live"
make test-e2e          # -m "e2e"
make test-smoke        # -m "smoke"  (PURPOSE axis, hand-tagged)
make test-live         # -m live  (real network round-trips to a venue)
make test-e2e-live     # tests/e2e/test_okx_sandbox_recon.py -m slow  (slow OKX-demo recon)
make test-cov          # --cov=itrader --cov-report=html --cov-report=term-missing
# domain shortcuts (path selectors, NOT marker selectors):
make test-portfolio    # tests/unit/portfolio/
make test-orders       # tests/unit/order/
make test-execution    # tests/unit/execution/
make test-events       # tests/unit/events/
make test-strategy     # tests/unit/strategy/

# single file / case
poetry run pytest tests/unit/order/test_order.py -v
poetry run pytest tests/unit/order/test_order.py -k "test_name" -v
```

**`make test` gotcha:** `make test` exports `ITRADER_DISABLE_LOGS=true`, which fails `caplog`-based warn-assertion tests (e.g. `test_warn_on_mid_life_gap`). Use `poetry run pytest tests` as the gate for those. In git worktrees, `make test` aborts on a missing `.env` — run `poetry run pytest tests` there instead (and prepend `PYTHONPATH="$PWD"` to defeat editable-install shadowing).

## Marker Axes (two orthogonal axes)

**TYPE axis (folder-derived, auto-applied):** `tests/conftest.py::pytest_collection_modifyitems` stamps the marker from the FOLDER, never the domain:
- `tests/unit/` → `unit`
- `tests/integration/` → `integration` + `slow`
- `tests/e2e/` → `e2e` (NOT `slow` — D-15: e2e scenarios are tiny ~10-bar full-engine runs, kept in the default `make test` suite)

**PURPOSE axis (hand-applied, NEVER folder-derived):**
- `smoke` — fast run-path liveness check. Applied with `@pytest.mark.smoke` or module-level `pytestmark = pytest.mark.smoke`. Stacks on top of the TYPE marker. Files: `tests/integration/test_backtest_smoke.py`, `tests/integration/test_okx_smoke.py`, `tests/unit/reporting/test_plots_smoke.py`.
- `live` — makes a REAL network round-trip to a live venue (OKX). Applied with `@pytest.mark.live`. Excluded from default `make test` (`-m "not live"`). Files: `tests/integration/test_okx_connectivity.py`, `tests/e2e/test_okx_sandbox_recon.py`, `tests/e2e/test_okx_dynamic_universe.py`.

**Registration:** the SINGLE `--strict-markers` source of truth is the `markers` list in `pyproject.toml` (`unit`, `integration`, `slow`, `e2e`, `smoke`, `live`). `conftest.py` only APPLIES; it never registers. Never register in both places.

**Durable rules:**
- Do not hand-apply a TYPE marker — the folder confers it.
- Any new smoke test MUST carry `@pytest.mark.smoke` (or a module `pytestmark`) to join `make test-smoke`.
- `live` is the network property; `skipif` on a credential gate (e.g. `_HAS_OKX_CREDS`) is the creds property — the two are deliberately NOT conflated.

## Test File Organization

**Location:** SEPARATE tree under `tests/`, mirroring the `itrader/` package inside `tests/unit/`. Tests are NOT co-located with source.

```
tests/
├── conftest.py            # root: TYPE auto-marking + global_queue + shared Bar/BarEvent factories + dev-DB env guard + fake_venue_connector
├── README.md              # the authoritative test-layout doc
├── golden/                # frozen-oracle assets (trades.csv, equity.csv, summary.json) + golden/pair/
├── support/               # tree-agnostic doubles: fake_venue_connector.py + support/fixtures/*.json
├── unit/                  # 175 files — ONE collaborating component each
│   ├── conftest.py        # unit-layer anchor
│   ├── config/ core/ outils/ events/ order/ execution/{exchanges/}
│   ├── portfolio/{positions/,reconcile/,transaction/} price/ price_handler/
│   ├── connectors/{conftest.py, fixtures/*.json}   # live-venue connector doubles
│   ├── reporting/ results/ storage/ strategy/ trading_system/ universe/
├── integration/           # 46 files — cross-component cascade, run-path smoke, golden oracle, Postgres
│   ├── conftest.py        # golden-path fixtures + backtest_engine + session Postgres container + remove_policy_harness
│   ├── test_backtest_oracle.py   # full 2018→2026 SMA_MACD run vs frozen oracle
│   ├── storage/{conftest.py}     # PG-backed order storage
│   └── pair_exit_safety/
└── e2e/                   # 62 files — per-scenario leaf folders (build→run→read→assemble→diff)
    ├── conftest.py        # the shared run_scenario harness + --freeze flag
    └── <category>/<scenario>/{scenario.py, test_scenario.py, golden/}
```

**Naming:** `test_<module>.py`; test functions `test_*`; optional test classes `Test*`.

**Test style:** predominantly **module-level `def test_*` functions** (~278 files) with fixtures. A minority (6 files) use `class Test*` with `setup_method`/helper methods (e.g. `tests/unit/order/test_order.py`). Prefer the function+fixture style for new tests.

## The unit / integration / e2e boundary (D-15)

- **unit** — drives ONE collaborating component. May import several classes from its own domain and use a real `global_queue`, but does NOT assert cross-component cascades.
- **integration** — asserts interaction ACROSS components: cross-domain, cross-manager, the full cascade, the run-path smoke, or the golden oracle.
- **e2e** — a full engine run on a `(strategy, data)` pair (or a tiny hand-crafted scenario) diffed against committed frozen goldens.

## Test Structure

**Function + fixture (dominant):**
```python
def test_single_market_buy(run_scenario):
    run_scenario(HERE)          # e2e leaf: delegate to the shared harness, no local asserts
```

**Class-based (legacy minority):**
```python
class TestOrderLifecycle:
    def setup_method(self):
        self.base_time = datetime.now()
    def create_test_order(self, **kwargs) -> Order: ...
    def test_order_properties(self):
        order = self.create_test_order(quantity=100.0, price=150.0)
        assert order.remaining_quantity == 100.0
```

**Patterns:**
- Setup via fixtures (`@pytest.fixture`, 84 files) or `setup_method` in classes.
- Teardown via fixture `yield` + `finally` (mandatory for anything holding a socket/thread — Pitfall 4).
- Assertions are plain `assert`; error paths use `pytest.raises` (76 files).

## Fixtures and Factories

**Shared root fixtures (`tests/conftest.py`):**
- `global_queue` — a fresh `queue.Queue` per test (the constructor convention).
- `make_bar` / `make_bar_event` / `make_bar_struct` — factory fixtures returning helpers that build a `Bar` / one-ticker `BarEvent` with every field entered via `Decimal(str(x))` (money correctness).
- `fake_venue_connector` — a connected, teardown-safe `FakeLiveConnector` (the single credential-free reconciliation double, from `tests/support/fake_venue_connector.py`).
- `_block_dev_database_env` (session, autouse) — pops the six `ITRADER_DATABASE_*` dev-DB env vars so no test can reach the developer's operational Postgres; a function-scoped `monkeypatch.setenv` naturally overrides it.

**Integration fixtures (`tests/integration/conftest.py`):**
- `golden_dir` / `golden_trades_path` / `golden_equity_path` / `golden_summary_path` — frozen-oracle asset paths.
- `backtest_engine` — factory returning a `_make(...)` callable that builds a CSV-fed `BacktestTradingSystem` (import DEFERRED so `--collect-only` stays clean).
- `pg_container_url` (session) — ONE `testcontainers` Postgres for the whole integration tree; import deferred, ANY startup failure → `pytest.skip` (D-11, never hard-fails a Dockerless run).
- `pg_database_env` — points the `ITRADER_DATABASE_URL` gate at the shared container within test scope.
- `remove_policy_harness` — factory building a two-symbol paper/replay `LiveTradingSystem` for universe remove-policy tests, driving the REAL provider→feed→exchange→portfolio path offline.

**Fixture idiom — DEFER heavy imports:** factory fixtures return an inner `_make(...)`/`_run(...)` callable and import heavy engine/connector/testcontainers code INSIDE the body so `--collect-only` and offline collection never trigger the import.

**Static fixture data:** JSON canned payloads under `tests/support/fixtures/okx_recon_payloads.json` and `tests/unit/connectors/fixtures/*.json` (`okx_business_candles.json`, `okx_order_lifecycle.json`).

## Mocking

**Framework:** `unittest.mock` (`Mock`, `MagicMock`, `AsyncMock`, `patch`) — used in ~40 files. `monkeypatch` (pytest) used in ~28 files, primarily for env vars and attribute patching.

**Patterns:**
```python
from unittest.mock import AsyncMock, MagicMock, patch
import ccxt.pro as ccxtpro

# Construct a REAL client offline (no socket opens); mock only the network edge (load_markets),
# so the test proves genuine ccxt routing rather than a fake's echo.
```

**What to Mock:**
- The network edge only (e.g. ccxt `load_markets`/`fetch_*`), while exercising the real transport/routing object.
- Live-venue connectors are replaced by `FakeLiveConnector` (a full daemon-thread loop + canned `watch_*`/`fetch_*` streams), NOT ad-hoc mocks, for reconciliation tests.

**What NOT to Mock:**
- Do NOT mock the engine internals in e2e/integration — the harness builds a REAL `BacktestTradingSystem`/`LiveTradingSystem` via the same `build_backtest_system` factory the run path uses (no parallel/reinvented config).
- Fakes intentionally return FLOATS everywhere (ccxt behavior); do NOT pre-Decimalize in the double — downstream code must route through `to_money(str(...))` (Pitfall 2).

## Golden-Master / Oracle & Cross-Validation Patterns

**Backtest oracle** (`tests/integration/test_backtest_oracle.py`, `integration`+`slow`):
- Runs the FULL SMA_MACD backtest 2018→2026 by invoking the committed generator `scripts/run_backtest.py::main` in-process, then diffs fresh `output/{trades,equity}.csv`+`summary.json` against committed `tests/golden/` with `assert_frame_equal(check_exact=True)` — NO float tolerance.
- Behavioral identity columns are the LAW: trades keyed on `(entry_date, exit_date, side)` + `pair`; equity on `timestamp`; summary on `trade_count` + numeric keys. Numerics are asserted EXACT as of the M2b/M5b re-freeze.
- Re-freeze discipline is documented in `tests/golden/REFREEZE-*.md`; the numerical oracle re-baselines at exactly two program points.

**E2E scenario harness** (`tests/e2e/conftest.py::run_scenario`) — the shared build→run→read→assemble→diff contract:
- A scenario is a leaf folder with `scenario.py` (a module-level `SCENARIO` `ScenarioSpec`), a one-line `test_scenario.py` that calls `run_scenario(HERE)`, and a `golden/` subdir. Authors edit ONLY their leaf — never the conftest, no central registry (parallel-safe by construction).
- The harness builds a real system via `build_backtest_system(spec)`, runs it (`print_summary=False`), reads portfolio state AFTER the run (queue-only, no mid-run cross-domain reads), assembles `trades`/`equity`/`summary`/`orders`/`cash_ops`/`portfolios` via the SHARED `itrader.reporting.*` path, and diffs ONLY the golden files present (presence = assertion) with the oracle's exact no-tolerance mechanic.
- `--freeze` flag (OFF by default) WRITES goldens; goldens NEVER auto-heal. It is mechanically refused when >1 test is selected — freeze ONE hand-verified scenario at a time, commit WITH a VERIFY note.
- Non-deterministic UUIDv7 ids must NOT be golden keys; snapshots key on stable business names (`PortfolioSpec.name`).

**External cross-validation oracles:** `backtesting.py` (0.6.5) and `backtrader` (1.9.78.123) are the GATING cross-validation oracles (`tests/golden/CROSS-VALIDATION.md`); `nautilus-trader` (1.227.0) is a non-gating reconciliation oracle. M5 is the only milestone allowed to change results, validated against these.

## Live-Trading Test Conventions (v1.7)

- Live-venue tests carry `@pytest.mark.live`; default CI (`-m "not live"`) never touches the network.
- ALL connector imports (`ccxt`, `ccxt.pro`, connector code) are LAZY (inside test bodies) so `not live` / offline collection stays fast and import-free.
- Credential gate: `_HAS_OKX_CREDS = all(os.environ.get(v) for v in ("OKX_API_KEY", "OKX_API_SECRET", "OKX_API_PASSPHRASE"))`, applied as `skipif` — SEPARATE from the `live` network flag.
- Offline reconciliation uses the shared credential-free `FakeLiveConnector` double (daemon-thread loop, `run_coroutine_threadsafe` RPC, cancellable stream tasks, client closed in teardown).
- The `paper` venue (offline `SimulatedExchange`) drives real synchronous provider→feed→exchange→portfolio paths for universe/remove-policy tests without any socket (`remove_policy_harness`).
- Sandbox safety: OKX demo creds are a demo sub-account; always verify `sandbox=True` routing before any order (the `sandbox` misroute test is the highest-severity gating assertion, `test_okx_connector.py`).

## Test Types

**Unit (`tests/unit/`, 175 files):** ONE component in isolation, real `global_queue`, no cross-component cascade.

**Integration (`tests/integration/`, 46 files):** cross-component cascade, run-path smoke, the golden oracle, Postgres-backed storage (session container, skips when Docker absent).

**E2E (`tests/e2e/`, 62 files):** per-scenario leaf folders diffed against frozen goldens; plus opt-in `live`/`slow` OKX-sandbox recon and dynamic-universe suites.

## Coverage

**Requirements:** None enforced (no coverage threshold in config).

**View Coverage:**
```bash
make test-cov          # opens htmlcov/index.html
```

## Common Patterns

**Error Testing:**
```python
with pytest.raises(InsufficientFundsError):
    ...
```

**Parametrization** (~19 files):
```python
@pytest.mark.parametrize("domain_base", [PortfolioError, OrderError, DataError])
def test_domain_bases(domain_base): ...
```

**Log-assertion testing** (`caplog`, ~8 files): assert on emitted structlog records — run via `poetry run pytest` (NOT `make test`, which disables logs).

**Temp files** (`tmp_path`, ~8 files): any disk debugging uses pytest `tmp_path` only, NEVER the committed `golden/`.

**Async:** `asyncio_mode = "auto"` means `async def test_*` runs without a per-test marker; live-connector loops run on daemon threads via `run_coroutine_threadsafe` rather than in-test event loops.

---

*Testing analysis: 2026-07-07*
