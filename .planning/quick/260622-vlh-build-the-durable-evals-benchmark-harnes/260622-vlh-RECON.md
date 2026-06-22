# Recon — API facts for the evals/ harness (resolves PERF-BASELINE §9 risks)

**Gathered:** 2026-06-22 (pre-planning, by orchestrator). All signatures verified against the live codebase. Treat as LOCKED facts; do not re-investigate.

## Feasibility (probed)
- **Binance reachable** via `ccxt` 4.5.56 (`ccxt.binance({'enableRateLimit': True})`, `fetch_ohlcv('BTC/USDT','5m',since=…,limit=1000)` returns real candles). Network fetch is feasible.
- `data/` is **NOT gitignored** → fetched CSVs will be committed (consistent with existing `data/BTCUSD_1d_ohlcv_2018_2026.csv`).
- This task runs **on the main tree (no worktree isolation)** — network fetch + large CSV writes + editable-install `.venv` shadowing make worktrees fragile here. Current branch: `initialise-v1.5-milestone`.

## 1. Strategy base API — `itrader/strategy_handler/base.py`
- Concrete strategies implement: `generate_signal(self, ticker: str) -> SignalIntent | None` (line ~422). Indicators declared in `init()` (see SMA_MACD).
- Sugar factories (all take `sl=`, `tp=`, `exit_fraction: Decimal = Decimal("1")`):
  - `buy(ticker, sl=None, tp=None, ...)` / `sell(...)` — MARKET
  - `buy_limit(ticker, *, price, sl=None, tp=None, ...)` / `sell_limit(...)` — price keyword-only
  - `buy_stop(ticker, *, price, ...)` / `sell_stop(...)` — price keyword-only
  - `sl`/`tp` coerced via `to_money()` (string-path Decimal). Declaring both → bracket/OCO.
- Direction enum: `itrader/core/enums/trading.py::TradingDirection` = {`LONG_ONLY`, `LONG_SHORT`, `SHORT_ONLY`}. Strategy sets class attr `direction`.
- Pyramiding gate: class attr `allow_increase: bool = False` (base.py ~line 105). **Set `True` to pyramid** (Strategy C).
- Sizing policies — `itrader/core/sizing.py` (frozen dataclasses): `FractionOfCash(fraction: Decimal, step_size=None)`, `FixedQuantity(qty, step_size=None)`, `RiskPercent(risk_pct, step_size=None)`, `LeveredFraction(fraction, step_size=None)`. Strategy sets `sizing_policy`.
- Fan-out: `strategy.subscribe_portfolio(portfolio_id)` (idempotent). One intent → SignalEvent to every subscribed portfolio; sizing resolved per-portfolio.

## 2. Reference strategy — `itrader/strategy_handler/strategies/SMA_MACD_strategy.py`
- `init()`: SMA(50)/SMA(100) + MACD hist (6/12/3). `generate_signal`: `buy()` on `crossover(macd_hist,0)` while `short_sma>long_sma`; `sell()` on `crossunder(...)`. Sizing `FractionOfCash(Decimal("0.95"))`, `LONG_ONLY`. Reuse this signal where the roster says so; change only order plumbing.

## 3. §9 RISK — cancel/modify (Strategy B): **REACHABLE, but not from `generate_signal()`**
- APIs exist: `OrderManager.modify_order(order_id, new_price=None, new_quantity=None, portfolio_id=None, reason=…)` and `cancel_order(order_id, portfolio_id=None, reason=…)` → delegate to `LifecycleManager`.
- A strategy **cannot** reference/cancel its own resting order from inside `generate_signal()` (intent is order-ref-free).
- **Reachable via the `on_tick(system, time_event)` hook** that `run()` accepts: `system.order_handler.modify_order(order_id, new_price=…)` / `cancel_order(order_id)`.
- **Design implication for B:** the re-price/cancel-unfilled-limit logic must live in the **runner's `on_tick` hook** (tracking resting order IDs), not in the pure strategy. Strategy B emits `buy_limit(price=…)`; the runner re-prices/cancels unfilled limits each bar. Document this clearly so the cancel/modify coverage claim is honest.

## 4. §9 RISK — pyramiding (Strategy C): **REACHABLE**
- Admission gate `AdmissionManager._enforce_position_admission()`: if open long and `allow_increase=False` → BUY rejected (`OrderTriggerSource.ADMISSION_INCREASE`). With `allow_increase=True`, repeated same-direction `buy()` falls through to sizing and **averages in**.
- Rejections then come from **cash** (`CASH_RESERVATION`, → `FillEvent(REFUSED)` → mirror reconcile), NOT a duplicate guard. So: set `allow_increase=True`, size with no cash headroom cap, let it over-extend so rejections fire for free.

## 5. Strategy D (SHORT_ONLY) wiring: **needs BOTH flags**
- `StrategiesHandler.add_strategy()` raises `ValueError` if `direction is not LONG_ONLY` unless `allow_short_selling AND enable_margin` (SHORT-01/D-07).
- Flags sourced from `PortfolioConfig.trading_rules`: `allow_short_selling: bool`, `enable_margin: bool`, `max_leverage: Decimal` (default 1). Wired through `compose_engine()` into both `StrategiesHandler` and `OrderHandler`.
- D: `direction = SHORT_ONLY`, cheap signal (z-score of a price ratio, NOT cointegration), `sell()`/`sell_stop(price=…)`, fan out to P4/P5/P6.

## 6. Runner wiring — `itrader/trading_system/backtest_trading_system.py`
- Constructor: `BacktestTradingSystem(exchange='binance', start_date=None, end_date='', to_sql=False, timeframe='1d', csv_paths: dict[str,str|Path]|None=None, *, engine=None, runner=None, signal_store=None)`. `csv_paths` maps ticker→CSV path.
- `run(print_summary=True, on_tick: Callable[[system, time_event], None] | None=None)`. **`on_tick` is the hook B's re-price logic uses.**
- Add strategy: `system.strategies_handler.add_strategy(strategy)`. Add portfolio: `system.portfolio_handler.add_portfolio(user_id=…, name=…, exchange='csv', cash=Decimal(...))` → returns portfolio_id. Subscribe: `strategy.subscribe_portfolio(portfolio_id)`.
- Results: `system.get_signal_records()`; `system.portfolio_handler.get_active_portfolios()` → per-portfolio `available_cash()`, `total_equity()`, positions/transactions.
- **VERIFY the short-flag plumbing path the runner must use.** Recon found two surfaces: the legacy `BacktestTradingSystem.__init__` (above) AND `compose_engine()`/`compose.py` reading `PortfolioConfig.trading_rules`. The executor MUST confirm, by reading `backtest_trading_system.py` + `trading_system/compose.py` + `config/`, the exact, working way to construct a backtest system with `allow_short_selling=True`+`enable_margin=True` BEFORE writing Strategy D's runner wiring. Do not guess.

## 7. CSV schema — `itrader/price_handler/store/csv_store.py`
- Expects Binance-kline header incl. `['Open time','Open','High','Low','Close','Volume']` (extra kline cols allowed/discarded). Reads those 6 → renames to `date,open,high,low,close,volume`; index = `pd.to_datetime(...,utc=True)` then tz-convert; cast float64; slice `[start,end]` inclusive.
- **Fetch script must write CSV with at least those 6 named columns**, `Open time` as ms-epoch or ISO that `pd.to_datetime` parses. Match the existing `data/BTCUSD_*` file's exact header (read it) for safety.

## 8. CCXT provider defects (confirmed) — `itrader/price_handler/providers/ccxt_provider.py`
Do NOT reuse `download_data`. Confirmed: `end_date` param ignored (fetches start→now); `resample().ffill()` fabricates flat O=H=L=C bars; unclosed last candle appended; no rate-limit/backoff & uncaught exceptions; output 5-col frame (drops Volume) ≠ CsvPriceStore 6-col input. → write hardened one-shot script: `enableRateLimit=True`+try/except backoff, explicit `since`→`end` bound, dedup by ts, **drop last (unclosed) candle**, **no ffill** (preserve gaps), write exact kline schema.

## Throwaway vs durable
- **Throwaway (do NOT over-engineer, but DO keep the script in repo as a documented one-shot under e.g. `evals/tools/fetch_binance_5m.py`):** the fetch script. Its OUTPUT (the CSVs) is committed.
- **Durable:** everything under `evals/` (strategies A–D, workloads W1 wiring + `synthetic.py`, runners), scalene dev dep.
- **Do NOT touch** `tests/integration/test_backtest_oracle.py` (byte-exact oracle) or the golden `BTCUSD` data.
</content>
</invoke>
