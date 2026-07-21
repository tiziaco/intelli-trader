# Testing Patterns

**Analysis Date:** 2026-07-21 (refresh of 2026-07-07 doc; verified post v1.8 Phases 8-10.1)

## Test Framework

**Runner:**
- pytest ^8.4.2 (`minversion = "8.0"`), config in `pyproject.toml::[tool.pytest.ini_options]`
- `testpaths = ["tests"]` (NOT `test/`)
- pytest-asyncio 1.4.0 — `asyncio_mode = "auto"` (every `async def test_*` runs without a per-test `@pytest.mark.asyncio`), `asyncio_default_fixture_loop_scope = "function"` (both keys REQUIRED under `--strict-config`; an unset loop scope emits a config warning that escalates to an error under `filterwarnings=["error"]`). The plugin's own `asyncio` marker is exempt from `--strict-markers`.

**Assertion Library:**
- Plain `assert` (pytest-native). `pandas.testing.assert_frame_equal` / `pdt` used for the oracle diff (`tests/integration/test_backtest_oracle.py`).

**Coverage:**
- pytest-cov ^7.1.0 — `make test-cov` runs `--cov=itrader --cov-report=html --cov-report=term-missing`, opens `htmlcov/index.html`. No coverage minimum/threshold enforced in `pyproject.toml`.
- pytest-html ^4.2.0 is a dependency but the `test-report` Makefile target is commented out (`Makefile:108-110`) — not currently wired up.

**Run Commands:**
```bash
make test              # poetry run pytest tests/ -v -m "not live"   (excludes live-venue tests)
make test-unit         # poetry run pytest tests/ -v -m "unit"
make test-integration  # poetry run pytest tests/ -v -m "integration and not live"
make test-e2e          # poetry run pytest tests/ -v -m "e2e"
make test-smoke        # poetry run pytest tests/ -v -m "smoke"
make test-live         # poetry run pytest tests/ -v -m live   (fast opt-in live-venue connectivity checks, e.g. tests/integration/test_okx_connectivity.py)
make test-e2e-live     # slow OKX-demo reconciliation e2e suite only (tests/e2e/test_okx_sandbox_recon.py -m slow); requires OKX_API_KEY in .env, unsets DB env vars to force in-memory fallback
make test-portfolio    # poetry run pytest tests/unit/portfolio/ -v
make test-orders       # poetry run pytest tests/unit/order/ -v
make test-execution    # poetry run pytest tests/unit/execution/ -v
make test-events       # poetry run pytest tests/unit/events/ -v      (path shortcut only, NOT a marker selector)
make test-strategy     # poetry run pytest tests/unit/strategy/ -v
make test-cov          # poetry run pytest tests/ --cov=itrader --cov-report=html --cov-report=term-missing -v
```

Single test / single case (not a Makefile target, run directly):
```bash
poetry run pytest tests/unit/order/test_order.py -v
poetry run pytest tests/unit/order/test_order.py -k "test_name" -v
```

## Test File Organization

**Location — real tree (verified 2026-07-21):**
```
tests/
├── conftest.py                    # root: folder-derived TYPE marker auto-apply, global_queue fixture, DB-env guard, bar helpers
├── unit/                          # 220 test_*.py files, 2606 total tests collected repo-wide
│   ├── conftest.py                #   unit-layer documentation/marker anchor
│   ├── config/                    #   ~56 tests
│   ├── connectors/                #   ~44 tests (+ fixtures/)
│   ├── core/                      #   ~170 tests
│   ├── events/                    #   ~132 tests
│   ├── execution/                 #   ~259 tests (+ exchanges/)
│   ├── order/                     #   ~278 tests
│   ├── outils/                    #   ~28 tests
│   ├── portfolio/                 #   ~360 tests (+ positions/, reconcile/, transaction/) — has __init__.py
│   ├── price/, price_handler/     #   ~108 + 24 tests
│   ├── reporting/                 #   ~65 tests
│   ├── results/                   #   ~33 tests
│   ├── storage/                   #   ~58 tests
│   ├── strategy/                  #   ~321 tests
│   ├── trading_system/            #   ~66 tests
│   ├── universe/                  #   ~92 tests
│   └── venues/                    #   ~32 tests
├── integration/                   # 54 test_*.py files
│   ├── conftest.py                #   integration-layer fixtures: golden-file paths + backtest_engine factory
│   ├── test_backtest_oracle.py    #   the byte-exact SMA_MACD oracle test (see below)
│   ├── _oracle_harness.py         #   shared repo-root/output-dir constants + importlib loader for the oracle generator
│   ├── pair_exit_safety/, storage/
│   └── (cross-component cascade, reconciliation, OKX connectivity/store-drive tests)
├── e2e/                           # 62 test_*.py files across ~35 scenario subdirs (admission/, cash/, cost/, matching/, multi/, sltp/, sizing/, robust/, smoke/, strategies/, levered_long*/, short_*/, trailing_*/, forced_liq_*/, partial_cover/), each with its own __init__.py
├── golden/                        # 0 test_*.py files — frozen ARTIFACTS only (trades.csv, equity.csv, summary.json, pair/, + REFREEZE-*.md / CROSS-VALIDATION*.md decision notes)
└── support/                       # shared test doubles (e.g. tests/support/fake_venue_connector.py) + fixtures/
```
2606 tests collected via `pytest --collect-only -q` on 2026-07-21.

**Naming:** `test_<module>.py` mirroring `itrader/` source module names; test functions `test_*`; test classes `Test*` (all per `pyproject.toml::python_files/python_classes/python_functions`).

**`__init__.py` collision — currently NOT reproducible.** Only `tests/unit/portfolio/__init__.py` exists as a package marker outside the `tests/e2e/` tree (which uses `__init__.py` throughout its scenario subdirs by design). `tests/integration/` currently has **zero** `__init__.py` files, so there is no `tests/unit/<x>` + `tests/integration/<x>` same-name package collision today. This was a real historical gotcha (see prior project memory) but the conflicting `tests/integration/portfolio/__init__.py` is gone — do not add a new `__init__.py` to any `tests/unit/<x>` or `tests/integration/<x>` directory that shares a name with a directory on the other side, or the collision can reappear.

## Markers

**Declared marker list (`pyproject.toml::[tool.pytest.ini_options] markers`) — the SINGLE `--strict-markers` registration home:**
```toml
markers = [
    "unit: Unit test — drives ONE collaborating component (tests/unit/)",
    "integration: Integration test — asserts cross-component interaction (tests/integration/)",
    "slow: Slow running test (the full-engine integration runs)",
    "e2e: End-to-end scenario — full engine on a (strategy, data) pair vs frozen goldens (tests/e2e/)",
    "smoke: Smoke test — fast run-path liveness check; PURPOSE axis, applied by hand",
    "live: Live-venue test — makes a real network round-trip to a live venue; PURPOSE axis, applied by hand",
]
```
`tests/conftest.py` only *applies* markers at collection time; it never registers them (per its own module docstring).

**TYPE axis (folder-derived, `tests/conftest.py::pytest_collection_modifyitems`):**
- file under `tests/unit/` → `unit`
- file under `tests/integration/` → `integration` **+** `slow`
- file under `tests/e2e/` → `e2e` (deliberately NOT `slow` — e2e scenarios are tiny ~10-bar full-engine runs, so they stay in the default `make test` selection)

**PURPOSE axis (hand-applied, orthogonal to TYPE):** `smoke` (`@pytest.mark.smoke` or module-level `pytestmark`), `live` (real network round-trip to a live venue). Never folder-derived, never auto-applied.

Pytest-asyncio's own `asyncio` marker is separately registered by the plugin and is exempt from `--strict-markers`.

## Strictness Gotchas

- `filterwarnings = ["error", "ignore::UserWarning", "ignore::DeprecationWarning"]` — every OTHER unexpected warning (e.g. `RuntimeWarning`, unclosed-resource `ResourceWarning`) fails the test.
- `--strict-markers` — any `@pytest.mark.x` not in the declared list above (or the asyncio plugin's own marker) is a collection error.
- `--strict-config` — unrecognized/invalid ini options are errors, not warnings. This is why both `asyncio_mode` and `asyncio_default_fixture_loop_scope` must be set together (an unset fixture-loop-scope emits a config warning that then escalates to a hard error via `filterwarnings=["error"]`).
- `-ra` shows short summary for everything except passed; `--disable-warnings` suppresses the pytest warnings summary section in output (does not affect `filterwarnings` enforcement, which runs regardless).

## Fixtures

**Root (`tests/conftest.py`):**
- `pytest_collection_modifyitems` — folder-derived TYPE marker application (see Markers above).
- `_block_dev_database_env` (session-scoped, `autouse=True`) — pops the six `ITRADER_DATABASE_*` dev-DB env vars (`PASSWORD`, `URL`, `HOST`, `PORT`, `USER`, `NAME` — NOT `ITRADER_DATABASE_DATABASE`, the sqlite path) from `os.environ` at session start, restores in `finally`. Guarantees no test can reach the operational dev Postgres unless it explicitly opts in via function-scoped `monkeypatch.setenv` (which wins over the session-scope pop and is undone at teardown).
- `global_queue` — fresh `queue.Queue()` per test (matches the constructor convention `global_queue`).
- `make_bar_struct` / `make_bar` / `make_bar_event` — factory fixtures building a bare `Bar` (`_bar_struct`) or a one-ticker `BarEvent` with `dict[str, Bar]` payload (`_bar_event`); money fields entered via `Decimal(str(x))` per the money-boundary rule.
- `fake_venue_connector` — connected, teardown-safe `FakeLiveConnector` for the reconciliation cluster (Phase 5, D-09/RECON-06); wraps a fake `ccxt.pro` client driven by canned `watch_*`/`fetch_*` payloads from `tests/support/fixtures/okx_recon_payloads.json`. The import of `tests.support.fake_venue_connector` is deferred into the fixture body so root conftest collection never depends on `tests.support` being importable early.

**Layer-specific:**
- `tests/unit/conftest.py` — documentation/marker anchor only (no unit-only fixtures of note beyond what root provides).
- `tests/integration/conftest.py` — golden-file path fixtures + the `backtest_engine` factory used by the cross-component cascade and the oracle test.

## Mocking

- No `unittest.mock`/`pytest-mock` pattern dominates; the established convention is hand-written fake/double objects (e.g. `FakeLiveConnector` in `tests/support/fake_venue_connector.py`) driving canned JSON payloads (`tests/support/fixtures/okx_recon_payloads.json`) rather than `Mock()`/`MagicMock()` patching. Prefer hand-written fakes over `unittest.mock.patch` for connector/exchange doubles, consistent with `fake_venue_connector`.
- `ReplayDataProvider` (`itrader/price_handler/providers/replay_provider.py`) replays the golden CSV through `LiveBarFeed` for the offline, CI-safe paper-replay parity gate — used as a data double rather than a mock.

## Golden / Oracle Tests

**The byte-exact SMA_MACD oracle:** `tests/integration/test_backtest_oracle.py`, sharing repo-root/output-dir constants and an importlib loader with `tests/integration/_oracle_harness.py` (also used by `test_reservation_inertness.py` so the two copies cannot drift).

- Runs the FULL 2018→2026 `SMA_MACD` backtest by invoking `scripts/run_backtest.py::main()` in-process (writes fresh `output/{trades,equity}.csv` + `output/summary.json`), then diffs against the committed `tests/golden/` equivalents.
- Diff mechanic: loads both CSVs to pandas DataFrames, `pandas.testing.assert_frame_equal` on deterministic columns — NOT a byte-compare. Trades keyed by `(entry_date, exit_date, side)` + `pair` (behavioral identity, asserted exact); equity keyed by `timestamp`; summary keyed by `trade_count` (identity) plus `final_cash`/`final_equity`/`total_realised_pnl` (numeric, asserted EXACT — no float tolerance, per the D-16 M2b re-freeze and the later M5b re-freeze).
- Carries `integration` + `slow` markers automatically via its `tests/integration/` path (folder-derived, not hand-added).
- **Current frozen golden values** (`tests/golden/summary.json`, verified 2026-07-21):
  - `final_cash` = `final_equity` = **`46189.87730727451`**
  - `total_realised_pnl` = `36189.87730727451`
  - `trade_count` = **134**
  - `starting_cash` = `10000.0`, window `2018-01-01` → `2026-06-03`, ticker `BTCUSD` / `1d`
  - `metrics`: `cagr` 0.19910032815485068, `max_drawdown` -0.538256823181407, `profit_factor` 1.291149869385797, `sharpe` 0.6583614133806527, `sortino` 1.038504038796619, `win_rate` 0.3656716417910448
  - Also asserted: presence of `slippage_entry`/`slippage_exit` columns in `trades.csv` (D-17 auto-lock).
- This matches the CLAUDE.md-cited oracle value `46189.87730727451` — confirmed current, not stale.
- Other frozen-golden decision notes live alongside the artifacts: `tests/golden/FINAL-ORACLE.md`, `REFREEZE-M5A.md`, `REFREEZE-M5B-DIRECTION.md`, `REFREEZE-M5B-INCREASE.md`, `REFREEZE-M5C-DECIMAL.md`, `REFREEZE-06-04.md`, and the cross-validation notes `CROSS-VALIDATION.md` / `CROSS-VALIDATION-ACCOUNTING.md` / `CROSS-VALIDATION-LIMIT.md` / `CROSS-VALIDATION-SCALE-IN.md` / `CROSS-VALIDATION-TRAILING.md` (gating oracles: `backtesting.py` 0.6.5, `backtrader` 1.9.78.123; non-gating: `nautilus-trader` 1.227.0).
- `tests/golden/pair/` holds a second frozen `trades.csv`/`equity.csv` pair (pairs-trading scenario).

**E2E scenario goldens:** each `tests/e2e/<scenario>/` subdir is a small (~10-bar) full-engine run compared against a scenario-local frozen golden, tagged `e2e` (not `slow`) so they stay in the default `make test` run.

## Common Patterns

**Async testing:** `asyncio_mode = "auto"` means any `async def test_*` in `tests/unit/connectors/` (OKX stream/reconnect-supervisor tests) runs without `@pytest.mark.asyncio`.

**Env-var isolation for DB tests:** container tests that need a real DB (e.g. `test_store_live_drive` / `test_two_sided_restart`) explicitly `monkeypatch.setenv` the `ITRADER_DATABASE_*` vars, overriding the session-wide `_block_dev_database_env` pop for the duration of that test only.

## Known Operational Gotchas

- **`make test` disables logs, breaking `caplog` assertions — CONFIRMED by code, not by Makefile itself.** `itrader/logger.py` reads `ITRADER_DISABLE_LOGS` (default `"false"`) as a full-off kill-switch (D-08). `Makefile` does `include .env` + `.EXPORT_ALL_VARIABLES` (`Makefile:1-3`), so if `.env` sets `ITRADER_DISABLE_LOGS=true` it is exported into every `make test*` target's pytest process. The var is NOT set directly in `Makefile` (`grep` for `DISABLE_LOGS` in `Makefile` returns nothing) — the `.env` file contents could not be read here (forbidden-file policy) to confirm the literal value, but this exact failure mode is independently corroborated by module docstrings in `tests/unit/strategy/test_reconfigure_atomic.py`, `tests/unit/strategy/test_strategy_command_verbs.py`, `tests/unit/strategy/test_rehydrate.py`, `tests/unit/connectors/test_stream_supervisor.py`, and `tests/integration/test_store_live_drive.py:297`, all of which instruct running under `poetry run pytest` (NOT `make test`) for exactly this reason. Treat as confirmed operational behavior; run `poetry run pytest ...` directly (bypassing `make test`) for any test asserting on `caplog` warning/error records.
- **`make test` aborts in git worktrees on missing `.env`.** `Makefile:2` does `include .env` unconditionally; a worktree checkout that lacks its own `.env` file fails Make immediately. Could not independently reproduce in this pass (no worktree spun up) — carried forward from prior verified project experience; use `poetry run pytest tests` directly inside a worktree, or `PYTHONPATH="$PWD" poetry run pytest tests` when an editable-install `.venv` is shadowing worktree edits.
- **`tests/unit/<x>` + `tests/integration/<x>` `__init__.py` package collision — NOT currently reproducible.** As of 2026-07-21 only `tests/unit/portfolio/__init__.py` exists outside the `tests/e2e/` tree; `tests/integration/` has zero `__init__.py` files, so there is no live collision today. This was a real historical defect (full-suite collection breaks when both `tests/unit/<x>/__init__.py` and `tests/integration/<x>/__init__.py` exist for the same `<x>`, creating two top-level `<x>` packages) — do not reintroduce it by adding `__init__.py` to a `tests/unit/`/`tests/integration/` directory whose name is mirrored on the other side.
- **Dev-DB env leak is systemically blocked, not just documented.** `tests/conftest.py::_block_dev_database_env` (session-scoped `autouse=True`) pops all six `ITRADER_DATABASE_*` vars for the whole session, so `make test`'s `include .env` exporting real dev-Postgres credentials cannot silently leak into a `LiveTradingSystem`/`SqlSettings` construction inside a test — a test must explicitly `monkeypatch.setenv` to opt back in.

---

*Testing analysis: 2026-07-21*
