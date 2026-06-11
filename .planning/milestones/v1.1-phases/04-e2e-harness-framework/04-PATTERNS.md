# Phase 4: E2E Harness & Framework - Pattern Map

**Mapped:** 2026-06-09
**Files analyzed:** 11 (5 create, 6 modify)
**Analogs found:** 11 / 11

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `tests/e2e/conftest.py` (CREATE) | test fixture / harness | request-response (build→run→read→diff) | `tests/integration/conftest.py::backtest_engine` + `tests/integration/test_backtest_oracle.py` (diff machinery) | exact (compose two analogs) |
| `tests/e2e/strategies/single_market_buy.py` (CREATE) | strategy (test library) | event-driven (per-bar signal) | `itrader/strategy_handler/SMA_MACD_strategy.py` + `base.py::Strategy` | exact |
| `tests/e2e/smoke/single_market_buy/scenario.py` (CREATE) | config/spec | transform (spec→engine knobs) | `scripts/run_backtest.py` pinned-constant block + `itrader/config/{exchange,portfolio}.py` | role-match |
| `tests/e2e/smoke/single_market_buy/test_scenario.py` (CREATE) | test | request-response | `tests/integration/test_backtest_oracle.py` (one-liner shape, NOT the body) | role-match |
| `tests/e2e/smoke/single_market_buy/bars.csv` + `golden/` (CREATE) | test data / fixtures | file-I/O | golden CSV schema in `itrader/price_handler/store/csv_store.py:155` + `tests/golden/` | exact (schema) |
| `itrader/reporting/summary.py` (CREATE) | library / serialization assembly | transform (state→dict) | `itrader/reporting/frames.py` (verbatim-relocation precedent) + `scripts/run_backtest.py:70-151` (the source bodies) | exact |
| `scripts/run_backtest.py` (MODIFY) | oracle generator | request-response | self (replace local defs with import) | self |
| `tests/conftest.py` (MODIFY) | test config hook | event-driven (collection) | self (`pytest_collection_modifyitems`, lines 42-56) | self |
| `pyproject.toml` (MODIFY) | build config | config | self (`markers` block, lines 61-65) | self |
| `Makefile` (MODIFY) | build target | config | self (`test-unit`/`test-integration`, lines 31-37) | self |
| `tests/unit/core/test_enums.py` (MODIFY) | test | n/a (delete dead skip) | self (lines 24-33) | self |

## Pattern Assignments

### `tests/e2e/conftest.py` (test fixture / harness — request-response)

**Primary analog:** `tests/integration/conftest.py::backtest_engine` (the deferred-construction factory). **Diff analog:** `tests/integration/test_backtest_oracle.py` (the exact-diff mechanic + in-process scenario-module load).

**Factory-fixture + deferred-import pattern** (`tests/integration/conftest.py:45-70`) — generalize this. The `backtest_engine` fixture returns a callable; the `TradingSystem` import lives INSIDE the inner function so `--collect-only` stays clean. `run_scenario` is the direct descendant — same shape, generalized to take `here: Path` and wire from a `ScenarioSpec`:
```python
@pytest.fixture
def backtest_engine():
    def _make(ticker="BTCUSD", timeframe="1d", start_date="2018-01-01", end_date="2026-06-03", cash=10_000):
        from itrader.trading_system.backtest_trading_system import TradingSystem  # deferred
        return TradingSystem(exchange="csv", start_date=start_date, end_date=end_date)
    return _make
```

**Engine wiring to copy** (`scripts/run_backtest.py:158-183`) — the exact `add_strategy` / `add_portfolio` / `subscribe_portfolio` / `run` / read-after-run sequence the harness reproduces:
```python
system = TradingSystem(exchange="csv", start_date=START_DATE, end_date=END_DATE)
strategy = SMA_MACD_strategy(timeframe=TIMEFRAME, tickers=[TICKER])
system.strategies_handler.add_strategy(strategy)
portfolio_id = system.portfolio_handler.add_portfolio(user_id=1, name="oracle_pf", exchange="csv", cash=CASH)
strategy.subscribe_portfolio(portfolio_id)
system.run()
# --- Read result state AFTER the run (queue-only rule) ---
portfolio = system.portfolio_handler.get_portfolio(portfolio_id)
```
**Signatures verified:** `TradingSystem.__init__(self, exchange='binance', start_date=None, end_date='', timeframe='1d', csv_paths: dict[str, str|Path]|None=None, ...)` (`backtest_trading_system.py:46-52`). `csv_paths` is the contrived-CSV seam (D-09; default `None`→golden, oracle-dark). `add_portfolio(user_id, name, exchange, cash, portfolio_config=None) -> PortfolioId` (`portfolio_handler.py:124`). `add_strategy(strategy)` (`strategies_handler.py:141`).

**Exact-diff mechanic to reuse VERBATIM** (`tests/integration/test_backtest_oracle.py:155-238`) — the identity-vs-numeric column split, `assert_frame_equal(check_exact=True, check_like=True)`, NO float tolerance (D-08). Auto-derive the numeric set from the golden header so each scenario freezes whatever columns it has:
```python
import pandas.testing as pdt
# trades: identity columns EXACT, then auto-derived numeric remainder EXACT
pdt.assert_frame_equal(fresh[_TRADE_IDENTITY], gold[_TRADE_IDENTITY], check_exact=True, check_like=True)
_numeric = [c for c in gold.columns if c not in _TRADE_IDENTITY]
pdt.assert_frame_equal(fresh[_numeric], gold[_numeric], check_exact=True, check_like=True)
# summary.json: whole "metrics" dict EXACT + key-by-key scalar compare
assert fresh_summary["metrics"] == golden_summary["metrics"]
```
Identity columns from the oracle (`test_backtest_oracle.py:39-50`): trades `["entry_date","exit_date","side","pair"]`, equity `["timestamp"]`. Sort before compare: `.sort_values(_TRADE_KEY_COLUMNS).reset_index(drop=True)` (lines 126-131).

**In-process module-load pattern for `scenario.py`** (`test_backtest_oracle.py:71-82`) — copy `_load_run_backtest_module` verbatim, generalized to a unique per-leaf module name (avoids two leaves' `scenario.py` shadowing — Pitfall 4):
```python
spec = importlib.util.spec_from_file_location("run_backtest", _RUN_BACKTEST)
assert spec is not None and spec.loader is not None, f"cannot load {_RUN_BACKTEST}"
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
```

**`--freeze` option** — new (`pytest_addoption` + `request.config.getoption("--freeze")`); no analog exists in-repo (env-var rejected, RESEARCH alt-table). DIFF by default; WRITE goldens only under `--freeze` (D-13). Indentation: **4 spaces** (matches `tests/conftest.py`).

**OPEN Q1 (record, do not block canary):** `TradingSystem(exchange="csv")` ignores fee/slippage — the seam for applying `spec.exchange` is `system.execution_handler.exchanges['simulated'].update_config(**kwargs)` post-construction, pre-`run()` (`simulated.py:539`). Canary uses defaults; Phase 7 needs it.

---

### `tests/e2e/strategies/single_market_buy.py` (strategy — event-driven)

**Analog:** `itrader/strategy_handler/SMA_MACD_strategy.py` + `itrader/strategy_handler/base.py::Strategy`.

**Strategy ABC contract** (`base.py:26-32, 76-104`) — subclass `Strategy`, call `super().__init__` with REQUIRED `sizing_policy`, implement `generate_signal(ticker, bars) -> SignalIntent | None`, use the `self.buy()`/`self.sell()` sugar. `max_window` (default 0, `base.py:57`) gates warmup — set to 0 for no-warmup canary.
```python
def __init__(self, name, timeframe, tickers, order_type="market", *,
             sizing_policy, direction=TradingDirection.LONG_ONLY,
             allow_increase=False, max_positions=1, sltp_policy=None): ...
@abstractmethod
def generate_signal(self, ticker: str, bars: pd.DataFrame) -> SignalIntent | None: ...
def buy(self, ticker, sl=None, tp=None, exit_fraction=Decimal("1")) -> SignalIntent: ...
```

**Concrete-strategy construction to copy** (`SMA_MACD_strategy.py:21-67`) — the `super().__init__` call with the real sizing policy, plus the `len(bars) < self.max_window: return None` warmup guard. For the canary, replace the SMA/MACD logic with a pinned fire-bar:
```python
super().__init__("SMA_MACD", timeframe, list(tickers or []),
                 sizing_policy=FractionOfCash(Decimal("0.95")),
                 direction=TradingDirection.LONG_ONLY, allow_increase=False)
# canary: return self.buy(ticker) if len(bars) == self.fire_on_bar else None
```
**Imports verified:** `from itrader.core.sizing import FractionOfCash, SignalIntent, TradingDirection` (`sizing.py:85` `FractionOfCash`, `:212` `SignalIntent`; `TradingDirection` co-located), `from itrader.strategy_handler.base import Strategy`. Indentation: **tabs** (both analog handler modules use tabs; match if placed alongside, but new file under `tests/` may use 4 spaces — keep internally consistent and warning-clean). One MARKET entry fills next-bar-open (the `attach_slippage` docstring convention, `run_backtest.py:71-78`).

---

### `tests/e2e/smoke/single_market_buy/scenario.py` (config/spec — transform)

**Analog:** `scripts/run_backtest.py:53-60` pinned-constant block + `itrader/config/exchange.py:136` (`ExchangeConfig`) + `itrader/config/portfolio.py:103` (`PortfolioConfig`).

**Pinned-knobs pattern** (`run_backtest.py:53-60`) — the canary's `ScenarioSpec` mirrors these exact knobs (D-03 reuses REAL config types, not a parallel schema):
```python
DATASET = "data/..."; START_DATE = "2018-01-01"; END_DATE = "2026-06-03"
CASH = 10_000; TICKER = "BTCUSD"; TIMEFRAME = "1d"
```
**Real config models to reference** (D-03): `ExchangeConfig` (`config/exchange.py:136`; `FeeModelType` at `:26`, `SlippageModelType` at `:36`, `FeeModelConfig` at `:45`, `SlippageModelConfig` at `:70`), `PortfolioConfig` (`config/portfolio.py:103`). Spec fields: `list[strategy]`, `list[PortfolioConfig]`, `ExchangeConfig`, data path(s), window — Lists support Phase 9 multi-entity (D-03). The VERIFY hand-derivation note lives in this file's module docstring (D-13; mirrors `tests/golden/REFREEZE-*.md`). Indentation: **4 spaces**.

---

### `tests/e2e/smoke/single_market_buy/test_scenario.py` (test — request-response)

**Analog:** the one-liner shape only — D-01 mandates `def test_x(run_scenario): run_scenario(HERE)`. Do NOT copy `test_backtest_oracle.py`'s body (that's the oracle's full diff; the harness owns the diff now). The leaf test is a trivial delegating call. `HERE = pathlib.Path(__file__).resolve().parent`.

---

### `tests/e2e/smoke/single_market_buy/bars.csv` + `golden/` (test data / fixtures — file-I/O)

**Analog:** golden Binance-kline schema (`csv_store.py:155`) + the frozen `tests/golden/` artifacts.

**Required CSV header** (`csv_store.py:155`, validated — missing columns raise, T-06-04):
```python
expected_cols = ['Open time', 'Open', 'High', 'Low', 'Close', 'Volume']
```
Hand-write a tiny contrived CSV in this schema (D-09/D-11 — contrived bars, real store path, NOT a real-data slice). `golden/` default freeze = `trades.csv` + `summary.json` (D-06); `equity.csv` opt-in. Trade CSV columns + `float_format="%.10f"` come from the shared assembly (see below) so they match the oracle byte-for-byte.

---

### `itrader/reporting/summary.py` (library / serialization assembly — transform) — D-16, HIGH RISK

**Analog:** `itrader/reporting/frames.py` (the proven verbatim-relocation PRECEDENT) — its docstring (`frames.py:1-15`) states "function bodies are character-identical to the run_backtest.py originals." **Source bodies:** `scripts/run_backtest.py:70-151`.

**The three functions to move VERBATIM** (`run_backtest.py:70-151`) — move bodies character-identical; parameterize ONLY the module constants `build_summary` closes over:
```python
def attach_slippage(trades, closes) -> trades:          # run_backtest.py:70-103 — pure, no constants
def build_metrics_block(equity, trades) -> dict:        # run_backtest.py:106-123 — pure, reads equity["total_equity"]
def build_summary(portfolio, trades) -> dict:           # run_backtest.py:126-151 — CLOSES over TICKER/TIMEFRAME/START_DATE/END_DATE/CASH
```
`build_summary` is the ONLY one with closed-over constants (`run_backtest.py:142-146` reads `TICKER`/`TIMEFRAME`/`START_DATE`/`END_DATE`/`CASH`). New signature: `build_summary(portfolio, trades, *, ticker, timeframe, start_date, end_date, starting_cash) -> dict`. `run_backtest.py` passes its pins verbatim; the harness passes spec values.

**Byte-load-bearing constants to keep unchanged** (Pitfall 1): `FLOAT_FORMAT = "%.10f"` (`run_backtest.py:63`), `SLIPPAGE_COLUMNS = ["slippage_entry","slippage_exit"]` (`:67`). **Keep serialization (`to_csv`/`json.dump(..., indent=2, sort_keys=True)`, `run_backtest.py:197-202`) IN `run_backtest.py`** — only the ASSEMBLY moves. **Money boundary preserved verbatim:** `float(portfolio.cash)` / `float(portfolio.total_equity)` (`run_backtest.py:147-148`) — the single Decimal→float edge for summary.json; no arithmetic before the cast.

**Purity contract** (copy `frames.py:11-15` / `metrics.py:1-31` docstring discipline): pandas + stdlib imports only, `portfolio`/`trades` duck-typed, zero handler imports. Indentation: **4 spaces** (matches `frames.py`). **mypy --strict clean** — it's in `files = ["itrader"]`.

**MANDATORY proof gate:** `tests/integration/test_backtest_oracle.py` must re-run GREEN after extraction (`make backtest && poetry run pytest tests/integration/test_backtest_oracle.py -x`). It asserts (verified `test_backtest_oracle.py:137-238`): trade count + `(entry/exit/side/pair)` EXACT, equity `timestamp` grid + numeric EXACT, all numeric trade columns incl. slippage EXACT, `final_cash`/`final_equity`/`total_realised_pnl`/`trade_count` EXACT, whole `metrics` dict EXACT. Sequence this task FIRST, before any harness code depends on the new module.

---

### `scripts/run_backtest.py` (MODIFY — oracle generator, must stay oracle-dark)

Replace the local `attach_slippage`/`build_metrics_block`/`build_summary` defs (`:70-151`) with an import from `itrader.reporting.summary` and pass the pinned constants explicitly to `build_summary(..., ticker=TICKER, timeframe=TIMEFRAME, start_date=START_DATE, end_date=END_DATE, starting_cash=CASH)`. Add to the existing import block (`:33-50`, alongside `from itrader.reporting.frames import ...`). Keep `:154-214` (`main`, serialization) byte-identical. The in-process loader (`test_backtest_oracle.py:78`) still resolves `main` — verified `itrader` is on the package path.

---

### `tests/conftest.py` (MODIFY — collection hook)

**Self-analog** — extend `pytest_collection_modifyitems` (`tests/conftest.py:42-56`) with one branch, matching the existing `unit`/`integration` style EXACTLY:
```python
for item in items:
    parts = pathlib.Path(str(item.fspath)).parts
    if "unit" in parts:
        item.add_marker(pytest.mark.unit)
    if "integration" in parts:
        item.add_marker(pytest.mark.integration)
        item.add_marker(pytest.mark.slow)
    if "e2e" in parts:                       # NEW — NOT slow (D-15)
        item.add_marker(pytest.mark.e2e)
```
Indentation: **4 spaces** (this file). Do NOT register the marker here (conftest only applies — see file docstring `:11-13`).

---

### `pyproject.toml` (MODIFY — marker registration, the SINGLE home)

**Self-analog** — add one line to the `markers` list (`pyproject.toml:61-65`), matching the existing entry format:
```toml
markers = [
    "unit: Unit test — drives ONE collaborating component (tests/unit/)",
    "integration: Integration test — asserts cross-component interaction (tests/integration/)",
    "slow: Slow running test (the full-engine integration runs)",
    "e2e: End-to-end scenario — full engine on a (strategy, data) pair vs frozen goldens (tests/e2e/)",
]
```
`--strict-markers` (`:52`) requires registration here. `filterwarnings = ["error", ...]` (`:71-75`) — scenarios must run warning-clean (Pitfall 2; reuse the already-clean `frames.py`/`metrics.py` idioms). `make test` (`pytest tests/ -v`, no `-m`) includes e2e automatically.

---

### `Makefile` (MODIFY — focused bucket target)

**Self-analog** — add `test-e2e` mirroring `test-unit`/`test-integration` (`Makefile:31-37`), and add `test-e2e` to `.PHONY` (`:6`):
```makefile
test-e2e:
	@echo "🌐 Running E2E scenario tests..."
	poetry run pytest tests/ -v -m "e2e"
```
Indentation: **tabs** (Makefile recipes require tab-indented commands). `make test` (`:27-29`) unchanged — keeps running everything (D-15).

---

### `tests/unit/core/test_enums.py` (MODIFY — FL-03 dead-skip removal)

**Self-analog** — `FillStatus.EXECUTED` now exists (`itrader/core/enums/execution.py:59`), so the skip at `test_enums.py:31-32` is dead. Delete the `if fill_status is None: pytest.skip(...)` branch in `_fill_status_or_skip` (`:24-33`) so the two now-passing assertions run. The 4-gate CLEANUP-STANDARD checklist applies (touched-path, behavior-preserving, no oracle re-baseline, reviewed).

## Shared Patterns

### Exact golden diff (no tolerance)
**Source:** `tests/integration/test_backtest_oracle.py:155-238`
**Apply to:** `tests/e2e/conftest.py` (the `run_scenario` diff loop)
`pdt.assert_frame_equal(fresh[cols], gold[cols], check_exact=True, check_like=True)` with identity/numeric column split; summary via whole-dict + key-by-key compare. No `rtol`/`atol` (D-08; the oracle abandoned tolerance, `:53-65`).

### Deferred-import in test fixtures
**Source:** `tests/integration/conftest.py:61-62` (and the file docstring `:48-52`)
**Apply to:** `tests/e2e/conftest.py`
Import `TradingSystem` INSIDE the inner fixture function so `--collect-only` stays clean even when downstream scenarios are not yet wired.

### Verbatim-relocation discipline (oracle-dark)
**Source:** `itrader/reporting/frames.py:1-15` docstring (the proven precedent)
**Apply to:** `itrader/reporting/summary.py` + `scripts/run_backtest.py`
Move function bodies character-identical; parameterize only closed-over module constants; guard with the existing oracle byte-exact gate.

### Folder-derived marker auto-marking
**Source:** `tests/conftest.py:42-56` + `pyproject.toml:61-65`
**Apply to:** the `e2e` marker (conftest applies, pyproject registers — never the reverse, `--strict-markers`)

### Decimal→float only at serialization edge
**Source:** `scripts/run_backtest.py:147-148`, `frames.py` / `metrics.py` purity docstrings
**Apply to:** `itrader/reporting/summary.py`
`float()` ONLY at the summary.json boundary, no arithmetic on the Decimal first (CLAUDE.md money policy).

### Warning-clean under `filterwarnings=["error"]`
**Source:** `itrader/reporting/metrics.py:27-31` (pandas-2-safe idioms: `.iloc`, whole-column construction, guarded denominators)
**Apply to:** all new harness + strategy + assembly code (Pitfall 2)

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| (none) | — | — | Every Phase-4 file maps to an existing in-repo pattern. The only NOVEL element is the `--freeze` `pytest_addoption` flag (a standard pytest API, no in-repo precedent; RESEARCH recommends it over an env var). The work is generalization + relocation, not invention. |

## Metadata

**Analog search scope:** `tests/integration/`, `tests/`, `scripts/`, `itrader/reporting/`, `itrader/strategy_handler/`, `itrader/config/`, `itrader/trading_system/`, `itrader/price_handler/store/`, `pyproject.toml`, `Makefile`
**Files scanned (read in full or grepped):** `tests/integration/conftest.py`, `tests/conftest.py`, `tests/integration/test_backtest_oracle.py`, `scripts/run_backtest.py`, `itrader/strategy_handler/base.py`, `SMA_MACD_strategy.py`, `itrader/reporting/frames.py`, `metrics.py`, `Makefile`, `pyproject.toml`, `tests/unit/core/test_enums.py`, `itrader/trading_system/backtest_trading_system.py` (grep), `itrader/price_handler/store/csv_store.py` (grep), `itrader/config/{exchange,portfolio}.py` (grep), `itrader/core/sizing.py` (grep)
**Pattern extraction date:** 2026-06-09
