#!/usr/bin/env python
"""Reproducible oracle generator for the SMA_MACD backtest (M1-07).

This committed driver pins every oracle-defining decision so a run is bit-reproducible:

  * D-01  dataset  : data/BTCUSD_1d_ohlcv_2018_2026.csv (the golden CSV feed)
  * D-02  window   : 2018-01-01 -> 2026-06-03 (pinned explicitly below)
  * D-03  params   : SMA_MACD code defaults (short=50/long=100/FAST=6/SLOW=12/WIN=3)
  * D-04  capital  : starting cash $10,000, fees 0, slippage 0
  * D-06  ticker   : BTCUSD on the 1d timeframe
  * D-10  output   : output/trades.csv + output/equity.csv + output/summary.json
  * D-12  fields   : only deterministic fields are serialized (no wall-clock timestamps,
                     no position-id / current-price / unrealised-pnl volatile values)

Queue-only rule: this script constructs the system and reads result state AFTER the run
(``portfolio.closed_positions`` and the metrics snapshots). It never calls handler methods
across domains during the run.

The summary carries the D-15 derived-metrics block (sharpe/sortino/cagr/max_drawdown/
profit_factor/win_rate) computed by ``itrader.reporting.metrics`` — the same formula
source the engine's end-of-run printout uses (D-14 amendment). The trades frame carries
the D-17 slippage-attribution columns. Both are produced every run and freeze into
``tests/golden/`` only at the named D-11 re-freezes (plan 07-07).

Run via ``make backtest`` or ``poetry run python scripts/run_backtest.py``.
"""

import json
import pathlib

from itrader.reporting.frames import (
    EQUITY_COLUMNS,
    TRADE_COLUMNS,
    build_equity_curve,
    build_trade_log,
)
from itrader.reporting.summary import (
    SLIPPAGE_COLUMNS,
    FLOAT_FORMAT,
    attach_slippage,
    build_metrics_block,
    build_summary,
)
from decimal import Decimal

from itrader.core.sizing import FractionOfCash, TradingDirection
from itrader.trading_system.backtest_trading_system import TradingSystem
from itrader.strategy_handler.config import SMA_MACDConfig
from itrader.strategy_handler.strategies.SMA_MACD_strategy import SMA_MACD_strategy
from itrader.logger import get_itrader_logger


# --- Pinned oracle configuration -------------------------------------------

DATASET = "data/BTCUSD_1d_ohlcv_2018_2026.csv"  # D-01
START_DATE = "2018-01-01"                        # D-02
END_DATE = "2026-06-03"                          # D-02
CASH = 10_000                                     # D-04 (fees 0, slippage 0 — exchange defaults)
TICKER = "BTCUSD"                                 # D-06
TIMEFRAME = "1d"                                  # D-06

OUTPUT_DIR = pathlib.Path("output")              # D-10 / D-11 (gitignored)


def main():
    logger = get_itrader_logger().bind(component="OracleRunner")

    # Construct the CSV-fed engine (D-01/D-02). Fees/slippage are exchange defaults (D-04).
    system = TradingSystem(
        exchange="csv",
        start_date=START_DATE,
        end_date=END_DATE,
    )

    # Reference strategy on the daily timeframe, subscribed to BTCUSD (D-03/D-06).
    # D-01: single config-object constructor. The golden sizing literal MUST be
    # FractionOfCash(Decimal("0.95")) (string-path Decimal — byte-exact, Pitfall 1).
    strategy_config = SMA_MACDConfig(
        timeframe=TIMEFRAME,
        tickers=[TICKER],
        sizing_policy=FractionOfCash(Decimal("0.95")),
        direction=TradingDirection.LONG_ONLY,
        allow_increase=False,
    )
    strategy = SMA_MACD_strategy(strategy_config)
    system.strategies_handler.add_strategy(strategy)

    # Single long-only portfolio with $10k starting cash (D-04).
    portfolio_id = system.portfolio_handler.add_portfolio(
        user_id=1,
        name="oracle_pf",
        exchange="csv",
        cash=CASH,
    )
    strategy.subscribe_portfolio(portfolio_id)

    # Run the full PING->BAR->SIGNAL->ORDER->FILL loop. The default
    # print_summary=True prints the engine-level D-15 metrics block at end of
    # run (D-14 amendment) — stdout only, no output/ artifact bytes change.
    system.run()

    # --- Read result state AFTER the run (queue-only rule) ------------------
    portfolio = system.portfolio_handler.get_portfolio(portfolio_id)
    trades = build_trade_log(portfolio)
    equity = build_equity_curve(portfolio)

    # D-17: post-hoc slippage attribution from the store's close series.
    closes = system.store.read_bars(TICKER)["close"]
    trades = attach_slippage(trades, closes)

    summary = build_summary(
        portfolio,
        trades,
        ticker=TICKER,
        timeframe=TIMEFRAME,
        start_date=START_DATE,
        end_date=END_DATE,
        starting_cash=CASH,
    )
    # D-15: nested derived-metrics block — produced every run, frozen at 07-07.
    summary["metrics"] = build_metrics_block(equity, trades)

    # --- Serialize the deterministic oracle (D-10/D-12) --------------------
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    trades[TRADE_COLUMNS + SLIPPAGE_COLUMNS].to_csv(
        OUTPUT_DIR / "trades.csv", index=False, float_format=FLOAT_FORMAT)
    equity[EQUITY_COLUMNS].to_csv(
        OUTPUT_DIR / "equity.csv", index=False, float_format=FLOAT_FORMAT)
    with open(OUTPUT_DIR / "summary.json", "w", encoding="utf-8") as handle:
        json.dump(summary, handle, indent=2, sort_keys=True)

    logger.info(
        "Oracle written",
        trades=len(trades),
        equity_points=len(equity),
        final_equity=summary["final_equity"],
        output_dir=str(OUTPUT_DIR),
    )


if __name__ == "__main__":
    main()
