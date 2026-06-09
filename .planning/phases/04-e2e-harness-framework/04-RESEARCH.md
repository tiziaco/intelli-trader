# Phase 4: E2E Harness & Framework - Research

**Researched:** 2026-06-09
**Domain:** pytest test-infrastructure (fixtures, collection hooks, custom options) + an in-process golden-compare harness over the existing `TradingSystem`; a behavior-preserving (oracle-dark) extraction of serialization assembly into `itrader.reporting`.
**Confidence:** HIGH — every claim is grounded in the actual code read this session (no new external packages; no training-data version guesses).

## Summary

Phase 4 is **pure test-infrastructure + one oracle-dark library extraction**, built entirely on tools already in the repo (pytest 9.0.3, pandas 2.3.x, the existing `TradingSystem`). There is **no new external dependency** — so package-legitimacy, environment-availability, and security sections below are short by design. The entire risk surface is (a) keeping the BTCUSD golden run **byte-identical** while moving `build_summary`/`build_metrics_block`/`attach_slippage` out of `scripts/run_backtest.py`, and (b) building a `run_scenario` harness + `--freeze` flow that is **parallel-worktree-safe** for the Phase 6-9 waves.

The single most important design constraint discovered: **`TradingSystem.__init__` takes `exchange: str` (e.g. `"csv"`), NOT an `ExchangeConfig`.** `ExecutionHandler` hardcodes the zero-fee/no-slippage `default` preset and aliases `"csv"` → the one `SimulatedExchange` instance. D-03 ("`ScenarioSpec` reuses the real `ExchangeConfig`, fee/slippage model + params") therefore has **no clean construction seam today**. The canary (zero fee, default config) does not need one, but the planner must decide how the harness applies a scenario's `ExchangeConfig` — the available seam is `system.execution_handler.exchanges['simulated'].update_config(**kwargs)` (verified at `simulated.py:539`) called *after* construction and *before* `run()`. This is an Open Question the canary defers but Phase 6-9 will hit immediately.

**Primary recommendation:** Generalize the existing `backtest_engine` factory fixture (`tests/integration/conftest.py`) into `run_scenario` in `tests/e2e/conftest.py`; reuse `test_backtest_oracle.py`'s exact `assert_frame_equal(check_exact=True, check_like=True)` diff verbatim; extract the three assembly functions into a new `itrader/reporting/summary.py` (parameterized on TICKER/window/cash) imported by BOTH `run_backtest.py` and the harness; guard the extraction with the existing `test_backtest_oracle.py` byte-exact gate as the mandatory proof. Use a pytest `--freeze` custom option (`pytest_addoption` in the e2e conftest), not an env var.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| `tests/e2e/` tree + leaf folders (E2E-01/03) | Test suite | — | Test artifacts; belong under `tests/`, never in `itrader/`. |
| `e2e` marker registration | Build config (`pyproject.toml`) | — | `pyproject.toml` is the SINGLE marker-registration home (`--strict-markers`); conftest only *applies*. |
| Folder→marker auto-marking | Test suite (`tests/conftest.py` hook) | — | Existing `pytest_collection_modifyitems` derives TYPE from folder path; extend, don't reinvent. |
| `run_scenario` harness (E2E-02) | Test suite (`tests/e2e/conftest.py`) | Engine (read-only) | Fixture wires + runs `TradingSystem`, reads portfolio AFTER run (queue-only), diffs goldens. |
| Summary/metrics/slippage assembly (D-16) | Library (`itrader.reporting`) | Oracle generator + harness (consumers) | Shared serialization path so oracle + e2e goldens cannot drift; lives beside `frames.py`/`metrics.py`. |
| `--freeze` regen mechanism (E2E-04) | Test suite (pytest option) | — | A test-collection-time flag, not an engine concern. |
| Contrived test strategies (D-04) | Test suite (`tests/e2e/strategies/`) | — | NOT `itrader/` (SMA_MACD relocation is deferred to Phase 5). |
| Contrived CSV data (D-09/D-10/D-11) | Test suite (leaf-local + `tests/e2e/data/`) | Engine (`CsvPriceStore` real path) | Committed CSVs flow through the real store→feed path, no mock. |
| `make test-e2e` target | Build (`Makefile`) | — | `-m e2e` bucket; `make test` keeps running everything. |
| FL-03 cleanup | Test suite | — | Delete the now-dead `pytest.skip` at `tests/unit/core/test_enums.py:32`. |

## Standard Stack

This phase adds **no packages**. It uses what is already pinned and proven.

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| pytest | 9.0.3 | Fixtures, `pytest_collection_modifyitems`, `pytest_addoption` | [VERIFIED: `poetry run pytest --version` → 9.0.3]; already the suite runner. |
| pandas | 2.3.x | `read_csv`, `assert_frame_equal` exact diff | [VERIFIED: pyproject `^2.3.3`]; the existing oracle diff machinery. |
| pandas.testing | (bundled) | `assert_frame_equal(check_exact=True, check_like=True)` | [VERIFIED: used today in `test_backtest_oracle.py`]. |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `itrader.reporting.frames` | in-repo | `build_trade_log`, `build_equity_curve`, `TRADE_COLUMNS`, `EQUITY_COLUMNS` | Already shared; the extracted summary assembly joins these. [VERIFIED: read `frames.py`]. |
| `itrader.reporting.metrics` | in-repo | `sharpe`/`sortino`/`cagr`/`max_drawdown`/`profit_factor`/`win_rate`/`compute_returns` | The metrics-block formula source. [VERIFIED: read `metrics.py`]. |
| `itrader.trading_system.backtest_trading_system.TradingSystem` | in-repo | The full engine the harness runs | [VERIFIED: read constructor; takes `exchange`, `start_date`, `end_date`, `timeframe`, `csv_paths`]. |
| `itrader.price_handler.store.csv_store.CsvPriceStore` | in-repo | Real data path via `csv_paths` passthrough | [VERIFIED: `csv_paths` default `None` → golden default; accepts `dict[ticker, path]`]. |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Per-folder one-line test + shared fixture (D-01, LOCKED) | Auto-discovery parametrized collector | Collector is a SHARED file every Phase 6-9 wave would edit → merge conflicts. D-01 forbids it. |
| pytest `--freeze` option (recommended) | `ITRADER_FREEZE` env var | Env var leaks across processes/worktrees and is invisible in `pytest --collect-only`; an option is explicit and parallel-safe. Both work; option is cleaner. |
| Per-scenario manual diff config | Diff-what's-frozen (D-05, LOCKED) | Manual config is per-scenario boilerplate; presence-of-golden-file = assertion is zero-config. |

**Installation:** None. (No `npm`/`pip` install — every dependency is already in `poetry.lock`.)

## Package Legitimacy Audit

> **Not applicable.** Phase 4 installs ZERO external packages. All code reuses already-pinned, already-audited dependencies (pytest 9.0.3, pandas 2.3.x) present in `poetry.lock`. slopcheck not run because there is nothing to check. If the planner adds a package (it should not need to), gate it behind a `checkpoint:human-verify` task.

## Architecture Patterns

### System Architecture Diagram

```
                         pytest collection
                                │
          pytest_collection_modifyitems (tests/conftest.py)
                                │  folder "e2e" in path → add_marker(e2e)
                                ▼
   tests/e2e/<subsystem>/<scenario>/test_*.py   (D-01: one-liner)
            def test_x(run_scenario): run_scenario(HERE)
                                │
                                ▼
   run_scenario fixture (tests/e2e/conftest.py)
     1. import HERE/scenario.py  → ScenarioSpec (D-02/D-03)
     2. build TradingSystem(exchange="csv", start, end, timeframe,
                            csv_paths=spec.data)               ─┐
        add_strategy(spec.strategies), add_portfolio(spec.pf),  │ real engine
        subscribe; (apply spec.exchange via update_config?  ── OPEN Q1)
     3. system.run(print_summary=False)                        ─┘
     4. read portfolio AFTER run (queue-only):                 ─┐
        build_trade_log / build_equity_curve                    │ shared
        + itrader.reporting.summary.build_summary/              │ reporting
          build_metrics_block/attach_slippage   ◄── D-16 extract ┘
     5. if --freeze: WRITE golden/ files
        else:        DIFF only files present in HERE/golden/    (D-05)
                     assert_frame_equal(check_exact=True, ...)  (D-08)
                                │
                                ▼
                   PASS (no drift) / FAIL (drift) / FROZEN
```

### Recommended Project Structure
```
tests/e2e/
├── conftest.py              # run_scenario fixture + pytest_addoption("--freeze")
├── strategies/              # D-04 shared purpose-built deterministic strategies
│   ├── __init__.py
│   └── single_market_buy.py # contrived: emit exactly one BUY on a known bar
├── data/                    # D-10 shared reusable inputs (BTCUSD slice, real-dataset refs)
│   └── ...
└── smoke/                   # D-14 subsystem group (canary lives under a stable domain dir)
    └── single_market_buy/   # the ONE canary leaf (D-12)
        ├── __init__.py      # (optional; needed only if importing scenario.py as a package)
        ├── scenario.py      # ScenarioSpec + VERIFY hand-derivation docstring (D-02/D-13)
        ├── test_scenario.py # def test_x(run_scenario): run_scenario(HERE)
        ├── bars.csv         # contrived tiny CSV (D-09/D-11) OR ref tests/e2e/data/
        └── golden/          # frozen trades.csv + summary.json (D-06 default freeze)
```
(Exact dir names/depth are Claude's discretion per D-14 — subsystem-grouped, stable names.)

### Pattern 1: `run_scenario` as the generalized `backtest_engine` factory (D-01)
**What:** The existing `backtest_engine` fixture returns a callable that builds a `TradingSystem`. `run_scenario` is its descendant: a fixture returning a callable `run_scenario(here: Path)` that imports the leaf's `scenario.py`, wires the engine from the `ScenarioSpec`, runs it, and diffs `here/golden/`.
**When to use:** Every e2e leaf test calls it with `HERE` (the leaf folder path).
**Example (synthesized from the verified `backtest_engine` fixture + `run_backtest.py` wiring):**
```python
# tests/e2e/conftest.py  (4-space indent — new module, matches config/ convention)
# Source: generalized from tests/integration/conftest.py::backtest_engine
#         + scripts/run_backtest.py::main (wiring) [VERIFIED: read both]
import importlib.util, json, pathlib
import pandas as pd
import pandas.testing as pdt
import pytest

def pytest_addoption(parser):
    parser.addoption("--freeze", action="store_true", default=False,
                     help="WRITE e2e golden fixtures instead of diffing them (E2E-04).")

@pytest.fixture
def run_scenario(request):
    def _run(here: pathlib.Path):
        spec = _load_spec(here / "scenario.py")            # ScenarioSpec (D-02)
        # Deferred import keeps --collect-only safe (backtest_engine pattern).
        from itrader.trading_system.backtest_trading_system import TradingSystem
        system = TradingSystem(exchange="csv", start_date=spec.start, end_date=spec.end,
                               timeframe=spec.timeframe, csv_paths=spec.data)  # D-09
        # OPEN Q1: apply spec.exchange (fee/slippage) here via
        # system.execution_handler.exchanges['simulated'].update_config(...)
        for strat in spec.strategies:                       # D-03 list[strategy]
            system.strategies_handler.add_strategy(strat)
        for pf in spec.portfolios:                          # D-03 list[PortfolioConfig]
            pid = system.portfolio_handler.add_portfolio(
                user_id=pf.user_id, name=pf.name, exchange="csv", cash=pf.cash)
            for strat in spec.strategies:
                strat.subscribe_portfolio(pid)
        system.run(print_summary=False)                     # queue-only; read AFTER
        portfolio = system.portfolio_handler.get_portfolio(pid)
        _diff_or_freeze(here, system, portfolio, freeze=request.config.getoption("--freeze"))
    return _run
```

### Pattern 2: Diff-what's-frozen, reusing the oracle diff verbatim (D-05/D-08)
**What:** Build all artifacts in memory; for each file present in `here/golden/`, load + `assert_frame_equal(check_exact=True, check_like=True)` (frames) or exact dict/key compare (summary.json). Presence of the golden file = the assertion.
**Example (the exact mechanic copied from `test_backtest_oracle.py` [VERIFIED]):**
```python
# Identity/numeric split is auto-derived from the golden header, same as the oracle:
_TRADE_IDENTITY = ["entry_date", "exit_date", "side", "pair"]
fresh = fresh_trades.sort_values(["entry_date","exit_date","side"]).reset_index(drop=True)
gold  = golden_trades.sort_values(["entry_date","exit_date","side"]).reset_index(drop=True)
pdt.assert_frame_equal(fresh[_TRADE_IDENTITY], gold[_TRADE_IDENTITY],
                       check_exact=True, check_like=True)
numeric = [c for c in gold.columns if c not in _TRADE_IDENTITY]
pdt.assert_frame_equal(fresh[numeric], gold[numeric], check_exact=True, check_like=True)
# summary.json: exact dict compare on the whole "metrics" block + key-by-key on scalars.
```

### Pattern 3: D-16 oracle-dark extraction (the high-risk move)
**What:** Move `build_summary`, `build_metrics_block`, `attach_slippage` (and the `FLOAT_FORMAT`/`SLIPPAGE_COLUMNS` pins) from `scripts/run_backtest.py` into a new `itrader/reporting/summary.py`, **parameterizing** the currently-pinned module constants (`TICKER`, `TIMEFRAME`, `START_DATE`, `END_DATE`, `CASH`) into function arguments. `run_backtest.py` then imports them and passes its pinned constants verbatim; the harness imports them and passes the scenario's spec values.
**Why it's safe:** The function *bodies* stay character-identical (same as the `frames.py` relocation precedent — see `frames.py` docstring: "function bodies are character-identical to the run_backtest.py originals"). Only the closed-over module constants become parameters.
**Mandatory proof gate:** `tests/integration/test_backtest_oracle.py` must re-run GREEN after the extraction. It asserts (verified, lines 137-238):
  - trade count identity + `(entry_date, exit_date, side, pair)` EXACT (`check_exact=True`),
  - equity point count + `timestamp` grid EXACT, plus all numeric equity columns EXACT,
  - all numeric trade columns (incl. `slippage_entry`/`slippage_exit`) EXACT,
  - summary scalars `final_cash`/`final_equity`/`total_realised_pnl`/`trade_count` EXACT,
  - the whole `summary["metrics"]` dict EXACT.
If any byte changes, that test fails — it is the oracle-dark guard. **Plan a task that runs `make backtest` + the oracle test as the extraction's acceptance, BEFORE writing any harness code that depends on the new module.**

**Signatures today (verified, `scripts/run_backtest.py`):**
```python
attach_slippage(trades, closes) -> trades            # closes = store.read_bars(TICKER)["close"]
build_metrics_block(equity, trades) -> dict          # pure; reads equity["total_equity"]
build_summary(portfolio, trades) -> dict             # closes over TICKER/TIMEFRAME/START/END/CASH
FLOAT_FORMAT = "%.10f"; SLIPPAGE_COLUMNS = ["slippage_entry","slippage_exit"]
```
`build_summary` is the ONLY one closing over module constants — those five become parameters: `build_summary(portfolio, trades, *, ticker, timeframe, start_date, end_date, starting_cash) -> dict`.

### Pattern 4: Contrived deterministic test strategy (D-04, canary)
**What:** SMA_MACD's 50/100 crossover needs ~100 bars and is not controllable. A canary needs a tiny strategy that emits exactly one BUY on a known bar. The `Strategy` ABC (`base.py`) requires only `generate_signal(ticker, bars) -> SignalIntent | None` plus a declared `sizing_policy`. A controllable strategy emits `self.buy(ticker)` when `len(bars) == N` (a pinned bar count), else `None`.
**Example (synthesized from the verified `Strategy` base + `SMA_MACD_strategy`):**
```python
# tests/e2e/strategies/single_market_buy.py
from decimal import Decimal
from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.strategy_handler.base import Strategy

class SingleMarketBuy(Strategy):
    def __init__(self, timeframe, tickers, *, fire_on_bar=2):
        super().__init__("single_market_buy", timeframe, list(tickers),
                         sizing_policy=FractionOfCash(Decimal("0.95")),
                         direction=TradingDirection.LONG_ONLY, allow_increase=False)
        self.fire_on_bar = fire_on_bar
        self.max_window = 0           # no warmup needed
    def generate_signal(self, ticker, bars):
        return self.buy(ticker) if len(bars) == self.fire_on_bar else None
```
This produces exactly ONE MARKET entry, which fills next-bar-open (verified convention in `simulated.py`/`attach_slippage` docstring), yielding a hand-derivable trade. Pair it with a tiny contrived CSV (e.g. 5-6 daily bars with hand-chosen opens) so the fill price and PnL are computable by hand for the VERIFY note.

### Anti-Patterns to Avoid
- **A shared collector/registry that every scenario edits.** Breaks D-01 parallel-safety; Phase 6-9 worktrees would merge-conflict. Each leaf owns its own `test_*.py`, `scenario.py`, `golden/`.
- **Writing fresh artifacts into the committed leaf folder.** D-07: results stay in memory; use `tmp_path` only for debug disk dumps, NEVER write into `golden/` except under `--freeze`.
- **Float tolerance in the diff (`rtol`/`atol`).** D-08: exact only; tolerance masks real regressions (the oracle abandoned its transitional tolerance precisely for this reason — verified in `test_backtest_oracle.py` lines 53-65).
- **Changing function bodies during the D-16 extraction.** Any non-identical body risks oracle drift. Move verbatim; parameterize only the module constants.
- **Slicing real BTCUSD for fill-shape scenarios.** D-11: real slices can't produce limit-touch/gap-through/OCO shapes on demand; use contrived bars (this is a Phase 6-9 concern, but the canary establishes the contrived-CSV template).
- **Re-registering markers in conftest.** `pyproject.toml` is the SINGLE registration home under `--strict-markers`; conftest only `add_marker` at collection time (verified in `tests/conftest.py` docstring).

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Exact frame diff with column-level failures | Custom byte-compare or row loop | `pandas.testing.assert_frame_equal(check_exact=True, check_like=True)` | Already the oracle's mechanic; gives clear per-column failure messages; `check_like=True` is order-insensitive on columns. |
| Folder→marker mapping | New marker plugin / decorator on each test | Extend the existing `pytest_collection_modifyitems` in `tests/conftest.py` | The hook already derives `unit`/`integration`/`slow` from path parts; add one `if "e2e" in parts` branch. |
| Custom run flag plumbing | `os.environ["ITRADER_FREEZE"]` parsing | `pytest_addoption` + `request.config.getoption("--freeze")` | First-class, visible in `--help`, scoped to the pytest invocation, parallel-safe. |
| Engine construction for a scenario | Re-implementing wiring in each test | The `TradingSystem` constructor + `add_strategy`/`add_portfolio`/`subscribe_portfolio` | The exact wiring `run_backtest.py` uses; queue-only reads after `run()`. |
| Summary/metrics serialization | Re-deriving the metrics dict in the harness | The extracted `itrader.reporting.summary` (D-16) | One assembly path → oracle and e2e goldens cannot diverge in format. |
| Hand-derivation provenance | Trusting a frozen number blindly | A committed VERIFY note (D-13), mirroring `tests/golden/REFREEZE-*.md` | The human-verification artifact a reviewer checks; goldens never auto-heal. |

**Key insight:** Everything this phase needs already exists in the repo in a near-identical form. The work is *generalization and relocation*, not invention — which is exactly why the oracle-dark gate is the dominant risk, not novel code.

## Runtime State Inventory

> Rename/refactor-adjacent (the D-16 extraction relocates symbols). Categories checked:

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — no datastore stores the symbol names `build_summary`/`build_metrics_block`/`attach_slippage`. They are Python locals in `scripts/run_backtest.py`. | None. |
| Live service config | None — no external service references these symbols. | None. |
| OS-registered state | None — no scheduler/daemon references these. | None. |
| Secrets/env vars | None — none of these symbols are env-var keyed. The recommended `--freeze` is a pytest option, NOT an env var, so no new env var is introduced. | None. |
| Build artifacts | The committed goldens at `tests/golden/{trades,equity}.csv` + `summary.json` are the artifacts the oracle-dark gate diffs against. The extraction must NOT change their bytes. `output/` is gitignored and regenerated by `make backtest`. | Re-run `make backtest` + `test_backtest_oracle.py` to prove byte-identity AFTER the extraction. |

**Import-graph note:** `scripts/run_backtest.py` is imported in-process by `test_backtest_oracle.py` via `_load_run_backtest_module` (`spec_from_file_location`, verified lines 71-82). After D-16 the oracle test still imports `run_backtest.py::main`, which now imports from `itrader.reporting.summary` — verify the in-process import still resolves (it will; `itrader` is on the package path). The harness imports the SAME `itrader.reporting.summary`, never `scripts/run_backtest.py`.

## Common Pitfalls

### Pitfall 1: The D-16 extraction silently re-formats the golden
**What goes wrong:** Moving `build_summary` and changing `json.dump(..., indent=2, sort_keys=True)` ordering, or altering `FLOAT_FORMAT`, or letting a parameterized default differ from the pinned constant → `summary.json`/`trades.csv` bytes change.
**Why it happens:** Parameterization tempts small "cleanups"; `sort_keys`/`indent`/`float_format` are byte-load-bearing.
**How to avoid:** Move bodies verbatim. Keep `FLOAT_FORMAT="%.10f"`, `json.dump(indent=2, sort_keys=True)`, and the `TRADE_COLUMNS + SLIPPAGE_COLUMNS` serialization order in `run_backtest.py` unchanged. The serialization (`to_csv`/`json.dump`) can stay in `run_backtest.py`; only the *assembly* functions move.
**Warning signs:** `test_backtest_oracle.py` goes red on any numeric/metrics/scalar assertion.

### Pitfall 2: `filterwarnings=["error"]` makes scenarios brittle
**What goes wrong:** A pandas FutureWarning (e.g. `equity[-1]` positional, empty-slice RuntimeWarning) in a scenario aborts the test as an error.
**Why it happens:** The suite sets `filterwarnings=["error", ...]` (verified pyproject lines 71-75). `metrics.py` already documents this regime and uses pandas-2-safe idioms (`.iloc`, guarded denominators). New harness/strategy code must match.
**How to avoid:** Reuse the already-warning-clean `frames.py`/`metrics.py` builders; use `.iloc`, whole-column construction, guarded empty-frame paths. Note: `addopts` includes `--disable-warnings` (suppresses the *summary report*) AND `filterwarnings=["error"]` (escalates to errors) — the escalation still fires; `--disable-warnings` only hides the end-of-run warnings recap, it does NOT downgrade errors. [VERIFIED: pyproject lines 50-75.]
**Warning signs:** A scenario fails with `... was raised` wrapping a pandas/numpy warning.

### Pitfall 3: `ScenarioSpec` can't apply fee/slippage through construction (OPEN — see Open Questions)
**What goes wrong:** D-03 says reuse `ExchangeConfig`, but `TradingSystem(exchange="csv")` ignores fee/slippage config — it builds the zero-fee default and aliases `"csv"`→`simulated` (verified `execution_handler.py:95-117`).
**Why it happens:** The engine wiring predates the e2e need; the only seam is `SimulatedExchange.update_config(**kwargs)` (verified `simulated.py:539`) or passing a `config` to `SimulatedExchange.__init__` (verified `simulated.py:38`), neither reachable from the `TradingSystem` constructor.
**How to avoid (Phase 4):** The canary uses default (zero fee/no slippage), so it does not exercise this. **The planner must record this as a known seam gap** — the harness should call `system.execution_handler.exchanges['simulated'].update_config(...)` from the scenario's `ExchangeConfig` AFTER construction and BEFORE `run()`. Validate that `update_config`'s key set (`fee_model_type`/`fee_rate`/`maker_rate`/`taker_rate`/`slippage_model_type`/`base_slippage_pct`/`slippage_pct`) covers Phase 7's COST requirements; it appears to, but Phase 7 will confirm.
**Warning signs:** A Phase 7 cost scenario silently runs zero-fee because the spec's `ExchangeConfig` was never applied.

### Pitfall 4: Importing the leaf `scenario.py` (collection vs runtime)
**What goes wrong:** `run_scenario(HERE)` must import `HERE/scenario.py`. If done with a bare module name it can collide; if the leaf isn't a package, relative imports fail.
**How to avoid:** Use `importlib.util.spec_from_file_location` with a unique module name per leaf (the exact pattern `test_backtest_oracle.py::_load_run_backtest_module` uses, verified). Defer the engine import inside the fixture body so `--collect-only` stays clean (the `backtest_engine` deferred-import precedent).
**Warning signs:** `--collect-only` errors, or two scenarios' `scenario.py` shadow each other.

### Pitfall 5: `--freeze` overwriting goldens in a parallel wave
**What goes wrong:** Running `pytest --freeze` across many scenarios at once writes all goldens unverified, defeating hand-verify-once (E2E-04).
**Why it happens:** `--freeze` is global to the invocation.
**How to avoid:** Freeze deliberately, per-scenario (`pytest tests/e2e/<sub>/<scenario> --freeze`), and commit the VERIFY note in the SAME change. The ROADMAP Phase 6 REMINDER explicitly says "hand-verify/freeze oracles in deliberate batches, not 12-at-once." Document this in the harness docstring + the canary template.
**Warning signs:** A golden changes with no matching VERIFY note in the diff.

## Code Examples

### Extending the folder-derived marker hook (E2E-01)
```python
# tests/conftest.py — add the e2e branch (4-space; this file uses 4 spaces) [VERIFIED]
def pytest_collection_modifyitems(config, items):
    for item in items:
        parts = pathlib.Path(str(item.fspath)).parts
        if "unit" in parts:
            item.add_marker(pytest.mark.unit)
        if "integration" in parts:
            item.add_marker(pytest.mark.integration)
            item.add_marker(pytest.mark.slow)
        if "e2e" in parts:                       # NEW
            item.add_marker(pytest.mark.e2e)     # NOT slow (D-15): tiny ~10-bar runs
```

### Registering the marker (E2E-01) — `pyproject.toml`
```toml
# Source: pyproject.toml lines 61-65 [VERIFIED] — add ONE line, the single registration home.
markers = [
    "unit: Unit test — drives ONE collaborating component (tests/unit/)",
    "integration: Integration test — asserts cross-component interaction (tests/integration/)",
    "slow: Slow running test (the full-engine integration runs)",
    "e2e: End-to-end scenario — full engine on a (strategy, data) pair vs frozen goldens (tests/e2e/)",
]
```

### `make test-e2e` (E2E-01) — `Makefile`
```makefile
# Source: Makefile pattern from test-unit/test-integration [VERIFIED]. make test (line 27-29)
# already runs `pytest tests/ -v` with no -m filter, so e2e is INCLUDED by default (D-15).
test-e2e:
	@echo "🌐 Running E2E scenario tests..."
	poetry run pytest tests/ -v -m "e2e"
```
Also add `test-e2e` to the `.PHONY` line (currently line 6).

### FL-03 cleanup — `tests/unit/core/test_enums.py`
`FillStatus` now exists with `EXECUTED` (verified `itrader/core/enums/execution.py:59`), so the `pytest.skip(...)` at line 32 is dead. Delete the `if fill_status is None: pytest.skip(...)` branch in `_fill_status_or_skip` so the now-passing assertions run. The 4-gate CLEANUP-STANDARD checklist applies (touched-path, behavior-preserving, no oracle re-baseline, reviewed).

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Assembly functions as `run_backtest.py` locals | Extracted to shared `itrader.reporting` (D-16) | This phase | Oracle + e2e share one serialization path. |
| `frames.py` already extracted verbatim | Same pattern reused for summary assembly | M5-07 (done) | Precedent proves verbatim relocation stays oracle-dark. |
| pytest 8.x | pytest 9.0.3 | repo upgrade (commit 0fa3d7f) | `pytest_addoption`/`pytest_collection_modifyitems` APIs unchanged; no migration needed. [VERIFIED: pytest 9.0.3 running.] |

**Deprecated/outdated:** Nothing new is deprecated for this phase. Avoid the legacy `statistics.py`/`performance.py` metric code (dead per `metrics.py` docstring) — always use `itrader.reporting.metrics`.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `SimulatedExchange.update_config(**kwargs)` keys fully cover Phase 7 COST scenarios (percent/maker_taker fees, fixed/linear slippage) | Pitfall 3 / Open Q1 | A Phase 7 cost scenario can't be expressed; needs a config-threading task. LOW for Phase 4 (canary uses defaults). |
| A2 | A contrived `len(bars) == N` strategy reliably fires exactly one BUY through the real feed→signal→order→fill path | Pattern 4 | Canary produces 0 or >1 trades; the VERIFY note can't be hand-derived. MITIGATE by asserting trade count in the canary's first freeze. |
| A3 | Moving only assembly functions (not `to_csv`/`json.dump` serialization) keeps the oracle byte-identical | Pattern 3 / Pitfall 1 | Oracle drift. MITIGATE: `test_backtest_oracle.py` is the gate — it will catch any drift. |
| A4 | `make test` (`pytest tests/ -v`, no `-m`) includes e2e automatically | make targets | If a default `-m` filter were added elsewhere, e2e could be excluded. Verified no `-m` in `make test` today. |

## Open Questions

1. **How does the harness apply a scenario's `ExchangeConfig` (D-03 fee/slippage)?**
   - What we know: `TradingSystem(exchange="csv")` ignores fee/slippage; the only seam is `system.execution_handler.exchanges['simulated'].update_config(**kwargs)` (verified) or `SimulatedExchange(config=...)` at construction (not reachable from `TradingSystem.__init__`).
   - What's unclear: Whether the planner threads an `ExchangeConfig` param through `TradingSystem.__init__` (a new oracle-dark seam, default `None` = today's behavior) OR has the harness call `update_config` post-construction.
   - Recommendation: For Phase 4, the canary uses defaults — defer the decision but RECORD it. Recommend the harness call `update_config(...)` from `spec.exchange` (no engine change, parallel-safe). If Phase 7 needs richer config, add an oracle-dark `exchange_config: ExchangeConfig | None = None` constructor param then (its own phase).

2. **VERIFY artifact: `VERIFY.md` file vs `scenario.py` docstring?** (Claude's discretion, D-13.)
   - Recommendation: A docstring in `scenario.py` keeps the hand-derivation co-located with the spec and travels with the leaf in one file (best for the copy-template); a `VERIFY.md` is more reviewer-visible. Either satisfies D-13. Slight lean to the `scenario.py` docstring for the canary template (fewer files), with the option to graduate to `VERIFY.md` for complex Phase 6+ scenarios.

3. **Contrived CSV authoring: hand-written vs an emit-helper?** (Claude's discretion, D-09.)
   - Recommendation: For ONE canary, hand-write a tiny committed CSV in the golden Binance-kline schema (`Open time, Open, High, Low, Close, Volume` — verified required header in `csv_store.py:155`). A small committed emit-helper pays off only once Phase 6 needs many contrived shapes; defer it.

## Environment Availability

> Skipped — Phase 4 is code/test-only. The only "tools" are pytest 9.0.3 and pandas 2.3.x, both already installed via Poetry (`poetry.lock` committed). No external service, runtime, or CLI beyond the existing `.venv` is required. `make backtest` (for the oracle-dark proof) needs only the committed `data/BTCUSD_1d_ohlcv_2018_2026.csv`, which is present.

## Validation Architecture

> nyquist_validation: enabled (no `workflow.nyquist_validation: false` found in config). This phase IS test infrastructure, so the meta-question is: **how do we know the harness correctly CATCHES drift and correctly PASSES the oracle-dark refactor?**

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.3 (+ pytest-cov 7.1.0) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `poetry run pytest tests/e2e -x -q` |
| Full suite command | `make test` (`poetry run pytest tests/ -v`) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| E2E-01 | `tests/e2e/` tree + `e2e` marker registered + auto-marked + `make test-e2e` | integration (meta) | `poetry run pytest tests/ -m e2e --collect-only -q` (proves marker applies) | ❌ Wave 0 |
| E2E-01 | `make test-e2e` selects only e2e | smoke | `make test-e2e` | ❌ Wave 0 |
| E2E-02 | `run_scenario` runs full engine + diffs trades/equity/summary | e2e (the canary) | `poetry run pytest tests/e2e/smoke/single_market_buy -x` | ❌ Wave 0 |
| E2E-03 | Self-contained leaf, warning-clean under `filterwarnings=["error"]` | e2e | `poetry run pytest tests/e2e/smoke/single_market_buy -x` (errors-as-warnings already on) | ❌ Wave 0 |
| E2E-04 | `--freeze` writes goldens; diff-only otherwise; VERIFY note committed | e2e + review | `poetry run pytest tests/e2e/smoke/single_market_buy --freeze` then re-run without `--freeze` passes | ❌ Wave 0 |
| D-16 | Reporting extraction is oracle-dark (byte-identical) | integration (gate) | `make backtest && poetry run pytest tests/integration/test_backtest_oracle.py -x` | ✅ exists (`test_backtest_oracle.py`) |
| FL-03 | Dead skip removed; the two `FillStatus` tests run + pass | unit | `poetry run pytest tests/unit/core/test_enums.py -x` | ✅ exists |

### Harness self-trust (the meta-validation — what makes test infra trustworthy)
1. **It catches drift:** Add a deliberate negative check — a task that mutates ONE golden cell (or the canary strategy's fire-bar) and asserts the canary test now FAILS, then reverts. Proves the diff is not a no-op. (Reviewer step; can be a documented manual VERIFY step rather than a committed test that intentionally fails.)
2. **It passes the oracle-dark refactor:** `test_backtest_oracle.py` GREEN after D-16 is the byte-exact proof that the extraction changed nothing. This is the dominant gate.
3. **`--freeze` is reversible & honest:** After `--freeze` writes a golden, the immediate diff-only re-run MUST pass (idempotence) — a one-command check in the canary acceptance.
4. **Determinism:** A double `run_scenario` of the canary yields byte-identical artifacts (the seeded RNG + injected clock guarantee; ROBUST-04 generalizes this for Phase 9).

### Sampling Rate
- **Per task commit:** `poetry run pytest tests/e2e -x -q` (canary + harness) + `poetry run pytest tests/unit/core/test_enums.py -x` (FL-03).
- **Per wave merge:** `make backtest && poetry run pytest tests/integration/test_backtest_oracle.py` (the oracle-dark gate) + `make test`.
- **Phase gate:** Full `make test` green (incl. e2e + oracle) before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `tests/e2e/conftest.py` — `run_scenario` fixture + `pytest_addoption("--freeze")` — covers E2E-02/E2E-04
- [ ] `tests/e2e/strategies/single_market_buy.py` — contrived deterministic strategy — covers E2E-03 (D-04)
- [ ] `tests/e2e/smoke/single_market_buy/{scenario.py,test_scenario.py,bars.csv,golden/}` — the canary leaf — covers E2E-02/03/04 (D-12)
- [ ] `itrader/reporting/summary.py` — extracted `build_summary`/`build_metrics_block`/`attach_slippage` — covers D-16
- [ ] `tests/conftest.py` — add the `e2e` marker branch — covers E2E-01
- [ ] `pyproject.toml` + `Makefile` — register `e2e` marker + `make test-e2e` — covers E2E-01
- [ ] No new framework install needed (pytest already present).

## Security Domain

> `security_enforcement` not set to a security-relevant context — this phase is internal test infrastructure with no auth, network, untrusted input, secrets, or cryptography surface. The only inputs are committed CSVs authored by the developer, parsed by the already-validating `CsvPriceStore` (malformed-header / empty-slice raises, verified `csv_store.py:154-188`). No ASVS category applies. Money handling stays Decimal end-to-end per CLAUDE.md (the extraction does `float()` only at the serialization edge, unchanged).

## Project Constraints (from CLAUDE.md)

- **Money is Decimal end-to-end**; `float()` only at the serialization/logging edge — the D-16 extraction must preserve the existing `float(portfolio.cash)`/`float(portfolio.total_equity)` boundary verbatim (it lives in `build_summary`).
- **Indentation per file:** `tests/conftest.py` and `itrader/config/`,`itrader/core/`,`price_handler/feed/`,events package use **4 spaces**; handler modules use **tabs**. New files: `tests/e2e/conftest.py` and `itrader/reporting/summary.py` → **4 spaces** (matches `tests/conftest.py` and `itrader/reporting/frames.py`). `scripts/run_backtest.py` uses 4 spaces. Match each file you edit.
- **Queue-only cross-domain contract:** the harness reads portfolio state ONLY AFTER `system.run()` returns (like `run_backtest.py`); it never calls handler methods mid-run. Injected read-models (feed, store) are the only mid-run read seam — not used by the harness.
- **Determinism:** seeded RNG (`performance.rng_seed`, default 42) + injected `BacktestClock` — already wired; scenarios inherit reproducibility, no per-call seeding.
- **Test strictness:** every new marker registered in `pyproject.toml` (`--strict-markers`); every scenario WARNING-CLEAN under `filterwarnings=["error"]` (`--strict-config`).
- **GSD workflow enforcement:** all edits go through a GSD command (this phase is `/gsd:execute-phase`).
- **No autoformatter/linter** beyond `mypy --strict` on `itrader/` — the new `itrader/reporting/summary.py` MUST be strict-clean (it's in-scope; `tests/` is not mypy-gated). Tests dir is not in `files = ["itrader"]`, so the harness fixture is not mypy-checked, but keep types honest.

## Sources

### Primary (HIGH confidence — read this session)
- `tests/integration/conftest.py` — `backtest_engine` factory + `golden_*` path fixtures.
- `tests/integration/test_backtest_oracle.py` — exact-diff machinery (`assert_frame_equal check_exact=True, check_like=True`), `_load_run_backtest_module`, identity/numeric column split, summary metrics dict compare.
- `scripts/run_backtest.py` — `build_summary`/`build_metrics_block`/`attach_slippage`, `FLOAT_FORMAT`, `SLIPPAGE_COLUMNS`, `TRADE_COLUMNS` usage, wiring + queue-only read.
- `tests/conftest.py` — `pytest_collection_modifyitems` folder-derived marker hook.
- `pyproject.toml` — `[tool.pytest.ini_options]` markers, `filterwarnings`, `addopts`, pytest 9.0.3 dev dep.
- `Makefile` — `test`/`test-unit`/`test-integration` targets; `make test` runs all (no `-m`).
- `itrader/reporting/frames.py`, `itrader/reporting/metrics.py` — shared builders + metric formulas.
- `itrader/trading_system/backtest_trading_system.py` — `TradingSystem.__init__` (`csv_paths` passthrough), `run`, `_initialise_backtest_session`.
- `itrader/price_handler/store/csv_store.py` — `csv_paths` seam, required CSV header, date-window slice.
- `itrader/config/exchange.py`, `itrader/config/portfolio.py` — `ExchangeConfig`/`PortfolioConfig` real models (D-03).
- `itrader/execution_handler/execution_handler.py` — `init_exchanges` ("csv"→simulated alias), no `ExchangeConfig` thread-through.
- `itrader/execution_handler/exchanges/simulated.py` — `__init__(config=...)`, `update_config(**kwargs)` seam.
- `itrader/strategy_handler/base.py`, `SMA_MACD_strategy.py` — `Strategy` ABC contract for the contrived strategy.
- `itrader/core/enums/execution.py` — `FillStatus.EXECUTED` exists → FL-03 skip is dead.
- `.planning/REQUIREMENTS.md` (E2E-01..04), `.planning/ROADMAP.md` (Phase 4 criteria + Phase 6 parallel REMINDER), `.planning/phases/04-e2e-harness-framework/04-CONTEXT.md` (D-01..D-16).
- `poetry run pytest --version` → 9.0.3 (tool-verified this session).

### Secondary / Tertiary
- None — no WebSearch needed; the phase is fully grounded in the local codebase.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — no new packages; versions tool-verified.
- Architecture (run_scenario, diff, extraction): HIGH — every pattern is a generalization of code read this session; the oracle gate already exists.
- Pitfalls: HIGH — Pitfall 3 (no `ExchangeConfig` construction seam) and Pitfall 1 (extraction byte-drift) are grounded in exact line reads.
- The single MEDIUM area is A1/A2 (whether `update_config` covers all Phase 7 costs, and whether the contrived strategy fires exactly once) — both are Phase-4-deferred (canary uses defaults) and mitigated by the canary's first-freeze trade-count assertion.

**Research date:** 2026-06-09
**Valid until:** ~2026-07-09 (stable; internal-codebase-grounded, no fast-moving external deps).
