# Phase 1: M1 — Ignition + Lock the Oracle - Pattern Map

**Mapped:** 2026-06-04
**Files analyzed:** 11 (5 NEW files, 4 NEW code regions / edits, 2 build/config files)
**Analogs found:** 11 / 11

> M1 is an **ignition + wiring** phase, not a feature build. Almost every "new" thing
> has a close in-tree analog to copy from. The biggest risk is convention drift
> (tabs vs spaces) and frame-shape mismatch. This map pins each new file/region to the
> exact analog + line range, and flags the per-file indentation rule.

---

## File Classification

| New/Modified File or Region | Role | Data Flow | Closest Analog | Match Quality |
|------------------------------|------|-----------|----------------|---------------|
| `scripts/run_backtest.py` (NEW) | entry-point / run script | batch / request-response | `itrader/trading_system/backtest_trading_system.py` `run()` + notebook usage | role-match |
| `Makefile` `make backtest` target (EDIT) | config / build | — | existing `test-*` targets (`Makefile:27-66`) | exact |
| CSV/offline branch in `itrader/price_handler/data_provider.py` (NEW region) | service (price feed) | file-I/O → in-memory | CCXT path: `data_provider.load_data` + `CCXT._format_data` (`CCXT.py:54-81`) | role+flow match |
| Fraction-of-cash sizing in `order_manager.py::_create_primary_order` (NEW region) | service (order/risk) | transform (signal→order) | existing `_create_primary_order` body (`order_manager.py:218-285`); `FixedPositionSizer.size_order` (informative, NOT the seam) | exact (same fn) |
| `record_metrics` per-Portfolio fix in `backtest_trading_system.py` (EDIT) | engine / run loop | event-driven (per-tick) | `PortfolioHandler.get_active_portfolios()` (`portfolio_handler.py:220`) + `Portfolio.record_metrics` (`portfolio.py:294`) | exact |
| Oracle serialization (trade log / equity / summary) (NEW region in run script) | reporting / serialization | transform → file-I/O | `Position.to_dict()` (`position.py:244`), `PortfolioSnapshot` (`metrics_manager.py:29`), `StatisticsReporting._prepare_data` (`statistics.py:52`, as cautionary reference) | role-match |
| `test/conftest.py` (NEW) | test infra | collection hook + fixtures | RESEARCH.md Pattern 2 (pytest docs); fixture style from `test/test_strategy/test_strategy.py` | role-match |
| `test/test_smoke/test_backtest_smoke.py` (NEW) | test (unit) | request-response | `test/test_strategy/test_strategy.py` structure | role-match |
| `test/test_integration/test_backtest_oracle.py` (NEW) | test (integration) | file-I/O diff | `test/test_strategy/test_strategy.py` + `pandas` frame-equal | role-match |
| `test/golden/{trades,equity}.csv + summary.json` (NEW data) | test fixture data | — | output of the oracle serialization (no code analog — generated) | n/a (data) |
| `itrader/config/__init__.py` re-export + `SMA_MACD_strategy.py` `.iloc`/`fillna` (EDITS) | bugfix | — | see Shared Patterns / per-edit notes | exact |

---

## Pattern Assignments

### `scripts/run_backtest.py` (NEW — entry-point, batch)

**Analog:** `itrader/trading_system/backtest_trading_system.py` — the engine + `run()` already exist. The script is a thin committed driver that constructs `TradingSystem`, adds the `SMA_MACD` strategy + a $10k portfolio, runs, then serializes the oracle.

**Indentation:** SPACES (new top-level script — match `config/`/newer-module convention, 4-space). Do NOT use tabs here.

**Construction pattern** to copy (`backtest_trading_system.py:25-66`): `TradingSystem(exchange=..., start_date=..., end_date=...)` wires the shared `global_queue` and all handlers in `__init__`. The script must:
- pin `start_date`/`end_date` = 2018-01-01 → 2026-06-03 explicitly (D-02)
- select the CSV/offline feed (pass an `exchange='csv'` style flag or a `csv_path` arg that the new `data_provider` branch keys off — see CSV branch below)
- add the portfolio with `cash=10_000` and the `SMA_MACD` strategy on `'1d'` subscribed to `BTCUSD` (D-03/D-04/D-06)
- call `system.run(print_summary=False)` (avoid `print_summary=True` — it hits the broken `StatisticsReporting._prepare_data`, Pitfall 5)

**Run-loop reference** (`backtest_trading_system.py:88-106`): the loop already does `for ping_event in self.ping: global_queue.put(...); event_handler.process_events(); record_metrics(...)`. The script does NOT re-implement the loop — it calls `run()`.

**Queue-only rule:** the script never calls handler methods across domains; it only constructs the system and reads result state (`portfolio.closed_positions`, snapshots) AFTER the run.

---

### `Makefile` `make backtest` target (EDIT — build)

**Analog:** existing test targets (`Makefile:27-66`). Copy the exact two-line form:

```makefile
backtest:
	@echo "🚀 Running backtest oracle generator..."
	poetry run python scripts/run_backtest.py
```

**Indentation:** TAB-indented recipe body (Makefile requirement). Add `backtest` to the `.PHONY` line (`Makefile:6`). Match the existing emoji-echo + `poetry run` style.

---

### CSV/offline branch in `itrader/price_handler/data_provider.py` (NEW region)

**Analog (flow):** `CCXT._format_data` (`CCXT.py:54-81`) defines the EXACT frame shape downstream expects. **Analog (placement):** `PriceHandler.load_data` (`data_provider.py:65-91`) is the method that populates `self.prices[ticker.upper()]`.

**Indentation:** TABS (this module uses tabs throughout — `data_provider.py` is tab-indented).

**Frame shape to reproduce EXACTLY** (copy from `CCXT.py:66-71`):
```python
data.columns = ['date', 'open', 'high', 'low', 'close', 'volume']   # lowercase
data = data.set_index('date')
data.index = pd.to_datetime(data.index, ..., utc=True)              # tz-aware
data.index = data.index.tz_convert(<TIMEZONE>)                       # consistent tz
data = data.astype(float)
```
The golden CSV header is `Open time, Open, High, Low, Close, Volume, Close time, ...` — map `Open time→date`, `Open/High/Low/Close/Volume→lowercase`, parse `'YYYY-MM-DD HH:MM:SS.ffffff UTC'`, drop the trailing Binance-kline columns, slice 2018→2026 (D-02).

**Skip SqlHandler/CCXT (D-07):** today `__init__` builds `self.sql_handler = SqlHandler()` (`data_provider.py:55`) and `_init_exchange` only knows `'binance'` (`data_provider.py:307-317`). The CSV branch must guard these so a `csv` exchange value:
- in `__init__`: does NOT construct `SqlHandler()` and does NOT call CCXT `_init_exchange`
- in `load_data`: reads the local CSV into `self.prices[ticker]` and returns — never touches `sql_handler.get_symbols_SQL()` / `exchange.download_data`

**TZ consistency (Pitfall 6):** `backtest_trading_system.py:85` does `ping.set_dates(next(iter(self.price_handler.prices.items()))[1].index)` — the ping vector is derived from THIS frame's index. So the CSV branch's tz-aware index IS the ping clock by construction; keep one tz, don't double-convert. `get_bar` does `self.prices[ticker].loc[time]` (`data_provider.py:169`) — lookups match only if index tz == ping tz.

---

### Fraction-of-cash sizing in `order_manager.py::_create_primary_order` (NEW region)

**Analog (same function):** `order_manager.py:218-285` — `_create_primary_order`. The seam replaces the `quantity=signal_event.quantity` passthrough.

**Indentation:** This file is mixed — `_create_primary_order` body uses TABS for control flow but the SL/TP helpers use 4-space (e.g. `order_manager.py:287` signature). **Match the exact indentation of the lines you edit inside `_create_primary_order`** (tabs in the `try`/`if order_type_str ==` block, `order_manager.py:234-265`).

**Where to inject (D-08/D-09):** before the `Order.new_order(signal_event, exchange)` call at `order_manager.py:238` (MARKET path). In scope at this point: `signal_event.portfolio_id`, `signal_event.price`, and `self.portfolio_handler.get_portfolio(pid)`.

```python
portfolio = self.portfolio_handler.get_portfolio(signal_event.portfolio_id)
qty = (0.95 * portfolio.cash) / signal_event.price      # D-08 fraction-of-cash, fractional BTC
```

**CRITICAL — `Order.new_order` reads `signal.quantity` internally** (`order.py:115-147`, line 143 `signal.quantity`). The MARKET path does NOT take a `quantity` arg — it pulls from the signal. So the seam must set the qty on the signal (or a copy) BEFORE constructing the order, OR add an overriding `quantity` param to the factory. The LIMIT/STOP branches (`order_manager.py:240-260`) DO pass `quantity=signal_event.quantity` explicitly — those would take `quantity=qty` directly. Planner picks the non-mutating approach; SMA_MACD only uses MARKET (sl=0/tp=0 per RESEARCH A5), so the MARKET path is the one that must carry the qty.

**Informative-only analog (NOT the seam):** `FixedPositionSizer.size_order` (`fixed_sizer.py:8-14`) sets `initial_order.quantity = self.default_quantity`. D-09 LOCKS sizing OUT of the `position_sizer/` layer — do not edit sizers.

---

### `record_metrics` per-Portfolio fix in `backtest_trading_system.py` (EDIT)

**Bug:** `backtest_trading_system.py:102` calls `self.portfolio_handler.record_metrics(ping_event.time)` — `PortfolioHandler` has no such method.

**Analog / fix:** `record_metrics` lives on `Portfolio` (`portfolio.py:294`, delegates to `metrics_manager.record_snapshot(time)`). Iterate portfolios via the existing `PortfolioHandler.get_active_portfolios()` (`portfolio_handler.py:220`, returns `List[Portfolio]`):

```python
for portfolio in self.portfolio_handler.get_active_portfolios():
    portfolio.record_metrics(ping_event.time)
```

**Indentation:** TABS (`backtest_trading_system.py` is tab-indented). `record_snapshot` uses the passed bar `time` (deterministic) — its `datetime.now()` default (`metrics_manager.py:130-131`) is never hit because the loop always passes `ping_event.time`.

---

### Oracle serialization (NEW region in `scripts/run_backtest.py`)

**Indentation:** SPACES (lives in the new script).

**Trade log** — source `portfolio.closed_positions` (`portfolio.py:250`) → `Position.to_dict()` (`position.py:244-265`). Deterministic columns to keep (D-12): `entry_date, exit_date, side, net_quantity, avg_price, avg_bought, avg_sold, total_bought, total_sold, realised_pnl, pair`. EXCLUDE `position_id`, `current_price`, `unrealised_pnl` (volatile/non-deterministic until M2). Identify trades by `(entry_date, exit_date, side)`.

**Equity curve** — source the `PortfolioSnapshot` list (`metrics_manager.py:29` dataclass: `timestamp, total_equity, cash_balance, positions_value, unrealized_pnl, realized_pnl, total_pnl, open_positions_count, portfolio_return`). Build the frame directly from snapshots — do NOT route through `StatisticsReporting._prepare_data`.

**Summary JSON** — final cash + a minimal deterministic metric set (trade count, total realised PnL, final equity). Keep derived ratios minimal (M5 re-baseline owns sharpe/sortino/cagr — some of that math is M5-buggy).

**Serialization mechanic (Don't Hand-Roll):** `pandas.DataFrame.to_csv(float_format=...)` with a pinned `float_format` for cross-platform repr stability; stdlib `json` for the summary; `pathlib` for `output/` vs `test/golden/` paths.

**CAUTION (Pitfall 5):** `StatisticsReporting._prepare_data` (`statistics.py:52-73`) reads `portfolio.metrics` which does NOT exist (`hasattr(Portfolio,'metrics') == False`). It is shown here ONLY as the structural reference for what a positions/equity frame looks like (`statistics.py:62-73`) — the capture must source from snapshots/`closed_positions` directly, NOT call `_prepare_data`.

---

### `test/conftest.py` (NEW — test infra)

**Indentation:** SPACES (new test infra; pytest convention is 4-space, and conftest is not a tab-handler module).

**Auto-marking hook (D-14)** — copy RESEARCH.md Pattern 2 verbatim (`pytest_collection_modifyitems` mapping dir→marker). Directory→marker map must cover the existing dirs: `test_portfolio_handler/test_positions/test_transaction → portfolio`, `test_events → events`, `test_order_handler → orders`, `test_execution_handler → execution`, `test_strategy → strategy`, `test_integration → integration` (+`slow`), `test_smoke → unit`. Works on the legacy `unittest.TestCase` items at collection time — zero edits to the 30 legacy files.

**Shared fixtures (D-15):** `global_queue` (a `queue.Queue` per the constructor convention), golden-file path fixtures (`pathlib` to `test/golden/`), and a backtest-engine factory fixture (constructs a `TradingSystem` with the CSV feed). Fixture/test style reference: `test/test_strategy/test_strategy.py` (uses `queue.Queue`, `BarEvent`/`SignalEvent` from `itrader.events_handler.event`).

---

### `test/test_smoke/test_backtest_smoke.py` (NEW — unit)

**Analog (style):** `test/test_strategy/test_strategy.py` — note the 30 legacy files are `unittest.TestCase`, BUT new tests may be pytest-native (function style). Either works under the collector; pytest-native functions are cleaner for new files. Match whatever the planner standardizes; the auto-marking applies regardless.

**Behavior (D-16):** import → construct `TradingSystem` (CSV feed) → run a handful of bars → assert run completes AND ≥1 trade with non-zero quantity (`portfolio.closed_positions` non-empty, qty > 0). Carries `unit` marker (via `test_smoke` path). This is the gate that catches the FutureWarning hard-error (Pitfall 3) and the empty-bars/zero-trade tz mismatch (Pitfall 6).

**Indentation:** SPACES.

---

### `test/test_integration/test_backtest_oracle.py` (NEW — integration + slow)

**Analog (style):** `test/test_strategy/test_strategy.py`; diff mechanic from RESEARCH "Don't Hand-Roll" (load both CSVs to DataFrame, assert frame-equal on deterministic columns — D-12/D-13, NO float tolerance).

**Behavior (D-16):** full 2018→2026 run → write `output/` → diff fresh `output/{trades,equity}.csv` + `summary.json` against committed `test/golden/`. Behavioral exact (trade timing/sides/sequence) + numerical exact. Carries `integration` + `slow` markers (via `test_integration` path auto-marking).

**Indentation:** SPACES.

---

## Shared Patterns

### Queue-only cross-domain communication
**Source:** all handler constructors take `global_queue` (`backtest_trading_system.py:42-66`).
**Apply to:** `scripts/run_backtest.py` (construct the system, never call across domains), the CSV branch (populate `self.prices`, emit nothing directly), the sizing seam (emit `OrderEvent` via the existing `OperationResult.order_events` path, `order_manager.py:271-277`). New files MUST NOT add direct cross-handler calls.

### Config name-resolution fix (M1-01) — re-export pattern
**Source:** flat `itrader/config.py` defines `Config`, `TIMEZONE` (`config.py:59`), `FORBIDDEN_SYMBOLS` (`config.py:33`); the package `itrader/config/__init__.py` shadows it and does NOT export them.
**Apply to (recommended minimal fix, RESEARCH Q1 / A2):** add re-exports of `FORBIDDEN_SYMBOLS`, `TIMEZONE`, `Config` to `itrader/config/__init__.py` (extend the imports block at the top + the `__all__` list at `config/__init__.py:82-145`) so `from itrader.config import FORBIDDEN_SYMBOLS` (used at `CCXT.py:8`) and `config.TIMEZONE` (used at `CCXT.py:71`, `data_provider.py:97`, `time_parser.py`) resolve.
**Indentation:** SPACES (`config/` package is 4-space). Match `config/__init__.py` exactly.

### TIMEZONE access fix (M1-02)
**Source:** `config.TIMEZONE` raises `AttributeError` because the singleton is `{}`. Flat `config.py:59` has `TIMEZONE = 'Europe/Paris'`.
**Apply to:** the four call sites (`CCXT.py:71`, `data_provider.py:97`, `time_parser.py:9,166`). The re-export above provides `TIMEZONE` as a module constant; the CSV branch's index tz MUST match whatever value flows to `get_bar`/ping (keep one tz — Pitfall 6). Source ping dates and CSV index from the same frame.

### Strategy indexing/fillna fix (M1-04)
**Source / target:** `itrader/strategy_handler/SMA_MACD_strategy.py`.
**Apply:** `short_sma[-1]`/`long_sma[-1]` → `.iloc[-1]` (mandatory — FutureWarning is promoted to a hard error under `filterwarnings=["error"]`, Pitfall 3); `fillna='False'` (truthy string) → `fillna=False`.
**Indentation:** TABS (handler/strategy module).
**Anti-pattern (do NOT do):** adding `FutureWarning` to the pyproject ignore list to dodge the error. Fix the code.

### Logging + naming conventions (all new code)
**Source:** every handler binds `self.logger = get_itrader_logger().bind(component="X")` (e.g. `data_provider.py:57`, `backtest_trading_system.py:35`).
**Apply to:** new code in `data_provider` CSV branch and the run script — use the same bound-logger pattern, `on_<event>`/`get_<thing>`/`_<private>` naming, `snake_case` files.

---

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `test/golden/{trades,equity}.csv`, `summary.json` | test fixture data | — | Generated artifact (promoted from a blessed `output/` run, D-11), not code — no analog to copy. Schema = the oracle serializer's output columns. |
| `output/` directory | runtime artifact dir | — | Already covered by `.gitignore` (`.gitignore:35` `output`); no new ignore entry strictly needed, but confirm the trailing-slash form matches. |

---

## Metadata

**Analog search scope:** `itrader/price_handler/`, `itrader/order_handler/`, `itrader/trading_system/`, `itrader/portfolio_handler/`, `itrader/reporting/`, `itrader/config/` (+ flat `config.py`), `itrader/strategy_handler/position_sizer/`, `test/`, `Makefile`, `.gitignore`.
**Files scanned:** data_provider.py, CCXT.py, order_manager.py, order.py, backtest_trading_system.py, statistics.py, metrics_manager.py, position.py, portfolio_handler.py, config/__init__.py, config.py (flat), fixed_sizer.py, test_strategy.py, Makefile.
**Pattern extraction date:** 2026-06-04

**Indentation cheat-sheet (per file — load-bearing, CLAUDE.md "match the file"):**
- TABS: `data_provider.py` (CSV branch), `order_manager.py` `_create_primary_order` body, `backtest_trading_system.py`, `SMA_MACD_strategy.py`, `Makefile` recipes.
- SPACES (4): `scripts/run_backtest.py`, `test/conftest.py`, new test files, `itrader/config/__init__.py` re-export.
