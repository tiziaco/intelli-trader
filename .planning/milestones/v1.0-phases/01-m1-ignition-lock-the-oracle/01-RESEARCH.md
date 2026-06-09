# Phase 1: M1 — Ignition + Lock the Oracle - Research

**Researched:** 2026-06-04
**Domain:** Brownfield structural refactor — Python 3.13 event-driven backtest engine ignition + golden-master oracle capture + pytest skeleton
**Confidence:** HIGH (every CONTEXT.md claim verified against running code in this session)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Dataset = `data/BTCUSD_1d_ohlcv_2018_2026.csv` (Binance-klines: comma-delimited, ascending/oldest-first, 3076 daily bars, header `Open time, Open, High, Low, Close, Volume, Close time, Quote asset volume, Number of trades, Taker buy base asset volume, Taker buy quote asset volume, Ignore`, timestamps like `2018-01-01 00:00:00.000000 UTC`). SUPERSEDES the `…01_01_2021-04_06_2026.csv` filename in PROJECT/REQUIREMENTS/ROADMAP/CLAUDE.md — flag those for update as a COVERAGE-INDEX §E delta.
- **D-02:** Date window = full range 2018-01-01 → 2026-06-03, pinned explicitly in the run script (not "whole file"). ~100 warmup bars (`max_window=100`) then ~2976 tradeable bars.
- **D-03:** SMA_MACD parameters = code defaults: `short_window=50, long_window=100, FAST=6, SLOW=12, WIN=3`.
- **D-04:** Starting cash = $10,000; fees = 0; slippage = 0. Cleanest oracle; M5 owns fee/slippage correctness.
- **D-05:** Run invocation = committed Python run script + new `make backtest` target. NOT the notebook.
- **D-06:** Ticker = `BTCUSD` (Claude's discretion to adjust if universe/price-handler wiring requires a specific symbol).
- **D-07:** Minimal `csv`/offline branch INSIDE `PriceHandler` (option 1, not standalone provider). Reads local CSV into `self.prices`, skips `SqlHandler`/`CCXT` construction entirely.
- **D-08:** Sizing rule = `qty = (0.95 × available_cash) / price`, fractional BTC, long-only single-position.
- **D-09:** Seam = `OrderManager.on_signal` path (where it reads `signal_event.quantity`). NOT the strategy/position_sizer.
- **D-10:** Oracle format = CSV trade log + CSV equity curve + JSON summary (final cash + metrics).
- **D-11:** Two locations: fresh run → `output/` (gitignored); frozen oracle → `test/golden/` (committed). `make backtest` writes `output/`; blessed run promoted into `test/golden/`; integration test diffs fresh vs golden.
- **D-12:** Determinism = capture only deterministic fields. Exclude wall-clock `created_at`/audit timestamps and integer order-ID *values*. Identify trades by `entry_time`/`exit_time`/`side`, not by ID. No M1 determinism code change.
- **D-13:** Assertion = behavioral exact (trade timing + sides + sequence) + numerical exact, re-baselined only after M2 and M5. No float tolerance.
- **D-14:** Markers applied by path-based auto-marking in root `test/conftest.py` via `pytest_collection_modifyitems` (dir→marker). Zero edits to the 30 legacy `unittest.TestCase` files. unittest→pytest-native bulk conversion is M2b, NOT M1.
- **D-15:** Single root `test/conftest.py` (shared fixtures: `global_queue`, golden-file paths, backtest-engine factory + auto-marking hook). No conftest exists today.
- **D-16:** Smoke (fast, `unit`) = import→construct→run a handful of bars, assert completes + ≥1 trade. Integration (`integration` + `slow`) = full 2018→2026 run, diff fresh `output/` vs `test/golden/`.

### Claude's Discretion
- Exact ticker string (D-06) if universe/price-handler wiring needs a specific symbol.
- Exact filenames/column schemas within `output/` and `test/golden/` (trade-log columns, equity-curve granularity, metrics in JSON) — keep human-readable and diffable.
- Exact directory→marker mapping details and conftest fixture signatures.
- Run-script location/name (e.g. `scripts/run_backtest.py`) and how `make backtest` invokes it.

### Deferred Ideas (OUT OF SCOPE)
- Standalone CSV data provider / real Provider–Store–Feed split → M5a (M5-04).
- Full strategy-declared sizing policy + `RiskManager.check_cash` + `VariableSizer` → M5b (M5-06).
- Injected clock + seeded RNG + UUIDv7 + Decimal money → M2 (M2-01…M2-05).
- Fee/slippage correctness → M5a (M5-03).
- Bulk `unittest` → pytest-native conversion → M2b (M2-12).
- Doc reference update (old CSV filename) → log as COVERAGE-INDEX §E gap-discovery delta for owner approval.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| M1-01 | Backtest run path imports successfully — resolve config package/flat-module shadowing + price-handler→trading-system import cascade | **VERIFIED ROOT CAUSE** (see Pitfall 1): import fails at `itrader/price_handler/exchange/CCXT.py:8` `from itrader.config import FORBIDDEN_SYMBOLS` — `FORBIDDEN_SYMBOLS` lives in flat `itrader/config.py` but the package `itrader/config/` shadows it. Same for `OANDA.py:6` (`FORBIDDEN_SYMBOLS, TIMEZONE`) and `live_trading_system.py:22` (`Config`). Fix: re-export flat names from package OR change CCXT/OANDA imports. |
| M1-02 | `config.TIMEZONE`-style access no longer raises on backtest path | **VERIFIED** (see Pitfall 2): `from itrader import config` resolves to the package; the `config` singleton is an **empty dict `{}`** (system FileConfigProvider, no `settings/system.yaml`). `config.TIMEZONE` → `AttributeError` (dict has no `.TIMEZONE`). Used at `time_parser.py:9,166`, `data_provider.py:97`, `CCXT.py:71`. |
| M1-03 | `to_timedelta` returns a real value for the golden run's timeframes | **VERIFIED FALSE ALARM for `1d`**: `to_timedelta('1d')` returns `datetime.timedelta(days=1)` correctly (`'d'` is in the unit map). Returns `None` only for unsupported units (weeks/months) — not used by the daily golden run. The M1 fix may be a no-op/defensive guard; M2-10 owns the real fix. |
| M1-04 | `SMA_MACD_strategy` runs without error — `[-1]`→`.iloc[-1]`, `fillna='False'`→`fillna=False` | **VERIFIED + ESCALATED** (see Pitfall 3): `short_sma[-1]` works today but emits `FutureWarning` ("treating keys as positions is deprecated"). **FutureWarning IS promoted to error** under pyproject `filterwarnings=["error"]` (only UserWarning/DeprecationWarning ignored). So `.iloc[-1]` is **mandatory**, not cosmetic. `fillna='False'` (truthy string) passed to `ta.trend.MACD`. |
| M1-05 | Full PING→BAR→SIGNAL→ORDER→FILL loop — fix `record_metrics` on `PortfolioHandler` vs `Portfolio` | **VERIFIED** (see Pitfall 4): `record_metrics` exists ONLY on `Portfolio` (`portfolio.py:294`), NOT on `PortfolioHandler`. `backtest_trading_system.py:102` calls `self.portfolio_handler.record_metrics(ping_event.time)` → `AttributeError`. Fix: iterate portfolios. |
| M1-06 | Orders carry real non-zero quantity — minimal sizing in order/risk seam | **VERIFIED SEAM** (see Code Examples): strategy base emits `quantity=0` (`base.py:63`); passthrough at `order_manager.py:245/256/312/357`. Inject `qty=(0.95×portfolio.cash)/signal_event.price` in `_create_primary_order` (`order_manager.py:218`) where `signal_event.portfolio_id`, `signal_event.price`, and `self.portfolio_handler.get_portfolio(pid).cash` are all in scope. |
| M1-07 | SMA_MACD produces non-trivial trade log + equity curve on the golden CSV (`make backtest`) | Run loop already produces `portfolio.closed_positions` (trade log) + `portfolio.metrics_manager` snapshots (equity). Needs all of M1-01…M1-06 + the CSV branch + run script. |
| M1-08 | Reference output captured + committed (trade log, equity curve, final cash/metrics) | Serialize `closed_positions`/snapshots/`StatisticsReporting` to CSV+JSON, strip volatile fields (D-12). **CAUTION:** `StatisticsReporting._prepare_data` reads `portfolio.metrics` which **does not exist** as an attribute (Pitfall 5) — capture must not depend on that broken path, or fix it minimally. |
| M1-09 | Test skeleton — 8 markers applied, conftest/fixtures, run-path smoke test | No `conftest.py` exists. 8 markers declared in pyproject. 28/31 test files are `unittest.TestCase`; `python_classes=["Test*"]` collects them. Auto-marking hook works on unittest items at collection. |
| M1-10 | Run-path integration test + 274 existing component tests stay green | Integration test diffs fresh `output/` vs `test/golden/`. `make test-integration` runs `-m "integration"` — integration test must carry the marker (via path auto-marking). |
</phase_requirements>

## Summary

This is an **ignition + lock-the-oracle** phase, not a feature build. The job is surgical: make `make backtest` import and run `SMA_MACD` end-to-end on the golden CSV, capture the resulting numbers as the regression oracle, and stand up a pytest skeleton — all while keeping the 274 legacy component tests green. The CONTEXT.md already locks the HOW for every decision; this research **verified each claim against the actually-running code** so the planner sequences fixes on facts.

**Every ignition bug claimed in CONTEXT.md was confirmed by running the import chain and probing the runtime**, with three refinements the planner must know: (1) the *first* import failure today is `FORBIDDEN_SYMBOLS` in `CCXT.py`, not a generic "config cascade" — the package `itrader/config/` shadows the flat `itrader/config.py`; (2) the `config` singleton is literally an empty `dict`, so `config.TIMEZONE` raises `AttributeError`, not `KeyError`; (3) the `short_sma[-1]` fix is **mandatory** (not cosmetic) because `FutureWarning` is promoted to a hard error by the project's `filterwarnings=["error"]` config — confirmed by probe. Two latent bugs beyond the listed M1 set surfaced: `to_timedelta('1d')` actually works (M1-03 is a near-no-op for daily data), and `StatisticsReporting._prepare_data` reads a non-existent `portfolio.metrics` attribute (will break oracle capture if used naively).

**Primary recommendation:** Fix the ignition cascade in strict dependency order (config shadowing → TIMEZONE access → strategy indexing/fillna → record_metrics target), add the in-`PriceHandler` CSV branch producing the exact `{lowercase-ohlcv, tz-aware DatetimeIndex}` shape CCXT produces, inject sizing at `OrderManager._create_primary_order`, then build the run script + capture serializer + conftest auto-marking. Verify each fix by re-running the import/run, not by inspection.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Config name resolution (flat vs package) | Shared core (`itrader/config/`) | Import machinery | Python package dir shadows sibling flat module; resolution is an import-system concern |
| CSV/offline price feed | Price layer (`PriceHandler`) | — | D-07 keeps feed inside `PriceHandler` to touch zero of its 4 consumers |
| Position sizing (qty resolution) | Order/risk layer (`OrderManager`) | Portfolio (read cash) | PROJECT #24/#31: order/risk layer resolves per-portfolio qty; NOT strategy layer |
| Bar dispatch + signal generation | Strategy layer (`StrategiesHandler`/`Strategy`) | Universe (bar source) | Strategy reads resampled bars, emits SignalEvent via queue |
| Metrics/equity snapshot | Portfolio layer (`Portfolio.record_metrics`) | Engine (drives per-tick) | Snapshot is per-`Portfolio` state; engine calls it per ping |
| Oracle serialization | Reporting/run-script layer | Portfolio (source data) | Run script reads `closed_positions`/snapshots; writes CSV+JSON |
| Test markers + fixtures | Test infra (`test/conftest.py`) | pytest collection hook | Collection-time marking applies to unittest.TestCase items |

## Standard Stack

This phase adds **no new runtime dependencies** — it uses what is already installed. The "stack" is the existing pinned versions, all verified present in this session.

### Core (verified in-session)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python (CPython) | 3.13.1 | Runtime | `[VERIFIED: poetry run python]` pinned via pyenv `.python-version` |
| pandas | 2.3.3 | OHLCV DataFrames, DatetimeIndex slicing, resample | `[VERIFIED: import]` primary data structure throughout |
| numpy | 2.2.6 | array ops, `np.nditer` in PingGenerator | `[VERIFIED: import]` |
| ta | 0.11.0 | `trend.SMAIndicator`, `trend.MACD` in SMA_MACD | `[CITED: CLAUDE.md STACK]` (`ta.__version__` not exposed; version from lockfile) |
| pytest | 8.4.2 | test runner | `[VERIFIED: pytest banner]` |
| pytest-cov | 5.0.0 | coverage | `[VERIFIED: pytest banner plugins]` |

### Supporting (already present, used by capture/skeleton)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `json` (stdlib) | — | JSON metrics summary (D-10) | Oracle summary serialization |
| `csv`/pandas `.to_csv` | — | trade log + equity curve CSV | Diffable series (D-10) |
| `pathlib` (stdlib) | — | `output/` vs `test/golden/` paths | Path fixtures in conftest |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `pandas.to_csv` for the oracle | hand-rolled writer | `to_csv` is deterministic given fixed columns/float format — prefer it; pin `float_format` to avoid platform repr drift |
| In-`PriceHandler` CSV branch (D-07) | standalone provider | LOCKED to in-PriceHandler — standalone is M5a (deferred) |

**Installation:** None. No `npm`/`pip install` step. (Package legitimacy audit therefore N/A — see below.)

## Package Legitimacy Audit

**Not applicable to this phase.** M1 installs **zero** new external packages — it is a bugfix/wiring/test-skeleton phase using only already-installed, already-locked dependencies (`poetry.lock` committed). No registry verification or slopcheck needed. If the planner later decides a tiny diff helper is wanted for the oracle test, prefer stdlib (`difflib`, `csv`, `json`) over any new dependency to keep the legitimacy surface at zero.

## Architecture Patterns

### System Architecture Diagram (M1 ignition path)

```
                       scripts/run_backtest.py  (D-05, committed)
                                │  pins ticker=BTCUSD, window 2018→2026, cash=10k, fees/slip=0
                                ▼
                    TradingSystem.__init__  (wires shared global_queue)
                                │
        ┌───────────────────────┼─────────────────────────────────────────┐
        ▼                       ▼                                           ▼
   PriceHandler           PortfolioHandler.add_portfolio()         StrategiesHandler.add_strategy()
   (+ CSV branch, D-07)    cash=10_000                              SMA_MACD(timeframe='1d')
        │  load_data() reads CSV → self.prices[BTCUSD]                     │ subscribe portfolio_id
        │  shape: {open,high,low,close,volume}, tz-aware DatetimeIndex     │
        ▼                                                                   ▼
   ping.set_dates(prices index)
        │
        ▼   for ping in ping:  ── PING ──▶ universe.generate_bar_event ── BAR ──▶ strategy.calculate_signal
                                                                                        │ buy/sell → quantity=0
                                                                          ── SIGNAL ──▶ OrderManager.on_signal
                                                                                        │ ★ SIZING SEAM (D-08/09)
                                                                                        │ qty=(0.95*cash)/price
                                                                          ── ORDER ───▶ ExecutionHandler → SimulatedExchange
                                                                                        │ fee=0 slip=0 → FillEvent(EXECUTED)
                                                                          ── FILL ────▶ Portfolio.on_fill (positions/cash)
                                                                                        + OrderManager.on_fill (reconcile)
        │  after each ping: ★ record_metrics PER Portfolio (M1-05 fix)
        ▼
   closed_positions (trade log) + metrics snapshots (equity curve) + StatisticsReporting (summary)
        │
        ▼   run script serializes → output/{trades.csv, equity.csv, summary.json}  (gitignored)
                                    promote blessed run → test/golden/  (committed)
                                    integration test diffs fresh vs golden  (behavioral+numerical exact)
```

### Recommended Project Structure (additions only)
```
scripts/
└── run_backtest.py        # D-05: committed reproducible oracle generator + invoked by `make backtest`
output/                    # D-11: gitignored fresh-run artifacts (already covered by .gitignore "output")
└── {trades.csv, equity.csv, summary.json}
test/
├── conftest.py            # D-15: shared fixtures + pytest_collection_modifyitems auto-marking (NEW)
├── golden/                # D-11: committed frozen oracle (NEW)
│   └── {trades.csv, equity.csv, summary.json}
├── test_smoke/            # D-16: smoke test (fast, unit) — or place under existing dir w/ explicit marker
└── test_integration/      # D-16: full-run integration (integration + slow)
```

### Pattern 1: Dependency-ordered ignition fixes
**What:** Fix import-time errors before runtime errors before logic errors.
**When to use:** Always for this phase — a later fix can't be verified until earlier ones unblock the import.
**Order:** (1) config shadowing [import] → (2) `config.TIMEZONE` access [import/init, hit by `time_parser` import] → (3) `record_metrics` target [runtime, end of loop] → (4) strategy `.iloc`/`fillna` [runtime, mid-loop] → (5) CSV branch [load] → (6) sizing seam [signal].
**Verify each:** re-run `poetry run python -c "from itrader.trading_system.backtest_trading_system import TradingSystem"` after (1)-(2); run a few bars after (3)-(6).

### Pattern 2: Path-based auto-marking (D-14)
**What:** `pytest_collection_modifyitems(config, items)` in root `conftest.py` inspects each item's path and adds markers.
**Why it works on unittest.TestCase:** pytest wraps `unittest.TestCase` methods as collected items; `item.add_marker(...)` at collection applies regardless of the test being unittest-native. Verified that `python_classes=["Test*"]` already collects the legacy classes.
**Example:**
```python
# Source: pytest docs — pytest_collection_modifyitems hook
import pathlib
import pytest

DIR_MARKERS = {
    "test_portfolio_handler": "portfolio",
    "test_positions":         "portfolio",
    "test_transaction":       "portfolio",
    "test_events":            "events",
    "test_order_handler":     "orders",
    "test_execution_handler": "execution",
    "test_strategy":          "strategy",
    "test_integration":       "integration",
    "test_smoke":             "unit",
}

def pytest_collection_modifyitems(config, items):
    for item in items:
        parts = pathlib.Path(str(item.fspath)).parts
        for segment, marker in DIR_MARKERS.items():
            if segment in parts:
                item.add_marker(getattr(pytest.mark, marker))
        # integration tests are also slow (D-16)
        if "test_integration" in parts:
            item.add_marker(pytest.mark.slow)
```

### Anti-Patterns to Avoid
- **Fixing sizing in the strategy/position_sizer.** D-09 LOCKS the seam to `OrderManager`. The `position_sizer/` modules are stranded and out of scope.
- **Letting the CSV branch produce a differently-shaped frame than CCXT.** Downstream (`get_bar`, `generate_bar_event`, strategy `bars.close`) expects lowercase OHLCV columns + tz-aware `date` DatetimeIndex. A mismatch yields silent `KeyError`/empty bars.
- **Depending on `portfolio.metrics`** for oracle capture (Pitfall 5) — it doesn't exist.
- **Adding new ignored warnings to pyproject** to dodge the FutureWarning. Fix the code (`.iloc`), don't loosen the gate.
- **Building a standalone CSV provider.** Deferred to M5a — out of scope.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Trade-log / equity-curve serialization | custom row writer | `pandas.DataFrame.to_csv(float_format=...)` | deterministic, diffable; pin `float_format` for cross-platform repr stability |
| Golden diff in integration test | byte-compare | load both CSVs to DataFrame + assert frame-equal on deterministic columns (D-12) | excludes volatile cols cleanly; clearer failure messages |
| String→timedelta | new parser | existing `to_timedelta` (works for `1d`) | already present; M2-10 fixes weeks/months |
| Marker application | edit 30 test files | `pytest_collection_modifyitems` (D-14) | zero edits to legacy files |
| Resampling daily→daily | manual | `PriceHandler.get_resampled_bars` (no-op branch when tf matches) | already handles same-timeframe path |

**Key insight:** Almost everything M1 needs already exists in-tree (engine loop, strategy, reporting, storage factory). The phase is *unblocking and wiring*, not building.

## Runtime State Inventory

> This is a rename/refactor-adjacent phase (config shadowing). State inventory applies to the config-resolution change.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | None — backtest path uses in-memory order storage (`OrderStorageFactory.create('backtest')`); no DB writes on the offline path once CSV branch skips `SqlHandler`. Verified `__init__` builds `SqlHandler()` today (must be skipped by CSV branch, D-07). | Ensure CSV branch does NOT construct `SqlHandler`/`CCXT` |
| Live service config | None — offline backtest, no external services touched. PostgreSQL on :5432 is referenced by `SqlHandler` but must not be reached on the CSV path. | Verify no Postgres connection attempted in backtest |
| OS-registered state | None — no schedulers, daemons, or OS registrations. | None |
| Secrets/env vars | `itrader/config.py` (flat) reads `BINANCE_*`/`OANDA_*` env vars via `load_secret_keys()`. Backtest path does not need them; they default to `None`. The `DATA_DB_URL`/`SYSTEM_DB_URL` env vars exist but are unused on CSV path. | None — code rename only if package re-export chosen; env var names unchanged |
| Build artifacts | None new. No egg-info rename. The flat-vs-package config decision is import-resolution only, not a package rename. | None |

**Config-shadowing specifics:** `itrader/config.py` (flat, defines `Config`, `TIMEZONE`, `FORBIDDEN_SYMBOLS`, `SUPPORTED_*`, `set_config`, `load_secret_keys`) coexists with `itrader/config/` (package, defines domain config classes + `get_*` getters). **The package wins** Python import resolution, so flat-only names are unreachable via `from itrader.config import X`. Consumers needing flat names: `CCXT.py` (`FORBIDDEN_SYMBOLS`, `config.TIMEZONE`), `OANDA.py` (`FORBIDDEN_SYMBOLS, TIMEZONE`), `live_trading_system.py` (`Config`), `time_parser.py` / `data_provider.py` (`config.TIMEZONE`). Two viable minimal fixes (planner picks): **(A)** re-export the needed flat names from `itrader/config/__init__.py` (and provide a `TIMEZONE` on the system config or as a module constant); **(B)** change the broken imports to pull from a clearly-named module. Live-path files (`OANDA.py`, `live_trading_system.py`) are out of program scope but their *import* still executes via the cascade — confirm they don't import on the backtest path (they do NOT: backtest imports `CCXT` via `data_provider`, but not `OANDA`/live).

## Common Pitfalls

### Pitfall 1: The first import failure is `FORBIDDEN_SYMBOLS`, not a generic "config cascade"
**What goes wrong:** `from itrader.trading_system.backtest_trading_system import TradingSystem` fails with `ImportError: cannot import name 'FORBIDDEN_SYMBOLS' from 'itrader.config'` at `itrader/price_handler/exchange/CCXT.py:8`.
**Why it happens:** `data_provider.py:12` does `from .exchange.CCXT import CCXT_exchange` unconditionally at module import; `CCXT.py:8` does `from itrader.config import FORBIDDEN_SYMBOLS`; the package shadows the flat module that defines `FORBIDDEN_SYMBOLS`.
**How to avoid:** Resolve the config name resolution FIRST (M1-01). Until then no other fix is verifiable.
**Warning signs:** Any import touching `data_provider` → `CCXT` → `config`.
`[VERIFIED: poetry run python import trace, this session]`

### Pitfall 2: `config.TIMEZONE` raises `AttributeError` (config is an empty dict)
**What goes wrong:** `config.TIMEZONE` → `AttributeError: 'dict' object has no attribute 'TIMEZONE'`.
**Why it happens:** `itrader/__init__.py:8` sets `config = system_provider.get_config()`; with no `settings/system.yaml`, the system FileConfigProvider returns `{}`. Confirmed `type(config) == dict`, `repr == {}`, `hasattr(config,'TIMEZONE') == False`.
**How to avoid (M1-02 minimal fix):** provide `TIMEZONE` where the code reads it. Cleanest minimal: a module-level `TIMEZONE` constant the four call sites import, OR set a default tz on the system config. The golden data is UTC daily; pick a tz consistent with the CSV branch's index tz and the PingGenerator default (`Europe/Paris`) so `get_bar(ticker, ping.time)` index-matches exactly.
**Warning signs:** `time_parser.py` imports `config` at module load (line 6) — but only *calls* `config.TIMEZONE` inside functions, so import succeeds; the error is deferred to first call (e.g. `data_provider.update_data` or `round_timestamp_to_frequency`). The backtest loop does NOT call `update_data`; check whether the chosen tz path is actually exercised.
`[VERIFIED: poetry run python, this session]`

### Pitfall 3: `short_sma[-1]` works but the FutureWarning is a HARD ERROR under pytest
**What goes wrong:** `short_sma[-1]` on a datetime-indexed Series emits `FutureWarning: Series.__getitem__ treating keys as positions is deprecated`. The value (`3`) is returned in a bare script, so `make backtest` may "work" — but **any test running the strategy fails** because `filterwarnings=["error"]` promotes `FutureWarning` to an exception.
**Why it happens:** pyproject ignores only `UserWarning` and `DeprecationWarning`; `FutureWarning` is NOT in the ignore list. `--disable-warnings` only hides the summary, it does NOT cancel the `error` filter — confirmed by probe (`test_future_warning_promotion FAILED`, `test_user_warning_ignored PASSED`).
**How to avoid:** `.iloc[-1]` (M1-04) is **mandatory** for M1-10 (green tests + integration test that runs the strategy). Also fix `fillna='False'` → `fillna=False` (the string is truthy — wrong behavior). After the fix, run the integration test to confirm zero FutureWarnings escape.
**Warning signs:** any new test that imports/runs SMA_MACD over real bars.
`[VERIFIED: pytest probe under project config, this session]`

### Pitfall 4: `record_metrics` called on the wrong object
**What goes wrong:** `backtest_trading_system.py:102` `self.portfolio_handler.record_metrics(ping_event.time)` → `AttributeError` (`PortfolioHandler` has no `record_metrics`).
**Why it happens:** `record_metrics` is defined on `Portfolio` (`portfolio.py:294`), which delegates to `metrics_manager.record_snapshot(time)`. The engine called it on the handler.
**How to avoid (M1-05):** iterate portfolios, e.g. `for pid in portfolio_handler.<list ids>: portfolio_handler.get_portfolio(pid).record_metrics(ping_event.time)`. (Confirm the handler's portfolio-enumeration API: `get_portfolio_count`, `get_portfolios_by_state` exist; planner picks the iteration method.) `record_snapshot` correctly uses the passed bar `time` (deterministic) — only its *default* is `datetime.now()`, which the loop never triggers.
**Warning signs:** loop completes BAR/SIGNAL/ORDER/FILL but crashes at end of each tick.
`[VERIFIED: grep + source read, this session]`

### Pitfall 5: `StatisticsReporting._prepare_data` reads non-existent `portfolio.metrics`
**What goes wrong:** `statistics.py:70` `equity_metrics = pd.DataFrame.from_dict(portfolio.metrics, orient='index')` — but `Portfolio` has **no `metrics` attribute** (only `record_metrics` method + `metrics_manager`). Confirmed `hasattr(Portfolio,'metrics') == False`.
**Why it happens:** latent dead/broken path; `_prepare_data` is "Not used in Live trading" and apparently untested on the backtest path.
**How to avoid (affects M1-08):** the oracle capture must source the equity curve from `metrics_manager` snapshots directly (the `PortfolioSnapshot` list: `timestamp,total_equity,cash_balance,positions_value,unrealized_pnl,realized_pnl,total_pnl,open_positions_count,portfolio_return`), NOT via `StatisticsReporting._prepare_data` as-is. Either (a) capture from snapshots in the run script, or (b) add a minimal `Portfolio.metrics` accessor returning the snapshot dict. Trade log: `portfolio.closed_positions` → `Position.to_dict()` (fields below). This is a gap-discovery item beyond the listed M1 bugs — flag for the planner.
**Warning signs:** `print_summary`/`calculate_statistics` raising `AttributeError` during capture.
`[VERIFIED: source read + hasattr probe, this session]`

### Pitfall 6: CSV index timezone must match PingGenerator and CCXT convention
**What goes wrong:** `get_bar(ticker, ping_event.time)` does `self.prices[ticker].loc[time]`; if the CSV index tz differs from the ping time tz, lookups silently miss (returns `None` via the bare-except in `get_bar`), bars are empty, no signals fire, zero trades.
**Why it happens:** CCXT path converts index to `config.TIMEZONE` (`CCXT.py:71`); PingGenerator default tz is `Europe/Paris`; the CSV is UTC. The CSV branch must set a consistent, tz-aware index and `ping.set_dates` derives from that same index — so as long as the branch's index is what `set_dates` consumes, they match by construction. Keep them sourced from the same frame.
**How to avoid:** build `self.prices[BTCUSD]` with a tz-aware DatetimeIndex; `ping.set_dates(self.price_handler.prices[...].index)` already uses that index (`backtest_trading_system.py:85`). Do NOT introduce a second tz conversion.
**Warning signs:** run completes but trade log is empty / equity flat at 10k.
`[VERIFIED: source read of get_bar, generate_bar_event, set_dates, this session]`

## Code Examples

### Expected `self.prices[TICKER]` shape (CSV branch must reproduce)
```python
# Source: itrader/price_handler/exchange/CCXT.py:66-71 (the shape downstream expects)
data.columns = ['date', 'open', 'high', 'low', 'close', 'volume']   # lowercase
data = data.set_index('date')
data.index = pd.to_datetime(data.index, unit='ms', utc=True)
data.index = data.index.tz_convert(config.TIMEZONE)                  # tz-aware
# → DataFrame indexed by tz-aware DatetimeIndex named 'date', cols open/high/low/close/volume
# CSV branch: read golden CSV, map 'Open time'→date, Open/High/Low/Close/Volume→lowercase,
#             parse 'YYYY-MM-DD HH:MM:SS.ffffff UTC' → tz-aware index, slice 2018→2026 (D-02)
```

### Sizing seam injection point (D-08/D-09)
```python
# Source: itrader/order_handler/order_manager.py:218-260 (_create_primary_order)
# In scope at the seam: signal_event.portfolio_id, signal_event.price (= last_close),
#                       self.portfolio_handler.get_portfolio(pid).cash
# Replace the quantity=signal_event.quantity passthrough (lines 245/256 and market via Order.new_order):
portfolio = self.portfolio_handler.get_portfolio(signal_event.portfolio_id)
qty = (0.95 * portfolio.cash) / signal_event.price        # D-08: fraction-of-cash, fractional BTC
# NOTE: Order.new_order(signal_event, exchange) (line 238, MARKET path) reads signal_event.quantity
#       internally — the seam must set the qty BEFORE Order construction (e.g. mutate a copy of the
#       signal or pass qty into the Order factory). Planner decides the cleanest non-mutating approach.
```

### Trade-log fields available (D-10/D-12)
```python
# Source: itrader/portfolio_handler/position.py:244 Position.to_dict()
# Deterministic fields for the oracle (D-12): entry_date, exit_date, side, net_quantity,
#   avg_price, avg_bought, avg_sold, total_bought, total_sold, realised_pnl, pair
# EXCLUDE: position_id (integer ID value — non-deterministic until M2), current_price/unrealised (volatile)
# Identify each trade by (entry_date, exit_date, side) per D-12 — NOT by position_id.
```

### Equity curve source (D-10, avoid Pitfall 5)
```python
# Source: itrader/portfolio_handler/metrics_manager.py:120 record_snapshot → PortfolioSnapshot
# Capture from the snapshot list, not StatisticsReporting._prepare_data:
#   timestamp, total_equity, cash_balance, positions_value,
#   unrealized_pnl, realized_pnl, total_pnl, open_positions_count, portfolio_return
# (Snapshot uses the bar `time` passed by record_metrics → deterministic.)
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `series[-1]` positional on datetime index | `series.iloc[-1]` | pandas 2.x deprecation | `[-1]` emits FutureWarning → hard error under `filterwarnings=["error"]`; M1-04 fix mandatory |
| Flat `config.py` module | domain `config/` package | refactor introduced package | Package shadows flat module; flat-only names (`FORBIDDEN_SYMBOLS`, `TIMEZONE`) unreachable — M1-01 |

**Deprecated/outdated:**
- `StatisticsReporting._prepare_data` `portfolio.metrics` access — broken path, do not rely on for capture (Pitfall 5).
- `to_timedelta` weeks/months → `None` — not exercised by daily golden run; M2-10 fixes.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `ta` is version 0.11.0 (couldn't read `ta.__version__`; taken from CLAUDE.md/lockfile) | Standard Stack | Low — strategy behavior unchanged by patch version; oracle is captured fresh regardless |
| A2 | Re-exporting flat names from `config/__init__.py` is an acceptable M1-01 fix (vs editing import sites) | Runtime State Inventory | Low — both options unblock import; planner/owner picks; M2-06 reworks config anyway |
| A3 | Backtest path does NOT import `OANDA.py`/live modules (so their broken imports don't block) | Runtime State Inventory | Medium — if a transitive import pulls them in, more import sites need fixing. Mitigation: planner verifies by running the import after the M1-01 fix |
| A4 | A consistent tz (e.g. UTC or Europe/Paris) for the CSV index avoids the Pitfall-6 mismatch | Pitfall 6 | Medium — wrong tz → empty bars / zero trades. Mitigation: source ping dates from the same frame; assert ≥1 trade in smoke test |
| A5 | Sizing at `_create_primary_order` covers the MARKET path (SMA_MACD uses market orders, no SL/TP) | Sizing seam | Low — verified SMA_MACD emits BUY/SELL with sl=0/tp=0 (`base.py` buy/sell defaults); only primary MARKET order created |

**These `[ASSUMED]` items need confirmation during planning/execution — primarily A3 (run the import) and A4 (assert ≥1 trade).**

## Open Questions (RESOLVED)

1. **Which M1-01 fix shape — re-export vs import-site edit?**
   - What we know: both unblock the import; flat `config.py` holds `FORBIDDEN_SYMBOLS`/`TIMEZONE`/`Config`; package holds domain classes.
   - What's unclear: owner preference; M2-06 collapses config to Pydantic anyway.
   - Recommendation: minimal re-export from `config/__init__.py` (smallest diff, no behavior change), defer the real fix to M2-06. Planner confirms.
   - **RESOLVED:** re-export flat names from `config/__init__.py` (chosen by Plan 01-01 Task 1). The real config collapse is deferred to M2-06; the flat `config.py` is left unmodified.

2. **CSV index timezone choice (Pitfall 6 / A4).**
   - What we know: CSV is UTC; PingGenerator default `Europe/Paris`; CCXT converts to `config.TIMEZONE`.
   - What's unclear: which tz makes `record_metrics`/`check_timeframe` behave correctly for daily bars.
   - Recommendation: keep index tz-aware and source ping dates from the same frame (they match by construction); the *value* of tz only matters where `check_timeframe` runs — confirm the daily path doesn't depend on a specific offset. Lock it once the smoke test produces ≥1 trade, then it's frozen in the oracle.
   - **RESOLVED:** `Europe/Paris` chosen to match the CCXT convention (`CCXT.py:71` converts to `config.TIMEZONE`) and the existing config singleton / PingGenerator default. A tz mismatch (which would silently yield zero trades — Pitfall 6) is caught at runtime by the smoke test's run-completion + ≥1-non-zero-qty-trade assertion in **Plan 01-04 Task 3** (`test/test_smoke/test_backtest_smoke.py`), which runs GREEN *before* the oracle is blessed/frozen into `test/golden/` (Plan 01-05). The CSV-branch index and the ping dates are sourced from the same frame (`backtest_trading_system.py:85` `ping.set_dates`), so the two tz-match by construction regardless of the chosen offset value.

3. **Equity-curve granularity / metric set in JSON summary (Claude's discretion).**
   - What we know: per-ping snapshots available; `StatisticsReporting` computes sharpe/sortino/cagr/drawdown but some of that math is buggy (M5-07 territory).
   - What's unclear: which metrics to freeze now without baking in M5-fixable bugs.
   - Recommendation: freeze raw deterministic series (per-ping equity, final cash, trade count, total realised PnL) + only metrics that are clearly correct; keep derived ratios minimal so the M5 re-baseline is the sanctioned place to add them.
   - **RESOLVED:** Claude's Discretion — minimal deterministic metrics only. Freeze the raw deterministic series (per-ping equity from snapshots, final cash, trade count, total realised PnL) plus only clearly-correct values; keep derived ratios (sharpe/sortino/cagr/drawdown) out of the M1 oracle so the sanctioned place to add them is the M5 re-baseline.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | everything | ✓ | 3.13.1 | — |
| Poetry venv (`.venv`) | run + tests | ✓ | in-project | — |
| pandas / numpy / ta | strategy + capture | ✓ | 2.3.3 / 2.2.6 / 0.11.0 | — |
| pytest (+cov) | skeleton + tests | ✓ | 8.4.2 / 5.0.0 | — |
| Golden CSV | oracle run | ✓ | `data/BTCUSD_1d_ohlcv_2018_2026.csv` (3076 bars + header) | — |
| PostgreSQL :5432 | `SqlHandler` (live/SQL path) | n/a | — | **CSV branch (D-07) skips SqlHandler entirely — Postgres NOT required for M1** |
| `settings/system.yaml` | system config TIMEZONE | ✗ | — | provide `TIMEZONE` via M1-02 fix (constant or default) — config singleton is `{}` today |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** PostgreSQL (avoided by CSV branch); `settings/system.yaml` (TIMEZONE supplied by M1-02 fix).

## Validation Architecture

> Nyquist validation enabled (no `workflow.nyquist_validation: false` in config). Section included.

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.4.2 (+ pytest-cov 5.0.0) |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `poetry run pytest test/ -m "unit" -q` (smoke) |
| Full suite command | `poetry run pytest test/ -q` (all 274 component tests + new) |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| M1-01 | import succeeds | smoke (unit) | `poetry run pytest test/test_smoke -m unit` (imports TradingSystem) | ❌ Wave 0 |
| M1-02 | no AttributeError on TIMEZONE | smoke (unit) | covered by run-a-few-bars smoke | ❌ Wave 0 |
| M1-04 | strategy runs w/o FutureWarning | smoke (unit) | smoke runs ≥max_window bars; `filterwarnings=error` catches FutureWarning | ❌ Wave 0 |
| M1-05 | loop completes per-tick | smoke (unit) | smoke asserts run completes | ❌ Wave 0 |
| M1-06 | orders have qty>0 | smoke (unit) | smoke asserts ≥1 trade with non-zero qty | ❌ Wave 0 |
| M1-07 | non-trivial trade log + equity | integration (slow) | `poetry run pytest test/test_integration -m integration` | ❌ Wave 0 |
| M1-08 | fresh run == frozen golden | integration (slow) | integration diffs `output/` vs `test/golden/` (behavioral+numerical exact, D-13) | ❌ Wave 0 |
| M1-09 | 8 markers applied | meta | `poetry run pytest test/ --collect-only -q` shows markers; `-m portfolio` etc. select | conftest ❌ Wave 0 |
| M1-10 | 274 legacy green + integration exists | full suite | `poetry run pytest test/ -q` | partially (legacy ✓, new ❌) |

### Sampling Rate
- **Per task commit:** `poetry run pytest test/ -m unit -q` (smoke + fast units)
- **Per wave merge:** `poetry run pytest test/ -q` (full suite, 274 + new)
- **Phase gate:** full suite green + integration diff exact before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `test/conftest.py` — shared fixtures (`global_queue`, golden paths, backtest-engine factory) + `pytest_collection_modifyitems` auto-marking (D-14/D-15)
- [ ] `test/test_smoke/test_backtest_smoke.py` — import→construct→run handful of bars, assert completes + ≥1 non-zero-qty trade (D-16)
- [ ] `test/test_integration/test_backtest_oracle.py` — full 2018→2026 run, diff fresh vs `test/golden/` (D-16)
- [ ] `test/golden/{trades.csv,equity.csv,summary.json}` — frozen oracle (promoted from a blessed `output/` run, D-11)
- [ ] `scripts/run_backtest.py` + `make backtest` target — oracle generator (D-05)
- [ ] No framework install needed (pytest already present)

## Security Domain

> `security_enforcement` not configured `false` → included. M1 is an offline backtest bugfix phase; security surface is minimal.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | offline backtest, no auth |
| V3 Session Management | no | n/a |
| V4 Access Control | no | n/a |
| V5 Input Validation | minor | CSV parsing — golden file is trusted/committed input; validate header/shape on load to fail loudly (Pitfall 6) |
| V6 Cryptography | no | no secrets handled on backtest path (env-var secrets default to `None`, unused) |

### Known Threat Patterns for offline backtest
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Malformed/regenerated CSV silently yields wrong oracle | Tampering | Validate column header + bar count on load; pin date window (D-02); assert ≥1 trade in smoke |
| Accidental Postgres/network reach on "offline" path | Info disclosure / availability | D-07 CSV branch must skip `SqlHandler`/`CCXT`; verify no connection attempted |
| Committed secrets | Info disclosure | flat `config.py` reads env vars only (no hardcoded creds); `settings/` and `keys.json` gitignored — verified |

## Sources

### Primary (HIGH confidence — verified in-session)
- `poetry run python` import trace → `ImportError FORBIDDEN_SYMBOLS` at `CCXT.py:8`
- `poetry run python` → `config` is `dict`, `{}`, no `TIMEZONE`
- `poetry run pytest` probe → FutureWarning promoted to error under project config; UserWarning ignored
- `poetry run python` → `to_timedelta('1d') == timedelta(days=1)`; `hasattr(Portfolio,'metrics') == False`
- Source reads: `data_provider.py`, `backtest_trading_system.py`, `SMA_MACD_strategy.py`, `time_parser.py`, `config.py` (flat), `config/__init__.py`, `order_manager.py`, `strategy_handler/base.py`, `portfolio.py`, `metrics_manager.py`, `position.py`, `statistics.py`, `dynamic.py`, `ping_generator.py`, `storage_factory.py`, `pyproject.toml`, `.gitignore`, `Makefile`
- `data/BTCUSD_1d_ohlcv_2018_2026.csv` header + row count (3077 lines incl. header)

### Secondary (project docs)
- `.planning/phases/01-m1-ignition-lock-the-oracle/01-CONTEXT.md` (locked decisions)
- `.planning/REQUIREMENTS.md` (M1-01…M1-10), `CLAUDE.md` (stack/conventions)

### Tertiary (LOW confidence — flagged)
- `ta` version 0.11.0 from CLAUDE.md/lockfile (not runtime-verifiable; `ta.__version__` absent) — A1

## Metadata

**Confidence breakdown:**
- Ignition bugs (M1-01…M1-05): HIGH — each reproduced by running code this session
- CSV branch shape (M1/D-07): HIGH — derived from CCXT's exact output columns + downstream consumers
- Sizing seam (M1-06): HIGH — seam located, in-scope vars confirmed
- Oracle capture (M1-07/08): MEDIUM — data sources confirmed, but `_prepare_data` is broken (Pitfall 5) so capture must source from snapshots directly
- Test skeleton (M1-09/10): HIGH — config + collection behavior verified by probe
- TZ choice (Pitfall 6): MEDIUM — mechanism understood; exact tz value to be locked by smoke test producing ≥1 trade

**Research date:** 2026-06-04
**Valid until:** 2026-07-04 (stable brownfield; re-verify if dependencies bumped)
